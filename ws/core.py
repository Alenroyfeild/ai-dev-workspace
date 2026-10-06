"""AI Dev Workspace core: tasks, claims, lessons, feedback, search, digest, run tracking.

Standard library only. Every function takes the workspace root so the CLI, the MCP
server and tests share one implementation.
"""
import contextlib
import ast
import datetime
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PACKAGED = (PACKAGE_DIR / 'kit.json').is_file()
KIT = PACKAGE_DIR if PACKAGED else PACKAGE_DIR.parent


def python_command():
    return sys.executable if PACKAGED else 'python3'


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


def redacted_line(value, field):
    if not isinstance(value, str) or any(c in value for c in '\r\n\x85\u2028\u2029'):
        raise WsError(f'{field} must be one line of text.')
    return redact(value)


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


def write_preserving(path, data, collisions):
    """Create kit content exclusively, staging conflicts without replacing user files."""
    path = Path(path)
    destination = path
    number = 0
    while True:
        if destination.is_file() and destination.read_bytes() == data:
            break
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open('xb') as stream:
                try:
                    stream.write(data)
                except BaseException:
                    destination.unlink()
                    raise
            break
        except (FileExistsError, IsADirectoryError):
            suffix = '.ws-new' + (f'.{number}' if number else '')
            destination = path.with_name(path.name + suffix)
            number += 1
    if destination != path:
        collisions.append(f'Kept {path.name}; kit content is in {destination.name}')
    return destination


def copy_preserving(source, target, collisions, skip=()):
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if str(relative) in skip:
            continue
        if path.is_dir():
            (target / relative).mkdir(parents=True, exist_ok=True)
        else:
            write_preserving(target / relative, path.read_bytes(), collisions)


def pack_rules(text, name):
    snippet = KIT / 'packs' / name / 'AGENTS.snippet.md'
    if snippet.is_file():
        rendered = snippet.read_text().replace('<kit>', str(KIT))
        if rendered.strip() not in text:
            return text.rstrip('\n') + '\n' + rendered
    return text


def _install_pack(target, name, collisions, install_rules=True):
    src = KIT / 'packs' / name
    if (src / 'vault').is_dir():
        copy_preserving(src / 'vault', target / 'vault', collisions)
    if install_rules:
        rules = target / 'AGENTS.md'
        text = rules.read_text()
        candidate = pack_rules(text, name)
        if candidate != text:
            # Appending keeps the user's rules byte-for-byte, so no sidecar is needed.
            atomic_write(rules, candidate)


def pack_add(root, name):
    """Plug a pack into an existing workspace; idempotent."""
    manifest = pack_manifest(name)
    cfg = config(root)
    collisions = []
    _install_pack(root, name, collisions)
    if name not in cfg['packs']:
        cfg['packs'].append(name)
        (root / 'workspace.json').write_text(json.dumps(cfg, indent=2) + '\n')
    nxt = [f"run {KIT / 'packs' / name / manifest['setup']}"] if manifest.get('setup') else []
    if manifest.get('selftest'):
        nxt.append(f"verify with {KIT / 'packs' / name / manifest['selftest']}")
    return {'pack': name, 'installed': True, 'collisions': collisions, 'next': nxt or ['nothing else needed'],
            'missing': [r for r in requirement_status(manifest) if not r['ok']]}


def init(target, name, packs=(), repos=()):
    target = Path(target).resolve()
    if (target / 'workspace.json').exists():
        raise WsError(f'{target} is already a workspace.')
    for pack in packs:
        pack_manifest(pack)
    target.mkdir(parents=True, exist_ok=True)
    collisions = []
    copy_preserving(KIT / 'template', target, collisions, skip=('AGENTS.md',))
    rules = (KIT / 'template' / 'AGENTS.md').read_text()
    for pack in packs:
        _install_pack(target, pack, collisions, install_rules=False)
        rules = pack_rules(rules, pack)
    write_preserving(target / 'AGENTS.md', rules.encode(), collisions)
    cfg = {'schema_version': 1, 'name': name, 'vault': 'vault', 'packs': list(packs),
           'repos': [str(Path(r).expanduser().resolve()) for r in repos], 'created': now()}
    # Claude Code reads the project .mcp.json; other detected clients are connected or previewed.
    connections = [connect(target, 'claude')]
    if not connections[0]['connected']:
        collisions.append(f"Kept .mcp.json; kit content is in {Path(connections[0]['path']).name}")
    install_memory_hooks(target, collisions)
    write_preserving(target / 'workspace.json', (json.dumps(cfg, indent=2) + '\n').encode(), collisions)
    for client in ('cursor', 'codex'):
        if shutil.which(client) or (client == 'cursor' and _has_app('Cursor')):
            connections.append(connect(target, client))
    if repos:
        codebase_map(target, repos[0])
    return dict(cfg, collisions=collisions, connections=connections)


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


