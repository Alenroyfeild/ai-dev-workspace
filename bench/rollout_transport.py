"""Isolated Codex transport for the explicitly invoked continuity benchmark."""
import json
import os
import re
import shlex
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from bench import run
from ws import core


# Fixed vocabularies prevent attacker-controlled command/tool strings from becoming
# persisted data. Unknown names deliberately collapse to "other".
_COMMAND_NAMES = frozenset(('cat', 'ls', 'pwd', 'rg', 'grep', 'sed', 'awk', 'head', 'tail', 'wc',
    'find', 'git', 'python', 'python3', 'pytest', 'make', 'jq', 'sort', 'uniq', 'cut', 'diff',
    'stat', 'test', 'printf', 'echo', 'mkdir', 'touch', 'cp', 'mv', 'rm', 'chmod', 'curl',
    'env', 'sh', 'bash', 'zsh', 'tree'))
_WS_COMMANDS = frozenset(('start', 'brief', 'remember', 'checkpoint', 'task', 'claim', 'release',
    'doctor', 'status', 'nudge', 'help', 'search', 'lessons', 'lesson', 'know', 'notices', 'recap',
    'pr-notes', 'validate', 'connect', 'init', 'demo', 'update', 'upgrade', 'audit', 'tools',
    'assist', 'feedback', 'import', 'delegate', 'route', 'team', 'sync', 'digest', 'pack', 'next'))
_MCP_TOOLS = frozenset(('brief', 'find_task', 'read_task', 'new_task', 'claim_task', 'release_task',
    'claim_next_task', 'checkpoint', 'remember', 'search_vault', 'search_lessons', 'add_lesson',
    'know_list', 'know_show', 'know_add', 'route', 'delegate', 'assist', 'import_usage',
    'search_sessions', 'codebase_map', 'nudge', 'connect_client', 'add_feedback', 'digest_file',
    'log_step', 'trace', 'notices', 'status'))
_CLAUDE_TOOLS = frozenset(('Read', 'Grep', 'Glob', 'Edit', 'Write', 'Skill', 'Task', 'WebSearch', 'WebFetch'))
_CODEX_TOOLS = {'file_change': 'file_change', 'web_search': 'web_search',
                'collab_agent_tool_call': 'agent', 'dynamic_tool_call': 'other'}


def shell_name(command):
    """Return a fixed command label, never shell arguments, paths, or output."""
    if not isinstance(command, str):
        return 'other'
    try:
        words = shlex.split(command)
        # Codex commonly wraps a command in /bin/{ba,z}sh -lc '...'.
        for _ in range(3):
            if len(words) >= 3 and words[0].rsplit('/', 1)[-1] in ('sh', 'bash', 'zsh') \
                    and words[1].startswith('-') and 'c' in words[1][1:]:
                words = shlex.split(words[2])
            else:
                break
    except ValueError:
        return 'other'
    if not words:
        return 'other'
    command_name = words[0].replace('\\', '/').rsplit('/', 1)[-1]
    if command_name == 'ws':
        args = words[1:]
        # This is the only global option that consumes a value before the command.
        if len(args) >= 2 and args[0] == '--workspace-root':
            args = args[2:]
        return 'ws ' + args[0] if args and args[0] in _WS_COMMANDS else 'ws'
    return command_name if command_name in _COMMAND_NAMES else 'other'


def mcp_name(name):
    return 'mcp:' + name if isinstance(name, str) and name in _MCP_TOOLS else 'mcp:other'


def codex_tool_names(events):
    names, indices = [], {}
    for event in events:
        if not isinstance(event, dict) or event.get('type') not in ('item.started', 'item.completed'):
            continue
        item = event.get('item')
        if not isinstance(item, dict):
            continue
        kind = item.get('type')
        if not isinstance(kind, str):
            continue
        if kind == 'command_execution':
            name = shell_name(item.get('command'))
        elif kind == 'mcp_tool_call':
            name = mcp_name(item.get('tool'))
        elif kind in _CODEX_TOOLS:
            name = _CODEX_TOOLS[kind]
        else:
            continue
        ident = item.get('id')
        if isinstance(ident, str) and ident in indices:
            if names[indices[ident]] in ('other', 'mcp:other'):
                names[indices[ident]] = name
        else:
            if isinstance(ident, str):
                indices[ident] = len(names)
            names.append(name)
    return names


def claude_tool_names(events):
    names = []
    for event in events:
        if not isinstance(event, dict) or event.get('type') != 'assistant':
            continue
        message = event.get('message')
        content = message.get('content', []) if isinstance(message, dict) else []
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get('type') != 'tool_use':
                continue
            tool = block.get('name')
            if tool == 'Bash':
                inputs = block.get('input')
                names.append(shell_name(inputs.get('command') if isinstance(inputs, dict) else None))
            elif isinstance(tool, str) and tool.startswith('mcp__ai-dev-workspace__'):
                names.append(mcp_name(tool[len('mcp__ai-dev-workspace__'):]))
            else:
                names.append(tool if isinstance(tool, str) and tool in _CLAUDE_TOOLS else 'other')
    return names


def usage(events, exit_code, prior=None):
    metrics = run.metrics('codex', events, exit_code)
    if prior:  # Codex exec resume reports cumulative session usage, not this turn's increment.
        for key in ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens'):
            metrics[key] = max(0, metrics[key] - prior.get(key, 0))
    return metrics


