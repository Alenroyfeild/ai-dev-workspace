"""Categorized, explicitly saved knowledge; team text is untrusted context."""
import re
from . import core, scope, sharing

CATEGORIES = ('product', 'feature', 'domain', 'repo', 'runbook', 'other')


def category(value):
    if value not in CATEGORIES: raise core.WsError('Category must be ' + ', '.join(CATEGORIES) + '.')
    return value


def add(root, text, value='other', team_scope=False):
    return sharing.standalone(root, 'knowledge', text, team_scope, category(value))


def _bases(root, layer):
    if layer not in ('all', 'private', 'team'): raise core.WsError('Layer must be private, team or all.')
    bases = []
    if layer != 'team': bases.append(('private', sharing._safe(root, core.vault(root) / 'Knowledge'), ''))
    link = core.config(root).get('team_workspace')
    if layer != 'private' and link:
        if not isinstance(link, dict) or link.get('path') != '.ws/team': raise core.WsError('Invalid team link; run ws team link.')
        clone = sharing._safe(root, root / '.ws/team')
        import json
        manifest = json.loads(sharing._text(sharing._safe(root, clone / 'team.json')))
        if (not isinstance(manifest, dict) or manifest.get('kind') != 'ai-dev-workspace-team' or
                manifest.get('schema_version') != 1 or not re.fullmatch(r'[a-f0-9]{32}', str(manifest.get('id', ''))) or
                manifest.get('id') != link.get('id')): raise core.WsError('Team identity changed; link again.')
        bases.append(('team', sharing._safe(root, clone / 'entries'), link['id']))
    return bases


def _read(root, path, layer, team_id):
    path = sharing._safe(root, path)
    if path.stat().st_size > 1024 * 1024: raise core.WsError('Knowledge entry exceeds the 1 MiB read limit.')
    if layer == 'private': _, _, _, raw, _, end, meta = scope._read(root, 'knowledge:' + path.stem)
    else:
        raw = core.read_text(path, [root], errors='strict').replace('\r\n', '\n')
        match = re.match(r'\A---\n.*?\n---(?=\n|\Z)', raw, re.S)
        if not match or core.conflicted(raw): raise core.WsError('Invalid or conflicted team entry.')
        keys = re.findall(r'^([A-Za-z_][A-Za-z0-9_]*):', match.group(), re.M)
        if len(keys) != len(set(keys)): raise core.WsError('Duplicate team metadata keys.')
        meta = core.parse_meta(match.group() + '\n'); end = match.end()
        if meta.get('id') != path.stem or meta.get('team') != team_id: raise core.WsError('Team entry identity does not match.')
    value = meta.get('category', 'other')
    if layer == 'team' and not (meta.get('source', '').startswith('knowledge:') or
                                 (value == 'runbook' and meta.get('source', '').startswith('task:'))): return None, ''
    category(value)
    body = re.sub(r'<!-- ws:captured:.*?<!-- /ws:captured -->', '', raw[end:], flags=re.S)
    if 'ws:captured:' in body or '/ws:captured' in body: raise core.WsError('Malformed capture block.')
    body = sharing.portable(root, body)
    row = {'key': layer + ':' + path.stem, 'id': path.stem, 'layer': layer, 'category': value,
           'summary': ' '.join(body.split()[:30]), 'author': sharing.portable(root, meta.get('author', 'local'))[:40],
           'source_sha': core.digest_text(raw), 'team': team_id, 'date': sharing.portable(root, meta.get('date', meta.get('created', '')))[:40],
           'source': sharing.portable(root, meta.get('source', 'knowledge:' + path.stem))[:100], 'untrusted': layer == 'team', 'path': path.relative_to(root).as_posix()}
    return row, body


def list_entries(root, value='', layer='all'):
    if value: category(value)
    rows, warnings = [], []
    for name, base, team_id in _bases(root, layer):
        scanned = 0
        for path in sorted(base.glob('*.md')):
            if path.name == 'INDEX.md' or path.name.endswith('.index.md') or path.stem.endswith('.local'): continue
            if not core.ID_RE.fullmatch(path.stem): continue
            if scanned >= 100: warnings.append('Catalog examines at most 100 entries per layer; use ws know show for omitted IDs.'); break
            scanned += 1
            try: row, _ = _read(root, path, name, team_id)
            except (core.WsError, OSError, ValueError):
                warnings.append(f'{name}:{path.stem}: entry unreadable, unsafe or conflicted; excluded.'); continue
            if row is not None and (not value or row['category'] == value): rows.append(row)
    return {'entries': rows, 'warnings': warnings}


def show(root, key):
    layer, separator, identifier = key.partition(':')
    if not separator: layer, identifier = 'private', key
    if layer not in ('private', 'team') or not core.ID_RE.fullmatch(identifier) or identifier.endswith('.local'):
        raise core.WsError('Use private:<ID> or team:<ID>.')
    for name, base, team_id in _bases(root, layer):
        path = base / (identifier + '.md')
        if path.exists():
            row, body = _read(root, path, name, team_id)
            if row is None: raise core.WsError('This team entry is not knowledge or a task runbook.')
            return {**row, 'content': body}
    raise core.WsError('No safe knowledge entry with that layer and ID; run ws know list.')


def search(root, query, value):
    words = re.findall(r'\w{3,}', query.lower())
    if not words: raise core.WsError('Search needs a word of 3+ letters.')
    hits = []
    for row in list_entries(root, value)['entries']:
        body = show(root, row['key'])['content']; score = sum(body.lower().count(w) for w in words)
        if score: hits.append({**row, 'score': score, 'lines': [line[:160] for line in body.splitlines() if any(w in line.lower() for w in words)][:3]})
    return sorted(hits, key=lambda h: -h['score'])[:20]
