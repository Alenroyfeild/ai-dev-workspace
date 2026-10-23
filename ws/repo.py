"""Private repo wiring; workspace memory stays outside the code checkout."""
import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from . import core, setup, upgrade, memory_import

LINK = '.ws-start.json'
FILES = ('CLAUDE.local.md', 'AGENTS.override.md', '.claude/settings.local.json', '.codex/hooks.json', '.mcp.json', '.codex/config.toml', '.codex/config.toml.ws-backup', '.cursor/hooks.json', '.cursor/mcp.json', '.cursor/rules/ws-current-task.mdc', '.github/hooks/ws.json', '.github/copilot-instructions.md', '.vscode/mcp.json', '.gemini/settings.json', 'GEMINI.md', '.agents/mcp_config.json', '.agents/hooks.json')


def path(repo, name):
    target = repo / name
    core.inside(target, [repo])
    if any(core.is_link(p) for p in (target, *target.parents) if p == repo or repo in p.parents):
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
    if entry and name not in JSON_FILES and hashlib.sha256(previous or b'').hexdigest() != entry['sha']:  # JSON files are merged from their current bytes
        raise core.WsError('Local file changed; review it before ws start: ' + name)
    if entry is None:
        entry = dict(before=base64.b64encode(previous).decode() if previous is not None else None)
        state['files'][name] = entry
    entry['sha'] = hashlib.sha256(data).hexdigest()
    core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    core.atomic_write(target, data)


def moved(repo, state):
    """The listed repo path this record was written for when the folder moved or copied; '' otherwise."""
    try: repos = core.config(Path(state['workspace'])).get('repos', [])
    except (OSError, ValueError, TypeError, KeyError): return ''
    old = os.path.abspath(state['exclude'])
    if str(repo) in repos: return ''
    return next((r for r in repos if isinstance(r, str) and old == os.path.join(os.path.abspath(r), '.git', 'info', 'exclude')), '')


def own_exclude(repo):
    """This repo's Git exclude path; a symlinked .git, git dir, info dir or exclude file is refused before any resolve."""
    expected = Path(subprocess.check_output(['git', '-C', str(repo), 'rev-parse', '--git-path', 'info/exclude'], encoding='utf-8', errors='replace').strip())
    if not expected.is_absolute(): expected = repo / expected
    # .git may be a gitdir-pointer file (worktree/submodule): git's own answer is checked instead of .git/info/exclude.
    parts = [repo / '.git', expected.parent.parent, expected.parent, expected]
    if any(p.is_symlink() for p in parts): raise core.WsError('This repo\'s Git exclude file is a symlink (or under one); restore a plain file before ws start or undo.')
    return expected


def exclusions(repo, state):
    exclude = Path(state['exclude'])
    expected = own_exclude(repo)
    if exclude.resolve() != expected.resolve():
        if not moved(repo, state): raise core.WsError('Start record points at another Git exclude file; restore it before undo.')
        exclude = expected  # moved or copied repo: only this repo's own exclude file is used
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
    if exclude.is_file() and exclude.read_bytes().count(block) != 1 and exclude.read_bytes().count(block.replace(b'\n', b'\r\n')) == 1: block = block.replace(b'\n', b'\r\n')  # a Windows editor rewrote the line endings
    if not exclude.is_file() or exclude.read_bytes().count(block) != 1: raise core.WsError('Git exclude block changed; restore the recorded block before ws start --undo.')
    return exclude, block


def restore_file(repo, state, name):
    """Put one recorded file back as it was before ws wrote it and drop it from the record; False if it was edited since."""
    entry = state['files'][name]
    target = path(repo, name)
    old = base64.b64decode(entry['before']) if entry['before'] is not None else None
    current = target.read_bytes() if target.exists() else None
    if name in JSON_FILES and current is None:  # the user deleted it: no ws entries are left to take out
        del state['files'][name]
        return True
    if name in JSON_FILES:  # the sha cannot tell: refresh records merged bytes, so always take out only ws's entries
        rest = stripped(name, current, old)
        if rest is not None and target.read_bytes() != current: current = target.read_bytes(); rest = stripped(name, current, old)  # an edit just landed: strip ws's entries from the new bytes
        if rest is None: return False
        base = stripped(name, old) if old else {}  # a zero-byte original is no JSON, and restores as zero bytes
        # ws added the version; a different value is the user's, and the version stays once the user's own hooks need it.
        if name == '.cursor/hooks.json' and rest.get('version') == WS_CURSOR_VERSION and 'version' not in (base or {}) and rest.get('hooks') == (base or {}).get('hooks'): del rest['version']
        if old is None and not rest: target.unlink(missing_ok=True)
        elif old is not None and rest == base: core.atomic_write(target, old)  # no user additions: byte-exact restore
        else: core.atomic_write(target, (json.dumps(rest, indent=2) + '\n').encode())
        del state['files'][name]
        return True
    if (current is None and old is not None) or (current is not None and current != old and hashlib.sha256(current).hexdigest() != entry['sha']): return False
    if old is None: target.unlink(missing_ok=True)
    else: core.atomic_write(target, old)
    del state['files'][name]
    return True


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
    for name in list(state['files']):
        if name not in kept and not restore_file(repo, state, name): kept.append(name)
    if kept:
        state['complete'] = False  # the files undo removed are gone: a later ws start must not say "Already set up"
        core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
        print('Kept edited local files: ' + ', '.join(kept) + '; restore or delete them, then run ws start --undo again.', file=sys.stderr)
    else:
        if exclude.exists(): core.atomic_write(exclude, exclude.read_bytes().replace(block, b'', 1))
        path(repo, LINK).unlink()
        for name in state.get('directories', []):
            directory = path(repo, name)
            if directory.exists() and not any(directory.iterdir()): directory.rmdir()
    return dict(root=state['workspace'], already=True, assistants=[], task='', branch=setup.branch(repo), partial=bool(kept), undone=True)


