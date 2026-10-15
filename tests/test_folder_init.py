import json
import os
import unittest
from pathlib import Path
from unittest import mock
import test_team_folder
from ws import core,team_folder


class FolderInitTests(unittest.TestCase):
    setUp=test_team_folder.TeamFolderTests.setUp
    record=test_team_folder.TeamFolderTests.record

    def host(self):
        path=self.base/'new-team';path.mkdir();return path

    def test_preview_attestation_init_two_homes_and_repeat(self):
        host=self.host();plan=team_folder.initialize(self.root,str(host),attest=True)
        self.assertFalse(list(host.iterdir()));self.assertFalse((self.root/'.ws/team').exists())
        with self.assertRaises(core.WsError):team_folder.initialize(self.root,str(host),True,False,False,plan)
        self.assertFalse(list(host.iterdir()))
        result=team_folder.initialize(self.root,str(host),True,True,False,plan)
        self.assertTrue(result['initialized']);before=(host/'team.json').read_bytes()
        self.assertTrue(team_folder.initialize(self.root,str(host),attest=True)['already'])
        peer=self.base/'peer'
        with mock.patch.dict(os.environ,HOME=str(self.other),USERPROFILE=str(self.other)):
            core.init(peer,'peer',clients=[]);join=team_folder.link(peer,str(host),attest=True)
            team_folder.link(peer,str(host),True,True,False,join)
        self.assertEqual(core.config(self.root)['team_workspace']['id'],core.config(peer)['team_workspace']['id'])
        self.assertEqual(before,(host/'team.json').read_bytes())

    def test_nonempty_or_changed_folder_never_overwrites_user_files(self):
        host=self.host();plan=team_folder.initialize(self.root,str(host),attest=True)
        note=host/'notes.md';note.write_text('Retain this user file.')
        with self.assertRaises(core.WsError):team_folder.initialize(self.root,str(host),True,True,False,plan)
        self.assertEqual(note.read_text(),'Retain this user file.');self.assertFalse((host/'team.json').exists())
        with self.assertRaises(core.WsError):team_folder.initialize(self.root,str(self.root),attest=True)

    def test_existing_manifest_requires_link_and_remains_intact(self):
        before=(self.folder/'team.json').read_bytes()
        with self.assertRaisesRegex(core.WsError,'link'):team_folder.initialize(self.root,str(self.folder),attest=True)
        self.assertEqual(before,(self.folder/'team.json').read_bytes())

    def test_concurrent_manifest_creation_is_not_overwritten(self):
        host=self.host();plan=team_folder.initialize(self.root,str(host),attest=True);original=Path.open
        def race(path,*args,**kwargs):
            if path==host/'team.json' and args and args[0]=='x':
                with original(path,'w') as writer:writer.write('Foreign manifest.')
            return original(path,*args,**kwargs)
        with mock.patch.object(Path,'open',race):
            with self.assertRaises(core.WsError):team_folder.initialize(self.root,str(host),True,True,False,plan)
        self.assertEqual((host/'team.json').read_text(),'Foreign manifest.')
        self.assertNotIn('team_workspace',core.config(self.root))

    def test_local_link_failure_reports_source_initialized_and_preserves_it(self):
        host=self.host();plan=team_folder.initialize(self.root,str(host),attest=True)
        with mock.patch('ws.team_folder.link',side_effect=core.WsError('synthetic local failure')):
            with self.assertRaisesRegex(core.WsError,'initialized'):team_folder.initialize(self.root,str(host),True,True,False,plan)
        self.assertEqual(json.loads((host/'team.json').read_text())['id'],plan['team'])
        self.assertNotIn('team_workspace',core.config(self.root))

    @unittest.skipIf(os.name=='nt','Symlink creation may require Windows privileges.')
    def test_user_selected_alias_initializes_only_the_canonical_folder(self):
        host=self.host();alias=self.base/'cloud-alias';alias.symlink_to(host,target_is_directory=True)
        plan=team_folder.initialize(self.root,str(alias),attest=True)
        self.assertEqual(plan['source'],str(host))
        team_folder.initialize(self.root,str(alias),True,True,False,plan);alias.unlink()
        self.assertEqual(core.config(self.root)['team_workspace']['remote'],str(host))
        self.assertEqual(json.loads((host/'team.json').read_text())['id'],plan['team'])
