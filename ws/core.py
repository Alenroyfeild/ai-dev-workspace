"""AI Dev Workspace core: tasks, claims, lessons, feedback, search, digest, run tracking.

Standard library only. Every function takes the workspace root so the CLI, the MCP
server and tests share one implementation.
"""
import contextlib
import io
import ast
import base64
import datetime
import errno
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import sre_parse
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PACKAGED = (PACKAGE_DIR / 'kit.json').is_file()
KIT = PACKAGE_DIR if PACKAGED else PACKAGE_DIR.parent
WINDOWS = os.name == 'nt'


def python_command():
    return sys.executable if PACKAGED or WINDOWS else 'python3'


def command_line(arguments):
    if WINDOWS:
        # Paths are always quoted, including those containing shell metacharacters without spaces.
        parts = []
        for argument in arguments:
            rendered = subprocess.list2cmdline([argument])
            parts.append(rendered if rendered.startswith('"') or argument.startswith('--') else '"' + re.sub(r'(\\+)$', r'\1\1', rendered) + '"')
        return ' '.join(parts)
    return shlex.join(arguments)


_HOOK_PREFIX = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand']
_HOOK_SCRIPT = (
    "[Console]::InputEncoding=[Text.UTF8Encoding]::new($false);"
    "$a=ConvertFrom-Json ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PAYLOAD')));"
    "$p=New-Object Diagnostics.Process;$p.StartInfo.FileName=$a.argv[0];$p.StartInfo.Arguments=$a.arguments;"
    "$p.StartInfo.UseShellExecute=$false;$p.StartInfo.RedirectStandardInput=$true;$p.StartInfo.CreateNoWindow=$true;"
    "[void]$p.Start();$b=[Text.Encoding]::UTF8.GetBytes([Console]::In.ReadToEnd());"
    "$p.StandardInput.BaseStream.Write($b,0,$b.Length);$p.StandardInput.BaseStream.Close();"
    "$p.WaitForExit();exit $p.ExitCode"
)


def encoded_hook_command(arguments):
    # Native Process.Start avoids cmd expansion of every path; stdin is forwarded as UTF-8 bytes.
    data = {'argv': arguments, 'arguments': subprocess.list2cmdline(arguments[1:])}
    payload = base64.b64encode(json.dumps(data).encode('utf-8')).decode('ascii')
    script = _HOOK_SCRIPT.replace('PAYLOAD', payload)
    return ' '.join(_HOOK_PREFIX + [base64.b64encode(script.encode('utf-16-le')).decode('ascii')])


def encoded_hook_args(parts):
    """Recognize our exact launcher without evaluating PowerShell during upgrades."""
    if len(parts) != 6 or parts[:5] != _HOOK_PREFIX: raise ValueError('Unknown hook launcher')
    script = base64.b64decode(parts[5], validate=True).decode('utf-16-le')
    match = re.fullmatch(re.escape(_HOOK_SCRIPT).replace('PAYLOAD', r'([A-Za-z0-9+/=]+)'), script)
    if not match: raise ValueError('Unknown hook script')
    data = json.loads(base64.b64decode(match[1], validate=True).decode('utf-8'))
    if not isinstance(data, dict) or set(data) != {'argv', 'arguments'}: raise ValueError('Unknown hook payload')
    args = data['argv']
    if not isinstance(args, list) or not args or any(not isinstance(a, str) for a in args) or data['arguments'] != subprocess.list2cmdline(args[1:]):
        raise ValueError('Invalid hook arguments')
    return args


REQUIRED = ('Objective', 'Acceptance criteria', 'Evidence', 'Checks', 'Blockers', 'Next action', 'Handoff')
STATUSES = ('backlog', 'ready', 'in_progress', 'review', 'blocked', 'done')
ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}')
SECRET_RE = re.compile(
    r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----'
    r'|\bBearer\s+[A-Za-z0-9._~+/=-]{8,}'
    r'|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'
    r'|(?<!claim_)(?i:(?:api[_-]?key|token|secret|password)["\']?\s*[:=]\s*["\']?)[A-Za-z0-9/+_.-]{12,}'
    r'|(?i:authorization["\']?\s*[:=]\s*["\']?(?:basic|bearer|digest|token)\s+)[^\s"\']{8,}'
    # .env-style names ending in KEY/TOKEN/SECRET/PASSWORD; upper case only, so prose is left alone.
    r'|(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)\s*=\s*(?:"[^"\n]*"|\'[^\'\n]*\'|[^\s"\']+)', re.S)
URL_CREDENTIALS_RE = re.compile(r'(\b[A-Za-z][A-Za-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@')
PRIVATE_RE = re.compile(r'<private>.*?</private>', re.I | re.S)
HOME_PATH_RE = re.compile(r'(?<![\w.~-])(?:/Users|/home)/[^/\s]+|(?<![\w.~-])[A-Za-z]:\\Users\\[^\\\s]+')


class WsError(ValueError):
    """A user-facing error; the message says what to do."""


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def redact(text):
    return URL_CREDENTIALS_RE.sub(r'\1[REDACTED]@', SECRET_RE.sub('[REDACTED]', text))


def localize_paths(text, root):
    """Workspace root becomes `.`; other absolute home paths become `~` (Windows separators too)."""
    for base in {str(root), str(Path(root).resolve())}:
        text = re.sub(re.escape(base) + r'(?![\w.-])', '.', text)
    text = HOME_PATH_RE.sub('~', text)
    # Only the tail of a Windows path still has backslashes: normalise it after the `~`.
    return re.sub(r'~((?:\\[^\\\s/]+)+)', lambda m: '~' + m.group(1).replace('\\', '/'), text)


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
    return json.loads((root / 'workspace.json').read_text(encoding='utf-8'))


def vault(root):
    value = config(root).get('vault', 'vault')
    if not isinstance(value, str) or Path(value).is_absolute() or '..' in Path(value).parts:
        raise WsError('Vault must be a relative workspace directory; review workspace.json.')
    return inside(root / value, [root])


def inside(path, roots):
    original = Path(path).expanduser()
    try: path = original.resolve()
    except (OSError, RuntimeError): raise WsError('Path cannot be resolved safely; check it, then run ws doctor.')
    if not any(path == Path(r).resolve() or Path(r).resolve() in path.parents for r in roots):
        raise WsError('Path is outside declared roots; review workspace.json repos or use an explicit CLI path.')
    return original


def read_roots(root):
    repos = config(root).get('repos', [])
    if not isinstance(repos, list) or any(not isinstance(p, str) or not p for p in repos):
        raise WsError('Repos must be a list of paths; review workspace.json, then run ws doctor.')
    return [root] + [Path(p).expanduser() for p in repos]


MAX_READ_BYTES = 50 * 1024 * 1024


def read_text(path, roots=None, errors='replace'):
    try:
        path = (inside(path, roots) if roots is not None else Path(path).expanduser()).resolve()
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_READ_BYTES: raise WsError('Read requires a regular file under 50 MB; run ws digest on a smaller file.')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode): raise WsError('Non-regular file refused; run ws doctor.')
            data = source.read(MAX_READ_BYTES + 1)
        if len(data) > MAX_READ_BYTES: raise WsError('Read exceeds 50 MB; run ws digest on a smaller file.')
        return data.decode('utf-8', errors=errors).replace('\r\n', '\n')  # CRLF from Windows editors must not hide frontmatter
    except (OSError, RuntimeError):
        raise WsError('File cannot be read safely; check the path, then run ws doctor.')


def pack_manifest(name):
    if not isinstance(name, str) or not ID_RE.fullmatch(name): raise WsError('Invalid pack name; run ws pack list.')
    path = KIT / 'packs' / name / 'pack.json'
    inside(path, [KIT / 'packs'])
    if not path.is_file():
        raise WsError(f'Unknown pack {name}. Available: {", ".join(available_packs())}')
    return json.loads(read_text(path, [KIT / 'packs']))


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
        rendered = snippet.read_text(encoding='utf-8').replace('<kit>', str(KIT))
        if rendered.strip() not in text:
            return text.rstrip('\n') + '\n' + rendered
    return text


def _install_pack(target, name, collisions, install_rules=True):
    src = KIT / 'packs' / name
    if (src / 'vault').is_dir():
        copy_preserving(src / 'vault', target / 'vault', collisions)
    if install_rules:
        rules = target / 'AGENTS.md'
        text = rules.read_text(encoding='utf-8')
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
    copy_preserving(KIT / 'template', target, collisions, skip=('AGENTS.md', 'routing.json', 'routing-presets.json'))
    from .orchestration import routing_template
    write_preserving(target / 'routing.json', routing_template().encode(), collisions)
    from . import upgrade
    rules = upgrade.block((KIT / 'template' / 'AGENTS.md').read_text(encoding='utf-8'))
    for pack in packs:
        _install_pack(target, pack, collisions, install_rules=False)
        rules = pack_rules(rules, pack)
    write_preserving(target / 'AGENTS.md', rules.encode(), collisions)
    cfg = {'schema_version': 2, 'kit_version': kit_meta()['version'], 'content_version': upgrade.fingerprint(target), 'upgrade_pending': [], 'name': name, 'vault': 'vault', 'packs': list(packs),
           'repos': [str(Path(r).expanduser().resolve()) for r in repos], 'created': now()}
    # Claude Code reads the project .mcp.json; other detected clients are connected or previewed.
    connections = [connect(target, 'claude')]
    if not connections[0]['connected']:
        collisions.append(f"Kept .mcp.json; kit content is in {Path(connections[0]['path']).name}")
    install_memory_hooks(target, collisions)
    for relative, text in upgrade.skills().items():
        write_preserving(target / relative, text.encode(), collisions)
    for relative, text in upgrade.pointer_files().items():
        write_preserving(target / relative, text.encode(), collisions)
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
            scripts = json.loads(_map_text(package, repo)).get('scripts', {})
            commands.extend(f'npm run {name}' for name in scripts if any(x in name.lower() for x in ('build', 'test', 'run', 'start', 'dev')))
        except json.JSONDecodeError:
            pass
    makefile = next((p for p in (repo / 'Makefile', repo / 'makefile') if p.is_file()), None)
    if makefile:
        commands.extend(f'make {m.group(1)}' for m in re.finditer(r'^([A-Za-z][\w.-]*):', _map_text(makefile, repo), re.M)
                        if any(x in m.group(1).lower() for x in ('build', 'test', 'run', 'start')))
    if (repo / 'Podfile').is_file(): commands.append('pod install')
    if any((repo / p).is_file() for p in ('build.gradle', 'build.gradle.kts', 'gradlew')):
        commands.extend(('./gradlew build', './gradlew test', './gradlew run'))
    pyproject = repo / 'pyproject.toml'
    if pyproject.is_file():
        data = _map_text(pyproject, repo)
        if 'pytest' in data: commands.append('python -m pytest')
        if '[build-system]' in data: commands.append('python -m build')
    if (repo / 'Cargo.toml').is_file(): commands.extend(('cargo build', 'cargo test', 'cargo run'))
    if (repo / 'go.mod').is_file(): commands.extend(('go build ./...', 'go test ./...', 'go run .'))
    return list(dict.fromkeys(commands))[:20]


