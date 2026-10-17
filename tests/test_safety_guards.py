import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ws import cli, core  # noqa: E402
from testutil import isolate_home, rmtree_owned  # noqa: E402


class SafetyGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(rmtree_owned, self.tmp.name, self.tmp.name)
        self.home = isolate_home(self, self.tmp.name)
        self.base = Path(self.tmp.name).resolve()

    def test_init_refuses_home_root_and_temp_but_not_subfolders(self):
        temp = self.base / 'fake-tmp'
        temp.mkdir()
        fs_root = Path(self.base.anchor)
        with mock.patch('tempfile.gettempdir', return_value=str(temp)), mock.patch('pathlib.Path.home', return_value=self.home):
            for target in (self.home, temp, fs_root):
                with self.subTest(target=str(target)), mock.patch.object(core.Path, 'mkdir') as mk:
                    with self.assertRaisesRegex(core.WsError, 'ws init ~/work/.*ws start'):
                        core.init(target, 'x')
                    mk.assert_not_called()
            core.init(temp / 'sub', 'x')
            core.init(self.home / 'work' / 'ws', 'x')
            self.assertTrue((temp / 'sub' / 'workspace.json').is_file())

    def test_unknown_task_errors_for_trace_and_run_report(self):
        root = self.base / 'ws'
        core.init(root, 'x')
        with self.assertRaisesRegex(core.WsError, 'No task NOPE-1'):
            core.trace(root, 'NOPE-1')
        with self.assertRaisesRegex(core.WsError, 'No task NOPE-1'):
            core.run_report(root, 'NOPE-1')
        core.task_new(root, 'A-1', 'T')
        self.assertIn('Trace: A-1', core.trace(root, 'A-1'))
        self.assertEqual(core.run_report(root, 'A-1')['steps'], 0)

    def test_task_show_unknown_section_lists_valid_names(self):
        root = self.base / 'ws'
        core.init(root, 'x')
        core.task_new(root, 'A-1', 'T')
        with mock.patch.object(cli.core, 'find_root', return_value=root), mock.patch('sys.stderr', new_callable=io.StringIO) as err:
            self.assertEqual(cli.main(['task', 'show', 'A-1', '--section', 'Nosuch']), 2)
            self.assertRegex(err.getvalue(), 'Unknown section Nosuch.*Objective.*Handoff')
            with mock.patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(cli.main(['task', 'show', 'A-1', '--section', 'Objective']), 0)

if __name__ == '__main__':
    unittest.main()
