import os
import unittest
from unittest import mock
import test_sharing
from ws import core, knowledge, sharing, team


class TeamSyncTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def bootstrap(self):
        team._git(self.clone,'add','team.json')
        team._git(self.clone,'-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','-qm','fixture')
        team._git(self.clone,'push','-q','origin','HEAD')

    def approved(self):
        item=knowledge.add(self.root,'Receipt checksum is CEDAR41.','repo',True)
        sharing.apply(self.root,sharing.preview(self.root,item))

    def test_preview_then_publish_only_approved_blobs_and_repeat_is_noop(self):
        from ws import team_sync
        self.bootstrap(); self.approved()
        before=team._git(self.remote,'show-ref')
        plan=team_sync.preview(self.root)
        self.assertTrue(plan['files']);self.assertEqual(before,team._git(self.remote,'show-ref'))
        result=team_sync.apply(self.root,plan);self.assertTrue(result['pushed'])
        self.assertFalse(team_sync.preview(self.root)['files'])
        self.assertFalse(team._git(self.clone,'status','--porcelain'))

    def test_unapproved_file_or_commit_blocks_without_discard(self):
        from ws import team_sync
        self.bootstrap();self.approved();extra=self.clone/'notes.md';extra.write_text('Unapproved private note.')
        with self.assertRaises(core.WsError):team_sync.preview(self.root)
        self.assertEqual(extra.read_text(),'Unapproved private note.');extra.unlink()
        team._git(self.clone,'add','entries','INDEX.md')
        team._git(self.clone,'-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','-qm','unapproved history')
        with self.assertRaises(core.WsError):team_sync.preview(self.root)

    def test_changed_after_preview_and_later_public_visibility_block(self):
        from ws import team_sync
        self.bootstrap();self.approved();plan=team_sync.preview(self.root)
        index=self.clone/'INDEX.md';index.write_text(index.read_text()+'private edit')
        with self.assertRaises(core.WsError):team_sync.apply(self.root,plan)
        index.write_text(plan['files']['INDEX.md'])
        with mock.patch('ws.team.privacy',side_effect=core.WsError('Remote now public')):
            with self.assertRaises(core.WsError):team_sync.apply(self.root,plan)

    def test_pull_fast_forwards_but_remote_advance_after_preview_refuses(self):
        from ws import team_sync
        self.bootstrap();peer=self.base/'peer';team._git(self.base,'clone','-q',str(self.remote),str(peer))
        (peer/'notice.md').write_text('Remote-only notice.')
        team._git(peer,'add','notice.md');team._git(peer,'-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','-qm','remote notice');team._git(peer,'push','-q')
        self.assertFalse(team_sync.preview(self.root)['files']);self.assertTrue((self.clone/'notice.md').exists())
        self.approved();plan=team_sync.preview(self.root)
        (peer/'notice.md').write_text('New remote notice.')
        team._git(peer,'add','notice.md');team._git(peer,'-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit','-qm','remote update');team._git(peer,'push','-q')
        with self.assertRaises(core.WsError):team_sync.apply(self.root,plan)

    def test_init_can_publish_only_the_exact_linked_manifest(self):
        from ws import team_sync
        plan=team_sync.preview(self.root);self.assertEqual(set(plan['files']),{'team.json'})
        self.assertTrue(team_sync.apply(self.root,plan)['pushed'])

    def test_forged_receipt_cannot_publish_private_text(self):
        import json
        from ws import team_sync
        self.bootstrap();self.approved()
        entry=next(p for p in (self.clone/'entries').glob('*.md') if not p.name.endswith('.index.md'))
        entry.write_text(entry.read_text()+'\n<private>hidden phrase</private>\n')
        receipt=self.root/'.ws/shares.json';state=json.loads(receipt.read_text())
        state['_artifacts:'+core.config(self.root)['team_workspace']['id']]['entries/'+entry.name]=core.digest_text(entry.read_text())
        receipt.write_text(json.dumps(state))
        with self.assertRaises(core.WsError):team_sync.preview(self.root)

    def test_unshare_publishes_approved_removals_and_keeps_private_source(self):
        from ws import team_sync
        self.bootstrap();item=knowledge.add(self.root,'Portable receipt checksum.','repo',True)
        sharing.apply(self.root,sharing.preview(self.root,item));team_sync.apply(self.root,team_sync.preview(self.root))
        sharing.apply(self.root,sharing.preview(self.root,item,unshare=True))
        plan=team_sync.preview(self.root);self.assertTrue(any(text is None for text in plan['files'].values()))
        team_sync.apply(self.root,plan)
        self.assertTrue((core.vault(self.root)/'Knowledge'/(item.split(':')[1]+'.md')).exists())

    def test_git_directory_redirect_is_refused_before_git_runs(self):
        from ws import team_sync
        metadata=self.clone/'.git';retained=self.clone/'retained-metadata';metadata.rename(retained)
        metadata.write_text('gitdir: '+str(retained)+'\n')
        with mock.patch('ws.team_sync._git',side_effect=AssertionError('must refuse before Git')):
            with self.assertRaises(core.WsError):team_sync.preview(self.root)

    def test_inherited_git_directory_cannot_redirect_sync(self):
        from ws import team_sync
        with mock.patch.dict(os.environ,GIT_DIR=str(self.remote)):
            self.assertEqual(set(team_sync.preview(self.root)['files']),{'team.json'})

    def test_core_worktree_redirect_cannot_make_sync_touch_another_repo(self):
        from ws import team_sync
        other=self.base/'other';other.mkdir()
        team._git(self.clone,'config','core.worktree',str(other))
        with self.assertRaisesRegex(core.WsError,'Git metadata'):
            team_sync.preview(self.root)

    def test_push_success_is_reported_if_tracking_update_fails_and_files_retained(self):
        from ws import team_sync
        self.bootstrap();self.approved();plan=team_sync.preview(self.root);runner=team_sync._git
        def fail(clone,*args,**kwargs):
            if args[0]=='update-ref':raise core.WsError('synthetic tracking failure')
            return runner(clone,*args,**kwargs)
        with mock.patch('ws.team_sync._git',side_effect=fail):
            with self.assertRaisesRegex(core.WsError,'Push succeeded'):
                team_sync.apply(self.root,plan)
        for name,text in plan['files'].items():self.assertEqual(sharing._text(self.clone/name),text)
        self.assertIn('INDEX.md',team._git(self.remote,'ls-tree','-r','--name-only','refs/heads/'+plan['branch']))
        with self.assertRaisesRegex(core.WsError,'Resolve manually'):team_sync.preview(self.root)

    def test_minimal_status_snapshot_requires_the_same_exact_approval(self):
        import json
        from ws import team_sync
        self.bootstrap();path=self.clone/'status/tester.json';path.parent.mkdir();text=json.dumps({'author':'tester','task':'Receipt guard','line':'Checking retries','date':'2026-10-14'})+'\n';path.write_text(text)
        with self.assertRaises(core.WsError):team_sync.preview(self.root)
        receipt=self.root/'.ws/shares.json';receipt.write_text(json.dumps({'_artifacts:'+core.config(self.root)['team_workspace']['id']:{'status/tester.json':core.digest_text(text)}}))
        plan=team_sync.preview(self.root);self.assertEqual(plan['files']['status/tester.json'],text)
        self.assertTrue(team_sync.apply(self.root,plan)['pushed'])
