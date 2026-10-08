"""Run the corrected-rollout benchmark (POSIX, explicitly authorized model calls)."""
import argparse
import json
import os
import random
import shutil
import tempfile
from pathlib import Path
from ws import core


def save(output, result):
    core.atomic_write(output, '{\n' + ',\n'.join(json.dumps(k) + ': ' + json.dumps(v) for k, v in result.items() if k != 'runs') +
                      ',\n"runs": [\n' + ',\n'.join(map(json.dumps, result['runs'])) + '\n]}\n')


def run_trials(benchmark, args, auth):
    base_seed = args.seed if args.seed is not None else random.SystemRandom().getrandbits(64)
    result = {'model': 'gpt-6-luna', 'effort': 'high', 'seed': None, 'n': args.n,
              'kit': benchmark.run.command(['git', 'rev-parse', 'HEAD'], benchmark.run.KIT).stdout.strip(), 'runs': []}
    with tempfile.TemporaryDirectory(prefix='ws-rollout-') as d:
        for number in range(args.n):
            expected = benchmark.seed(base_seed + number)
            for arm in ('baseline', 'workspace', 'markdown'):
                record = benchmark.trial(Path(d) / (str(number) + '-' + arm), expected, arm, auth)
                record['seed_index'] = number; result['runs'].append(record)
                # Persist progress without publishing the answer-generating seed during worker runs.
                save(args.output, result); print(json.dumps(record), flush=True)
    result['seed'] = base_seed; save(args.output, result)


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('-n', type=int, default=5)
    p.add_argument('--seed', type=int); p.add_argument('--output', type=Path, required=True); args = p.parse_args()
    if os.name == 'nt' or args.n < 5 or not shutil.which('codex'): p.error('Needs POSIX FIFO, installed Codex and n >= 5; no installs or fallback.')
    from bench import rollout
    auth = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'auth.json'
    run_trials(rollout, args, auth)


if __name__ == '__main__': main()
