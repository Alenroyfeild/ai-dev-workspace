"""Owned private checkouts for explicitly requested implementation work."""
import json
import hashlib
import os
import re
import stat
import subprocess
import shutil
from pathlib import Path, PurePosixPath, PureWindowsPath
from . import core, orchestration


def git(repo, *args, env_extra=None, binary=False):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0', GIT_LFS_SKIP_SMUDGE='1')
    if env_extra: env.update(env_extra)
    try:
        result = subprocess.run(['git', '-c', 'core.hooksPath=' + os.devnull, '-c', 'core.fsmonitor=false', '-c', 'core.longpaths=true', '-c', 'core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol', '-C', str(repo), *args],
                                env=env, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired): raise core.WsError('Worker Git operation could not complete; no provider was launched.')
    if result.returncode: raise core.WsError('Worker Git operation failed: ' + core.redact(result.stderr[-1000:].decode('utf-8', errors='replace')))
    return result.stdout if binary else result.stdout.decode('utf-8').strip()


def prepare(root, task_id, scope, base='HEAD', apply=False, confirm=None):
    root = Path(root).resolve()
    task = core.task_read(root, task_id, ['Objective', 'Next action', 'Blockers', 'Evidence'])
    meta = task['meta']; worker, token = core._claim_defaults(root, task_id, None, None)
    if task.get('conflicted') or meta.get('status') == 'done' or not token or meta.get('claimed_by') != worker or meta.get('claim_token') != token:
        raise core.WsError('Worker preparation needs a current local task claim; claim the task first.')
    source = Path(meta.get('repo') or '').expanduser().resolve()
    if source not in [p.resolve() for p in core.read_roots(root)[1:]]:
        raise core.WsError('Worker repository must be one declared workspace repo.')
    if Path(git(source, 'rev-parse', '--show-toplevel')).resolve() != source:
        raise core.WsError('Worker repository must be the Git checkout root.')
    if not isinstance(base, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/~^/-]{0,200}', base):
        raise core.WsError('Worker base must name a commit or branch.')
    commit = git(source, 'rev-parse', '--verify', '--end-of-options', base + '^{commit}')
    scope = list(dict.fromkeys(scope or []))
    if not scope: raise core.WsError('Worker needs at least one relative --scope path.')
    for name in scope:
        parts = PurePosixPath(name.replace('\\', '/')).parts
        if not parts or not name.isprintable() or PureWindowsPath(name).anchor or name.startswith('/') or '..' in parts or any(p in ('.git', '.ws', '.codex', '.claude') for p in parts):
            raise core.WsError('Worker scope must stay inside checkout files, away from metadata and client config.')
    scope = [str(PurePosixPath(n.replace('\\', '/'))) for n in scope]
    tree = git(source, 'ls-tree', '-r', commit)
    if re.search(r'^160000 ', tree, re.M): raise core.WsError('Worker v1 refuses submodule dependencies.')
    if re.search(r'^120000 ', tree, re.M): raise core.WsError('Worker v1 refuses tracked symlinks; use a repository without linked dependencies.')
    storage = root / '.ws/workers'
    for path in (root / '.ws', storage):
        if path.is_symlink(): raise core.WsError('Worker storage must not be symlinked.')
    if source == storage or source in storage.parents:
        raise core.WsError('Worker storage must be outside the source repository.')
    run_id = core.uuid.uuid4().hex[:16]; directory = storage / run_id
    binding = orchestration.route(root, 'worker', provider='codex')
    result = dict(id=run_id, task=task_id, state='prepared', source=str(source), base=commit, scope=scope,
                  source_dirty=bool(git(source, 'status', '--porcelain')), provider=binding['provider'], model=binding['model'],
                  available=binding['available'], applied=False, directory=str(directory), checkout=str(directory / 'checkout'),
                  record=str(directory / 'run.json'), brief=str(directory / 'brief.md'),
                  warning='Committed files only; ignored files and uncommitted edits are not copied. No worker is launched.')
    if not apply or confirm is not None and not confirm(result): return result
    for path in (root / '.ws', storage):
        if path.is_symlink(): raise core.WsError('Worker storage changed to a symlink during confirmation.')
    with core.lock(root):
        if core.task_read(root, task_id)['sha'] != task['sha']:
            raise core.WsError('Task changed during preview; review it before preparing again.')
        directory.mkdir(parents=True, mode=0o700)
        state = dict(result, complete=False, claim_token=token, claimed_by=worker, task_sha=task['sha'], effort=binding['effort'])
        core.atomic_write(directory / 'run.json', json.dumps(state, indent=2) + '\n')
    try:
        git(directory, 'init', '--bare', '--template=', str(directory / 'source.git'))
        git(directory / 'source.git', 'fetch', '--depth=1', '--no-tags', '--', str(source), commit)
        git(directory / 'source.git', 'worktree', 'add', '--detach', str(directory / 'checkout'), commit)
        body = '# Implementation task (UNVERIFIED)\nEdit only allowed paths. Do not commit, push, merge or change task memory.\n'
        for section, limit in zip(('Objective', 'Next action', 'Blockers', 'Evidence'), (80, 60, 30, 100)):
            body += '\n## ' + section + '\n' + ' '.join(core.redact(task['sections'][section]).split()[:limit]) + '\n'
        body += '\n## Allowed paths\n' + '\n'.join(scope) + '\n\nReport changed paths, checks actually run and blockers. Lead reviews before acceptance.\n'
        if len(body.split()) > 400: raise core.WsError('Worker brief exceeds 400 words; shorten the scope.')
        core.atomic_write(directory / 'brief.md', body)
        with core.lock(root):
            latest = core.task_read(root, task_id, ['Objective']); current = latest['meta']
            if (current.get('claimed_by'), current.get('claim_token')) != (worker, token) or core._claim_defaults(root, task_id, None, None) != (worker, token) or current.get('status') == 'done':
                raise core.WsError('Task claim changed during preparation; checkout retained for inspection.')
            if latest['sha'] != task['sha']: raise core.WsError('Task changed during preparation; stale brief retained for inspection.')
            state.update(complete=True, applied=True)
            core.atomic_write(directory / 'run.json', json.dumps(state, indent=2) + '\n')
    except core.WsError as error:
        state['reason'] = str(error)
        core.atomic_write(directory / 'run.json', json.dumps(state, indent=2) + '\n')
        raise core.WsError(f'Preparation {run_id} incomplete; inspect {directory}: {error}')
    return dict(result, applied=True)


