import json
from pathlib import Path

from test_ws import Base
from ws import core, discipline
from testutil import run_ws

KIT = Path(__file__).resolve().parents[1]


def claude_failure(command, session='s1', code=1):
    return {'hook_event_name': 'PostToolUseFailure', 'session_id': session, 'tool_name': 'Bash',
            'tool_input': {'command': command}, 'error': f'Exit code {code}\nboom'}


class DisciplineTests(Base):
    def test_third_failure_of_the_same_command_nudges_once(self):
        results = [discipline.hook(self.root, claude_failure('pytest  -x')) for _ in range(4)]
        self.assertEqual(results[:2], [{}, {}])
        out = results[2]['hookSpecificOutput']
        self.assertEqual(out['hookEventName'], 'PostToolUseFailure')
        self.assertIn('failed 3 times', out['additionalContext'])
        self.assertIn('Do not redo=', out['additionalContext'])
        self.assertEqual(results[3], {})

    def test_counts_are_per_command_and_per_session(self):
        for command, session in (('make a', 's1'), ('make b', 's1'), ('make a', 's2'), ('make a', 's1')):
            self.assertEqual(discipline.hook(self.root, claude_failure(command, session)), {})
        self.assertTrue(discipline.hook(self.root, claude_failure('make  a', 's1')))  # whitespace-insensitive

    def test_command_text_is_not_stored(self):
        for _ in range(3): discipline.hook(self.root, claude_failure('deploy --token-file secret.txt'))
        stored = ''.join(p.read_text() for p in (self.root / '.ws/discipline').iterdir())
        self.assertNotIn('deploy', stored)

    def test_codex_post_tool_use_reads_the_exit_code(self):
        payload = lambda response: {'hook_event_name': 'PostToolUse', 'session_id': 'c', 'tool_name': 'Bash',
                                    'tool_input': {'command': ['bash', '-lc', 'npm test']}, 'tool_response': response}
        for response in ('Exit code: 0\nok', {'exit_code': 0}): self.assertFalse(discipline.failed(payload(response)))
        for response in ('Exit code: 2\nfail', {'exit_code': 1}): self.assertTrue(discipline.failed(payload(response)))
        results = [discipline.hook(self.root, payload('Process exited with code 1')) for _ in range(3)]
        self.assertEqual(results[2]['hookSpecificOutput']['hookEventName'], 'PostToolUse')

    def test_codex_same_command_same_response_three_times_nudges_once(self):
        payload = lambda command, text: {'hook_event_name': 'PostToolUse', 'session_id': 'c', 'tool_name': 'Bash',
                                         'tool_input': {'command': command}, 'tool_response': text}
        results = [discipline.hook(self.root, payload('npm test', 'FAIL a.test\n' + '\n' * i)) for i in range(4)]  # trailing whitespace is ignored
        self.assertEqual(results[:2], [{}, {}])
        out = results[2]['hookSpecificOutput']
        self.assertEqual(out['hookEventName'], 'PostToolUse')
        self.assertIn('returned the same result 3 times', out['additionalContext'])
        self.assertIn('Do not redo=', out['additionalContext'])
        self.assertEqual(results[3], {})
        for text in ('one', 'two', 'three'): self.assertEqual(discipline.hook(self.root, payload('npm run x', text)), {})  # different results
        stored = ''.join(p.read_text() for p in (self.root / '.ws/discipline').iterdir())
        self.assertNotIn('FAIL', stored)

    def test_quoted_arguments_that_differ_only_in_spaces_are_distinct(self):
        for command in ('grep "a b" f', 'grep "a  b" f', 'grep "a   b" f'):
            self.assertEqual(discipline.hook(self.root, claude_failure(command)), {})
            self.assertEqual(discipline.hook(self.root, claude_failure(command)), {})
        self.assertTrue(discipline.hook(self.root, claude_failure('grep "a b" f')))
        self.assertEqual(discipline.hook(self.root, claude_failure('grep "unterminated')), {})  # shlex fails: raw fallback, no crash

    def test_tolerant_shell_tool_names(self):
        for name in ('shell', 'exec_command'):
            payload = {'hook_event_name': 'PostToolUse', 'session_id': name, 'tool_name': name,
                       'tool_input': {'command': 'make'}, 'tool_response': {'exit_code': 1}}
            results = [discipline.hook(self.root, payload) for _ in range(3)]
            self.assertIn('failed 3 times', results[2]['hookSpecificOutput']['additionalContext'])

    def test_success_other_tools_and_bad_input_are_ignored(self):
        self.assertFalse(discipline.failed(claude_failure('x', code=0)))
        self.assertEqual(discipline.hook(self.root, {**claude_failure('x'), 'tool_name': 'Edit'}), {})
        self.assertEqual(discipline.hook(self.root, {**claude_failure('x'), 'tool_input': 'nope'}), {})

    def test_hooks_only_with_the_pack_and_cli_fails_open(self):
        self.assertEqual(core.pack_hooks(self.root, 'claude'), {})
        core.pack_add(self.root, 'discipline')
        self.assertEqual(list(core.pack_hooks(self.root, 'claude')), ['PostToolUseFailure'])
        self.assertEqual(list(core.pack_hooks(self.root, 'codex')), ['PostToolUse'])
        run = lambda data: json.loads(run_ws('--workspace-root', self.root, 'discipline', '--hook', input=data).stdout)
        self.assertEqual(run('not json'), {})
        for _ in range(2): run(json.dumps(claude_failure('cargo test')))
        self.assertIn('additionalContext', run(json.dumps(claude_failure('cargo test')))['hookSpecificOutput'])

    def test_codex_silent_repeats_do_not_nudge(self):
        payload = {'hook_event_name': 'PostToolUse', 'session_id': 'q', 'tool_name': 'Bash', 'tool_input': {'command': 'git add -A'}, 'tool_response': '  '}
        self.assertEqual([discipline.hook(self.root, payload) for _ in range(4)], [{}] * 4)

    def test_explicit_success_status_repeats_do_not_nudge(self):
        payload = lambda response: {'hook_event_name': 'PostToolUse', 'session_id': 'e', 'tool_name': 'Bash', 'tool_input': {'command': 'git status'}, 'tool_response': response}
        for response in ({'exit_code': 0, 'stdout': 'clean'}, 'Exit code: 0\nclean'):
            self.assertEqual([discipline.hook(self.root, payload(response)) for _ in range(4)], [{}] * 4)
