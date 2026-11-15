"""Run the corrected-rollout benchmark (POSIX, explicitly authorized model calls)."""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from ws import core


def save(output, result):
    core.atomic_write(output, '{\n' + ',\n'.join(json.dumps(k) + ': ' + json.dumps(v) for k, v in result.items() if k != 'runs') +
                      ',\n"runs": [\n' + ',\n'.join(map(json.dumps, result['runs'])) + '\n]}\n')


def transport_failures(calls, previous=0):
    for call in calls:
        previous = 0 if call['completed'] else previous + 1
    return previous


_CANDIDATE_SCRIPT = r"""
import json
import sys
import types
from pathlib import Path

data = json.load(sys.stdin)
kit = Path(data['kit']).resolve()
sys.path.insert(0, str(kit))
from ws import core
if Path(core.__file__).resolve() != kit / 'ws' / 'core.py':
    raise RuntimeError('Candidate workspace package did not load from the selected checkout')
package = types.ModuleType('bench')
package.__path__ = [data['harness']]
sys.modules['bench'] = package
from bench import run
run.KIT = kit
from bench import rollout
record = rollout.trial(Path(data['root']), data['expected'], 'workspace', Path(data['auth']))
Path(data['output']).write_text(json.dumps(record), encoding='utf-8')
"""


def candidate_trial(kit, root, expected, auth, benchmark):
    """Run the existing workspace trial against the candidate kit in a fresh interpreter."""
    kit = Path(kit).resolve()
    with tempfile.TemporaryDirectory(prefix='ws-bench-arm4-') as temporary:
        output = Path(temporary) / 'record.json'
        payload = {'kit': str(kit), 'harness': str(benchmark.run.HERE), 'root': str(root),
                   'expected': expected, 'auth': str(auth), 'output': str(output)}
        env = dict(os.environ, PYTHONPATH=str(kit), PYTHONDONTWRITEBYTECODE='1')
        try:
            process = subprocess.run([sys.executable, '-c', _CANDIDATE_SCRIPT], cwd=kit, env=env,
                                     input=json.dumps(payload), capture_output=True, text=True, timeout=1900)
            if process.returncode or not output.is_file():
                raise RuntimeError('Candidate arm failed before saving a trial.')
            record = json.loads(output.read_text(encoding='utf-8'))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise RuntimeError('Candidate arm could not save a valid trial.') from None
        if not isinstance(record, dict) or record.get('arm') != 'workspace':
            raise RuntimeError('Candidate arm returned an invalid trial.')
        record['arm'] = 'verbatim'
        return record


def run_trials(benchmark, args, auth):
    base_seed = args.seed if args.seed is not None else random.SystemRandom().getrandbits(64)
    claude = os.environ.get('WS_BENCH_PROVIDER') == 'claude'
    result = {'model': 'sonnet' if claude else 'gpt-6-luna', 'effort': 'default' if claude else 'high', 'seed': None, 'n': args.n,
              'kit': benchmark.run.command(['git', 'rev-parse', 'HEAD'], benchmark.run.KIT).stdout.strip(), 'runs': []}
    candidate = getattr(args, 'verbatim_kit', None)
    if candidate:
        result['kit_dirty'] = bool(benchmark.run.command(['git', 'status', '--porcelain'], benchmark.run.KIT).stdout.strip())
        result['verbatim_kit'] = benchmark.run.command(['git', 'rev-parse', 'HEAD'], candidate).stdout.strip()
        result['verbatim_kit_dirty'] = bool(benchmark.run.command(['git', 'status', '--porcelain'], candidate).stdout.strip())
        if result['verbatim_kit_dirty']:
            raise RuntimeError('The candidate checkout must be clean to identify the tested code.')
    arms = ('baseline', 'workspace', 'markdown', 'verbatim') if candidate else ('baseline', 'workspace', 'markdown')
    failures = 0
    with tempfile.TemporaryDirectory(prefix='ws-rollout-') as d:
        for number in range(args.n):
            expected = benchmark.seed(base_seed + number)
            for arm in arms:
                root = Path(d) / (str(number) + '-' + arm)
                if arm == 'verbatim':
                    record = None
                    try:
                        before = benchmark.run.command(['git', 'rev-parse', 'HEAD'], candidate).stdout.strip()
                        dirty = benchmark.run.command(['git', 'status', '--porcelain'], candidate).stdout.strip()
                        if before != result['verbatim_kit'] or dirty:
                            raise RuntimeError('The candidate checkout changed during the benchmark.')
                        record = candidate_trial(candidate, root, expected, auth, benchmark)
                        after = benchmark.run.command(['git', 'rev-parse', 'HEAD'], candidate).stdout.strip()
                        dirty = benchmark.run.command(['git', 'status', '--porcelain'], candidate).stdout.strip()
                        if after != before or dirty:
                            raise RuntimeError('The candidate checkout changed during the benchmark.')
                    except (RuntimeError, OSError, subprocess.SubprocessError):
                        if record is None:
                            record = {'arm': arm, 'calls': [], 'usage_incomplete': True}
                        record.update(seed_index=number, result='inconclusive',
                                      error='candidate arm could not be verified')
                        result['runs'].append(record)
                        result.update(seed=base_seed, stopped='candidate arm could not be verified')
                        save(args.output, result)
                        return False
                else:
                    record = benchmark.trial(root, expected, arm, auth)
                record['seed_index'] = number; result['runs'].append(record)
                # Persist progress without publishing the answer-generating seed during worker runs.
                save(args.output, result); print(json.dumps(record), flush=True)
                failures = transport_failures(record.get('calls', []), failures)
                if failures >= 2:
                    result.update(seed=base_seed, stopped='two consecutive transport failures')
                    save(args.output, result); return False
    result['seed'] = base_seed; save(args.output, result)
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('-n', type=int)
    p.add_argument('--verbatim-kit', type=Path, help='candidate checkout for the fourth handoff arm')
    p.add_argument('--seed', type=int); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--provider', choices=('codex', 'claude'), default='codex', help='claude runs Claude Code sonnet with its saved transcripts kept, as for a real user')
    args = p.parse_args()
    if args.n is None: args.n = 10 if args.verbatim_kit else 5
    if os.name == 'nt' or args.n < 5 or not shutil.which(args.provider): p.error('Needs POSIX process isolation, the selected CLI and n >= 5; no installs or fallback.')
    if args.verbatim_kit:
        args.verbatim_kit = args.verbatim_kit.resolve()
        if not (args.verbatim_kit / 'ws/core.py').is_file():
            p.error('The fourth arm needs a candidate checkout containing ws/core.py.')
    os.environ['WS_BENCH_PROVIDER'] = args.provider
    from bench import rollout
    auth = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'auth.json'
    if not run_trials(rollout, args, auth): raise SystemExit(2)


if __name__ == '__main__': main()
