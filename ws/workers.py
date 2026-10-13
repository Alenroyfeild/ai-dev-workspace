"""Owned private checkouts for explicitly requested implementation work."""
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath
from . import core, orchestration


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0', GIT_LFS_SKIP_SMUDGE='1')
    try:
        result = subprocess.run(['git', '-c', 'core.hooksPath=', '-c', 'core.fsmonitor=false', '-C', str(repo), *args],
                                env=env, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired): raise core.WsError('Worker Git operation could not complete; no provider was launched.')
    if result.returncode: raise core.WsError('Worker Git operation failed: ' + core.redact(result.stderr[-1000:]))
    return result.stdout.strip()


def prepare(root, task_id, scope, base='HEAD', apply=False, confirm=None):
    root = Path(root).resolve()
    task = core.task_read(root, task_id, ['Objective', 'Next action', 'Blockers', 'Evidence'])
    meta = task['meta']; worker, token = core._claim_defaults(root, task_id, None, None)
    if task.get('conflicted') or meta.get('status') == 'done' or not token or meta.get('claimed_by') != worker or meta.get('claim_token') != token:
        raise core.WsError('Worker preparation needs a current local task claim; claim the task first.')
    source = Path(meta.get('repo') or '').expanduser().resolve()
    if source not in [Path(p).expanduser().resolve() for p in core.config(root).get('repos', [])]:
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
        if not parts or PureWindowsPath(name).drive or name.startswith('/') or '..' in parts or any(p in ('.git', '.ws', '.codex', '.claude') for p in parts) or '\x00' in name:
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
        git(directory, 'clone', '--bare', '--no-local', '--template=', '--', str(source), str(directory / 'source.git'))
        git(directory / 'source.git', 'remote', 'remove', 'origin')
        git(directory / 'source.git', 'fetch', '--no-tags', '--', str(source), commit)
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
