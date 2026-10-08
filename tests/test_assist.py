import datetime
import json
import os
from unittest import mock
from test_ws import Base
from ws import core, assist


class AssistTests(Base):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(assist, 'feature_suggestions')
        patch.start(); self.addCleanup(patch.stop)

    def test_filters_cost_findings_and_caps_suggestions(self):
        names = ['ccd_builtin', 'claude-in-chrome', 'ai-dev-workspace', 'recent', 'graphy-helper', 'idle']
        report = {'findings': [{'id': name, 'title': 'Remove ' + name, 'explanation': name,
                    'estimatedSavingsUSD': 2, 'fix': {'text': 'Remove ' + name}} for name in names]}
        usage = {'mcp': [{'Server': 'recent', 'Calls': 1}]}
        with mock.patch.object(core, 'tools', return_value=[]), mock.patch.object(assist, 'cost_data', return_value=(report, usage)):
            items = assist.suggestions(self.root)
        self.assertEqual([s['id'] for s in items], ['cost-idle'])
        self.assertEqual(items[0]['safety'], 'changes-config')
        self.assertIn('$2.00', items[0]['estimated_saving'])
        self.assertNotIn('--apply', items[0]['command'])
        with mock.patch.object(assist, 'cost_data', return_value=(report, usage)), mock.patch.object(core, 'tools', return_value=[]):
            with self.assertRaises(core.WsError): assist.decide(self.root, 'cost-idle', 'always')
            with self.assertRaises(core.WsError): assist.apply(self.root, 'cost-idle')

    def test_decline_snooze_and_safe_explicit_application(self):
        repo = self.root / 'repo'; repo.mkdir(); (repo / 'README.md').write_text('# Synthetic\n')
        cfg = core.config(self.root); cfg['repos'] = [str(repo)]
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        with mock.patch.object(core, 'tools', return_value=[]), mock.patch.object(assist, 'cost_data', return_value=({}, {})):
            suggestion = assist.suggestions(self.root)[0]
            self.assertEqual(suggestion['id'], 'map')
            with self.assertRaises(core.WsError): assist.apply(self.root, 'map')
            assist.decide(self.root, 'map', 'declined')
            self.assertNotIn('map', [s['id'] for s in assist.suggestions(self.root)])
            with mock.patch.object(core, 'now', return_value=(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=31)).isoformat()):
                self.assertIn('map', [s['id'] for s in assist.suggestions(self.root)])
            assist.decide(self.root, 'map', 'always'); assist.apply(self.root, 'map')
            self.assertTrue((core.vault(self.root) / 'Project/Codebase map.md').exists())
            os.utime(core.vault(self.root) / 'Project/Codebase map.md', (0, 0))
            self.assertIn('map', [s['id'] for s in assist.suggestions(self.root)])

    def test_sessions_checkpoint_lessons_long_session_and_notices(self):
        core.claim(self.root, 'T-1', 'synthetic')
        with mock.patch.object(core, 'tools', return_value=[]), mock.patch.object(assist, 'cost_data', return_value=({}, {})):
            for i in range(3): assist.observe(self.root, {'hook_event_name': 'SessionStart', 'session_id': str(i)})
            self.assertIn('checkpoint-T-1', [s['id'] for s in assist.suggestions(self.root)])
            for i in range(5): core.checkpoint(self.root, 'T-1', 'in_progress', 'Synthetic next')
            self.assertIn('lesson', [s['id'] for s in assist.suggestions(self.root)])
            transcript = self.root / 'large'; transcript.write_bytes(b'x' * 2000001)
            assist.observe(self.root, {'transcript_path': str(transcript)})
            self.assertIn('long-session', [s['id'] for s in assist.suggestions(self.root)])
            self.assertLessEqual(len(assist.suggestions(self.root)), 2)
            self.assertLessEqual(len(core.notices(self.root)), 2)
            self.assertEqual(core.notices(self.root), [])
