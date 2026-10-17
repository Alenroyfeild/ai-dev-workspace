"""Private repo wiring; workspace memory stays outside the code checkout."""
import base64
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from . import core, setup, upgrade, memory_import

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
    if state.get('complete') is False and 'exclude_before' in state:
        current = exclude.read_bytes() if exclude.is_file() else b''
        before = base64.b64decode(state['exclude_before'])
        intended = before + block
        if current != intended and intended.startswith(current) and current.startswith(before):
            core.atomic_write(exclude, before)
            return exclude, b''
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
    print('Apply this setup and previewed private memory imports? [y/N] ', end='', file=sys.stderr)
    try: return input().strip().lower() in ('y', 'yes')
    except EOFError: raise core.WsError('No confirmation; use ws start --yes or --dry-run.')


def codex_files(repo, root):
    if core.client_connected(root, 'codex', global_only=True): return {}
    target = path(repo, '.codex/config.toml')
    block = core.codex_mcp_config(root)
    if target.exists():
        print('Codex: manual step pending. Review and paste this block into ' + str(target) + ':\n' + block, file=sys.stderr)
        return {}
    return {'.codex/config.toml': block.encode()}


def codex_pending(root, check_global=True):
    global_connected = core.client_connected(root, 'codex', global_only=True)
    if check_global and global_connected: return []
    return [str(p / '.codex/config.toml') for p in core.read_roots(root)[1:]
            if (p / LINK).is_file() and load(p).get('codex_status') in (('manual step pending', 'connected via global config') if global_connected else ('manual step pending',))]


HOOK_FILES = ('.claude/settings.local.json', '.codex/hooks.json', '.cursor/hooks.json', '.github/hooks/ws.json', '.gemini/settings.json')


def _strings(node):
    if isinstance(node, str): yield node
    elif isinstance(node, dict): yield from (s for v in node.values() for s in _strings(v))
    elif isinstance(node, list): yield from (s for v in node for s in _strings(v))


def _missing_in_hook(command, root):
    """First dead path in a ws-written hook command, else ''. Commands we cannot parse are skipped, never reported."""
    if 'bin/ws' not in command and '--workspace-root' not in command and 'EncodedCommand' not in command: return ''
    try:
        parts = shlex.split(command)
        if parts[:1] == [core._HOOK_PREFIX[0]]: parts = core.encoded_hook_args(parts)
        elif core.WINDOWS: return ''  # quoted Windows paths do not survive posix splitting
        if '--workspace-root' not in parts: return ''
        interpreter, kit, workspace = parts[0], parts[1], parts[parts.index('--workspace-root') + 1]
    except (ValueError, IndexError): return ''
    for item in (interpreter, kit):
        if not Path(item).exists() and not shutil.which(item): return item
    return '' if Path(workspace).resolve() == Path(root).resolve() else workspace  # resolve: /private symlinks on macOS


def stale_hooks(root):
    """Hook commands that ws start wrote which point to a moved kit or another workspace."""
    found = []
    for repo in core.read_roots(root)[1:]:
        if not (repo / LINK).is_file(): continue
        try: names = [n for n in load(repo)['files'] if n in HOOK_FILES]
        except (OSError, ValueError, core.WsError): continue
        for name in names:
            try: data = json.loads((repo / name).read_text(encoding='utf-8'))
            except (OSError, ValueError): continue
            missing = next(filter(None, (_missing_in_hook(c, root) for c in _strings(data.get('hooks') if isinstance(data, dict) else None))), '')
            if missing: found.append({'repo': str(repo), 'file': name, 'missing': missing})
    return found


