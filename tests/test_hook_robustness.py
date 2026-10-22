"""Hook entry points (brief/nudge/paste/guard/discipline --hook) fail open on malformed input: exit 0, JSON or empty stdout, no traceback."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from test_ws import Base
from ws import cli

CLI = Path(__file__).resolve().parents[1] / 'bin/ws'
BAD_STDIN = {'empty': b'', 'whitespace': b' \n\t', 'invalid json': b'{nope', 'array': b'[1]', 'number': b'7', 'string': b'"x"',
             'null': b'null', 'non-utf8': b'\xff\xfe{'}
EVENT = {'brief': 'SessionStart', 'nudge': 'Stop', 'paste': 'UserPromptSubmit', 'guard': 'PreToolUse', 'discipline': 'PostToolUse'}


class HookRobustnessTests(Base):
    def hook(self, cmd, data, client='claude', root=True):
        if isinstance(data, dict): data = json.dumps(data).encode()
        argv = (['--workspace-root', str(self.root)] if root else []) + [cmd, '--hook', '--client', client]
        stdin = io.TextIOWrapper(io.BytesIO(data), encoding='utf-8', errors='replace')
        stdin.buffer.seek(0)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), unittest.mock.patch.object(sys, 'stdin', stdin):
            try: code = cli.main(argv)
            except Exception as exc: self.fail(f'{cmd}/{client}: {type(exc).__name__}: {exc}')
        return code, out.getvalue(), err.getvalue()

    def assert_open(self, cmd, data, client='claude', label='', root=True):
        code, out, err = self.hook(cmd, data, client, root)
        self.assertEqual(code, 0, f'{cmd}/{client}/{label}: exit {code}: {err}')
        self.assertNotIn('Traceback', err)
        if out.strip() and not (cmd == 'brief' and client == 'claude'): json.loads(out)  # Claude's SessionStart stdout is plain context text
        return out

    def test_malformed_stdin_fails_open_for_every_hook_and_client(self):
        for cmd, clients in (('brief', ('claude', 'codex', 'cursor', 'gemini', 'vscode', 'antigravity')), ('nudge', ('claude', 'codex', 'cursor', 'gemini', 'vscode')),
                             ('paste', ('claude', 'codex', 'cursor', 'gemini')), ('guard', ('claude', 'codex', 'antigravity')), ('discipline', ('claude', 'codex'))):
            for client in clients:
                for label, data in BAD_STDIN.items(): self.assert_open(cmd, data, client, label)

    def test_wrong_typed_fields_fail_open(self):
        for cmd, event in EVENT.items():
            for field in ('cwd', 'session_id', 'transcript_path', 'prompt', 'tool_name', 'tool_input', 'tool_response'):
                for value in (5, [], None, {}):
                    self.assert_open(cmd, {'hook_event_name': event, field: value}, label=f'{field}={value!r}')
        for field in ('file_path', 'content', 'old_string', 'new_string', 'command'):
            for tool in ('Write', 'Edit', 'Bash'):
                self.assert_open('guard', {'hook_event_name': 'PreToolUse', 'tool_name': tool, 'tool_input': {field: 5}}, label=field)

    def test_stop_with_unreadable_transcript_never_blocks_or_crashes(self):
        directory = Path(self.tmp.name)
        for name, body in (('bad.jsonl', b'{"type":"assistant"}\n\xff\xfe\n'), ('shapes.jsonl', b'[1]\n"x"\n{"type":"assistant","message":[]}\n{"type":"assistant","message":null}\n')):
            (directory / name).write_bytes(body)
            for event in ('Stop', 'PreCompact'):
                out = self.assert_open('nudge', {'hook_event_name': event, 'transcript_path': str(directory / name)}, label=name)
                self.assertNotIn('block', out)

    def test_session_start_with_bad_cwd_still_prints_the_brief(self):
        for cwd in (5, [], '/nonexistent/zz', 'relative', '/tmp'):
            out = self.assert_open('brief', {'hook_event_name': 'SessionStart', 'cwd': cwd}, label=repr(cwd))
            self.assertTrue(out.strip(), cwd)

    def test_corrupt_workspace_or_task_fails_open(self):
        (self.root / 'vault/Tasks/T-1.md').write_bytes(b'\x00\xff garbage')
        for cmd, event in EVENT.items(): self.assert_open(cmd, {'hook_event_name': event, 'prompt': 'hi'}, label='corrupt task')
        (self.root / 'workspace.json').write_text('{bad')
        for cmd, event in EVENT.items(): self.assert_open(cmd, {'hook_event_name': event, 'prompt': 'hi'}, label='corrupt workspace.json')

    def test_no_workspace_found_fails_open(self):
        empty = tempfile.mkdtemp(dir=self.tmp.name)
        env = {**os.environ, 'WS_ROOT': ''}
        for cmd, event in EVENT.items():
            proc = subprocess.run([sys.executable, str(CLI), cmd, '--hook'], input=json.dumps({'hook_event_name': event, 'prompt': 'hi'}).encode(),
                                  capture_output=True, cwd=empty, env=env)
            self.assertEqual(proc.returncode, 0, (cmd, proc.stderr))
            self.assertNotIn(b'Traceback', proc.stderr)

    def test_paste_still_blocks_a_large_prompt(self):
        code, _, err = self.hook('paste', {'hook_event_name': 'UserPromptSubmit', 'prompt': 'x\n' * 400})
        self.assertEqual(code, 2); self.assertIn('Prompt saved', err)


if __name__ == '__main__':
    unittest.main()
