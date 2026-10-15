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
    if any(p.is_symlink() for p in (path, *path.parents) if p == base or base in p.parents):
        raise core.WsError('Symlink memory source skipped.')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
        raise core.WsError('Memory source must be a regular file under 16 KiB.')
    return core.read_text(path, [base], errors='strict')


def preview(repo, memory_dir=None):
    paths = [(repo / name, repo, name) for name in ('CLAUDE.md', '.claude/CLAUDE.md', 'AGENTS.md', '.cursorrules')]
    rules = repo / '.cursor/rules'
    if rules.is_dir() and not rules.is_symlink():
        paths += [(p, repo, p.relative_to(repo).as_posix()) for p in sorted(rules.glob('*.mdc'))[:16]]
    # Standard Claude project layout; --memory-dir handles custom settings/worktrees.
    home = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude').expanduser()
    project = os.environ.get('CLAUDE_CODE_PROJECT_DIR_NAME') if os.environ.get('CLAUDE_CONFIG_DIR') else None
    project = project or re.sub(r'[^A-Za-z0-9]', '-', str(repo))
    base = Path(memory_dir).expanduser().absolute() if memory_dir else home / 'projects' / project / 'memory'
    if base.is_dir() and not base.is_symlink() and not any(p.is_symlink() for p in base.parents if p == Path.home() or Path.home() in p.parents):
        paths += [(p, base, 'Claude memory/' + p.name) for p in sorted(base.glob('*.md'))[:16]]
    rows = []; total = 0
    for path, parent, label in paths:
        if not path.exists() and not path.is_symlink(): continue
        try: raw = _read(path, parent)
        except (core.WsError, OSError, ValueError):
            print('Memory import skipped unsafe/unreadable source: ' + label, file=sys.stderr); continue
        if re.search(r'#private\b', raw, re.I) or raw.lstrip().lower().startswith('/private'): continue
        text = core.redact(core.PRIVATE_RE.sub('', raw)).replace('<!--', '&lt;!--').strip()
        if not text or total + len(text.encode()) > 65536: continue
        total += len(text.encode())
        rows.append(dict(path=path, base=parent, label=label, sha=core.digest_text(raw), text=text))
        print('Import to private knowledge (unverified): ' + label + '\n' + json.dumps(text, ensure_ascii=True), file=sys.stderr)
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
            snippet = ' '.join(row['text'].split()[:12])
            snippets.append(row['label'] + ': ' + snippet + ' (' + name + ')')
        path = core.task_path(root, task); text = path.read_text(encoding='utf-8')
        # A dedicated section keeps imported text separate from user-stated decisions.
        core.atomic_write(path, core.set_section(text, 'Imported memory', '\n'.join(snippets)))
        core.refresh_native(root, locked=True)
