import json
import subprocess
import sys

from test_ws import Base, KIT
from ws import core


class VisibleMemoryTests(Base):
    def hook(self, *client):
        run = subprocess.run([sys.executable, str(KIT / 'bin/ws'), '--workspace-root', str(self.root), 'brief', '--hook', *client],
                             input=json.dumps({'hook_event_name': 'SessionStart', 'source': 'startup'}), capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def capture(self, text='Decided: use violet. Never log tokens.'):
        path = self.root / 'chat.jsonl'
        path.write_text(json.dumps({'type': 'user', 'message': {'content': text}}) + '\n' + json.dumps(
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read'}, {'type': 'text', 'text': 'Next step: test it.'}]}}))
        self.assertTrue(core.capture_decisions(self.root, str(path)))

    def test_counts_remembered_and_captured_decisions(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Write the migration')
        core.remember(self.root, 'use Postgres, not SQLite')
        self.assertEqual(core.memory_summary(self.root), 'Remembered: 1 decision · next: Write the migration')
        core.remember(self.root, 'never ship on Friday')
        self.assertEqual(core.memory_summary(self.root), 'Remembered: 2 decisions · next: Write the migration')
        self.capture()
        self.assertEqual(core.memory_summary(self.root), 'Remembered: 4 decisions · next: Write the migration')

    def test_captured_requests_with_decision_verbs_do_not_count_as_decisions(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Test pagination')
        path = core.task_path(self.root, 'T-1')
        handoff = '<!-- ws:captured:fixture -->\n### Captured 2026-10-12 (unverified transcript)\nUser constraints:\n- Please return the invoice list.\n- Please use a table.\nLast assistant summary / next step: I will test pagination.\n<!-- /ws:captured -->'
        path.write_text(core.set_section(path.read_text(), 'Handoff', handoff))
        self.assertEqual(core.memory_summary(self.root), 'Remembered: next: Test pagination')

    def test_empty_memory_says_how_to_save(self):
        core.claim(self.root, 'T-1', 'synthetic')
        self.assertEqual(core.memory_summary(self.root), 'No saved memory yet for T-1 · next: ws remember "<decision>" or /handoff')

    def test_saved_handoff_prose_is_not_empty_memory(self):
        core.claim(self.root, 'T-1', 'synthetic')
        path = core.task_path(self.root, 'T-1')
        path.write_text(core.set_section(path.read_text(), 'Handoff', 'Waiting for the product answer.'))
        self.assertEqual(core.memory_summary(self.root), 'Remembered: saved context')

    def test_saved_blocker_is_not_empty_memory(self):
        core.claim(self.root, 'T-1', 'synthetic')
        path = core.task_path(self.root, 'T-1')
        path.write_text(core.set_section(path.read_text(), 'Blockers', 'Waiting for the product answer.'))
        self.assertEqual(core.memory_summary(self.root), 'Remembered: saved context')

    def test_next_action_alone_and_no_task(self):
        self.assertEqual(core.memory_summary(self.root), '')
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Write the migration')
        self.assertEqual(core.memory_summary(self.root), 'Remembered: next: Write the migration')

    def test_line_is_one_short_line_with_truncated_next_action(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Write the migration\nand then ' + 'verify everything carefully ' * 20)
        core.remember(self.root, 'use Postgres')
        line = core.memory_summary(self.root)
        self.assertLessEqual(len(line), 120)
        self.assertNotIn('\n', line)
        self.assertTrue(line.startswith('Remembered: 1 decision · next: Write the migration and then verify'))
        self.assertTrue(line.endswith('…'))

    def test_claude_and_codex_hooks_show_the_line_and_keep_context(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Write the migration')
        core.remember(self.root, 'use Postgres')
        for client in ((), ('--client', 'codex')):
            data = self.hook(*client)
            self.assertEqual(data['systemMessage'], 'Remembered: 1 decision · next: Write the migration')
            self.assertEqual(data['hookSpecificOutput']['hookEventName'], 'SessionStart')
            self.assertEqual(data['hookSpecificOutput']['additionalContext'], core.brief(self.root))
            self.assertIn('use Postgres', data['hookSpecificOutput']['additionalContext'])

    def test_no_task_keeps_todays_output(self):
        run = subprocess.run([sys.executable, str(KIT / 'bin/ws'), '--workspace-root', str(self.root), 'brief', '--hook'],
                             input='{"hook_event_name":"SessionStart"}', capture_output=True, text=True)
        self.assertEqual(run.stdout.strip(), core.brief(self.root))
        self.assertNotIn('systemMessage', run.stdout)

    def test_cursor_output_is_unchanged(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.remember(self.root, 'use Postgres')
        self.assertEqual(self.hook('--client', 'cursor'), {'additional_context': core.brief(self.root)})
