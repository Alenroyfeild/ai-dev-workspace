"""Local support and feedback release evidence."""
from datetime import datetime
import json
import os
import re
import time


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


_ISSUE_URL = re.compile(r'https://github\.com/([A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100})/issues/([1-9][0-9]{0,8})')
_LOGIN = re.compile(r'[A-Za-z0-9-]{1,39}(?:\[bot\])?')
_COMMIT_SHA = re.compile(r'[a-fA-F0-9]{40}')


def _issue_match(url):
    match = _ISSUE_URL.fullmatch(url) if isinstance(url, str) else None
    if match and all(part not in ('.', '..') for part in match[1].split('/')):
        return match
    return None


def _read_closures(root, path):
    from . import core

    try:
        core.inside(path, [root])
        raw = json.loads(core.read_text(path, [root], errors='strict'))
        if raw.get('version') != 1 or not isinstance(raw.get('issues'), dict):
            return {}
    except (core.WsError, ValueError, AttributeError, RecursionError):
        return {}
    records = {}
    for url, record in raw['issues'].items():
        match = _issue_match(url)
        if not match or not isinstance(record, dict):
            continue
        state, observed = record.get('state'), record.get('observed_at')
        if state not in ('open', 'closed') or type(observed) is not int or observed <= 0:
            continue
        entry = {'state': state, 'observed_at': observed}
        if state == 'closed':
            closed_at = record.get('closed_at')
            if closed_at is not None:
                try:
                    _github_time(closed_at)
                except ValueError:
                    continue
            evidence = _validated_evidence(record, match[1])
            if evidence is None or not 0 < evidence['checked_at'] <= observed:
                continue
            entry.update(evidence, closed_at=closed_at)
        records[url] = entry
    return records


def _fetch_data(fetch, url):
    from . import core

    try:
        return fetch(url)
    except (OSError, ValueError, core.WsError, RecursionError):
        return None


def _closing_event(fetch, endpoint, repository, closed_at):
    # A truncated or ambiguous timeline cannot identify the event for this closure.
    events = _fetch_data(fetch, endpoint + '/timeline?per_page=100')
    if not isinstance(events, list) or len(events) >= 100:
        return None, None
    matches = [event for event in events if isinstance(event, dict)
               and event.get('event') == 'closed' and event.get('created_at') == closed_at]
    if len(matches) != 1:
        return None, None
    event = matches[0]
    actor = event.get('actor')
    login = actor.get('login') if isinstance(actor, dict) else None
    actor_login = login if isinstance(login, str) and _LOGIN.fullmatch(login) else None
    commit = event.get('commit_id')
    reference = None
    if (isinstance(commit, str) and _COMMIT_SHA.fullmatch(commit)
            and event.get('commit_url') == f'https://api.github.com/repos/{repository}/commits/{commit}'):
        reference = f'https://github.com/{repository}/commit/{commit}'
    return actor_login, reference


def _validated_evidence(record, repository):
    checked = record.get('checked_at')
    if type(checked) is not int:
        return None
    actor = record.get('closing_actor')
    if actor is not None and (not isinstance(actor, str) or not _LOGIN.fullmatch(actor)):
        return None
    reference = record.get('closing_reference')
    if reference is not None and (not isinstance(reference, str) or not re.fullmatch(
            rf'https://github\.com/{re.escape(repository)}/commit/[a-fA-F0-9]{{40}}', reference)):
        return None
    release = record.get('release')
    if release is not None:
        if not isinstance(release, dict) or not isinstance(release.get('url'), str):
            return None
        match = re.fullmatch(rf'https://github\.com/{re.escape(repository)}/releases/tag/(.+)', release['url'])
        if not match or not _RELEASE_TAG.fullmatch(match[1]) or release.get('version') != match[1].removeprefix('v'):
            return None
        release = {'url': release['url'], 'version': release['version']}
    return {'checked_at': checked, 'closing_actor': actor, 'closing_reference': reference, 'release': release}


def sync_feedback(root, fetch=None):
    """Refresh linked issues and save closure evidence with the workspace lock."""
    from . import core

    empty = {'closed': [], 'reopened': [], 'closures': {}, 'release_mentions': [], 'unknown': []}
    if os.environ.get('WS_OFFLINE') == '1':
        return dict(core._offline('feedback sync'), **empty)
    try:
        return _sync_feedback(root, fetch or core._get_json)
    except (core.WsError, OSError, ValueError, RecursionError):
        return dict(empty, status='unknown')


