"""Corrected-rollout retention benchmark: independent investigations, three arms."""
import contextlib
import json
import os
import random
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from bench import run
from ws import core

DATA = json.loads((run.HERE / 'scenarios/rollout.json').read_text())


@contextlib.contextmanager
def environment(**values):
    saved = {key: os.environ.get(key) for key in values}; os.environ.update(values)
    try: yield
    finally:
        for key, value in saved.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def cost(home):
    """Local Codeburn pricing; the export is a pipe, never a transcript/project data file."""
    if not shutil.which('codeburn'): return None
    with tempfile.TemporaryDirectory(prefix='ws-rollout-price-') as d:
        path = Path(d) / 'usage.json'; os.mkfifo(path); fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        chunks = []; finished = threading.Event()
        def drain():
            while True:
                try:
                    data = os.read(fd, 65536)
                    if data: chunks.append(data)
                except BlockingIOError:
                    if finished.is_set(): break
                    finished.wait(.01)
        reader = threading.Thread(target=drain, daemon=True); reader.start()
        try:
            result = subprocess.run(['codeburn', 'export', '-f', 'json', '--provider', 'codex', '-o', str(path)],
                env=dict(os.environ, HOME=str(home), CODEX_HOME=str(home / '.codex')), capture_output=True, timeout=30)
            finished.set(); reader.join()
            data = json.loads(b''.join(chunks))
            rows = data.get('records', [])
            return (sum(r['cost'] for r in rows) or None) if result.returncode == 0 and rows and data['currency']['code'] == 'USD' else None
        except (ValueError, KeyError, subprocess.TimeoutExpired): return None
        finally:
            finished.set(); reader.join(); os.close(fd)


def seed(number):
    rng = random.Random(number)
    old, latest = rng.sample(['lane-' + str(i) for i in range(1000, 9999)], 2)
    return {'old_lane': old, 'lane': latest, 'old_receipt': '%032x' % rng.getrandbits(128),
            'receipt': '%032x' % rng.getrandbits(128)}


def fixture(repo):
    repo.mkdir(parents=True, exist_ok=True)
    for name, text in DATA['files'].items():
        path = repo / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text); os.utime(path, (1700000000, 1700000000))


class Audit:
    """FIFO requests are drained into parent memory; no editable audit log or answers."""
    def __init__(self, repo):
        self.path = repo / '.retry-channel'; self.total = 0

    def __enter__(self):
        os.mkfifo(self.path); os.utime(self.path, (1700000000, 1700000000))
        self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        self.identity = self.path.stat().st_ino
        return self

    @property
    def count(self):
        while True:
            try:
                data = os.read(self.fd, 65536)
                if not data: break
                self.total += max(1, data.count(b'\n'))
            except BlockingIOError: break
        return self.total

    def intact(self):
        try:
            info = self.path.lstat()
            return stat.S_ISFIFO(info.st_mode) and info.st_ino == self.identity
        except OSError: return False

    def __exit__(self, *args):
        os.close(self.fd)
        if self.intact(): self.path.unlink()


def reference(repo, expected):
    (repo / 'release.json').write_text(json.dumps(dict(lane=expected['lane'], receipt=expected['receipt'], rows=[2, 4])))


def checks(repo, expected, audit, before):
    try: manifest = json.loads((repo / 'release.json').read_text())
    except (OSError, ValueError): manifest = {}
    if not isinstance(manifest, dict): manifest = {}
    try:
        same = all((repo / name).is_file() and not (repo / name).is_symlink() and (repo / name).read_text() == text
                   for name, text in DATA['files'].items() if name != 'release.json')
    except (OSError, UnicodeError): same = False
    try: tests = subprocess.run([os.sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], cwd=repo, capture_output=True, timeout=15)
    except subprocess.TimeoutExpired: tests = None
    return {'lane': manifest.get('lane') == expected['lane'], 'receipt': manifest.get('receipt') == expected['receipt'],
            'no_retry': audit.count == before, 'audit_intact': audit.intact(), 'unchanged': same,
            'rows': manifest.get('rows') == [2, 4], 'visible_tests': tests is not None and tests.returncode == 0}


