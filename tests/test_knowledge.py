import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from testutil import needs_symlinks
from unittest import mock
import test_sharing
from ws import cli, core, sharing


class KnowledgeTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def test_categories_private_default_team_projection_and_layer_ids(self):
        from ws import knowledge
        for category in knowledge.CATEGORIES:
            item = knowledge.add(self.root, 'Portable queue contracts remain bounded.', category)
            self.assertEqual(core.parse_meta((core.vault(self.root) / 'Knowledge' / (item.split(':')[1]+'.md')).read_text())['scope'], 'private')
            self.assertEqual(len(knowledge.list_entries(self.root, category)['entries']), 1)
        item = knowledge.add(self.root, 'Use bounded queues <private>private sentence</private>.', 'domain', True)
        plan = sharing.preview(self.root, item); self.assertIn('category: domain', plan['content']); sharing.apply(self.root, plan)
        rows = knowledge.list_entries(self.root, 'domain')['entries']; self.assertEqual({r['layer'] for r in rows}, {'private', 'team'})
        self.assertEqual(len({r['key'] for r in rows}), len(rows))
        result = knowledge.show(self.root, 'team:'+plan['entry']); self.assertNotIn('private sentence', result['content'])
        self.assertTrue(result['untrusted']); self.assertIn('source_sha', result)
        self.assertEqual(result['team'], core.config(self.root)['team_workspace']['id']); self.assertIn('date', result)
        self.assertEqual(result['source_sha'], plan['source_sha']); self.assertNotEqual(result['revision'], result['source_sha'])
        matches = core.search(self.root, 'bounded', category='domain'); self.assertTrue(matches)
        self.assertTrue(all(m['category']=='domain' for m in matches))

    def test_invalid_category_conflict_private_markers_and_symlink_refuse(self):
        from ws import knowledge
        with self.assertRaises(core.WsError): knowledge.add(self.root, 'Queue contract.', 'invented')
        with self.assertRaises(core.WsError): knowledge.show(self.root, 'team:../escape')
        item = knowledge.add(self.root, 'Queue contract.', 'repo'); path = core.vault(self.root)/'Knowledge'/(item.split(':')[1]+'.md')
        path.write_text(path.read_text()+'\n<<<<<<< left\nbroken\n>>>>>>> right\n')
        listing = knowledge.list_entries(self.root); self.assertFalse(listing['entries']); self.assertTrue(listing['warnings'])
        with self.assertRaises(core.WsError): knowledge.show(self.root, 'private:'+item.split(':')[1])

    def test_cli_and_mcp_category_calls_never_publish(self):
        from ws import knowledge
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(['--workspace-root',str(self.root),'know','add','Bounded queue contract.','--category','product']),0)
        item = json.loads(out.getvalue())['saved']; key='private:'+item.split(':')[1]
        for args in (['know','list','--category','product'], ['know','show',key], ['search','bounded','--category','product']):
            with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(cli.main(['--workspace-root',str(self.root),*args]),0)
        meta={'io.modelcontextprotocol/protocolVersion':'2026-07-28','io.modelcontextprotocol/clientCapabilities':{}}
        calls=[{'jsonrpc':'2.0','id':i,'method':'tools/call','params':{'_meta':meta,'name':name,'arguments':args}} for i,(name,args) in enumerate([
            ('know_list',{'category':'product'}),('know_show',{'id':key}),('search_vault',{'query':'bounded','category':'product'}),('know_add',{'text':'Private bounded domain contract.','category':'domain'}),('know_list',{'category':'invented'})])]
        run=subprocess.run([sys.executable,str(core.KIT/'mcp/server.py'),'--root',str(self.root)],input='\n'.join(map(json.dumps,calls))+'\n',text=True,capture_output=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stderr); replies=[json.loads(line) for line in run.stdout.splitlines()]
        self.assertFalse(any(r.get('result',{}).get('isError') for r in replies[:4]));self.assertIn('error',replies[4])
        self.assertFalse((self.clone/'entries').exists())

    @needs_symlinks
    def test_symlinked_knowledge_directory_cannot_alias_private_notes(self):
        from ws import knowledge
        personal=core.vault(self.root)/'Personal'; personal.mkdir();(personal/'K1.md').write_text('---\nid: K1\n---\nPrivate note.\n')
        (core.vault(self.root)/'Knowledge').symlink_to(personal,target_is_directory=True)
        with self.assertRaises(core.WsError): knowledge.list_entries(self.root)

    def test_missing_team_identity_cannot_be_read_as_a_valid_link(self):
        from ws import knowledge
        cfg = core.config(self.root); cfg['team_workspace']['id'] = None
        core.atomic_write(self.root/'workspace.json',json.dumps(cfg))
        manifest=self.clone/'team.json'; data=json.loads(manifest.read_text()); data['id']=None;manifest.write_text(json.dumps(data))
        with self.assertRaises(core.WsError): knowledge.list_entries(self.root)

    def test_knowledge_catalog_excludes_ordinary_team_tasks(self):
        from ws import knowledge
        plan=sharing.preview(self.root,'task:T1');sharing.apply(self.root,plan)
        self.assertFalse(knowledge.list_entries(self.root,layer='team')['entries'])

    def test_private_limit_cannot_hide_the_team_layer(self):
        from ws import knowledge
        item=knowledge.add(self.root,'Team queue contract.','domain',True)
        sharing.apply(self.root,sharing.preview(self.root,item))
        directory=core.vault(self.root)/'Knowledge'
        for i in range(100):
            (directory/('K%03d.md'%i)).write_text('---\nid: K%03d\n---\nPrivate queue contract.\n'%i)
        rows=knowledge.list_entries(self.root)['entries'];self.assertTrue(any(r['layer']=='team' for r in rows))

    def test_finished_runbook_reaches_catalog_through_supported_share_gate(self):
        from ws import knowledge
        core.checkpoint(self.root,'T1','done','Review runbook.',notes={'Evidence':'Queue smoke passed.',
            'Handoff':'Decision: Use bounded queues.\nReason: Terminate retries.\nOutcome: Stable receipts.'})
        plan=sharing.preview(self.root,'T1',as_format='runbook');sharing.apply(self.root,plan)
        row=knowledge.list_entries(self.root,'runbook','team')['entries'][0]
        self.assertEqual(row['source_sha'],plan['source_sha'])
        self.assertIn('Stable receipts.',knowledge.show(self.root,row['key'])['content'])
