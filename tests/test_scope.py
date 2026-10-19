import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from testutil import needs_symlinks
from pathlib import Path
from unittest import mock
from ws import cli, core, team


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.home = self.base / 'home'; self.home.mkdir()
        patch = mock.patch.dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home), WS_OFFLINE='1')
        patch.start(); self.addCleanup(patch.stop)
        self.a, self.b = self.base / 'a', self.base / 'b'
        for root in (self.a, self.b): core.init(root, 'synthetic', clients=[])

    def command(self, root, identifier, value=None):
        args = ['--workspace-root', str(root), 'scope', identifier] + ([value] if value else [])
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(args)
        return code, output.getvalue()

    def test_new_and_legacy_tasks_default_private(self):
        core.task_new(self.a, 'T-1', 'synthetic')
        self.assertEqual(core.task_read(self.a, 'T-1', ['Objective'])['meta'].get('scope'), 'private')
        self.assertEqual(core.config(self.a).get('share'), 'ask')
        path = core.task_path(self.a, 'T-1'); path.write_text(path.read_text().replace('scope: private\n', ''))
        before = path.read_bytes(); code, result = self.command(self.a, 'task:T-1')
        self.assertEqual(code, 0); self.assertEqual(json.loads(result)['scope'], 'private')
        self.assertEqual(before, path.read_bytes())

    def test_all_record_kinds_change_metadata_only_and_preserve_crlf_body(self):
        from ws import scope
        for kind, directory in scope.DIRECTORIES.items():
            path = core.vault(self.a) / directory / 'R-1.md'; path.parent.mkdir(exist_ok=True)
            body = b'\r\n\r\n# Keep user text\r\nA private note\nMixed endings stay intact.\r\n'
            path.write_bytes(b'---\r\nid: R-1\r\n---' + body)
            with mock.patch('ws.team._git', side_effect=AssertionError('Scope must not access Git')):
                self.assertEqual(self.command(self.a, kind + ':R-1', 'team')[0], 0)
            raw = path.read_bytes(); self.assertIn(b'scope: team', raw)
            self.assertEqual(raw.split(b'\r\n---', 1)[1], body)
            self.assertEqual(self.command(self.a, kind + ':R-1', 'private')[0], 0)

    def test_two_homes_scope_never_copies_to_team_or_remote(self):
        remote = self.base / 'team.git'
        def git(path, *args):
            return subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True, text=True).stdout
        git(self.base, 'init', '--bare', '-q', str(remote))
        team.manage(self.a, 'init', str(remote), apply=True, attest=True)
        clone = self.a / '.ws/team'; git(clone, 'add', 'team.json')
        git(clone, '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', 'commit', '-qm', 'fixture')
        git(clone, 'push', '-q', 'origin', 'HEAD'); before = git(remote, 'show-ref')
        other = self.base / 'other-home'; other.mkdir()
        with mock.patch.dict(os.environ, HOME=str(other), USERPROFILE=str(other)):
            team.manage(self.b, 'link', str(remote), apply=True, attest=True)
        for root in (self.a, self.b):
            core.task_new(root, 'T-1', 'synthetic')
            self.assertEqual(self.command(root, 'task:T-1', 'team')[0], 0)
            self.assertEqual(sorted(p.name for p in (root / '.ws/team').iterdir()), ['.git', 'team.json'])
        self.assertEqual(before, git(remote, 'show-ref'))
        self.assertEqual(core.config(self.a)['team_workspace']['id'], core.config(self.b)['team_workspace']['id'])

    def test_notes_invalid_scope_and_auto_policy_refuse_without_writes(self):
        from ws import scope
        core.task_new(self.a, 'T-1', 'synthetic'); path = core.task_path(self.a, 'T-1'); before = path.read_bytes()
        for item in ('note:T-1', 'task:../T-1', 'task:T-1.local'):
            with self.assertRaises(core.WsError): scope.record(self.a, item, 'team')
        with self.assertRaises(core.WsError): scope.record(self.a, 'task:T-1', 'auto')
        cfg = core.config(self.a); cfg['share'] = {'task': 'auto'}
        core.atomic_write(self.a / 'workspace.json', json.dumps(cfg))
        with self.assertRaises(core.WsError): scope.record(self.a, 'task:T-1', 'team')
        self.assertEqual(before, path.read_bytes())

    def test_claim_conflict_and_stale_sha_refuse(self):
        from ws import scope
        core.task_new(self.a, 'T-1', 'synthetic'); core.claim(self.a, 'T-1', 'synthetic')
        path = core.task_path(self.a, 'T-1'); before = path.read_bytes()
        with self.assertRaises(core.WsError): scope.record(self.a, 'task:T-1', 'team', expected_sha='stale')
        core._local_claim_path(self.a, 'T-1').unlink()
        with self.assertRaises(core.WsError): scope.record(self.a, 'task:T-1', 'team')
        self.assertEqual(before, path.read_bytes())
        path.write_text('---\nid: T-1\nscope: private\nscope: team\n---\nbody\n')
        with self.assertRaises(core.WsError): scope.record(self.a, 'task:T-1')

    @needs_symlinks
    def test_note_alias_via_symlinked_record_directory_is_ineligible(self):
        from ws import scope
        private = core.vault(self.a) / 'Personal'; private.mkdir()
        note = private / 'P-1.md'; note.write_text('---\nid: P-1\n---\nPersonal text.\n')
        directory = core.vault(self.a) / 'Decisions'; directory.symlink_to(private, target_is_directory=True)
        before = note.read_bytes()
        with self.assertRaises(core.WsError): scope.record(self.a, 'decision:P-1', 'team')
        self.assertEqual(before, note.read_bytes())

    @needs_symlinks
    def test_symlinked_record_file_is_ineligible_for_read_and_change(self):
        from ws import scope
        target = core.vault(self.a) / 'Personal' / 'R-1.md'; target.parent.mkdir()
        target.write_text('---\nid: R-1\nscope: private\n---\nPersonal text.\n')
        path = core.vault(self.a) / 'Decisions' / 'R-1.md'; path.parent.mkdir(); path.symlink_to(target)
        before = target.read_bytes()
        for value in (None, 'team'):
            with self.assertRaises(core.WsError): scope.record(self.a, 'decision:R-1', value)
        self.assertEqual(before, target.read_bytes())
