import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from ws import cli, core


class TeamLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.remote = self.base / 'remote.git'
        self.home = self.base / 'home'; self.home.mkdir()
        patch = mock.patch.dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home), WS_OFFLINE='1')
        patch.start(); self.addCleanup(patch.stop)
        self.a = self.base / 'a'; self.b = self.base / 'b'
        for root in (self.a, self.b): core.init(root, 'synthetic', clients=[])
        self.git(self.base, 'init', '--bare', '-q', str(self.remote))

    def git(self, path, *args):
        return subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True, text=True).stdout

    def command(self, root, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(['--workspace-root', str(root), 'team', *args])
        return code, output.getvalue()

    def test_preview_init_join_and_unlink_preserve_private_data(self):
        private = self.a / 'vault/personal.local.md'; private.write_text('Only amber is private.\n')
        before = (self.a / 'workspace.json').read_bytes()
        self.assertEqual(self.command(self.a, 'init', str(self.remote), '--dry-run')[0], 0)
        self.assertEqual(before, (self.a / 'workspace.json').read_bytes())
        self.assertFalse((self.a / '.ws/team').exists())
        self.assertEqual(self.command(self.a, 'init', str(self.remote), '--yes', '--attest-private', '--auto-pull')[0], 0)
        team = self.a / '.ws/team'
        self.git(team, 'add', 'team.json')
        self.git(team, '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', 'commit', '-qm', 'team fixture')
        self.git(team, 'push', '-q', 'origin', 'HEAD')
        other_home = self.base / 'other-home'; other_home.mkdir()
        with mock.patch.dict(os.environ, HOME=str(other_home), USERPROFILE=str(other_home)):
            self.assertEqual(self.command(self.b, 'link', str(self.remote), '--yes', '--attest-private', '--no-auto-pull')[0], 0)
        a, b = core.config(self.a)['team_workspace'], core.config(self.b)['team_workspace']
        self.assertEqual(a['id'], b['id']); self.assertTrue(a['auto_pull']); self.assertFalse(b['auto_pull'])
        self.assertEqual(a['privacy']['method'], 'attested')
        saved = (self.b / 'workspace.json').read_bytes()
        self.assertEqual(self.command(self.b, 'link', str(self.remote), '--yes')[0], 0)
        self.assertEqual(saved, (self.b / 'workspace.json').read_bytes())
        self.assertEqual(self.command(self.b, 'unlink', '--yes')[0], 0)
        self.assertNotIn('team_workspace', core.config(self.b))
        self.assertTrue((self.b / '.ws/team/team.json').is_file())
        self.assertEqual(private.read_text(), 'Only amber is private.\n')
        self.assertFalse((team / 'vault').exists())
        self.assertEqual(core.doctor(self.a)['team_workspace']['privacy'], 'attested')

    def test_unknown_public_and_credentials_refused_without_writes(self):
        self.assertEqual(self.command(self.a, 'init', str(self.remote), '--yes')[0], 2)
        self.assertFalse((self.a / '.ws/team').exists())
        from ws import team
        for visibility in ('PUBLIC', 'INTERNAL'):
            with mock.patch.dict(os.environ, WS_OFFLINE='0'), mock.patch('ws.team.shutil.which', return_value='fake'), \
                 mock.patch('ws.team.subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps({'visibility': visibility}), '')):
                with self.assertRaises(core.WsError): team.privacy('https://github.com/synthetic/team', True)
        for remote in ('https://user:secret@host.invalid/team', 'ext::unsafe', '-bad', 'https://host.invalid/team?token=secret'):
            with self.assertRaises(core.WsError): team.remote_parts(remote)
        with mock.patch.dict(os.environ, WS_OFFLINE='0'), mock.patch('ws.team.shutil.which', return_value='fake'), \
             mock.patch('ws.team.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '{"visibility":"private"}', '')) as run:
            self.assertEqual(team.privacy('https://gitlab.com/synthetic/team')['method'], 'glab')
            self.assertIn('projects/synthetic%2Fteam', run.call_args.args[0])

    def test_conflicting_link_and_existing_clone_are_kept(self):
        from ws import team
        target = self.a / '.ws/team'; target.mkdir(parents=True); (target / 'mine.txt').write_text('keep')
        self.assertEqual(self.command(self.a, 'init', str(self.remote), '--yes', '--attest-private')[0], 2)
        self.assertEqual((target / 'mine.txt').read_text(), 'keep')
        with self.assertRaises(core.WsError): team.manage(self.a, 'link', str(self.remote), apply=True, attest=True, expected='stale')

    def test_nondefault_port_is_not_verified_as_another_remote(self):
        from ws import team
        self.assertEqual(team.remote_parts('https://github.com:8443/synthetic/team')[0], 'github.com:8443')
        with mock.patch.dict(os.environ, WS_OFFLINE='0'), mock.patch('ws.team.subprocess.run') as run:
            with self.assertRaises(core.WsError): team.privacy('https://github.com:8443/synthetic/team')
            run.assert_not_called()

    def test_config_change_during_clone_preserves_user_edit(self):
        from ws import team
        real_git = team._git
        def changed(path, *args):
            result = real_git(path, *args)
            if args[0] == 'clone':
                cfg = core.config(self.a); cfg['user_note'] = 'keep amber'
                core.atomic_write(self.a / 'workspace.json', json.dumps(cfg))
            return result
        with mock.patch('ws.team._git', side_effect=changed):
            with self.assertRaises(core.WsError): team.manage(self.a, 'init', str(self.remote), apply=True, attest=True)
        self.assertEqual(core.config(self.a)['user_note'], 'keep amber')
        self.assertFalse((self.a / '.ws/team').exists())

    @unittest.skipIf(os.name == 'nt', 'POSIX fake CLI shebang; portable mocked verification is tested separately')
    def test_installed_fake_host_cli_verifies_without_real_service(self):
        from ws import team
        directory = self.base / 'fake-bin'; directory.mkdir()
        binary = directory / 'gh'
        binary.write_text('#!/usr/bin/env python3\nprint(\'{"visibility":"PRIVATE"}\')\n'); binary.chmod(0o755)
        with mock.patch.dict(os.environ, WS_OFFLINE='0', PATH=str(directory) + os.pathsep + os.environ['PATH']):
            self.assertEqual(team.privacy('https://github.com/synthetic/team')['method'], 'gh')

    def test_decline_does_not_clone_or_edit_configuration(self):
        code, preview = self.command(self.a, 'init', str(self.remote), '--dry-run', '--attest-private', '--auto-pull')
        self.assertEqual(code, 0); self.assertTrue(json.loads(preview)['auto_pull'])
        self.assertEqual(json.loads(preview)['privacy'], 'attested')
        before = (self.a / 'workspace.json').read_bytes()
        with mock.patch('builtins.input', return_value='no'):
            self.assertEqual(self.command(self.a, 'init', str(self.remote), '--attest-private')[0], 0)
        self.assertEqual(before, (self.a / 'workspace.json').read_bytes())
        self.assertFalse((self.a / '.ws/team').exists())

    @unittest.skipIf(os.name == 'nt', 'symlink creation may require Windows developer mode')
    def test_symlinked_state_is_rejected_before_writes(self):
        from ws import team
        state = self.a / '.ws'
        if state.exists(): state.rename(self.a / '.ws-original')
        state.symlink_to(self.home, target_is_directory=True)
        with self.assertRaises(core.WsError): team.manage(self.a, 'init', str(self.remote), apply=True, attest=True)
        self.assertFalse((self.home / 'team').exists())
