"""AI Dev Workspace core: tasks, claims, lessons, feedback, search, digest, run tracking.

Standard library only. Every function takes the workspace root so the CLI, the MCP
server and tests share one implementation.
"""
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
REQUIRED = ('Objective', 'Acceptance criteria', 'Evidence', 'Checks', 'Blockers', 'Next action', 'Handoff')
STATUSES = ('backlog', 'ready', 'in_progress', 'review', 'blocked', 'done')
ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}')
SECRET_RE = re.compile(
    r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----'
    r'|\bBearer\s+[A-Za-z0-9._~+/=-]{8,}'
    r'|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'
    r'|(?<!claim_)(?i:(?:api[_-]?key|token|secret|password)["\']?\s*[:=]\s*["\']?)[A-Za-z0-9/+_.-]{12,}', re.S)


class WsError(ValueError):
    """A user-facing error; the message says what to do."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def redact(text):
    return SECRET_RE.sub('[REDACTED]', text)


# --- workspace -------------------------------------------------------------------

def find_root(start=None):
    """Walk up from start (or cwd) to the directory holding workspace.json."""
    path = Path(start or os.environ.get('WS_ROOT') or os.getcwd()).resolve()
    for candidate in (path, *path.parents):
        if (candidate / 'workspace.json').is_file():
            return candidate
    raise WsError('No workspace.json found here or above. Run `ws init <dir>` first, or set WS_ROOT.')


def config(root):
    return json.loads((root / 'workspace.json').read_text())


def vault(root):
    return root / config(root).get('vault', 'vault')


def pack_manifest(name):
    path = KIT / 'packs' / name / 'pack.json'
    if not path.is_file():
        raise WsError(f'Unknown pack {name}. Available: {", ".join(available_packs())}')
    return json.loads(path.read_text())


def available_packs():
    return sorted(p.name for p in (KIT / 'packs').iterdir() if (p / 'pack.json').is_file())


def _install_pack(target, name):
    src = KIT / 'packs' / name
    if (src / 'vault').is_dir():
        shutil.copytree(src / 'vault', target / 'vault', dirs_exist_ok=True)
    snippet = src / 'AGENTS.snippet.md'
    rules = target / 'AGENTS.md'
    if snippet.is_file() and snippet.read_text().strip() not in rules.read_text():
        rules.write_text(rules.read_text().rstrip('\n') + '\n' + snippet.read_text().replace('<kit>', str(KIT)))


def pack_add(root, name):
    """Plug a pack into an existing workspace; idempotent."""
    manifest = pack_manifest(name)
    cfg = config(root)
    _install_pack(root, name)
    if name not in cfg['packs']:
        cfg['packs'].append(name)
        (root / 'workspace.json').write_text(json.dumps(cfg, indent=2) + '\n')
    nxt = [f"run {KIT / 'packs' / name / manifest['setup']}"] if manifest.get('setup') else []
    if manifest.get('selftest'):
        nxt.append(f"verify with {KIT / 'packs' / name / manifest['selftest']}")
    return {'pack': name, 'installed': True, 'next': nxt or ['nothing else needed'],
            'missing': [r for r in requirement_status(manifest) if not r['ok']]}


def init(target, name, packs=(), repos=()):
    target = Path(target).resolve()
    if (target / 'workspace.json').exists():
        raise WsError(f'{target} is already a workspace.')
    for pack in packs:
        pack_manifest(pack)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(KIT / 'template', target, dirs_exist_ok=True)
    for pack in packs:
        _install_pack(target, pack)
    cfg = {'schema_version': 1, 'name': name, 'vault': 'vault', 'packs': list(packs),
           'repos': [str(Path(r).expanduser().resolve()) for r in repos], 'created': now()}
    (target / 'workspace.json').write_text(json.dumps(cfg, indent=2) + '\n')
    # Project-scoped MCP config: Claude Code reads .mcp.json; other clients can copy the same command.
    mcp = {'mcpServers': {'ai-dev-workspace': {'command': 'python3',
           'args': [str(KIT / 'mcp' / 'server.py'), '--root', str(target)]}}}
    (target / '.mcp.json').write_text(json.dumps(mcp, indent=2) + '\n')
    if repos:
        codebase_map(target, repos[0])
    return cfg


def _map_commands(repo):
    commands = []
    package = repo / 'package.json'
    if package.is_file():
        try:
            scripts = json.loads(package.read_text()).get('scripts', {})
            commands.extend(f'npm run {name}' for name in scripts if any(x in name.lower() for x in ('build', 'test', 'run', 'start', 'dev')))
        except json.JSONDecodeError:
            pass
    makefile = next((p for p in (repo / 'Makefile', repo / 'makefile') if p.is_file()), None)
    if makefile:
        commands.extend(f'make {m.group(1)}' for m in re.finditer(r'^([A-Za-z][\w.-]*):', makefile.read_text(), re.M)
                        if any(x in m.group(1).lower() for x in ('build', 'test', 'run', 'start')))
    if (repo / 'Podfile').is_file(): commands.append('pod install')
    if any((repo / p).is_file() for p in ('build.gradle', 'build.gradle.kts', 'gradlew')):
        commands.extend(('./gradlew build', './gradlew test', './gradlew run'))
    pyproject = repo / 'pyproject.toml'
    if pyproject.is_file():
        data = pyproject.read_text()
        if 'pytest' in data: commands.append('python -m pytest')
        if '[build-system]' in data: commands.append('python -m build')
    if (repo / 'Cargo.toml').is_file(): commands.extend(('cargo build', 'cargo test', 'cargo run'))
    if (repo / 'go.mod').is_file(): commands.extend(('go build ./...', 'go test ./...', 'go run .'))
    return list(dict.fromkeys(commands))[:20]


def codebase_map(root, repo=None):
    root = Path(root).resolve()
    repos = config(root).get('repos', [])
    selected = repo or (repos[0] if repos else None)
    if not selected:
        raise WsError('Codebase map needs a repository path: `ws map /path/to/repo`.')
    repo = Path(selected).expanduser().resolve()
    if not repo.is_dir():
        raise WsError('Codebase map needs a repository path: `ws map /path/to/repo`.')
    files = [p for p in repo.rglob('*') if p.is_file() and '.git' not in p.parts]
    names = {'.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript', '.swift': 'Swift', '.go': 'Go', '.rs': 'Rust', '.java': 'Java', '.kt': 'Kotlin', '.rb': 'Ruby'}
    languages = {}
    for path in files:
        language = names.get(path.suffix.lower())
        if language: languages[language] = languages.get(language, 0) + 1
    folders = {p.name: sum(1 for f in p.rglob('*') if f.is_file() and '.git' not in f.parts)
               for p in repo.iterdir() if p.is_dir() and p.name != '.git'}
    changed = {}
    run = subprocess.run(['git', '-C', str(repo), 'log', '--since=90.days', '--name-only', '--format='], capture_output=True, text=True, check=False)
    for name in run.stdout.splitlines():
        if name: changed[name] = changed.get(name, 0) + 1
    readme = next((p for p in repo.glob('README*') if p.is_file()), None)
    heading = next((line[2:].strip() for line in readme.read_text(errors='replace').splitlines() if line.startswith('# ')), 'No README heading') if readme else 'No README found'
    section = ['<!-- ws:codebase-map:start -->', f'Repository: `{repo}`', '', f'## README\n{heading}', '', '## Languages']
    section.extend([f'- {name}: {count}' for name, count in sorted(languages.items(), key=lambda x: (-x[1], x[0]))] or ['- None detected'])
    section.extend(['', '## Commands'])
    section.extend([f'- `{c}`' for c in _map_commands(repo)] or ['- None found'])
    section.extend(['', '## Top-level folders'])
    section.extend([f'- {name}: {count} files' for name, count in sorted(folders.items())] or ['- None'])
    section.extend(['', '## Most changed (90 days)'])
    section.extend([f'- {name}: {count}' for name, count in sorted(changed.items(), key=lambda x: (-x[1], x[0]))[:15]] or ['- No Git history'])
    section.append('<!-- ws:codebase-map:end -->')
    rendered = '\n'.join(section) + '\n'
    path = vault(root) / 'Project' / 'Codebase map.md'
    existing = path.read_text() if path.exists() else '# Codebase map\n'
    pattern = r'<!-- ws:codebase-map:start -->.*?<!-- ws:codebase-map:end -->\n?'
    text = re.sub(pattern, rendered, existing, flags=re.S) if re.search(pattern, existing, re.S) else existing.rstrip() + '\n\n' + rendered
    with lock(root): atomic_write(path, text)
    return {'repo': str(repo), 'path': str(path.relative_to(root)), 'words': len(rendered.split())}


# --- files -----------------------------------------------------------------------

def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextlib.contextmanager
def lock(root):
    (root / '.ws').mkdir(exist_ok=True)
    with (root / '.ws' / 'lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise WsError('Another workspace update is running; retry in a moment.')
        yield


def parse_meta(text):
    meta = {}
    if text.startswith('---\n'):
        for line in text.split('\n---', 1)[0][4:].splitlines():
            if ':' in line:
                key, value = line.split(':', 1)
                meta[key.strip()] = value.strip()
    return meta


def set_meta(text, values):
    if not text.startswith('---\n') or '\n---' not in text[4:]:
        raise WsError('Task file has no frontmatter.')
    head, body = text[4:].split('\n---', 1)
    for key, value in values.items():
        value = str(value)
        if '\n' in value:
            raise WsError('Metadata values must be one line.')
        if re.search(rf'^{re.escape(key)}:', head, re.M):
            head = re.sub(rf'^{re.escape(key)}:.*$', lambda m: f'{key}: {value}', head, flags=re.M)
        else:
            head += f'\n{key}: {value}'
    return '---\n' + head + '\n---' + body


def section(text, name):
    m = re.search(rf'^## {re.escape(name)}[ \t]*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    return m.group(1).strip() if m else ''


def set_section(text, name, body):
    pattern = rf'(^## {re.escape(name)}[ \t]*\n).*?(?=^## |\Z)'
    if re.search(pattern, text, re.M | re.S):
        return re.sub(pattern, lambda m: m.group(1) + body.strip() + '\n\n', text, count=1, flags=re.M | re.S)
    return text.rstrip('\n') + f'\n\n## {name}\n{body.strip()}\n'


def digest_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


# --- tasks -----------------------------------------------------------------------

def task_path(root, task_id):
    if not ID_RE.fullmatch(task_id or ''):
        raise WsError('Task IDs use letters, digits, dot, dash or underscore (e.g. JIRA-123, fix-login).')
    return vault(root) / 'Tasks' / f'{task_id}.md'


def task_new(root, task_id, title, objective='', branch='', repo=''):
    path = task_path(root, task_id)
    if path.exists():
        raise WsError(f'Task {task_id} already exists: {path.relative_to(root)}')
    template = (vault(root) / 'Templates' / 'Task.md').read_text()
    text = template.replace('{{id}}', task_id).replace('{{title}}', title).replace('{{date}}', now()[:10])
    text = set_meta(text, {'branch': branch, 'repo': repo})
    if objective:
        text = set_section(text, 'Objective', redact(objective))
    with lock(root):
        atomic_write(path, text)
    return {'task': task_id, 'path': str(path.relative_to(root))}


def task_list(root):
    out = []
    for path in sorted((vault(root) / 'Tasks').glob('*.md')):
        text = path.read_text()
        meta = parse_meta(text)
        title = re.search(r'^# (.+)$', text, re.M)
        out.append({'id': meta.get('id', path.stem), 'title': title.group(1) if title else path.stem,
                    'status': meta.get('status', 'unknown'), 'claimed_by': meta.get('claimed_by', ''),
                    'branch': meta.get('branch', ''), 'next': section(text, 'Next action')[:200]})
    return out


def task_find(root, ref):
    ref = ref.lower()
    return [t for t in task_list(root) if ref in t['id'].lower() or ref == t['branch'].lower() or ref in t['title'].lower()]


def task_read(root, task_id, sections=None):
    path = task_path(root, task_id)
    if not path.is_file():
        raise WsError(f'No task {task_id}. Create it with `ws task new {task_id} "<title>"`.')
    text = path.read_text()
    if not sections:
        return {'task': task_id, 'sha': digest_text(text), 'text': text}
    return {'task': task_id, 'sha': digest_text(text), 'meta': parse_meta(text),
            'sections': {s: section(text, s) for s in sections}}


def claim(root, task_id, worker):
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', worker):
        raise WsError('Worker is a short label such as claude-main or codex-1.')
    with lock(root):
        path = task_path(root, task_id)
        text = path.read_text()
        meta = parse_meta(text)
        if meta.get('claimed_by'):
            raise WsError(f'{task_id} is claimed by {meta["claimed_by"]} since {meta.get("claimed_at")}. '
                          'Release it first (only after checking that session has stopped).')
        if meta.get('status') == 'done':
            raise WsError(f'{task_id} is done; reopen it with a checkpoint first.')
        token = uuid.uuid4().hex
        atomic_write(path, set_meta(text, {'claimed_by': worker, 'claim_token': token, 'claimed_at': now()}))
    return {'task': task_id, 'worker': worker, 'token': token}


def release(root, task_id, worker, token):
    with lock(root):
        path = task_path(root, task_id)
        text = path.read_text()
        meta = parse_meta(text)
        if meta.get('claimed_by') != worker or meta.get('claim_token') != token:
            raise WsError('Worker/token do not match the claim; nothing changed.')
        atomic_write(path, set_meta(text, {'claimed_by': '', 'claim_token': '', 'claimed_at': ''}))
    return {'task': task_id, 'released': True}


def checkpoint(root, task_id, status, next_action, expected_sha=None, worker=None, token=None, notes=None):
    if status not in STATUSES:
        raise WsError(f'Status must be one of: {", ".join(STATUSES)}')
    if not next_action.strip():
        raise WsError('Next action is required: say exactly what the next person or AI should do.')
    with lock(root):
        path = task_path(root, task_id)
        text = path.read_text()
        meta = parse_meta(text)
        if meta.get('claimed_by') and (worker != meta['claimed_by'] or token != meta.get('claim_token')):
            raise WsError(f'{task_id} is claimed by {meta["claimed_by"]}; pass its worker and token.')
        if expected_sha and expected_sha != digest_text(text):
            raise WsError('Task changed since you read it; read it again before checkpointing.')
        text = set_meta(text, {'status': status, 'updated': now()})
        text = set_section(text, 'Next action', redact(next_action))
        for name, body in (notes or {}).items():
            if name not in REQUIRED and name not in ('Findings', 'Failures', 'Risks', 'Do not redo'):
                raise WsError(f'Unknown section {name}.')
            text = set_section(text, name, redact(body))
        atomic_write(path, text)
    return {'task': task_id, 'status': status, 'sha': digest_text(text)}


# --- knowledge -------------------------------------------------------------------

def search(root, query, limit=20):
    """Rank vault notes by query-word hits; return path:line snippets, not whole files."""
    words = [w.lower() for w in re.findall(r'\w{3,}', query)]
    if not words:
        raise WsError('Search needs at least one word of 3+ letters.')
    hits = []
    for path in vault(root).rglob('*.md'):
        if '.ws' in path.parts or 'Runs' in path.parts:
            continue
        lines = path.read_text(errors='replace').splitlines()
        score, best = 0, []
        for i, line in enumerate(lines, 1):
            low = line.lower()
            n = sum(low.count(w) for w in words)
            if n:
                score += n + (3 if line.startswith('#') else 0)
                best.append((n, i, line.strip()[:160]))
        if score:
            best.sort(reverse=True)
            hits.append({'path': str(path.relative_to(root)), 'score': score,
                         'lines': [f'{i}: {t}' for _, i, t in best[:3]]})
    hits.sort(key=lambda h: -h['score'])
    return hits[:limit]


def _append_line(root, rel, line):
    path = root / rel
    with lock(root):
        text = path.read_text() if path.exists() else ''
        atomic_write(path, text.rstrip('\n') + '\n' + line + '\n')


def lesson_add(root, text, tags=()):
    text = ' '.join(redact(text).split())
    if len(text) < 10:
        raise WsError('Write the lesson as: what happened → rule.')
    tag = ' '.join(f'#{t}' for t in tags)
    _append_line(root, Path(config(root).get('vault', 'vault')) / 'Learnings.md', f'- {now()[:10]} {text} {tag}'.rstrip())
    return {'added': True}


def lesson_search(root, query):
    path = vault(root) / 'Learnings.md'
    words = [w.lower() for w in re.findall(r'\w{3,}', query)]
    lines = [l for l in path.read_text().splitlines() if l.startswith('- ')] if path.exists() else []
    return [l for l in lines if any(w in l.lower() for w in words)] if words else lines


def feedback_add(root, text, kind='idea', source='user'):
    if kind not in ('idea', 'bug', 'praise', 'friction'):
        raise WsError('Kind is one of: idea, bug, praise, friction.')
    _append_line(root, Path(config(root).get('vault', 'vault')) / 'Feedback.md',
                 f'- [ ] {now()[:10]} **{kind}** ({source}): {" ".join(redact(text).split())}')
    return {'added': True}


def feedback_list(root, open_only=True):
    path = vault(root) / 'Feedback.md'
    lines = [l for l in path.read_text().splitlines() if l.startswith('- [')] if path.exists() else []
    return [l for l in lines if l.startswith('- [ ]')] if open_only else lines


# --- digest ----------------------------------------------------------------------

def _shape(value, depth=0):
    if depth > 6:
        return '…'
    if isinstance(value, dict):
        return {k: _shape(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return [f'{len(value)} items', _shape(value[0], depth + 1)] if value else []
    if isinstance(value, str):
        return f'str({len(value)})'
    return type(value).__name__


ERR_RE = re.compile(r'\b(error|fatal|failed|failure|exception|warning|denied|panic|traceback)\b', re.I)


def digest_file(path, max_lines=60):
    """Deterministic summary of a big file: JSON shape, or deduplicated error lines of a log."""
    path = Path(path)
    raw = path.read_text(errors='replace')
    out = {'file': str(path), 'bytes': len(raw), 'lines': raw.count('\n') + 1}
    try:
        out['json_shape'] = _shape(json.loads(raw))
        return out
    except ValueError:
        pass
    seen, picked = {}, []
    for i, line in enumerate(raw.splitlines(), 1):
        if ERR_RE.search(line):
            key = re.sub(r'\d+', '#', line.strip())[:200]
            if key in seen:
                seen[key] += 1
                continue
            seen[key] = 1
            picked.append((i, key))
    out['distinct_problem_lines'] = len(picked)
    out['problems'] = [f'L{i} (x{seen[k]}): {redact(k)}' for i, k in picked[:max_lines]]
    out['tail'] = [redact(l)[:200] for l in raw.splitlines()[-5:]]
    return out


# --- orchestration run tracking ---------------------------------------------------

def run_log(root, task_id, step, provider, model='', tokens_in=0, tokens_out=0, seconds=0.0,
            result='ok', note=''):
    """Append one orchestration step (who did what, cost, outcome) to vault/Runs/<task>.jsonl."""
    task_path(root, task_id)
    if result not in ('ok', 'failed', 'rejected', 'accepted', 'skipped'):
        raise WsError('result is ok, failed, rejected, accepted or skipped.')
    entry = {'at': now(), 'task': task_id, 'step': step, 'provider': provider, 'model': model,
             'tokens_in': int(tokens_in), 'tokens_out': int(tokens_out), 'seconds': float(seconds),
             'result': result, 'note': redact(note)[:300]}
    path = vault(root) / 'Runs' / f'{task_id}.jsonl'
    with lock(root):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as stream:
            stream.write(json.dumps(entry) + '\n')
    return entry


def run_report(root, task_id=None):
    files = [vault(root) / 'Runs' / f'{task_id}.jsonl'] if task_id else sorted((vault(root) / 'Runs').glob('*.jsonl'))
    by = {}
    steps = 0
    for path in files:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            e = json.loads(line)
            steps += 1
            b = by.setdefault(e['provider'], {'steps': 0, 'tokens_in': 0, 'tokens_out': 0, 'seconds': 0.0, 'failed': 0})
            b['steps'] += 1
            b['tokens_in'] += e['tokens_in']
            b['tokens_out'] += e['tokens_out']
            b['seconds'] += e['seconds']
            b['failed'] += e['result'] in ('failed', 'rejected')
    return {'steps': steps, 'by_provider': by}


# --- health ----------------------------------------------------------------------

def validate(root):
    errors, warnings = [], []
    v = vault(root)
    for path in sorted((v / 'Tasks').glob('*.md')):
        text = path.read_text()
        meta = parse_meta(text)
        if meta.get('id') != path.stem:
            errors.append(f'{path.name}: id must equal the file name')
        if meta.get('status') not in STATUSES:
            errors.append(f'{path.name}: status must be one of {", ".join(STATUSES)}')
        for name in REQUIRED:
            if not re.search(rf'^## {re.escape(name)}\s*$', text, re.M):
                errors.append(f'{path.name}: missing section {name}')
        if meta.get('status') not in ('done', 'backlog') and not section(text, 'Next action'):
            errors.append(f'{path.name}: empty Next action')
    names = {p.stem for p in v.rglob('*.md')} | {str(p.relative_to(v))[:-3] for p in v.rglob('*.md')}
    for path in v.rglob('*.md'):
        text = path.read_text(errors='replace')
        if redact(text) != text:
            warnings.append(f'{path.relative_to(root)}: looks like it contains a secret; remove it')
        for target in re.findall(r'\[\[([^\]|#]+)', text):
            if target.strip() not in names:
                errors.append(f'{path.relative_to(root)}: broken link [[{target}]]')
    return {'valid': not errors, 'errors': errors, 'warnings': warnings}


def status(root):
    tasks = task_list(root)
    counts = {}
    for t in tasks:
        counts[t['status']] = counts.get(t['status'], 0) + 1
    return {'workspace': config(root)['name'], 'packs': config(root).get('packs', []), 'tasks': counts,
            'active_claims': [f"{t['id']} by {t['claimed_by']}" for t in tasks if t['claimed_by']],
            'blocked': [f"{t['id']}: {t['next']}" for t in tasks if t['status'] == 'blocked'],
            'open_feedback': len(feedback_list(root)), 'lessons': len(lesson_search(root, '')),
            'runs': run_report(root)}


def _has_app(name):
    return any(Path(base, f'{name}.app').exists() for base in ('/Applications', Path.home() / 'Applications'))


def requirement_status(manifest):
    out = []
    for req in manifest.get('requires', []):
        ok = bool(shutil.which(req['cmd'])) if 'cmd' in req else _has_app(req['app'])
        out.append({'pack': manifest['name'], 'needs': req.get('cmd') or req.get('app'), 'ok': ok,
                    'optional': req.get('optional', False), 'why': req['why'], 'install': req['install']})
    return out


RECOMMENDED = [
    {'needs': 'ollama', 'cmd': 'ollama', 'why': 'free local model for log triage and extraction (pack local-llm)',
     'install': 'brew install ollama && ollama pull qwen3.5:4b'},
    {'needs': 'Obsidian', 'app': 'Obsidian', 'why': 'read and edit the vault comfortably (pack obsidian)',
     'install': 'https://obsidian.md'},
    {'needs': 'codex', 'cmd': 'acpx', 'why': 'optional second AI as read-only worker (pack codex-worker)',
     'install': 'npm install -g acpx, then add pack codex-worker'},
]


def doctor(root=None):
    """What is installed, what each plugged pack still needs, and recommended extras."""
    report = {'core': {'python3': True, 'git': bool(shutil.which('git'))}, 'packs': [], 'recommended': []}
    packs = config(root).get('packs', []) if root else []
    for name in packs:
        report['packs'] += requirement_status(pack_manifest(name))
    for rec in RECOMMENDED:
        ok = bool(shutil.which(rec['cmd'])) if 'cmd' in rec else _has_app(rec['app'])
        if not ok:
            report['recommended'].append({k: rec[k] for k in ('needs', 'why', 'install')})
    cache = Path.home() / '.cache' / 'ai-dev-workspace' / 'update.json'
    report['kit'] = {'version': kit_meta()['version']}
    if cache.is_file():
        report['kit'].update(json.loads(cache.read_text())['result'])
    if root:
        report['workspace'] = str(root)
        report['valid'] = validate(root)['valid']
    return report


# --- releases and feedback-to-issue loop -------------------------------------------

def kit_meta():
    return json.loads((KIT / 'kit.json').read_text())


def _vtuple(v):
    # 1.2.3-beta.4 < 1.2.3: a final release outranks its pre-releases.
    m = re.match(r'v?(\d+)\.(\d+)\.(\d+)(?:-[A-Za-z]*\.?(\d+)?)?', v.strip())
    if not m:
        return (0, 0, 0, 0, 0)
    pre = m.group(4) if m.group(0) != f'{m[1]}.{m[2]}.{m[3]}' and '-' in m.group(0) else None
    return (int(m[1]), int(m[2]), int(m[3]), 0 if '-' in m.group(0) else 1, int(pre or 0))


def _repo():
    repo = os.environ.get('WS_REPO') or kit_meta()['repo']
    if repo.startswith('OWNER/'):
        raise WsError('This kit has no GitHub repo set yet; set "repo" in kit.json (owner/name) or WS_REPO.')
    return repo


def _get_json(url):
    req = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'ai-dev-workspace'})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.load(resp)


def check_update(force=False):
    """Compare the local kit version with the latest GitHub release; cached so it costs at most one call a day."""
    meta = kit_meta()
    cache = Path.home() / '.cache' / 'ai-dev-workspace' / 'update.json'
    if not force and cache.is_file():
        data = json.loads(cache.read_text())
        if time.time() - data.get('checked', 0) < meta.get('update_check_hours', 24) * 3600:
            return data['result']
    try:
        rel = _get_json(f'https://api.github.com/repos/{_repo()}/releases/latest')
        latest = rel['tag_name'].lstrip('v')
        result = {'current': meta['version'], 'latest': latest,
                  'update_available': _vtuple(latest) > _vtuple(meta['version']),
                  'notes': (rel.get('body') or '')[:1500], 'url': rel.get('html_url', '')}
    except (OSError, KeyError, ValueError, WsError) as exc:
        return {'current': meta['version'], 'update_available': False, 'error': str(exc)}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({'checked': time.time(), 'result': result}))
    return result


def update_kit():
    """Fast-forward the kit's own git checkout; refuses if the user has local changes."""
    if not (KIT / '.git').exists():
        raise WsError(f'{KIT} is not a git clone; download the new release from GitHub instead.')
    dirty = subprocess.run(['git', '-C', str(KIT), 'status', '--porcelain'], capture_output=True, text=True).stdout.strip()
    if dirty:
        raise WsError('The kit has local changes; commit or stash them first. Nothing was changed.')
    run = subprocess.run(['git', '-C', str(KIT), 'pull', '--ff-only'], capture_output=True, text=True)
    if run.returncode:
        raise WsError('git pull failed: ' + run.stderr.strip())
    return {'updated_to': kit_meta()['version'], 'git': run.stdout.strip()[-300:]}


