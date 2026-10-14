import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from ws import cards, core, knowledge


class TeamFolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name).resolve()
        self.home=self.base/'home-a';self.home.mkdir();self.other=self.base/'home-b';self.other.mkdir()
        patch=mock.patch.dict(os.environ,HOME=str(self.home),USERPROFILE=str(self.home),WS_OFFLINE='1');patch.start();self.addCleanup(patch.stop)
        self.root=self.base/'a';core.init(self.root,'synthetic',clients=[])
        self.folder=self.base/'shared';self.folder.mkdir();self.team='a'*32;self.entry='b'*32
        (self.folder/'team.json').write_text(json.dumps({'kind':'ai-dev-workspace-team','schema_version':1,'id':self.team}))
        self.record('Receipt checksum is CEDAR41.')

    def record(self, body):
        directory=self.folder/'entries';directory.mkdir(exist_ok=True)
        text='---\nid: '+self.entry+'\nteam: '+self.team+'\nsource: knowledge:K1\ncategory: repo\nauthor: tester\nsource_sha: '+'c'*64+'\ndate: 2026-10-14T00:00:00Z\n---\n'+body+'\n'
        path=self.root/'.ws/team/entries'/(self.entry+'.md');row,_=knowledge._read(self.root,path,'team',self.team,raw=text)
        (directory/path.name).write_text(text)
        (directory/(self.entry+'.index.md')).write_text(cards.HEAD+'\n'+json.dumps({'schema':1,'source_bytes':len(text.encode()),'row':row,'counts':{'receipt':1}})+'\n'+cards.TAIL+'\n')

    def link(self, root=None):
        from ws import team_folder
        root=root or self.root;plan=team_folder.link(root,str(self.folder),attest=True)
        return team_folder.link(root,str(self.folder),True,True,False,plan)

    def test_preview_attestation_two_homes_reads_and_unlink_preserve_source(self):
        from ws import team,team_folder
        before={str(p.relative_to(self.folder)):p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}
        plan=team_folder.link(self.root,str(self.folder),attest=True)
        self.assertFalse((self.root/'.ws/team').exists());self.assertFalse(plan['publishes'])
        with self.assertRaises(core.WsError):team_folder.link(self.root,str(self.folder),True)
        self.link();peer=self.base/'b'
        with mock.patch.dict(os.environ,HOME=str(self.other),USERPROFILE=str(self.other)):
            core.init(peer,'peer',clients=[]);self.link(peer)
            self.assertIn('CEDAR41',knowledge.show(peer,'team:'+self.entry)['content'])
        self.assertTrue(knowledge.show(self.root,'team:'+self.entry)['untrusted'])
        team.manage(self.root,'unlink',apply=True)
        self.assertTrue((self.root/'.ws/team/team.json').is_file())
        self.assertEqual(before,{str(p.relative_to(self.folder)):p.read_bytes() for p in self.folder.rglob('*') if p.is_file()})

    def test_changed_folder_after_preview_refuses_without_link(self):
        from ws import team_folder
        plan=team_folder.link(self.root,str(self.folder),attest=True);self.record('Changed receipt.')
        with self.assertRaises(core.WsError):team_folder.link(self.root,str(self.folder),True,True,False,plan)
        self.assertNotIn('team_workspace',core.config(self.root));self.assertFalse((self.root/'.ws/team').exists())

    def test_pull_updates_and_local_edits_are_never_overwritten(self):
        from ws import team_auto
        self.link();self.record('Receipt checksum is CYPRESS27.')
        self.assertTrue(team_auto.pull(self.root)['updated']);self.assertIn('CYPRESS27',knowledge.show(self.root,'team:'+self.entry)['content'])
        path=self.root/'.ws/team/entries'/(self.entry+'.md');path.write_text(path.read_text()+'Local edit.')
        self.record('Receipt checksum is CEDAR99.')
        with self.assertRaises(core.WsError):team_auto.pull(self.root)
        self.assertIn('Local edit.',path.read_text());self.assertIn('CYPRESS27',path.read_text())

    def test_conflict_copy_partial_card_and_identity_change_retain_old_snapshot(self):
        from ws import team_auto
        self.link();before=knowledge.show(self.root,'team:'+self.entry)['content']
        conflict=self.folder/'entries'/(self.entry+' (conflicted copy).md');conflict.write_text('Conflict copy.')
        with self.assertRaises(core.WsError):team_auto.pull(self.root)
        conflict.unlink();card=self.folder/'entries'/(self.entry+'.index.md');card.write_text('Partial JSON {')
        with self.assertRaises(core.WsError):team_auto.pull(self.root)
        self.assertEqual(knowledge.show(self.root,'team:'+self.entry)['content'],before)
        self.record('Complete again.');self.assertTrue(team_auto.pull(self.root)['updated'])
        (self.folder/'team.json').write_text(json.dumps({'kind':'ai-dev-workspace-team','schema_version':1,'id':'d'*32}))
        with self.assertRaises(core.WsError):team_auto.pull(self.root)

    def test_folder_cannot_be_inside_private_workspace_or_symlink(self):
        from ws import team_folder
        with self.assertRaises(core.WsError):team_folder.link(self.root,str(self.root),attest=True)
        if os.name!='nt':
            alias=self.base/'alias';alias.symlink_to(self.folder,target_is_directory=True)
            with self.assertRaises(core.WsError):team_folder.link(self.root,str(alias),attest=True)

    def test_snapshot_write_failure_rolls_back_and_normal_sync_cannot_publish(self):
        from ws import team_auto,team_sync
        self.link();path=self.root/'.ws/team/entries'/(self.entry+'.md');before=path.read_bytes();self.record('Changed receipt.')
        writer=core.atomic_write
        def fail(target,text):
            if target.name=='folder-base.json':raise OSError('synthetic baseline failure')
            return writer(target,text)
        with mock.patch('ws.core.atomic_write',side_effect=fail):
            with self.assertRaises(core.WsError):team_auto.pull(self.root)
        self.assertEqual(path.read_bytes(),before)
        with self.assertRaises(core.WsError):team_sync.preview(self.root)

    def test_consent_question_cannot_refresh_an_unshown_folder_preview(self):
        import contextlib,io
        from ws import cli
        answers=iter(('y','n'))
        def answer(prompt):
            if 'automatically' in prompt:self.record('Changed while deciding.')
            return next(answers)
        with mock.patch('builtins.input',side_effect=answer),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--workspace-root',str(self.root),'team','link',str(self.folder),'--folder','--attest-private']),2)
        self.assertNotIn('team_workspace',core.config(self.root))

    def test_card_metadata_must_match_the_entry_not_only_its_revision(self):
        from ws import team_auto
        self.link();local=self.root/'.ws/team/entries'/(self.entry+'.index.md');before=local.read_bytes()
        path=self.folder/'entries'/(self.entry+'.index.md');data=json.loads(path.read_text().split(cards.HEAD)[1].split(cards.TAIL)[0])
        data['row']['summary']='Forged summary with the original body revision.'
        path.write_text(cards.HEAD+'\n'+json.dumps(data)+'\n'+cards.TAIL+'\n')
        with self.assertRaises(core.WsError):team_auto.pull(self.root)
        self.assertEqual(local.read_bytes(),before)