def confirm(yes, dry_run, imports=False):
    if dry_run: return False
    if yes: return True
    print('Apply this setup' + (' and previewed private memory imports' if imports else '') + '? [y/N] ', end='', file=sys.stderr)
    try: return input().strip().lower() in ('y', 'yes')
    except EOFError: print(file=sys.stderr); raise core.WsError('No confirmation; use ws start --yes or --dry-run.')  # newline: end the prompt line


def codex_files(repo, root):
    if core.client_connected(root, 'codex', global_only=True): return {}
    target = path(repo, '.codex/config.toml')
    block = core.codex_mcp_config(root)
    if target.exists():
        print('Codex: manual step pending. Review and paste this block into ' + str(target) + ':\n' + block, file=sys.stderr)
        return {}
    return {'.codex/config.toml': block.encode()}


PLUGIN = 'ai-dev-workspace@ai-dev-workspace'


def claude_dir():
    """The Claude config dir named by CLAUDE_CONFIG_DIR now, or '' (the default ~/.claude)."""
    return str(Path(os.environ['CLAUDE_CONFIG_DIR']).expanduser()) if os.environ.get('CLAUDE_CONFIG_DIR') else ''


def claude_plugin_enabled(repo, recorded=''):
    """enabledPlugins for this kit's Claude Code plugin; local beats project beats user, like Claude Code.
    `recorded` is the config dir saved at ws start; it stands in when CLAUDE_CONFIG_DIR is unset in this shell."""
    value = None
    user = Path(os.environ.get('CLAUDE_CONFIG_DIR') or recorded or Path.home() / '.claude')  # Claude Code honours CLAUDE_CONFIG_DIR
    for settings in (user / 'settings.json', repo / '.claude/settings.json', repo / '.claude/settings.local.json'):
        try: plugins = json.loads(settings.read_text(encoding='utf-8-sig')).get('enabledPlugins')  # -sig: PowerShell 5 writes a BOM
        except (OSError, ValueError, AttributeError): continue
        if isinstance(plugins, dict) and isinstance(plugins.get(PLUGIN), bool): value = plugins[PLUGIN]
    return value is True


def plugin_state(p):
    try: return load(p).get('plugin', False)
    except (OSError, ValueError, core.WsError): return False


def plugin_on(p):
    """claude_plugin_enabled for a started repo, using the config dir its record saved."""
    try: recorded = load(p).get('claude_config_dir', '')
    except (OSError, ValueError, core.WsError): recorded = ''
    return claude_plugin_enabled(p, recorded)


def _same(p, only):
    return only is None or Path(only).resolve() == p.resolve()


def plugin_duplicates(root, only=None):
    """Started repos (just `only`, if given) where the Claude Code plugin and ws start's own Claude hooks would both run."""
    def files(p):  # a corrupt start record must not crash doctor; ws start reports it
        try: return load(p).get('files', {})
        except (OSError, ValueError, core.WsError): return {}
    return [str(p) for p in core.read_roots(root)[1:] if (p / LINK).is_file() and _same(p, only)
            and '.claude/settings.local.json' in files(p) and not plugin_state(p) and plugin_on(p)]


def plugin_missing(root):
    """Started repos whose record says the plugin brings Claude's hooks, but the plugin is no longer enabled."""
    return [str(p) for p in core.read_roots(root)[1:] if (p / LINK).is_file() and plugin_state(p) and not plugin_on(p)]


def codex_pending(root, check_global=True):
    global_connected = core.client_connected(root, 'codex', global_only=True)
    if check_global and global_connected: return []
    def status(p):  # a corrupt start record must not crash doctor; ws start reports it
        try: return load(p).get('codex_status')
        except (OSError, ValueError, core.WsError): return None
    return [str(p / '.codex/config.toml') for p in core.read_roots(root)[1:]
            if (p / LINK).is_file() and status(p) in (('manual step pending', 'connected via global config') if global_connected else ('manual step pending',))]


HOOK_FILES = ('.claude/settings.local.json', '.codex/hooks.json', '.cursor/hooks.json', '.github/hooks/ws.json', '.gemini/settings.json', '.agents/hooks.json')


def _strings(node):
    if isinstance(node, str): yield node
    elif isinstance(node, dict): yield from (s for v in node.values() for s in _strings(v))
    elif isinstance(node, list): yield from (s for v in node for s in _strings(v))


