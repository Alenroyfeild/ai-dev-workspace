import json
import unittest
from unittest import mock
import test_sharing
from ws import core, sharing


class TeamStatusTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def test_off_by_default_opt_in_preview_and_minimal_record(self):
        from ws import team_status
        with self.assertRaises(core.WsError):team_status.preview(self.root,'Checking receipts','tester')
        plan=team_status.preview(self.root,'Checking receipts <private>hidden note</private>.','tester',enable=True)
        self.assertFalse(core.config(self.root).get('publish_status',False));self.assertFalse((self.clone/'status').exists())
        team_status.apply(self.root,plan)
        self.assertTrue(core.config(self.root)['publish_status'])
        data=json.loads((self.clone/'status/tester.json').read_text())
        self.assertEqual(set(data),{'author','task','line','date'});self.assertNotIn('hidden note',json.dumps(data))
        self.assertEqual(data['task'],'synthetic');self.assertEqual(data['author'],'tester')
        receipts=json.loads((self.root/'.ws/shares.json').read_text())
        self.assertEqual(receipts['_artifacts:'+core.config(self.root)['team_workspace']['id']]['status/tester.json'],core.digest_text(plan['content']))

    def test_changed_task_or_foreign_snapshot_cannot_be_overwritten(self):
        from ws import team_status
        plan=team_status.preview(self.root,'Checking receipts','tester',enable=True)
        core.checkpoint(self.root,'T1','done','Finished.')
        with self.assertRaises(core.WsError):team_status.apply(self.root,plan)
        path=self.clone/'status/tester.json';path.parent.mkdir();path.write_text('foreign snapshot')
        with self.assertRaises(core.WsError):team_status.preview(self.root,'', 'tester',disable=True)
        self.assertEqual(path.read_text(),'foreign snapshot')

    def test_readers_label_last_reported_untrusted_and_refuse_bad_or_private_data(self):
        from ws import team_status
        team_status.apply(self.root,team_status.preview(self.root,'Checking receipts','tester',enable=True))
        text=core.brief(self.root)
        self.assertIn('last reported',text);self.assertIn('untrusted',text);self.assertLess(len(text.split()),200)
        path=self.clone/'status/tester.json';data=json.loads(path.read_text());data['date']='2001-01-01T00:00:00+00:00';path.write_text(json.dumps(data))
        self.assertIn('2001-01-01',core.brief(self.root))
        data['line']='<private>must not load</private>';path.write_text(json.dumps(data))
        self.assertFalse(team_status.list_entries(self.root)['entries']);self.assertIn('Team status warning',core.brief(self.root))

    def test_disable_keeps_private_task_and_records_approved_deletion(self):
        from ws import team_status
        team_status.apply(self.root,team_status.preview(self.root,'Checking receipts','tester',enable=True));before=core.task_path(self.root,'T1').read_bytes()
        plan=team_status.preview(self.root,'','tester',disable=True);self.assertIn('history',plan['warning'])
        team_status.apply(self.root,plan)
        self.assertFalse(core.config(self.root)['publish_status']);self.assertFalse((self.clone/'status/tester.json').exists())
        self.assertEqual(before,core.task_path(self.root,'T1').read_bytes())

    def test_failure_rolls_back_snapshot_consent_and_receipt(self):
        from ws import team_status
        plan=team_status.preview(self.root,'Checking receipts','tester',enable=True);writer=core.atomic_write
        def fail(path,text):
            if path==self.root/'.ws/shares.json':raise OSError('synthetic receipt failure')
            writer(path,text)
        with mock.patch('ws.core.atomic_write',side_effect=fail):
            with self.assertRaises(core.WsError):team_status.apply(self.root,plan)
        self.assertFalse(core.config(self.root).get('publish_status',False));self.assertFalse((self.clone/'status/tester.json').exists())

    def test_deeply_nested_snapshot_cannot_break_private_brief(self):
        from ws import team_status
        path=self.clone/'status/tester.json';path.parent.mkdir();path.write_text('['*1100+'0'+']'*1100)
        self.assertFalse(team_status.list_entries(self.root)['entries'])
        self.assertIn('Team status warning',core.brief(self.root))

    def test_invalid_status_files_do_not_hide_later_valid_author(self):
        from ws import team_status
        team_status.apply(self.root,team_status.preview(self.root,'Checking receipts','zztester',enable=True))
        for i in range(100):(self.clone/'status'/('%03d.json'%i)).write_text('{}')
        listing=team_status.list_entries(self.root)
        self.assertEqual([r['author'] for r in listing['entries']],['zztester'])
        self.assertEqual(listing['warnings'],['100 unsafe or incomplete status files excluded'])

    def test_empty_foreign_status_before_or_after_preview_is_preserved(self):
        from ws import team_status
        plan=team_status.preview(self.root,'Checking receipts','tester',enable=True)
        path=self.clone/'status/tester.json';path.parent.mkdir();path.touch()
        with self.assertRaises(core.WsError):team_status.preview(self.root,'Checking receipts','tester',enable=True)
        with self.assertRaises(core.WsError):team_status.apply(self.root,plan)
        self.assertEqual(path.read_bytes(),b'');self.assertFalse(core.config(self.root).get('publish_status',False))

    def test_brief_shows_two_newest_dates_instead_of_first_aliases(self):
        from ws import team_status
        for author,date in [('alpha','2026-10-14T09:00:00+00:00'),('beta','2026-10-14T09:30:00+01:00'),('zeta','2026-10-14T08:45:00+00:00')]:
            team_status.apply(self.root,team_status.preview(self.root,'Checking receipts',author,enable=True))
            path=self.clone/'status'/(author+'.json');row=json.loads(path.read_text());row['date']=date;core.atomic_write(path,json.dumps(row))
        fields=team_status.brief_fields(self.root);prefixes=[p for p,_,_ in fields]
        self.assertEqual(len(prefixes),2);self.assertIn('alpha',prefixes[0]);self.assertIn('zeta',prefixes[1])