def launch(root, run_id):
    raise core.WsError('Write workers remain preparation-only until the O2d real-client hostile probe passes.')


def _record(root, run_id, require_checkout=True):
    if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{16}', run_id): raise core.WsError('Invalid worker run ID.')
    directory = Path(root).resolve() / '.ws/workers' / run_id
    for p in (directory.parent.parent, directory.parent, directory, directory / 'checkout', directory / 'source.git', directory / 'run.json', directory / 'diff.patch'):
        if core.is_link(p): raise core.WsError('Worker run paths must not be symlinked.')
    state = json.loads((directory / 'run.json').read_text(encoding='utf-8'))
    if (state.get('id') != run_id or state.get('directory') != str(directory) or state.get('checkout') != str(directory / 'checkout')
            or require_checkout and not state.get('complete') or state.get('provider') != 'codex'):
        raise core.WsError('Worker preparation is incomplete or its recorded paths changed.')
    if require_checkout and Path(git(directory / 'checkout', 'rev-parse', '--git-common-dir')).resolve() != directory / 'source.git':
        raise core.WsError('Worker Git metadata moved outside its private run.')
    return directory, state


def _claim(root, state):
    task = core.task_read(root, state['task'], ['Objective'])
    if (task.get('conflicted') or task['meta'].get('status') == 'done' or task['sha'] != state['task_sha']
            or core._claim_defaults(root, state['task'], None, None) != (state['claimed_by'], state['claim_token'])):
        raise core.WsError('Worker task or local claim changed; output retained without acceptance.')
    return task