FEEDBACK_RE = re.compile(r'^- \[( |x)\] (\S+) \*\*(\w+)\*\* \(([^)]*)\): (.*?)(?: — issue: (\S+))?$')


def _feedback_lines(root):
    path = vault(root) / 'Feedback.md'
    return path, (path.read_text().splitlines() if path.exists() else [])


def feedback_items(root):
    _, lines = _feedback_lines(root)
    items = []
    for i, line in enumerate(lines):
        m = FEEDBACK_RE.match(line)
        if m:
            items.append({'n': len(items) + 1, 'line': i, 'done': m[1] == 'x', 'date': m[2], 'kind': m[3],
                          'source': m[4], 'text': m[5], 'issue': m[6]})
    return items


def feedback_submit(root, n, yes=False, use_gh=None):
    """Turn feedback item n into a GitHub issue. Without yes, only returns the preview."""
    items = feedback_items(root)
    item = next((i for i in items if i['n'] == n), None)
    if not item:
        raise WsError(f'No feedback item {n}; see `ws feedback list --all`.')
    if item['issue']:
        raise WsError(f'Already submitted: {item["issue"]}')
    title = f'[{item["kind"]}] {item["text"][:70]}'
    body = (f'{redact(item["text"])}\n\n- kind: {item["kind"]}\n- recorded: {item["date"]}\n'
            f'- kit version: {kit_meta()["version"]}\n- packs: {", ".join(config(root).get("packs", []))}\n')
    preview = {'title': title, 'body': body, 'note': 'Check it contains nothing private, then re-run with --yes.'}
    if not yes:
        return preview
    repo = _repo()
    gh = shutil.which('gh') if use_gh is None else use_gh
    if gh:
        run = subprocess.run([gh, 'issue', 'create', '-R', repo, '-t', title, '-b', body, '-l', f'feedback,{item["kind"]}'],
                             capture_output=True, text=True)
        if run.returncode:
            raise WsError('gh issue create failed: ' + run.stderr.strip())
        url = run.stdout.strip().splitlines()[-1]
    else:
        query = urllib.parse.urlencode({'title': title, 'body': body, 'labels': f'feedback,{item["kind"]}'})
        return {'open_this_url': f'https://github.com/{repo}/issues/new?{query}',
                'then': 'After creating it, run: ws feedback link ' + str(n) + ' <issue-url>'}
    feedback_link(root, n, url)
    return {'issue': url}