SKIP_DIRS = {'.git', 'node_modules', 'Pods', 'build', 'DerivedData', 'dist', '.venv', 'venv', '__pycache__', 'Carthage', '.build'}


def _repo_files(repo):
    # Tracked files respect .gitignore; fall back to a walk that skips dependency and build folders.
    run = subprocess.run(['git', '-C', str(repo), 'ls-files', '-z'], capture_output=True, check=False)
    if run.returncode == 0 and run.stdout:
        return [repo / n for n in run.stdout.decode(errors='replace').split('\0') if n]
    return [p for p in repo.rglob('*') if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(repo).parts)]


def codebase_map(root, repo=None):
    root = Path(root).resolve()
    repos = config(root).get('repos', [])
    selected = repo or (repos[0] if repos else None)
    if not selected:
        raise WsError('Codebase map needs a repository path: `ws map /path/to/repo`.')
    repo = Path(selected).expanduser().resolve()
    if not repo.is_dir():
        raise WsError('Codebase map needs a repository path: `ws map /path/to/repo`.')
    files = _repo_files(repo)
    names = {'.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript', '.swift': 'Swift', '.go': 'Go', '.rs': 'Rust', '.java': 'Java', '.kt': 'Kotlin', '.rb': 'Ruby'}
    languages = {}
    for path in files:
        language = names.get(path.suffix.lower())
        if language: languages[language] = languages.get(language, 0) + 1
    folders = {}
    for path in files:
        parts = path.relative_to(repo).parts
        if len(parts) > 1:
            folders[parts[0]] = folders.get(parts[0], 0) + 1
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


def install_memory_hooks(root, collisions):
    command = 'env WS_ROOT=' + shlex.quote(str(root)) + ' ' + shlex.quote(python_command()) + ' ' + shlex.quote(str(KIT / 'bin/ws'))
    hooks = {'hooks': {event: [{'hooks': [{'type': 'command', 'timeout': 10,
                         'command': command + (' brief --hook' if event == 'SessionStart' else ' nudge --hook')}]}]
                       for event in ('SessionStart', 'PreCompact', 'Stop')}}
    data = (json.dumps(hooks, indent=2) + '\n').encode()
    for relative in ('.claude/settings.json', '.codex/hooks.json'):
        write_preserving(root / relative, data, collisions)


def mcp_command(root):
    return {'command': python_command(), 'args': [str(KIT / 'mcp/server.py'), '--root', str(Path(root).resolve())]}


def client_connected(root, client):
    if client == 'codex':
        path = Path.home() / '.codex/config.toml'
        text = path.read_text() if path.is_file() else ''
        match = re.search(r'^\[mcp_servers\.(?:ai-dev-workspace|"ai-dev-workspace"|\'ai-dev-workspace\')\]\s*$(.*?)(?=^\[|\Z)', text, re.M | re.S)
        if not match:
            return False
        fields = {}
        for key in ('command', 'args'):
            value = re.search(r'^' + key + r'\s*=\s*(\[.*?\]|"[^"\n]*"|\'[^\'\n]*\')', match[1], re.M | re.S)
            try:
                fields[key] = ast.literal_eval(value[1]) if value else None
            except (ValueError, SyntaxError):
                return False
        return fields == mcp_command(root)
    path = root / ('.mcp.json' if client == 'claude' else '.cursor/mcp.json')
    try:
        data = json.loads(path.read_text())
        return data.get('mcpServers', {}).get('ai-dev-workspace') == mcp_command(root)
    except (OSError, ValueError, AttributeError):
        return False


