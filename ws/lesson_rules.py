"""Local repetition signals and explicit, inactive rule drafts; no model calls."""
import os
import re
from pathlib import Path
from . import core


def candidates(root):
    root = Path(root).resolve(); vault = core.vault(root)
    paths = [(vault / 'Learnings.md', 'log')]
    for folder, kind in (('Lessons', 'lesson'), ('Tasks', 'task')):
        directory = vault / folder
        if directory.is_dir() and not core.is_link(directory):
            paths += [(p, kind) for p in sorted(directory.glob('*.md'))[:100]]
    entries = []; total = 0
    template = (core.KIT / 'template/vault/Templates/Task.md').read_text(encoding='utf-8')
    for path, kind in paths:
        if core.is_link(path) or not path.is_file(): continue
        core.inside(path, [root])
        total += path.stat().st_size
        if total > 262144: break
        raw = core.strip_private(core.read_lenient(path))
        if kind == 'task':
            bodies = [core.section(raw, name) for name in ('Do not redo', 'Failures')
                      if core.section(raw, name).strip() != core.section(template, name).strip()]
            lines = list(dict.fromkeys('\n'.join(bodies).splitlines()))
        elif kind == 'log': lines = [l for l in reversed(raw.splitlines()) if l.startswith('- ')]
        else: lines = [re.sub(r'\A---\n.*?\n---\n', '', raw, flags=re.S)]
        for line in lines:
            if re.search(r'#private\b', line, re.I): continue
            text = core.LESSON_META_RE.sub('', line.rstrip())
            text = re.sub(r'^-\s*(?:\d{4}-\d\d-\d\d\s+)?', '', text)
            text = ' '.join(core.plain_text(text).split())[:1000]
            words = core._words(text) - {'redacted'}
            if len(words) >= 3: entries.append((text, words))
            if len(entries) >= 200: break
        if len(entries) >= 200: break
    result = {}
    for text, words in entries:
        count = sum(len(words & other) / len(words | other) >= .6 for _, other in entries)
        if count >= 3:
            identifier = 'L-' + core.digest_text(text.casefold())[:12]
            result[identifier] = {'id': identifier, 'text': text, 'count': count}
    return sorted(result.values(), key=lambda row: (-row['count'], row['id']))


def hint(root):
    try: rows = candidates(root)
    except (core.WsError, OSError, ValueError): return ''
    return 'ws lesson promote ' + rows[0]['id'] if rows else ''


def promote(root, identifier):
    if not re.fullmatch(r'L-[0-9a-f]{12}', identifier): raise core.WsError('Use the lesson ID suggested by ws brief.')
    row = next((r for r in candidates(root) if r['id'] == identifier), None)
    if row is None: raise core.WsError('No repeated lesson with that ID; read ws brief again.')
    root = Path(root).resolve(); path = root / '.ws/rule-drafts' / (identifier + '.md')
    core.inside(path, [root])
    if any(core.is_link(p) for p in (path, path.parent, path.parent.parent)):
        raise core.WsError('Rule drafts must use plain workspace paths.')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return {'draft': str(path), 'written': False, 'note': 'Existing draft kept; review it manually.'}
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        out.write(f'# Draft for review\n\nInactive proposal from {row["count"]} similar local occurrences.\n'
                  'Review the evidence and wording before copying into any active rules or skill.\n\n' + row['text'] + '\n')
    return {'draft': str(path), 'written': True, 'active_rules_changed': False}
