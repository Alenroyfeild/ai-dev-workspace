import tempfile
import unittest
from pathlib import Path
from unittest import mock

from testutil import run_ws as ws
from ws import core

RELOAD = 'running assistant sessions and MCP servers keep the old code'
CHANGE = {'path': 'AGENTS.md', 'new': False, 'diff': '--- a\n+++ b'}


class UpdateRouteTests(unittest.TestCase):
    def test_compact_help_names_the_update_route_in_order(self):
        text = ' '.join(ws('--help').stdout.split())
        self.assertIn('Updating?', text)
        route = text.split('Updating?')[1]
        positions = [route.index(s) for s in ('ws update', 'ws upgrade --dry-run', '--yes', 'ws start')]
        self.assertEqual(positions, sorted(positions))

    def test_readme_and_setup_doc_carry_the_same_route(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('README.md', 'docs/SETUP.md'):
            text = (root / name).read_text(encoding='utf-8')
            self.assertIn('ws upgrade --dry-run', text, name)
        self.assertIn('Updating', (root / 'README.md').read_text(encoding='utf-8'))

    def update(self, *args, update_result=None, available=True, packaged=False):
        with mock.patch.object(core, 'PACKAGED', packaged), \
             mock.patch.object(core, 'check_update', return_value={'update_available': available}), \
             mock.patch.object(core, 'update_kit', return_value=update_result or {'updated_to': '9', 'git': 'Updating a..b'}) as kit:
            return ws('update', *args), kit

    def test_reload_line_after_a_real_source_update_on_stderr_only(self):
        result, kit = self.update()
        self.assertEqual(result.returncode, 0, result.stderr)
        kit.assert_called_once()
        self.assertIn(RELOAD, result.stderr)
        self.assertNotIn(RELOAD, result.stdout)

    def test_no_reload_line_for_check_noop_or_package_hint(self):
        result, kit = self.update('--check')
        self.assertNotIn(RELOAD, result.stderr); kit.assert_not_called()
        result, _ = self.update(available=False)
        self.assertNotIn(RELOAD, result.stderr)
        result, _ = self.update(update_result={'updated_to': '9', 'git': 'Already up to date.'})
        self.assertNotIn(RELOAD, result.stderr)
        result, _ = self.update(packaged=True, update_result={'installation': 'package', 'command': 'pipx upgrade x', 'note': 'n'})
        self.assertNotIn(RELOAD, result.stderr)

    def upgrade(self, *args, changes):
        plan = {'changes': changes, 'pending': [], 'backups': []}
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(core, 'find_root', return_value=Path(tmp)), \
             mock.patch.object(core, 'upgrade_workspace', return_value=plan), \
             mock.patch('ws.upgrade.summary', return_value='~ AGENTS.md'):
            return ws('upgrade', *args)

    def test_reload_line_only_after_upgrade_applied_changes(self):
        applied = self.upgrade('--yes', changes=[CHANGE])
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertIn(RELOAD, applied.stderr)
        self.assertNotIn(RELOAD, applied.stdout)
        for args, changes in ((('--dry-run',), [CHANGE]), (('--yes',), [])):
            result = self.upgrade(*args, changes=changes)
            self.assertNotIn(RELOAD, result.stderr, args)


if __name__ == '__main__':
    unittest.main()