def upgrade_codex(repo, root, state, yes, dry_run):
    desired = codex_files(repo, root)
    if not desired:
        if core.client_connected(root, 'codex', global_only=True):
            state['codex_status'] = 'connected via global config'; return True
        if state.get('codex_status') == 'manual step pending': return True
        record_before = path(repo, LINK).read_bytes()
        if not confirm(yes, dry_run): return False
        if path(repo, LINK).read_bytes() != record_before: raise core.WsError('Setup record changed during confirmation; review it before retrying ws start.')
        if not path(repo, '.codex/config.toml').is_file(): raise core.WsError('Codex config disappeared during confirmation; retry ws start.')
        state['codex_status'] = 'manual step pending'
        if not dry_run:
            if subprocess.check_output(['git', '-C', str(repo), 'ls-files', '--', LINK], text=True).strip(): raise core.WsError('Start will not change its tracked setup record.')
            core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
        return True
    exclude, block = exclusions(repo, state)
    record = path(repo, LINK); record_before = record.read_bytes()
    if subprocess.check_output(['git', '-C', str(repo), 'ls-files', '--', LINK, *desired], text=True).strip(): raise core.WsError('Start will not change tracked local files or its setup record.')
    before = {n: path(repo, n).read_bytes() if path(repo, n).exists() else None for n in desired}
    print('Create Codex MCP locally; no global config writes:', file=sys.stderr)
    for name in (LINK, *desired): print('  ' + str(repo / name), file=sys.stderr)
    print('  ' + str(exclude) + ' (local exclusions)', file=sys.stderr)
    if not confirm(yes, dry_run): return False
    if not record.is_file() or record.read_bytes() != record_before: raise core.WsError('Setup record changed during confirmation; review it before retrying ws start.')
    if any((path(repo, n).read_bytes() if path(repo, n).exists() else None) != data for n, data in before.items()): raise core.WsError('Local config changed during confirmation; review it before retrying.')
    if subprocess.check_output(['git', '-C', str(repo), 'ls-files', '--', LINK, *desired], text=True).strip(): raise core.WsError('Start will not change tracked local files or its setup record.')
    exclude, block = exclusions(repo, state)
    updated = block.replace(b'# /ws:start', ('\n'.join('/' + n for n in desired) + '\n# /ws:start').encode())
    state['files'].update({n: dict(before=base64.b64encode(data).decode() if data is not None else None, sha=hashlib.sha256(data or b'').hexdigest()) for n, data in before.items()})
    state.update(complete=False, exclude_previous=state['exclude_block'], exclude_block=base64.b64encode(updated).decode())
    core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    core.atomic_write(exclude, exclude.read_bytes().replace(block, updated, 1))
    for name, data in desired.items(): record_file(repo, state, name, data)
    state['complete'] = True; state['codex_status'] = 'connected'; state.pop('exclude_previous', None)
    core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    return True


def branch_task(root, repo, branch):
    matches = []
    for task in core.task_list(root) if root.exists() else []:
        if task['branch'] != branch: continue
        value = core.task_read(root, task['id'], ['Next action'])['meta'].get('repo', '')
        location = Path(value)
        if not location.is_absolute(): location = root / location
        if location.resolve() == repo: matches.append(task['id'])
    if len(matches) > 1: raise core.WsError('Several tasks match this repo and branch; resolve them before ws start.')
    if matches: return matches[0]
    name = (re.sub(r'[^A-Za-z0-9._-]+', '-', branch).strip('._-') or 'branch')[:80].rstrip('._-')
    if re.fullmatch(r'(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?', name): name = 'branch-' + name[:73]
    if root.exists() and core.task_path(root, name).exists():
        name = name[:71] + '-' + core.digest_text(str(repo) + '\0' + branch)[:8]
        if core.task_path(root, name).exists(): raise core.WsError('Branch task name collision; resolve existing records before ws start.')
    return name


def render(repo, root, clients, prior):
    """Repo wiring for this kit, built on each file's bytes from before ws (prior(name) -> bytes or None)."""
    command = core.command_line([core.python_command(), str(core.KIT / 'bin/ws'), '--workspace-root', str(root)])
    instructions = f'Private task memory: {root}\nAt session start, run `{command} brief` unless saved task memory is already in context. Follow the current request. Save verified decisions and next actions with `{command} checkpoint`.\n'
    instructions += 'When the user states a decision or corrects an earlier one, call the MCP `remember` tool with it; for a correction, say what it replaces.\n'
    desired = {}
    for name, prefix in (('CLAUDE.local.md', '@AGENTS.md\n' if (repo / 'AGENTS.md').is_file() else ''), ('AGENTS.override.md', 'Read AGENTS.md for repo rules when it exists.\n')):
        desired[name] = (prior(name) or b'') + ('\n' + prefix + instructions).encode()
    for client, name in (('cursor', '.cursor/rules/ws-current-task.mdc'), ('copilot', '.github/copilot-instructions.md'), ('gemini', 'GEMINI.md')):
        if client not in clients: continue
        if subprocess.check_output(['git', 'ls-files', '--', name], text=True).strip():
            print('Keeping tracked instructions: ' + name, file=sys.stderr); continue
        prefix = '---\nalwaysApply: true\n---\n' if client == 'cursor' else ''
        previous = prior(name) or b''
        desired[name] = previous + (('\n' if previous else prefix) + instructions).encode()
    for client, name in (('claude', '.claude/settings.local.json'), ('codex', '.codex/hooks.json'), ('cursor', '.cursor/hooks.json'), ('copilot', '.github/hooks/ws.json'), ('gemini', '.gemini/settings.json')):
        if client not in clients: continue
        data = json.loads(prior(name) or b'{}')
        if not isinstance(data, dict) or not isinstance(data.get('hooks', {}), dict): raise core.WsError('Invalid local hook settings: ' + name)
        hooks = data.setdefault('hooks', {})
        generated = core.memory_hooks(root, 'vscode' if client == 'copilot' else client)
        generated['hooks'].update(core.pack_hooks(root, client))
        if 'version' in generated: data.setdefault('version', generated['version'])
        for event, entries in generated['hooks'].items():
            if not isinstance(hooks.get(event, []), list): raise core.WsError('Invalid local hook event: ' + name)
            hooks[event] = hooks.get(event, []) + entries
        desired[name] = (json.dumps(data, indent=2) + '\n').encode()
    for client in clients:
        if client == 'codex': continue
        name, key = core.MCP_LOCATIONS['vscode' if client == 'copilot' else client]
        data = json.loads(desired[name] if name in desired else prior(name) or b'{}')
        if not isinstance(data, dict) or not isinstance(data.get(key, {}), dict): raise core.WsError('Invalid MCP settings: ' + name)
        servers = data.setdefault(key, {})
        if 'ai-dev-workspace' in servers: raise core.WsError('Existing workspace MCP entry; review it before ws start.')
        servers['ai-dev-workspace'] = core.mcp_command(root); desired[name] = (json.dumps(data, indent=2) + '\n').encode()
    return desired