def _public(state):
    return {k: v for k, v in state.items() if k not in ('claim_token', 'claimed_by')}


def _snapshot(state):
    fields = ('tree', 'diff_sha', 'checks', 'base', 'source', 'scope', 'task_sha')
    if not all(state.get(k) for k in fields): raise core.WsError('Worker has no checked snapshot to review.')
    return hashlib.sha256(json.dumps({k: state[k] for k in fields}, sort_keys=True).encode()).hexdigest()


def review(root, run_id, approve=False, confirm=None):
    directory, state = _record(root, run_id, require_checkout=False)
    if state['state'] == 'needs-review' and not state.get('blocked'):
        collect(root, run_id); directory, state = _record(root, run_id)
    result = dict(_public(state), applied=False)
    result['diff'] = ''
    if state.get('tree') and state.get('diff_sha'):
        diff = git(directory / 'checkout', 'diff', '--binary', '--no-ext-diff', '--no-textconv', state['base'], state['tree'], binary=True)
        if hashlib.sha256(diff).hexdigest() != state['diff_sha']:
            raise core.WsError('Worker diff changed since collection; collect again')
        result['diff'] = core.redact(diff.decode('utf-8', errors='replace'))
    if state.get('blocked'):
        result['message'] = 'Blocked: start a new run with ws worker prepare'
        if approve: raise core.WsError(result['message'])
    if not approve: return result
    if state['state'] != 'needs-review' or state.get('blocked'): raise core.WsError('Worker is blocked or not ready for review.')
    signature = _snapshot(state)
    if confirm is not None and not confirm(result): return result
    with core.lock(root):
        directory, state = _record(root, run_id); _claim(root, state)
        if state['state'] != 'needs-review' or state.get('blocked') or _snapshot(state) != signature:
            raise core.WsError('Worker changed during review; review again.')
        state['review'] = dict(snapshot=signature, reviewer=state['claimed_by'], reviewed_at=core.now())
        core.atomic_write(directory / 'run.json', json.dumps(state, indent=2) + '\n')
    return dict(_public(state), diff=result['diff'], applied=True)


def _approved(root, run_id):
    directory, state = _record(root, run_id)
    approval = state.get('review')
    if (state['state'] not in ('needs-review', 'accepting') or state.get('blocked')
            or not isinstance(approval, dict) or approval.get('snapshot') != _snapshot(state)
            or approval.get('reviewer') != state['claimed_by']):
        raise core.WsError('Worker needs a current lead review before acceptance.')
    task = _claim(root, state); source = Path(state['source']).resolve()
    if (source != Path(task['meta'].get('repo') or '').expanduser().resolve() or source not in [p.resolve() for p in core.read_roots(root)[1:]]
            or Path(git(source, 'rev-parse', '--show-toplevel')).resolve() != source):
        raise core.WsError('Worker source repository changed.')
    return directory, state, source


def _later_edits(directory, state):
    checkout = directory / 'checkout'; expected = {}
    for entry in git(checkout, 'ls-tree', '-r', '-z', state['tree']).split('\0'):
        if entry:
            metadata, name = entry.split('\t', 1); mode, _, blob = metadata.split(); expected[name] = (mode, blob)
    names = set(filter(None, git(checkout, 'ls-files', '--cached', '--others', '-z').split('\0')))
    if names != set(expected): return True
    # Hash with line-ending conversion on (a CRLF checkout via .gitattributes eol=crlf or autocrlf); skip it when a filter driver could run code.
    plain = ['--no-filters'] if any(k.lower().startswith('filter.') for k in git(checkout, 'config', '--includes', '--name-only', '--list').splitlines()) else []
    for name, (mode, blob) in expected.items():
        path = checkout / name
        if (path.is_symlink() or not path.is_file() or git(checkout, 'hash-object', *plain, '--', name) != blob
                or os.name != 'nt' and bool(path.stat().st_mode & 0o111) != (mode == '100755')): return True
    return False


