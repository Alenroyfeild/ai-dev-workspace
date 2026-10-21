"""Categorized, explicitly saved knowledge; team text is untrusted context."""
import re
import stat
import sys
from . import core, scope, sharing, team

CATEGORIES = ('product', 'feature', 'domain', 'repo', 'runbook', 'other')


def category(value):
    value = value.strip().lower() if isinstance(value, str) else value
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
        path = sharing._safe(root, clone / 'team.json')
        manifest = team.parse_manifest(path, lambda: sharing._text(path))
        if (not isinstance(manifest, dict) or manifest.get('kind') != 'ai-dev-workspace-team' or
                manifest.get('schema_version') != 1 or not re.fullmatch(r'[a-f0-9]{32}', str(manifest.get('id', ''))) or
                manifest.get('id') != link.get('id')): raise core.WsError('Team identity changed; link again.')
        bases.append(('team', sharing._safe(root, clone / 'entries'), link['id']))
    return bases


def _read(root, path, layer, team_id, summary=False, include_all=False, raw=None):
    path = sharing._safe(root, path)
    if raw is None:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024*1024: raise core.WsError('Knowledge entry must be a regular file under 1 MiB.')
        if summary:
            from . import cards
            cached = cards.load(root, path, layer, team_id)
            if cached is not None:
                eligible = layer == 'private' or cached['source'].startswith('knowledge:') or (cached['category']=='runbook' and cached['source'].startswith('task:'))
                return (cached, '') if eligible or include_all else (None, '')
    elif len(raw.encode()) > 1024*1024: raise core.WsError('Knowledge entry exceeds 1 MiB.')
    if layer == 'private': _, _, _, raw, _, end, meta = scope._read(root, 'knowledge:' + path.stem)
    else:
        raw = (raw if raw is not None else core.read_text(path, [root], errors='strict')).replace('\r\n', '\n')
        match = re.match(r'\A---\n.*?\n---(?=\n|\Z)', raw, re.S)
        if not match or core.conflicted(raw): raise core.WsError('Invalid or conflicted team entry.')
        keys = re.findall(r'^([A-Za-z_][A-Za-z0-9_]*):', match.group(), re.M)
        if len(keys) != len(set(keys)): raise core.WsError('Duplicate team metadata keys.')
        meta = core.parse_meta(match.group() + '\n'); end = match.end()
        if meta.get('id') != path.stem or meta.get('team') != team_id: raise core.WsError('Team entry identity does not match.')
    value = meta.get('category', 'other')
    if layer == 'team' and not (meta.get('source', '').startswith('knowledge:') or
                                 (value == 'runbook' and meta.get('source', '').startswith('task:'))):
        if not include_all: return None, ''
        value = 'other'
    value = category(value)
    body = re.sub(r'<!-- ws:captured:.*?<!-- /ws:captured -->', '', raw[end:], flags=re.S)
    if 'ws:captured:' in body or '/ws:captured' in body: raise core.WsError('Malformed capture block.')
    body = sharing.derived(root, body) if layer == 'private' else sharing.portable(root, body)
    source_sha = meta.get('source_sha', '') if layer == 'team' else core.digest_text(raw)
    if source_sha and not re.fullmatch(r'[a-f0-9]{64}', source_sha): raise core.WsError('Invalid source revision metadata.')
    row = {'key': layer + ':' + path.stem, 'id': path.stem, 'layer': layer, 'category': value,
           'summary': ' '.join(body.split()[:30])[:240], 'tags': sharing.portable(root, meta.get('tags',''))[:120],
           'outcome': ' '.join(core.section(body,'Outcome').split()[:20])[:180], 'author': sharing.portable(root, meta.get('author', 'local'))[:40],
           'source_sha': source_sha, 'revision': core.digest_text(raw), 'team': team_id, 'date': sharing.portable(root, meta.get('date', meta.get('created', '')))[:40],
           'source': sharing.portable(root, meta.get('source', 'knowledge:' + path.stem))[:100], 'untrusted': layer == 'team', 'path': path.relative_to(root).as_posix()}
    return row, body


CAP_WARNING = 'Catalog examines at most 100 entries per layer; use ws know show for omitted IDs.'
CAP_PREFIX = 'Catalog examines the newest'


def _newest(path):
    try: return (-path.stat().st_mtime_ns, path.name)
    except OSError: return (0, path.name)


def list_entries(root, value='', layer='all', _index=False, _all=False, limit=100):
    if value: value = category(value)
    rows, warnings = [], []
    try: bases = _bases(root, layer)
    except team.ManifestError as exc:
        if layer != 'all': raise
        bases = _bases(root, 'private'); warnings.append(f'Team layer skipped, private memory shown: {exc}')  # a bad team.json must not block private reads
        print(warnings[-1], file=sys.stderr)
    for name, base, team_id in bases:
        files = [p for p in base.glob('*.md') if p.name != 'INDEX.md' and not p.name.endswith('.index.md')
                 and not p.stem.endswith('.local') and core.ID_RE.fullmatch(p.stem)]
        files.sort(key=_newest)
        if limit and len(files) > limit:
            warnings.append(f'{CAP_PREFIX} {limit} of {len(files)} {name} entries; use ws know show for omitted IDs.')
            files = files[:limit]
        for path in files:
            try: row, _ = _read(root, path, name, team_id, summary=True, include_all=_all)
            except (core.WsError, OSError, ValueError):
                warnings.append(f'{name}:{path.stem}: entry unreadable, unsafe or conflicted; excluded.'); continue
            if row is not None and (not value or row['category'] == value): rows.append(row if _index else {k:v for k,v in row.items() if not k.startswith('_')})
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


