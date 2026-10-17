"""Managed summary snapshots; no network and no execution of shared text."""
import json
import re
from . import core, sharing

HEAD, TAIL = '<!-- ws:cards -->', '<!-- /ws:cards -->'
FIELDS = ('key', 'id', 'layer', 'category', 'summary', 'author', 'source_sha', 'revision', 'team', 'date', 'source', 'path', 'tags', 'outcome')


def managed(root, path, body, public=False):
    path = sharing._safe(root, path)
    if path.exists() and path.stat().st_size > 1024 * 1024: raise core.WsError('Index artifact exceeds 1 MiB.')
    old = sharing._text(path)
    checked = old.replace(HEAD, '').replace(TAIL, '').replace('\r\n', '\n')
    if public and sharing.portable(root, checked) != checked.strip():
        raise core.WsError('Shared index contains nonportable/private text; review it locally first.')
    if old:
        if old.count(HEAD) != 1 or old.count(TAIL) != 1 or old.index(HEAD) > old.index(TAIL):
            raise core.WsError('Unmanaged or malformed index/card; preserve it and move it before rebuilding.')
        start, end = old.index(HEAD), old.index(TAIL) + len(TAIL)
        text = old[:start] + (HEAD + '\n' + body + '\n' + TAIL if body is not None else '') + old[end:]
    else: text = HEAD + '\n' + body + '\n' + TAIL + '\n' if body is not None else ''
    return text if text.strip() else None


def load(root, path, layer, team_id):
    card = sharing._safe(root, path.with_suffix('.index.md'))
    if not card.exists() or card.stat().st_size > 16384 or card.stat().st_mtime_ns < path.stat().st_mtime_ns: return None
    try:
        raw = sharing._text(card)
        if raw.count(HEAD) != 1 or raw.count(TAIL) != 1 or raw.index(HEAD) > raw.index(TAIL): return None
        data = json.loads(raw.split(HEAD)[1].split(TAIL)[0]); row = data['row']; counts = data['counts']
        if data['schema'] != 1 or data['source_bytes'] != path.stat().st_size: return None
        if not all(isinstance(row[k], str) for k in FIELDS): return None
        if row['id'] != path.stem or row['layer'] != layer or row['team'] != team_id: return None
        if not re.fullmatch(r'[a-f0-9]{64}', row['revision']) or (row['source_sha'] and not re.fullmatch(r'[a-f0-9]{64}', row['source_sha'])): return None
        if not isinstance(counts, dict) or len(counts) > 24 or any(not re.fullmatch(r'\w{3,}', k) or len(k.encode()) > 32 or type(v) is not int or not 0 <= v <= 1024*1024 for k,v in counts.items()): return None
        from .knowledge import category
        category(row['category'])
        caps = {'summary':240, 'author':40, 'date':40, 'source':100, 'tags':120, 'outcome':180}
        clean = {k: sharing.portable(root, row[k])[:caps.get(k,2048)] for k in FIELDS}
        return {**clean, 'key': layer + ':' + path.stem, 'path': path.relative_to(root).as_posix(),
                'untrusted': layer == 'team', 'summary_snapshot': True, '_counts': counts}
    except (KeyError, ValueError, TypeError, RecursionError, core.WsError): return None


def index_body(rows, public, prefix=None):
    prefix = ('entries/' if public else '') if prefix is None else prefix
    lines = ['# Shared memory index' if public else '# Private knowledge index']
    lines += [f'- [{r["id"]}]({prefix}{r["id"]}.md) ({r["category"]}; {r["author"]}) {r["summary"]}'.replace('<!--','&lt;!--') for r in rows]
    return '\n'.join(lines)


def plan(root, layer, replacements=None):
    from . import knowledge
    overrides = replacements or {}; changes = {}; public = layer == 'team'
    for name, base, team_id in knowledge._bases(root, layer):
        paths = {p for p in base.glob('*.md') if p.name != 'INDEX.md' and not p.name.endswith('.index.md') and not p.stem.lower().endswith('.local')}
        paths.update(overrides)
        if len(paths) > 1000: raise core.WsError('Index generation is limited to 1000 sources per layer.')
        rows = []
        for path in sorted(paths):
            if not core.ID_RE.fullmatch(path.stem): continue
            card = path.with_suffix('.index.md')
            if path in overrides and overrides[path] is None:
                text = managed(root, card, None, public)
            else:
                row, body = knowledge._read(root, path, name, team_id, summary=True, include_all=True, raw=overrides.get(path))
                row['summary'] = row['summary'][:240]; rows.append(row)
                counts = row.get('_counts')
                if counts is None:
                    words = sorted({w for w in re.findall(r'\w{3,}', (row['summary']+' '+row['tags']+' '+row['outcome']).lower()) if len(w.encode()) <= 32})[:24]
                    counts = {w: body.lower().count(w) for w in words}
                size = len(overrides[path].encode()) if path in overrides else path.stat().st_size
                payload = {'schema': 1, 'source_bytes': size, 'row': {k: row[k] for k in FIELDS}, 'counts': counts}
                encoded = json.dumps(payload, sort_keys=True, indent=2).replace('<', '\\u003c').replace('>', '\\u003e')
                if len(encoded.encode()) > 16000: raise core.WsError('Card exceeds its bounded size; shorten source metadata.')
                text = managed(root, card, encoded, public)
            if text != (sharing._text(card) if card.exists() else None): changes[card] = text
        index = base.parent/'INDEX.md' if public else base/'INDEX.md'
        text = managed(root, index, index_body(rows, public), public)
        if text != (sharing._text(index) if index.exists() else None): changes[index] = text
    return changes


def write(root, changes):
    old = {p: sharing._text(sharing._safe(root,p)) if p.exists() else None for p in changes}; touched = []
    try:
        for p, text in changes.items():
            sharing._safe(root,p)
            if text is None: p.unlink(missing_ok=True)
            else: core.atomic_write(p,text)
            touched.append(p)
    except (OSError, core.WsError):
        for p in reversed(touched):
            sharing._safe(root,p)
            if old[p] is None: p.unlink(missing_ok=True)
            else: core.atomic_write(p,old[p])
        raise core.WsError('Index/copy write failed; prior files restored. Preview again.')
