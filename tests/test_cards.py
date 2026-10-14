import json
import os
import unittest
from unittest import mock
import test_sharing
from ws import core, knowledge, sharing


class CardTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def test_private_cards_index_and_common_search_read_no_source_body(self):
        item = knowledge.add(self.root, 'Bounded queues preserve stable receipts.', 'domain')
        path = core.vault(self.root)/'Knowledge'/(item.split(':')[1]+'.md')
        card = path.with_suffix('.index.md'); self.assertTrue(card.is_file())
        self.assertTrue((path.parent/'INDEX.md').is_file()); reader=core.read_text
        def no_body(p,*args,**kwargs):
            if p == path: raise AssertionError('valid cards should avoid full source reads')
            return reader(p,*args,**kwargs)
        with mock.patch('ws.core.read_text', side_effect=no_body):
            self.assertEqual(len(knowledge.list_entries(self.root,'domain')['entries']),1)
            self.assertEqual(core.search(self.root,'bounded',category='domain')[0]['score'],1)
        source=knowledge.show(self.root,'private:'+path.stem);self.assertIn('Bounded queues',source['content'])
        with (path.parent/'INDEX.md').open('a') as stream:stream.write('\nUser index note.\n')
        knowledge.add(self.root,'A second queue rule.','repo')
        self.assertIn('User index note.',(path.parent/'INDEX.md').read_text())

    def test_team_artifacts_preview_exactly_and_rollback_with_source(self):
        item=knowledge.add(self.root,'Bounded queues <private>hidden sentence</private>.','domain',True)
        plan=sharing.preview(self.root,item);self.assertTrue(plan['artifacts']);self.assertFalse((self.clone/'INDEX.md').exists())
        sharing.apply(self.root,plan);self.assertTrue((self.clone/'INDEX.md').is_file())
        card=(self.clone/plan['destination']).with_suffix('.index.md');self.assertTrue(card.is_file())
        self.assertNotIn('hidden sentence',card.read_text());self.assertTrue(sharing.preview(self.root,item)['unchanged'])
        removal=sharing.preview(self.root,item,unshare=True);sharing.apply(self.root,removal)
        self.assertFalse(card.exists());self.assertIn('entries/',plan['artifact_diff'])
        plan=sharing.preview(self.root,item);writer=core.atomic_write
        for error in (OSError, core.WsError):
            def fail_index(p,text):
                if p==self.clone/'INDEX.md':raise error('synthetic index failure')
                writer(p,text)
            with mock.patch('ws.core.atomic_write',side_effect=fail_index):
                with self.assertRaises(core.WsError):sharing.apply(self.root,plan)
            self.assertFalse((self.clone/plan['destination']).exists());self.assertFalse(card.exists())

    def test_stale_card_falls_back_and_unmarked_index_is_never_overwritten(self):
        item=knowledge.add(self.root,'Old bounded queue rule.','repo');path=core.vault(self.root)/'Knowledge'/(item.split(':')[1]+'.md')
        core.atomic_write(path,path.read_text().replace('Old bounded queue rule.','Newest corrected receipt rule.'))
        self.assertIn('Newest corrected',knowledge.list_entries(self.root,'repo')['entries'][0]['summary'])
        index=path.parent/'INDEX.md';index.write_text('User-owned index.\n');before=sorted(path.parent.iterdir())
        with self.assertRaises(core.WsError):knowledge.add(self.root,'Another bounded queue rule.','repo')
        self.assertEqual(index.read_text(),'User-owned index.\n');self.assertEqual(before,sorted(path.parent.iterdir()))

    @unittest.skipIf(os.name=='nt','symlink fixture requires Windows developer mode')
    def test_symlinked_card_and_stale_artifact_preview_refuse(self):
        item=knowledge.add(self.root,'Bounded queue rule.','repo',True);plan=sharing.preview(self.root,item);sharing.apply(self.root,plan)
        index=self.clone/'INDEX.md';index.write_text(index.read_text()+'\nUser note.\n')
        removal=sharing.preview(self.root,item,unshare=True);index.write_text(index.read_text()+'Changed after preview.\n')
        with self.assertRaises(core.WsError):sharing.apply(self.root,removal)
        card=(self.clone/plan['destination']).with_suffix('.index.md');card.unlink();card.symlink_to(core.task_path(self.root,'T1'))
        with self.assertRaises(core.WsError):sharing.preview(self.root,item)

    def test_crlf_managed_index_preserves_user_text_outside_markers(self):
        item=knowledge.add(self.root,'Bounded queues preserve receipts.','repo')
        directory=core.vault(self.root)/'Knowledge';index=directory/'INDEX.md'
        index.write_bytes(b'User before\r\n'+index.read_bytes().replace(b'\n',b'\r\n')+b'\r\nUser after\r\n')
        knowledge.add(self.root,'A second portable queue rule.','repo')
        self.assertTrue(index.read_bytes().startswith(b'User before\r\n'))
        self.assertTrue(index.read_bytes().endswith(b'\r\nUser after\r\n'))

    def test_legacy_private_capture_and_secret_text_never_reach_cards(self):
        item=knowledge.add(self.root,'Bounded queues preserve receipts.','repo')
        path=core.vault(self.root)/'Knowledge'/(item.split(':')[1]+'.md')
        path.write_text(path.read_text()+'\n<private>legacy hidden phrase</private>\napi_key=syntheticcredentialvalue\n<!-- ws:captured:x -->\nDecision: hidden capture phrase\n<!-- /ws:captured -->\n')
        knowledge.add(self.root,'A second portable queue rule.','repo')
        for artifact in (path.with_suffix('.index.md'),path.parent/'INDEX.md'):
            for private in ('legacy hidden phrase','syntheticcredentialvalue','hidden capture phrase'):
                self.assertNotIn(private,artifact.read_text())

    def test_invalid_artifact_receipt_refuses_before_writing(self):
        item=knowledge.add(self.root,'Bounded queue rule.','repo',True)
        receipt=self.root/'.ws/shares.json';team_id=core.config(self.root)['team_workspace']['id']
        core.atomic_write(receipt,json.dumps({'_artifacts:'+team_id:[]}))
        plan=sharing.preview(self.root,item)
        with self.assertRaises(core.WsError):sharing.apply(self.root,plan)
        self.assertFalse((self.clone/plan['destination']).exists())

    def test_malformed_card_envelope_falls_back_to_source(self):
        from ws import cards
        item=knowledge.add(self.root,'Bounded queue rule.','repo')
        path=core.vault(self.root)/'Knowledge'/(item.split(':')[1]+'.md');card=path.with_suffix('.index.md')
        payload=card.read_text().split(cards.HEAD)[1].split(cards.TAIL)[0]
        card.write_text(cards.TAIL+'\n'+cards.HEAD+payload)
        self.assertFalse(knowledge.list_entries(self.root,'repo')['entries'][0].get('summary_snapshot',False))

    def test_default_search_omits_managed_metadata_but_keeps_user_index_text(self):
        before=len(core.search(self.root,'bounded'))
        item=knowledge.add(self.root,'Bounded queues preserve receipts.','repo')
        hits=core.search(self.root,'bounded');self.assertEqual(len(hits),before+1)
        index=core.vault(self.root)/'Knowledge/INDEX.md'
        with index.open('a') as stream:stream.write('User bounded queue note.\n')
        hits=core.search(self.root,'bounded');self.assertEqual(len(hits),before+2)
        shown=next(h for h in hits if h['path']==index.relative_to(self.root).as_posix())
        self.assertTrue(shown['lines'][0].startswith(str(len(index.read_text().splitlines()))+':'))

    def test_untrusted_card_text_is_bounded_on_read(self):
        from ws import cards
        item=knowledge.add(self.root,'Bounded queue rule.','repo')
        path=core.vault(self.root)/'Knowledge'/(item.split(':')[1]+'.md');card=path.with_suffix('.index.md')
        data=json.loads(card.read_text().split(cards.HEAD)[1].split(cards.TAIL)[0]);data['row']['summary']='x'*10000
        card.write_text(cards.HEAD+'\n'+json.dumps(data)+'\n'+cards.TAIL+'\n')
        self.assertLessEqual(len(knowledge.list_entries(self.root,'repo')['entries'][0]['summary']),240)
