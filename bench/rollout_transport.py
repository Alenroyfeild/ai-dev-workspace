"""Isolated Codex transport for the explicitly invoked continuity benchmark."""
import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from bench import run


def usage(events, exit_code, prior=None):
    metrics = run.metrics('codex', events, exit_code)
    if prior:  # Codex exec resume reports cumulative session usage, not this turn's increment.
        for key in ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens'):
            metrics[key] = max(0, metrics[key] - prior.get(key, 0))
    return metrics


def session(root, home, prompt, workspace, auth, resume=None, prior=None):
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
        return {'completed': False, 'seconds': time.monotonic()-start}, '', None
    except KeyboardInterrupt:
        os.killpg(process.pid, signal.SIGKILL); process.communicate(); raise
    events = []
    for line in output.splitlines():
        try: events.append(json.loads(line))
        except ValueError: pass
    messages = [e['item'].get('text', '') for e in events if e.get('type') == 'item.completed' and e.get('item', {}).get('type') == 'agent_message']
    thread = next((e['thread_id'] for e in events if e.get('type') == 'thread.started'), resume)
    return dict(usage(events, process.returncode, prior), seconds=round(time.monotonic()-start, 2)), '\n'.join(messages), thread