SKIP_DIRS = {'.git', 'node_modules', 'Pods', 'build', 'DerivedData', 'dist', '.venv', 'venv', '__pycache__', 'Carthage', '.build'}


def _map_text(path, repo):
    try: return read_text(path, [repo])
    except WsError: return ''


def _repo_files(repo):
    # Tracked files respect .gitignore; fall back to a walk that skips dependency and build folders.
    run = subprocess.run(['git', '-C', str(repo), 'ls-files', '-z'], capture_output=True, check=False)
    if run.returncode == 0 and run.stdout:
        return [repo / n for n in run.stdout.decode(errors='replace').split('\0') if n]
    return [p for p in repo.rglob('*') if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(repo).parts)]


def _graphify_report(repo):
    path = repo / 'graphify-out' / 'GRAPH_REPORT.md'
    return path if path.is_file() else None


def codebase_map(root, repo=None, allow_external=False):
    root = Path(root).resolve()
    repos = config(root).get('repos', [])
    selected = repo or (repos[0] if repos else None)
    if not selected:
        raise WsError('Codebase map needs a repository path: `ws map /path/to/repo`.')
    repo = Path(selected).expanduser().resolve()
    if not allow_external: inside(repo, read_roots(root))
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
    heading = next((line[2:].strip() for line in _map_text(readme, repo).splitlines() if line.startswith('# ')), 'No README heading') if readme else 'No README found'
    section = ['<!-- ws:codebase-map:start -->', f'Repository: `{repo}`', '', f'## README\n{heading}', '', '## Languages']
    section.extend([f'- {name}: {count}' for name, count in sorted(languages.items(), key=lambda x: (-x[1], x[0]))] or ['- None detected'])
    section.extend(['', '## Commands'])
    section.extend([f'- `{c}`' for c in _map_commands(repo)] or ['- None found'])
    section.extend(['', '## Top-level folders'])
    section.extend([f'- {name}: {count} files' for name, count in sorted(folders.items())] or ['- None'])
    section.extend(['', '## Most changed (90 days)'])
    section.extend([f'- {name}: {count}' for name, count in sorted(changed.items(), key=lambda x: (-x[1], x[0]))[:15]] or ['- No Git history'])
    report = _graphify_report(repo)
    if report:
        headings = []
        with io.StringIO(_map_text(report, repo)) as source:
            for line in source:
                if line.startswith('#'):
                    headings.append(line.lstrip('#').strip())
                if len(headings) == 5:
                    break
        section.extend(['', '## Graphify report', f'- [Graphify report]({report})'])
        section.extend([f'- {heading}' for heading in headings])
    section.append('<!-- ws:codebase-map:end -->')
    rendered = redact('\n'.join(section) + '\n')
    path = inside(vault(root) / 'Project' / 'Codebase map.md', [root])
    existing = read_text(path, [root]) if path.exists() else '# Codebase map\n'
    pattern = r'<!-- ws:codebase-map:start -->.*?<!-- ws:codebase-map:end -->\n?'
    text = re.sub(pattern, lambda _: rendered, existing, flags=re.S) if re.search(pattern, existing, re.S) else existing.rstrip() + '\n\n' + rendered
    with lock(root): atomic_write(path, text)
    return {'repo': str(repo), 'path': path.relative_to(root).as_posix(), 'words': len(rendered.split())}


def memory_hooks(root, client='claude'):
    arguments = [python_command(), str(KIT / 'bin/ws'), '--workspace-root', str(root)]
    command = command_line(arguments)
    events = ('sessionStart', 'preCompact', 'stop', 'sessionEnd') if client == 'cursor' else ('SessionStart', 'PreCompress', 'AfterAgent', 'SessionEnd') if client == 'gemini' else ('SessionStart', 'PreCompact', 'Stop')
    prompt_event = {'claude': 'UserPromptSubmit', 'codex': 'UserPromptSubmit', 'cursor': 'beforeSubmitPrompt', 'gemini': 'BeforeAgent'}.get(client)
    result = {'hooks': {}}
    if client == 'cursor': result['version'] = 1
    for event in events:
        suffix = ['brief' if event.lower() == 'sessionstart' else 'nudge', '--hook'] + ([] if client == 'claude' else ['--client', client])
        hook = {'type': 'command', 'timeout': 10000 if client == 'gemini' else 10,
                'command': encoded_hook_command(arguments + suffix) if WINDOWS and any('%' in a for a in arguments) else command + ' ' + ' '.join(suffix)}
        result['hooks'][event] = [hook if client in ('cursor', 'vscode') else {'hooks': [hook]}]
    if prompt_event:
        suffix = ['paste', '--hook', '--client', client]
        hook = {'type': 'command', 'timeout': 10000 if client == 'gemini' else 10,
                'command': encoded_hook_command(arguments + suffix) if WINDOWS and any('%' in a for a in arguments) else command + ' ' + ' '.join(suffix)}
        result['hooks'][prompt_event] = [hook if client == 'cursor' else {'hooks': [hook]}]
    return result
def install_memory_hooks(root, collisions):
    for client, relative in (('claude', '.claude/settings.json'), ('codex', '.codex/hooks.json')):
        data = (json.dumps(memory_hooks(root, client), indent=2) + '\n').encode()
        write_preserving(root / relative, data, collisions)


def upgrade_workspace(root, dry_run=False):
    from .upgrade import upgrade
    return upgrade(root, dry_run)


def mcp_command(root):
    return {'command': python_command(), 'args': [str(KIT / 'mcp/server.py'), '--root', str(Path(root).resolve())]}


# Project MCP config per client: (file, key holding the server map).
MCP_LOCATIONS = {'claude': ('.mcp.json', 'mcpServers'), 'cursor': ('.cursor/mcp.json', 'mcpServers'),
                 'vscode': ('.vscode/mcp.json', 'servers'), 'gemini': ('.gemini/settings.json', 'mcpServers')}


def client_connected(root, client):
    if client == 'codex':
        path = Path.home() / '.codex/config.toml'
        text = path.read_text(encoding='utf-8') if path.is_file() else ''
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
    locations = MCP_LOCATIONS
    path, key = (root / locations[client][0], locations[client][1]) if client in locations else (None, None)
    if path is None: return False
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data.get(key, {}).get('ai-dev-workspace') == mcp_command(root)
    except (OSError, ValueError, AttributeError):
        return False


def link_skills(client, root):
    location = '.claude/skills' if client == 'claude' else '.agents/skills'
    directory = Path.home() / location
    project = Path(root) / location
    workspace_names = {p.name for p in project.iterdir()
                       if p.is_dir() and (p / 'SKILL.md').is_file()} if project.is_dir() else set()
    linked, kept, skipped = [], [], []
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for source in sorted((KIT / 'skills').iterdir()):
            if not source.is_dir() or not (source / 'SKILL.md').is_file():
                continue
            if source.name in workspace_names:
                skipped.append(source.name)
                if (directory / source.name).exists() or (directory / source.name).is_symlink():
                    kept.append(source.name)
                continue
            try:
                (directory / source.name).symlink_to(source.resolve(), target_is_directory=True)
                linked.append(source.name)
            except FileExistsError:
                kept.append(source.name)
    except OSError as exc:
        raise WsError(f'Could not link skills into {directory}: {exc}. Existing names were kept.')
    return {'directory': str(directory), 'linked': linked, 'kept': kept, 'skipped': skipped}


def connect(root, client, write=False, skills=False, verify=False):
    if client == 'gemini':
        # Gemini keeps MCP servers and hooks in one settings file: merge both, touching only our entries.
        return dict(_connect_gemini(root), **({'mcp': mcp_doctor(root, ('gemini',))[0]} if verify else {}))
    result = _connect_config(root, client, write)
    if client in ('cursor', 'codex', 'vscode'):
        from .upgrade import hooks
        relative = {'cursor': '.cursor/hooks.json', 'codex': '.codex/hooks.json', 'vscode': '.github/hooks/ai-dev-workspace.json'}[client]
        path = inside(root / relative, [root]); candidate = json.dumps(memory_hooks(root, client), indent=2) + '\n'
        with lock(root):
            merged = hooks(path.read_text(encoding='utf-8'), candidate) if path.exists() else candidate
            collisions = []
            if merged is not None: atomic_write(path, merged)
            else: write_preserving(path, candidate.encode(), collisions)
        result['hooks'] = {'path': str(path), 'collisions': collisions}
    if skills and client in ('claude', 'codex'):
        result['skills'] = link_skills(client, root)
    if verify and client in ('claude', 'cursor', 'vscode', 'gemini'):
        result['mcp'] = mcp_doctor(root, (client,))[0]
    return result