def link_skills(client):
    location = '.claude/skills' if client == 'claude' else '.agents/skills'
    directory = Path.home() / location
    linked, kept = [], []
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for source in sorted((KIT / 'skills').iterdir()):
            if not source.is_dir() or not (source / 'SKILL.md').is_file():
                continue
            try:
                (directory / source.name).symlink_to(source.resolve(), target_is_directory=True)
                linked.append(source.name)
            except FileExistsError:
                kept.append(source.name)
    except OSError as exc:
        raise WsError(f'Could not link skills into {directory}: {exc}. Existing names were kept.')
    return {'directory': str(directory), 'linked': linked, 'kept': kept}


def connect(root, client, write=False, skills=False, verify=False):
    result = _connect_config(root, client, write)
    if skills and client in ('claude', 'codex'):
        result['skills'] = link_skills(client)
    if verify and client in ('claude', 'cursor'):
        result['mcp'] = mcp_doctor(root, (client,))[0]
    return result


def _connect_config(root, client, write=False):
    if client not in ('claude', 'codex', 'cursor'):
        raise WsError('Client must be claude, codex or cursor.')
    if write and client != 'codex':
        raise WsError('--write applies only to the Codex global configuration.')
    server = mcp_command(root)
    if client == 'codex':
        block = '[mcp_servers.ai-dev-workspace]\ncommand = ' + json.dumps(server['command']) + '\nargs = ' + json.dumps(server['args']) + '\n'
        result = {'client': client, 'connected': client_connected(root, client), 'config': block}
        if not write or result['connected']:
            return result
        path = Path.home() / '.codex/config.toml'
        original = path.read_text() if path.exists() else ''
        if re.search(r'^(?:mcp_servers\s*=|mcp_servers\.|\[mcp_servers\.(?:"ai-dev-workspace"|\'ai-dev-workspace\'|ai-dev-workspace)(?:\]|\.))', original, re.M):
            raise WsError('Codex already has a different workspace entry; review the printed block manually.')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            number = 0
            while True:
                backup = path.with_name(path.name + '.ws-backup' + (f'.{number}' if number else ''))
                try:
                    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(path.read_bytes())
                    break
                except FileExistsError:
                    number += 1
            result['backup'] = str(backup)
        atomic_write(path, original.rstrip('\n') + '\n\n' + block)
        result['connected'] = True
        return result
    path = root / ('.mcp.json' if client == 'claude' else '.cursor/mcp.json')
    if client_connected(root, client):
        return {'client': client, 'connected': True, 'path': str(path)}
    data = {'mcpServers': {}}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
            if isinstance(existing, dict) and isinstance(existing.get('mcpServers'), dict):
                data = existing
        except (OSError, ValueError):
            pass
    data['mcpServers']['ai-dev-workspace'] = server
    collision = path.exists()
    destination = path.with_name(path.name + '.ws-new') if collision else path
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open('x') as stream:
            stream.write(json.dumps(data, indent=2) + '\n')
    except FileExistsError:
        pass
    return {'client': client, 'connected': not collision, 'path': str(destination),
            'note': 'Review the staged config; existing files were kept.' if collision else 'Project MCP configuration written; approve it in the client.'}


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


def _local_claim_path(root, task_id):
    if not ID_RE.fullmatch(task_id or ''):
        raise WsError('Task IDs use letters, digits, dot, dash or underscore (e.g. JIRA-123, fix-login).')
    return root / '.ws' / 'claims' / f'{task_id}.json'


def _claim_defaults(root, task_id, worker, token):
    if worker is not None and token is not None:
        return worker, token
    path = _local_claim_path(root, task_id)
    try:
        local = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return worker, token
    return worker if worker is not None else local.get('worker'), token if token is not None else local.get('token')


def task_new(root, task_id, title, objective='', branch='', repo=''):
    title = redacted_line(title, 'Title')
    branch = redacted_line(branch, 'Branch')
    repo = redacted_line(repo, 'Repo')
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


def claim_note(root, task_id, meta):
    """Tell readers whether a claim was made from this workspace (local claim file matches)."""
    if not meta.get('claimed_by'):
        return ''
    try:
        local = json.loads(_local_claim_path(root, task_id).read_text())
    except (OSError, ValueError, WsError):
        local = {}
    if local.get('token') and local.get('token') == meta.get('claim_token'):
        return 'claimed in this workspace: continue; ws claim resumes it'
    return f"claimed elsewhere by {meta['claimed_by']}: ask before taking over"