def accept(root, run_id, apply=False, confirm=None):
    directory, state, source = _approved(root, run_id)
    branch = 'ws/worker/' + run_id; ref = 'refs/heads/' + branch
    def existing():
        ref_path = source / git(source, 'rev-parse', '--git-path', ref)
        target = git(source, 'for-each-ref', '--format=%(objectname) %(symref)', ref)
        present = ref_path.exists() or ref_path.is_symlink() or bool(target)
        if present and (state['state'] != 'accepting' or target != state.get('commit') or ref_path.is_symlink()):
            raise core.WsError('Worker branch already exists at a different or unowned commit.')
        return present
    existing()
    result = dict(_public(state), branch=branch, snapshot=_snapshot(state), applied=False)
    if _later_edits(directory, state): result['warning'] = 'later edits in the worker checkout are not included'
    if not apply or confirm is not None and not confirm(result): return result
    if state['state'] != 'accepting': collect(root, run_id)
    with core.lock(root):
        directory, state, source = _approved(root, run_id)
        if _snapshot(state) != result['snapshot']: raise core.WsError('Worker changed during acceptance; review again.')
        if _later_edits(directory, state): result['warning'] = 'later edits in the worker checkout are not included'
        identity = {key: value for role in ('AUTHOR', 'COMMITTER') for key, value in
                    ((f'GIT_{role}_NAME', 'ai-dev-workspace'), (f'GIT_{role}_EMAIL', 'worker@workspace.invalid'))}
        if state['state'] == 'accepting':
            commit = state.get('commit', '')
            if (state.get('branch') != branch or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', commit)
                    or git(directory / 'source.git', 'show', '-s', '--format=%T %P', commit) != state['tree'] + ' ' + state['base']):
                raise core.WsError('Pending acceptance receipt does not match the reviewed commit.')
        else:
            commit = git(directory / 'source.git', 'commit-tree', state['tree'], '-p', state['base'], '-m', 'Reviewed worker ' + run_id, env_extra=identity)
        git(source, 'fetch', '--no-tags', '--no-write-fetch-head', '--no-recurse-submodules', '--no-auto-maintenance', '--', str(directory / 'source.git'), commit)
        if state['state'] != 'accepting':
            state.update(state='accepting', branch=branch, commit=commit)
            core.atomic_write(directory / 'run.json', json.dumps(state, indent=2) + '\n')
        if not existing(): git(source, 'update-ref', '--no-deref', '-m', 'Accept worker ' + run_id, ref, commit, '0' * len(commit))
        state.update(state='accepted', branch=branch, commit=commit, accepted_at=core.now())
        core.atomic_write(directory / 'run.json', json.dumps(state, indent=2) + '\n')
    return dict(_public(state), warning=result.get('warning', ''), applied=True)


def discard(root, run_id, apply=False, confirm=None):
    directory, state = _record(root, run_id, require_checkout=False)
    if state['state'] in ('running', 'accepting', 'accepted'): raise core.WsError('Running, accepting or accepted workers cannot be discarded.')
    names = ('checkout', 'source.git', 'scratch', 'brief.md', 'diff.patch', 'collection.index', 'collection.index.lock', 'worker.config.toml')
    result = dict(_public(state), paths=[str(directory / n) for n in names], applied=False)
    if state['state'] == 'discarded' or not apply or confirm is not None and not confirm(result): return result
    with core.lock(root):
        directory, state = _record(root, run_id, require_checkout=False)
        if state['state'] in ('running', 'accepting', 'accepted'): raise core.WsError('Worker state changed; discard refused.')
        def readonly_retry(function, filename, error):
            paths = (Path(filename), Path(filename).parent)
            if (not isinstance(error[1], PermissionError) or any(path.is_symlink() or path.resolve() != path.absolute()
                    or not path.resolve().is_relative_to(directory) for path in paths)):
                raise error[1]
            for path in paths: os.chmod(str(path), path.stat().st_mode | stat.S_IWRITE)
            function(filename)
        for name in names:
            path = directory / name
            if path.is_symlink() or path.is_file(): path.unlink()
            elif path.is_dir(): shutil.rmtree(path, onerror=readonly_retry)
        for key in ('tree', 'diff_sha', 'checks', 'review', 'output'): state.pop(key, None)
        state.update(state='discarded', discarded_at=core.now())
        core.atomic_write(directory / 'run.json', json.dumps(state, indent=2) + '\n')
    return dict(_public(state), applied=True)