def _connect_gemini(root):
    from .upgrade import managed_command
    path = inside(root / '.gemini/settings.json', [root])
    with lock(root):
        try:
            data = json.loads(read_text(path, [root])) if path.exists() else {}
            if not isinstance(data, dict): raise ValueError()
            if not isinstance(data.get('mcpServers', {}), dict) or not isinstance(data.get('hooks', {}), dict): raise ValueError()
            for groups in data.get('hooks', {}).values():
                if not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get('hooks', []), list) or any(not isinstance(h, dict) for h in g.get('hooks', [])) for g in groups): raise ValueError()
        except (OSError, ValueError):
            collisions = []
            write_preserving(path, (json.dumps(dict(mcpServers={'ai-dev-workspace': mcp_command(root)}, **memory_hooks(root, 'gemini')), indent=2) + '\n').encode(), collisions)
            return {'client': 'gemini', 'connected': False, 'path': str(path), 'note': 'Existing settings are invalid; review the proposal, then run ws doctor.'}
        servers = data.setdefault('mcpServers', {})
        servers['ai-dev-workspace'] = mcp_command(root)
        hooks = data.setdefault('hooks', {})
        for event, groups in memory_hooks(root, 'gemini')['hooks'].items():
            kept = [g for g in hooks.get(event, []) if not any(isinstance(h.get('command'), str) and managed_command(h['command']) for h in g.get('hooks', []))]
            hooks[event] = kept + groups
        atomic_write(path, json.dumps(data, indent=2) + '\n')
    return {'client': 'gemini', 'connected': True, 'path': str(path), 'hooks': {'path': str(path), 'collisions': []}}


def _connect_config(root, client, write=False):
    if client not in ('claude', 'codex', 'cursor', 'vscode', 'gemini'):
        raise WsError('Client must be claude, codex, cursor, vscode or gemini.')
    if write and client != 'codex':
        raise WsError('--write applies only to the Codex global configuration.')
    server = mcp_command(root)
    if client == 'codex':
        block = '[mcp_servers.ai-dev-workspace]\ncommand = ' + json.dumps(server['command']) + '\nargs = ' + json.dumps(server['args']) + '\n'
        result = {'client': client, 'connected': client_connected(root, client), 'config': block}
        if not write or result['connected']:
            return result
        path = Path.home() / '.codex/config.toml'
        original = path.read_text(encoding='utf-8') if path.exists() else ''
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
    locations = MCP_LOCATIONS
    relative, key = locations[client]
    path = inside(root / relative, [root])
    if client_connected(root, client):
        return {'client': client, 'connected': True, 'path': str(path)}
    data = {key: {}}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(existing, dict) and isinstance(existing.get(key), dict):
                data = existing
        except (OSError, ValueError):
            pass
    data[key]['ai-dev-workspace'] = server
    collision = path.exists()
    destination = path.with_name(path.name + '.ws-new') if collision else path
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open('x', encoding='utf-8', newline='') as stream:
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
        with (os.fdopen(fd, 'wb') if isinstance(text, bytes) else os.fdopen(fd, 'w', encoding='utf-8', newline='')) as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextlib.contextmanager
def lock(root):
    inside(root / '.ws', [root]); inside(root / '.ws/lock', [root])
    (root / '.ws').mkdir(exist_ok=True)
    with (root / '.ws' / 'lock').open('a+b') as stream:
        try:
            file_lock(stream)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK): raise
            raise WsError('Another workspace update is running; retry in a moment.')
        try: yield
        finally: file_lock(stream, release=True)


def file_lock(stream, release=False):
    if WINDOWS:
        import msvcrt
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK if release else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream, fcntl.LOCK_UN if release else fcntl.LOCK_EX | fcntl.LOCK_NB)


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


def conflicted(text):
    return bool(re.search(r'^<<<<<<< ', text, re.M) and re.search(r'^>>>>>>> ', text, re.M))


def keep_ours(text):
    """Resolve git conflict markers to the local (HEAD) side so a clashing task file can still be read."""
    return re.sub(r'^<<<<<<< [^\n]*\n(.*?)(?:^(?:=======|\|\|\|\|\|\|\| )[^\n]*\n.*?)?^>>>>>>> [^\n]*\n?', r'\1', text, flags=re.M | re.S)


def conflict_hint(task_id):
    return (f'{task_id} has unresolved git conflict markers: open vault/Tasks/{task_id}.md, keep one side, '
            'delete the <<<<<<< ======= >>>>>>> lines, then `git add` it (docs/TEAM.md).')


def digest_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


# --- tasks -----------------------------------------------------------------------

def task_path(root, task_id):
    if not ID_RE.fullmatch(task_id or ''):
        raise WsError('Task IDs use letters, digits, dot, dash or underscore (e.g. JIRA-123, fix-login).')
    return inside(vault(root) / 'Tasks' / f'{task_id}.md', [root])


def _local_claim_path(root, task_id):
    if not ID_RE.fullmatch(task_id or ''):
        raise WsError('Task IDs use letters, digits, dot, dash or underscore (e.g. JIRA-123, fix-login).')
    return inside(root / '.ws' / 'claims' / f'{task_id}.json', [root])


def _claim_defaults(root, task_id, worker, token):
    if worker is not None and token is not None:
        return worker, token
    try:
        path = _local_claim_path(root, task_id)
        local = json.loads(read_text(path, [root]))
        if not isinstance(local, dict): return worker, token
    except (OSError, ValueError, RecursionError):
        return worker, token
    return worker if worker is not None else local.get('worker'), token if token is not None else local.get('token')


def task_new(root, task_id, title, objective='', branch='', repo=''):
    title = redacted_line(title, 'Title')
    branch = redacted_line(branch, 'Branch')
    repo = redacted_line(repo, 'Repo')
    configured_repos = config(root).get('repos', [])
    if not repo and isinstance(configured_repos, list) and len(configured_repos) == 1:
        candidate = configured_repos[0]
        if isinstance(candidate, str):
            normalized = redacted_line(candidate, 'Repo')
            repo = normalized if normalized == candidate else ''
    path = task_path(root, task_id)
    if path.exists():
        raise WsError(f'Task {task_id} already exists: {path.relative_to(root)}')
    template = (vault(root) / 'Templates' / 'Task.md').read_text(encoding='utf-8')
    text = template.replace('{{id}}', task_id).replace('{{title}}', title).replace('{{date}}', now()[:10])
    text = set_meta(text, {'branch': branch, 'repo': repo})
    if objective:
        text = set_section(text, 'Objective', redact(objective))
    with lock(root):
        atomic_write(path, text)
    return {'task': task_id, 'path': path.relative_to(root).as_posix()}


def _local_claim_matches(root, task_id, meta):
    if not meta.get('claimed_by'):
        return False
    try:
        local = json.loads(_local_claim_path(root, task_id).read_text(encoding='utf-8'))
    except (OSError, ValueError, WsError):
        local = {}
    return bool(local.get('token')) and local.get('token') == meta.get('claim_token')


def claim_note(root, task_id, meta):
    """Tell readers whether a claim was made from this workspace (local claim file matches)."""
    if _local_claim_matches(root, task_id, meta):
        return 'claimed in this workspace: continue; ws claim resumes it'
    if not meta.get('claimed_by'):
        return ''
    return f"claimed elsewhere by {meta['claimed_by']}: ask before taking over"


def task_list(root):
    out = []
    directory = inside(vault(root) / 'Tasks', [root])
    for path in sorted(directory.glob('*.md')):
        try: text = read_text(path, [root])
        except WsError: continue
        bad = conflicted(text)
        if bad: text = keep_ours(text)
        meta = parse_meta(text)
        title = re.search(r'^# (.+)$', text, re.M)
        out.append({'id': meta.get('id', path.stem), 'title': title.group(1) if title else path.stem,
                    'status': 'conflicted' if bad else meta.get('status', 'unknown'),
                    'claimed_by': '' if bad else meta.get('claimed_by', ''),
                    'claim': '' if bad else claim_note(root, meta.get('id', path.stem), meta),
                    'branch': meta.get('branch', ''), 'next': section(text, 'Next action')[:200],
                    'depends_on': _deps(meta)})
    return out


def _deps(meta):
    return [d.strip() for d in meta.get('depends_on', '').split(',') if d.strip()]


def _cycle_through(graph, start):
    """True when following depends_on edges from start comes back to start."""
    seen, stack = set(), list(graph.get(start, ()))
    while stack:
        node = stack.pop()
        if node == start: return True
        if node not in seen:
            seen.add(node); stack.extend(graph.get(node, ()))
    return False


def task_depend(root, task_id, other):
    for ref in (task_id, other):
        if not task_path(root, ref).is_file():
            raise WsError(f'No task {ref}. Create it with `ws task new {ref} "<title>"`.')
    if task_id == other:
        raise WsError(f'{task_id} cannot depend on itself.')
    with lock(root):
        graph = {t['id']: t['depends_on'] for t in task_list(root)}
        deps = graph.get(task_id, [])
        if other not in deps:
            if _cycle_through({**graph, task_id: deps + [other]}, task_id):
                raise WsError(f'{task_id} -> {other} would create a dependency cycle.')
            deps = deps + [other]
            path = task_path(root, task_id)
            atomic_write(path, set_meta(path.read_text(encoding='utf-8'), {'depends_on': ', '.join(deps)}))
    return {'task': task_id, 'depends_on': deps}


def task_next(root):
    """Open tasks whose dependencies are all done: in_progress first, then review, ready, backlog."""
    tasks = {t['id']: t for t in task_list(root)}
    rank = {'in_progress': 0, 'review': 1, 'ready': 2, 'backlog': 3}
    ready, waiting = [], 0
    for t in tasks.values():
        if t['status'] not in rank: continue  # done, blocked or unknown
        if any(tasks.get(d, {}).get('status') != 'done' for d in t['depends_on']):
            waiting += 1; continue
        unblocks = sorted(o['id'] for o in tasks.values() if t['id'] in o['depends_on'] and o['status'] != 'done')
        ready.append({'id': t['id'], 'status': t['status'], 'title': t['title'], 'unblocks': unblocks})
    ready.sort(key=lambda r: (rank[r['status']], r['id']))
    return {'ready': ready, 'waiting': waiting}


# Task Master statuses -> ws statuses (anything unlisted, e.g. pending, becomes ready).
_IMPORT_STATUS = {'done': 'done', 'in-progress': 'in_progress', 'review': 'review', 'blocked': 'blocked',
                  'deferred': 'backlog', 'cancelled': 'backlog'}
_CHECK_RE = re.compile(r'^\s*[-*] \[([ xX])\] (T\d+)\b\s*(.*)$')