def task_list(root):
    out = []
    for path in sorted((vault(root) / 'Tasks').glob('*.md')):
        text = path.read_text()
        meta = parse_meta(text)
        title = re.search(r'^# (.+)$', text, re.M)
        out.append({'id': meta.get('id', path.stem), 'title': title.group(1) if title else path.stem,
                    'status': meta.get('status', 'unknown'), 'claimed_by': meta.get('claimed_by', ''),
                    'claim': claim_note(root, meta.get('id', path.stem), meta),
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
    meta = parse_meta(text)
    return {'task': task_id, 'sha': digest_text(text), 'meta': meta, 'claim': claim_note(root, task_id, meta),
            'sections': {s: section(text, s) for s in sections}}


def claim(root, task_id, worker):
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', worker):
        raise WsError('Worker is a short label such as claude-main or codex-1.')
    with lock(root):
        path = task_path(root, task_id)
        text = path.read_text()
        meta = parse_meta(text)
        if meta.get('claimed_by'):
            # The local claim file (gitignored) proves this workspace made the claim: a later session here resumes it.
            try:
                local = json.loads(_local_claim_path(root, task_id).read_text())
            except (OSError, ValueError):
                local = {}
            if local.get('token') and local.get('token') == meta.get('claim_token'):
                return {'task': task_id, 'worker': meta['claimed_by'], 'token': local['token'], 'resumed': True}
            raise WsError(f'{task_id} is claimed by {meta["claimed_by"]} since {meta.get("claimed_at")}. '
                          'Release it first (only after checking that session has stopped).')
        if meta.get('status') == 'done':
            raise WsError(f'{task_id} is done; reopen it with a checkpoint first.')
        token = uuid.uuid4().hex
        atomic_write(path, set_meta(text, {'claimed_by': worker, 'claim_token': token, 'claimed_at': now()}))
        atomic_write(_local_claim_path(root, task_id), json.dumps({'worker': worker, 'token': token}) + '\n')
    return {'task': task_id, 'worker': worker, 'token': token}


def release(root, task_id, worker=None, token=None):
    with lock(root):
        worker, token = _claim_defaults(root, task_id, worker, token)
        path = task_path(root, task_id)
        text = path.read_text()
        meta = parse_meta(text)
        if meta.get('claimed_by') != worker or meta.get('claim_token') != token:
            raise WsError('Worker/token do not match the claim; nothing changed.')
        atomic_write(path, set_meta(text, {'claimed_by': '', 'claim_token': '', 'claimed_at': ''}))
        _local_claim_path(root, task_id).unlink(missing_ok=True)
    return {'task': task_id, 'released': True}


def checkpoint(root, task_id, status, next_action, expected_sha=None, worker=None, token=None, notes=None):
    if status not in STATUSES:
        raise WsError(f'Status must be one of: {", ".join(STATUSES)}')
    if not next_action.strip():
        raise WsError('Next action is required: say exactly what the next person or AI should do.')
    with lock(root):
        worker, token = _claim_defaults(root, task_id, worker, token)
        path = task_path(root, task_id)
        text = path.read_text()
        meta = parse_meta(text)
        if meta.get('claimed_by') and (worker != meta['claimed_by'] or token != meta.get('claim_token')):
            raise WsError(f'{task_id} is claimed by {meta["claimed_by"]}; pass its worker and token.')
        if expected_sha and expected_sha != digest_text(text):
            raise WsError('Task changed since you read it; read it again before checkpointing.')
        text = set_meta(text, {'status': status, 'updated': now(), 'checkpoint_at': now()})
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


def _session_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ' '.join(_session_text(item) for item in value)
    if isinstance(value, dict):
        return ' '.join(_session_text(value[key]) for key in ('text', 'content', 'message') if key in value)
    return ''


def _session_file(path):
    try:
        return '~/' + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def session_search(query, roots=None):
    """Search local Claude Code and Codex JSONL transcripts without loading whole files."""
    query = ' '.join(query.split())
    if not query:
        raise WsError('Session search needs words to find.')
    roots = roots or {'claude': Path.home() / '.claude/projects', 'codex': Path.home() / '.codex/sessions'}
    hits = []
    for tool, root in roots.items():
        root = Path(root)
        if not root.is_dir():
            continue
        for path in root.rglob('*.jsonl'):
            if path.stat().st_size > 50 * 1024 * 1024:
                continue
            with path.open(errors='replace') as stream:
                for line in stream:
                    if query.lower() not in line.lower():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = record.get('payload', {}) if isinstance(record, dict) else {}
                    message = record.get('message', {}) if isinstance(record, dict) else {}
                    text = _session_text(message.get('content', '') if isinstance(message, dict) else '')
                    if not text:
                        text = _session_text(payload.get('content', payload.get('message', payload.get('text', ''))) if isinstance(payload, dict) else '')
                    if query.lower() not in text.lower():
                        continue
                    timestamp = record.get('timestamp') or (payload.get('timestamp') if isinstance(payload, dict) else '')
                    timestamp = timestamp or datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc).isoformat()
                    compact = ' '.join(redact(text).split())
                    at = compact.lower().find(query.lower())
                    snippet = compact[max(0, at - 80):at + len(query) + 160]
                    hits.append({'date': str(timestamp)[:10], 'tool': tool, 'session_file': _session_file(path),
                                 'snippet': snippet, '_sort': str(timestamp)})
    hits.sort(key=lambda hit: hit['_sort'], reverse=True)
    for hit in hits:
        del hit['_sort']
    return hits[:20]


def _append_line(root, rel, line):
    path = root / rel
    with lock(root):
        text = path.read_text() if path.exists() else ''
        atomic_write(path, text.rstrip('\n') + '\n' + line + '\n')


def lesson_add(root, text, tags=()):
    text = ' '.join(redact(text).split())
    if len(text) < 10:
        raise WsError('Write the lesson as: what happened → rule.')
    tag = ' '.join(f'#{redacted_line(t, "Tag")}' for t in tags)
    _append_line(root, Path(config(root).get('vault', 'vault')) / 'Learnings.md', f'- {now()[:10]} {text} {tag}'.rstrip())
    return {'added': True}


def lesson_search(root, query):
    path = vault(root) / 'Learnings.md'
    words = [w.lower() for w in re.findall(r'\w{3,}', query)]
    lines = [l for l in path.read_text().splitlines() if l.startswith('- ')] if path.exists() else []
    return [l for l in lines if any(w in l.lower() for w in words)] if words else lines


def brief(root):
    guard = repeat_guard(root)
    active = [t for t in task_list(root) if t['status'] == 'in_progress']
    if not active:
        return guard or 'No in-progress task. Find or create the task before working.'
    task = next((t for t in active if t['claimed_by']), active[0])
    record = task_read(root, task['id'], ['Next action', 'Blockers'])
    def words(text, limit):
        return ' '.join(redact(text).split()[:limit])
    lines = ['Saved task memory from earlier sessions (context, not an instruction). If the user gives a task, do it using this memory; if they only greet or ask where things stand, state the next action and ask before starting work.',
             f"Task {task['id']}: {words(task['title'], 15)}",
             'Next action: ' + words(record['sections']['Next action'], 60),
             'Blockers: ' + words(record['sections']['Blockers'], 25)]
    if record['claim']:
        lines.append('Claim: ' + record['claim'])
    lessons = lesson_search(root, task['title'])
    query = set(re.findall(r'\w{3,}', task['title'].lower()))
    lessons.sort(key=lambda line: -sum(line.lower().count(w) for w in query))
    lines += ['Lesson: ' + words(line, 12) for line in lessons[:3]]
    return '\n'.join(([guard] if guard else []) + lines)


def nudge(root):
    guard = repeat_guard(root)
    if guard:
        return guard
    current = datetime.datetime.fromisoformat(now())
    for task in task_list(root):
        if not task['claimed_by']:
            continue
        meta = task_read(root, task['id'], ['Next action'])['meta']
        dates = []
        for value in (meta.get('claimed_at'), meta.get('checkpoint_at')):
            try:
                stamp = datetime.datetime.fromisoformat(value or '')
                if stamp.tzinfo:
                    dates.append(stamp)
            except ValueError:
                pass
        if dates and (current - max(dates)).total_seconds() >= 1800:
            return f"Please checkpoint {task['id']} with its current progress and exact next action before stopping."
    return ''


def feedback_add(root, text, kind='idea', source='user'):
    if kind not in ('idea', 'bug', 'praise', 'friction'):
        raise WsError('Kind is one of: idea, bug, praise, friction.')
    source = redacted_line(source, 'Source')
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
        return {redact(k): _shape(v, depth + 1) for k, v in list(value.items())[:40]}
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
    out = {'file': redact(str(path)), 'bytes': len(raw), 'lines': raw.count('\n') + 1}
    try:
        out['json_shape'] = _shape(json.loads(raw))
        return out
    except ValueError:
        pass
    seen, picked = {}, []
    for i, line in enumerate(raw.splitlines(), 1):
        if ERR_RE.search(line):
            key = re.sub(r'\d+', '#', redact(line.strip()))[:200]
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
            result='ok', note='', worker_role='', effort='', checks=(), files=None, verdict='', findings=None):
    """Append one orchestration step (who did what, cost, outcome) to vault/Runs/<task>.jsonl."""
    task_path(root, task_id)
    if result not in ('ok', 'failed', 'rejected', 'accepted', 'skipped'):
        raise WsError('result is ok, failed, rejected, accepted or skipped.')
    entry = {'at': now(), 'task': task_id, 'step': redacted_line(step, 'Step'),
             'provider': redacted_line(provider, 'Provider'), 'model': redacted_line(model, 'Model'),
             'tokens_in': int(tokens_in), 'tokens_out': int(tokens_out), 'seconds': float(seconds),
             'result': result, 'note': redact(note)[:300]}
    if verdict not in ('', 'accepted', 'changes', 'rejected'):
        raise WsError('verdict is accepted, changes or rejected.')
    for key, value in (('files', files), ('findings', findings)):
        if value is not None:
            if type(value) is not int or value < 0:
                raise WsError(f'{key} must be a nonnegative integer.')
            entry[key] = value
    for key, value in (('worker_role', worker_role), ('effort', effort), ('verdict', verdict)):
        if value:
            entry[key] = redacted_line(value, key)
    parsed = []
    for check in checks:
        command, separator, code = redacted_line(check, 'Check').rpartition('=')
        if not separator or not command.strip() or not re.fullmatch(r'-?\d+', code):
            raise WsError('Check must be <command>=<integer exit code>; commands are recorded, not executed.')
        parsed.append({'command': command, 'exit_code': int(code)})
    if parsed:
        entry['checks'] = parsed
    path = vault(root) / 'Runs' / f'{task_id}.jsonl'
    with lock(root):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as stream:
            stream.write(json.dumps(entry) + '\n')
    return entry


