import json
import os
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock
from test_ws import Base
from ws import assist, cli, core, orchestration, upgrade


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

    def test_upgrade_applies_migration_result_block_to_stderr(self):
        cfg = core.config(self.root)
        cfg['kit_version'] = '0.0.1'
        repo_dir = Path(self.tmp.name) / 'repo'
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / '.git').mkdir(parents=True, exist_ok=True)
        repo_state = {'kit_version': '0.0.1', 'files': {}, 'workspace': str(self.root)}
        (repo_dir / '.ws-start.json').write_text(json.dumps(repo_state))
        cfg['repos'] = [str(repo_dir)]
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        (self.root / 'AGENTS.md').write_text('Custom unmarked user rules without markers\n')
        (self.root / 'routing.json').write_text('{"preset": "mixed"}\n')

        with mock.patch('urllib.request.urlopen', side_effect=OSError('network disabled')):
            with redirect_stdout(StringIO()) as out_buf, redirect_stderr(StringIO()) as err_buf:
                code = cli.main(['--workspace-root', str(self.root), 'upgrade', '--yes'])

        self.assertEqual(code, 0)
        out_text = out_buf.getvalue()
        self.assertIn('"pending_review"', out_text)
        self.assertIn('"backups"', out_text)

        err_text = err_buf.getvalue()
        self.assertIn('Migration result:', err_text)
        self.assertIn(f"CLI version: {core.kit_meta()['version']}", err_text)
        self.assertIn(f"Template version: {core.kit_meta()['version']}", err_text)
        self.assertIn('Repo wiring kit_version: 0.0.1', err_text)
        self.assertIn('Files changed:', err_text)
        self.assertIn('kept:', err_text)
        self.assertIn('Pending proposals (.ws-new):', err_text)
        self.assertIn('AGENTS.md', err_text)
        self.assertIn('Backup directory:', err_text)
        self.assertIn('.ws/backups/', err_text)
        self.assertIn('Rollback: copy files back from', err_text)
        self.assertNotIn('--rollback', err_text)
        self.assertIn('configuration check, not live health', err_text)
        self.assertIn('Offline config check:', err_text)

    def test_upgrade_migration_result_suppressed_in_json_mode(self):
        cfg = core.config(self.root)
        cfg['kit_version'] = '0.0.1'
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        (self.root / 'routing.json').write_text('{"preset": "mixed"}\n')

        with mock.patch.dict(os.environ, {'WS_JSON': '1'}):
            with redirect_stdout(StringIO()) as out_buf, redirect_stderr(StringIO()) as err_buf:
                code = cli.main(['--workspace-root', str(self.root), 'upgrade', '--yes'])

        self.assertEqual(code, 0)
        self.assertNotIn('Migration result:', err_buf.getvalue())
        data = json.loads(out_buf.getvalue())
        self.assertIn('pending_review', data)
        self.assertIn('backups', data)

    def test_routed_readonly_provider_selftests_are_deduplicated(self):
        binding = dict(available=True, provider='codex')
        with mock.patch.object(orchestration, 'route', return_value=binding), mock.patch.object(core, '_detected', side_effect=lambda n: n == 'codex'):
            self.assertNotIn('selftest-codex', self.items())  # never delegated: no selftest pitch
            (self.root / '.ws/briefs').mkdir(parents=True)
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
