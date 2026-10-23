"""Compact MCP recall cards with explicit bounded detail reads; no new tool catalog."""
import datetime
import re
from pathlib import Path
from . import core, knowledge


def _reports(root):
    return {str(path): 'report:' + str(i) for i, repo in enumerate(core.config(root).get('repos', []))
            for path in [core._graphify_report(core.repo_path(root, repo))] if path}


def _note(root, identifier, terms=()):
    metadata = {}
    if len(identifier) > 512: raise core.WsError('Recall ID is too long.')
    if re.fullmatch(r'report:\d{1,5}', identifier):
        path = next((Path(p) for p, key in _reports(root).items() if key == identifier), None)
        if path is None: raise core.WsError('Repository report no longer exists; search again.')
        raw = core.read_text(path, core.read_roots(root))
    elif identifier.startswith(('private:', 'team:')):
        layer, item = identifier.split(':', 1)
        if not core.ID_RE.fullmatch(item) or item.endswith('.local'): raise core.WsError('Invalid knowledge ID.')
        for name, base, team_id in knowledge._bases(root, layer):
            path = base / (item + '.md')
            if path.exists():
                row, raw = knowledge._read(root, path, name, team_id, include_all=True)
                metadata = {'title': row['summary'], 'date': row['date']}
                break
        else: raise core.WsError('No knowledge entry with that ID.')
    else:
        relative = Path(identifier)
        if relative.is_absolute() or '\\' in identifier or ':' in identifier or relative.suffix != '.md' or relative.stem.endswith('.local') or any(p.startswith('.') for p in relative.parts):
            raise core.WsError('Use a note ID returned by search_vault.')
        path = core.inside(root / relative, [core.vault(root)])
        if 'Runs' in relative.parts or any(core.is_link(p) for p in (path, *path.parents) if p == root or root in p.parents):
            raise core.WsError('Hidden, run-log or symlinked notes are not recall details.')
        raw = core.read_text(path, [core.vault(root)])
    if re.search(r'#private\b', raw, re.I): raise core.WsError('Note is marked private; no recall details returned.')
    body = core.localize_paths(core.plain_text(raw), root)
    body = ''.join(c for c in body if c.isprintable() or c.isspace())
    meta = {**core.parse_meta(body), **metadata}
    title = meta.get('title') or next((l.lstrip('# ').strip() for l in body.splitlines() if l.startswith('# ')), path.stem)
    date = meta.get('created', meta.get('date', '')) or datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc).date().isoformat()
    result = {'id': identifier, 'title': ' '.join(str(title).split())[:100], 'date': str(date)[:40],
            'content': body[:20000], 'truncated': len(body) > 20000, 'untrusted': True}
    if terms: result['_matches'] = any(word.lower() in body.lower() for word in terms)
    return result


def search(root, query='', category='', detail=''):
    root = Path(root).resolve()
    if detail: return _note(root, detail)
    reports = _reports(root); rows = []
    for hit in core.search(root, query, category=category):
        identifier = hit.get('key') or reports.get(hit['path'], hit['path'])
        if core.redact(identifier) != identifier: continue
        try: note = _note(root, identifier, re.findall(r'\w{3,}', query)[:core.MAX_QUERY_WORDS])
        except (core.WsError, OSError, ValueError): continue
        if not note.get('_matches'): continue
        rows.append({k: note[k] for k in ('id', 'title', 'date', 'untrusted')})
    return rows