def feedback_link(root, n, url):
    if not re.fullmatch(r'https://github\.com/[\w.-]+/[\w.-]+/issues/\d+', url):
        raise WsError('Expected a GitHub issue URL like https://github.com/owner/repo/issues/12')
    with lock(root):
        path, lines = _feedback_lines(root)
        item = next((i for i in feedback_items(root) if i['n'] == n), None)
        if not item:
            raise WsError(f'No feedback item {n}.')
        lines[item['line']] = lines[item['line']].split(' — issue: ')[0] + f' — issue: {url}'
        atomic_write(path, '\n'.join(lines) + '\n')
    return {'linked': url}


def feedback_sync(root, fetch=None):
    """Tick feedback whose GitHub issue is closed."""
    fetch = fetch or _get_json
    closed = []
    with lock(root):
        path, lines = _feedback_lines(root)
        for item in feedback_items(root):
            if item['issue'] and not item['done']:
                m = re.match(r'https://github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)', item['issue'])
                try:
                    state = fetch(f'https://api.github.com/repos/{m[1]}/issues/{m[2]}').get('state')
                except OSError:
                    continue
                if state == 'closed':
                    lines[item['line']] = lines[item['line']].replace('- [ ]', '- [x]', 1)
                    closed.append(item['issue'])
        if closed:
            atomic_write(path, '\n'.join(lines) + '\n')
    return {'closed': closed}


