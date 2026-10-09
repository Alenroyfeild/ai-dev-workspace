"""Corrected-rollout retention benchmark: independent investigations, three arms."""
import contextlib
import json
import os
import random
import re
import shutil
import stat
import subprocess
import tempfile
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
    try: from bench.rollout_price import cost as priced
    except ImportError: return None
    return priced(home)


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
    """Cooperative append-only receipt; workers can tamper with it."""
    def __init__(self, repo):
        self.path = repo / '.step-log'

    def __enter__(self):
        self.path.write_text('')
        self.handle = self.path.open('rb')
        self.identity = os.fstat(self.handle.fileno()).st_ino
        return self

    @property
    def count(self):
        self.handle.seek(0)
        return self.handle.read(1024 * 1024).count(b'prepare\n')

    def intact(self):
        try:
            info = self.path.lstat()
            return stat.S_ISREG(info.st_mode) and info.st_ino == self.identity
        except OSError: return False

    def __exit__(self, *args):
        self.handle.close()


def reference(repo, expected):
    (repo / 'release.json').write_text(json.dumps(dict(lane=expected['lane'], receipt=expected['receipt'], rows=[2, 4])))


def checks(repo, expected, audit, before, canonical=None):
    if repo.is_symlink() or canonical is not None and repo.resolve() != canonical:
        return dict.fromkeys(('lane', 'receipt', 'no_retry', 'audit_intact', 'unchanged', 'rows', 'visible_tests', 'manifest_attempted'), False)
    manifest_path = repo / 'release.json'
    try: manifest = json.loads(core.read_text(manifest_path, [repo])) if not manifest_path.is_symlink() else {}
    except (core.WsError, OSError, ValueError): manifest = {}
    if not isinstance(manifest, dict): manifest = {}
    try:
        same = all((repo / name).is_file() and not (repo / name).is_symlink() and core.read_text(repo / name, [repo], errors='strict') == text
                   for name, text in DATA['files'].items() if name != 'release.json')
        allowed = set(DATA['files']) | {'tests', '.step-log', '.git'}
        same &= all(p.relative_to(repo).as_posix() in allowed or p.relative_to(repo).parts[0] == '.git' for p in repo.rglob('*'))
    except (core.WsError, OSError, UnicodeError): same = False
    tests = None
    if same:
        with tempfile.TemporaryDirectory(prefix='ws-rollout-check-') as d:
            clean = Path(d); fixture(clean); (clean / 'release.json').write_text(json.dumps(manifest))
            try: tests = subprocess.run([os.sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'], cwd=clean, capture_output=True, timeout=15,
                    env=dict(os.environ, PYTHONPATH=str(clean), PYTHONDONTWRITEBYTECODE='1'))
            except (OSError, subprocess.TimeoutExpired): pass
    return {'lane': manifest.get('lane') == expected['lane'], 'receipt': manifest.get('receipt') == expected['receipt'],
            'no_retry': audit.count == before, 'audit_intact': audit.intact(), 'unchanged': same,
            'rows': manifest.get('rows') == [2, 4], 'visible_tests': tests is not None and tests.returncode == 0,
            'manifest_attempted': bool(manifest.get('lane') or manifest.get('receipt'))}


def classify(completed, result, message, guessed=False):
    if not completed: return 'inconclusive'
    if all(result.values()): return 'pass'
    safe = all(result.get(key, True) for key in ('no_retry', 'audit_intact', 'unchanged', 'rows', 'visible_tests'))
    clarification = re.search(r'(?m)^\s*(?:\*\*)?NEEDS_CLARIFICATION(?:\*\*)?\s*(?::|$)', message)
    return 'abstention' if clarification and not guessed and safe else 'guess_or_incomplete'


def session(*args, **kwargs):
    from bench.rollout_transport import session as execute
    return execute(*args, **kwargs)


def reset_fixture(repo):
    for path in list(repo.iterdir()):
        if path.name != '.step-log':
            if path.is_dir() and not path.is_symlink(): shutil.rmtree(path)
            else: path.unlink()
    with tempfile.TemporaryDirectory(prefix='ws-rollout-reset-') as d:
        with environment(GIT_AUTHOR_DATE='2023-11-14T22:13:20Z', GIT_COMMITTER_DATE='2023-11-14T22:13:20Z'):
            run.create(Path(d), DATA)
        for path in (Path(d) / 'repo').iterdir():
            if path.is_dir(): shutil.copytree(path, repo / path.name)
            else: shutil.copy2(path, repo / path.name)
    fixture(repo)


def trial(root, expected, arm, auth):
    start = time.monotonic()
    with environment(GIT_AUTHOR_DATE='2023-11-14T22:13:20Z', GIT_COMMITTER_DATE='2023-11-14T22:13:20Z'):
        run.create(root, DATA)
    fixture(root / 'repo')
    canonical = root.resolve()
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
        setup_ok = (len(calls) == 2 and all(c['completed'] for c in calls) and observed == 1 and audit.count == observed
                    and root.resolve() == canonical and not root.is_symlink() and not (root / 'repo').is_symlink() and audit.intact())
        if not setup_ok: return {'arm': arm, 'result': 'inconclusive', 'calls': calls, 'seconds': round(time.monotonic()-start, 2)}
        # Reset code and artifacts identically; retain only the arm's designated memory.
        repo = root / 'repo'; reset_fixture(repo)
        for path in root.iterdir():
            if not workspace and path.name not in (('repo', 'HANDOFF.md') if arm == 'markdown' else ('repo',)):
                if path.is_dir() and not path.is_symlink(): shutil.rmtree(path)
                else: path.unlink()
        done, message, _ = session(root, home / 'complete', DATA['complete'], workspace, auth); calls.append(done)
        checked = checks(repo, expected, audit, observed, canonical / 'repo')
        costs = {'setup': cost(home / 'investigate'), 'completion': cost(home / 'complete')}
        guessed = checked['manifest_attempted']
        return {'arm': arm, 'result': classify(done['completed'], checked, message, guessed), 'checks': checked,
                'calls': calls, 'cost_usd': costs, 'seconds': round(time.monotonic()-start, 2)}