def claude_session(root, home, prompt, workspace, resume=None):
    """Use an allowlisted environment and strict project-only settings."""
    home.mkdir(parents=True, exist_ok=True)
    env = run.claude_environment(home, root if workspace else None)
    version = subprocess.run(['claude', '--version'], env=env, capture_output=True, text=True, timeout=15)
    match = re.search(r'\b(\d+)\.(\d+)\.(\d+)\b', version.stdout)
    if version.returncode or not match or tuple(map(int, match.groups())) < (2, 1, 285):
        raise RuntimeError('Claude benchmark needs Claude Code >= 2.1.285 for strict isolation; no fallback or install.')
    policy = {'permissions': {'blockReadsOutsideWorkingDirectories': True}, 'disableClaudeAiConnectors': True,
              'sandbox': {'enabled': True, 'failIfUnavailable': True, 'allowUnsandboxedCommands': False, 'autoAllowBashIfSandboxed': False,
                          'filesystem': {'allowRead': [str(run.KIT)]},
                          'credentials': {'envVars': [{'name': 'ANTHROPIC_API_KEY', 'mode': 'deny'}]}}}
    mcp = root / '.mcp.json'
    if workspace and not mcp.is_file(): raise RuntimeError('Workspace benchmark requires its MCP config; no empty-config fallback.')
    servers = {'mcpServers': {'ai-dev-workspace': core.mcp_command(root)}} if workspace else {'mcpServers': {}}
    if workspace and json.loads(core.read_text(mcp, [root])) != servers:
        raise RuntimeError('Workspace MCP config changed; only the trusted kit server is permitted.')
    tools = ['Read', 'Grep', 'Glob', 'Edit', 'Write', 'Bash(python3 *)', 'Bash(git *)'] + (['Skill', 'Bash(ws *)', 'mcp__ai-dev-workspace__*'] if workspace else [])
    args = ['claude', '-p', prompt] + (['--resume', resume] if resume else []) + [
        '--setting-sources', 'project', '--strict-mcp-config', '--mcp-config', json.dumps(servers),
        '--settings', json.dumps(policy), '--tools', 'Read,Grep,Glob,Edit,Write,Bash' + (',Skill' if workspace else ''),
        '--permission-mode', 'acceptEdits', '--allowedTools', *tools, '--max-turns', '40', '--model', 'sonnet', '--output-format', 'stream-json', '--verbose']
    start = time.monotonic()
    process = subprocess.Popen(args, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try: output, _ = process.communicate(timeout=600)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL); process.communicate()
        return {'completed': False, 'seconds': time.monotonic()-start, 'tool_names': []}, '', None
    except KeyboardInterrupt:
        os.killpg(process.pid, signal.SIGKILL); process.communicate(); raise
    events = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
            if isinstance(event, dict): events.append(event)
        except ValueError: pass
    result = next((e for e in reversed(events) if e.get('type') == 'result'), {})
    return dict(run.metrics('claude', events, process.returncode), tool_names=claude_tool_names(events), seconds=round(time.monotonic()-start, 2)), result.get('result') or '', result.get('session_id', resume)


def session(root, home, prompt, workspace, auth, resume=None, prior=None):
    if os.environ.get('WS_BENCH_PROVIDER') == 'claude': return claude_session(root, home, prompt, workspace, resume)
    codex = home / '.codex'; codex.mkdir(parents=True, exist_ok=True)
    if not (codex / 'auth.json').exists() and auth.is_file(): (codex / 'auth.json').symlink_to(auth)
    (codex / 'config.toml').write_text('[projects.' + json.dumps(str(root)) + ']\ntrust_level="trusted"\n')
    env = dict(os.environ, HOME=str(home), CODEX_HOME=str(codex), WS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1',
               PATH=str(run.KIT / 'bin') + os.pathsep + os.environ['PATH'])
    env.pop('WS_ROOT', None)
    if workspace: env['WS_ROOT'] = str(root)
    args = ['codex', 'exec'] + (['resume', resume] if resume else ['-C', str(root)])
    args += ['--json', '--dangerously-bypass-hook-trust', '--disable', 'apps', '--disable', 'plugins',
             '--enable' if workspace else '--disable', 'hooks', '--skip-git-repo-check', '-m', 'gpt-6-luna',
             '-c', 'sandbox_mode="workspace-write"', '-c', 'approval_policy="never"', '-c', 'model_reasoning_effort="high"', prompt]
    start = time.monotonic()
    process = subprocess.Popen(args, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try: output, _ = process.communicate(timeout=600)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL); process.communicate()
        return {'completed': False, 'seconds': time.monotonic()-start, 'tool_names': []}, '', None
    except KeyboardInterrupt:
        os.killpg(process.pid, signal.SIGKILL); process.communicate(); raise
    events = []
    for line in output.splitlines():
        try: events.append(json.loads(line))
        except ValueError: pass
    messages = [e['item'].get('text', '') for e in events if e.get('type') == 'item.completed' and e.get('item', {}).get('type') == 'agent_message']
    thread = next((e['thread_id'] for e in events if e.get('type') == 'thread.started'), resume)
    return dict(usage(events, process.returncode, prior), tool_names=codex_tool_names(events), seconds=round(time.monotonic()-start, 2)), '\n'.join(messages), thread
