#!/usr/bin/env python3
"""Fresh-session continuity benchmark. Fixtures and checks never live in real workspaces."""
import argparse
import datetime
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
sys.path.insert(0, str(KIT))
from ws import core


def command(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


def create(root, data):
    repo = root / 'repo'; repo.mkdir(parents=True)
    for name, text in data['files'].items():
        path = repo / name
        if Path(name).is_absolute() or '..' in Path(name).parts: raise ValueError('Fixture paths must stay in repo.')
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
    command(['git', 'init', '-q'], repo); command(['git', 'add', '.'], repo)
    command(['git', '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture'], repo)


def score(root, data):
    repo = root / 'repo'
    tests = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], cwd=repo, capture_output=True)
    checked = subprocess.run([sys.executable, str(HERE / 'checks' / data['checks']), str(repo)], cwd=repo, capture_output=True, text=True)
    try: checks = json.loads(checked.stdout) if checked.returncode == 0 else {'checker_completed': False}
    except ValueError: checks = {'checker_completed': False}
    if not isinstance(checks, dict) or not checks or any(type(v) is not bool for v in checks.values()): checks = {'checker_completed': False}
    return {'tests_pass': tests.returncode == 0, 'checks': checks}


def prepare_snapshot(root, data):
    repo = root / 'repo'
    for name, expected in data.get('setup', {}).items():
        path = repo / name
        if not path.is_file() or path.read_text() != expected:
            raise RuntimeError('Session 1 did not establish the interrupted checkpoint; inconclusive.')
    if not data.get('preserve_code'):
        command(['git', 'restore', '.'], repo); command(['git', 'clean', '-fdq'], repo)


def metrics(provider, events, exit_code):
    done = [e for e in events if e.get('type') == ('turn.completed' if provider == 'codex' else 'result')]
    usage = done[-1].get('usage', {}) if done else {}
    return {'completed': bool(done) and exit_code == 0 and not done[-1].get('is_error'), 'exit_code': exit_code,
            'tool_calls': sum(e.get('type') == 'item.completed' and e.get('item', {}).get('type') == 'command_execution' for e in events) if provider == 'codex' else sum(sum(c.get('type') == 'tool_use' for c in e.get('message', {}).get('content', [])) for e in events if e.get('type') == 'assistant'),
            'input_tokens': usage.get('input_tokens', 0), 'output_tokens': usage.get('output_tokens', 0),
            'cache_read_tokens': usage.get('cached_input_tokens', usage.get('cache_read_input_tokens', 0)),
            'cache_write_tokens': usage.get('cache_write_input_tokens', usage.get('cache_creation_input_tokens', 0)),
            'cost_usd': done[-1].get('total_cost_usd') if done else None}