def _profile(directory, executable=None):
    checkout = directory / 'checkout'; scratch = directory / 'scratch'
    runtime = Path(core.sys.base_prefix).resolve()
    if runtime == Path(runtime.anchor) or runtime == Path.home().resolve() or runtime in Path.home().resolve().parents:
        raise core.WsError('Python runtime root would expose HOME; no worker launched.')
    rules = {':minimal': 'read', str(runtime): 'read',
             str(directory / 'source.git'): 'read', str(scratch): 'write',
             ':workspace_roots': {'.': 'write', '.git': 'read', '.codex': 'read', '.claude': 'read'}}
    if executable:
        executable = Path(executable).resolve(); rules[str(executable)] = 'read'
        package = executable.parent.parent; home = Path.home().resolve()
        try: metadata = json.loads((package / 'codex-package.json').read_text(encoding='utf-8'))
        except (OSError, ValueError): metadata = {}
        protected = (home, home / '.codex', home / '.local', home / '.local/bin', *home.parents)
        install = home / '.codex/packages/standalone/releases'
        if (install == install.resolve() and package.parent == install and package not in protected
                and isinstance(metadata, dict) and metadata.get('layoutVersion') == 1 and metadata.get('variant') == 'codex'
                and metadata.get('entrypoint') == 'bin/codex' and (package / 'bin/codex').resolve() == executable):
            rules[str(package)] = 'read'
    def value(v):
        if isinstance(v, dict): return '{' + ', '.join(json.dumps(k, ensure_ascii=False) + ' = ' + value(x) for k, x in v.items()) + '}'
        return 'false' if v is False else json.dumps(v, ensure_ascii=False)
    profile = value({'filesystem': rules, 'network': {'enabled': False}})
    shell = {'PATH': os.environ.get('PATH', ''), 'HOME': str(scratch), 'TMPDIR': str(scratch),
             'TMP': str(scratch), 'TEMP': str(scratch), 'GIT_OPTIONAL_LOCKS': '0', 'PYTHONNOUSERSITE': '1'}
    settings = ['shell_environment_policy.inherit="none"', 'shell_environment_policy.set=' + value(shell), 'default_permissions="worker-private"', 'permissions.worker-private=' + profile,
                'approval_policy="never"', 'web_search="disabled"', 'projects.' + json.dumps(str(checkout), ensure_ascii=False) + '.trust_level="untrusted"']
    core.atomic_write(directory / 'worker.config.toml', '\n'.join(settings) + '\n')
    return [arg for setting in settings for arg in ('-c', setting)]


