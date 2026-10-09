import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ws import core  # noqa: E402

FIX = ROOT / 'tests/fixtures/ready_work'


class ReadyWorkBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'ws'
        core.init(self.root, 'ready')
        self.addCleanup(self.tmp.cleanup)

    def new(self, *ids, status=None):
        for i in ids:
            core.task_new(self.root, i, f'Title {i}')
            if status:
                p = core.task_path(self.root, i)
                p.write_bytes(core.set_meta(p.read_text(), {'status': status}).encode())  # LF on Windows too

    def status(self, i):
        return core.parse_meta(core.task_path(self.root, i).read_text())['status']


class DependTests(ReadyWorkBase):
    def test_depend_records_and_is_idempotent(self):
        self.new('A-1', 'A-2', 'A-3')
        core.task_depend(self.root, 'A-3', 'A-1')
        res = core.task_depend(self.root, 'A-3', 'A-2')
        core.task_depend(self.root, 'A-3', 'A-2')
        self.assertEqual(res['depends_on'], ['A-1', 'A-2'])
        meta = core.parse_meta(core.task_path(self.root, 'A-3').read_text())
        self.assertEqual(meta['depends_on'], 'A-1, A-2')

    def test_rejects_missing_self_and_cycles(self):
        self.new('A-1', 'A-2', 'A-3')
        with self.assertRaisesRegex(core.WsError, 'No task NOPE'):
            core.task_depend(self.root, 'A-1', 'NOPE')
        with self.assertRaisesRegex(core.WsError, 'No task NOPE'):
            core.task_depend(self.root, 'NOPE', 'A-1')
        with self.assertRaisesRegex(core.WsError, 'itself'):
            core.task_depend(self.root, 'A-1', 'A-1')
        core.task_depend(self.root, 'A-2', 'A-1')
        core.task_depend(self.root, 'A-3', 'A-2')
        with self.assertRaisesRegex(core.WsError, 'cycle'):
            core.task_depend(self.root, 'A-1', 'A-3')
        with self.assertRaisesRegex(core.WsError, 'cycle'):
            core.task_depend(self.root, 'A-1', 'A-2')
        self.assertEqual(core.task_list(self.root)[0]['depends_on'], [])  # failed attempts wrote nothing


class NextTests(ReadyWorkBase):
    def test_order_filtering_and_unblocks(self):
        self.new('B-done', status='done')
        self.new('B-prog', status='in_progress')
        self.new('B-ready', status='ready')
        self.new('B-back', status='backlog')
        self.new('B-blocked', status='blocked')
        self.new('B-wait', status='ready')
        self.new('B-after', status='ready')
        core.task_depend(self.root, 'B-ready', 'B-done')
        core.task_depend(self.root, 'B-wait', 'B-prog')
        core.task_depend(self.root, 'B-after', 'B-prog')
        res = core.task_next(self.root)
        self.assertEqual([t['id'] for t in res['ready']], ['B-prog', 'B-ready', 'B-back'])
        self.assertEqual(res['ready'][0]['unblocks'], ['B-after', 'B-wait'])
        self.assertEqual(res['waiting'], 2)

    def test_missing_dependency_counts_as_waiting(self):
        self.new('C-1')
        p = core.task_path(self.root, 'C-1')
        p.write_bytes(core.set_meta(p.read_text(), {'depends_on': 'GONE-1'}).encode())
        self.assertEqual(core.task_next(self.root), {'ready': [], 'waiting': 1})

    def test_cli_next_text_line(self):
        self.new('D-1', 'D-2', status='ready')
        core.task_depend(self.root, 'D-2', 'D-1')
        env = dict(os.environ, WS_ROOT=str(self.root))
        run = subprocess.run([sys.executable, str(ROOT / 'bin/ws'), 'next'], env=env, text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.strip().splitlines(),
                         ['D-1 ready Title D-1 (unblocks: D-2)', '1 waiting on dependencies'])


