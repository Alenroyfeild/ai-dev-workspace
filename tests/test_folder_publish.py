import json
import os
import unittest
from unittest import mock
import test_team_folder
from ws import cards,core,knowledge,sharing,team_auto,team_folder


class FolderPublishTests(unittest.TestCase):
    setUp=test_team_folder.TeamFolderTests.setUp
    record=test_team_folder.TeamFolderTests.record
    link=test_team_folder.TeamFolderTests.link

    def inventory(self):
        return {str(p.relative_to(self.folder)):p.read_bytes() for p in self.folder.rglob('*') if p.is_file()}

    def approved(self):
        item=knowledge.add(self.root,'Portable receipt verifier checksum.','repo',True)
        plan=sharing.preview(self.root,item,author='tester');sharing.apply(self.root,plan)
        return item,plan['destination']

    def test_preview_publish_peer_pull_repeat_and_unshare_keep_private_source(self):
        from ws import folder_publish
        self.link();peer=self.base/'peer'
        with mock.patch.dict(os.environ,HOME=str(self.other),USERPROFILE=str(self.other)):
            core.init(peer,'peer',clients=[]);self.link(peer)
        item,name=self.approved();before=self.inventory();plan=folder_publish.preview(self.root)
        self.assertIn(name,plan['files']);self.assertEqual(before,self.inventory())
        self.assertTrue(folder_publish.apply(self.root,plan)['published']);self.assertFalse(folder_publish.preview(self.root)['files'])
        team_auto.pull(peer);self.assertIn('checksum',knowledge.show(peer,'team:'+name.split('/')[-1][:-3])['content'])
        sharing.apply(self.root,sharing.preview(self.root,item,unshare=True));folder_publish.apply(self.root,folder_publish.preview(self.root))
        team_auto.pull(peer);self.assertFalse((peer/'.ws/team'/name).exists())
        self.assertTrue((core.vault(self.root)/'Knowledge'/(item.split(':')[1]+'.md')).exists())

    def test_changed_source_after_preview_refuses_before_any_write(self):
        from ws import folder_publish
        self.link();_,name=self.approved();plan=folder_publish.preview(self.root)
        self.record('A teammate updated the original receipt.');before=self.inventory()
        with self.assertRaises(core.WsError):folder_publish.apply(self.root,plan)
        self.assertEqual(before,self.inventory());self.assertFalse((self.folder/name).exists())

    def test_unapproved_local_file_and_forged_private_projection_never_publish(self):
        from ws import folder_publish
        self.link();_,name=self.approved();before=self.inventory();extra=self.root/'.ws/team/private-note.md';extra.write_text('Keep private.')
        with self.assertRaises(core.WsError):folder_publish.preview(self.root)
        extra.unlink();path=self.root/'.ws/team'/name;path.write_text(path.read_text()+'\n<private>hidden synthetic text</private>\n')
        cards.write(self.root,cards.plan(self.root,'team'))
        receipt=self.root/'.ws/shares.json';state=json.loads(receipt.read_text());approved=state['_artifacts:'+self.team]
        for p in (self.root/'.ws/team').rglob('*'):
            if p.is_file():approved[p.relative_to(self.root/'.ws/team').as_posix()]=core.digest_text(p.read_text())
        receipt.write_text(json.dumps(state))
        with self.assertRaises(core.WsError):folder_publish.preview(self.root)
        self.assertEqual(before,self.inventory())

    def test_source_write_failure_restores_unchanged_owned_writes_and_keeps_backup(self):
        from ws import folder_publish
        self.link();self.approved();folder_publish.apply(self.root,folder_publish.preview(self.root))
        index=self.folder/'INDEX.md';index.write_bytes(index.read_bytes().replace(b'\n',b'\r\n'))
        _,name=self.approved();plan=folder_publish.preview(self.root);before=self.inventory()
        from ws import folder_io
        writer=folder_io.replace
        def fail(folder,identity,path,text,expected):
            if path==name and text is not None:raise OSError('synthetic source failure')
            return writer(folder,identity,path,text,expected)
        with mock.patch('ws.folder_io.replace',side_effect=fail):
            with self.assertRaises(core.WsError):folder_publish.apply(self.root,plan)
        self.assertEqual(before,self.inventory());self.assertTrue((self.root/'.ws/team'/name).exists())
        backups=[json.loads(p.read_text()) for p in (self.root/'.ws/backups').glob('folder-*/state.json')]
        self.assertTrue(any('\r\n' in (b['files'].get('INDEX.md') or '') for b in backups))

    def test_published_source_local_refresh_failure_is_honest_and_retryable(self):
        from ws import folder_publish
        self.link();_,name=self.approved();plan=folder_publish.preview(self.root);writer=core.atomic_write
        def fail(path,text):
            if path.name=='folder-base.json':raise OSError('synthetic refresh failure')
            return writer(path,text)
        with mock.patch('ws.core.atomic_write',side_effect=fail):
            with self.assertRaisesRegex(core.WsError,'published'):folder_publish.apply(self.root,plan)
        self.assertTrue((self.folder/name).exists())
        folder_publish.apply(self.root,folder_publish.preview(self.root))
        self.assertFalse(folder_publish.preview(self.root)['files'])