def collect(root, run_id):
    """Lead-side snapshot; no approval or source-repo changes."""
    directory, state = _record(root, run_id); checkout = directory / 'checkout'
    if state.get('blocked'): raise core.WsError('Blocked: start a new run with ws worker prepare')
    if state['state'] in ('accepting', 'accepted', 'discarded'): raise core.WsError('Accepting or terminal worker runs cannot be collected again.')
    reasons = []; changed = []; secrets = []; binary = []; snapshot = {}
    checks = state.pop('checks', None)
    for field in ('tree', 'diff_sha'): state.pop(field, None)
    try:
        _claim(root, state)
        if (not state.get('started_at') or not state.get('finished_at') or state.get('worker_exit') != 0
                or not isinstance(checks, list) or not checks
                or any(not isinstance(check, dict) or check.get('exit_code') != 0 for check in checks)):
            raise core.WsError('Collection requires a completed worker run and successful command evidence.')
        if git(checkout, 'rev-parse', 'HEAD') != state['base']: raise core.WsError('Worker changed its pinned Git base.')
        base_blobs = {}
        for entry in git(checkout, 'ls-tree', '-r', '-z', state['base']).split('\0'):
            if entry:
                spec, name = entry.split('\t', 1); base_blobs[name] = spec.split()[2]
        for p in checkout.rglob('*'):
            if core.is_link(p): raise core.WsError('Worker introduced a symlink; collection blocked.')
            info = p.stat()
            if not (stat.S_ISREG(info.st_mode) or p.is_dir()): raise core.WsError('Worker introduced a special file; collection blocked before staging.')
            if stat.S_ISREG(info.st_mode) and info.st_size > 1024 * 1024:
                name = p.relative_to(checkout).as_posix()
                if name not in base_blobs or git(checkout, 'hash-object', '--no-filters', '--', name) != base_blobs[name]:
                    raise core.WsError('Changed file exceeds the 1 MiB scan limit.')
        if any(key.lower().startswith('filter.') for key in git(checkout, 'config', '--includes', '--name-only', '--list').splitlines()):
            raise core.WsError('filter driver configured')
        index = directory / 'collection.index'; index.unlink(missing_ok=True)
        extra = {'GIT_INDEX_FILE': str(index)}
        git(checkout, 'read-tree', state['base'], env_extra=extra)
        git(checkout, 'add', '-A', '-f', '--', '.', env_extra=extra)
        changed = git(checkout, 'diff', '--cached', '--name-only', '--no-renames', '-z', state['base'], '--', env_extra=extra, binary=True).decode('utf-8').split('\0')
        changed = [n for n in changed if n]
        tree = git(checkout, 'write-tree', env_extra=extra); blobs = {}
        for entry in git(checkout, 'ls-tree', '-r', '-z', tree).split('\0'):
            if entry:
                spec, name = entry.split('\t', 1); mode, _, oid = spec.split(); blobs[name] = (mode, oid)
        for name in changed:
            if not any(name == p or name.startswith(p.rstrip('/') + '/') for p in state['scope']): reasons.append('Outside scope: ' + name)
            if any(p.lower() in ('.git', '.ws', '.codex', '.claude') for p in PurePosixPath(name).parts): reasons.append('Protected metadata: ' + name)
            if name in blobs:
                mode, oid = blobs[name]
                if mode not in ('100644', '100755'): raise core.WsError('Snapshot contains a linked or special file; collection blocked.')
                if int(git(checkout, 'cat-file', '-s', oid)) > 1024 * 1024: raise core.WsError('Changed file exceeds the 1 MiB scan limit.')
                data = git(checkout, 'cat-file', 'blob', oid, binary=True)
                try: text = data.decode('utf-8')
                except UnicodeError: binary.append(name); continue
                if '\0' in text: binary.append(name)
                if core.redact(text) != text: secrets.append(name)
        if secrets: reasons.append('Secret scan flagged changed files.')
        if binary: reasons.append('Binary changed files cannot be secret-scanned in v1.')
        state.update(changed=changed, secret_files=secrets, binary_files=binary)
        diff = git(checkout, 'diff', '--cached', '--binary', '--no-ext-diff', '--no-textconv', state['base'], '--', env_extra=extra, binary=True)
        if len(diff) > 2 * 1024 * 1024: raise core.WsError('Worker diff exceeds the 2 MiB review limit.')
        core.atomic_write(directory / 'diff.patch', core.redact(diff.decode('utf-8', errors='replace')).encode('utf-8'))
        snapshot = dict(tree=tree, diff_sha=hashlib.sha256(diff).hexdigest(), checks=checks)
        try: git(checkout, 'diff', '--cached', '--check', state['base'], '--', env_extra=extra)
        except core.WsError: raise core.WsError('Worker diff whitespace check failed.')
    except (core.WsError, OSError, UnicodeError) as error: reasons.append(core.redact(str(error)))
    state.update(state='needs-review', changed=changed, blocked=bool(reasons), reason='; '.join(reasons))
    with core.lock(root):
        _, latest = _record(root, run_id, require_checkout=False)
        if latest['state'] in ('accepting', 'accepted', 'discarded') or latest.get('blocked'):
            raise core.WsError('Worker state changed during collection; output retained.')
        try: _claim(root, state)
        except core.WsError as error: state.update(blocked=True, reason=str(error))
        if not state['blocked']: state.update(snapshot)
        if state.get('review') and (state['blocked'] or state['review'].get('snapshot') != _snapshot(state)):
            state.pop('review', None)
        core.atomic_write(directory / 'run.json', json.dumps(state, indent=2) + '\n')
    return {k: v for k, v in state.items() if k not in ('claim_token', 'claimed_by')}


