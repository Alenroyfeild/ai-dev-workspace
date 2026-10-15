"""A disposable, offline demonstration of a remembered decision."""
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from . import core


@contextmanager
def isolated_environment(values):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def run():
    decision = 'Store totals as integer cents.'
    with tempfile.TemporaryDirectory(prefix='ws-demo-') as directory:
        base = Path(directory)
        root, home = base / 'workspace', base / 'home'
        home.mkdir()
        env = dict(HOME=str(home), USERPROFILE=str(home),
                   CODEX_HOME=str(home / '.codex'), CLAUDE_CONFIG_DIR=str(home / '.claude'),
                   WS_ROOT=str(root), WS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1')
        with isolated_environment(env):
            core.init(root, 'demo', clients=[])
            core.task_new(root, 'DEMO', 'Store payment totals')
            core.claim(root, 'DEMO', 'demo')
            core.checkpoint(root, 'DEMO', 'in_progress', 'Write the storage tests.')
            core.remember(root, decision)
            try:
                result = subprocess.run([sys.executable, '-B', str(core.KIT / 'bin/ws'),
                                         '--workspace-root', str(root), 'brief'],
                                        cwd=base, env=dict(os.environ), capture_output=True, text=True, timeout=20)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise core.WsError('Demo brief process could not finish; retry ws demo.') from exc
            if result.returncode or decision not in result.stdout:
                raise core.WsError('Demo could not read the saved decision in a fresh process.')
            brief = result.stdout.strip()
    return (f'Saved with ws remember: "{decision}"\n\nFresh process — brief read from disk:\n{brief}\n\n'
            'Demo workspace removed. No assistant was started.\n'
            'Try it in your own code repo: ws start')
