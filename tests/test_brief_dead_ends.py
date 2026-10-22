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

    def test_items_are_kept_whole_and_the_rest_are_counted(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Fix the upload.', notes={
            'Do not redo': 'Never retry the upload in a loop; the API rate-limits after 3 calls.',
            'Failures': 'Multipart upload failed: the server rejects it with 415 and a long explanation about content types.'})
        brief = core.brief(self.root)
        self.assertIn('Never retry the upload in a loop; the API rate-limits after 3 calls.', brief)
        self.assertIn('(+1 more in the task', brief)
        self.assertNotIn('[…]', brief.split('Do not redo:')[1].split('\n')[0])

    def test_an_over_budget_first_item_is_pointed_to_not_cut(self):
        long_item = 'Rewriting the uploader as a streaming client ' + 'with extra retry and backoff layers ' * 7 + 'failed: it deadlocks.'
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Fix the upload.', notes={'Do not redo': long_item + '\n- Short one: fails too'})
        line = core.brief(self.root).split('Do not redo:')[1].split('\n')[0]
        self.assertNotIn('[…]', line)
        self.assertNotIn('streaming client', line)
        self.assertTrue(line.strip().startswith('Short one: fails too (+1 more in the task'), line)
        core.task_new(self.root, 'T-2', 'Other upload', 'Synthetic')  # dead ends accumulate, so a lone item needs a fresh task
        core.checkpoint(self.root, 'T-2', 'in_progress', 'Fix the upload.', notes={'Do not redo': long_item, 'Failures': ''})
        line = core.brief(self.root, 'T-2').split('Do not redo:')[1].split('\n')[0]
        self.assertIn("1 saved; read the task's Do not redo/Failures before retrying", line)
