"""Private repo wiring; workspace memory stays outside the code checkout."""
import base64
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from . import core, setup, upgrade

LINK = '.ws-start.json'
FILES = ('CLAUDE.local.md', 'AGENTS.override.md', '.claude/settings.local.json', '.codex/hooks.json', '.mcp.json', '.codex/config.toml', '.codex/config.toml.ws-backup', '.cursor/hooks.json', '.cursor/mcp.json', '.cursor/rules/ws-current-task.mdc', '.github/hooks/ws.json', '.github/copilot-instructions.md', '.vscode/mcp.json', '.gemini/settings.json', 'GEMINI.md')


def path(repo, name):
    target = repo / name
    core.inside(target, [repo])
    if any(p.is_symlink() for p in (target, *target.parents) if p == repo or repo in p.parents):
        raise core.WsError('Start refuses symlinked local files: ' + name)
    return target


def load(repo):
    data = json.loads(path(repo, LINK).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('files'), dict) or any(n not in FILES for n in data['files']):
        raise core.WsError('Invalid start record; restore .ws-start.json before ws start --undo.')
    return data


def record_file(repo, state, name, data):
    target = path(repo, name)
    previous = target.read_bytes() if target.exists() else None
    entry = state['files'].get(name)
    if entry and hashlib.sha256(previous or b'').hexdigest() != entry['sha']:
        raise core.WsError('Local file changed; review it before ws start: ' + name)
    if entry is None:
        entry = dict(before=base64.b64encode(previous).decode() if previous is not None else None)
        state['files'][name] = entry
    entry['sha'] = hashlib.sha256(data).hexdigest()
    core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    core.atomic_write(target, data)


def exclusions(repo, state):
    exclude = Path(state['exclude'])
    expected = Path(subprocess.check_output(['git', '-C', str(repo), 'rev-parse', '--git-path', 'info/exclude'], text=True).strip())
    if not expected.is_absolute(): expected = repo / expected
    if exclude.resolve() != expected.resolve(): raise core.WsError('Start record points at another Git exclude file; restore it before undo.')
    if exclude.is_symlink(): raise core.WsError('Local Git exclude changed to a symlink; restore it before undo.')
    block = base64.b64decode(state['exclude_block'])
    if state.get('complete') is False and 'exclude_previous' in state and (not exclude.is_file() or exclude.read_bytes().count(block) != 1):
        previous = base64.b64decode(state['exclude_previous'])
        if not previous and (not exclude.exists() or block.splitlines()[1] not in exclude.read_bytes()): return exclude, b''
        block = previous
    if not exclude.is_file() or exclude.read_bytes().count(block) != 1: raise core.WsError('Git exclude block changed; restore the recorded block before ws start --undo.')
    return exclude, block


def undo(repo, state):
    exclude, block = exclusions(repo, state)
    kept = []
    config = state['files'].get('.codex/config.toml')
    backup = '.codex/config.toml.ws-backup'
    if config and backup in state['files']:
        target = path(repo, '.codex/config.toml')
        old = base64.b64decode(config['before']) if config['before'] is not None else None
        current = target.read_bytes() if target.exists() else None
        if current is None or (current != old and hashlib.sha256(current).hexdigest() != config['sha']):
            kept.append(backup)
    for name, entry in list(state['files'].items()):
        if name in kept: continue
        target = path(repo, name)
        old = base64.b64decode(entry['before']) if entry['before'] is not None else None
        current = target.read_bytes() if target.exists() else None
        if (current is None and old is not None) or (current is not None and current != old and hashlib.sha256(current).hexdigest() != entry['sha']):
            kept.append(name); continue
        if old is None: target.unlink(missing_ok=True)
        else: core.atomic_write(target, old)
        del state['files'][name]
    if kept:
        core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
        print('Kept edited local files: ' + ', '.join(kept), file=sys.stderr)
    else:
        if exclude.exists(): core.atomic_write(exclude, exclude.read_bytes().replace(block, b'', 1))
        path(repo, LINK).unlink()
        for name in state.get('directories', []):
            directory = path(repo, name)
            if directory.exists() and not any(directory.iterdir()): directory.rmdir()
    return dict(root=state['workspace'], already=True, assistants=[], task='', branch=setup.branch(repo), partial=bool(kept), undone=True)


