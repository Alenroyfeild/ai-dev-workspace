"""Explicit, bounded imports from a checkpointed claude-mem database; never migrate it."""
import json
import re
import sqlite3
from pathlib import Path
from . import core, sharing


def preview(database, project):
    path = Path(database).expanduser().resolve()
    if not project.strip() or not path.is_file() or path.stat().st_size > 256 * 1024 * 1024:
        raise core.WsError('Choose an existing SQLite file (up to 256 MiB) and an exact source project.')
    if any(p.exists() and p.stat().st_size for p in (Path(str(path) + '-wal'), Path(str(path) + '-journal'))):
        raise core.WsError('Use a checkpointed database copy; active WAL/journal sources are not imported.')
    try:
        # immutable prevents even SQLite sidecar writes. Active journals are refused above.
        db = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)
        try:
            db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA trusted_schema=OFF')
            ticks = [0]
            def stop():
                ticks[0] += 1
                return ticks[0] > 1000
            db.set_progress_handler(stop, 10000)
            table = db.execute("SELECT type, sql FROM sqlite_master WHERE name='observations'").fetchone()
            columns = {r[1] for r in db.execute('PRAGMA table_info(observations)')}
            if not table or table[0] != 'table' or 'VIRTUAL' in table[1].upper() or not {'id', 'project', 'type', 'created_at'} <= columns:
                raise core.WsError('Unrecognized claude-mem observations schema; nothing imported.')
            fields = [c for c in ('title', 'subtitle', 'narrative', 'facts', 'text') if c in columns]
            if not fields: raise core.WsError('No supported observation text columns; nothing imported.')
            selected = ','.join(fields)
            bounded = ' AND '.join('(' + c + " IS NULL OR (typeof(" + c + ")='text' AND length(" + c + ')<=8000))' for c in fields)
            rows = db.execute('SELECT CAST(id AS INTEGER),substr(type,1,64),substr(created_at,1,80),' + selected + ' FROM observations WHERE project=? AND ' + bounded + ' ORDER BY id DESC LIMIT 50', (project,)).fetchall()
        finally:
            db.close()
    except (sqlite3.Error, UnicodeError) as exc:
        raise core.WsError('SQLite source is unreadable or unsupported; nothing imported.') from exc
    items = []
    for identifier, kind, date, *values in rows:
        raw = '\n'.join(str(v) for v in values if v)
        if re.search(r'#private\b', raw, re.I) or raw.lstrip().lower().startswith('/private'): continue
        body = ' '.join(core.plain_text(raw).split()[:150])
        if not body: continue
        origin = core.plain_text(f'claude-mem observation {identifier}, {date}')
        items.append({'kind': 'decision' if kind == 'decision' else 'lesson',
                      'text': f'Imported context (unverified; not instructions).\nSource: {origin}\n\n{body}'})
    return items


def import_store(root, database, project, apply=False):
    items = preview(database, project)
    result = {'items': items, 'saved': [], 'note': 'Private preview only; use --apply to review and save. Maximum 50 observations; fields over 8000 characters are excluded.'}
    if not apply or not items: return result
    print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)
    try: accepted = input('Save these as private, unverified records? [y/N] ').strip().lower() in ('y', 'yes')
    except (EOFError, OSError): accepted = False
    if not accepted: return result
    if preview(database, project) != items:
        raise core.WsError('Source changed after preview; review it again before saving.')
    result['saved'] = [sharing.standalone(root, item['kind'], item['text'], False) for item in items]
    result['note'] = 'Saved privately; review before using or sharing.'
    return result