def run_entries(root, task_id):
    task_path(root, task_id)
    path = vault(root) / 'Runs' / f'{task_id}.jsonl'
    if not path.exists():
        return []
    entries = []
    with path.open() as stream:
        for line in stream:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue  # A torn or hand-edited line must not break session hooks.
    return [e for e in entries if isinstance(e, dict)]


def repeat_guard(root):
    # Only open work can warn; finished or abandoned tasks must not block every later session.
    open_tasks = {t['id'] for t in task_list(root) if t['status'] in ('in_progress', 'review', 'blocked')}
    for path in sorted((vault(root) / 'Runs').glob('*.jsonl')):
        if path.stem not in open_tasks:
            continue
        entries = run_entries(root, path.stem)[-2:]
        def failed(entry):
            return (entry.get('result') in ('failed', 'rejected')
                    or entry.get('verdict') in ('changes', 'rejected')
                    or any(check['exit_code'] != 0 for check in entry.get('checks', [])))
        if len(entries) == 2 and all(failed(entry) for entry in entries):
            return f'Task {path.stem}: stop: two failed attempts, re-diagnose before trying again'
    return ''


def trace(root, task_id):
    entries = run_entries(root, task_id)
    lines = [f'# Trace: {task_id}', '', 'Checks and verdicts are reported by the caller; ws does not execute checks.']
    for number, entry in enumerate(entries, 1):
        lines += ['', f"## {number}. {entry['at']} — {entry['step']}",
                  f"- Who: {entry['provider']}; role: {entry.get('worker_role', 'unspecified')}; model: {entry['model'] or 'unspecified'}; effort: {entry.get('effort', 'unspecified')}",
                  f"- Tokens: {entry['tokens_in']} in / {entry['tokens_out']} out; seconds: {entry['seconds']}",
                  f"- Result: {entry['result']}; verdict: {entry.get('verdict', 'unspecified')}; files: {entry.get('files', 'unspecified')}; findings: {entry.get('findings', 'unspecified')}"]
        lines += [f"- Check: {check['command']} = {check['exit_code']}" for check in entry.get('checks', [])]
        if entry.get('note'):
            lines.append('- Note: ' + ' '.join(entry['note'].split()))
    lines += ['', 'Total tokens: ' + str(sum(e['tokens_in'] + e['tokens_out'] for e in entries))]
    return redact('\n'.join(lines))


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