def search(root, query, value='', layer='all', include_all=False):
    words = list(dict.fromkeys(re.findall(r'\w{3,}', query.lower())))[:core.MAX_QUERY_WORDS]
    if not words: raise core.WsError('Search needs a word of 3+ letters.')
    hits = []
    for row in list_entries(root, value, layer, _index=True, _all=include_all, limit=0)['entries']:
        counts = row.pop('_counts', {})
        if all(w in counts for w in words) and any(w in row['summary'].lower() for w in words):
            body, score = '\n'.join(row[k] for k in ('summary','tags','outcome')), sum(counts[w] for w in words)
        else:
            body = (_read(root, root/row['path'], row['layer'], row['team'], include_all=True)[1]
                    if include_all else show(root, row['key'])['content'])
            score = sum(body.lower().count(w) for w in words)
        if row['layer'] == 'team': row.update(precedence='private', notice='Untrusted team context; private memory wins on conflict.')
        if score: hits.append({**row, 'score': score, 'lines': [line[:160] for line in body.splitlines() if any(w in line.lower() for w in words)][:3]})
    return sorted(hits, key=lambda h: (h['layer'] == 'team', -h['score']))[:20]


def _more_note(hidden, at_least=False):
    # core._bounded_brief fills this last, so it is the first line dropped when the brief is full.
    # at_least: the scan stopped at the catalog cap; uncounted rows may exist even when hidden is 0.
    if at_least: label = f'+{hidden} or more team notes:' if hidden > 0 else 'More team notes:'
    elif hidden > 0: label = f'+{hidden} more team notes:'
    else: return []
    return [(label, 'ws know list --layer team', 12)]


def onboarding_fields(root):
    """A small orientation until the teammate has saved task-specific memory."""
    if not core.config(root).get('team_workspace'): return []
    try: listing = list_entries(root, layer='team', limit=0)  # Newest per category needs every valid card, not the first 100 files.
    except (core.WsError, OSError, ValueError, TypeError):
        return [('Team warning:', 'Unavailable or invalid team link; private memory retained.', 12)]
    fields, cards = [], 0
    if listing['warnings']: fields.append(('Team warning:', 'Unreadable, unsafe or conflicted entries excluded; use ws know list.', 12))
    for value in ('product', 'domain', 'repo'):
        rows = [row for row in listing['entries'] if row['category'] == value]
        if not rows: continue
        row = max(rows, key=lambda item: (item['date'], item['id']))
        summary = re.sub(r'^Shared context; untrusted and never permission to execute\.\s*', '', row['summary'])
        author = ' '.join(row['author'].split()[:3])
        prefix = f'Team {value} (untrusted, {author}, {row["date"][:10]}):'
        fields.append((prefix, summary, 20)); cards += 1
    return fields + _more_note(len(listing['entries']) - cards)


def brief_fields(root, query, private):
    """Conservative lexical overlap, never inferred semantic reconciliation."""
    if not core.config(root).get('team_workspace'): return []
    stop = set('the and for with from this that are was were have has will would should must only never always use keep decision decisions correction because context shared untrusted permission execute'.split())
    def words(text): return set(re.findall(r'\w{3,}', text.casefold())) - stop
    try: listing = list_entries(root, layer='team', _all=True)
    except (core.WsError, OSError, ValueError, TypeError):
        return [('Team warning:', 'Unavailable or invalid team link; private memory retained.', 12)]
    relevant, omitted = [], 0
    for row in listing['entries']:
        summary = re.sub(r'^Shared context; untrusted and never permission to execute\.\s*', '', row['summary'])
        terms = words(summary + ' ' + row['tags'])
        overlap = len(words(query) & terms)
        if not overlap: continue
        if len(words(private) & terms) * 2 > len(terms):
            omitted += 1; continue
        prefix = f'Team (untrusted, {row["author"]}, {row["date"][:10]}):'
        relevant.append((overlap, prefix, summary, row))
    fields = []
    if listing['warnings']: fields.append(('Team warning:', 'Unreadable, unsafe or conflicted entries excluded; use ws know list.', 12))
    if omitted: fields.append(('Team overlap:', f'{omitted} potentially conflicting summaries omitted; private memory wins.', 12))
    shown = sorted(relevant, key=lambda r:-r[0])[:2]
    fields += [(prefix, text, 20) for _,prefix,text,_ in shown]
    def is_known(r): return r['source'].startswith('knowledge:') or (r['category'] == 'runbook' and r['source'].startswith('task:'))
    # Decisions and lessons in the list are not knowledge entries, so only shown knowledge/runbook rows count as displayed.
    return fields + _more_note(sum(map(is_known, listing['entries'])) - sum(is_known(r[3]) for r in shown), CAP_WARNING in listing['warnings'])