def session(root, prompt, provider, model, workspace, auth):
    with tempfile.TemporaryDirectory(prefix='ws-bench-home-') as temporary:
        home = Path(temporary); codex = home / '.codex'; codex.mkdir()
        if auth.is_file(): (codex / 'auth.json').symlink_to(auth)
        (codex / 'config.toml').write_text('[projects.' + json.dumps(str(root)) + ']\ntrust_level="trusted"\n')
        env = dict(os.environ, HOME=str(home), CODEX_HOME=str(codex), PATH=str(KIT / 'bin') + os.pathsep + os.environ['PATH'], WS_OFFLINE='1')
        env.pop('WS_ROOT', None)
        if workspace: env['WS_ROOT'] = str(root)
        if provider == 'codex':
            args = ['codex', 'exec', '--json', '--dangerously-bypass-hook-trust', '--disable', 'apps', '--disable', 'plugins', '--enable' if workspace else '--disable', 'hooks', '-s', 'workspace-write', '-c', 'approval_policy="never"', '-m', model, '-c', 'model_reasoning_effort="high"', '--skip-git-repo-check', '-C', str(root), prompt]
        else:
            args = ['claude', '-p', prompt, '--setting-sources', 'project', '--strict-mcp-config', '--mcp-config', json.dumps({'mcpServers': {}}), '--permission-mode', 'acceptEdits', '--max-turns', '40', '--model', model, '--output-format', 'stream-json', '--verbose']
        start = time.monotonic(); process = subprocess.Popen(args, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try: output, _ = process.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL); output, _ = process.communicate()
        events = []
        for line in output.splitlines():
            try: events.append(json.loads(line))
            except ValueError: continue
        return dict(metrics(provider, events, process.returncode), seconds=round(time.monotonic()-start, 2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', default='decisions'); parser.add_argument('--provider', choices=('codex', 'claude'), default='codex')
    parser.add_argument('--model'); parser.add_argument('-n', type=int, default=5); parser.add_argument('--allow-claude', action='store_true')
    parser.add_argument('--output', type=Path); args = parser.parse_args()
    if args.n < 1 or args.provider == 'claude' and not args.allow_claude: parser.error('Use positive n; Claude execution requires --allow-claude.')
    if not shutil.which(args.provider): parser.error('Selected provider unavailable; no fallback or installation.')
    data = json.loads((HERE / 'scenarios' / (args.scenario + '.json')).read_text())
    auth = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'auth.json'
    result = {'date': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'provider': args.provider, 'model': args.model or ('gpt-6-luna' if args.provider == 'codex' else 'sonnet'), 'scenario': args.scenario, 'n': args.n, 'kit': command(['git', 'rev-parse', 'HEAD'], KIT).stdout.strip(), 'session1': {}, 'runs': []}
    with tempfile.TemporaryDirectory(prefix='ws-bench-') as temporary:
        base = Path(temporary).resolve()
        for arm in ('baseline', 'workspace'):
            root = base / arm; create(root, data)
            if arm == 'workspace':
                core.init(root, 'Synthetic benchmark', [], [str(root / 'repo')]); core.task_new(root, 'BENCH-1', data['title'], data['objective'], repo=str(root / 'repo'))
                core.claim(root, 'BENCH-1', 'synthetic'); core.checkpoint(root, 'BENCH-1', 'in_progress', 'Investigate the synthetic task.')
            result['session1'][arm] = session(root, data['session1'], args.provider, result['model'], arm == 'workspace', auth)
            if not result['session1'][arm]['completed']: raise RuntimeError('Session 1 did not complete; benchmark is inconclusive.')
            prepare_snapshot(root, data)
            snapshot = base / ('snapshot-' + arm); shutil.copytree(root, snapshot)
            for trial in range(1, args.n + 1):
                shutil.rmtree(root); shutil.copytree(snapshot, root)
                record = session(root, data['session2'], args.provider, result['model'], arm == 'workspace', auth)
                record.update(arm=arm, trial=trial, **score(root, data)); record['success'] = record['completed'] and record['tests_pass'] and all(record['checks'].values())
                record['result'] = 'inconclusive' if not record['completed'] else 'pass' if record['success'] else 'fail'
                result['runs'].append(record); print(json.dumps(record), flush=True)
    output = args.output or HERE / 'results' / (result['date'][:10] + '-' + args.provider + '.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('{\n' + '\n'.join(json.dumps(k) + ': ' + json.dumps(v) + ',' for k, v in result.items() if k != 'runs') + '\n"runs": [\n' + ',\n'.join(map(json.dumps, result['runs'])) + '\n]}\n')
    table = '| Arm | Successful session 2 | Mean seconds |\n|---|---|---|\n'
    for arm in ('baseline', 'workspace'):
        rows = [r for r in result['runs'] if r['arm'] == arm]
        table += f'| {arm} | {sum(r["success"] for r in rows)}/{args.n} | {sum(r["seconds"] for r in rows)/args.n:.1f} |\n'
    output.with_suffix('.md').write_text(table); print(table)


if __name__ == '__main__': main()
