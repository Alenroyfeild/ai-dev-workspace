import contextlib
import io
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
from ws import cli, core, upgrade  # noqa: E402
from mcp import server  # noqa: E402


class PasteGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'workspace'
        core.init(self.root, 'synthetic')

    def tearDown(self):
        self.tmp.cleanup()

    def invoke_hook(self, client, payload):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
                mock.patch('sys.stdin', io.StringIO(json.dumps(payload))):
            code = cli.main(['--workspace-root', str(self.root), 'paste', '--hook', '--client', client])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_paste_reads_stdin_redacts_and_prints_only_digest(self):
        raw = 'error: password=' + 'S' * 20 + '\nordinary context\n'
        proc = subprocess.run([sys.executable, str(KIT / 'bin/ws'), '--workspace-root', str(self.root), 'paste'],
                              cwd=self.root, input=raw, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        digest = json.loads(proc.stdout)
        self.assertIn('distinct_problem_lines', digest)
        self.assertNotEqual(proc.stdout, raw)
        saved = list((self.root / '.ws/inbox').glob('*.log'))
        self.assertEqual(len(saved), 1)
        self.assertNotIn('S' * 20, saved[0].read_text())
        self.assertIn('[REDACTED]', saved[0].read_text())
        self.assertIn('.ws/', (self.root / '.gitignore').read_text())

    def test_paste_bounds_stdin_read_before_saving(self):
        class TrackingInput(io.StringIO):
            def __init__(self, value):
                super().__init__(value)
                self.read_size = None
            def read(self, size=-1):
                self.read_size = size
                return super().read(size)
        source = TrackingInput('x' * 100)
        err = io.StringIO()
        with mock.patch.object(core, 'MAX_READ_BYTES', 3), mock.patch('sys.stdin', source), \
                contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'paste']), 2)
        self.assertEqual(source.read_size, 4)
        self.assertIn('50 MB', err.getvalue())
        self.assertFalse(list((self.root / '.ws/inbox').glob('*.log')))

    def test_paste_reads_clipboard_when_stdin_is_interactive(self):
        stdout = io.StringIO()
        process = mock.Mock(stdout=io.BytesIO(b'clipboard text'), returncode=0)
        with mock.patch.object(core.shutil, 'which', side_effect=lambda name: '/usr/bin/pbpaste' if name == 'pbpaste' else None), \
                mock.patch.object(core.subprocess, 'Popen', return_value=process), \
                mock.patch('sys.stdin', mock.Mock(isatty=lambda: True)), contextlib.redirect_stdout(stdout):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'paste']), 0)
        self.assertIn('distinct_problem_lines', stdout.getvalue())
        self.assertEqual(list((self.root / '.ws/inbox').glob('*.log'))[0].read_text(), 'clipboard text')

    def test_focus_matches_precede_deterministic_digest_and_mcp_accepts_focus(self):
        path = self.root / 'focus.log'
        path.write_text('noise\nkeep this\nerror: failed\n')
        result = core.digest_file(path, focus='keep', root=self.root)
        self.assertEqual(list(result)[3], 'focus_matches')
        self.assertEqual(result['focus_matches'], ['L2: keep this'])
        self.assertEqual(result['distinct_problem_lines'], 1)
        many = self.root / 'many.log'
        many.write_text('\n'.join(f'hit {n}' for n in range(100)))
        focused = core.digest_file(many, max_lines=2, focus='hit', root=self.root)['focus_matches']
        self.assertEqual(focused, ['L1: hit 0', 'L2: hit 1'])
        proc = subprocess.run([sys.executable, str(KIT / 'bin/ws'), '--workspace-root', str(self.root),
                               'digest', str(path), '--focus', 'keep'], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['focus_matches'], ['L2: keep this'])
        with self.assertRaises(core.WsError): core.digest_file(path, focus='[', root=self.root)
        long_line = self.root / 'long.log'
        long_line.write_text('a' * 50000)
        with self.assertRaisesRegex(core.WsError, 'simple regular expressions'):
            core.digest_file(long_line, focus='a.*z', root=self.root)
        self.assertEqual(core.digest_file(path, focus='kee{1,3}p', root=self.root)['focus_matches'], ['L2: keep this'])
        for unsafe in ('(a+)+$', 'a*a*a*a*a*b', '(a|aa)+$'):
            with self.subTest(focus=unsafe), self.assertRaisesRegex(core.WsError, 'simple regular expressions'):
                core.digest_file(path, focus=unsafe, root=self.root)
        reply = server.handle(self.root, {'jsonrpc': '2.0', 'method': 'tools/call', 'id': 1, 'params': {
            'name': 'digest_file', 'arguments': {'path': str(path), 'focus': 'keep'}}})
        self.assertEqual(json.loads(reply['result']['content'][0]['text'])['focus_matches'], ['L2: keep this'])

    def test_all_documented_prompt_hooks_block_oversized_prompts(self):
        cases = [('claude', 'UserPromptSubmit'), ('codex', 'UserPromptSubmit'),
                 ('cursor', 'beforeSubmitPrompt'), ('gemini', 'BeforeAgent')]
        prompt = 'line\n' * 151
        for client, event in cases:
            with self.subTest(client=client):
                if client in ('cursor', 'gemini'): core.connect(self.root, client)
                relative = {'claude': '.claude/settings.json', 'codex': '.codex/hooks.json',
                            'cursor': '.cursor/hooks.json', 'gemini': '.gemini/settings.json'}[client]
                hooks = json.loads((self.root / relative).read_text())['hooks']
                self.assertIn(event, hooks)
                handler = hooks[event][0] if client == 'cursor' else hooks[event][0]['hooks'][0]
                command = handler['command']
                self.assertIn(' paste --hook --client ' + client, command)
                argv = shlex.split(command)
                if argv[0] == 'powershell.exe': argv = core.encoded_hook_args(argv)
                payload = {'prompt': prompt, 'hook_event_name': event}
                if client == 'cursor': payload['attachments'] = []
                proc = subprocess.run(argv, cwd=self.root, input=json.dumps(payload), capture_output=True, text=True, timeout=15)
                code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
                blocked = stderr if client == 'claude' else json.loads(stdout)
                self.assertIn('ws digest', str(blocked))
                self.assertEqual(code, 2 if client == 'claude' else 0)
                if client == 'codex': self.assertEqual(blocked['decision'], 'block')
                if client == 'cursor': self.assertFalse(blocked['continue'])
                if client == 'gemini': self.assertEqual(blocked['decision'], 'deny')
                saved = list((self.root / '.ws/inbox').glob('*.log'))
                self.assertTrue(saved)
                self.assertEqual(len(saved[-1].read_text().splitlines()), 151)

    def test_size_limit_raw_bypass_and_short_prompt(self):
        event = 'UserPromptSubmit'
        too_big = 'x' * (12 * 1024 + 1)
        code, stdout, stderr = self.invoke_hook('codex', {'hook_event_name': event, 'prompt': too_big})
        self.assertEqual(json.loads(stdout)['decision'], 'block')
        self.assertEqual(len(list((self.root / '.ws/inbox').glob('*.log'))), 1)
        code, stdout, _ = self.invoke_hook('codex', {'hook_event_name': event, 'prompt': too_big + '\n!raw'})
        self.assertEqual(json.loads(stdout)['decision'], 'block')
        self.assertEqual(len(list((self.root / '.ws/inbox').glob('*.log'))), 2)
        code, stdout, stderr = self.invoke_hook('codex', {'hook_event_name': event, 'prompt': '!raw\n' + too_big})
        self.assertEqual((code, stdout), (0, '{}\n'))
        self.assertEqual(len(list((self.root / '.ws/inbox').glob('*.log'))), 2)
        code, stdout, _ = self.invoke_hook('codex', {'hook_event_name': event, 'prompt': 'short prompt'})
        self.assertEqual((code, stdout), (0, '{}\n'))

    def test_hook_bounds_json_read_and_blocks_oversized_input(self):
        class TrackingInput(io.StringIO):
            def __init__(self, value):
                super().__init__(value)
                self.read_size = None
            def read(self, size=-1):
                self.read_size = size
                return super().read(size)
        source = TrackingInput(json.dumps({'prompt': 'too large'}))
        stdout = io.StringIO()
        with mock.patch.object(core, 'MAX_READ_BYTES', 3), mock.patch('sys.stdin', source), \
                contextlib.redirect_stdout(stdout):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'paste', '--hook', '--client', 'codex']), 0)
        self.assertEqual(source.read_size, 4)
        self.assertEqual(json.loads(stdout.getvalue())['decision'], 'block')

    def test_clipboard_reader_stops_at_size_limit(self):
        class Process:
            def __init__(self):
                self.stdout = io.BytesIO(b'x' * 100)
                self.returncode = 0
                self.killed = False
            def wait(self, timeout=None): return self.returncode
            def kill(self):
                self.killed = True
                self.returncode = -9
        process = Process()
        with mock.patch.object(core, 'MAX_READ_BYTES', 3), \
                mock.patch.object(core.shutil, 'which', side_effect=lambda name: '/fake/pbpaste' if name == 'pbpaste' else None), \
                mock.patch.object(core.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(core.WsError, '50 MB'):
                core.clipboard_text()
        self.assertTrue(process.killed)

    def test_block_response_survives_prompt_save_limit(self):
        prompt = 'x' * (12 * 1024 + 1)
        for client in ('claude', 'codex', 'cursor', 'gemini'):
            with self.subTest(client=client), mock.patch.object(core, 'paste_save', side_effect=core.WsError('synthetic write failure')):
                code, stdout, stderr = self.invoke_hook(client, {'hook_event_name': 'UserPromptSubmit', 'prompt': prompt})
                response = stderr if client == 'claude' else json.loads(stdout)
                self.assertIn('short question', str(response))
                self.assertEqual(code, 2 if client == 'claude' else 0)
                if client == 'codex': self.assertEqual(response['decision'], 'block')
                if client == 'cursor': self.assertFalse(response['continue'])
                if client == 'gemini': self.assertEqual(response['decision'], 'deny')
        self.assertFalse(list((self.root / '.ws/inbox').glob('*.log')))

    def test_local_summary_is_gated_by_configured_pack(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), mock.patch.object(cli.subprocess, 'run', side_effect=AssertionError('must not run')):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'digest', str(KIT / 'kit.json'), '--local-summary']), 2)
        self.assertIn('local-llm pack', err.getvalue())
        config = core.config(self.root); config['packs'].append('local-llm')
        (self.root / 'workspace.json').write_text(json.dumps(config))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), mock.patch.object(cli.subprocess, 'run',
                return_value=subprocess.CompletedProcess([], 0, 'synthetic summary\n', '')) as run:
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'digest', str(KIT / 'kit.json'), '--local-summary']), 0)
        self.assertIn('synthetic summary', stdout.getvalue())
        self.assertEqual(run.call_args.args[0][1], str(KIT / 'packs/local-llm/summarize.py'))

    def test_upgrade_adds_guard_without_replacing_a_user_prompt_hook(self):
        desired = core.memory_hooks(self.root, 'codex')
        old = json.loads(json.dumps(desired))
        del old['hooks']['UserPromptSubmit']
        user_hook = {'hooks': [{'type': 'command', 'command': 'user-prompt-hook'}]}
        old['hooks']['UserPromptSubmit'] = [user_hook]
        merged = json.loads(upgrade.hooks(json.dumps(old), json.dumps(desired)))
        self.assertEqual(merged['hooks']['UserPromptSubmit'][0], user_hook)
        self.assertIn('paste --hook --client codex', merged['hooks']['UserPromptSubmit'][1]['hooks'][0]['command'])


if __name__ == '__main__':
    unittest.main()
