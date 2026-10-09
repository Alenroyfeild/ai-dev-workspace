import json
import os
import shlex
import tempfile
from pathlib import Path
from unittest import mock
from test_ws import Base
from ws import core, orchestration


class ProviderDataTests(Base):
    def setUp(self):
        home = tempfile.TemporaryDirectory(); self.addCleanup(home.cleanup)
        env = mock.patch.dict(os.environ, {'HOME': home.name, 'CODEX_HOME': home.name + '/.codex', 'WS_OFFLINE': '1'})
        env.start(); self.addCleanup(env.stop); super().setUp()

    def test_custom_cli_family_and_command_are_data(self):
        path = self.root / 'routing.json'; data = json.loads(path.read_text())
        data['_ws_managed']['providers']['sample'] = {
            'cli': 'sample-agent', 'models': {'fast-family': 'sample-v2'},
            'tiers': {'worker': {'family': 'fast-family', 'effort': 'high'}},
            'headless': ['--read-only', '--model', '{model}', '--effort', '{effort}']}
        data['role_overrides']['explorer'] = {'provider': 'sample'}; path.write_text(json.dumps(data))
        with mock.patch.object(core.shutil, 'which', side_effect=lambda name: '/fixture/bin/' + name):
            binding = orchestration.route(self.root, 'explorer')
        self.assertEqual(binding['executable'], '/fixture/bin/sample-agent')
        self.assertEqual(orchestration.worker_command(binding, self.root),
            ['/fixture/bin/sample-agent', '--read-only', '--model', 'sample-v2', '--effort', 'high'])
        binding['headless'] = ['--root', '{repo}']
        literal = Path('/fixture/{prompt}')
        self.assertEqual(orchestration.worker_command(binding, literal), ['/fixture/bin/sample-agent', '--root', str(literal)])

    def test_printed_prompt_matches_redacted_brief(self):
        path = self.root / 'routing.json'; data = json.loads(path.read_text())
        data['role_overrides']['explorer'] = {'provider': 'cursor'}; path.write_text(json.dumps(data))
        redact = core.redact
        with mock.patch.object(core.shutil, 'which', return_value='/fixture/cursor-agent'), \
                mock.patch.object(core, 'redact', side_effect=lambda text: redact(text).replace('UNVERIFIED', 'REDACTED_LABEL')):
            prepared = orchestration.delegate(self.root, 'T-1', 'explorer')
        brief = Path(prepared['brief']).read_text()
        self.assertEqual(shlex.split(prepared['command'])[-1], brief)

    def test_headless_prompt_is_passed_to_execution(self):
        binding = dict(executable='synthetic', model='sample', effort='high', provider='sample',
                       headless=['--prompt', '{prompt}'], prepare=[], timeout_seconds=2)
        process = mock.Mock(returncode=0); process.communicate.return_value = ('ok', '')
        with mock.patch.object(orchestration.subprocess, 'Popen', return_value=process) as launch:
            orchestration.worker_run(binding, self.root, 'bounded synthetic prompt')
        self.assertEqual(launch.call_args[0][0][-1], 'bounded synthetic prompt')

    def test_invalid_cli_and_command_are_rejected(self):
        path = self.root / 'routing.json'; data = json.loads(path.read_text())
        data['role_overrides']['explorer'] = {'provider': 'codex'}
        for field, value in [('cli', '/outside/codex'), ('headless', 'shell command'), ('headless', ['bad\x00arg'])]:
            edited = json.loads(json.dumps(data)); edited['_ws_managed']['providers']['codex'][field] = value
            path.write_text(json.dumps(edited))
            with self.assertRaises(core.WsError): orchestration.route(self.root, 'explorer')

    def test_documented_clients_are_prepare_only_and_use_their_cli(self):
        path = self.root / 'routing.json'; data = json.loads(path.read_text())
        for provider, cli in [('cursor', 'cursor-agent'), ('copilot', 'copilot'), ('gemini', 'gemini')]:
            data['role_overrides']['explorer'] = {'provider': provider}; path.write_text(json.dumps(data))
            with mock.patch.object(core.shutil, 'which', side_effect=lambda name: '/fixture/bin/' + name):
                binding = orchestration.route(self.root, 'explorer')
                self.assertTrue(binding['available']); self.assertEqual(binding['executable'], '/fixture/bin/' + cli)
                self.assertFalse(binding['headless'])
                with self.assertRaisesRegex(core.WsError, 'preparation-only'):
                    orchestration.delegate(self.root, 'T-1', 'explorer', run=True)

    def test_legacy_upgrade_keeps_model_and_root_overrides(self):
        path = self.root / 'routing.json'; data = json.loads(path.read_text())
        for provider in ('claude', 'codex', 'ollama'):
            data['_ws_managed']['providers'][provider].pop('cli', None)
            data['_ws_managed']['providers'][provider].pop('headless', None)
        data['_ws_managed']['providers']['ollama']['models']['local'] = 'sample-local'
        data['role_overrides']['explorer'] = {'provider': 'codex', 'model': 'custom-model'}
        path.write_text(json.dumps(data)); core.upgrade_workspace(self.root)
        upgraded = json.loads(path.read_text())
        self.assertEqual(upgraded['_ws_managed']['providers']['ollama']['models']['local'], 'sample-local')
        self.assertEqual(upgraded['role_overrides'], data['role_overrides'])
        with mock.patch.object(core.shutil, 'which', return_value='/fixture/codex'):
            binding = orchestration.route(self.root, 'explorer')
        self.assertEqual(binding['model'], 'custom-model')
        self.assertIn('read-only', orchestration.worker_command(binding, self.root))
