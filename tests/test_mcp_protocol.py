"""Only the new protocol boundary; real stdio, no client/model launches."""
import json, os, subprocess, sys, tempfile, unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ws import core
KIT=Path(__file__).resolve().parents[1]
P='io.modelcontextprotocol/'
def request(i, method, params=None, version='2026-07-28'):
    body=dict(params or {})
    if version is not None: body['_meta']={P+'protocolVersion':version,P+'clientCapabilities':{}}
    return dict(jsonrpc='2.0',id=i,method=method,params=body)
class WireTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        home=str(Path(self.temp.name)/'home')
        env=patch.dict(os.environ, HOME=home, CODEX_HOME=home+'/.codex', CLAUDE_CONFIG_DIR=home+'/.claude')
        env.start();self.addCleanup(env.stop)
        self.root=Path(self.temp.name)/'memory';core.init(self.root,'Synthetic');core.task_new(self.root,'T-1','Resume fixture')
    def wire(self, messages):
        p=subprocess.run([sys.executable,str(KIT/'mcp/server.py'),'--root',str(self.root)],input='\n'.join(json.dumps(m) for m in messages)+'\n',text=True,capture_output=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr);return [json.loads(line) for line in p.stdout.splitlines()]
    def test_old_handshakes_and_new_process_resume(self):
        for version in ('2025-11-25','2025-06-18'):
            replies=self.wire([request(1,'initialize',{'protocolVersion':version,'capabilities':{},'clientInfo':{'name':'old','version':'1'}},None),{'jsonrpc':'2.0','method':'notifications/initialized'},request(2,'tools/list',version=None),request(3,'tools/call',{'name':'checkpoint','arguments':{'id':'T-1','status':'in_progress','next':'Use violet; no dependency.'}},None),request(4,'ping',version=None)])
            self.assertEqual(len(replies),4);self.assertEqual(replies[0]['result']['protocolVersion'],version)
            self.assertNotIn('resultType',replies[1]['result']);self.assertFalse(replies[2]['result']['isError']);self.assertEqual(replies[3]['result'],{})
        reply=self.wire([request(1,'tools/call',{'name':'brief','arguments':{}})])[0]
        self.assertIn('Use violet; no dependency.',reply['result']['content'][0]['text'])
        reply=self.wire([request(1,'tools/call',{'name':'checkpoint','arguments':{'id':'T-1','status':'in_progress','next':'Keep violet; preserve the index.'}})])[0]
        self.assertFalse(reply['result']['isError'])
        reply=self.wire([request(1,'initialize',{'protocolVersion':'2025-11-25'},None),request(2,'tools/call',{'name':'brief','arguments':{}},None)])[1]
        self.assertIn('Keep violet; preserve the index.',reply['result']['content'][0]['text'])
    def test_modern_discovery_direct_calls_and_cacheable_results(self):
        replies=self.wire([request(1,'server/discover'),request(2,'tools/list'),request(3,'prompts/list'),request(4,'resources/list'),request(5,'resources/read',{'uri':'workspace://brief'}),request(6,'prompts/get',{'name':'pickup'})])
        self.assertEqual(replies[0]['result']['supportedVersions'],['2026-07-28','2025-11-25','2025-06-18'])
        for i,reply in enumerate(replies):
            self.assertEqual(reply['result']['resultType'],'complete');self.assertIn(P+'serverInfo',reply['result']['_meta'])
            if i<5:self.assertEqual((reply['result']['ttlMs'],reply['result']['cacheScope']),(0,'private'))
    def test_bad_metadata_cannot_write_and_each_request_validates(self):
        args={'name':'checkpoint','arguments':{'id':'T-1','status':'done','next':'Wrong mutation'}}
        missing=request(2,'tools/call',args);del missing['params']['_meta'][P+'clientCapabilities']
        before=core.task_path(self.root,'T-1').read_bytes()
        replies=self.wire([request(1,'tools/call',args,'1900-01-01'),missing,request(3,'tools/call',args,None),request(4,'tools/list')])
        self.assertEqual([r.get('error',{}).get('code') for r in replies],[-32022,-32602,-32602,None])
        self.assertEqual(replies[0]['error']['data']['requested'],'1900-01-01');self.assertIn('2025-06-18',replies[0]['error']['data']['supported'])
        self.assertEqual(before,core.task_path(self.root,'T-1').read_bytes())
    def test_removed_methods_and_resource_error_then_recovery(self):
        replies=self.wire([request(1,'ping'),request(2,'resources/read',{'uri':'workspace://unknown'}),request(3,'tools/list')])
        self.assertEqual(replies[0]['error']['code'],-32601);self.assertEqual(replies[1]['error']['code'],-32602);self.assertIn('tools',replies[2]['result'])
    def test_legacy_unknown_version_is_not_echoed_and_metadata_does_not_stick(self):
        replies=self.wire([request(1,'initialize',{'protocolVersion':'1900-01-01'},None),request(2,'tools/list'),request(3,'ping',version=None)])
        self.assertEqual(replies[0]['result']['protocolVersion'],'2025-11-25');self.assertEqual(replies[1]['result']['resultType'],'complete');self.assertEqual(replies[2]['result'],{})
    def test_incomplete_modern_metadata_never_inherits_legacy_state(self):
        bad=request(2,'tools/list');del bad['params']['_meta'][P+'protocolVersion']
        replies=self.wire([request(1,'initialize',{'protocolVersion':'2025-06-18'},None),bad,request(3,'tools/list')])
        self.assertEqual(replies[1]['error']['code'],-32602);self.assertEqual(replies[2]['result']['resultType'],'complete')

    def test_malformed_metadata_and_ids_never_write(self):
        args={'name':'checkpoint','arguments':{'id':'T-1','status':'done','next':'Wrong mutation'}}
        messages=[]
        for meta in (None, [], {P+'protocolVersion':20260728,P+'clientCapabilities':{}},
                     {P+'protocolVersion':'2026-07-28',P+'clientCapabilities':[]},
                     {P+'protocolVersion':'2026-07-28',P+'clientCapabilities':{},P+'clientInfo':{}},
                     {P+'protocolVersion':'2026-07-28',P+'clientCapabilities':{},P+'clientInfo':None},
                     {P+'protocolVersion':'2025-11-25',P+'clientCapabilities':{}}):
            msg=request(len(messages),'tools/call',args);msg['params']['_meta']=meta;messages.append(msg)
        before=core.task_path(self.root,'T-1').read_bytes()
        self.assertTrue(all(r['error']['code']==-32602 for r in self.wire(messages)))
        for mid in (None, True, [], {}):
            self.assertEqual(self.wire([request(mid,'tools/call',args)])[0]['error']['code'],-32600)
        notice=request(1,'tools/call',args);del notice['id']
        self.assertEqual(self.wire([notice]),[])
        self.assertEqual(before,core.task_path(self.root,'T-1').read_bytes())
if __name__=='__main__':unittest.main()
