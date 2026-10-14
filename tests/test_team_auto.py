import contextlib
import io
import json
import plistlib
import unittest
from unittest import mock
import test_sharing
from ws import cli,core,sharing,team


class TeamAutoTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def consent(self):
        cfg=core.config(self.root);cfg['team_workspace']['auto_pull']=True;core.atomic_write(self.root/'workspace.json',json.dumps(cfg))

    def test_no_consent_means_no_git_or_scheduler(self):
        from ws import team_auto
        with mock.patch('ws.team_auto.team_sync._git',side_effect=AssertionError('no Git without consent')):
            self.assertIsNone(team_auto.maybe_pull(self.root))
            self.assertTrue(team_auto.pull(self.root,automatic=True)['skipped'])
        with self.assertRaises(core.WsError):team_auto.schedule(self.root,'09:15')

    def test_pull_only_updates_despite_unapproved_note_and_never_pushes(self):
        from ws import team_auto
        team._git(self.clone,'add','team.json');team._git(self.clone,'-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','-qm','fixture');team._git(self.clone,'push','-q','origin','HEAD')
        peer=self.base/'peer';team._git(self.base,'clone','-q',str(self.remote),str(peer));(peer/'notice.md').write_text('Remote notice.')
        team._git(peer,'add','notice.md');team._git(peer,'-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','-qm','notice');team._git(peer,'push','-q')
        (self.clone/'private-note.md').write_text('Unapproved local note.');self.consent();before=team._git(self.remote,'show-ref')
        result=team_auto.pull(self.root,automatic=True)
        self.assertTrue(result['updated']);self.assertFalse(result['pushed']);self.assertEqual(before,team._git(self.remote,'show-ref'))
        self.assertEqual((self.clone/'private-note.md').read_text(),'Unapproved local note.')

    def test_checkpoint_and_share_attempt_only_consented_pull_after_lock(self):
        from ws import team_auto
        self.consent()
        with mock.patch('ws.team_auto.pull',return_value={'updated':False,'pushed':False}) as pull:
            core.checkpoint(self.root,'T1','in_progress','Inspect receipts.')
            sharing.apply(self.root,sharing.preview(self.root,'task:T1'))
        self.assertEqual(pull.call_count,2)
        with mock.patch('ws.team_auto.pull',side_effect=core.WsError('synthetic offline')):
            result=core.checkpoint(self.root,'T1','in_progress','Save local memory first.')
        self.assertIn('warning',result['team_update']);self.assertIn('Save local memory first',core.brief(self.root))

    def test_scheduler_preview_confirm_and_revoke_consent(self):
        from ws import team_auto
        self.consent()
        with mock.patch('ws.team_auto.sys.platform','darwin'):
            plan=team_auto.schedule(self.root,'09:15');path=self.base/'Library/LaunchAgents'/(plan['label']+'.plist')
            self.assertFalse(path.exists());data=plistlib.loads(plan['content'].encode())
            self.assertEqual(data['StartCalendarInterval'],{'Hour':9,'Minute':15});self.assertEqual(data['ProgramArguments'][-2:],['--pull-only','--automatic'])
            with mock.patch('ws.team_auto.subprocess.run',return_value=mock.Mock(returncode=0)) as launch:
                result=team_auto.schedule(self.root,'09:15',apply=True,expected=plan)
            self.assertTrue(result['activated']);self.assertTrue(path.exists());self.assertIn('bootstrap',launch.call_args[0][0])
            cfg=core.config(self.root);cfg['team_workspace']['auto_pull']=False;core.atomic_write(self.root/'workspace.json',json.dumps(cfg))
            self.assertTrue(team_auto.pull(self.root,automatic=True)['skipped'])

    def test_unmanaged_scheduler_and_failed_registration_preserve_user_files(self):
        from ws import team_auto
        self.consent()
        with mock.patch('ws.team_auto.sys.platform','darwin'):
            plan=team_auto.schedule(self.root,'09:15');path=self.base/'Library/LaunchAgents'/(plan['label']+'.plist');path.parent.mkdir(parents=True);path.write_text('User job.')
            with self.assertRaises(core.WsError):team_auto.schedule(self.root,'09:15')
            self.assertEqual(path.read_text(),'User job.');path.unlink()
            with mock.patch('ws.team_auto.subprocess.run',side_effect=OSError('synthetic launchd failure')):
                with self.assertRaises(core.WsError):team_auto.schedule(self.root,'09:15',apply=True,expected=plan)
            self.assertFalse(path.exists())

    def test_non_mac_scheduler_only_suggests_and_bad_time_refuses(self):
        from ws import team_auto
        self.consent()
        with mock.patch('ws.team_auto.sys.platform','linux'):
            plan=team_auto.schedule(self.root,'09:15');self.assertFalse(plan['supported']);self.assertIn('cron',plan['suggestion'])
        for value in ('25:00','09:61','09:15; command'):
            with self.assertRaises(core.WsError):team_auto.schedule(self.root,value)

    def test_session_start_hook_pulls_but_plain_brief_does_not(self):
        from ws import team_auto
        self.consent()
        with mock.patch('ws.team_auto.pull',return_value={'updated':False,'pushed':False}) as pull:
            core.brief(self.root);self.assertFalse(pull.called)
            with mock.patch('sys.stdin',io.StringIO(json.dumps({'hook_event_name':'SessionStart'}))),contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cli.main(['--workspace-root',str(self.root),'brief','--hook','--client','codex']),0)
            self.assertTrue(pull.called);self.assertIn('hookSpecificOutput',json.loads(out.getvalue()))

    def test_schedule_changed_after_preview_refuses_before_launch(self):
        from ws import team_auto
        self.consent()
        with mock.patch('ws.team_auto.sys.platform','darwin'):
            plan=team_auto.schedule(self.root,'09:15');path=self.base/'Library/LaunchAgents'/(plan['label']+'.plist');core.atomic_write(path,plan['content'])
            data=plistlib.loads(path.read_bytes());data['ProgramArguments']=['foreign'];path.write_bytes(plistlib.dumps(data))
            with mock.patch('ws.team_auto._launch',side_effect=AssertionError('no launch before validation')):
                with self.assertRaises(core.WsError):team_auto.schedule(self.root,'09:15',True,plan)

    def test_automatic_deadline_refuses_expired_git_call_before_spawn(self):
        from ws import team_sync
        token=team_sync.AUTO_DEADLINE.set(0)
        try:
            with mock.patch('ws.team_sync.subprocess.run',side_effect=AssertionError('expired command must not spawn')):
                with self.assertRaises(core.WsError):team_sync._git(self.clone,'status')
        finally:team_sync.AUTO_DEADLINE.reset(token)

    def test_invalid_calendar_is_preserved_and_reschedule_exposes_old_time(self):
        from ws import team_auto
        self.consent()
        with mock.patch('ws.team_auto.sys.platform','darwin'):
            plan=team_auto.schedule(self.root,'09:15');path=self.base/'Library/LaunchAgents'/(plan['label']+'.plist');core.atomic_write(path,plan['content'])
            data=plistlib.loads(path.read_bytes());data['StartCalendarInterval']={'Hour':99,'Minute':15};path.write_bytes(plistlib.dumps(data));before=path.read_bytes()
            with self.assertRaises(core.WsError):team_auto.schedule(self.root,'10:30')
            self.assertEqual(before,path.read_bytes())
            core.atomic_write(path,plan['content']);new=team_auto.schedule(self.root,'10:30')
            self.assertEqual(new['previous_time'],'09:15')
            self.assertEqual(new['time'],'10:30')

    def test_contended_automatic_pull_returns_without_git(self):
        from ws import team_auto
        self.consent()
        with core.lock(self.root),mock.patch('ws.team_sync._git',side_effect=AssertionError('must not reach Git')):
            result=team_auto.maybe_pull(self.root)
        self.assertIn('warning',result);self.assertFalse(result['pushed'])