def _parse_import(path):
    """Return (items, ignored): items are {key, title, objective, status, deps} with file-local keys."""
    text = read_text(path)
    items, ignored = [], 0
    if Path(path).suffix.lower() == '.json':
        try: data = json.loads(text)
        except ValueError as exc: raise WsError(f'{path} is not valid JSON: {exc}')
        if isinstance(data, dict) and isinstance(data.get('master'), dict): data = data['master']
        if isinstance(data, dict): data = data.get('tasks')
        if not isinstance(data, list):
            raise WsError('Expected a Task Master tasks.json: a "tasks" list or {"master": {"tasks": [...]}}.')
        for raw in data:
            if not isinstance(raw, dict) or raw.get('id') in (None, '') or not raw.get('title'):
                raise WsError('Every task needs an id and a title.')
            ignored += len(raw.get('subtasks') or [])
            items.append({'key': str(raw['id']), 'title': ' '.join(str(raw['title']).split()),
                          'objective': str(raw.get('description') or ''),
                          'status': _IMPORT_STATUS.get(str(raw.get('status', '')).lower(), 'ready'),
                          'deps': [str(d) for d in raw.get('dependencies') or []]})
    else:
        for line in text.splitlines():
            m = _CHECK_RE.match(line)
            if not m:
                ignored += bool(re.match(r'^\s*[-*] \[[ xX]\]', line)); continue
            mark, key, rest = m.groups()
            deps = []
            for found in re.findall(r'\(depends on ([^)]*)\)', rest, re.I):
                deps += re.findall(r'T\d+', found)
            rest = re.sub(r'\(depends on [^)]*\)', '', rest, flags=re.I)
            rest = re.sub(r'\[(?:P|US\d+)\]', '', rest)
            items.append({'key': key, 'title': ' '.join(rest.split()) or key, 'objective': '',
                          'status': 'done' if mark in 'xX' else 'ready', 'deps': deps})
    if not items:
        raise WsError(f'No tasks found in {path}.')
    return items, ignored


def task_import(root, file, prefix='SPEC', write=False):
    """Create ws tasks from a Task Master tasks.json or a Spec Kit style tasks.md; never overwrites."""
    items, ignored = _parse_import(file)
    ids = {i['key']: f"{prefix}-{i['key']}" for i in items}
    errors = [f'duplicate task {k} in file' for k in {i['key'] for i in items if [j['key'] for j in items].count(i['key']) > 1}]
    for ref in ids.values():
        task_path(root, ref)  # validates the prefixed ID against ID_RE
    graph = {}
    existing = {t['id'] for t in task_list(root)}
    for i in items:
        deps = []
        for d in i['deps']:
            ref = ids.get(d) or (f'{prefix}-{d}' if f'{prefix}-{d}' in existing else d if d in existing else '')
            if not ref: errors.append(f"{ids[i['key']]} depends on unknown task {d}")
            else: deps.append(ref)
        i['depends_on'] = deps; graph[ids[i['key']]] = deps
    errors += [f'dependency cycle through {n}' for n in graph if _cycle_through(graph, n)]
    skipped = [ids[i['key']] for i in items if ids[i['key']] in existing]
    new = [i for i in items if ids[i['key']] not in existing]
    result = {'file': str(file), 'preview': not write, 'create': [ids[i['key']] for i in new],
              'skipped_existing': skipped, 'ignored_lines_or_subtasks': ignored, 'errors': errors}
    if write:
        if errors: raise WsError('Nothing imported: ' + '; '.join(errors))
        for i in new:
            ref = ids[i['key']]
            task_new(root, ref, i['title'], i['objective'])
            with lock(root):
                path = task_path(root, ref)
                meta = {'status': i['status']}
                if i['depends_on']: meta['depends_on'] = ', '.join(i['depends_on'])
                atomic_write(path, set_meta(path.read_text(encoding='utf-8'), meta))
    return result


def task_find(root, ref):
    ref = ref.lower()
    return [t for t in task_list(root) if ref in t['id'].lower() or ref == t['branch'].lower() or ref in t['title'].lower()]


def task_read(root, task_id, sections=None):
    path = task_path(root, task_id)
    if not path.is_file():
        raise WsError(f'No task {task_id}. Create it with `ws task new {task_id} "<title>"`.')
    text = path.read_text(encoding='utf-8')
    bad = {'conflicted': True} if conflicted(text) else {}
    if not sections:
        return {'task': task_id, 'sha': digest_text(text), 'text': text, **bad}
    sha, text = digest_text(text), keep_ours(text) if bad else text
    meta = parse_meta(text)
    return {'task': task_id, 'sha': sha, 'meta': meta, 'claim': '' if bad else claim_note(root, task_id, meta),
            'sections': {s: section(text, s) for s in sections}, **bad}


def claim(root, task_id, worker):
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', worker):
        raise WsError('Worker is a short label such as claude-main or codex-1.')
    with lock(root):
        path = task_path(root, task_id)
        text = path.read_text(encoding='utf-8')
        if conflicted(text): raise WsError(conflict_hint(task_id))
        meta = parse_meta(text)
        if meta.get('claimed_by'):
            # The local claim file (gitignored) proves this workspace made the claim: a later session here resumes it.
            try:
                local = json.loads(_local_claim_path(root, task_id).read_text(encoding='utf-8'))
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
        local = {'worker': worker, 'token': token}
        head = _task_git(root, task_id, 'rev-parse', 'HEAD').strip()
        if re.fullmatch(r'[0-9a-f]{40,64}', head):
            local.update(git_head=head, repo=meta.get('repo', ''))
        atomic_write(_local_claim_path(root, task_id), json.dumps(local) + '\n')
    return {'task': task_id, 'worker': worker, 'token': token}


def release(root, task_id, worker=None, token=None):
    with lock(root):
        worker, token = _claim_defaults(root, task_id, worker, token)
        path = task_path(root, task_id)
        text = path.read_text(encoding='utf-8')
        if conflicted(text): raise WsError(conflict_hint(task_id))
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
        text = path.read_text(encoding='utf-8')
        if conflicted(text): raise WsError(conflict_hint(task_id))
        meta = parse_meta(text)
        if meta.get('claimed_by') and (worker != meta['claimed_by'] or token != meta.get('claim_token')):
            raise WsError(f'{task_id} is claimed by {meta["claimed_by"]}; pass its worker and token.')
        if expected_sha and expected_sha != digest_text(text):
            raise WsError('Task changed since you read it; read it again before checkpointing.')
        values = {'status': status, 'updated': now(), 'checkpoint_at': now(), 'checkpoint_count': int(meta.get('checkpoint_count', 0)) + 1}
        head = _task_git(root, task_id, 'rev-parse', 'HEAD').strip()
        if re.fullmatch(r'[0-9a-f]{40,64}', head): values['checkpoint_commit'] = head  # lets brief spot stale memory
        text = set_meta(text, values)
        text = set_section(text, 'Next action', redact(next_action))
        for name, body in (notes or {}).items():
            if name not in REQUIRED and name not in ('Findings', 'Failures', 'Risks', 'Do not redo'):
                raise WsError(f'Unknown section {name}.')
            text = set_section(text, name, redact(body))
        atomic_write(path, text)
        refresh_native(root, locked=True)
    return {'task': task_id, 'status': status, 'sha': digest_text(text)}


# Instruction files that clients read at session start (CLAUDE.md is skipped: its SessionStart hook already injects the brief).
# Only clients without a session-start brief hook: Claude and Codex read AGENTS.md and already get the brief.
NATIVE_FILES = ('.github/copilot-instructions.md', '.cursor/rules/ws-current-task.mdc')
CURSOR_RULE_HEAD = '---\ndescription: Current ai-dev-workspace task memory (managed; do not edit)\nalwaysApply: true\n---\n'


def refresh_native(root, locked=False):
    """Keep the `current-task` managed block in existing client instruction files equal to the brief.
    Returns the changed paths; never raises, so a checkpoint is not undone by an unwritable file."""
    from .upgrade import block, markdown
    changed = []
    try:
        if config(root).get('native_writeback', True) is False: return changed
        with (contextlib.nullcontext() if locked else lock(root)):
            text = brief(root)
            body = 'No task in progress.' if text.startswith('No in-progress task') else text
            new = block(body, 'current-task')
            for relative in NATIVE_FILES:
                path = root / relative
                cursor = relative.startswith('.cursor/')
                if cursor and not (root / '.cursor').is_dir(): continue
                try:
                    inside(path, [root])
                    old = path.read_text(encoding='utf-8') if path.is_file() else CURSOR_RULE_HEAD if cursor and not path.exists() else None
                    if old is None: continue
                    if '<!--ws:managed:current-task:' in old:
                        updated = markdown(old, new)  # None for duplicate/malformed blocks: leave for the user
                    else:
                        updated = old + ('' if old.endswith('\n') or not old else '\n') + ('\n' if old else '') + new
                    if updated is not None and updated != old:
                        atomic_write(path, updated); changed.append(relative)
                except (WsError, OSError, UnicodeError):
                    continue
    except (WsError, OSError, ValueError):
        pass
    return changed


# --- knowledge -------------------------------------------------------------------