HOOK_COMMANDS = {'brief', 'nudge', 'paste', 'guard', 'discipline', 'digest-hint'}


def _ws_hook_parts(command):
    """argv of a hook command ws wrote (<python> <kit>/bin/ws[-plugin] --workspace-root <root> ... <hook subcommand>), else None; a user's own hook is never matched."""
    if 'bin/ws' not in command and '--workspace-root' not in command and 'EncodedCommand' not in command: return None
    try:
        parts = shlex.split(command, posix=not core.WINDOWS)  # posix splitting eats the backslashes of Windows paths
        if core.WINDOWS: parts = [p[1:-1] if len(p) > 1 and p[0] == p[-1] == '"' else p for p in parts]
        if parts[:1] == [core._HOOK_PREFIX[0]]: parts = core.encoded_hook_args(parts)
        if '--workspace-root' not in parts: return None
        kit = parts[1]
        if Path(kit).name not in ('ws', 'ws-plugin') or Path(kit).parent.name != 'bin' or not set(parts) & HOOK_COMMANDS: return None
    except (ValueError, IndexError): return None
    return parts


def _missing_in_hook(command, root):
    """First dead path in a ws-written hook command, else ''. Commands we cannot parse are skipped, never reported."""
    parts = _ws_hook_parts(command)
    if not parts: return ''
    interpreter, kit, workspace = parts[0], parts[1], parts[parts.index('--workspace-root') + 1]
    for item in (interpreter, kit):
        if not Path(item).exists() and not shutil.which(item): return item
    return '' if Path(workspace).resolve() == Path(root).resolve() else workspace  # resolve: /private symlinks on macOS


JSON_FILES = HOOK_FILES + ('.mcp.json', '.cursor/mcp.json', '.vscode/mcp.json', '.agents/mcp_config.json')  # merged into, so ws owns only its entries
WS_CURSOR_VERSION = 1  # the `version` key core.memory_hooks writes into cursor's hooks.json
MCP_KEYS = {n: k for n, k in core.MCP_LOCATIONS.values()}


def _is_ws_hook(hook):
    return isinstance(hook, dict) and isinstance(hook.get('command'), str) and _ws_hook_parts(hook['command']) is not None


def _user_entries(entries):
    """Hook entries without ws's own hooks; an entry that mixed ws and user hooks keeps the user's."""
    out = []
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get('hooks'), list):
            inner = [h for h in entry['hooks'] if not _is_ws_hook(h)]
            if len(inner) != len(entry['hooks']):
                if inner: out.append({**entry, 'hooks': inner})
                continue
        elif _is_ws_hook(entry): continue
        out.append(entry)
    return out


def stripped(name, raw, before=None):
    """The JSON file's data without the hooks and MCP server ws wrote (user keys stay); None if it is not a JSON object.
    `before` is the file as it was before ws: an event or container the user already had stays even when ws's removal empties it."""
    try: data = json.loads(raw)
    except ValueError: return None
    if not isinstance(data, dict): return None
    try: had = json.loads(before) if before else {}
    except ValueError: had = {}
    had = had if isinstance(had, dict) else {}
    had_hooks = had.get('hooks') if isinstance(had.get('hooks'), dict) else {}
    hooks = data.get('hooks')
    if isinstance(hooks, dict):
        touched = False  # only what ws's removal emptied goes; a list or container the user left empty stays
        for event in list(hooks):
            if not isinstance(hooks[event], list): continue
            user = _user_entries(hooks[event])
            if user == hooks[event]: continue
            touched = True; hooks[event] = user
            if not user and event not in had_hooks: del hooks[event]
        if touched and not hooks and 'hooks' not in had: del data['hooks']
    servers = data.get(MCP_KEYS.get(name))
    if isinstance(servers, dict) and servers.pop('ai-dev-workspace', None) is not None and not servers and MCP_KEYS[name] not in had: del data[MCP_KEYS[name]]
    return data


def _stale_here(root, repo):
    """This repo's ws-written hooks point to a moved kit, so a plain rerun should refresh them."""
    return any(Path(item['repo']).resolve() == repo.resolve() for item in stale_hooks(root))