def hook_packs(root):
    """Packs that add repo hooks (guards, discipline); turning one on or off is a reason to refresh the repo setup."""
    return [p for p in core.HOOK_PACKS if p in core.config(root).get('packs', [])]


def refresh(repo, root, state, yes, dry_run, keep=()):
    """Rewrite ws-written files still unchanged since ws wrote them, for this kit version; user edits stop it earlier."""
    def before(name):
        entry = state['files'].get(name)
        return base64.b64decode(entry['before']) if entry and entry.get('before') else None
    desired = render(repo, root, state.get('assistants', ['claude', 'codex']), before)
    codex = state['files'].get('.codex/config.toml')
    if codex and codex.get('before') is None: desired['.codex/config.toml'] = core.codex_mcp_config(root).encode()
    changes = {n: data for n, data in desired.items() if n in state['files'] and n not in keep and path(repo, n).read_bytes() != data}
    for name in keep: print('Kept your edits, not refreshed: ' + str(repo / name), file=sys.stderr)
    if changes:
        print('Refresh repo setup for this ai-dev-workspace version (saved memory is kept):', file=sys.stderr)
        for name in changes: print('  ' + str(repo / name), file=sys.stderr)
        tracked = subprocess.run(['git', '-C', str(repo), 'ls-files', '--', LINK, *changes], capture_output=True, text=True, check=True).stdout.strip()
        if tracked: raise core.WsError('Start will not change tracked local files: ' + tracked.replace('\n', ', '))  # same rule as first setup
        if dry_run: return sorted(changes)
        if not confirm(yes, dry_run): return None
        for name, data in changes.items(): record_file(repo, state, name, data)  # refuses a file changed meanwhile
    if dry_run: return sorted(changes)
    # Kept (user-edited) files stay pending: the version moves only once every recorded file is current.
    if not keep: state['kit_version'] = core.kit_meta()['version']; state['hook_packs'] = hook_packs(root)
    core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    return sorted(changes)


