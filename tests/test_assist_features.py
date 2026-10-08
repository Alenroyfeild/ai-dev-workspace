import json
from unittest import mock
from test_ws import Base
from ws import assist, core, orchestration


class FeatureTests(Base):
    def setUp(self):
        super().setUp()
        for target, name, value in ((core, 'tools', []), (core, '_detected', False),
                                    (orchestration, 'route', {'available': False})):
            patch = mock.patch.object(target, name, return_value=value)
            patch.start(); self.addCleanup(patch.stop)

    def items(self):
        return {item['id']: item for item in assist.suggestions(self.root, True)}

    def test_upgrade_version_and_pending_proposals_are_local(self):
        path = self.root / 'workspace.json'; cfg = core.config(self.root)
        cfg['kit_version'] = '0.0.1'; path.write_text(json.dumps(cfg))
        self.assertEqual(self.items()['upgrade']['command'], 'ws upgrade --dry-run')
        assist.decide(self.root, 'upgrade', 'declined')
        self.assertNotIn('upgrade', [i['id'] for i in assist.suggestions(self.root)])
        with self.assertRaises(core.WsError): assist.decide(self.root, 'upgrade', 'always')
        with self.assertRaises(core.WsError): assist.apply(self.root, 'upgrade')
        cfg['kit_version'] = '99.0.0'; path.write_text(json.dumps(cfg))
        self.assertNotIn('upgrade', self.items())
        (self.root / 'AGENTS.md.ws-new.1').write_text('Synthetic pending rules')
        self.assertIn('upgrade', self.items())

    def test_routed_readonly_provider_selftests_are_deduplicated(self):
        binding = dict(available=True, provider='codex')
        with mock.patch.object(orchestration, 'route', return_value=binding), mock.patch.object(core, '_detected', side_effect=lambda n: n == 'codex'):
            self.assertEqual(self.items()['selftest-codex']['command'], 'ws delegate --selftest --provider codex')
            path = self.root / '.ws/delegate-selftests.json'
            path.write_text(json.dumps({'codex': {'executed': False, 'result': 'prepared'}}))
            self.assertIn('selftest-codex', self.items())
            path.write_text(json.dumps({'codex': {'executed': True, 'result': 'SELFTEST OK'}}))
            self.assertNotIn('selftest-codex', self.items())
        with mock.patch.object(orchestration, 'route', side_effect=core.WsError('old routing')):
            self.assertNotIn('selftest-codex', self.items())

    def test_unconnected_clients_and_long_sessions_keep_ask_first_contract(self):
        with mock.patch.object(core, '_detected', return_value=True), mock.patch.object(core, 'client_connected', return_value=False):
            items = self.items()
            for client in ('cursor', 'vscode', 'gemini'):
                self.assertEqual(items['connect-' + client]['command'], 'ws connect ' + client)
                with self.assertRaises(core.WsError): assist.apply(self.root, 'connect-' + client)
            self.assertLessEqual(len(assist.suggestions(self.root)), 2)
            with mock.patch.object(core, 'client_connected', return_value=True):
                self.assertFalse(any(i.startswith('connect-') for i in self.items()))
        assist.save(self.root, {'long_session_bytes': 2000001})
        item = self.items()['long-session']
        self.assertIn('fresh', item['why'])
        self.assertIn('handoff', item['command'])
        assist.observe(self.root, {'hook_event_name': 'SessionStart', 'session_id': 'fresh'})
        self.assertNotIn('long-session', self.items())
