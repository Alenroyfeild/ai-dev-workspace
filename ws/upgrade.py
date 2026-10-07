"""Previewable, local workspace upgrades; ownership is explicit, never inferred."""
import difflib
import json
import re
from pathlib import Path
from . import core


def block(body, name='rules'):
    return f'<!--ws:managed:{name}:{core.kit_meta()["version"]}-->\n{body.rstrip()}\n<!--/ws:managed:{name}-->\n'


def skill(text, name):
    header, body = text[4:].split('---\n', 1)
    return '---\n' + header + '---\n' + block(body, 'skill-' + name)


def skills():
    return {f'{client}/skills/{p.parent.name}/SKILL.md': skill(p.read_text(), p.parent.name)
            for client in ('.claude', '.agents') for p in sorted((core.KIT / 'skills').glob('*/SKILL.md')) if p.parent.name in ('handoff', 'pickup', 'lesson')}


def fingerprint(root):
    from .orchestration import routing_template
    return core.digest_text((core.KIT / 'template/AGENTS.md').read_text() + routing_template() + json.dumps(skills(), sort_keys=True) + json.dumps(core.memory_hooks(root), sort_keys=True))


def markdown(old, new):
    name = re.search(r'<!--\s*ws:managed:([^:]+):', new).group(1)
    pattern = rf'<!--\s*ws:managed:{re.escape(name)}:[^\n]*?-->\n.*?<!--\s*/ws:managed:{re.escape(name)}\s*-->\n?'
    if len(re.findall(r'<!--\s*ws:managed:' + re.escape(name) + ':', old)) != 1 or len(re.findall(r'<!--\s*/ws:managed:' + re.escape(name) + r'\s*-->', old)) != 1:
        return None
    candidate = re.sub(pattern, lambda m: re.search(pattern, new, re.S).group(), old, count=1, flags=re.S)
    return candidate if re.search(pattern, old, re.S) else None


MANAGED_HOOK = re.compile(r'(?:^|\s)(?:brief|nudge) --hook$')


def hooks(old, new):
    """Replace only our hook commands (recognized by `ws brief|nudge --hook`); keep every other setting."""
    try:
        data, desired = json.loads(old), json.loads(new)['hooks']
        found, changed = {}, False
        for event, groups in data.get('hooks', {}).items():
            for group in groups:
                for i, hook in enumerate(group.get('hooks', [])):
                    if event in desired and isinstance(hook.get('command'), str) and MANAGED_HOOK.search(hook['command']):
                        found[event] = found.get(event, 0) + 1
                        want = desired[event][0]['hooks'][0]
                        changed |= hook != want
                        group['hooks'][i] = want
        if set(found) != set(desired) or any(n != 1 for n in found.values()):
            return None  # missing or duplicated managed hooks: stage a proposal instead of guessing
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
        if previous == value: return old
        return old[:start] + json.dumps(value, indent=2) + old[end:]
    except (ValueError, KeyError): return None


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
        rules = block((core.KIT / 'template/AGENTS.md').read_text())
        for pack in cfg.get('packs', []): rules = core.pack_rules(rules, pack)
        from .orchestration import routing_template
        desired = {'AGENTS.md': rules, 'routing.json': routing_template(), **{p: json.dumps(core.memory_hooks(root), indent=2) + '\n'
                   for p in ('.claude/settings.json', '.codex/hooks.json')}, **skills()}
        pending, operations = [], []
        for relative, candidate in desired.items():
            path = root / relative; safe(path)
            if path.is_dir(): raise core.WsError('Upgrade expected a file: ' + relative)
            before = path.read_bytes() if path.exists() else b''
            if path.exists():
                try: merged = routing(before.decode(), candidate) if relative == 'routing.json' else hooks(before.decode(), candidate) if relative.endswith('.json') else markdown(before.decode(), candidate)
                except UnicodeError: merged = None
                if merged is None:
                    pending.append(relative)
                    number = 0
                    while True:
                        path = root / (relative + '.ws-new' + (f'.{number}' if number else '')); safe(path)
                        if not path.exists() or path.read_bytes() == candidate.encode(): break
                        number += 1
                    before = path.read_bytes() if path.exists() else b''
                else: candidate = merged
            if before != candidate.encode(): operations.append((path, before, candidate.encode()))
        cfg.update(schema_version=2, kit_version=core.kit_meta()['version'], content_version=fingerprint(root), upgrade_pending=pending)
        path = root / 'workspace.json'; safe(path)
        before = path.read_bytes(); after = (json.dumps(cfg, indent=2) + '\n').encode()
        if before != after: operations.append((path, before, after))
        claims = root / '.ws/claims'; safe(claims)
        changes = [dict(path=str(p.relative_to(root)), action='write', diff=''.join(difflib.unified_diff(
            old.decode(errors='replace').splitlines(True), new.decode().splitlines(True),
            fromfile=str(p.relative_to(root)), tofile=str(p.relative_to(root))))) for p, old, new in operations]
        backups = []
        if not dry_run and changes:
            stamp = core.now().replace(':', '').replace('+', '-') + '-' + core.uuid.uuid4().hex[:8]
            for path, old, new in operations:
                if path.exists() and path.read_bytes() != old: raise core.WsError('File changed during upgrade; run dry-run again.')
                if old:
                    backup = root / '.ws/backups' / stamp / path.relative_to(root); safe(backup)
                    core.atomic_write(backup, old.decode('utf-8')); backups.append(str(backup.relative_to(root)))
                core.atomic_write(path, new.decode('utf-8'))
        if not dry_run:
            claims.mkdir(parents=True, exist_ok=True)  # local, gitignored state: created silently, not reported as an upgrade
        return dict(dry_run=dry_run, changes=changes, pending=pending, backups=backups)