def confirm(yes, dry_run):
    if dry_run: return False
    if yes: return True
    print('Apply these local files? [y/N] ', end='', file=sys.stderr)
    try: return input().strip().lower() in ('y', 'yes')
    except EOFError: raise core.WsError('No confirmation; use ws start --yes or --dry-run.')


def codex_files(repo, root):
    target = path(repo, '.codex/config.toml'); original = target.read_bytes() if target.exists() else b''
    text = original.decode('utf-8')
    parent = re.search(r'^\s*\[\s*(?:"mcp_servers"|\'mcp_servers\'|mcp_servers)\s*\]\s*(.*?)(?=^\s*\[|\Z)', text, re.M | re.S)
    parent_has_server = parent and re.search(r'^\s*(?:"ai-dev-workspace"|\'ai-dev-workspace\'|ai-dev-workspace)\s*=', parent[1], re.M)
    if parent_has_server or re.search(r'^\s*(?:mcp_servers\s*=|mcp_servers\s*\.\s*(?:"ai-dev-workspace"|\'ai-dev-workspace\'|ai-dev-workspace)\s*(?:\.|=)|\[\s*(?:"mcp_servers"|\'mcp_servers\'|mcp_servers)\s*\.\s*(?:"ai-dev-workspace"|\'ai-dev-workspace\'|ai-dev-workspace)\s*\])', text, re.M):
        raise core.WsError('Existing Codex workspace entry; review project config before ws start.')
    desired = {}
    if target.exists():
        backup = '.codex/config.toml.ws-backup'
        if path(repo, backup).exists(): raise core.WsError('Codex backup already exists; keep it safe and review it before ws start.')
        desired[backup] = original
    desired['.codex/config.toml'] = original + ('\n' + core.codex_mcp_config(root)).encode()
    return desired


def upgrade_codex(repo, root, state, yes, dry_run):
    desired = codex_files(repo, root); exclude, block = exclusions(repo, state)
    if subprocess.check_output(['git', '-C', str(repo), 'ls-files', '--', *desired], text=True).strip(): raise core.WsError('Start will not change tracked Codex config or backup files.')
    before = {n: path(repo, n).read_bytes() if path(repo, n).exists() else None for n in desired}
    print('Apply Codex MCP locally (backup first); no global config writes:', file=sys.stderr)
    for name in (LINK, *desired): print('  ' + str(repo / name), file=sys.stderr)
    print('  ' + str(exclude) + ' (local exclusions)', file=sys.stderr)
    if not confirm(yes, dry_run): return False
    if any((path(repo, n).read_bytes() if path(repo, n).exists() else None) != data for n, data in before.items()): raise core.WsError('Local config changed during confirmation; review it before retrying.')
    exclude, block = exclusions(repo, state)
    updated = block.replace(b'# /ws:start', ('\n'.join('/' + n for n in desired) + '\n# /ws:start').encode())
    state['files'].update({n: dict(before=base64.b64encode(data).decode() if data is not None else None, sha=hashlib.sha256(data or b'').hexdigest()) for n, data in before.items()})
    state.update(complete=False, exclude_previous=state['exclude_block'], exclude_block=base64.b64encode(updated).decode())
    core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    core.atomic_write(exclude, exclude.read_bytes().replace(block, updated, 1))
    for name, data in desired.items(): record_file(repo, state, name, data)
    state['complete'] = True; state.pop('exclude_previous', None)
    core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    return True


