"""Owned private checkouts for explicitly requested implementation work."""
import json
import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath
from . import core, orchestration


def git(repo, *args, env_extra=None, binary=False):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0', GIT_LFS_SKIP_SMUDGE='1')
    if env_extra: env.update(env_extra)
    try:
        result = subprocess.run(['git', '-c', 'core.hooksPath=' + os.devnull, '-c', 'core.fsmonitor=false', '-c', 'core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol', '-C', str(repo), *args],
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


def _record(root, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{16}', run_id): raise core.WsError('Invalid worker run ID.')
    directory = Path(root).resolve() / '.ws/workers' / run_id
    for p in (directory.parent.parent, directory.parent, directory, directory / 'checkout', directory / 'source.git'):
        if p.is_symlink(): raise core.WsError('Worker run paths must not be symlinked.')
    state = json.loads((directory / 'run.json').read_text())
    if (state.get('directory') != str(directory) or state.get('checkout') != str(directory / 'checkout')
            or not state.get('complete') or state.get('provider') != 'codex'):
        raise core.WsError('Worker preparation is incomplete or its recorded paths changed.')
    if Path(git(directory / 'checkout', 'rev-parse', '--git-common-dir')).resolve() != directory / 'source.git':
        raise core.WsError('Worker Git metadata moved outside its private run.')
    return directory, state


def _claim(root, state):
    task = core.task_read(root, state['task'], ['Objective'])
    if (task.get('conflicted') or task['meta'].get('status') == 'done' or task['sha'] != state['task_sha']
            or core._claim_defaults(root, state['task'], None, None) != (state['claimed_by'], state['claim_token'])):
        raise core.WsError('Worker task or local claim changed; output retained without acceptance.')


def _profile(directory):
    checkout = directory / 'checkout'; scratch = directory / 'scratch'
    runtime = Path(core.sys.base_prefix).resolve()
    if runtime == Path(runtime.anchor) or runtime == Path.home().resolve() or runtime in Path.home().resolve().parents:
        raise core.WsError('Python runtime root would expose HOME; no worker launched.')
    rules = {':minimal': 'read', str(runtime): 'read',
             str(directory / 'source.git'): 'read', str(scratch): 'write',
             ':workspace_roots': {'.': 'write', '.git': 'read', '.codex': 'read', '.claude': 'read'}}
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
        for p in checkout.rglob('*'):
            if p.is_symlink(): raise core.WsError('Worker introduced a symlink; collection blocked.')
            info = p.stat()
            if not (stat.S_ISREG(info.st_mode) or p.is_dir()): raise core.WsError('Worker introduced a special file; collection blocked before staging.')
            if stat.S_ISREG(info.st_mode) and info.st_size > 1024 * 1024: raise core.WsError('Changed file exceeds the 1 MiB scan limit.')
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
        try: _claim(root, state)
        except core.WsError as error: state.update(blocked=True, reason=str(error))
        if not state['blocked']: state.update(snapshot)
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
        (directory / 'scratch').mkdir(mode=0o700)
        args = ['exec', '--ignore-user-config', '--ignore-rules', '--ephemeral', '--json', '-m', state['model'],
                '-c', 'model_reasoning_effort=' + json.dumps(state['effort']), *_profile(directory),
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
        code, output, tokens_in, tokens_out, known = orchestration.worker_run(binding, checkout, (directory / 'brief.md').read_text(), receipt=receipt)
        state.update(worker_exit=code, output=core.redact(output), usage=dict(input=tokens_in, output=tokens_out, known=known))
    except (OSError, ValueError) as error: state.update(worker_exit=1, output=core.redact(str(error)))
    state['finished_at'] = core.now()
    core.atomic_write(directory / 'run.json', json.dumps(state, indent=2) + '\n')
    result = collect(root, run_id)
    if state['worker_exit'] or not state['checks'] or any(c['exit_code'] != 0 for c in state['checks']):
        state = json.loads((directory / 'run.json').read_text()); state.update(blocked=True, reason=state['reason'] + '; worker failed, checks failed, or command evidence missing.')
        core.atomic_write(directory / 'run.json', json.dumps(state, indent=2) + '\n')
        result = {k: v for k, v in state.items() if k not in ('claim_token', 'claimed_by')}
    return result
