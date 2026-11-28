import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ws import core
from testutil import isolate_home, rmtree_owned


class FixStatusTests(unittest.TestCase):
    """OFF-1: imported vaults use other status spellings; validate names the fix and fix-status renames them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(rmtree_owned, self.tmp.name, self.tmp.name)
        isolate_home(self, self.tmp.name)
        self.root = Path(self.tmp.name) / 'workspace'
        core.init(self.root, 'fixture')

    def task(self, task_id, status):
        core.task_new(self.root, task_id, task_id)
        path = core.task_path(self.root, task_id)
        path.write_text(core.set_meta(path.read_text(), {'status': status}), encoding='utf-8')
        return path

    def test_validate_names_the_standard_status(self):
        self.task('A', 'complete'); self.task('B', 'weird')
        errors = '\n'.join(core.validate(self.root)['errors'])
        self.assertIn('use done (`ws task fix-status` previews the rename)', errors)
        self.assertRegex(errors, r'B\.md: status must be one of [^\n]*done\n|B\.md: status must be one of [^\n]*done$')

    def test_preview_changes_nothing_and_apply_renames_with_old_status(self):
        paths = {s: self.task(f'T-{i}', s) for i, s in enumerate(['in-progress', 'Complete', 'queued', 'waiting', 'diagnosed', 'mystery'])}
        before = {s: p.read_bytes() for s, p in paths.items()}
        preview = core.task_fix_status(self.root)
        self.assertFalse(preview['applied'])
        self.assertEqual(preview['next'], 'ws task fix-status --yes')
        self.assertEqual({r['from']: r['to'] for r in preview['renames']},
                         {'in-progress': 'in_progress', 'Complete': 'done', 'queued': 'ready', 'waiting': 'blocked', 'diagnosed': 'review'})
        self.assertEqual(preview['unknown'], [{'task': 'T-5', 'status': 'mystery'}])
        self.assertEqual({s: p.read_bytes() for s, p in paths.items()}, before)
        done = core.task_fix_status(self.root, apply=True)
        self.assertTrue(done['applied'])
        meta = core.parse_meta(paths['Complete'].read_text())
        self.assertEqual((meta['status'], meta['old_status']), ('done', 'Complete'))
        self.assertEqual(paths['mystery'].read_bytes(), before['mystery'])
        self.assertEqual(core.task_fix_status(self.root)['renames'], [])

    def test_renamed_complete_task_is_not_claimable(self):
        self.task('OLD', 'complete'); self.task('NEW', 'ready')
        core.task_fix_status(self.root, apply=True)
        statuses = {t['id']: t['status'] for t in core.task_list(self.root)}
        self.assertEqual(statuses['OLD'], 'done')
        self.assertEqual(core.claim_next(self.root, 'w1')['task'], 'NEW')


if __name__ == '__main__':
    unittest.main()
