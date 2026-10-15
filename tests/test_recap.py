import contextlib
import io
import json
import unittest
from unittest import mock
from test_ws import Base
import test_sharing
from ws import cli, core, sharing, team_status

NOW = '2026-10-16T12:00:00+00:00'


class RecapTests(Base):
    def report(self, since='7d'):
        from ws import recap
        with mock.patch.object(core, 'now', return_value=NOW): return recap.report(self.root, since)

    def test_dated_decisions_status_changes_and_since_filter(self):
        with mock.patch.object(core, 'now', return_value='2026-09-01T12:00:00+00:00'):
            core.remember(self.root, 'Old choice.', 'T-1')
        with mock.patch.object(core, 'now', return_value='2026-10-15T11:00:00+00:00'):
            core.checkpoint(self.root, 'T-1', 'blocked', 'Wait for receipt review.')
            core.remember(self.root, 'Use integer cents token=syntheticsecret123456', 'T-1')
        result = self.report(); row = result['tasks'][0]
        self.assertEqual([e['kind'] for e in row['events']], ['status', 'decision'])
        self.assertEqual((row['events'][0]['from'], row['events'][0]['to']), ('ready', 'blocked'))
        self.assertNotIn('syntheticsecret123456', json.dumps(result))
        self.assertIn('integer cents', row['events'][1]['text'])
        self.assertEqual(self.report('1d')['tasks'], [])

    def test_old_notes_are_current_snapshots_and_recap_never_writes(self):
        path = core.task_path(self.root, 'T-1')
        text = core.set_meta(path.read_text(), {'updated': NOW})
        path.write_text(core.set_section(text, 'Handoff', 'Decision: keep the receipt parser.'))
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        row = self.report()['tasks'][0]
        self.assertEqual(row['events'], []); self.assertIn('receipt parser', row['current_decisions'][0])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        from ws import recap
        self.assertIn('current snapshot', recap.render(self.report()))

    def test_invalid_dates_and_history_are_bounded_and_warn(self):
        for since in ('yesterday', '0d', '99999d'):
            with self.assertRaises(core.WsError): self.report(since)
        path = core.task_path(self.root, 'T-1')
        path.write_text(core.set_section(core.set_meta(path.read_text(), {'updated': NOW}), 'Activity', '{broken json}\n'))
        self.assertTrue(self.report()['warnings'])

    def test_long_decisions_remain_in_dated_history_and_deep_json_is_skipped(self):
        core.remember(self.root, 'Receipt policy ' + 'bounded ' * 1000, 'T-1')
        self.assertTrue(self.report()['tasks'][0]['events'])
        path = core.task_path(self.root, 'T-1')
        path.write_text(core.set_section(core.set_meta(path.read_text(), {'updated': NOW}), 'Activity', '[' * 1500 + ']' * 1500))
        self.assertTrue(self.report()['warnings'])

    def test_cli_plain_and_json(self):
        core.remember(self.root, 'Keep receipt checksum.', 'T-1')
        for suffix in ([], ['--json']):
            with contextlib.redirect_stdout(io.StringIO()) as output, mock.patch.object(core, 'now', return_value=NOW):
                self.assertEqual(cli.main(['--workspace-root', str(self.root), 'recap', *suffix]), 0)
            if suffix: self.assertEqual(json.loads(output.getvalue())['tasks'][0]['id'], 'T-1')
            else: self.assertIn('receipt checksum', output.getvalue())


class TeamRecapTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def test_only_approved_shared_decisions_and_status_snapshots(self):
        from ws import recap
        item = sharing.standalone(self.root, 'decision', 'Use shared receipt checksums.', True)
        sharing.apply(self.root, sharing.preview(self.root, item, author='sam'))
        sharing.standalone(self.root, 'decision', 'PRIVATE_TEAM_SENTINEL', False)
        team_status.apply(self.root, team_status.preview(self.root, 'Checking receipts.', author='sam', enable=True))
        with mock.patch.object(core, 'now', return_value=NOW), mock.patch('ws.team._git', side_effect=AssertionError('recap must not contact git')):
            result = recap.report(self.root)
        self.assertEqual({r['kind'] for r in result['team']}, {'decision snapshot', 'status snapshot'})
        self.assertTrue(all(r['author'] == 'sam' and r['untrusted'] for r in result['team']))
        self.assertNotIn('PRIVATE_TEAM_SENTINEL', json.dumps(result))
        self.assertIn('untrusted', recap.render(result))

    def test_invalid_team_status_date_is_filtered_before_recap(self):
        from ws import recap
        team_status.apply(self.root, team_status.preview(self.root, 'Valid receipt status.', author='sam', enable=True))
        (self.clone / 'status/zzbad.json').write_text(json.dumps(dict(author='zzbad', task='other', line='BAD_DATE_SENTINEL', date='invalid')))
        with mock.patch.object(core, 'now', return_value=NOW): result = recap.report(self.root)
        self.assertTrue(any(r['author'] == 'sam' and r['kind'] == 'status snapshot' for r in result['team']))
        self.assertNotIn('BAD_DATE_SENTINEL', json.dumps(result)); self.assertTrue(result['warnings'])
