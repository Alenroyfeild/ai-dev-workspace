"""Shared setup for the opt-in, stub-model-tested examples; no hosted inference."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('workspace', type=Path)
parser.add_argument('phase', choices=('write', 'resume'))
parser.add_argument('--decision')
args = parser.parse_args()
if (args.phase == 'write') != bool(args.decision):
    parser.error('write requires --decision; resume must not receive one')
ROOT = args.workspace.resolve()
if not (ROOT / 'workspace.json').is_file():
    parser.error('initialize a disposable workspace and MEM-1 task first')
PHASE = args.phase
TOOLS = ['find_task', 'brief', 'checkpoint', 'add_lesson']
PLAN = [('find_task', {'ref': 'MEM-1'}), ('brief', {})]
if PHASE == 'write':
    PLAN += [('checkpoint', {'id': 'MEM-1', 'status': 'in_progress', 'next': args.decision,
                            'notes': {'Handoff': args.decision}}),
             ('add_lesson', {'text': 'Verify the saved rollback marker before retrying the migration.'})]

def deny_network(event, values):
    if event == 'socket.connect' and values[0].family in (socket.AF_INET, socket.AF_INET6):
        raise RuntimeError('Network disabled in stub examples')
sys.addaudithook(deny_network)

def connection():
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'SYSTEMROOT', 'WINDIR', 'TMP', 'TEMP', 'TMPDIR', 'LANG', 'LC_ALL') if k in os.environ}
    env['WS_OFFLINE'] = '1'
    server = Path(__file__).resolve().parents[3] / 'mcp/server.py'
    return {'command': sys.executable, 'args': [str(server), '--root', str(ROOT)], 'env': env}

def emit(framework, results, final):
    assert len(results) == len(PLAN), (results, PLAN)
    print(json.dumps({'framework': framework, 'phase': PHASE, 'results': results, 'final': final}))
