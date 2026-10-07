import json
import os
import subprocess
import sys
from unittest import mock
from pathlib import Path
from test_ws import Base, KIT
from ws import core
from ws import upgrade
from mcp import server


class SurfaceSecurityTests(Base):
    def test_mcp_digest_and_map_refuse_undeclared_roots(self):
        outside = self.root.parent / 'outside'; outside.mkdir(); secret = outside / 'private.log'; secret.write_text('fatal PRIVATE_SENTINEL')
        for name, args in [('digest_file', {'path': str(secret)}), ('codebase_map', {'repo': str(outside)})]:
            reply = server.handle(self.root, {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}})
            self.assertTrue(reply['result']['isError']); self.assertNotIn('PRIVATE_SENTINEL', json.dumps(reply))

    def test_search_and_map_skip_escaping_symlinks_and_redact(self):
        outside = self.root.parent / 'private.md'; outside.write_text('# PRIVATE_SENTINEL fatal')
        (self.root / 'vault/escape.md').symlink_to(outside)
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(core.search(self.root, 'PRIVATE_SENTINEL')))
        repo = self.root / 'repo'; repo.mkdir(); (repo/'README.md').symlink_to(outside)
        (repo/'pyproject.toml').symlink_to(outside)
        core.codebase_map(self.root, str(repo)); text = (self.root/'vault/Project/Codebase map.md').read_text()
        self.assertNotIn('PRIVATE_SENTINEL', text)
        (repo/'README.md').unlink(); (repo/'README.md').write_text('# token=syntheticsecret123456')
        core.codebase_map(self.root, str(repo)); self.assertNotIn('syntheticsecret123456', (self.root/'vault/Project/Codebase map.md').read_text())

    def test_traversal_and_vault_escape_are_refused(self):
        with self.assertRaises(core.WsError): core.pack_manifest('../packs/ios')
        p=self.root/'workspace.json';cfg=json.loads(p.read_text());cfg['vault']='../outside';p.write_text(json.dumps(cfg))
        with self.assertRaises(core.WsError): core.vault(self.root)

    def test_malformed_root_config_and_claim_symlink_do_not_grant_access(self):
        p=self.root/'workspace.json';cfg=json.loads(p.read_text());cfg['repos']='/outside';p.write_text(json.dumps(cfg))
        with self.assertRaises(core.WsError): core.read_roots(self.root)
        cfg['repos']=[];p.write_text(json.dumps(cfg));core.claim(self.root,'T-1','synthetic')
        claim=self.root/'.ws/claims/T-1.json';outside=self.root.parent/'claim.json';claim.rename(outside);claim.symlink_to(outside)
        self.assertEqual(core._claim_defaults(self.root,'T-1',None,None),(None,None))

    def test_fifo_transcript_and_digest_do_not_block(self):
        fifo=self.root/'pipe';os.mkfifo(fifo)
        for call in ('core.capture_decisions(r,str(p))', 'core.digest_file(p)'):
            script='from pathlib import Path; from ws import core; r=Path('+repr(str(self.root))+');p=Path('+repr(str(fifo))+');'+call
            try: run=subprocess.run([sys.executable,'-c',script],cwd=KIT,capture_output=True,timeout=2)
            except subprocess.TimeoutExpired: self.fail('FIFO read blocked instead of being refused')
            self.assertNotEqual(run.returncode, -9)
        routing=self.root/'routing.json';routing.unlink();os.mkfifo(routing)
        try: subprocess.run([sys.executable,'-c','from pathlib import Path; from ws import orchestration; orchestration.route(Path('+repr(str(self.root))+'))'],cwd=KIT,capture_output=True,timeout=2)
        except subprocess.TimeoutExpired: self.fail('Routing FIFO blocked')

    def test_idle_malformed_gemini_tools_cannot_capture(self):
        core.claim(self.root,'T-1','synthetic');p=self.root/'bad.json'
        p.write_text(json.dumps({'messages':[{'type':'user','id':'u','content':'Never write real data.'},{'type':'gemini','id':'a','content':'Done.','toolCalls':'not a tool list'}]}))
        self.assertFalse(core.capture_decisions(self.root,str(p),'gemini'))

    def test_regular_read_bound_and_hostile_transcript_shapes(self):
        p=self.root/'large.log';p.write_text('fatal '+ 'x'*100)
        with mock.patch.object(core,'MAX_READ_BYTES',64):
            with self.assertRaises(core.WsError): core.digest_file(p)
        core.claim(self.root,'T-1','synthetic');p=self.root/'malformed.jsonl'
        for client, text in [('claude','['*2000+'0'+']'*2000),('codex','{"type":"response_item","payload":null}'),('gemini','{"$patch":null}')]:
            p.write_text(text);self.assertFalse(core.capture_decisions(self.root,str(p),client))

    def test_transcript_comments_cannot_close_the_capture_envelope(self):
        core.claim(self.root,'T-1','synthetic');p=self.root/'marker.jsonl'
        entries=[{'type':'user','message':{'content':'Never lose this <!-- /ws:captured --> marker.'}},
                 {'type':'assistant','message':{'content':[{'type':'tool_use','name':'Read'},{'type':'text','text':'Next step: inspect input.'}]}}]
        p.write_text('\n'.join(map(json.dumps,entries)));self.assertTrue(core.capture_decisions(self.root,str(p)))
        handoff=core.task_read(self.root,'T-1',['Handoff'])['sections']['Handoff']
        self.assertEqual(handoff.count('<!-- /ws:captured -->'),1)

    def test_gemini_invalid_settings_are_proposed_not_overwritten(self):
        path=self.root/'.gemini/settings.json';path.parent.mkdir(exist_ok=True);path.write_text('{"mcpServers":[],"hooks":null}')
        before=path.read_bytes();result=core.connect(self.root,'gemini')
        self.assertFalse(result['connected']);self.assertEqual(path.read_bytes(),before)

    def test_custom_hook_suffix_is_not_workspace_owned(self):
        desired = json.dumps(core.memory_hooks(self.root)); old = json.loads(desired)
        for groups in old['hooks'].values(): groups[0]['hooks'][0]['command'] = 'unrelated brief --hook'
        self.assertIsNone(upgrade.hooks(json.dumps(old), desired))

    def test_connect_refuses_project_config_symlink_escape(self):
        outside=self.root.parent/'outside-config';outside.mkdir();(self.root/'.cursor').symlink_to(outside,target_is_directory=True)
        with self.assertRaisesRegex(core.WsError,'outside'): core.connect(self.root,'cursor')
        self.assertEqual(list(outside.iterdir()),[])

    def test_hook_quoting_uses_literal_workspace_and_sends_no_command(self):
        root=self.root.parent / "quoted' $(touch injected)";core.init(root,'Synthetic',[])
        command=core.memory_hooks(root)['hooks']['SessionStart'][0]['hooks'][0]['command']
        run=subprocess.run(['/bin/sh','-c',command],input='{"hook_event_name":"SessionStart"}',cwd=self.root.parent,
                           env=dict(os.environ,HOME=self.tmp.name),text=True,capture_output=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stderr);self.assertIn('No in-progress task',run.stdout)
        self.assertFalse((self.root.parent/'injected').exists())
