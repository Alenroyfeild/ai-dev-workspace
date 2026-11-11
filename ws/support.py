"""Local support and feedback release evidence."""
from datetime import datetime
import os
import re


_RELEASE_TAG = re.compile(r'v?[0-9]{1,8}(?:\.[0-9]{1,8}){2}(?:-[A-Za-z][A-Za-z0-9.]{0,25})?')
_REPOSITORY = re.compile(r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}')
_RELEASE_PAGE_SIZE = 30
_RELEASE_PAGE_LIMIT = 10


def _github_time(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', value):
        raise ValueError('Invalid GitHub timestamp')
    return datetime.fromisoformat(value[:-1] + '+00:00')


def release_mention(repository, number, closed_at, fetch):
    """Return the earliest published release whose notes cite the issue, if coverage is complete."""
    if (os.environ.get('WS_OFFLINE') == '1' or not _REPOSITORY.fullmatch(repository)
            or any(part in ('.', '..') for part in repository.split('/'))
            or type(number) is not int or not 0 < number <= 999999999):
        return None
    repo = re.escape(repository)
    reference = re.compile(
        rf'(?<![\w./#-])(?:https://github\.com/{repo}/issues/|(?:{repo})?#){number}(?![\w/#-])',
        re.IGNORECASE,
    )
    previous = None
    earliest = None
    try:
        closure = _github_time(closed_at)
        for page in range(1, _RELEASE_PAGE_LIMIT + 1):
            releases = fetch(
                f'https://api.github.com/repos/{repository}/releases?per_page={_RELEASE_PAGE_SIZE}&page={page}'
            )
            if not isinstance(releases, list) or len(releases) > _RELEASE_PAGE_SIZE:
                return None
            boundary = False
            for release in releases:
                if not isinstance(release, dict) or type(release.get('draft')) is not bool:
                    return None
                if release['draft']:
                    continue
                published = _github_time(release.get('published_at'))
                if previous is not None and published > previous:
                    return None
                previous = published
                if published <= closure:
                    boundary = True
                    continue
                tag, body = release.get('tag_name'), release.get('body')
                if not isinstance(tag, str) or not _RELEASE_TAG.fullmatch(tag):
                    return None
                if body is not None and not isinstance(body, str):
                    return None
                if body and reference.search(body):
                    earliest = {
                        'version': tag.removeprefix('v'),
                        'url': f'https://github.com/{repository}/releases/tag/{tag}',
                    }
            if len(releases) < _RELEASE_PAGE_SIZE:
                return earliest
            if boundary:
                # GitHub does not promise publication order for unobserved pages.
                return None
    except (OSError, ValueError, RecursionError):
        return None
    return None


# These are version stamps, not arbitrary strings from local metadata.
_VERSION = re.compile(r'[0-9]{1,8}(?:\.[0-9]{1,8}){2}(?:-(?:alpha|beta|rc)\.[0-9]{1,8})?')
_CLIENTS = ('claude', 'codex', 'cursor', 'vscode', 'gemini', 'antigravity')
_FINDINGS = ('conflicted', 'stale_hooks', 'skill_duplicates', 'claude_plugin_missing',
             'claude_plugin_duplicates', 'codex_manual_pending')


def _version(value):
    return value if isinstance(value, str) and _VERSION.fullmatch(value) else None


def _managed_blocks(root):
    from . import core, upgrade

    expected = [('AGENTS.md', 'workspace', 'rules', 'rules')]
    expected += [(path, 'claude' if path.startswith('.claude/') else 'codex', 'skills',
                  'skill-' + path.split('/')[-2]) for path in upgrade.skills()]
    expected += [('.github/copilot-instructions.md', 'copilot', 'instructions', 'copilot-instructions'),
                 ('GEMINI.md', 'gemini', 'instructions', 'gemini-instructions')]
    counts = {}
    versions = set()
    incomplete = False
    for relative, client, kind, marker in expected:
        group = counts.setdefault(client, {})
        count = group.setdefault(kind, 0)
        path = root / relative
        try:
            text = core.read_text(path, [root], errors='strict') if path.exists() else ''
        except (core.WsError, OSError, ValueError):
            group[kind] = None
            incomplete = True
            continue
        stamps = list(re.finditer(rf'^<!--ws:managed:{re.escape(marker)}:([^\n]+)-->$', text, re.MULTILINE))
        ends = list(re.finditer(rf'^<!--/ws:managed:{re.escape(marker)}-->$', text, re.MULTILINE))
        if len(stamps) != 1 or len(ends) != 1 or stamps[0].end() >= ends[0].start():
            if count is not None:
                group[kind] = count + 1
            incomplete = True
        else:
            stamp = _version(stamps[0][1])
            if stamp:
                versions.add(stamp)
            else:
                incomplete = True
    return counts, versions, incomplete


def snapshot(start=None):
    """Read-only doctor summary with an allowlist of counts, labels and version stamps."""
    from . import core, repo

    card = {
        'status': 'unable_to_inspect',
        'installation': 'package' if core.PACKAGED else 'checkout',
        'versions': {'cli': _version(core.kit_meta().get('version')), 'workspace_template': None,
                     'workspace_kit_stamp': None, 'repo_wiring_kit_stamps': None},
        'counts': {'packs': None, 'configured_clients': None, 'pending_proposals': None,
                   'missing_managed_blocks': None, 'repo_wiring_stamps_unknown': None,
                   'doctor_findings': dict.fromkeys(_FINDINGS)},
        'client_check': 'configuration_only',
        'half_migrated': {'detected': None, 'evidence': 'insufficient_evidence'},
    }
    try:
        root = core.find_root(start)
        cfg = core.config(root)
        report = core.doctor(root)
        linked = core.read_roots(root)[1:]
        counts, marker_stamps, incomplete_markers = _managed_blocks(root)
        proposed = {
            re.sub(r'\.ws-new(?:\.[0-9]+)?$', '', path.relative_to(root).as_posix())
            for path in root.rglob('*.ws-new*')
            if re.search(r'\.ws-new(?:\.[0-9]+)?$', path.name) and path.is_file()
        }
    except (core.WsError, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return card, 2

    repo_stamps = []
    for checkout in linked:
        try:
            state = repo.load(checkout)
            repo_stamps.append(_version(state.get('kit_version')) if state.get('workspace') == str(root) else None)
        except (core.WsError, OSError, ValueError, RecursionError):
            repo_stamps.append(None)
    workspace_stamp = _version(cfg.get('kit_version'))
    card['versions']['workspace_kit_stamp'] = workspace_stamp
    card['versions']['repo_wiring_kit_stamps'] = sorted({v for v in repo_stamps if v is not None})
    card['counts']['repo_wiring_stamps_unknown'] = repo_stamps.count(None)
    packs = cfg.get('packs')
    card['counts']['packs'] = len(packs) if isinstance(packs, list) else None
    clients = report.get('configured_clients')
    if isinstance(clients, dict):
        card['counts']['configured_clients'] = sum(clients.get(name) is True for name in _CLIENTS)
    findings = card['counts']['doctor_findings']
    for key in findings:
        value = report.get(key)
        if isinstance(value, list):
            findings[key] = len(value)
        elif type(value) is bool:
            findings[key] = int(value)
    pending = cfg.get('upgrade_pending')
    if isinstance(pending, list):
        proposed.update(name for name in pending if isinstance(name, str))
    card['counts']['pending_proposals'] = len(proposed) if proposed or isinstance(pending, list) else None
    card['counts']['missing_managed_blocks'] = counts

    migration = card['half_migrated']
    stamps = marker_stamps.union(v for v in [workspace_stamp, *repo_stamps] if v is not None)
    if proposed:
        migration.update(detected=True, evidence='pending_proposals')
    elif len(stamps) > 1:
        migration.update(detected=True, evidence='split_version_stamps')
    elif (workspace_stamp and not incomplete_markers and None not in repo_stamps
          and isinstance(pending, list)):
        migration.update(detected=False, evidence='consistent_version_stamps')

    dependencies = report.get('core', {})
    healthy = (
        report.get('valid') is True
        and dependencies.get('git') is True
        and dependencies.get('python3') is True
        and bool(card['counts']['configured_clients'])
        and not report.get('upgrade_due')
        and not any(findings.values())
        and migration['detected'] is False
    )
    card['status'] = 'healthy' if healthy else 'attention'
    return card, 0 if healthy else 1
