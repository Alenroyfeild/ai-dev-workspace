import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest import mock
from test_ws import Base
from ws import core, orchestration
from mcp import server


class OrchestrationTests(Base):
    def executable(self, directory, name, code):
        import sys
        path = directory / (name + '.cmd' if os.name == 'nt' else name)
        if os.name == 'nt':
            script = directory / (name + '.py'); script.write_text(code + '\n')
            path.write_text('@echo off\n"' + sys.executable + '" "' + str(script) + '" %*\n')
        else:
            path.write_text('#!' + sys.executable + '\n' + code + '\n'); path.chmod(0o755)
        return path

    def test_reviewer_diff_is_bounded_redacted_and_counted(self):
        repo = self.root / 'fixture'; repo.mkdir(); source = repo / 'calc.py'
        git = shutil.which('git'); subprocess.run([git, 'init', '-q', str(repo)], check=True)
        for text in ('def subtract(a, b): return a - b\n', 'def subtract(a, b): return a + b\n# token=syntheticsecret123456\n'):
            source.write_text(text); subprocess.run([git, '-C', str(repo), 'add', '.'], check=True)
            subprocess.run([git, '-C', str(repo), '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture'], check=True)
        core.task_new(self.root, 'DIFF-1', 'Review synthetic subtraction', repo=str(repo))
        with self.fake('print("calc.py:1: adds instead of subtracting. Use subtraction.")'):
            (Path(os.environ['PATH']) / 'git').symlink_to(git)
            prepared = orchestration.delegate(self.root, 'DIFF-1', 'reviewer', diff='HEAD~1..HEAD')
            brief = Path(prepared['brief']).read_text()
            for expected in ('Diff stat', 'Changed files', 'Bounded hunks', 'calc.py', '[REDACTED]'): self.assertIn(expected, brief)
            self.assertNotIn('syntheticsecret123456', brief); self.assertLessEqual(len(brief.split()), 400)
            result = orchestration.delegate(self.root, 'DIFF-1', 'reviewer', run=True, diff='HEAD~1..HEAD')
            self.assertEqual(result['findings'], 1); self.assertEqual(core.run_entries(self.root, 'DIFF-1')[-1]['findings'], 1)
            with self.assertRaises(core.WsError): orchestration.delegate(self.root, 'DIFF-1', 'reviewer', diff='--output=outside')
            with self.assertRaises(core.WsError): orchestration.delegate(self.root, 'DIFF-1', 'explorer', diff='HEAD')
            outside = self.root.parent / 'outside'; outside.mkdir()
            core.task_new(self.root, 'OUTSIDE-1', 'Unauthorized diff', repo=str(outside))
            with self.assertRaisesRegex(core.WsError, 'outside'):
                orchestration.delegate(self.root, 'OUTSIDE-1', 'reviewer', diff='HEAD')
            with mock.patch.object(orchestration.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='large change line\n' * 1000)):
                large = orchestration.delegate(self.root, 'DIFF-1', 'reviewer', diff='HEAD~1..HEAD')
            text = Path(large['brief']).read_text()
            for label in ('Diff stat', 'Changed files', 'Bounded hunks'): self.assertIn(label, text)
            self.assertLessEqual(len(text.split()), 400)

    def fake(self, code='import sys; print("UNVERIFIED sample.py:1 synthetic finding")'):
        directory = self.root / 'bin'; directory.mkdir(exist_ok=True)
        for name in ('codex', 'ollama'): self.executable(directory, name, code)
        return mock.patch.dict(os.environ, {'PATH': str(directory)})

    def fake_provider(self, name, code):
        directory = self.root / 'fake-bin'; directory.mkdir(exist_ok=True)
        self.executable(directory, name, code)
        return mock.patch.dict(os.environ, {'PATH': str(directory)})

    def test_codex_delegate_logs_turn_usage_and_keeps_output_readable(self):
        events = [
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'UNVERIFIED sample.py:1 finding'}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 31, 'output_tokens': 9}},
        ]
        code = 'import json,sys; assert "--json" in sys.argv; print("\\n".join(map(json.dumps, ' + repr(events) + ')))'
        with self.fake_provider('codex', code):
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
        entry = core.run_entries(self.root, 'T-1')[-1]
        self.assertEqual((entry['tokens_in'], entry['tokens_out']), (31, 9))
        self.assertIn('Total tokens: 40', core.trace(self.root, 'T-1'))
        self.assertIn('UNVERIFIED sample.py:1 finding', __import__('pathlib').Path(result['output']).read_text())

    def test_claude_delegate_logs_json_usage(self):
        payload = {'type': 'result', 'result': 'UNVERIFIED sample.py:2 finding',
                   'usage': {'input_tokens': 17, 'output_tokens': 6}}
        code = 'import json,sys; assert sys.argv[sys.argv.index("--output-format") + 1] == "json"; print(json.dumps(' + repr(payload) + '))'
        cfg = json.loads((self.root / 'routing.json').read_text())
        cfg['role_overrides']['explorer'] = {'provider': 'claude'}
        (self.root / 'routing.json').write_text(json.dumps(cfg))
        with self.fake_provider('claude', code):
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
        entry = core.run_entries(self.root, 'T-1')[-1]
        self.assertEqual((entry['tokens_in'], entry['tokens_out']), (17, 6))
        self.assertIn('UNVERIFIED sample.py:2 finding', __import__('pathlib').Path(result['output']).read_text())

    def test_unknown_usage_logs_zero_with_note(self):
        event = {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Synthetic result'}}
        code = 'import json; print(json.dumps(' + repr(event) + '))'
        with self.fake_provider('codex', code):
            orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
        entry = core.run_entries(self.root, 'T-1')[-1]
        self.assertEqual((entry['tokens_in'], entry['tokens_out']), (0, 0))
        self.assertIn('usage unavailable', entry['note'])

    def test_binding_overrides_no_fallback_and_upgrade(self):
        with self.fake():
            binding = orchestration.route(self.root, 'explorer')
            self.assertEqual((binding['provider'], binding['family'], binding['effort']), ('codex', 'luna', 'high'))
            planner = orchestration.route(self.root, 'planner')  # claude preferred but absent: visible fallback to codex
            self.assertEqual((planner['provider'], planner['family'], planner['available']), ('codex', 'sol', True))
            self.assertEqual(planner['skipped'], [{'provider': 'claude', 'reason': 'CLI not on PATH'}])
            path = self.root / 'routing.json'; d = json.loads(path.read_text())
            d['role_overrides']['planner'] = {'provider': 'claude'}  # an explicitly pinned provider never falls back
            path.write_text(json.dumps(d))
            self.assertFalse(orchestration.route(self.root, 'planner')['available'])
            with self.assertRaises(core.WsError): orchestration.delegate(self.root, 'T-1', 'planner')
            d['role_overrides'] = {}
            d['role_overrides']['explorer'] = {'provider': 'codex', 'model': 'gpt-6.1-sol', 'effort': 'low'}
            path.write_text(json.dumps(d))
            self.assertEqual(orchestration.route(self.root, 'explorer')['model'], 'gpt-6.1-sol')
            core.upgrade_workspace(self.root)
            self.assertEqual(json.loads(path.read_text())['role_overrides'], d['role_overrides'])

    def test_bounded_prepare_run_evidence_and_write_role_refusal(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect synthetic files', notes={'Evidence': 'Keep human evidence.'})
        with self.fake():
            prepared = orchestration.delegate(self.root, 'T-1', 'explorer')
            text = (__import__('pathlib').Path(prepared['brief'])).read_text()
            for section in ('Objective', 'Next action', 'Blockers', 'Evidence', 'Allowed paths', 'Output contract'):
                self.assertIn(section, text)
            self.assertLessEqual(len(text.split()), 400)
            self.assertIn('read-only', prepared['command'])
            with self.assertRaises(core.WsError): orchestration.delegate(self.root, 'T-1', 'worker', run=True)
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
            self.assertEqual(result['exit_code'], 0)
            evidence = core.task_read(self.root, 'T-1', ['Evidence'])['sections']['Evidence']
            self.assertIn('Keep human evidence.', evidence); self.assertIn('unverified', evidence)
            self.assertIn('luna', core.trace(self.root, 'T-1'))
            reply = server.handle(self.root, {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'delegate','arguments':{'task':'T-1','role':'explorer','run':True}}})
            self.assertIn('error', reply)

    def test_provider_failure_is_logged_without_fallback(self):
        with self.fake('import sys; print("synthetic failure"); sys.exit(3)'):
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
            self.assertEqual(result['exit_code'], 3)
            self.assertEqual(core.run_entries(self.root, 'T-1')[-1]['result'], 'failed')

    def test_selftest_positive_control_disk_verdicts_and_doctor(self):
        git = shutil.which('git')
        cases = [('print("expired login")', 'INCONCLUSIVE', 2),
                 ('from pathlib import Path; print(Path("token.txt").read_text())', 'SELFTEST OK', 0),
                 ('from pathlib import Path; print(Path("token.txt").read_text()); Path("../outside/new").write_text("x")', 'FAIL', 1),
                 ('from pathlib import Path; Path("token.txt").write_text("changed")', 'FAIL', 1)]
        for code, verdict, exit_code in cases:
            with self.subTest(verdict=verdict), self.fake(code):
                binary = Path(os.environ['PATH']) / 'git'
                if os.name == 'nt': self.executable(binary.parent, 'git', 'import subprocess,sys; sys.exit(subprocess.call([' + repr(git) + ', *sys.argv[1:]]))')
                elif not binary.exists(): binary.symlink_to(git)
                result = orchestration.selftest(self.root, 'codex')
                self.assertEqual((result['result'], result['exit_code']), (verdict, exit_code))
                self.assertEqual(core.doctor(self.root)['delegate_selftests']['codex']['result'], verdict)

    def test_selftest_claude_prepares_and_missing_provider_is_inconclusive(self):
        with self.fake():
            result = orchestration.selftest(self.root, 'codex', run=False)
            self.assertIn('read-only', result['command'])
            shutil.rmtree(result['directory'])
            suffix = '.cmd' if os.name == 'nt' else ''
            shutil.copy2(Path(os.environ['PATH'], 'codex' + suffix), Path(os.environ['PATH'], 'claude' + suffix))
            with mock.patch.object(orchestration, 'worker_run', side_effect=AssertionError('must not run Claude')):
                prepared = orchestration.selftest(self.root, 'claude', run=False)
            self.assertIn('Read,Glob,Grep', prepared['command'])
            shutil.rmtree(prepared['directory'])
        with mock.patch.dict(os.environ, {'PATH': ''}):
            self.assertEqual(orchestration.selftest(self.root, 'codex')['exit_code'], 2)
