import json
import unittest
from ws import core, team_folder
import test_team_folder


class FolderIndexTests(unittest.TestCase):
    setUp=test_team_folder.TeamFolderTests.setUp
    record=test_team_folder.TeamFolderTests.record
    link=test_team_folder.TeamFolderTests.link

    def test_source_index_ignored_and_private_index_derived_from_valid_pairs(self):
        index=self.folder/'INDEX.md';index.write_text('Foreign INDEX must remain byte-for-byte.\n')
        before=index.read_bytes();self.link()
        self.assertNotIn('INDEX.md',team_folder.snapshot(self.root,self.folder)['files'])
        self.assertFalse((self.root/'.ws/team/INDEX.md').exists())
        local=self.root/'.ws/team-index.md';text=local.read_text()
        self.assertIn('CEDAR41',text);self.assertIn('team/entries/'+self.entry+'.md',text)
        self.assertNotIn('Foreign INDEX',text);self.assertEqual(index.read_bytes(),before)
        local.write_text('Private annotation outside markers.\n'+text)
        self.record('Receipt checksum is CYPRESS27.');team_folder.pull(self.root)
        self.assertIn('CYPRESS27',local.read_text());self.assertTrue(local.read_text().startswith('Private annotation outside markers.\n'))
        self.assertEqual(index.read_bytes(),before)

    def test_legacy_mirror_index_and_baseline_are_not_overwritten_or_published(self):
        self.link();legacy=self.root/'.ws/team/INDEX.md';legacy.write_text('Keep old imported/user index.\n')
        base=self.root/'.ws/folder-base.json';saved=json.loads(base.read_text());saved['INDEX.md']=core.digest_text(legacy.read_text());base.write_text(json.dumps(saved))
        self.record('Receipt checksum is ELM55.');team_folder.pull(self.root)
        self.assertEqual(legacy.read_text(),'Keep old imported/user index.\n')
        self.assertNotIn('INDEX.md',json.loads(base.read_text()))
        self.assertIn('ELM55',(self.root/'.ws/team-index.md').read_text())

    def test_partial_pair_keeps_previous_private_index(self):
        self.link();local=self.root/'.ws/team-index.md';before=local.read_bytes()
        (self.folder/'entries'/(self.entry+'.index.md')).write_text('Partial card.')
        with self.assertRaises(core.WsError):team_folder.pull(self.root)
        self.assertEqual(local.read_bytes(),before)
