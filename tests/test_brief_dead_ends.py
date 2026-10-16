from test_ws import Base
from mcp import server
from ws import core


class DeadEndTests(Base):
    def test_do_not_redo_and_failures_reach_the_brief(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Fix the upload.', notes={
            'Do not redo': '- Retrying the upload in a loop: the API rate-limits after 3 calls',
            'Failures': 'Switching to multipart: the server rejects it'})
        brief = core.brief(self.root)
        self.assertIn('Do not redo:', brief)
        self.assertIn('Retrying the upload in a loop: the API rate-limits after 3 calls', brief)
        self.assertIn('Switching to multipart: the server rejects it', brief)

    def test_empty_template_and_captured_text_add_nothing(self):
        self.assertNotIn('Do not redo:', core.brief(self.root))
        core.checkpoint(self.root, 'T-1', 'in_progress', 'x', notes={
            'Do not redo': '<!-- ws:captured:2026-10-16 -->\nguessed dead end\n<!-- /ws:captured -->'})
        brief = core.brief(self.root)
        self.assertNotIn('guessed dead end', brief)
        self.assertNotIn('Do not redo:', brief)

    def test_long_dead_ends_stay_within_the_brief_budget(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Fix the upload.', notes={'Do not redo': 'tried approach number ' * 60})
        brief = core.brief(self.root)
        self.assertIn('Do not redo:', brief)
        self.assertLess(len(brief.split()), 200)
        self.assertIn('Fix the upload.', brief)

    def test_mcp_checkpoint_can_save_a_dead_end(self):
        core.claim(self.root, 'T-1', 'synthetic')
        args = {'id': 'T-1', 'status': 'in_progress', 'next': 'Fix the upload.',
                'notes': {'Do not redo': 'Polling every second: it trips the rate limit'}}
        reply = server.handle(self.root, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'checkpoint', 'arguments': args}})
        self.assertFalse(reply['result']['isError'], reply)
        self.assertIn('Polling every second', core.brief(self.root))