def notices(root):
    """Short things worth telling the user at session start, each with the command to run on their yes.

    Network use: at most one release check and one issue sync per day (cached); WS_OFFLINE=1 disables both.
    """
    out = []
    offline = os.environ.get('WS_OFFLINE') == '1'
    if not offline:
        upd = check_update()
        if upd.get('update_available'):
            first = next((l.strip('- ').strip() for l in upd.get('notes', '').splitlines() if l.strip()), '')
            out.append({'kind': 'update', 'message': f"ai-dev-workspace {upd['latest']} is available (you have {upd['current']})"
                        + (f': {first[:120]}' if first else '.'), 'suggest': 'ws update'})
        stamp = root / '.ws' / 'sync.json'
        linked = [i for i in feedback_items(root) if i['issue'] and not i['done']]
        last = json.loads(stamp.read_text()).get('at', 0) if stamp.is_file() else 0
        if linked and time.time() - last > 86400:
            (root / '.ws').mkdir(exist_ok=True)
            stamp.write_text(json.dumps({'at': time.time()}))
            for url in feedback_sync(root)['closed']:
                out.append({'kind': 'fixed', 'message': f'Your reported issue was closed: {url}. Update to get the fix if it is released.',
                            'suggest': 'ws update --check'})
    unsent = [i for i in feedback_items(root) if not i['done'] and not i['issue'] and i['kind'] != 'praise']
    if unsent:
        out.append({'kind': 'feedback', 'message': f'{len(unsent)} feedback note(s) not shared with the maintainers yet '
                    f'(oldest: "{unsent[0]["text"][:80]}").', 'suggest': f'ws feedback submit {unsent[0]["n"]}'})
    return out