def _sync_feedback(root, fetch):
    from . import core

    result = {'closed': [], 'reopened': [], 'closures': {}, 'release_mentions': [], 'unknown': []}
    path = root / '.ws' / 'feedback-closures.json'
    with core.lock(root):
        core.inside(path, [root])
        observed_at = time.time_ns()
        old = _read_closures(root, path)
        urls = dict.fromkeys(item['issue'] for item in core.feedback_items(root) if _issue_match(item['issue']))
    interval = core.kit_meta().get('update_check_hours', 24) * 3600 * 10**9
    updates = {}
    for url in urls:
        issue = _issue_match(url)
        repository, number = issue.groups()
        endpoint = f'https://api.github.com/repos/{repository}/issues/{number}'
        data = _fetch_data(fetch, endpoint)
        if not isinstance(data, dict) or data.get('state') not in ('open', 'closed'):
            result['unknown'].append(url)
            continue
        state = data['state']
        record = {'state': state, 'observed_at': observed_at}
        if state == 'closed':
            closed_at = data.get('closed_at')
            try:
                _github_time(closed_at)
            except ValueError:
                closed_at = None
            cached = old.get(url, {})
            if (cached.get('state') == 'closed' and cached.get('closed_at') == closed_at
                    and 0 <= observed_at - cached['checked_at'] < interval):
                evidence = _validated_evidence(cached, repository)
            else:
                actor, reference = _closing_event(fetch, endpoint, repository, closed_at) if closed_at else (None, None)
                evidence = {
                    'checked_at': observed_at, 'closing_actor': actor, 'closing_reference': reference,
                    'release': release_mention(repository, int(number), closed_at,
                                               lambda release_url: _fetch_data(fetch, release_url)) if closed_at else None,
                }
            record.update(evidence, closed_at=closed_at)
        updates[url] = record

    if not updates:
        return result
    with core.lock(root):
        core.inside(path, [root])
        current = _read_closures(root, path)
        feedback, lines = core._feedback_lines(root, exact=True)
        items = core.feedback_items(root)
        active = {item['issue'] for item in items if _issue_match(item['issue'])}
        current = {url: record for url, record in current.items() if url in active}
        accepted = set()
        for url, record in updates.items():
            if url not in active:
                continue
            existing = current.get(url, {})
            if existing.get('observed_at', 0) > observed_at:
                continue
            current[url] = record
            accepted.add(url)
            if record['state'] == 'closed':
                release = record['release']
                result['closures'][url] = {'closed_at': record['closed_at'], 'release': release}
                if release and release != existing.get('release'):
                    result['release_mentions'].append(url)
        if not accepted:
            return result
        changed = False
        for item in items:
            url = item['issue']
            if url not in accepted:
                continue
            done = current[url]['state'] == 'closed'
            if done != item['done']:
                lines[item['line']] = ('- [x]' if done else '- [ ]') + lines[item['line']][5:]
                bucket = result['closed' if done else 'reopened']
                if url not in bucket:
                    bucket.append(url)
                changed = True
        core.atomic_write(path, json.dumps({'version': 1, 'issues': current}, indent=2) + '\n')
        if changed:
            core.atomic_write(feedback, '\n'.join(lines) + '\n')
    return result


def attachment_preview(title, body, card):
    """Build the exact issue payload and digest from the local support card."""
    from . import core

    encoded_card = json.dumps(card, indent=2, sort_keys=True, ensure_ascii=False)
    attached = body + '\n\n### Support snapshot\n\n```json\n' + encoded_card + '\n```\n'
    exact = json.dumps([title, attached], ensure_ascii=False, separators=(',', ':'))
    return {'title': title, 'body': attached, 'support': card, 'preview_sha': core.digest_text(exact)}


def feedback_notice(url, release):
    """Show release-note evidence and the update path for this installation."""
    from . import core

    issue = _issue_match(url)
    if not issue:
        return None
    message = f'Issue #{issue[2]} closed, release not confirmed.'
    if release:
        version = release['version']
        message = f'Issue #{issue[2]} closed. Release {version} notes mention it ({release["url"]}).'
        if core._vtuple(version) > core._vtuple(core.kit_meta()['version']):
            if core.PACKAGED:
                message += (' For pipx, run `pipx upgrade ai-dev-workspace`. '
                            'For a venv, reinstall from the original source with its pip. '
                            'Then use `ws upgrade --yes` to apply workspace updates.')
            else:
                message += ' Run `ws update`, then `ws upgrade --yes` to apply workspace updates.'
    return {'kind': 'fixed', 'message': message, 'suggest': 'ws update --check'}
