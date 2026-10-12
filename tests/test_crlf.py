import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ws import core  # noqa: E402


def crlf(path):
    """Rewrite a file the way a Windows editor would: CRLF only."""
    path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))


class CrlfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'w'
        core.init(self.root, 'demo')
        core.task_new(self.root, 'T-1', 'Fix crash', 'Crash on empty email')
        self.path = core.task_path(self.root, 'T-1')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Reproduce the crash.')
        crlf(self.path)
        self.assertIn(b'\r\n', self.path.read_bytes())

    def test_list_next_and_brief_see_crlf_task(self):
        t = core.task_list(self.root)[0]
        self.assertEqual((t['id'], t['status'], t['next']), ('T-1', 'in_progress', 'Reproduce the crash.'))
        self.assertEqual([r['id'] for r in core.task_next(self.root)['ready']], ['T-1'])
        self.assertIn('Reproduce the crash.', core.brief(self.root))

    def test_read_sections_and_meta(self):
        r = core.task_read(self.root, 'T-1', ['Objective', 'Next action'])
        self.assertEqual(r['meta']['status'], 'in_progress')
        self.assertEqual(r['sections']['Next action'], 'Reproduce the crash.')
        self.assertEqual(r['sections']['Objective'], 'Crash on empty email')
        self.assertNotIn('\r', core.task_read(self.root, 'T-1')['text'])

    def test_claim_and_checkpoint_keep_meta_and_one_ending(self):
        core.claim(self.root, 'T-1', 'w1')
        crlf(self.path)  # editor re-saves after the claim
        self.assertEqual(core.task_list(self.root)[0]['claimed_by'], 'w1')
        core.release(self.root, 'T-1', 'w1', core.parse_meta(self.path.read_text())['claim_token'])
        crlf(self.path)
        core.checkpoint(self.root, 'T-1', 'review', 'Ask for review.')
        data = self.path.read_bytes()
        self.assertEqual(data.count(b'\r\n'), 0)  # rewritten as LF, not mixed
        meta = core.parse_meta(data.decode())
        self.assertEqual((meta['status'], meta['id']), ('review', 'T-1'))
        self.assertIn(b'Crash on empty email', data)
        self.assertEqual(core.task_list(self.root)[0]['status'], 'review')

    def test_lesson_search_on_crlf_learnings(self):
        core.lesson_add(self.root, 'Empty email crashed the login form; validate before submit.')
        crlf(core.vault(self.root) / 'Learnings.md')
        hits = core.lesson_search(self.root, 'login')
        self.assertEqual(len(hits), 1)
        self.assertNotIn('\r', hits[0])
        self.assertTrue(core.search(self.root, 'login'))


if __name__ == '__main__':
    unittest.main()
