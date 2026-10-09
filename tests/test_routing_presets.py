import json
import os
import tempfile
from unittest import mock
from test_ws import Base
from ws import core, orchestration


class RoutingPresetTests(Base):
    def setUp(self):
        home = tempfile.TemporaryDirectory(); self.addCleanup(home.cleanup)
        env = mock.patch.dict(os.environ, {'HOME': home.name, 'CODEX_HOME': home.name + '/.codex'})
        env.start(); self.addCleanup(env.stop); super().setUp()

    def test_single_presets_use_only_one_provider_and_cannot_run(self):
        roles = ('lead', 'planner', 'worker', 'explorer', 'reviewer', 'local')
        for provider in ('claude', 'codex', 'cursor', 'copilot', 'gemini'):
            (self.root / 'routing.json').write_text(orchestration.routing_template(provider + '-only'))
            with mock.patch.object(core.shutil, 'which', side_effect=lambda cli: '/fixture/' + cli) as detect:
                for role in roles:
                    binding = orchestration.route(self.root, role)
                    self.assertEqual(binding['provider'], provider)
                    self.assertTrue(binding['available']); self.assertFalse(binding['can_run'])
                    self.assertEqual(binding['skipped'], [])
                self.assertEqual({call.args[0] for call in detect.call_args_list}, {'cursor-agent' if provider == 'cursor' else provider})
                with self.assertRaisesRegex(core.WsError, 'preparation-only'):
                    orchestration.delegate(self.root, 'T-1', 'explorer', run=True)

    def test_upgrade_preserves_selection_and_custom_models(self):
        path = self.root / 'routing.json'; data = json.loads(orchestration.routing_template('codex-only'))
        data['_ws_managed']['providers']['codex']['models']['luna'] = 'custom-model'
        data['role_overrides']['worker'] = {'effort': 'low'}
        path.write_text(json.dumps(data)); core.upgrade_workspace(self.root)
        updated = json.loads(path.read_text())
        self.assertEqual(updated['preset'], 'codex-only')
        self.assertEqual(updated['_ws_managed']['roles']['local']['preference'], ['codex'])
        self.assertEqual(updated['_ws_managed']['providers']['codex']['models']['luna'], 'custom-model')
        self.assertEqual(updated['role_overrides'], data['role_overrides'])
        self.assertEqual(core.upgrade_workspace(self.root)['changes'], [])

    def test_two_provider_and_selected_mixed_presets(self):
        combined = json.loads(orchestration.routing_template('claude+codex'))
        self.assertEqual(combined['assistants'], ['claude', 'codex'])
        self.assertEqual(combined['delegation_mode'], 'read-only')
        mixed = json.loads(orchestration.routing_template('mixed', ['cursor', 'copilot']))
        self.assertEqual(mixed['assistants'], ['cursor', 'copilot'])
        for role in mixed['_ws_managed']['roles'].values():
            self.assertTrue(role['preference']); self.assertLessEqual(set(role['preference']), {'cursor', 'copilot'})
        for name, selected in [('unknown', None), ('mixed', []), ('mixed', [{}]), ('codex-only', ['claude'])]:
            with self.assertRaises(core.WsError): orchestration.routing_template(name, selected)
