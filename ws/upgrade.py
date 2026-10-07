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
    return core.digest_text((core.KIT / 'template/AGENTS.md').read_text() + json.dumps(skills(), sort_keys=True) + json.dumps(core.memory_hooks(root), sort_keys=True))


def markdown(old, new):
    name = re.search(r'<!--\s*ws:managed:([^:]+):', new).group(1)
    pattern = rf'<!--\s*ws:managed:{re.escape(name)}:[^\n]*?-->\n.*?<!--\s*/ws:managed:{re.escape(name)}\s*-->\n?'
    if len(re.findall(r'<!--\s*ws:managed:' + re.escape(name) + ':', old)) != 1 or len(re.findall(r'<!--\s*/ws:managed:' + re.escape(name) + r'\s*-->', old)) != 1:
        return None
    candidate = re.sub(pattern, lambda m: re.search(pattern, new, re.S).group(), old, count=1, flags=re.S)
    return candidate if re.search(pattern, old, re.S) else None


def hooks(old, new):
    try:
        json.loads(old)
        desired = {event: groups[0]['hooks'][0] for event, groups in json.loads(new)['hooks'].items()}
        spans, quoted, escaped = [], False, False
        for i, char in enumerate(old):
            if quoted:
                if escaped: escaped = False
                elif char == '\\': escaped = True
                elif char == '"': quoted = False
            elif char == '"': quoted = True
            elif char == '{':
                value, end = json.JSONDecoder().raw_decode(old, i)
                marker = value.get('statusMessage', '')
                match = re.fullmatch(r'ws:managed:(SessionStart|PreCompact|Stop):[^\n]+', marker) if isinstance(marker, str) else None
                if match: spans.append((i, end, match[1]))
        if len(spans) != len(desired) or {event for _, _, event in spans} != set(desired): return None
        for start, end, event in reversed(spans):
            indent = start - old.rfind('\n', 0, start) - 1
            replacement = json.dumps(desired[event], indent=2).replace('\n', '\n' + ' ' * indent)
            old = old[:start] + replacement + old[end:]
        json.loads(old)
        return old
    except (ValueError, AttributeError, KeyError):
        return None


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
        desired = {'AGENTS.md': rules, **{p: json.dumps(core.memory_hooks(root), indent=2) + '\n'
                   for p in ('.claude/settings.json', '.codex/hooks.json')}, **skills()}
        pending, operations = [], []
        for relative, candidate in desired.items():
            path = root / relative; safe(path)
            if path.is_dir(): raise core.WsError('Upgrade expected a file: ' + relative)
            before = path.read_bytes() if path.exists() else b''
            if path.exists():
                try: merged = hooks(before.decode(), candidate) if relative.endswith('.json') else markdown(before.decode(), candidate)
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
        if not claims.exists(): changes.append(dict(path='.ws/claims/', action='mkdir', diff='mkdir .ws/claims/\n'))
        backups = []
        if not dry_run and changes:
            stamp = core.now().replace(':', '').replace('+', '-') + '-' + core.uuid.uuid4().hex[:8]
            for path, old, new in operations:
                if path.exists() and path.read_bytes() != old: raise core.WsError('File changed during upgrade; run dry-run again.')
                if old:
                    backup = root / '.ws/backups' / stamp / path.relative_to(root); safe(backup)
                    core.atomic_write(backup, old.decode('utf-8')); backups.append(str(backup.relative_to(root)))
                core.atomic_write(path, new.decode('utf-8'))
            claims.mkdir(parents=True, exist_ok=True)
        return dict(dry_run=dry_run, changes=changes, pending=pending, backups=backups)