def search(root, query, limit=20):
    """Rank vault notes by query-word hits; return path:line snippets, not whole files."""
    words = [w.lower() for w in re.findall(r'\w{3,}', query)]
    if not words:
        raise WsError('Search needs at least one word of 3+ letters.')
    hits, paths = [], []
    for path in vault(root).rglob('*.md'):
        if '.ws' not in path.parts and 'Runs' not in path.parts:
            paths.append((path, path.relative_to(root).as_posix()))
    for repo in config(root).get('repos', []):
        report = _graphify_report(Path(repo).expanduser())
        if report:
            paths.append((report, str(report)))
    for path, shown in paths:
        score, best = 0, []
        try: contents = read_text(path, read_roots(root))
        except WsError: continue
        with io.StringIO(contents) as source:
            for i, line in enumerate(source, 1):
                low = line.lower()
                n = sum(low.count(w) for w in words)
                if n:
                    score += n + (3 if line.startswith('#') else 0)
                    best.append((n, i, redact(line.strip())[:160]))
        if score:
            best.sort(reverse=True)
            hits.append({'path': shown, 'score': score,
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
        return '~/' + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)


def _search_session_records(stream, tool):
    if tool in ('cursor', 'gemini'):
        from .transcripts import records
        for record in records(stream, tool):
            if record.get('type') not in ('user', 'assistant') or record.get('channel') == 'analysis': continue
            message = record.get('message', {})
            if not isinstance(message, dict): continue
            content = message.get('content', '')
            if isinstance(content, list):
                content = [p for p in content if isinstance(p, str) or isinstance(p, dict) and p.get('type') == 'text']
            yield _session_text(content), record.get('timestamp')
    else:
        for line in stream:
            try: record = json.loads(line)
            except ValueError: continue
            if not isinstance(record, dict): continue
            payload, message = record.get('payload', {}), record.get('message', {})
            text = _session_text(message.get('content', '')) if isinstance(message, dict) else ''
            if not text and isinstance(payload, dict):
                text = _session_text(payload.get('content', payload.get('message', payload.get('text', ''))))
            yield text, record.get('timestamp') or (payload.get('timestamp') if isinstance(payload, dict) else '')


def session_search(query, roots=None):
    """Search bounded local transcripts; return redacted conversation snippets."""
    query = ' '.join(query.split())
    if not query: raise WsError('Session search needs words to find.')
    roots = roots if roots is not None else {'claude': Path.home() / '.claude/projects', 'codex': Path.home() / '.codex/sessions',
                                           'cursor': Path.home() / '.cursor/projects', 'gemini': Path.home() / '.gemini/tmp'}
    hits = []
    for tool, root in roots.items():
        root = Path(root)
        if not root.is_dir() or root.is_symlink(): continue
        extensions = ('.jsonl', '.json') if tool == 'gemini' else ('.jsonl', '.txt') if tool == 'cursor' else ('.jsonl',)
        for path in root.rglob('*'):
            if path.suffix not in extensions or path.is_symlink(): continue
            try:
                if not path.is_file() or path.stat().st_size > 50 * 1024 * 1024: continue
                fallback = datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc).isoformat()
                with path.open(encoding='utf-8', errors='replace') as stream:
                    for text, timestamp in _search_session_records(stream, tool):
                        if query.lower() not in text.lower(): continue
                        timestamp = timestamp or fallback
                        compact = ' '.join(redact(text).split())
                        at = compact.lower().find(query.lower())
                        snippet = compact[max(0, at - 80):at + len(query) + 160]
                        hits.append({'date': str(timestamp)[:10], 'tool': tool, 'session_file': _session_file(path),
                                     'snippet': snippet, '_sort': str(timestamp)})
            except (OSError, ValueError, TypeError, AttributeError, KeyError, IndexError):
                continue  # A broken transcript must not hide other sessions.
    hits.sort(key=lambda hit: hit['_sort'], reverse=True)
    for hit in hits: del hit['_sort']
    return hits[:20]


def _append_line(root, rel, line):
    path = inside(root / rel, [root])
    with lock(root):
        text = path.read_text(encoding='utf-8') if path.exists() else ''
        atomic_write(path, text.rstrip('\n') + '\n' + line + '\n')


def lesson_add(root, text, tags=(), paths=(), area=''):
    text = ' '.join(redact(text).split())
    if len(text) < 10:
        raise WsError('Write the lesson as: what happened → rule.')
    tag = ' '.join(f'#{redacted_line(t, "Tag")}' for t in tags)
    if not isinstance(paths, (list, tuple)): raise WsError('Paths must be relative globs.')
    patterns = [redacted_line(p, 'Path').replace('\\', '/') for p in paths]
    if any(not p or p.startswith('/') or re.match(r'^[A-Za-z]:', p) or '..' in p.split('/') for p in patterns):
        raise WsError('Lesson paths must be relative repo globs without traversal.')
    metadata = {'paths': patterns, 'area': redacted_line(area, 'Area')}
    suffix = ' <!-- ws:lesson ' + json.dumps(metadata).replace('<', '\\u003c').replace('>', '\\u003e') + ' -->' if patterns or area else ''
    _append_line(root, Path(config(root).get('vault', 'vault')) / 'Learnings.md', f'- {now()[:10]} {text} {tag}'.rstrip() + suffix)
    return {'added': True}


def lesson_search(root, query):
    path = vault(root) / 'Learnings.md'
    words = [w.lower() for w in re.findall(r'\w{3,}', query)]
    lines = [l for l in path.read_text(encoding='utf-8').splitlines() if l.startswith('- ')] if path.exists() else []
    return [l for l in lines if any(w in l.lower() for w in words)] if words else lines


def _task_git(root, task_id, *args):
    """Read local git state only for the task's declared repository."""
    try:
        repo = task_read(root, task_id, ['Objective'])['meta'].get('repo')
        if not repo: return ''
        path = inside(root / repo, read_roots(root))
        result = subprocess.run(['git', '-C', str(path), *args], capture_output=True, encoding='utf-8', errors='replace', timeout=2)
        return result.stdout if result.returncode == 0 else ''
    except (WsError, OSError, ValueError, subprocess.SubprocessError):
        return ''


def relevant_lessons(root, task):
    title = set(re.findall(r'\w{3,}', task['title'].lower()))
    changed = []
    try:
        local = json.loads(read_text(_local_claim_path(root, task['id']), [root]))
        meta = task_read(root, task['id'], ['Objective'])['meta']
        head = local.get('git_head', '')
        if local.get('token') == meta.get('claim_token') and local.get('repo') == meta.get('repo') and re.fullmatch(r'[0-9a-f]{40,64}', head):
            changed = _task_git(root, task['id'], 'diff', '--no-ext-diff', '--no-textconv', '--name-only', '-z', head, '--').split('\0')
    except (WsError, OSError, ValueError, TypeError, AttributeError):
        pass
    saved = lesson_search(root, '')
    tracked = _task_git(root, task['id'], 'ls-files', '-z').split('\0') if saved else []
    ranked = []
    for line in saved:
        match = re.search(r'\s*<!-- ws:lesson (.*?) -->$', line)
        metadata = {}
        if match:
            try: metadata = json.loads(match[1])
            except ValueError: pass
            line = line[:match.start()]
        if not isinstance(metadata, dict): metadata = {}
        paths = metadata.get('paths', [])
        if not isinstance(paths, list): paths = []
        overlap = sum(any(isinstance(p, str) and fnmatch.fnmatchcase(f, p) for p in paths) for f in changed)
        score = len(title & set(re.findall(r'\w{3,}', (line + ' ' + str(metadata.get('area', ''))).lower())))
        gone = tracked != [''] and paths and not any(isinstance(p, str) and fnmatch.fnmatchcase(f, p) for f in tracked for p in paths)
        if overlap or score: ranked.append((overlap, score, ('(paths gone) ' if gone else '') + line))
    ranked.sort(key=lambda item: (-item[0], -item[1]))
    return [line for _, _, line in ranked]


def _memory_check(root, task_id, meta, next_action):
    """One line when the repo moved on from (or behind) the commit the checkpoint was written at; '' if unknown."""
    saved = meta.get('checkpoint_commit', '')
    head = _task_git(root, task_id, 'rev-parse', 'HEAD').strip()
    if not re.fullmatch(r'[0-9a-f]{40,64}', saved) or not head or head == saved: return ''
    if _task_git(root, task_id, 'rev-list', '-n1', saved, '^' + head).strip():  # saved is not an ancestor of HEAD
        return f'Memory check: code is behind the saved checkpoint ({saved[:7]}); the work it describes may be undone.'
    names = _task_git(root, task_id, 'diff', '--no-ext-diff', '--no-textconv', '--name-only', '-z', saved, '--').split('\0')
    hit = list(dict.fromkeys(os.path.basename(n) for n in names if n and os.path.basename(n) in next_action))[:5]
    return f'Memory check: written at {saved[:7]}; changed since: {", ".join(hit)} (verify before acting).' if hit else ''