def stale_hooks(root):
    """Hook commands that ws start wrote which point to a moved kit or another workspace."""
    found = []
    for repo in core.read_roots(root)[1:]:
        if not (repo / LINK).is_file(): continue
        try: names = [n for n in load(repo)['files'] if n in HOOK_FILES]
        except (OSError, ValueError, core.WsError): continue
        for name in names:
            try: data = json.loads((repo / name).read_text(encoding='utf-8-sig'))
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
            if subprocess.check_output(['git', '-C', str(repo), 'ls-files', '--', LINK], encoding='utf-8', errors='replace').strip(): raise core.WsError('Start will not change its tracked setup record.')
            core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
        return True
    exclude, block = exclusions(repo, state)
    record = path(repo, LINK); record_before = record.read_bytes()
    if subprocess.check_output(['git', '-C', str(repo), 'ls-files', '--', LINK, *desired], encoding='utf-8', errors='replace').strip(): raise core.WsError('Start will not change tracked local files or its setup record.')
    before = {n: path(repo, n).read_bytes() if path(repo, n).exists() else None for n in desired}
    print('Create Codex MCP locally; no global config writes:', file=sys.stderr)
    for name in (LINK, *desired): print('  ' + str(repo / name), file=sys.stderr)
    print('  ' + str(exclude) + ' (local exclusions)', file=sys.stderr)
    if not confirm(yes, dry_run): return False
    if not record.is_file() or record.read_bytes() != record_before: raise core.WsError('Setup record changed during confirmation; review it before retrying ws start.')
    if any((path(repo, n).read_bytes() if path(repo, n).exists() else None) != data for n, data in before.items()): raise core.WsError('Local config changed during confirmation; review it before retrying.')
    if subprocess.check_output(['git', '-C', str(repo), 'ls-files', '--', LINK, *desired], encoding='utf-8', errors='replace').strip(): raise core.WsError('Start will not change tracked local files or its setup record.')
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


def relink_tasks(root, old, new):
    """Point task records whose `repo:` is the moved-from path at the new one; other records are untouched."""
    for task in core.task_list(root):
        path = core.task_path(root, task['id'])
        try: text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError: print(f'Left {path.name} as is: it is not valid UTF-8, so its repo path was not updated.', file=sys.stderr); continue
        if core.parse_meta(text).get('repo') == old: core.atomic_write(path, core.set_meta(text, {'repo': new}))


def rehome(repo, root, state, yes, dry_run):
    """The repo folder was moved or copied: link this path to its workspace (memory and hooks stay as they are)."""
    if not (root / 'workspace.json').is_file(): raise core.WsError('Linked workspace is missing; run ws start --undo here, then ws start.')
    old = moved(repo, state)  # '' when a retry finds the repo already listed
    exclude, _ = exclusions(repo, dict(state, exclude=str(own_exclude(repo))))
    print(f'This repo was moved or copied. Link {repo} to private workspace {root}:', file=sys.stderr)
    print('  ' + str(root / 'workspace.json') + ' (repo list)', file=sys.stderr)
    print('  ' + str(repo / LINK) + ' (exclude path)', file=sys.stderr)
    if not confirm(yes, dry_run): return False
    with core.lock(root):
        cfg = core.config(root)
        # Only the path this repo moved from is dropped, and only when it is gone; other entries (unmounted drives) stay.
        cfg['repos'] = [r for r in cfg.get('repos', []) if r != old or Path(r).is_dir()] + [str(repo)] * (str(repo) not in cfg.get('repos', []))
        core.atomic_write(root / 'workspace.json', json.dumps(cfg, indent=2) + '\n')
        if old and not Path(old).is_dir(): relink_tasks(root, old, str(repo))  # a surviving copy keeps its own records
    state['exclude'] = str(exclude)
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


def _json(text, name):
    try: return json.loads(text)
    except ValueError as exc: raise core.WsError(f'Repo setup stopped; nothing was changed. {name} is not valid JSON ({exc}); JSON comments are not supported. Fix or move that file, then run ws start again.') from None


def render(repo, root, clients, prior, plugin=False):
    """Repo wiring for this kit, built on each file's bytes from before ws (prior(name) -> bytes or None)."""
    command = core.command_line([core.python_command(), str(core.KIT / 'bin/ws'), '--workspace-root', str(root)])
    instructions = f'Private task memory: {root}\nAt session start, run `{command} brief` unless saved task memory is already in context. Follow the current request. Save verified decisions and next actions with `{command} checkpoint`.\n'
    instructions += 'When the user states a decision or corrects an earlier one, call the MCP `remember` tool with it; for a correction, say what it replaces.\n'
    desired = {}
    for name, prefix in (('CLAUDE.local.md', '@AGENTS.md\n' if (repo / 'AGENTS.md').is_file() else ''), ('AGENTS.override.md', 'Read AGENTS.md for repo rules when it exists.\n')):
        desired[name] = (prior(name) or b'') + ('\n' + prefix + instructions).encode()
    for client, name in (('cursor', '.cursor/rules/ws-current-task.mdc'), ('copilot', '.github/copilot-instructions.md'), ('gemini', 'GEMINI.md'), ('antigravity', 'GEMINI.md')):
        if client not in clients: continue
        if subprocess.check_output(['git', '-C', str(repo), 'ls-files', '--', name], encoding='utf-8', errors='replace').strip():
            print('Keeping tracked instructions: ' + name, file=sys.stderr); continue
        prefix = '---\nalwaysApply: true\n---\n' if client == 'cursor' else ''
        previous = prior(name) or b''
        desired[name] = previous + (('\n' if previous else prefix) + instructions).encode()
    for client, name in (('claude', '.claude/settings.local.json'), ('codex', '.codex/hooks.json'), ('cursor', '.cursor/hooks.json'), ('copilot', '.github/hooks/ws.json'), ('gemini', '.gemini/settings.json'), ('antigravity', '.agents/hooks.json')):
        if client not in clients: continue
        data = _json(prior(name) or b'{}', name)
        if not isinstance(data, dict) or not isinstance(data.get('hooks', {}), dict): raise core.WsError('Invalid local hook settings: ' + name)
        hooks = data.setdefault('hooks', {})
        generated = {'hooks': {}} if plugin and client == 'claude' else core.memory_hooks(root, 'vscode' if client == 'copilot' else client)  # the plugin has the memory hooks
        generated['hooks'].update(core.pack_hooks(root, client))
        if not generated['hooks']: continue
        if 'version' in generated: data.setdefault('version', generated['version'])
        for event, entries in generated['hooks'].items():
            if not isinstance(hooks.get(event, []), list): raise core.WsError('Invalid local hook event: ' + name)
            hooks[event] = hooks.get(event, []) + entries
        desired[name] = (json.dumps(data, indent=2) + '\n').encode()
    for client in clients:
        if client == 'codex' or plugin and client == 'claude': continue  # the plugin brings the MCP server
        name, key = core.MCP_LOCATIONS['vscode' if client == 'copilot' else client]
        data = _json(desired[name] if name in desired else prior(name) or b'{}', name)
        if not isinstance(data, dict) or not isinstance(data.get(key, {}), dict): raise core.WsError('Invalid MCP settings: ' + name)
        servers = data.setdefault(key, {})
        if 'ai-dev-workspace' in servers: raise core.WsError('Existing workspace MCP entry in ' + name + '; review it before ws start.')
        servers['ai-dev-workspace'] = core.mcp_command(root); desired[name] = (json.dumps(data, indent=2) + '\n').encode()
    return desired