def _mcp_config(root, client):
    path = root / ('.mcp.json' if client == 'claude' else '.cursor/mcp.json')
    if not path.exists():
        return None
    try:
        server = json.loads(path.read_text())['mcpServers']['ai-dev-workspace']
        command, args = server['command'], server.get('args', [])
        if not isinstance(command, str) or not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError('command and args must be strings')
        return path, [command, *args]
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        return path, str(exc)


def mcp_doctor(root, clients=('claude', 'cursor')):
    checks = []
    messages = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'ws-doctor', 'version': '1'}}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'status', 'arguments': {}}},
    ]
    for client in clients:
        config = _mcp_config(root, client)
        if config is None:
            continue
        path, command = config
        report = {'client': client, 'config': str(path.relative_to(root)), 'ok': False}
        if isinstance(command, str):
            report.update(step='config', stderr=command)
            checks.append(report)
            continue
        try:
            run = subprocess.run(command, input=''.join(json.dumps(message) + '\n' for message in messages),
                                 capture_output=True, text=True, timeout=10)
        except OSError as exc:
            report.update(step='launch', stderr=str(exc)[-400:])
            checks.append(report)
            continue
        except subprocess.TimeoutExpired as exc:
            report.update(step='timeout', stderr=(exc.stderr or '')[-400:])
            checks.append(report)
            continue
        try:
            replies = {reply.get('id'): reply for reply in map(json.loads, run.stdout.splitlines())}
        except (AttributeError, json.JSONDecodeError):
            replies = {}
        for ident, step in ((1, 'initialize'), (2, 'tools/list'), (3, 'status')):
            reply = replies.get(ident, {})
            if 'error' in reply or reply.get('result', {}).get('isError') or 'result' not in reply:
                report.update(step=step, stderr=run.stderr[-400:])
                break
        else:
            report.update(ok=True, steps=['initialize', 'tools/list', 'status'])
        checks.append(report)
    return checks