def _capture_words(text, limit):
    words = redact(text).split()
    if len(words) > limit:
        if limit < 3: return ' '.join(words[-limit:]) if limit else ''
        head = min(8, limit // 3)
        words = words[:head] + ['[…]'] + words[-(limit - head - 1):]
    return ' '.join(words)


def _constraint_clauses(text):
    return re.split(r'(?<=[.!?])\s+|\n+', text)


def _constraint_budget(clauses, limit, multiline=False):
    parts = []
    for clause in clauses:
        if limit <= int(multiline): break
        if not clause.strip(): continue
        clipped = _capture_words(clause, limit - int(multiline))
        if multiline: clipped = '- ' + clipped
        parts.append(clipped)
        limit -= len(clipped.split())
    return ('\n' if multiline else '; ').join(parts)


def _captured_step(summary):
    latest = ''
    for match in re.finditer(r'\bnext (?:step|action)\s*[*_`]*(?::|\bis\b|\bwill be\b|,)\s*[*_`]*\s*(?:-\s+)?', summary, re.I):
        if re.search(r'\b(?:no|not(?:\s+(?:have|take|perform|run|execute))?|without)\s+(?:a\s+|the\s+)?$', summary[:match.start()], re.I): continue
        prefix = ' '.join(match.group().split()).rstrip(' -')
        latest = prefix + ' ' + re.split(r'(?<=[.!?])\s+|\n+', summary[match.end():])[0]
    return latest


def _bounded_brief(lines):
    bounded, remaining = [], 198  # reserve one word for a final truncation notice
    for line in lines:
        tokens = line.split()
        if len(tokens) > remaining:
            if line.startswith('Explicit Handoff') and remaining > 7:
                tokens = 'Explicit Handoff (saved task record):'.split() + tokens[-(remaining - 6):]
            bounded.append(' '.join(tokens[:max(0, remaining - 1)]) + ' [truncated]')
            break
        bounded.append(line); remaining -= len(tokens)
    return '\n'.join(bounded)


def brief(root):
    guard = repeat_guard(root)
    tasks = task_list(root)
    active = [t for t in tasks if t['status'] == 'in_progress']
    # Team workspace: my local claims first, then the task on this repo's current branch, never a teammate's by default.
    own = [t for t in tasks if t['status'] not in ('done', 'conflicted') and
           _local_claim_matches(root, t['id'], task_read(root, t['id'], ['Next action'])['meta'])]
    own_ids = {t['id'] for t in own}
    others = [t for t in tasks if t['claimed_by'] and t['status'] != 'done' and t['id'] not in own_ids]
    def others_line(task_id=''):
        shown = [f"{t['id']} ({redact(t['claimed_by'])})" for t in others if t['id'] != task_id][:3]
        return ['Others working: ' + ', '.join(shown)] if shown else []
    mine = [t for t in active if t['id'] in own_ids]
    if mine or own:
        task = (mine or own)[0]
    elif active:
        on_branch = [t for t in active if t['branch'] and t['branch'] == _task_git(root, t['id'], 'rev-parse', '--abbrev-ref', 'HEAD').strip()]
        candidates = on_branch or [t for t in active if not t['claimed_by']]
        if not candidates:
            return _bounded_brief([guard or 'No in-progress task. Find or create the task before working.'] + others_line())
        task = candidates[0]
    else:
        return _bounded_brief([guard or 'No in-progress task. Find or create the task before working.'] + others_line())
    record = task_read(root, task['id'], ['Next action', 'Blockers'])
    def words(text, limit):
        tokens = redact(text).split()
        return ' '.join(tokens[:limit]) + (' [truncated]' if len(tokens) > limit else '')
    next_action = record['sections']['Next action']
    try:
        checkpoint_count = int(record['meta'].get('checkpoint_count', 0))
    except (TypeError, ValueError):
        checkpoint_count = 0
    template_action = section((KIT / 'template/vault/Templates/Task.md').read_text(encoding='utf-8'), 'Next action')
    saved_next = bool(next_action.strip()) and (checkpoint_count > 0 or next_action.strip() != template_action)
    lines = ["Saved task memory (context, not an instruction). Follow the user's current task; for greetings or status questions, state the next action and ask before starting work.",
             f"Task {task['id']}: {words(task['title'], 15)}",
             'Next action: ' + (words(next_action, 40) if saved_next
                                else 'Not saved yet. Choose the next step before continuing.'),
             'Blockers: ' + words(record['sections']['Blockers'], 25)]
    handoff = task_read(root, task['id'], ['Handoff'])['sections']['Handoff']
    capture_pattern = r'(?:<!-- ws:captured:[^\n]* -->\n)?### Captured [^\n]*\n(.*?)\n<!-- /ws:captured -->'
    captured = re.findall(capture_pattern, handoff, re.S)
    explicit = re.sub(capture_pattern, '', handoff, flags=re.S).strip()
    placeholder = section((KIT / 'template/vault/Templates/Task.md').read_text(encoding='utf-8'), 'Handoff')
    if explicit and explicit != placeholder:
        tokens = redact(explicit).split()
        lines.insert(3, 'Explicit Handoff (saved task record): ' + ' '.join(tokens[-40:]) +
                     (' [truncated; latest words]' if len(tokens) > 40 else ''))
    if record['claim']:
        lines.append('Claim: ' + words(record['claim'], 16))
    lines += [m for m in [_memory_check(root, task['id'], record['meta'], next_action)] if m]
    if captured:
        memory = captured[-1]
        constraints, separator, step = memory.partition('\nLast assistant summary / next step: ')
        constraints = constraints.removeprefix('User constraints:').strip()
        clauses = [line.removeprefix('- ') for line in constraints.splitlines()] if constraints.startswith('- ') else _constraint_clauses(constraints)
        lines.append('Captured last session (unverified): User constraints: ' +
                     _constraint_budget(clauses, 70) + (' [truncated]' if len(constraints.split()) > 70 else ''))
        if separator:
            lines.append('Captured next step (unverified): ' + _capture_words(step, 25) +
                         (' [truncated]' if len(step.split()) > 25 else ''))
            action = re.search(r'\bnext (?:step|action)\s*[*_`]*(?::|\bis\b|\bwill be\b|,)\s*[*_`]*(.+)', _captured_step(step), re.I)
            def normalized(value):
                return re.sub(r'^to\s+', '', ' '.join(value.strip(' \t\n*_`.:').split()).casefold())
            if action and normalized(action[1]) != normalized(record['sections']['Next action']):
                lines.append('Captured plan differs from saved checkpoint; verify before replacing.')
    lines += others_line(task['id'])
    lessons = relevant_lessons(root, task)
    lines += ['Lesson: ' + words(line, 25) for line in lessons[:3]]
    if len(lessons) > 3: lines.append(f'Lessons: {len(lessons) - 3} more (ws lesson search)')
    return _bounded_brief(([words(guard, 20)] if guard else []) + lines)


def capture_decisions(root, transcript_path, client='claude'):
    """Capture bounded, unverified transcript memory to a locally owned task."""
    with lock(root):
        reason = _capture_decisions(root, transcript_path, client)
        outcome = reason if reason in ('captured', 'unchanged') else 'skipped'
        health = {'date': now(), 'client': client if client in ('claude', 'codex', 'cursor', 'gemini', 'vscode') else 'unsupported',
                  'outcome': outcome, 'reason': reason}
        try:
            atomic_write(inside(root / '.ws/capture-health.json', [root]), json.dumps(health) + '\n')
        except (WsError, OSError):
            pass  # Diagnostics cannot undo capture.
    return reason == 'captured'


def _capture_decisions(root, transcript_path, client):
    if not isinstance(transcript_path, str) or not transcript_path:
        return 'missing_transcript_path'
    try:
        if config(root).get('capture') is False:
            return 'disabled_by_config'
    except (OSError, ValueError, AttributeError):
        pass  # Unreadable config keeps the default: capture on.
    decisions, summary, worked, recognized = [], '', False, False
    try:
        path = Path(transcript_path)
        if path.stat().st_size > 50 * 1024 * 1024:
            return 'transcript_too_large'
        # ponytail: scan at most 50 MB per hook; add incremental reads if sessions outgrow this.
        with io.StringIO(read_text(path, errors='strict')) as stream:
            from .transcripts import records
            for line in stream if client == 'claude' else records(stream, client):
                try:
                    entry = json.loads(line) if client == 'claude' else line
                    kind, message = entry.get('type'), entry.get('message', {})
                    content = message.get('content')
                except (ValueError, AttributeError):
                    continue
                if kind not in ('user', 'assistant') or entry.get('isMeta') or entry.get('isCompactSummary'):
                    continue
                recognized = True
                text = content if isinstance(content, str) else ''
                if isinstance(content, list):
                    text = _session_text([item for item in content if isinstance(item, dict) and item.get('type') == 'text'])
                # Private markers: `#private` / leading `/private` drops the message, <private> blocks are cut.
                if re.search(r'#private\b', text, re.I) or text.lstrip().lower().startswith('/private'):
                    continue
                text = localize_paths(redact(PRIVATE_RE.sub(' ', text)), root)
                if kind == 'assistant':
                    worked |= isinstance(content, list) and any(isinstance(item, dict) and item.get('type') == 'tool_use' for item in content)
                    if text.strip():
                        summary = text
                else:
                    # Session mechanics ("in this session only investigate") are not product decisions;
                    # numbered decisions in one sentence become separate items so none is clipped away.
                    decisions.extend(item for sentence in _constraint_clauses(text)
                                     if re.search(r'\b(must|do not|decided|only|always|never)\b', sentence, re.I)
                                     and not re.search(r'\bsession\b', sentence, re.I)
                                     for item in re.split(r';?\s+(?=\(\d+\)\s)', sentence))
    except WsError:
        return 'unreadable_transcript'
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError, KeyError, RecursionError):
        return 'unreadable_transcript'
    if not recognized:
        return 'unsupported_transcript'
    if not worked or not (decisions or summary):
        return 'no_work_or_memory'
    # Newest corrections get the budget first; captured memory never replaces verified sections.
    body = 'User constraints:\n' + _constraint_budget(reversed(decisions), 95, multiline=True)
    body += '\nLast assistant summary / next step: ' + _capture_words(_captured_step(summary) or summary, 35)
    body = body.replace('<!--', '&lt;!--')
    # Keyed by session: the Stop hook fires every turn, so a session updates its own block instead of adding more.
    marker = '<!-- ws:captured:' + digest_text(str(Path(transcript_path).resolve()))[:16] + ' -->'
    block = marker + '\n### Captured ' + now()[:10] + ' (unverified transcript)\n' + body + '\n<!-- /ws:captured -->\n'
    owned = []
    for task in task_list(root):
        worker, token = _claim_defaults(root, task['id'], None, None)
        path = task_path(root, task['id'])
        text = path.read_bytes().decode('utf-8')
        meta = parse_meta(text)
        if task['status'] != 'done' and token and worker == meta.get('claimed_by') and token == meta.get('claim_token'):
            owned.append((path, text))
    if len(owned) != 1:
        return 'ambiguous_claims' if owned else 'no_local_claim'
    path, original = owned[0]
    text = original
    match = re.search(r'^## Handoff[ \t]*\n.*?(?=^## |\Z)', text, re.M | re.S)
    if not match:
        return 'missing_handoff'
    section_text = match.group()
    own = re.search(re.escape(marker) + r'.*?<!-- /ws:captured -->\n?', section_text, re.S)
    if own:
        section_text = section_text[:own.start()] + block + section_text[own.end():]
    else:
        section_text = section_text.rstrip('\n') + '\n\n' + block
    text = text[:match.start()] + section_text + text[match.end():]
    if text == original:
        return 'unchanged'
    atomic_write(path, text)
    return 'captured'