def hook_packs(root):
    """Packs that add repo hooks (guards, discipline); turning one on or off is a reason to refresh the repo setup."""
    return [p for p in core.HOOK_PACKS if p in core.config(root).get('packs', [])]


STARTERS = {'ios': 'an iOS project', 'ml': 'an ML or data project', 'web': 'a web app', 'library': 'a Python package'}


def starter(repo, root):
    """Starter pack that fits this repo's type, for a one-line hint at first setup; '' if none fits or it is on."""
    names = {p.name for p in repo.iterdir()}
    def read(name):
        try: return (repo / name).read_text(encoding='utf-8', errors='replace')[:20000] if name in names else ''
        except OSError: return ''  # a broken symlink or unreadable file is just no hint
    deps = ' '.join(read(n) for n in ('requirements.txt', 'pyproject.toml'))
    kind = ('ios' if re.search(r'\.iOS\b', read('Package.swift')) or any(n.endswith(('.xcodeproj', '.xcworkspace')) for n in names)
            else 'ml' if any(n.endswith('.ipynb') for n in names) or re.search(r'\b(torch|tensorflow|jax|scikit-learn|keras)\b', deps)
            else 'web' if 'package.json' in names else 'library' if names & {'pyproject.toml', 'setup.py'} else '')
    return kind if kind and kind not in core.config(root).get('packs', []) else ''


def _without_stale_block(data, digest, exclude):
    """Drop this repo's leftover exclude block (git clean -fdx deleted the record, not the block); refuse a malformed one."""
    begin = rb'\r?\n# ws:start:' + digest.encode() + rb'\r?\n'
    cleaned = re.sub(begin + rb'(?:/[^\r\n]*\r?\n)*# /ws:start\r?\n', b'', data)  # only path lines may sit between the markers
    if re.search(begin, cleaned): raise core.WsError(f'{exclude} has a ws start block that is damaged (missing end marker or extra lines inside). Remove it by hand, then rerun ws start; nothing was changed.')
    return cleaned


def extend_exclude(repo, state, names):
    """Add files ws newly writes to its Git-exclude block and the start record (also its directories, for undo)."""
    exclude, block = exclusions(repo, state)
    nl = b'\r\n' if b'\r\n' in block else b'\n'
    end = b'# /ws:start' + nl
    lines = block.decode().splitlines()
    extra = b''.join(('/' + n).encode() + nl for n in names if '/' + n not in lines)
    grown = block[:-len(end)] + extra + end
    core.atomic_write(exclude, exclude.read_bytes().replace(block, grown, 1))
    state['exclude_block'] = base64.b64encode(grown).decode()
    new_dirs = {p.relative_to(repo).as_posix() for n in names for p in (repo / n).parents if repo in p.parents and not p.exists()}
    state['directories'] = sorted(set(state.get('directories', [])) | new_dirs, key=lambda n: n.count('/'), reverse=True)
    core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')


def shrink_exclude(repo, state, names):
    """Inverse of extend_exclude: files ws no longer owns leave the exclude block, so a user's own file there shows in git status."""
    exclude, block = exclusions(repo, state)
    drop = {'/' + n for n in names}
    shrunk = b''.join(line for line in block.splitlines(keepends=True) if line.rstrip(b'\r\n').decode() not in drop)
    core.atomic_write(exclude, exclude.read_bytes().replace(block, shrunk, 1))
    state['exclude_block'] = base64.b64encode(shrunk).decode()
    core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')


WITHOUT_PLUGIN = ('.claude/settings.local.json', '.mcp.json')  # Claude files the plugin replaces; render() stops producing them in plugin mode


