"""Optional plugin entrypoints; inactive outside a validated ws-started repo."""
import argparse
import io
import json
import os
import sys
from pathlib import Path
from . import core


def workspace(start=None):
    # Plugin processes must not inherit unrelated memory through WS_ROOT.
    base = Path(start or os.getcwd()).resolve()
    for candidate in (base, *base.parents):
        if (candidate / '.ws-start.json').is_file():
            return core.find_root(candidate)
    return None


def main(argv=None):
    from . import cli
    parser = argparse.ArgumentParser()
    parser.add_argument('--client', choices=('claude', 'codex'), required=True)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(cli._read_limited_stdin())
        if not isinstance(payload, dict): raise ValueError('Expected an object')
        cwd = payload.get('cwd')
        if cwd is not None and (not isinstance(cwd, str) or not cwd): raise ValueError('Invalid cwd')
        command = {'SessionStart': 'brief', 'PreCompact': 'nudge', 'Stop': 'nudge',
                   'UserPromptSubmit': 'paste'}.get(payload.get('hook_event_name'))
        root = workspace(cwd) if command else None
    except (core.WsError, OSError, ValueError, TypeError, KeyError):
        root = None
    if root is None:
        print('{}'); return 0
    previous = sys.stdin
    try:
        sys.stdin = io.StringIO(json.dumps(payload))
        return cli.main(['--workspace-root', str(root), command, '--hook', '--client', args.client])
    finally:
        sys.stdin = previous