def capture_health(root):
    path = root / '.ws/capture-health.json'
    try:
        if not path.exists():
            return {'outcome': 'not_run', 'reason': 'not_run'}
        health = json.loads(read_text(path, [root]))
        # Only our fixed diagnostic vocabulary can reach doctor; never echo arbitrary file text.
        if health['outcome'] not in ('captured', 'unchanged', 'skipped'): raise ValueError
        if health['reason'] not in ('captured', 'unchanged', 'missing_transcript_path', 'transcript_too_large',
                                   'unreadable_transcript', 'unsupported_transcript', 'no_work_or_memory',
                                   'ambiguous_claims', 'no_local_claim', 'missing_handoff', 'disabled_by_config'): raise ValueError
        if health['client'] not in ('claude', 'codex', 'cursor', 'gemini', 'vscode', 'unsupported'): raise ValueError
        if not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00', health['date']): raise ValueError
        return {key: health[key] for key in ('date', 'client', 'outcome', 'reason')}
    except (WsError, OSError, ValueError, TypeError, KeyError):
        return {'outcome': 'unknown', 'reason': 'unreadable_health'}


def sole_local_claim(root):
    """The one unfinished task claimed from this workspace, or '' when none or several."""
    tasks = [t['id'] for t in task_list(root) if t['status'] != 'done'
             and _local_claim_matches(root, t['id'], task_read(root, t['id'], ['Next action'])['meta'])]
    return tasks[0] if len(tasks) == 1 else ''


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
    lines = [l for l in path.read_text(encoding='utf-8').splitlines() if l.startswith('- [')] if path.exists() else []
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


def _focus_pattern(source):
    """Compile a deliberately small regex subset with predictable matching cost."""
    if len(source) > 256:
        raise WsError('Focus regular expressions are limited to 256 characters.')
    try:
        parsed = sre_parse.parse(source)
    except re.error as exc:
        raise WsError(f'Invalid focus regular expression: {exc}')
    repeats = [0]
    simple = {sre_parse.LITERAL, sre_parse.NOT_LITERAL, sre_parse.ANY,
              sre_parse.IN, sre_parse.CATEGORY}
    repeat_ops = {sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT}
    if hasattr(sre_parse, 'POSSESSIVE_REPEAT'):
        repeat_ops.add(sre_parse.POSSESSIVE_REPEAT)

    def check(tokens):
        for op, arg in tokens:
            if op in repeat_ops:
                _, maximum, child = arg
                repeats[0] += 1
                if repeats[0] > 1 or maximum == sre_parse.MAXREPEAT or maximum > 64 or any(inner not in simple for inner, _ in child):
                    raise WsError('Focus supports simple regular expressions only (one bounded repetition, up to 64 characters).')
            elif op == sre_parse.SUBPATTERN:
                check(arg[-1])
            elif op not in simple and op != sre_parse.AT:
                raise WsError('Focus supports simple regular expressions only.')
    check(parsed)
    return re.compile(source)


def digest_file(path, max_lines=60, root=None, focus=None):
    """Deterministic summary of a big file: JSON shape, or deduplicated error lines of a log."""
    path = Path(path)
    raw = read_text(path, read_roots(root) if root is not None else None)
    out = {'file': redact(str(path)), 'bytes': len(raw), 'lines': raw.count('\n') + 1}
    if focus is not None:
        pattern = _focus_pattern(focus)
        matches = []
        for i, line in enumerate(io.StringIO(raw), 1):
            match = pattern.search(line[:4096])
            if match:
                if len(matches) >= max_lines: break
                safe_line = redact(line)
                safe_match = pattern.search(safe_line[:4096])
                if safe_match:
                    start = max(0, safe_match.start() - 80)
                    end = min(len(safe_line), max(safe_match.end() + 80, start + 200))
                else:
                    start, end = 0, min(len(safe_line), 200)
                snippet = ('…' if start else '') + safe_line[start:end].strip() + ('…' if end < len(safe_line) else '')
                matches.append(f'L{i}: {snippet}')
        out['focus_matches'] = matches
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