def refresh(repo, root, state, yes, dry_run, keep=()):
    """Bring ws-written files in line with this kit version, packs and Claude plugin: rewrite those still unchanged since ws wrote them, create ones now needed, restore ones no longer needed."""
    plugin = claude_plugin_enabled(repo, state.get('claude_config_dir', ''))
    basis = {}  # the exact bytes (None: no file) each merged JSON file was built from
    def before(name):
        if name in JSON_FILES: basis.setdefault(name, path(repo, name).read_bytes() if path(repo, name).is_file() else None)
        entry = state['files'].get(name)
        if entry is None: return path(repo, name).read_bytes() if path(repo, name).exists() else None  # not written by ws yet: start from what is there, like start()
        if name in JSON_FILES and basis[name] is not None:  # rebuild from the current file minus ws's entries, so user keys survive
            data = stripped(name, basis[name], base64.b64decode(entry['before']) if entry.get('before') else None)
            if data is not None: return json.dumps(data).encode()
        return base64.b64decode(entry['before']) if entry.get('before') else None
    off = bool(state.get('plugin')) and not plugin  # the plugin was switched off since ws start: its Claude files must come back
    hint = ' The Claude plugin is no longer enabled, so ws must restore its Claude hooks and MCP entry: enable the plugin again, or move your file aside (or run ws start --undo) and rerun ws start.'
    clients = state.get('assistants', ['claude', 'codex'])
    try: desired = render(repo, root, clients, before, plugin)
    except core.WsError as exc: raise core.WsError(str(exc) + (hint if off else ''))
    def merged(name):
        """The merge for a JSON file, rebuilt from its bytes now if it changed while the preview was open (a user edit is kept)."""
        for _ in range(3):
            raw = path(repo, name).read_bytes() if path(repo, name).exists() else None
            if raw == basis.get(name): return desired[name]
            if raw is not None and stripped(name, raw) is None: break
            basis.clear(); desired.update(render(repo, root, clients, before, plugin))
        raise core.WsError('Local file changed during confirmation; rerun ws start: ' + name)
    codex = state['files'].get('.codex/config.toml')
    if codex and codex.get('before') is None: desired['.codex/config.toml'] = core.codex_mcp_config(root).encode()
    new = {n: before(n) for n in desired if n not in state['files']}  # what render() saw, to catch an edit while confirming
    changes = {n: data for n, data in desired.items() if n not in keep and (n in new or path(repo, n).read_bytes() != data)}
    gone = [n for n in WITHOUT_PLUGIN if n in state['files'] and n not in desired and n not in keep]
    for name in keep: print('Kept your edits, not refreshed: ' + str(repo / name), file=sys.stderr)
    if changes or gone:
        print('Refresh repo setup for this ai-dev-workspace version (saved memory is kept):', file=sys.stderr)
        for name in changes: print('  ' + str(repo / name) + (' (new)' if name in new else ''), file=sys.stderr)
        for name in gone: print('  ' + str(repo / name) + ' (ws entries removed)', file=sys.stderr)
        tracked = subprocess.run(['git', '-C', str(repo), 'ls-files', '--', LINK, *changes, *gone], capture_output=True, encoding='utf-8', errors='replace', check=True).stdout.strip()
        if tracked: raise core.WsError('Start will not change tracked local files: ' + tracked.replace('\n', ', ') + (hint if off and set(WITHOUT_PLUGIN) & set(tracked.splitlines()) else ''))  # same rule as first setup
        if dry_run: return sorted({*changes, *gone})
        if not confirm(yes, dry_run): return None
        if any(before(n) != data for n, data in new.items() if n not in JSON_FILES): raise core.WsError('Local config changed during confirmation; review it before retrying.')
        if new: extend_exclude(repo, state, list(new))
        for name, data in changes.items(): record_file(repo, state, name, merged(name) if name in JSON_FILES else data)  # refuses a file changed meanwhile
        for name in gone:
            if not restore_file(repo, state, name): raise core.WsError('Local file changed; review it before ws start: ' + name)
            core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
        if gone: shrink_exclude(repo, state, gone)
    if dry_run: return sorted({*changes, *gone})
    # Kept (user-edited) files stay pending: the version moves only once every recorded file is current. Packs and plugin describe the hook/MCP files only,
    # so they move as soon as none of those is kept; otherwise a stale value would hide a later flip back (the rest was already rewritten).
    if not keep: state['kit_version'] = core.kit_meta()['version']
    if not {*HOOK_FILES, '.mcp.json'} & set(keep): state['hook_packs'] = hook_packs(root); state['plugin'] = plugin
    if claude_dir(): state['claude_config_dir'] = claude_dir()  # kept when a later shell lacks CLAUDE_CONFIG_DIR
    core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    return sorted({*changes, *gone})


