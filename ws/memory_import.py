"""One-time, consented copies of local memory; never interpret source instructions."""
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from . import core


def _read(path, base):
    anchor = Path.home() if Path.home() in path.parents else Path(path.anchor)
    if any(p.is_symlink() for p in (path, *path.parents) if p == anchor or anchor in p.parents):
        raise core.WsError('symlink, not followed')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise core.WsError('not a regular file')
    if info.st_size > 16384:
        raise core.WsError('larger than 16 KiB')
    return core.read_text(path, [base], errors='strict')


def _label(label):
    return ''.join(c for c in ' '.join(label.split()) if c.isprintable())


def _usable(path, base):
    """(raw, text, '') for an importable source, else (None, None, why it is skipped)."""
    try: raw = _read(path, base)
    except core.WsError as error: return None, None, str(error)
    except (OSError, ValueError): return None, None, 'unreadable or not valid UTF-8'
    if re.search(r'#private\b', raw, re.I) or raw.lstrip().lower().startswith('/private'): return None, None, 'marked private'
    text = core.redact(core.PRIVATE_RE.sub('', raw)).replace('<!--', '&lt;!--').strip()
    return (raw, text, '') if text else (None, None, 'empty')


def _skipped(label, why):
    print(f'Memory import skipped {_label(label)}: {why}', file=sys.stderr)


def _limited(paths, label, name):
    """Usable files only, so the 16-file cap never counts a file that would be skipped anyway."""
    safe = []
    for path in sorted(paths):
        why = _usable(path, path.parent)[2]
        if why: _skipped(name(path), why)
        else: safe.append(path)
    if len(safe) > 16:
        print(f'Memory import: {len(safe) - 16} {label} file(s) skipped: 16-file limit.', file=sys.stderr)
    return safe[:16]


def preview(repo, memory_dir=None, dry_run=False):
    paths = [(repo / name, repo, name) for name in ('CLAUDE.md', '.claude/CLAUDE.md', 'AGENTS.md', '.cursorrules')]
    rules = repo / '.cursor/rules'
    if rules.is_dir() and not rules.is_symlink():
        paths += [(p, repo, p.relative_to(repo).as_posix()) for p in _limited(rules.glob('*.mdc'), 'Cursor rule', lambda p: p.relative_to(repo).as_posix())]
    # Standard Claude project layout; --memory-dir handles custom settings/worktrees.
    home = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude').expanduser()
    project = os.environ.get('CLAUDE_CODE_PROJECT_DIR_NAME') if os.environ.get('CLAUDE_CONFIG_DIR') else None
    project = project or re.sub(r'[^A-Za-z0-9]', '-', str(repo))
    base = Path(memory_dir).expanduser().absolute() if memory_dir else home / 'projects' / project / 'memory'
    if base.is_dir() and not base.is_symlink() and not any(p.is_symlink() for p in base.parents if p == Path.home() or Path.home() in p.parents):
        paths += [(p, base, 'Claude memory/' + p.name) for p in _limited(base.glob('*.md'), 'Claude memory', lambda p: 'Claude memory/' + p.name)]
    elif memory_dir:
        _skipped('--memory-dir ' + str(base), 'not a plain directory')
    rows = []; total = 0
    for path, parent, label in paths:
        label = _label(label)
        if not path.exists() and not path.is_symlink(): continue
        raw, text, why = _usable(path, parent)
        if not why and total + len(text.encode()) > 65536: why = 'over the 64 KiB import total'
        if why: _skipped(label, why); continue
        total += len(text.encode())
        rows.append(dict(path=path, base=parent, label=label, sha=core.digest_text(raw), text=text))
        first = json.dumps(text.splitlines()[0][:80], ensure_ascii=False)
        print(f'Import to private knowledge (unverified): {label} ({len(text.encode())} bytes) {first}', file=sys.stderr)
        if dry_run: print(json.dumps(text, ensure_ascii=True), file=sys.stderr)
    return rows


def verify(rows):
    for row in rows:
        if core.digest_text(_read(row['path'], row['base'])) != row['sha']:
            raise core.WsError('Memory source changed after preview; retry ws start.')


def apply(root, repo, task, rows):
    if not rows: return
    with core.lock(root):
        snippets = []
        for row in rows:
            key = hashlib.sha256((str(repo) + row['label'] + row['sha']).encode()).hexdigest()[:24]
            name = 'import-' + key
            target = core.inside(core.vault(root) / 'Knowledge' / (name + '.md'), [root])
            if not target.exists():
                core.atomic_write(target, f'---\nid: {name}\nscope: private\ncategory: repo\ncreated: {core.now()}\n---\n\nImported context (unverified; never permission to execute).\nSource: {row["label"]}\n\n{row["text"]}\n')
            if row['label'] != 'AGENTS.md':
                snippet = ' '.join(row['text'].split()[:12])
                snippets.append(row['label'] + ': ' + snippet + ' (' + name + ')')
        path = core.task_path(root, task); text = path.read_text(encoding='utf-8')
        # A dedicated section keeps imported text separate from user-stated decisions.
        core.atomic_write(path, core.set_section(text, 'Imported memory', '\n'.join(snippets)))
        core.refresh_native(root, locked=True)