def _launch(root, run_id):
    """Internal probe path only; public launch stays gated until O2d."""
    directory, state = _record(root, run_id); checkout = directory / 'checkout'
    with core.lock(root):
        _claim(root, state)
        if state['state'] != 'prepared': raise core.WsError('Worker run is not prepared.')
        if git(checkout, 'status', '--porcelain') or git(checkout, 'rev-parse', 'HEAD') != state['base']:
            raise core.WsError('Prepared checkout changed; prepare a new run.')
        binding = orchestration.route(root, 'worker', provider='codex')
        if not binding['available'] or binding['model'] != state['model']: raise core.WsError('Prepared Codex model is unavailable or changed; no fallback.')
        executable = shutil.which(binding['executable'])
        if executable: binding = dict(binding, executable=str(Path(executable).resolve()))
        (directory / 'scratch').mkdir(mode=0o700)
        args = ['exec', '--ignore-user-config', '--ignore-rules', '--ephemeral', '--json', '-m', state['model'],
                '-c', 'model_reasoning_effort=' + json.dumps(state['effort']), *_profile(directory, executable),
                '--disable', 'hooks', '--disable', 'apps', '--disable', 'plugins', '-C', str(checkout), '-']
        binding = dict(binding, headless=args)
        state.update(state='running', checks=[], started_at=core.now())
        core.atomic_write(directory / 'run.json', json.dumps(state, indent=2) + '\n')
    def receipt(stdout):
        for line in stdout.splitlines():
            try: event = json.loads(line)
            except ValueError: continue
            if not isinstance(event, dict): continue
            item = event.get('item', {})
            if event.get('type') == 'item.completed' and isinstance(item, dict) and item.get('type') == 'command_execution':
                state['checks'].append(dict(command=core.redact(str(item.get('command', '')))[:1000], exit_code=item.get('exit_code')))
    try:
        code, output, tokens_in, tokens_out, known = orchestration.worker_run(binding, checkout, (directory / 'brief.md').read_text(encoding='utf-8'), receipt=receipt)
        state.update(worker_exit=code, output=core.redact(output), usage=dict(input=tokens_in, output=tokens_out, known=known))
    except (OSError, ValueError) as error: state.update(worker_exit=1, output=core.redact(str(error)))
    state['finished_at'] = core.now()
    core.atomic_write(directory / 'run.json', json.dumps(state, indent=2) + '\n')
    result = collect(root, run_id)
    if state['worker_exit'] or not state['checks'] or any(c['exit_code'] != 0 for c in state['checks']):
        state = json.loads((directory / 'run.json').read_text(encoding='utf-8')); state.update(blocked=True, reason=state['reason'] + '; worker failed, checks failed, or command evidence missing.')
        core.atomic_write(directory / 'run.json', json.dumps(state, indent=2) + '\n')
        result = {k: v for k, v in state.items() if k not in ('claim_token', 'claimed_by')}
    return result
