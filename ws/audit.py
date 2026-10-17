"""ws audit: read-only scorecard of a repo's AI assistant setup with the top fixes; no network, no writes."""
import datetime
import json
import re
import subprocess
from pathlib import Path

from . import core

INSTRUCTIONS = ('CLAUDE.md', 'AGENTS.md', '.github/copilot-instructions.md', 'GEMINI.md')
BIG = 2000  # words loaded into every session before the user types anything
MCP_SERVERS = 5
EXTENSIONLESS = {'Makefile', 'Dockerfile', 'Justfile', 'Procfile', 'Gemfile', 'Rakefile', 'Brewfile', 'Vagrantfile', 'LICENSE', 'CODEOWNERS'}  # @Name is a person otherwise
STALE_DAYS = 14


def _repo(path):
    path = Path(path or '.').resolve()
    try:
        top = subprocess.run(['git', '-C', str(path), 'rev-parse', '--show-toplevel'], capture_output=True, text=True, timeout=5)
        return Path(top.stdout.strip()).resolve() if top.returncode == 0 else path
    except (OSError, subprocess.SubprocessError):
        return path


def _refs(text):
    """Files an instruction file points at: @imports, Markdown links and backticked relative paths."""
    imports = [r.rstrip('.') for r in re.findall(r'(?m)(?:^|\s)@([\w.-]+(?:/[\w.-]+)*)', text)]
    # @AGENTS.md is a file import; @openai/agents (no extension, with a slash) is a package name; @Makefile (capitalised, no slash) is a file.
    found = ([r for r in imports if re.search(r'\.\w{1,8}$', r) or r.split('/')[-1] in EXTENSIONLESS] + re.findall(r'\]\(([^)#\s]+)', text)
             + re.findall(r'`((?:[\w.-]+/)+[\w.-]+\.\w{1,8}|[\w-]+\.(?:md|py|json|toml|ya?ml|sh|js|ts))`', text))
    return [r for r in dict.fromkeys(found) if '://' not in r and '*' not in r and not r.startswith(('mailto:', '/', '~', '$'))]


def _session_start_command(path):
    """True when a hooks file has at least one SessionStart command (not just an empty list)."""
    try: entries = json.loads(path.read_text(encoding='utf-8')).get('hooks', {}).get('SessionStart')
    except (OSError, ValueError, AttributeError): return False
    if not isinstance(entries, list): return False
    hooks = [h for e in entries if isinstance(e, dict) for h in (e.get('hooks') if isinstance(e.get('hooks'), list) else [e])]
    return any(isinstance(h, dict) and isinstance(h.get('command'), str) and h['command'].strip() for h in hooks)


def _mcp_servers(repo):
    names = set()
    try: servers = json.loads((repo / '.mcp.json').read_text(encoding='utf-8')).get('mcpServers')
    except (OSError, ValueError, AttributeError): servers = None
    if isinstance(servers, dict): names |= set(servers)
    try: names |= set(re.findall(r'(?m)^\[mcp_servers\.([^\].]+)\]', (repo / '.codex/config.toml').read_text(encoding='utf-8')))
    except OSError: pass
    return sorted(names)


def audit(path=None):
    repo = _repo(path)
    checks = []
    def check(name, ok, detail, fix):
        checks.append({'check': name, 'ok': bool(ok), 'detail': detail, 'fix': '' if ok else fix})

    present = [n for n in INSTRUCTIONS if (repo / n).is_file()]
    texts = {n: (repo / n).read_text(encoding='utf-8', errors='replace') for n in present}
    words = sum(len(t.split()) for t in texts.values())
    check('Instructions', {'CLAUDE.md', 'AGENTS.md'} & set(present), ', '.join(present) or 'none',
          'Add AGENTS.md with the build and test commands and repo rules; CLAUDE.md can import it with @AGENTS.md.')
    check('Instruction size', words <= BIG, f'{words:,} words loaded every session',
          f'Trim the instruction files under {BIG:,} words; move rarely needed detail into linked docs.')
    broken = [f'{n}: {r}' for n, t in texts.items() for r in _refs(t) if not ((repo / n).parent / r).exists() and not (repo / r).exists()]
    check('References', not broken, ', '.join(broken[:5]) + (f' (+{len(broken) - 5} more)' if len(broken) > 5 else '') or 'all resolve',
          'Fix or remove references to missing files: ' + ', '.join(broken[:3]) + '.')

    root = None
    try: root = core.find_root(repo) if (repo / '.ws-start.json').is_file() else None
    except (core.WsError, OSError, ValueError): pass
    check('Memory', root, 'connected' if root else 'not connected', 'Run ws start in this repo to give every session the saved decisions and next step.')
    hooks = [label for label, rel in (('Claude Code', '.claude/settings.local.json'), ('Claude Code', '.claude/settings.json'), ('Codex', '.codex/hooks.json'))
             if _session_start_command(repo / rel)]
    check('Session hooks', hooks, ', '.join(dict.fromkeys(hooks)) or 'none',
          'Run ws start: it adds SessionStart hooks so Claude Code and Codex load memory without being asked.')
    servers = _mcp_servers(repo)
    profile = core.config(root).get('mcp_tools', 'core') if root else 'core'
    check('MCP budget', len(servers) <= MCP_SERVERS and profile != 'all', f"{len(servers)} servers" + (', ws lists all tools' if profile == 'all' else ''),
          f'Each MCP server adds tool descriptions to every session; keep {MCP_SERVERS} or fewer'
          + (' and set "mcp_tools": "core" in workspace.json.' if profile == 'all' else '.'))
    if root:
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=STALE_DAYS)).strftime('%Y-%m-%d')
        stale = [t['id'] for t in core.task_list(root) if t['status'] == 'in_progress'
                 and str(core.task_read(root, t['id'], ['Next action'])['meta'].get('updated', ''))[:10] < cutoff]
        check('Stale tasks', not stale, ', '.join(stale[:5]) or 'none',
              f'Checkpoint or close tasks idle for {STALE_DAYS}+ days: ' + ', '.join(stale[:3]) + '.')
    passed = sum(c['ok'] for c in checks)
    fixes = []
    for fix in (c['fix'] for c in checks if c['fix']):
        if not (fix.startswith('Run ws start') and any(f.startswith('Run ws start') for f in fixes)): fixes.append(fix)  # one start fixes both
    return {'repo': repo.name, 'score': f'{passed}/{len(checks)}', 'checks': checks, 'fixes': fixes[:3]}


def text(report):
    lines = [f"AI setup audit for {report['repo']}: {report['score']}"]
    lines += [f"  {'ok  ' if c['ok'] else 'fix '} {c['check']}: {c['detail']}" for c in report['checks']]
    if report['fixes']: lines += ['Top fixes:'] + [f'{i}. {fix}' for i, fix in enumerate(report['fixes'], 1)]
    return '\n'.join(lines)