class ImportTests(ReadyWorkBase):
    def test_task_master_preview_then_write(self):
        preview = core.task_import(self.root, FIX / 'taskmaster.json', 'TM')
        self.assertTrue(preview['preview'])
        self.assertEqual(preview['create'], ['TM-1', 'TM-2', 'TM-3'])
        self.assertEqual(preview['ignored_lines_or_subtasks'], 1)  # the one subtask
        self.assertEqual(core.task_list(self.root), [])  # preview wrote nothing
        core.task_import(self.root, FIX / 'taskmaster.json', 'TM', write=True)
        self.assertEqual([self.status(i) for i in ('TM-1', 'TM-2', 'TM-3')], ['done', 'in_progress', 'ready'])
        meta = core.parse_meta(core.task_path(self.root, 'TM-3').read_text())
        self.assertEqual(meta['depends_on'], 'TM-1, TM-2')
        self.assertIn('Front end.', core.task_read(self.root, 'TM-3')['text'])
        self.assertEqual([t['id'] for t in core.task_next(self.root)['ready']], ['TM-2'])

    def test_task_master_tagged_master(self):
        res = core.task_import(self.root, FIX / 'taskmaster-tagged.json', 'X', write=True)
        self.assertEqual(res['create'], ['X-1'])

    def test_spec_kit_markdown(self):
        res = core.task_import(self.root, FIX / 'speckit-tasks.md', 'SK', write=True)
        self.assertEqual(res['create'], ['SK-T001', 'SK-T002', 'SK-T003', 'SK-T004', 'SK-T005'])
        self.assertEqual(res['ignored_lines_or_subtasks'], 1)  # checkbox line with no ID
        self.assertEqual(self.status('SK-T001'), 'done')
        self.assertEqual(self.status('SK-T002'), 'ready')
        tasks = {t['id']: t for t in core.task_list(self.root)}
        self.assertEqual(tasks['SK-T004']['depends_on'], ['SK-T001', 'SK-T002'])
        self.assertEqual(tasks['SK-T005']['depends_on'], ['SK-T003', 'SK-T004'])
        self.assertEqual(tasks['SK-T003']['title'], 'Contract test in tests/contract/test_albums.py')
        self.assertEqual([t['id'] for t in core.task_next(self.root)['ready']], ['SK-T002', 'SK-T003'])

    def test_skips_existing_and_never_overwrites(self):
        core.task_new(self.root, 'TM-1', 'My own task', objective='keep me')
        before = core.task_read(self.root, 'TM-1')['text']
        res = core.task_import(self.root, FIX / 'taskmaster.json', 'TM', write=True)
        self.assertEqual(res['skipped_existing'], ['TM-1'])
        self.assertEqual(res['create'], ['TM-2', 'TM-3'])
        self.assertEqual(core.task_read(self.root, 'TM-1')['text'], before)
        self.assertEqual(core.parse_meta(core.task_path(self.root, 'TM-2').read_text())['depends_on'], 'TM-1')

    def test_cycle_and_missing_dependency_block_write(self):
        for name, word in (('taskmaster-cycle.json', 'cycle'), ('taskmaster-missing.json', 'unknown task 9')):
            preview = core.task_import(self.root, FIX / name, 'E')
            self.assertTrue(any(word in e for e in preview['errors']), preview)
            with self.assertRaisesRegex(core.WsError, word):
                core.task_import(self.root, FIX / name, 'E', write=True)
        self.assertEqual(core.task_list(self.root), [])

    def test_bad_prefix_and_input(self):
        with self.assertRaises(core.WsError):
            core.task_import(self.root, FIX / 'taskmaster.json', 'bad prefix!')
        bad = Path(self.tmp.name) / 'bad.json'
        bad.write_text('{"nope": 1}')
        with self.assertRaisesRegex(core.WsError, 'tasks.json'):
            core.task_import(self.root, bad)

    def test_cli_preview_default_and_yes(self):
        env = dict(os.environ, WS_ROOT=str(self.root))
        def run(*a): return subprocess.run([sys.executable, str(ROOT / 'bin/ws'), 'task', 'import', *a], env=env, text=True, capture_output=True)
        pre = run(str(FIX / 'speckit-tasks.md'), '--prefix', 'SK')
        self.assertEqual(pre.returncode, 0, pre.stderr)
        self.assertTrue(json.loads(pre.stdout)['preview'])
        self.assertEqual(core.task_list(self.root), [])
        done = run(str(FIX / 'speckit-tasks.md'), '--prefix', 'SK', '--yes')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(core.task_list(self.root)), 5)
        self.assertEqual(run(str(FIX / 'taskmaster-cycle.json')).returncode, 1)


if __name__ == '__main__':
    unittest.main()