def clipboard_text():
    commands = [('pbpaste', []), ('wl-paste', ['--no-newline']), ('xclip', ['-selection', 'clipboard', '-o']),
                ('powershell.exe', ['-NoProfile', '-Command', '$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; Get-Clipboard -Raw'])]
    for executable, args in commands:
        if shutil.which(executable):
            try:
                process = subprocess.Popen([executable, *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                chunks, total, oversized = [], [0], [False]
                def collect():
                    while total[0] <= MAX_READ_BYTES:
                        chunk = process.stdout.read(min(65536, MAX_READ_BYTES + 1 - total[0]))
                        if not chunk: break
                        total[0] += len(chunk); chunks.append(chunk)
                    if total[0] > MAX_READ_BYTES:
                        oversized[0] = True
                        process.kill()
                reader = threading.Thread(target=collect)
                reader.start()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(); reader.join(); process.stdout.close()
                    continue
                reader.join()
                process.stdout.close()
            except OSError:
                continue
            if oversized[0]: raise WsError('Clipboard exceeds 50 MB; save it to a file and run `ws digest` instead.')
            if process.returncode == 0:
                try: return b''.join(chunks).decode('utf-8')
                except UnicodeDecodeError: raise WsError(f'Clipboard output from {executable} was not valid UTF-8; pipe text to `ws paste` instead.')
            continue
    raise WsError('No supported clipboard reader found; pipe text to `ws paste` instead.')


def paste_save(root, text):
    if not isinstance(text, str): raise WsError('Paste input must be text.')
    text = redact(text)
    try: size = len(text.encode('utf-8'))
    except UnicodeEncodeError: raise WsError('Paste contains text that cannot be saved as UTF-8.')
    if size > MAX_READ_BYTES: raise WsError('Paste exceeds 50 MB; save it to a file and run `ws digest` instead.')
    inbox = inside(root / '.ws/inbox', [root])
    with lock(root):
        inbox.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        path = inbox / (stamp + '.log')
        suffix = 1
        while path.exists():
            suffix += 1
            path = inbox / f'{stamp}-{suffix}.log'
        atomic_write(path, text)
    return {'path': path, 'digest': digest_file(path, root=root)}


def prompt_is_large(prompt):
    if not isinstance(prompt, str): return False
    try:
        if len(prompt.encode('utf-8')) > 12 * 1024: return True
        return len(prompt.splitlines()) > 150
    except UnicodeEncodeError: return True


# --- orchestration run tracking ---------------------------------------------------

def run_log(root, task_id, step, provider, model='', tokens_in=0, tokens_out=0, seconds=0.0,
            result='ok', note='', worker_role='', effort='', checks=(), files=None, verdict='', findings=None,
            source='', import_id='', at=None):
    """Append one orchestration step (who did what, cost, outcome) to vault/Runs/<task>.jsonl."""
    task_path(root, task_id)
    if result not in ('ok', 'failed', 'rejected', 'accepted', 'skipped'):
        raise WsError('result is ok, failed, rejected, accepted or skipped.')
    entry = {'at': at or now(), 'task': task_id, 'step': redacted_line(step, 'Step'),
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
        if source:
            if source != 'codeburn' or not re.fullmatch(r'[a-f0-9]{64}', import_id):
                raise WsError('Imported usage requires a Codeburn source and stable import ID.')
            entry.update(source=source, import_id=import_id)
            if path.is_file():
                lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
                matches = []
                for raw in lines:
                    try:
                        old = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(old, dict) and old.get('import_id') == import_id:
                        matches.append(old)
                if matches:
                    if len(matches) == 1 and matches[0] == entry:
                        return None
                    replaced, rendered = False, []
                    for raw in lines:
                        try:
                            old = json.loads(raw)
                        except ValueError:
                            rendered.append(raw)
                            continue
                        if isinstance(old, dict) and old.get('import_id') == import_id:
                            if not replaced:
                                rendered.append(json.dumps(entry) + '\n')
                                replaced = True
                        else:
                            rendered.append(raw)
                    atomic_write(path, ''.join(rendered))
                    return entry
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8', newline='') as stream:
            stream.write(json.dumps(entry) + '\n')
    return entry


def import_codeburn(root, since=None, task_id=None):
    from .codeburn import import_usage
    return import_usage(root, since, task_id)


def run_entries(root, task_id):
    task_path(root, task_id)
    path = vault(root) / 'Runs' / f'{task_id}.jsonl'
    if not path.exists():
        return []
    entries = []
    with path.open(encoding='utf-8') as stream:
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
        entries = [e for e in run_entries(root, path.stem) if e.get('source') != 'codeburn'][-2:]
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
        for line in path.read_text(encoding='utf-8').splitlines():
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
        text = path.read_text(encoding='utf-8')
        if conflicted(text):
            errors.append(f'{path.name}: ' + conflict_hint(path.stem)); continue
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
    names = {p.stem for p in v.rglob('*.md')} | {p.relative_to(v).as_posix()[:-3] for p in v.rglob('*.md')}
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
    report = {'workspace': config(root)['name'], 'packs': config(root).get('packs', []), 'tasks': counts,
              'active_claims': [f"{t['id']} by {t['claimed_by']}" for t in tasks if t['claimed_by']],
              'conflicted': [conflict_hint(t['id']) for t in tasks if t['status'] == 'conflicted'],
              'blocked': [f"{t['id']}: {t['next']}" for t in tasks if t['status'] == 'blocked'],
              'open_feedback': len(feedback_list(root)), 'lessons': len(lesson_search(root, '')),
              'runs': run_report(root)}
    from . import native
    goals = native.codex_goals(root)
    if 'skipped' not in goals:
        report['codex_goals'] = goals
    return report


def _has_app(name):
    return any(Path(base, f'{name}.app').exists() for base in ('/Applications', Path.home() / 'Applications'))


def requirement_status(manifest):
    out = []
    for req in manifest.get('requires', []):
        ok = bool(shutil.which(req['cmd'])) if 'cmd' in req else _has_app(req['app'])
        out.append({'pack': manifest['name'], 'needs': req.get('cmd') or req.get('app'), 'ok': ok,
                    'optional': req.get('optional', False), 'why': req['why'], 'install': req['install']})
    return out


def tool_policy(root, entry):
    cfg = config(root) if root else {}
    profile = cfg.get('tool_profile', 'standard')
    if profile not in ('lean', 'standard', 'full'):
        profile = 'standard'
    default = profile == 'full' or (profile == 'standard' and entry['level'] == 'recommended')
    override = cfg.get('tool_overrides', {}).get(entry['name'])
    mode = override if override in ('on', 'off', 'ask') else ('on' if default else 'off')
    return {'profile': profile, 'override': override, 'mode': mode}


def tool_costs(root=None, usage=None):
    """Measure full MCP tool descriptors and local skill/plugin metadata without changing them."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('ws_mcp_server', KIT / 'mcp' / 'server.py')
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)  # our server by path: a top-level 'mcp' import could pick up the unrelated MCP SDK
    reply = server.handle(root, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
    schemas = reply['result']['tools']
    schema_costs = []
    for item in schemas:
        payload = json.dumps({key: item[key] for key in ('name', 'description', 'inputSchema')},
                             separators=(',', ':')).encode()
        schema_costs.append({'name': item['name'], 'bytes': len(payload),
                             'approx_tokens': (len(payload) + 3) // 4})
    if usage is None:
        from . import assist
        _, cached = assist.cost_data()
        rows = cached.get('mcp', [])
        usage = {str(row.get('Server', '')).lower(): row.get('Calls', 0) for row in rows}
    report = []
    for entry in tools():
        metadata_bytes = len(json.dumps(entry, separators=(',', ':')).encode())
        metadata_files = set()
        checks = [entry['detect']] if isinstance(entry['detect'], str) else entry['detect']
        for check in checks:
            if check.startswith('~/'):
                path = Path.home() / check[2:]
            elif check.startswith('/'):
                path = Path(check)
            else:
                continue
            if path.is_file():
                metadata_files.add(path.resolve())
            elif path.is_dir():
                metadata_files.update(p.resolve() for p in path.rglob('*') if p.is_file() and
                                      p.name in ('SKILL.md', 'plugin.json'))
        file_bytes = sum(path.stat().st_size for path in metadata_files)
        key = entry['name'].lower()
        calls = next((count for name, count in usage.items() if key in name), None)
        report.append(dict(entry, policy=tool_policy(root, entry), catalog_bytes=metadata_bytes,
                           skill_plugin_bytes=file_bytes, approx_tokens=(metadata_bytes + file_bytes + 3) // 4,
                           uses_last_30_days=calls))
    schema_bytes = sum(item['bytes'] for item in schema_costs)
    return {'profile': config(root).get('tool_profile', 'standard') if root else 'standard',
            'mcp_schema_scope': 'tool name, description and input schema from tools/list',
            'mcp_schema_bytes': schema_bytes, 'mcp_schema_approx_tokens': (schema_bytes + 3) // 4,
            'mcp_tools': schema_costs, 'tools': report,
            'usage_source': 'Codeburn daily cache, last 30 days' if usage else 'unavailable'}


def tools(root=None):
    """Catalog entries with their current executable state; never install anything."""
    entries = json.loads((KIT / 'tools.json').read_text(encoding='utf-8'))
    return [dict(entry, installed=_detected(entry['detect']), **({'policy': tool_policy(root, entry)} if root else {}))
            for entry in entries]


def _detected(checks):
    # A check is a command on PATH, 'app:<Name>' for a macOS app, or a '~/' path (plugins and skills).
    for check in ([checks] if isinstance(checks, str) else checks):
        if check.startswith('app:'):
            found = _has_app(check[4:])
        elif check.startswith('~/'):
            found = Path(check).expanduser().exists()
        else:
            found = bool(shutil.which(check))
        if found:
            return True
    return False


def _mcp_config(root, client):
    locations = MCP_LOCATIONS
    if client not in locations: return None
    relative, key = locations[client]
    path = root / relative
    if not path.exists():
        return None
    try:
        server = json.loads(path.read_text(encoding='utf-8'))[key]['ai-dev-workspace']
        command, args = server['command'], server.get('args', [])
        if not isinstance(command, str) or not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError('command and args must be strings')
        return path, [command, *args]
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        return path, str(exc)


def mcp_doctor(root, clients=('claude', 'cursor', 'vscode', 'gemini')):
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
        report = {'client': client, 'config': path.relative_to(root).as_posix(), 'ok': False}
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


def _git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, encoding='utf-8', errors='replace', timeout=10)


def _team_checks(root):
    """Warnings for a workspace shared through git (local claims must stay local, no secrets in tracked notes); None outside a repo."""
    try:
        if _git(root, 'rev-parse', '--is-inside-work-tree').stdout.strip() != 'true': return None
        warnings = []
        if _git(root, 'check-ignore', '-q', '.ws/claims/probe').returncode != 0:
            warnings.append('.ws/ is not ignored: add `.ws/` to .gitignore so local claim tokens are never committed.')
        if _git(root, 'ls-files', '-z', '--', '.ws').stdout.strip('\0'):
            warnings.append('.ws/ files are tracked: run `git rm -r --cached .ws` so claim tokens leave the repo.')
        found = []
        for name in _git(root, 'ls-files', '-z', '--', vault(root).resolve().relative_to(root.resolve()).as_posix()).stdout.split('\0'):
            if not name: continue
            try:
                path = root / name
                if path.stat().st_size >= 1_000_000:
                    warnings.append(f'{name}: not checked for secrets (file is 1 MB or larger).'); continue
                text = read_text(path, [root])
            except (OSError, WsError):
                warnings.append(f'{name}: not checked for secrets (cannot read safely).'); continue
            lines = {text.count('\n', 0, m.start()) + 1 for rx in (SECRET_RE, URL_CREDENTIALS_RE) for m in rx.finditer(text)}
            found += [f'{name}:{n}' for n in sorted(lines)]
        # The index, rather than the edited working copy, is what the next commit shares.
        for name in _git(root, 'diff', '--cached', '--name-only', '-z', '--', vault(root).resolve().relative_to(root.resolve()).as_posix()).stdout.split('\0'):
            if not name: continue
            revision = ':./' + name
            size = _git(root, 'cat-file', '-s', revision)
            if size.returncode: continue  # deletion or unmerged entry; conflict checks handle the latter
            if int(size.stdout) >= 1_000_000:
                warnings.append(f'{name}: staged content not checked for secrets (1 MB or larger).'); continue
            staged = _git(root, 'show', revision)
            if staged.returncode:
                warnings.append(f'{name}: staged content not checked for secrets (cannot read index).'); continue
            text = staged.stdout
            lines = {text.count('\n', 0, m.start()) + 1 for rx in (SECRET_RE, URL_CREDENTIALS_RE) for m in rx.finditer(text)}
            found += [f'{name}:{n} (staged)' for n in sorted(lines)]
        warnings += [f'possible secret at {place} (value not shown); remove it and rotate the credential.' for place in found[:10]]
        if len(found) > 10: warnings.append(f'{len(found) - 10} more possible secrets in tracked vault files.')
        return {'warnings': warnings}
    except (OSError, ValueError, subprocess.SubprocessError, WsError):
        return None


def doctor(root=None, mcp=False):
    """What is installed, what each plugged pack still needs, and recommended extras."""
    report = {'core': {'python3': True, 'git': bool(shutil.which('git'))}, 'packs': [], 'recommended': [],
              'skill_duplicates': []}
    packs = config(root).get('packs', []) if root else []
    for name in packs:
        local = config(root).get('local_packs', {}).get(name)
        if local:
            from .packs import load
            manifest = load(local['path'])[1]
        else: manifest = pack_manifest(name)
        report['packs'] += requirement_status(manifest)
    listed_tools = tools(root)
    missing_tools = [tool for tool in listed_tools if tool['level'] == 'recommended' and not tool['installed']
                     and tool_policy(root, tool)['mode'] != 'off']
    report['recommended'] = missing_tools
    report['toolbox'] = missing_tools
    report['tool_profile'] = config(root).get('tool_profile', 'standard') if root else 'standard'
    report['tools'] = listed_tools
    cache = Path.home() / '.cache' / 'ai-dev-workspace' / 'update.json'
    report['kit'] = {'version': kit_meta()['version']}
    if cache.is_file():
        report['kit'].update(json.loads(cache.read_text(encoding='utf-8'))['result'])
    if root:
        report['workspace'] = str(root)
        report['capture_health'] = capture_health(root)
        from . import native
        report['codex_goals'] = native.codex_goals(root)
        selftests = root / '.ws/delegate-selftests.json'
        report['delegate_selftests'] = json.loads(selftests.read_text(encoding='utf-8')) if selftests.exists() else {}
        report['valid'] = validate(root)['valid']
        report['conflicted'] = [conflict_hint(t['id']) for t in task_list(root) if t['status'] == 'conflicted']
        team = _team_checks(root)
        if team is not None: report['team'] = team
        report['clients'] = {client: client_connected(root, client)
                             for client in ('claude', 'codex', 'cursor', 'vscode', 'gemini')}
        report['client_instructions'] = {
            name: {'path': path, 'present': (root / path).is_file()}
            for name, path in (('copilot', '.github/copilot-instructions.md'), ('gemini', 'GEMINI.md'))}
        from . import orchestration
        try:
            report['routes'] = {role: orchestration.route(root, role)
                                for role in ('lead', 'planner', 'worker', 'explorer', 'reviewer', 'local')}
        except WsError as exc:  # workspaces created before routing.json: doctor still reports everything else
            report['routes'] = {'error': str(exc)}
        for client, location in (('claude', '.claude/skills'), ('codex', '.agents/skills')):
            project = root / location
            user = Path.home() / location
            if project.is_dir() and user.is_dir():
                project_names = {p.name for p in project.iterdir() if p.is_dir() and (p / 'SKILL.md').is_file()}
                user_names = {p.name for p in user.iterdir() if p.is_dir() and (p / 'SKILL.md').is_file()}
                report['skill_duplicates'].extend({'client': client, 'name': name}
                                                  for name in sorted(project_names & user_names))
        if mcp:
            report['mcp'] = mcp_doctor(root)
    return report


# --- releases and feedback-to-issue loop -------------------------------------------

def kit_meta():
    return json.loads((KIT / 'kit.json').read_text(encoding='utf-8'))


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
        data = json.loads(cache.read_text(encoding='utf-8'))
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
    return path, (path.read_text(encoding='utf-8').splitlines() if path.exists() else [])


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
        last = json.loads(stamp.read_text(encoding='utf-8')).get('at', 0) if stamp.is_file() else 0
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
    from . import assist
    return assist.notices(root, 2, out)
