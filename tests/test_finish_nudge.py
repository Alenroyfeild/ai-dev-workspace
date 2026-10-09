import json
import subprocess
import sys
from test_ws import Base, KIT
from ws import cli, core


def use(name, **data):
    return {'type': 'tool_use', 'name': name, 'input': data}


class FinishNudgeTests(Base):
    def stop(self, uses, **payload):
        path = self.root / 'session.jsonl'
        path.write_text(json.dumps({'type': 'assistant', 'message': {'content': uses}}) + '\n')
        proc = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'nudge', '--hook'], cwd=self.root, capture_output=True, text=True,
                              input=json.dumps(dict(hook_event_name='Stop', transcript_path=str(path), **payload)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_edits_without_task_update_ask_once_for_a_checkpoint(self):
        core.claim(self.root, 'T-1', 'synthetic')
        reply = self.stop([use('Read', file_path='a.py'), use('Edit', file_path='a.py')])
        self.assertEqual(reply['decision'], 'block')
        self.assertIn('ws checkpoint T-1', reply['reason'])
        self.assertEqual(self.stop([use('Edit', file_path='a.py')], stop_hook_active=True), {})

    def test_recorded_unrelated_or_read_only_sessions_are_left_alone(self):
        self.assertEqual(self.stop([use('Edit', file_path='a.py')]), {})  # no local claim: nothing to update
        core.claim(self.root, 'T-1', 'synthetic')
        for uses in ([use('Read', file_path='a.py')],
                     [use('Edit'), use('mcp__ai-dev-workspace__checkpoint', task='T-1')],
                     [use('Write'), use('Bash', command='ws checkpoint T-1 --status done --next "Nothing."')],
                     [use('Edit'), use('Skill', skill='handoff')]):
            with self.subTest(uses=[u['name'] for u in uses]):
                self.assertEqual(cli.unrecorded_work(self.root, uses), '')

    def test_several_local_claims_are_ambiguous(self):
        core.task_new(self.root, 'T-2', 'Second synthetic task')
        core.claim(self.root, 'T-1', 'synthetic'); core.claim(self.root, 'T-2', 'synthetic')
        self.assertEqual(cli.unrecorded_work(self.root, [use('Edit')]), '')