def doctor(root=None, mcp=False):
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
        report['clients'] = {client: client_connected(root, client) for client in ('claude', 'codex', 'cursor')}
        if mcp:
            report['mcp'] = mcp_doctor(root)
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


def _offline(action):
    return {'offline': True, 'message': f'Offline mode: {action} is disabled while WS_OFFLINE=1.'}


def check_update(force=False):
    """Compare the local kit version with the latest GitHub release; cached so it costs at most one call a day."""
    if os.environ.get('WS_OFFLINE') == '1':
        return _offline('update checks')
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
    if PACKAGED:
        return {'installation': 'package', 'command': 'pipx upgrade ai-dev-workspace',
                'note': 'Run this outside ws to update the pipx environment from its original install source. '
                        'For a pip-managed venv, use its pip to reinstall from the original source.'}
    if os.environ.get('WS_OFFLINE') == '1':
        return _offline('kit updates')
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
    title = f'[{item["kind"]}] {redact(item["text"])[:70]}'
    body = redact(f'{item["text"]}\n\n- kind: {item["kind"]}\n- recorded: {item["date"]}\n'
                  f'- kit version: {kit_meta()["version"]}\n- packs: {", ".join(config(root).get("packs", []))}\n')
    preview = {'title': title, 'body': body, 'note': 'Check it contains nothing private, then re-run with --yes.'}
    if not yes:
        return preview
    if os.environ.get('WS_OFFLINE') == '1':
        return _offline('feedback submission')
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
    if os.environ.get('WS_OFFLINE') == '1':
        return dict(_offline('feedback sync'), closed=[])
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
