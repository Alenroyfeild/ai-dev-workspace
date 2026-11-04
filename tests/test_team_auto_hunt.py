import json
from unittest import mock

from test_ws import Base
from testutil import run_ws
from ws import core, team_auto


class TeamAutoLinkShapeTests(Base):
    def test_malformed_link_fails_before_backend_access_and_keeps_config(self):
        path = self.root / 'workspace.json'
        original = core.config(self.root)
        for value in (None, [], 'PRIVATE_LINK_CANARY', 42, False):
            with self.subTest(shape=type(value).__name__):
                path.write_text(json.dumps(dict(original, team_workspace=value)))
                before = path.read_bytes()
                with mock.patch.object(team_auto.team_sync, '_view') as pull, mock.patch.object(team_auto, '_launch') as launch:
                    with self.assertRaisesRegex(core.WsError, 'team_workspace'):
                        team_auto.pull(self.root, automatic=True)
                    with self.assertRaisesRegex(core.WsError, 'team_workspace'):
                        team_auto.schedule(self.root, '09:15')
                    pull.assert_not_called()
                    launch.assert_not_called()
                for args in (('sync', '--pull-only', '--automatic'),
                             ('sync', '--pull-only'),
                             ('sync', '--daily', '09:15', '--dry-run')):
                    result = run_ws('--workspace-root', self.root, *args, cwd=self.root)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn('team_workspace', result.stderr)
                    self.assertNotIn('Traceback', result.stderr)
                    self.assertNotIn('PRIVATE_LINK_CANARY', result.stderr + result.stdout)
                self.assertEqual(path.read_bytes(), before)