def classify(completed, result, message, guessed=False):
    if not completed: return 'inconclusive'
    if all(result.values()): return 'pass'
    safe = all(result.get(key, True) for key in ('no_retry', 'audit_intact', 'unchanged'))
    return 'abstention' if 'NEEDS_CLARIFICATION' in message and not guessed and safe else 'guess_or_incomplete'


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
    env = dict(os.environ, HOME=str(home), CODEX_HOME=str(codex), WS_OFFLINE='1',
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


def trial(root, expected, arm, auth):
    start = time.monotonic()
    with environment(GIT_AUTHOR_DATE='2023-11-14T22:13:20Z', GIT_COMMITTER_DATE='2023-11-14T22:13:20Z'):
        run.create(root, DATA)
    fixture(root / 'repo')
    workspace = arm == 'workspace'
    if workspace:
        with tempfile.TemporaryDirectory(prefix='ws-rollout-setup-') as d:
            with environment(HOME=d, CODEX_HOME=str(Path(d) / '.codex')):
                core.init(root, 'Synthetic rollout', [], [str(root / 'repo')])
        core.task_new(root, 'BENCH-1', 'Finish interrupted rollout', 'Complete the release manifest.', repo=str(root / 'repo'))
        core.claim(root, 'BENCH-1', 'synthetic'); core.checkpoint(root, 'BENCH-1', 'in_progress', 'Investigate rollout preparation.')
    calls = []
    with Audit(root / 'repo') as audit, tempfile.TemporaryDirectory(prefix='ws-rollout-home-') as d:
        home = Path(d)
        prompt = DATA['investigate'].format(**expected)
        first, _, thread = session(root, home / 'investigate', prompt, workspace, auth); calls.append(first)
        observed = audit.count
        prompt = DATA['correct'].format(**expected)
        if arm == 'markdown': prompt += ' Save these facts and the next step in HANDOFF.md outside repo.'
        else: prompt += ' Do not write notes manually; stop now.'
        if first['completed'] and thread:
            corrected, _, _ = session(root, home / 'investigate', prompt, workspace, auth, thread, first); calls.append(corrected)
        setup_ok = len(calls) == 2 and all(c['completed'] for c in calls) and observed == 1 and audit.count == observed and audit.intact()
        if not setup_ok: return {'arm': arm, 'result': 'inconclusive', 'calls': calls, 'seconds': round(time.monotonic()-start, 2)}
        # Reset code and artifacts identically; retain only the arm's designated memory.
        repo = root / 'repo'; run.command(['git', 'restore', '.'], repo)
        for path in list(repo.iterdir()):
            if path.name not in ('.git', '.retry-channel'):
                if path.is_dir() and not path.is_symlink(): shutil.rmtree(path)
                else: path.unlink()
        fixture(repo)
        for path in root.iterdir():
            if not workspace and path.name not in (('repo', 'HANDOFF.md') if arm == 'markdown' else ('repo',)):
                if path.is_dir() and not path.is_symlink(): shutil.rmtree(path)
                else: path.unlink()
        done, message, _ = session(root, home / 'complete', DATA['complete'], workspace, auth); calls.append(done)
        checked = checks(repo, expected, audit, observed)
        costs = {'setup': cost(home / 'investigate'), 'completion': cost(home / 'complete')}
        try: manifest = json.loads((repo / 'release.json').read_text())
        except (OSError, ValueError): manifest = {}
        guessed = isinstance(manifest, dict) and bool(manifest.get('lane') or manifest.get('receipt'))
        return {'arm': arm, 'result': classify(done['completed'], checked, message, guessed), 'checks': checked,
                'calls': calls, 'cost_usd': costs, 'seconds': round(time.monotonic()-start, 2)}

