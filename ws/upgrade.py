"""Previewable, local workspace upgrades; ownership is explicit, never inferred."""
import difflib
import json
import re
import shlex
from pathlib import Path
from . import core


def block(body, name='rules'):
    return f'<!--ws:managed:{name}:{core.kit_meta()["version"]}-->\n{body.rstrip()}\n<!--/ws:managed:{name}-->\n'


def skill(text, name):
    header, body = text[4:].split('---\n', 1)
    return '---\n' + header + '---\n' + block(body, 'skill-' + name)


def skills():
    return {f'{client}/skills/{p.parent.name}/SKILL.md': skill(p.read_text(encoding='utf-8'), p.parent.name)
            for client in ('.claude', '.agents') for p in sorted((core.KIT / 'skills').glob('*/SKILL.md')) if p.parent.name in ('handoff', 'pickup', 'lesson')}


def pointer_files():
    return {'.github/copilot-instructions.md': block('Follow the repository root AGENTS.md for project rules.', 'copilot-instructions'),
            'GEMINI.md': block('Follow the repository root AGENTS.md for project rules.', 'gemini-instructions')}


def fingerprint(root):
    from .orchestration import routing_template
    return core.digest_text((core.KIT / 'template/AGENTS.md').read_text(encoding='utf-8') + routing_template() + json.dumps(skills(), sort_keys=True) + json.dumps(pointer_files(), sort_keys=True) + json.dumps([core.memory_hooks(root, c) for c in ('claude', 'codex', 'cursor', 'gemini', 'vscode')], sort_keys=True))


def markdown(old, new):
    name = re.search(r'<!--\s*ws:managed:([^:]+):', new).group(1)
    pattern = rf'<!--\s*ws:managed:{re.escape(name)}:[^\n]*?-->\r?\n.*?<!--\s*/ws:managed:{re.escape(name)}\s*-->(?:\r?\n)?'
    if len(re.findall(r'<!--\s*ws:managed:' + re.escape(name) + ':', old)) != 1 or len(re.findall(r'<!--\s*/ws:managed:' + re.escape(name) + r'\s*-->', old)) != 1:
        return None
    candidate = re.sub(pattern, lambda m: re.search(pattern, new, re.S).group(), old, count=1, flags=re.S)
    return candidate if re.search(pattern, old, re.S) else None


def managed_command(command):
    """Our hook command, in the old `env WS_ROOT=<dir> python bin/ws ...` form or the portable
    `python bin/ws --workspace-root <dir> ...` form (Windows-safe)."""
    try:
        parts = shlex.split(command)
        if parts[:1] == ['powershell.exe']: parts = core.encoded_hook_args(parts)
    except ValueError: return False
    if len(parts) >= 2 and parts[0] == 'env' and parts[1].startswith('WS_ROOT='):
        parts = parts[2:]
    if len(parts) < 4 or re.fullmatch(r'python(?:\d+(?:\.\d+)?)?(?:\.exe)?', Path(parts[0]).name) is None:
        return False
    if Path(parts[1]).name != 'ws' or Path(parts[1]).parent.name != 'bin':
        return False
    rest = parts[2:]
    if rest[:1] == ['--workspace-root']:
        rest = rest[2:]
    return (len(rest) in (2, 4) and rest[0] in ('brief', 'nudge', 'paste') and rest[1] == '--hook'
            and (len(rest) == 2 or rest[2] == '--client' and rest[3] in ('claude', 'codex', 'cursor', 'gemini', 'vscode')))


def hooks(old, new):
    """Replace only our hook commands (recognized by `ws brief|nudge --hook`); keep every other setting."""
    try:
        data, desired = json.loads(old), json.loads(new)['hooks']
        found, changed = {}, False
        for event, groups in data.get('hooks', {}).items():
            for index, group in enumerate(groups):
                for i, hook in enumerate(group.get('hooks', [])):
                    if event in desired and isinstance(hook.get('command'), str) and managed_command(hook['command']):
                        found[event] = found.get(event, 0) + 1
                        want = desired[event][0]['hooks'][0]
                        changed |= hook != want
                        group['hooks'][i] = want
                if event in desired and isinstance(group.get('command'), str) and managed_command(group['command']):
                    found[event] = found.get(event, 0) + 1
                    want = desired[event][0]; changed |= group != want; groups[index] = want
        additions = set(desired) - set(found)
        if additions - {'UserPromptSubmit', 'beforeSubmitPrompt', 'BeforeAgent'} or any(n != 1 for n in found.values()):
            return None  # Missing lifecycle hooks or duplicate handlers need review.
        for event in additions:
            groups = data.setdefault('hooks', {}).get(event, [])
            if not isinstance(groups, list): return None
            data['hooks'][event] = groups + desired[event]
            changed = True
        return json.dumps(data, indent=2) + '\n' if changed else old
    except (ValueError, AttributeError, KeyError, TypeError, IndexError):
        return None


