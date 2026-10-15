import os
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ws import cli, core
from testutil import isolate_home


ROOT = Path(__file__).resolve().parents[1]


class DemoTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'the demo is a POSIX shell script')
    def test_demo_runs_without_model_calls_and_shows_the_daily_loop(self):
        result = subprocess.run([str(ROOT / 'scripts/demo.sh')], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ('ws init ', 'ws connect claude', 'ws task new ', 'ws claim ',
                        'ws checkpoint ', 'ws brief', 'ws delegate '):
            self.assertIn('$ ' + command, result.stdout)
        self.assertIn("--token '<claim-token>'", result.stdout)
        self.assertIn('delegate was prepared; no model was called', result.stdout)


class CommandDemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = isolate_home(self, self.tmp.name)

    def test_fresh_process_remembers_without_clients_network_or_existing_workspace_writes(self):
        guard = Path(self.tmp.name) / 'network-guard'
        guard.mkdir()
        (guard / 'sitecustomize.py').write_text(
            'import socket\n'
            'def deny(*args, **kwargs): raise AssertionError("demo network denied")\n'
            'socket.socket.connect = deny\nsocket.socket.connect_ex = deny\n'
            'socket.getaddrinfo = deny\n', encoding='utf-8')
        env = dict(os.environ, PYTHONPATH=str(guard))
        control = subprocess.run([sys.executable, '-B', '-c',
                                  'import socket; socket.create_connection(("localhost", 9))'],
                                 env=env, text=True, capture_output=True)
        self.assertNotEqual(control.returncode, 0)
        self.assertIn('demo network denied', control.stderr)
        sentinel = self.home / 'workspace.json'
        sentinel.write_text('leave this alone', encoding='utf-8')
        before = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        output = io.StringIO()
        with mock.patch.dict(os.environ, WS_ROOT=str(self.home), PYTHONPATH=str(guard)), \
                mock.patch.object(core, 'connect', side_effect=AssertionError('connect')), \
                mock.patch.object(core, 'brief', return_value='PARENT-ONLY-BRIEF'), \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('network')), \
                mock.patch('subprocess.run', wraps=subprocess.run) as child, \
                contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(['demo']), 0)
        self.assertEqual(child.call_count, 1)
        self.assertIn('brief', child.call_args.args[0])
        self.assertIn('Store totals as integer cents.', output.getvalue())
        self.assertIn('Fresh process', output.getvalue())
        self.assertNotIn('PARENT-ONLY-BRIEF', output.getvalue())
        self.assertIn('removed', output.getvalue())
        after = {p.relative_to(self.home): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse(Path(child.call_args.kwargs['cwd']).exists())

    def test_failed_demo_removes_its_workspace(self):
        roots = []
        original = core.init
        def initialize(root, *args, **kwargs):
            roots.append(Path(root))
            return original(root, *args, **kwargs)
        with mock.patch.object(core, 'init', side_effect=initialize), \
                mock.patch.object(core, 'remember', side_effect=core.WsError('synthetic failure')), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['demo']), 2)
        self.assertEqual(len(roots), 1)
        self.assertFalse(roots[0].exists())

    def test_explicit_workspace_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--workspace-root', str(self.home), 'demo']), 2)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_brief_timeout_is_an_error_and_cleans_up(self):
        with mock.patch('subprocess.run', side_effect=subprocess.TimeoutExpired('brief', 20)) as child, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['demo']), 2)
        self.assertFalse(Path(child.call_args.kwargs['cwd']).exists())


if __name__ == '__main__':
    unittest.main()