def start(yes=False, dry_run=False, workspace=None, remove=False):
    if remove and dry_run: raise core.WsError('Use --undo or --dry-run separately.')
    try: result = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc: raise core.WsError('Cannot inspect this Git repo; check git and retry ws start: ' + str(exc))
    if result.returncode: raise core.WsError('Run ws start inside a git code repository.')
    repo = Path(result.stdout.strip()).resolve(); current = setup.branch(repo)
    if not current and not remove: raise core.WsError('Choose a git branch before ws start; detached HEAD has no task name.')
    if path(repo, LINK).exists():
        state = load(repo)
        if remove: return undo(repo, state)
        root = Path(state['workspace'])
        if str(repo) not in core.config(root).get('repos', []): raise core.WsError('Linked workspace belongs elsewhere; review .ws-start.json or undo this repo setup.')
        task = next((t['id'] for t in core.task_list(root) if t['branch'] == current), '')
        partial = state.get('complete') is False or any(not path(repo, n).is_file() or hashlib.sha256(path(repo, n).read_bytes()).hexdigest() != e['sha'] for n, e in state['files'].items())
        if partial: print('Setup is incomplete or local files changed; review them, then ws start --undo before retrying.', file=sys.stderr)
        if not partial and '.codex/config.toml' not in state['files']:
            if not upgrade_codex(repo, root, state, yes, dry_run): return None
        return dict(root=str(root), already=True, partial=partial, assistants=state.get('assistants', ['claude', 'codex']), task=task, branch=current)
    if remove: raise core.WsError('No repo setup to undo; run ws start first.')
    root = Path(workspace).expanduser().resolve() if workspace else (Path.home() / '.ai-dev-workspace' / repo.name).resolve()
    if root == repo or repo in root.parents: raise core.WsError('Choose a workspace outside the repo with ws start --workspace <dir>.')
    if root.exists() and (not (root / 'workspace.json').is_file() or str(repo) not in core.config(root).get('repos', [])):
        raise core.WsError('Workspace belongs elsewhere or is not a workspace; choose ws start --workspace <dir>.')
    task = 'BR-' + core.digest_text(str(repo) + '\0' + current)[:10]
    command = core.command_line([core.python_command(), str(core.KIT / 'bin/ws'), '--workspace-root', str(root)])
    instructions = f'Private task memory: {root}\nAt session start, run `{command} brief` unless saved task memory is already in context. Follow the current request. Save verified decisions and next actions with `{command} checkpoint`.\n'
    desired = {}
    clients = ['claude', 'codex'] + [d['assistant'] for d in setup.detect() if d['assistant'] in ('cursor', 'copilot', 'gemini') and (d['cli_available'] or d['apps'])]
    for name, prefix in (('CLAUDE.local.md', '@AGENTS.md\n' if (repo / 'AGENTS.md').is_file() else ''), ('AGENTS.override.md', 'Read AGENTS.md for repo rules when it exists.\n')):
        target = path(repo, name)
        desired[name] = (target.read_bytes() if target.exists() else b'') + ('\n' + prefix + instructions).encode()
    for client, name in (('cursor', '.cursor/rules/ws-current-task.mdc'), ('copilot', '.github/copilot-instructions.md'), ('gemini', 'GEMINI.md')):
        if client not in clients: continue
        if subprocess.check_output(['git', 'ls-files', '--', name], text=True).strip():
            print('Keeping tracked instructions: ' + name, file=sys.stderr); continue
        prefix = '---\nalwaysApply: true\n---\n' if client == 'cursor' else ''
        target = path(repo, name); previous = target.read_bytes() if target.exists() else b''
        desired[name] = previous + (('\n' if previous else prefix) + instructions).encode()
    for client, name in (('claude', '.claude/settings.local.json'), ('codex', '.codex/hooks.json'), ('cursor', '.cursor/hooks.json'), ('copilot', '.github/hooks/ws.json'), ('gemini', '.gemini/settings.json')):
        if client not in clients: continue
        target = path(repo, name); data = json.loads(target.read_text()) if target.exists() else {}
        if not isinstance(data, dict) or not isinstance(data.get('hooks', {}), dict): raise core.WsError('Invalid local hook settings: ' + name)
        hooks = data.setdefault('hooks', {})
        generated = core.memory_hooks(root, 'vscode' if client == 'copilot' else client)
        if 'version' in generated: data.setdefault('version', generated['version'])
        for event, entries in generated['hooks'].items():
            if not isinstance(hooks.get(event, []), list): raise core.WsError('Invalid local hook event: ' + name)
            hooks[event] = hooks.get(event, []) + entries
        desired[name] = (json.dumps(data, indent=2) + '\n').encode()
    for client in clients:
        if client == 'codex': continue
        name, key = core.MCP_LOCATIONS['vscode' if client == 'copilot' else client]
        target = path(repo, name); data = json.loads(desired[name] if name in desired else target.read_bytes() if target.exists() else b'{}')
        if not isinstance(data, dict) or not isinstance(data.get(key, {}), dict): raise core.WsError('Invalid MCP settings: ' + name)
        servers = data.setdefault(key, {})
        if 'ai-dev-workspace' in servers: raise core.WsError('Existing workspace MCP entry; review it before ws start.')
        servers['ai-dev-workspace'] = core.mcp_command(root); desired[name] = (json.dumps(data, indent=2) + '\n').encode()
    desired.update(codex_files(repo, root))
    tracked = subprocess.run(['git', 'ls-files', '--', LINK, *desired], capture_output=True, text=True, check=True).stdout.strip()
    if tracked: raise core.WsError('Start will not change tracked local files: ' + tracked.replace('\n', ', '))
    exclude = Path(subprocess.check_output(['git', 'rev-parse', '--git-path', 'info/exclude'], text=True).strip()).absolute()
    if exclude.is_symlink(): raise core.WsError('Start refuses a symlinked Git exclude file.')
    block = ('\n# ws:start:' + core.digest_text(str(repo))[:12] + '\n' + '\n'.join('/' + n for n in (LINK, *desired)) + '\n# /ws:start\n').encode()
    before = {n: path(repo, n).read_bytes() if path(repo, n).exists() else None for n in desired}
    print('Preview: local repo files (Git-excluded) and private workspace ' + str(root), file=sys.stderr)
    if 'copilot' in clients: print('Copilot instructions are normally shared; these stay private for local VS Code. Cloud agents require a committed copy; ask before sharing.', file=sys.stderr)
    for name in (LINK, *desired): print('  ' + str(repo / name), file=sys.stderr)
    print('  ' + str(exclude) + ' (local exclusions)', file=sys.stderr)
    outside = {'.ws/lock', '.ws/claims/' + task + '.json', 'vault/Tasks/' + task + '.md'}
    if not root.exists(): outside |= {p.relative_to(core.KIT / 'template').as_posix() for p in (core.KIT / 'template').rglob('*') if p.is_file()} - {'routing-presets.json'} | set(upgrade.skills()) | set(upgrade.pointer_files()) | {'workspace.json', 'routing.json', 'vault/Project/Codebase map.md'}
    for name in sorted(outside): print('  ' + str(root / name), file=sys.stderr)
    if not confirm(yes, dry_run): return None
    if any((path(repo, n).read_bytes() if path(repo, n).exists() else None) != data for n, data in before.items()): raise core.WsError('Local config changed during confirmation; review it before retrying.')
    if not root.exists(): core.init(root, repo.name, repos=[str(repo)], clients=[])
    owned = {n: dict(before=base64.b64encode(data).decode() if data is not None else None, sha=hashlib.sha256(data or b'').hexdigest()) for n, data in before.items()}
    directories = {p.relative_to(repo).as_posix() for n in desired for p in (repo / n).parents if repo in p.parents and not p.exists()}
    state = dict(workspace=str(root), files=owned, complete=False, exclude_previous='', assistants=clients, directories=sorted(directories, key=lambda n: n.count('/'), reverse=True), exclude=str(exclude), exclude_block=base64.b64encode(block).decode())
    core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    core.atomic_write(exclude, (exclude.read_bytes() if exclude.exists() else b'') + block)
    state.pop('exclude_previous'); core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    for name, data in desired.items(): record_file(repo, state, name, data)
    new_task = not core.task_find(root, task)
    if new_task: core.task_new(root, task, current, branch=current, repo=str(repo))
    core.claim(root, task, 'local')
    if new_task: core.checkpoint(root, task, 'in_progress', 'Follow the current request; save the next action before stopping.')
    state['complete'] = True; core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    return dict(root=str(root), already=False, assistants=clients, task=task, branch=current)