def start(yes=False, dry_run=False, workspace=None, remove=False, memory_dir=None, no_import=False):
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
        task = branch_task(root, repo, current)
        if not core.task_path(root, task).exists(): task = ''
        incomplete = state.get('complete') is False or any(not path(repo, n).is_file() for n in state['files'])
        edited = [n for n, e in state['files'].items() if path(repo, n).is_file() and hashlib.sha256(path(repo, n).read_bytes()).hexdigest() != e['sha']]
        partial = incomplete or bool(edited)
        if partial: print('Setup is incomplete or local files changed; review them, then ws start --undo before retrying.', file=sys.stderr)
        newer = core._vtuple(state.get('kit_version') or '0.0.0') > core._vtuple(core.kit_meta()['version'])
        if not incomplete and newer: print('Repo setup is from a newer ai-dev-workspace version; update this kit (ws update or pipx upgrade) before changing it.', file=sys.stderr)
        # Files the user edited are kept; the rest still refresh, so one edited file does not leave hooks stale.
        refreshed = refresh(repo, root, state, yes, dry_run, keep=edited) if not incomplete and not newer and (state.get('kit_version') != core.kit_meta()['version'] or state.get('hook_packs', []) != hook_packs(root)) else []
        if refreshed is None: return None
        if not partial and not newer and '.codex/config.toml' not in state['files']:  # a newer setup is never changed
            if not upgrade_codex(repo, root, state, yes, dry_run): return None
        return dict(root=str(root), already=True, partial=partial, refreshed=refreshed, assistants=state.get('assistants', ['claude', 'codex']), task=task, branch=current, codex_status=state.get('codex_status', 'connected'))
    if remove: raise core.WsError('No repo setup to undo; run ws start first.')
    root = Path(workspace).expanduser().resolve() if workspace else (Path.home() / '.ai-dev-workspace' / repo.name).resolve()
    if root == repo or repo in root.parents: raise core.WsError('Choose a workspace outside the repo with ws start --workspace <dir>.')
    if root.exists() and (not (root / 'workspace.json').is_file() or str(repo) not in core.config(root).get('repos', [])):
        raise core.WsError('Workspace belongs elsewhere or is not a workspace; choose ws start --workspace <dir>.')
    task = branch_task(root, repo, current)
    clients = ['claude', 'codex'] + [d['assistant'] for d in setup.detect() if d['assistant'] in ('cursor', 'copilot', 'gemini') and (d['cli_available'] or d['apps'])]
    desired = render(repo, root, clients, lambda n: path(repo, n).read_bytes() if path(repo, n).exists() else None)
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
    if dry_run:
        for name in sorted(outside): print('  ' + str(root / name), file=sys.stderr)
    else:  # the private files are ws's own; --dry-run lists each one
        print(f'  plus {len(outside)} private workspace files (ws start --dry-run lists them)', file=sys.stderr)
    imports = [] if no_import else memory_import.preview(repo, memory_dir, dry_run=dry_run)
    if not confirm(yes, dry_run): return None
    memory_import.verify(imports)
    if '.codex/config.toml' not in desired and not core.client_connected(root, 'codex', global_only=True) and not path(repo, '.codex/config.toml').is_file(): raise core.WsError('Codex config disappeared during confirmation; retry ws start.')
    if path(repo, LINK).exists(): raise core.WsError('Setup record appeared during confirmation; keep it safe and review before ws start.')
    if any((path(repo, n).read_bytes() if path(repo, n).exists() else None) != data for n, data in before.items()): raise core.WsError('Local config changed during confirmation; review it before retrying.')
    tracked = subprocess.run(['git', 'ls-files', '--', LINK, *desired], capture_output=True, text=True, check=True).stdout.strip()
    if tracked: raise core.WsError('Start will not change tracked local files: ' + tracked.replace('\n', ', '))
    if not root.exists(): core.init(root, repo.name, repos=[str(repo)], clients=[])
    owned = {n: dict(before=base64.b64encode(data).decode() if data is not None else None, sha=hashlib.sha256(data or b'').hexdigest()) for n, data in before.items()}
    directories = {p.relative_to(repo).as_posix() for n in desired for p in (repo / n).parents if repo in p.parents and not p.exists()}
    previous_exclude = exclude.read_bytes() if exclude.exists() else b''
    state = dict(kit_version=core.kit_meta()['version'], hook_packs=hook_packs(root), codex_status='connected' if '.codex/config.toml' in desired else 'connected via global config' if core.client_connected(root, 'codex', global_only=True) else 'manual step pending', workspace=str(root), files=owned, complete=False, exclude_previous='', exclude_before=base64.b64encode(previous_exclude).decode(), assistants=clients, directories=sorted(directories, key=lambda n: n.count('/'), reverse=True), exclude=str(exclude), exclude_block=base64.b64encode(block).decode())
    if path(repo, LINK).exists(): raise core.WsError('Setup record appeared during confirmation; keep it safe and review before ws start.')
    core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    core.atomic_write(exclude, (exclude.read_bytes() if exclude.exists() else b'') + block)
    state.pop('exclude_previous'); state.pop('exclude_before'); core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    for name, data in desired.items(): record_file(repo, state, name, data)
    new_task = not core.task_path(root, task).exists()
    if new_task: core.task_new(root, task, current, branch=current, repo=str(repo))
    core.claim(root, task, 'local')
    if new_task:
        with core.lock(root):
            target = core.task_path(root, task); text = target.read_text(encoding='utf-8')
            meta = core.parse_meta(text)
            template = core.section((core.KIT / 'template/vault/Templates/Task.md').read_text(encoding='utf-8'), 'Next action')
            if (core._local_claim_matches(root, task, meta) and meta.get('status') == 'ready'
                    and not meta.get('checkpoint_at') and core.section(text, 'Next action') == template):
                core.atomic_write(target, core.set_meta(core.set_section(text, 'Next action', ''), {'status': 'in_progress'}))
    memory_import.apply(root, repo, task, imports)
    state['complete'] = True; core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    return dict(root=str(root), already=False, assistants=clients, task=task, branch=current, codex_status=state['codex_status'])
