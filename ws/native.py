"""Read-only import of assistant-native memories and Codex goals. Never writes to native stores."""
import os
import re
import sqlite3
from pathlib import Path

from . import core

WORDS, MAX_ITEMS, ITEM_CHARS = 150, 20, 200
CLIENTS = ('claude', 'codex', 'gemini')


def _line(text, limit=ITEM_CHARS):
    text = ' '.join(core.redact(str(text)).replace('<!--', '').split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def _folders(root):
    cfg = core.config(root)
    return [Path(p).expanduser().resolve() for p in (str(root), *cfg.get('repos', []))]


def _codex_home():
    return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')


def _query(name, sql, columns, table):
    """Rows from a Codex sqlite file opened read-only, or (None, reason) when absent or unrecognised."""
    path = _codex_home() / name
    if not path.is_file():
        return None, f'{name} not found'
    try:
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        try:
            have = {row[1] for row in db.execute(f'pragma table_info({table})')}
            if not set(columns) <= have:
                return None, f'{name}: unknown schema'
            return db.execute(sql).fetchall(), ''
        finally:
            db.close()
    except sqlite3.Error:
        return None, f'{name}: unreadable'


def _claude(root):
    items, seen = [], set()
    for folder in _folders(root):
        for slug in {re.sub(r'[^A-Za-z0-9]', '-', str(folder)), str(folder).replace('/', '-')}:
            directory = Path.home() / '.claude/projects' / slug / 'memory'
            if directory in seen or not directory.is_dir() or directory.is_symlink():
                continue
            seen.add(directory)
            for path in sorted(directory.glob('*.md'), key=lambda p: p.stat().st_mtime, reverse=True):
                if path.name == 'MEMORY.md' or path.is_symlink():
                    continue
                try: text = path.read_text(encoding='utf-8', errors='replace')[:20000]
                except OSError: continue
                head = re.match(r'---\n(.*?)\n---\n?(.*)', text, re.S)
                meta = {k: v.strip('"\' ') for k, v in re.findall(r'^(name|description):[ \t]*(.*)$', head[1], re.M)} if head else {}
                body = next((l for l in (head[2] if head else text).splitlines() if l.strip()), '')
                desc = meta.get('description') or body
                items.append({'client': 'claude', 'source': f'claude:{path.name}',
                              'text': _line(f"{meta['name']}: {desc}" if meta.get('name') else desc)})
    return items


def _codex(root):
    needles = {n.lower() for f in _folders(root) for n in (str(f), f.name if len(f.name) >= 4 else '') if n}
    rows, _ = _query('memories_1.sqlite', 'select thread_id, raw_memory, rollout_summary, rollout_slug from stage1_outputs order by generated_at desc limit 200',
                     ('thread_id', 'raw_memory', 'rollout_summary', 'rollout_slug', 'generated_at'), 'stage1_outputs')
    items = []
    for thread, raw, summary, slug in rows or []:
        hay = f'{slug or ""}\n{raw or ""}'.lower()
        if any(n in hay for n in needles):
            items.append({'client': 'codex', 'source': f'codex:{slug or str(thread)[:8]}', 'text': _line(summary or raw or '')})
    return items


def _gemini(root):
    path = Path.home() / '.gemini/GEMINI.md'
    try: text = path.read_text(encoding='utf-8', errors='replace')[:200000]
    except OSError: return []
    found = re.search(r'^## Gemini Added Memories[ \t]*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    return [{'client': 'gemini', 'source': 'gemini:GEMINI.md', 'text': _line(l[2:])}
            for l in (found[1].splitlines() if found else []) if l.startswith('- ') and l[2:].strip()]


def collect(root, client='all'):
    if client != 'all' and client not in CLIENTS:
        raise core.WsError('Client must be claude, codex, gemini or all.')
    readers = {'claude': _claude, 'codex': _codex, 'gemini': _gemini}
    return [i for name in CLIENTS if client in ('all', name) for i in readers[name](root) if i['text']]


def _task(root, task):
    if task:
        return task
    active = [t['id'] for t in core.task_list(root) if t['status'] == 'in_progress']
    if len(active) != 1:
        raise core.WsError('Use --task ID: need exactly one in-progress task' + (f' (found {len(active)}).' if active else '.'))
    return active[0]


def _select(items, handoff):
    """Drop items already in the Handoff, cap each client at 150 words and the whole list at 20."""
    chosen, used = [], {}
    for item in items:
        words = len(item['text'].split()) + 1
        if f"- {item['text']}" in handoff or used.get(item['client'], 0) + words > WORDS or len(chosen) >= MAX_ITEMS:
            continue
        used[item['client']] = used.get(item['client'], 0) + words
        chosen.append(item)
    return chosen


def import_native(root, client='all', task=None, yes=False):
    """Preview native memories; with yes, append one unverified block per client to the task Handoff."""
    items = collect(root, client)
    try: tid = _task(root, task)
    except core.WsError:
        if yes: raise
        tid = None
    handoff = core.task_read(root, tid, ['Handoff'])['sections']['Handoff'] if tid else ''
    chosen = _select(items, handoff)
    written = []
    if yes and chosen:
        with core.lock(root):
            worker, token = core._claim_defaults(root, tid, None, None)
            path = core.task_path(root, tid)
            text = path.read_text(encoding='utf-8')
            meta = core.parse_meta(text)
            if meta.get('claimed_by') and (worker != meta['claimed_by'] or token != meta.get('claim_token')):
                raise core.WsError(f'{tid} is claimed by {meta["claimed_by"]}; pass its worker and token.')
            handoff = core.section(text, 'Handoff')
            for name in CLIENTS:
                mine = [i for i in chosen if i['client'] == name]
                if mine:
                    handoff += (f'\n\n### Imported {core.now()[:10]} (unverified, from {name})\n'
                                + '\n'.join('- ' + i['text'] for i in mine) + '\n<!-- /ws:imported -->')
                    written.append(name)
            core.atomic_write(path, core.set_section(text, 'Handoff', handoff))
    return {'task': tid, 'items': [{k: i[k] for k in ('client', 'source', 'text')} for i in chosen], 'written': written,
            'note': 'Written to the task Handoff as unverified.' if written else
                    'Nothing new to import.' if yes else 'Preview only; add --yes to append to the task Handoff.'}


# --- Codex goals (read-only) ---------------------------------------------------------

def _goals(root, tasks):
    rows, reason = _query('goals_1.sqlite', 'select objective, status from thread_goals', ('objective', 'status'), 'thread_goals')
    if rows is None:
        return None, reason
    needles = [n.lower() for t in tasks for n in (t['id'], t['title']) if n]
    return [(o or '', s) for o, s in rows if any(n in (o or '').lower() for n in needles)], ''


def codex_goals(root):
    """Goal counts for threads whose objective mentions an in-progress task ID or title."""
    tasks = [t for t in core.task_list(root) if t['status'] == 'in_progress']
    if not tasks:
        return {'skipped': 'no in-progress task'}
    goals, reason = _goals(root, tasks)
    if goals is None:
        return {'skipped': reason}
    return {'active': sum(s == 'active' for _, s in goals), 'complete': sum(s == 'complete' for _, s in goals)}


def goal_hint(root, task_id):
    """One-line hint when a Codex goal for this task is still active, else ''."""
    tasks = [t for t in core.task_list(root) if t['id'] == task_id]
    goals, _ = _goals(root, tasks) if tasks else (None, '')
    active = [o for o, s in goals or [] if s == 'active']
    return f'Codex goal still active: {_line(active[0], 100)} — close it in Codex' if active else ''