def routing(old, new):
    try:
        json.loads(old); marker = r'"_ws_managed"\s*:\s*'
        matches = list(re.finditer(marker, old))
        if len(matches) != 1: return None
        start = matches[0].end(); previous, end = json.JSONDecoder().raw_decode(old, start)
        value = json.loads(new)['_ws_managed']
        if not isinstance(previous, dict) or not isinstance(previous.get('providers', {}), dict): return None
        # Provider data can contain user model mappings; preserve them during migration.
        for name, settings in previous.get('providers', {}).items():
            value['providers'][name] = dict(value.get('providers', {}).get(name, {}), **settings)
        if previous == value: return old
        return old[:start] + json.dumps(value, indent=2) + old[end:]
    except (ValueError, KeyError, TypeError): return None


def upgrade(root, dry_run=False):
    root = Path(root).resolve()
    def safe(path):
        if any(p.is_symlink() for p in (path, *path.parents) if p != root and root in p.parents):
            raise core.WsError('Upgrade refuses symlinks: ' + str(path.relative_to(root)))
        if any(p.exists() and not p.is_dir() for p in path.parents if p != root and root in p.parents):
            raise core.WsError('Upgrade destination has a non-directory parent: ' + str(path.relative_to(root)))
    safe(root / '.ws')
    safe(root / '.ws/backups')
    for directory in (root / '.ws', root / '.ws/backups', root / '.ws/claims'):
        if directory.exists() and not directory.is_dir(): raise core.WsError('Upgrade requires a directory: ' + str(directory.relative_to(root)))
    with (core.contextlib.nullcontext() if dry_run else core.lock(root)):
        cfg = core.config(root)
        if cfg.get('schema_version', 1) > 2: raise core.WsError('Workspace schema is newer than this upgrade supports.')
        rules = block((core.KIT / 'template/AGENTS.md').read_text(encoding='utf-8'))
        for pack in cfg.get('packs', []):
            if pack not in cfg.get('local_packs', {}): rules = core.pack_rules(rules, pack)
        from .orchestration import routing_template
        clients = {'.claude/settings.json': 'claude', '.codex/hooks.json': 'codex', '.cursor/hooks.json': 'cursor', '.gemini/settings.json': 'gemini', '.github/hooks/ai-dev-workspace.json': 'vscode'}
        desired = {'AGENTS.md': rules, 'routing.json': routing_template(), **{p: json.dumps(core.memory_hooks(root, c), indent=2) + '\n'
                   for p, c in clients.items() if c in ('claude', 'codex') or (root / p).exists()}, **skills(), **pointer_files()}
        from . import packs
        private = packs.desired(root, cfg, desired)
        pending, operations = [], []
        for relative, candidate in desired.items():
            path = root / relative; safe(path)
            if path.is_dir(): raise core.WsError('Upgrade expected a file: ' + relative)
            before = path.read_bytes() if path.exists() else b''
            if path.exists():
                try:
                    if relative in private:
                        merged = candidate if core.hashlib.sha256(before).hexdigest() == private[relative] else None
                    else:
                        merged = routing(before.decode(), candidate) if relative == 'routing.json' else hooks(before.decode(), candidate) if relative.endswith('.json') else markdown(before.decode(), candidate)
                        if relative == 'AGENTS.md': merged = packs.merge_rules(before.decode(), merged, cfg)
                except UnicodeError: merged = None
                if merged is None:
                    pending.append(relative)
                    number = 0
                    while True:
                        path = root / (relative + '.ws-new' + (f'.{number}' if number else '')); safe(path)
                        if not path.exists() or path.read_bytes() == (candidate if isinstance(candidate, bytes) else candidate.encode('utf-8')): break
                        number += 1
                    before = path.read_bytes() if path.exists() else b''
                else: candidate = merged
            if before != (candidate if isinstance(candidate, bytes) else candidate.encode('utf-8')): operations.append((path, before, (candidate if isinstance(candidate, bytes) else candidate.encode('utf-8'))))
        cfg.update(schema_version=2, kit_version=core.kit_meta()['version'], content_version=fingerprint(root), upgrade_pending=pending)
        path = root / 'workspace.json'; safe(path)
        before = path.read_bytes(); after = (json.dumps(cfg, indent=2) + '\n').encode()
        if before != after: operations.append((path, before, after))
        claims = root / '.ws/claims'; safe(claims)
        changes = [dict(path=p.relative_to(root).as_posix(), action='write', diff=''.join(difflib.unified_diff(
            old.decode(errors='replace').splitlines(True), new.decode(errors='replace').splitlines(True),
            fromfile=p.relative_to(root).as_posix(), tofile=p.relative_to(root).as_posix()))) for p, old, new in operations]
        backups = []
        if not dry_run and changes:
            stamp = core.now().replace(':', '').replace('+', '-') + '-' + core.uuid.uuid4().hex[:8]
            for path, old, new in operations:
                if path.exists() and path.read_bytes() != old: raise core.WsError('File changed during upgrade; run dry-run again.')
                if old:
                    backup = root / '.ws/backups' / stamp / path.relative_to(root); safe(backup)
                    core.atomic_write(backup, old); backups.append(backup.relative_to(root).as_posix())
                core.atomic_write(path, new)
        if not dry_run:
            claims.mkdir(parents=True, exist_ok=True)  # local, gitignored state: created silently, not reported as an upgrade
        return dict(dry_run=dry_run, changes=changes, pending=pending, backups=backups)
