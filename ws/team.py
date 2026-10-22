"""Previewed Git team links; no publishing or automatic sync."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import quote, urlsplit
from . import core


class ManifestError(core.WsError):
    """The linked team.json cannot be read; `ws sync --pull-only` may still pull a fix."""


def parse_manifest(path, read):
    try: return json.loads(read())
    except (ValueError, OSError) as exc:
        raise ManifestError(f'Team manifest {path} is missing or not valid JSON ({exc}). If you did not edit it, run '
                            f'`git -C {Path(path).parent} checkout -- team.json`, or `ws sync --pull-only` once a teammate has fixed it.') from None


def remote_parts(remote):
    if not isinstance(remote, str) or not remote or not remote.isprintable() or remote.startswith('-'):
        raise core.WsError('Use a local absolute repository path or an SSH/HTTPS remote without credentials.')
    if Path(remote).is_absolute(): return '', ''
    scp = re.fullmatch(r'[\w.-]+@([\w.-]+):([\w./-]+)', remote)
    if scp and '..' not in scp[2].split('/'): return scp[1].lower(), scp[2].removesuffix('.git')
    try:
        parsed = urlsplit(remote); port = parsed.port
    except ValueError:
        raise core.WsError('Remote URL or port is invalid; use an SSH/HTTPS repository URL.')
    if (parsed.scheme not in ('https', 'ssh') or not parsed.hostname or parsed.password or
            parsed.query or parsed.fragment or (parsed.username and
                (parsed.scheme != 'ssh' or not re.fullmatch(r'[\w][\w.-]*', parsed.username)))):
        raise core.WsError('Remote must use SSH/HTTPS without embedded credentials, queries or fragments.')
    slug = parsed.path.strip('/').removesuffix('.git')
    if not slug or '..' in slug.split('/'): raise core.WsError('Remote repository path is invalid.')
    host = parsed.hostname.lower()
    if port and port != (443 if parsed.scheme == 'https' else 22): host += ':' + str(port)
    return host, slug


def privacy(remote, attest=False, verifier=''):
    if verifier not in ('', 'gh', 'glab'): raise core.WsError('Verify with gh or glab only.')
    host, slug = remote_parts(remote)
    tool = verifier or ('gh' if host == 'github.com' else 'glab' if host == 'gitlab.com' else '')
    visibility = ''; method = 'unknown'
    if tool and host and shutil.which(tool) and os.environ.get('WS_OFFLINE') != '1':
        command = ['gh', 'repo', 'view', f'https://{host}/{slug}', '--json', 'visibility'] if tool == 'gh' else [
            'glab', 'api', 'projects/' + quote(slug, safe=''), '--hostname', host, '--method', 'GET']
        try:
            result = subprocess.run(command, capture_output=True, encoding='utf-8', errors='replace', timeout=15)
            if result.returncode == 0: visibility = json.loads(result.stdout).get('visibility', '').lower()
        except (OSError, ValueError, AttributeError, subprocess.TimeoutExpired): pass
        if visibility and visibility != 'private': raise core.WsError('Team remote is not private; linking is blocked.')
        if visibility == 'private': method = tool
    if method == 'unknown':
        if not attest: raise core.WsError('Privacy is unverified. Confirm this remote is private to your team with --attest-private.')
        method = 'attested'
    return {'method': method, 'remote': remote, 'date': core.now()}


def _git(path, *args):
    try:
        return subprocess.run(['git', '-c', 'core.hooksPath=' + os.devnull, '-C', str(path), *args],
                              check=True, capture_output=True, encoding='utf-8', errors='replace', timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        raise core.WsError('Git team operation failed; review the remote and retained local files before retrying.')


def manage(root, action, remote='', apply=False, attest=False, auto_pull=False, verifier='', expected=None):
    metadata = core.inside(root / 'workspace.json', [root]); original = metadata.read_text(encoding='utf-8')
    cfg = json.loads(original); linked = cfg.get('team_workspace')
    if (root / '.ws').is_symlink(): raise core.WsError('Team state must not use a symlink.')
    target = core.inside(root / '.ws/team', [root])
    if action not in ('init', 'link', 'unlink'): raise core.WsError('Use team init, link or unlink.')
    if action != 'unlink': remote_parts(remote)
    elif remote: raise core.WsError('Unlink takes no remote.')
    if linked and not isinstance(linked, dict): raise core.WsError('Invalid team link; review workspace.json.')
    if linked and action != 'unlink':
        if linked.get('remote') != remote: raise core.WsError('Unlink the current team first; a changed remote needs fresh privacy consent.')
        manifest = core.inside(target / 'team.json', [root])
        if not manifest.is_file(): raise core.WsError('Linked team clone is missing; retain the link for recovery or unlink explicitly.')
        return {'already': True, 'path': str(target)}
    plan = {'action': action, 'remote': remote, 'path': str(target), 'sha': core.digest_text(original),
            'changes': ['workspace.json team_workspace', '.ws/team (retained on unlink)'], 'publishes': False,
            'auto_pull': bool(auto_pull), 'privacy': 'attested' if attest else 'verify before clone'}
    if not apply: return plan
    if expected is not None and expected != plan['sha']: raise core.WsError('Workspace changed; preview again.')
    with core.lock(root):
        if metadata.read_text(encoding='utf-8') != original: raise core.WsError('Workspace changed; preview again.')
        if action == 'unlink':
            cfg.pop('team_workspace', None)
        else:
            if target.exists() or target.is_symlink(): raise core.WsError('Team clone already exists; retain or move it before linking.')
            host, _ = remote_parts(remote)
            if host and os.environ.get('WS_OFFLINE') == '1': raise core.WsError('Offline mode: remote cloning is disabled.')
            verified = privacy(remote, attest, verifier)
            with tempfile.TemporaryDirectory(prefix='team-prepare-', dir=root / '.ws') as tmp:
                clone = Path(tmp) / 'clone'
                _git(root, 'clone', '--no-hardlinks', '--', remote, str(clone))
                manifest = core.inside(clone / 'team.json', [clone])
                if action == 'init':
                    if _git(clone, 'ls-remote', 'origin').strip() or manifest.exists(): raise core.WsError('Init needs an empty remote; use link for an existing team.')
                    record = {'kind': 'ai-dev-workspace-team', 'schema_version': 1, 'id': uuid.uuid4().hex}
                    core.atomic_write(manifest, json.dumps(record, indent=2) + '\n')
                else:
                    try: record = json.loads(core.read_text(manifest, [clone]))
                    except (OSError, ValueError): raise core.WsError('Remote has no valid team.json. The host must run `ws team init <repo>` and then `ws sync` once to publish it.')
                    if (not isinstance(record, dict) or record.get('kind') != 'ai-dev-workspace-team' or
                            record.get('schema_version') != 1 or not re.fullmatch(r'[a-f0-9]{32}', str(record.get('id', '')))):
                        raise core.WsError('Remote has no valid team manifest.')
                if metadata.read_text(encoding='utf-8') != original: raise core.WsError('Workspace changed; preview again.')
                core.inside(target, [root])
                if target.exists() or target.is_symlink(): raise core.WsError('Team destination changed; preview again.')
                cfg['team_workspace'] = {'id': record['id'], 'path': '.ws/team', 'remote': remote,
                                         'privacy': verified, 'auto_pull': bool(auto_pull)}
                updated = json.dumps(cfg, indent=2) + '\n'
                try:
                    core.atomic_write(metadata, updated); core.replace_file(clone, target)
                except OSError:
                    if metadata.read_text(encoding='utf-8') == updated: core.atomic_write(metadata, original)
                    raise core.WsError('Team link write failed; configuration preserved. Preview before retrying.')
        if action == 'unlink':
            try: core.atomic_write(metadata, json.dumps(cfg, indent=2) + '\n')
            except OSError: raise core.WsError('Unlink write failed; team clone retained. Preview before retrying.')
    return {**plan, 'applied': True, 'privacy': cfg.get('team_workspace', {}).get('privacy', {}).get('method', ''),
            'bootstrap_pending': action == 'init', 'pulls_active': cfg.get('team_workspace',{}).get('auto_pull') is True}