def start(yes=False, dry_run=False, workspace=None, remove=False, memory_dir=None, no_import=False):
    if remove and dry_run: raise core.WsError('Use --undo or --dry-run separately.')
    try: result = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, encoding='utf-8', errors='replace', timeout=10)
    except (OSError, subprocess.SubprocessError) as exc: raise core.WsError('Cannot inspect this Git repo; check git and retry ws start: ' + str(exc))
    if result.returncode: raise core.WsError('Run ws start inside a git code repository.')
    repo = Path(result.stdout.strip()).resolve(); current = setup.branch(repo)
    if not current and not remove: raise core.WsError('Choose a git branch before ws start; detached HEAD has no task name.')
    if core.LINE_BREAK_RE.search(current) and not remove: raise core.WsError('This branch name has a line break or control character, so ws cannot name its task; rename the branch (git branch -m) and run ws start again.')
    if path(repo, LINK).exists():
        state = load(repo)
        if remove: return undo(repo, state)
        root = Path(state['workspace'])
        listed = str(repo) in core.config(root).get('repos', [])
        # Listed but the record still names another exclude file: an interrupted relink; finish it (rehome only ever writes this repo's own path).
        if not listed or Path(state['exclude']).resolve() != own_exclude(repo).resolve():
            if not listed and not moved(repo, state): raise core.WsError('Linked workspace belongs elsewhere; review .ws-start.json or undo this repo setup.')
            if not rehome(repo, root, state, yes, dry_run): return None
            state = load(repo)
        task = branch_task(root, repo, current)
        if not core.task_path(root, task).exists(): task = ''
        incomplete = state.get('complete') is False or any(not path(repo, n).is_file() for n in state['files'])
        edited = [n for n, e in state['files'].items() if path(repo, n).is_file() and hashlib.sha256(path(repo, n).read_bytes()).hexdigest() != e['sha']
                  and not (n in JSON_FILES and stripped(n, path(repo, n).read_bytes()) is not None)]  # valid JSON is merged, not kept
        partial = incomplete or bool(edited)
        if partial: print('Setup is incomplete or local files changed; review them, then ws start --undo before retrying.', file=sys.stderr)
        newer = core._vtuple(state.get('kit_version') or '0.0.0') > core._vtuple(core.kit_meta()['version'])
        if not incomplete and newer: print('Repo setup is from a newer ai-dev-workspace version; update this kit (ws update or pipx upgrade) before changing it.', file=sys.stderr)
        if state.get('plugin') and state.get('claude_config_dir') and not claude_dir() and claude_plugin_enabled(repo, state['claude_config_dir']):
            print('Plugin mode kept: checked the Claude config dir saved at the last ws start (' + state['claude_config_dir'] + ') because CLAUDE_CONFIG_DIR is unset here. To leave plugin mode, disable the plugin there.', file=sys.stderr)
        # Files the user edited are kept; the rest still refresh, so one edited file does not leave hooks stale.
        refreshed = refresh(repo, root, state, yes, dry_run, keep=edited) if not incomplete and not newer and (state.get('kit_version') != core.kit_meta()['version'] or state.get('hook_packs', []) != hook_packs(root) or state.get('plugin', False) != claude_plugin_enabled(repo, state.get('claude_config_dir', '')) or (claude_dir() and state.get('claude_config_dir', '') != claude_dir()) or edited or _stale_here(root, repo)) else []
        if refreshed is None: return None
        if not partial and not newer and '.codex/config.toml' not in state['files']:  # a newer setup is never changed
            if not upgrade_codex(repo, root, state, yes, dry_run): return None
        return dict(root=str(root), repo=str(repo), already=True, partial=partial, refreshed=refreshed, assistants=state.get('assistants', ['claude', 'codex']), task=task, branch=current, codex_status=state.get('codex_status', 'connected'))
    if remove: raise core.WsError('No repo setup to undo; run ws start first.')
    root = Path(workspace).expanduser().resolve() if workspace else (Path.home() / '.ai-dev-workspace' / repo.name).resolve()
    if root == repo or repo in root.parents: raise core.WsError('Choose a workspace outside the repo with ws start --workspace <dir>.')
    if root.exists() and (not (root / 'workspace.json').is_file() or str(repo) not in core.config(root).get('repos', [])):
        raise core.WsError('Workspace belongs elsewhere or is not a workspace; choose ws start --workspace <dir>.')
    task = branch_task(root, repo, current)
    clients = ['claude', 'codex'] + [d['assistant'] for d in setup.detect() if d['assistant'] in ('cursor', 'copilot', 'gemini', 'antigravity') and (d['cli_available'] or d['apps'])]
    plugin = claude_plugin_enabled(repo)  # the plugin brings Claude's memory hooks and MCP server; pack hooks stay
    desired = render(repo, root, clients, lambda n: path(repo, n).read_bytes() if path(repo, n).exists() else None, plugin)
    desired.update(codex_files(repo, root))
    tracked = subprocess.run(['git', '-C', str(repo), 'ls-files', '--', LINK, *desired], capture_output=True, encoding='utf-8', errors='replace', check=True).stdout.strip()
    if tracked: raise core.WsError('Start will not change tracked local files: ' + tracked.replace('\n', ', '))
    exclude = repo / subprocess.check_output(['git', '-C', str(repo), 'rev-parse', '--git-path', 'info/exclude'], encoding='utf-8', errors='replace').strip()  # root-anchored; absolute output wins
    if exclude.is_symlink(): raise core.WsError('Start refuses a symlinked Git exclude file.')
    block = ('\n# ws:start:' + core.digest_text(str(repo))[:12] + '\n' + '\n'.join('/' + n for n in (LINK, *desired)) + '\n# /ws:start\n').encode()
    before = {n: path(repo, n).read_bytes() if path(repo, n).exists() else None for n in desired}
    print('Preview: local repo files (Git-excluded) and private workspace ' + str(root), file=sys.stderr)
    if 'copilot' in clients: print('Copilot instructions are normally shared; these stay private for local VS Code. Cloud agents require a committed copy; ask before sharing.', file=sys.stderr)
    for name in (LINK, *desired): print('  ' + str(repo / name), file=sys.stderr)
    print('  ' + str(exclude) + ' (local exclusions)', file=sys.stderr)
    yours = [n for n, data in before.items() if data is not None]  # existing untracked files join the exclude block
    if yours: print('Hidden from git status until ws start --undo (already yours): ' + ', '.join(yours), file=sys.stderr)
    outside = {'.ws/lock', '.ws/claims/' + task + '.json', 'vault/Tasks/' + task + '.md'}
    if not root.exists(): outside |= {p.relative_to(core.KIT / 'template').as_posix() for p in (core.KIT / 'template').rglob('*') if p.is_file()} - {'routing-presets.json'} | set(upgrade.skills()) | set(upgrade.pointer_files()) | {'workspace.json', 'routing.json', 'vault/Project/Codebase map.md'}
    if dry_run:
        for name in sorted(outside): print('  ' + str(root / name), file=sys.stderr)
    else:  # the private files are ws's own; --dry-run lists each one
        print(f'  plus {len(outside)} private workspace files (ws start --dry-run lists them)', file=sys.stderr)
    imports = [] if no_import else memory_import.preview(repo, memory_dir, dry_run=dry_run)
    if not confirm(yes, dry_run, bool(imports)): return None
    memory_import.verify(imports)
    if '.codex/config.toml' not in desired and not core.client_connected(root, 'codex', global_only=True) and not path(repo, '.codex/config.toml').is_file(): raise core.WsError('Codex config disappeared during confirmation; retry ws start.')
    if path(repo, LINK).exists(): raise core.WsError('Setup record appeared during confirmation; keep it safe and review before ws start.')
    if any((path(repo, n).read_bytes() if path(repo, n).exists() else None) != data for n, data in before.items()): raise core.WsError('Local config changed during confirmation; review it before retrying.')
    tracked = subprocess.run(['git', '-C', str(repo), 'ls-files', '--', LINK, *desired], capture_output=True, encoding='utf-8', errors='replace', check=True).stdout.strip()
    if tracked: raise core.WsError('Start will not change tracked local files: ' + tracked.replace('\n', ', '))
    previous_exclude = exclude.read_bytes() if exclude.exists() else b''
    leftover = _without_stale_block(previous_exclude, core.digest_text(str(repo))[:12], exclude)  # refuses before anything is written
    if not root.exists(): core.init(root, repo.name, repos=[str(repo)], clients=[])
    owned = {n: dict(before=base64.b64encode(data).decode() if data is not None else None, sha=hashlib.sha256(data or b'').hexdigest()) for n, data in before.items()}
    directories = {p.relative_to(repo).as_posix() for n in desired for p in (repo / n).parents if repo in p.parents and not p.exists()}
    if leftover != previous_exclude: core.atomic_write(exclude, leftover); previous_exclude = leftover
    state = dict(kit_version=core.kit_meta()['version'], hook_packs=hook_packs(root), plugin=plugin, claude_config_dir=claude_dir(), codex_status='connected' if '.codex/config.toml' in desired else 'connected via global config' if core.client_connected(root, 'codex', global_only=True) else 'manual step pending', workspace=str(root), files=owned, complete=False, exclude_previous='', exclude_before=base64.b64encode(previous_exclude).decode(), assistants=clients, directories=sorted(directories, key=lambda n: n.count('/'), reverse=True), exclude=str(exclude), exclude_block=base64.b64encode(block).decode())
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
            target = core.task_path(root, task); text = core.read_exact(target)
            meta = core.parse_meta(text)
            template = core.section((core.KIT / 'template/vault/Templates/Task.md').read_text(encoding='utf-8'), 'Next action')
            if (core._local_claim_matches(root, task, meta) and meta.get('status') == 'ready'
                    and not meta.get('checkpoint_at') and core.section(text, 'Next action') == template):
                core.atomic_write(target, core.set_meta(core.set_section(text, 'Next action', ''), {'status': 'in_progress'}))
    memory_import.apply(root, repo, task, imports)
    state['complete'] = True; core.atomic_write(path(repo, LINK), json.dumps(state, indent=2) + '\n')
    return dict(root=str(root), repo=str(repo), already=False, assistants=[c for c in clients if not (plugin and c == 'claude')] + (['claude (plugin)'] if plugin else []), task=task, branch=current, codex_status=state['codex_status'], starter=starter(repo, root))
