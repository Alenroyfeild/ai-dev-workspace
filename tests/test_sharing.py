import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from ws import cli, core, scope, team


class SharingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve(); self.root = self.base / 'workspace'
        p = mock.patch.dict(os.environ, HOME=str(self.base), USERPROFILE=str(self.base), WS_OFFLINE='1')
        p.start(); self.addCleanup(p.stop)
        core.init(self.root, 'synthetic', clients=[])
        self.remote = self.base / 'team.git'; team._git(self.base, 'init', '--bare', '-q', str(self.remote))
        team.manage(self.root, 'init', str(self.remote), apply=True, attest=True)
        self.clone = self.root / '.ws/team'
        core.task_new(self.root, 'T1', 'synthetic'); core.claim(self.root, 'T1', 'synthetic')
        core.remember(self.root, 'Use the portable queue because it is bounded.')
        scope.record(self.root, 'task:T1', 'team')

    def test_preview_redacts_excludes_capture_and_apply_unshare_preserves_original(self):
        from ws import sharing
        source = core.task_path(self.root, 'T1'); text = source.read_text()
        source.write_text(text + '\n<!-- ws:captured:x -->\n### Captured today\nsecret capture\n<!-- /ws:captured -->\n')
        core.remember(self.root, 'Prefer queues <private>private sentence</private> token=syntheticsecretvalue /tmp/private/location')
        before = source.read_bytes(); plan = sharing.preview(self.root, 'task:T1', author='tester')
        for excluded in ('secret capture', 'private sentence', 'syntheticsecretvalue', '/tmp/private/location', 'claim_token:'):
            self.assertNotIn(excluded, plan['content'])
        self.assertFalse((self.clone / 'entries').exists()); sharing.apply(self.root, plan)
        target = self.clone / plan['destination']; self.assertIn('author: tester', target.read_text())
        self.assertTrue(sharing.preview(self.root, 'task:T1', author='tester')['unchanged'])
        removal = sharing.preview(self.root, 'task:T1', unshare=True); self.assertIn('history', removal['warning'])
        sharing.apply(self.root, removal); self.assertFalse(target.exists()); self.assertEqual(before, source.read_bytes())

    def test_inline_handoff_stays_private_and_failed_receipt_write_rolls_back(self):
        from ws import sharing
        source = core.task_path(self.root, 'T1')
        source.write_text(core.set_section(source.read_text(), 'Objective', 'Build a bounded queue.'))
        plan = sharing.preview(self.root, 'task:T1')
        self.assertIn('Build a bounded queue.', plan['content'])
        self.assertNotIn('Use the portable queue', plan['content'])
        writer = core.atomic_write
        def fail_receipt(path, text):
            if path.name == 'shares.json': raise OSError('synthetic failure')
            writer(path, text)
        with mock.patch('ws.core.atomic_write', side_effect=fail_receipt):
            with self.assertRaises(core.WsError): sharing.apply(self.root, plan)
        self.assertFalse((self.clone / plan['destination']).exists())

    def test_crlf_standalone_projection_keeps_the_whole_body(self):
        from ws import sharing
        directory = core.vault(self.root) / 'Knowledge'; directory.mkdir()
        (directory / 'K1.md').write_bytes(b'---\r\nid: K1\r\nscope: team\r\n---\r\n\r\nKeep the first word and every line.\r\n')
        self.assertIn('Keep the first word and every line.', sharing.preview(self.root, 'knowledge:K1')['content'])

    def test_unshare_missing_source_uses_only_owned_receipt(self):
        from ws import sharing
        plan = sharing.preview(self.root, 'task:T1'); sharing.apply(self.root, plan)
        core.task_path(self.root, 'T1').unlink()
        removal = sharing.preview(self.root, 'task:T1', unshare=True); sharing.apply(self.root, removal)
        self.assertFalse((self.clone / plan['destination']).exists())
        with self.assertRaises(core.WsError): sharing.preview(self.root, 'task:T1', unshare=True)

    def test_stale_source_destination_and_private_scope_refuse(self):
        from ws import sharing
        plan = sharing.preview(self.root, 'task:T1'); core.remember(self.root, 'New decision requires another preview.')
        with self.assertRaises(core.WsError): sharing.apply(self.root, plan)
        plan = sharing.preview(self.root, 'task:T1'); sharing.apply(self.root, plan)
        target = self.clone / plan['destination']; target.write_text('teammate edit\n')
        with self.assertRaises(core.WsError): sharing.preview(self.root, 'task:T1', unshare=True)
        scope.record(self.root, 'task:T1', 'private')
        with self.assertRaises(core.WsError): sharing.preview(self.root, 'task:T1')

    def test_team_saves_are_standalone_and_one_gate_keeps_inline_decision_private(self):
        for args, directory in ((['remember', 'A bounded decision remains portable.', '--team'], 'Decisions'),
                                (['lesson', 'add', 'A timeout happened; always bound retries.', '--team'], 'Lessons'),
                                (['know', 'add', 'The queue contract uses stable receipts.', '--team'], 'Knowledge')):
            with mock.patch('builtins.input', return_value='n') as confirm, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(['--workspace-root', str(self.root), *args]), 0)
            self.assertEqual(confirm.call_count, 1)
            records = [p for p in (core.vault(self.root) / directory).glob('*.md') if p.name != 'INDEX.md' and not p.name.endswith('.index.md')]; self.assertEqual(len(records), 1)
            self.assertEqual(core.parse_meta(records[0].read_text())['scope'], 'team')
        self.assertFalse((self.clone / 'entries').exists())
        self.assertIn('Decision: A bounded', core.section(core.task_path(self.root, 'T1').read_text(), 'Handoff'))
        self.assertFalse(list(self.clone.rglob('*.md')))

    @unittest.skipIf(os.name == 'nt', 'symlink fixture requires Windows developer mode')
    def test_symlink_destination_and_changed_remote_refuse(self):
        from ws import sharing
        (self.clone / 'entries').symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(core.WsError): sharing.preview(self.root, 'task:T1')
        (self.clone / 'entries').unlink(); team._git(self.clone, 'remote', 'set-url', 'origin', str(self.base / 'other.git'))
        with self.assertRaises(core.WsError): sharing.preview(self.root, 'task:T1')
