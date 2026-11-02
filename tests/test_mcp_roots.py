"""Fake stdio clients only; no assistant sessions or real configuration."""
import json
import os
import queue
import subprocess
import sys
import threading
import unittest
from pathlib import Path

import test_plugin_runtime as fixture
from ws import core
from testutil import needs_symlinks

P = 'io.modelcontextprotocol/'
KIT = Path(__file__).resolve().parents[1]


class McpRootsTests(unittest.TestCase):
    setUp = fixture.PluginRuntimeTests.setUp

    def start(self, plugin=True, cwd=None):
        cwd = cwd or self.base / 'plugin'; cwd.mkdir(exist_ok=True)
        self.process = subprocess.Popen([sys.executable, str(KIT/'mcp/server.py'), *(['--plugin'] if plugin else [])],
                                        cwd=cwd, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding='utf-8')
        self.messages = queue.Queue()
        def read():
            for line in self.process.stdout: self.messages.put(json.loads(line))
        self.reader = threading.Thread(target=read, daemon=True); self.reader.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.process.stdin.close()
        try: self.process.wait(timeout=10)
        except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(); self.fail('MCP did not exit at EOF')
        self.reader.join(timeout=2)
        for stream in (self.process.stdout, self.process.stderr): stream.close()

    def send(self, message):
        self.process.stdin.write(json.dumps(message)+'\n'); self.process.stdin.flush()

    def receive(self):
        try: return self.messages.get(timeout=5)
        except queue.Empty: self.fail('MCP response timed out')

    def rpc(self, mid, method, params=None):
        self.send(dict(jsonrpc='2.0', id=mid, method=method, params=params or {}))
        reply = self.receive(); self.assertEqual(reply.get('id'), mid); return reply

    def initialize(self, capabilities=None):
        self.rpc(1, 'initialize', {'protocolVersion':'2025-11-25', 'capabilities':capabilities or {}})
        self.send(dict(jsonrpc='2.0', method='notifications/initialized'))

    def roots(self, request, rows):
        self.send(dict(jsonrpc='2.0', id=request['id'], result={'roots':rows}))

    def brief(self, mid=3, meta=None, **extra):
        params = dict(name='brief', arguments={}, **extra)
        if meta is not None: params['_meta'] = meta
        return self.rpc(mid, 'tools/call', params)['result']

    def test_legacy_roots_activate_started_repo_from_outside_it(self):
        self.start(); self.initialize({'roots':{'listChanged':True}})
        request = self.receive(); self.assertEqual(request['method'], 'roots/list')
        self.assertTrue(self.brief()['isError'])  # no blocking while a client has not answered
        self.send(dict(jsonrpc='2.0', id='unsolicited', result={'roots':[{'uri':self.repo.as_uri()}]}))
        self.assertTrue(self.brief(4)['isError'])
        self.roots(request, [{'uri':self.repo.as_uri()}])
        reply = self.brief(5)
        self.assertFalse(reply['isError']); self.assertIn('integer cents', reply['content'][0]['text'])
        self.assertGreater(len(self.rpc(6,'tools/list')['result']['tools']),1)

    def test_invalid_or_unstarted_roots_never_bind(self):
        self.start(); self.initialize({'roots':{}}); request=self.receive()
        empty=self.base/'empty';empty.mkdir()
        fake=self.base/'forged';fake.mkdir();(fake/'.ws-start.json').write_text(json.dumps({'workspace':str(self.root)}))
        invalid=[None,{}, {'uri':'https://example.invalid/repo'}, {'uri':'file://remote.invalid/repo'},
                 {'uri':'file:relative'}, {'uri':empty.as_uri()}, {'uri':self.root.as_uri()},
                 {'uri':fake.as_uri()}, {'uri':self.repo.as_uri()+'?query=1'}, {'uri':'file:////remote.invalid/repo'}]
        self.roots(request, invalid)
        self.assertTrue(self.brief()['isError'])
        self.assertEqual(self.rpc(4,'resources/list')['result']['resources'],[])
        self.assertEqual(self.rpc(5,'ping')['result'],{})

    def test_changed_roots_clear_binding_and_ignore_stale_replies(self):
        self.start(); self.initialize({'roots':{'listChanged':True}}); first=self.receive()
        self.roots(first,[{'uri':self.repo.as_uri()}]);self.assertFalse(self.brief()['isError'])
        self.send(dict(jsonrpc='2.0',method='notifications/roots/list_changed')); second=self.receive()
        self.assertTrue(self.brief(4)['isError'])
        self.roots(first,[{'uri':self.repo.as_uri()}]);self.assertTrue(self.brief(5)['isError'])
        self.roots(second,[]);self.assertTrue(self.brief(6)['isError'])
        self.send(dict(jsonrpc='2.0',method='notifications/roots/list_changed')); third=self.receive()
        self.roots(third,[{'uri':self.repo.as_uri()}]);self.assertFalse(self.brief(7)['isError'])

    def test_no_roots_capability_preserves_inactive_plugin(self):
        self.start();self.initialize()
        self.assertTrue(self.brief()['isError'])
        self.assertEqual([t['name'] for t in self.rpc(4,'tools/list')['result']['tools']],['brief'])

    def test_modern_roots_use_per_request_input_and_do_not_stick(self):
        self.start()
        meta={P+'protocolVersion':'2026-07-28',P+'clientCapabilities':{'roots':{}}}
        catalog=self.rpc(0,'tools/list',{'_meta':meta})['result']
        self.assertEqual(catalog['resultType'],'complete')
        self.assertIn('remember',[t['name'] for t in catalog['tools']])
        result=self.brief(1,meta)
        self.assertEqual(result['resultType'],'input_required')
        inputs=result['inputRequests'];key=next(iter(inputs));self.assertEqual(inputs[key]['method'],'roots/list')
        supplied={key:{'roots':[{'uri':self.repo.as_uri()}]}}
        result=self.brief(2,meta,inputResponses=supplied)
        self.assertFalse(result['isError']);self.assertIn('integer cents',result['content'][0]['text'])
        no_cap={P+'protocolVersion':'2026-07-28',P+'clientCapabilities':{}}
        self.assertTrue(self.brief(3,no_cap,inputResponses=supplied)['isError'])
        self.assertEqual(self.brief(4,meta)['resultType'],'input_required')
        self.assertTrue(self.brief(5,meta,inputResponses={key:{'roots':[{'uri':self.root.as_uri()}]}})['isError'])

    def test_started_cwd_stays_pinned_without_roots_requests(self):
        self.start(cwd=self.repo);self.initialize({'roots':{'listChanged':True}})
        self.assertFalse(self.brief()['isError'])

    def test_roots_error_stays_inactive_and_stdio_keeps_working(self):
        self.start();self.initialize({'roots':{}});request=self.receive()
        self.send(dict(jsonrpc='2.0',id=request['id'],error={'code':-32601,'message':'unsupported'}))
        self.assertTrue(self.brief()['isError'])
        self.assertEqual(self.rpc(4,'ping')['result'],{})

    @needs_symlinks
    def test_symlinked_start_link_never_authorizes_a_root(self):
        link=self.repo/'.ws-start.json';outside=self.base/'copied-link.json';outside.write_bytes(link.read_bytes())
        link.unlink();link.symlink_to(outside)
        self.start();self.initialize({'roots':{}});request=self.receive()
        self.roots(request,[{'uri':self.repo.as_uri()}]);self.assertTrue(self.brief()['isError'])

    def test_modern_request_does_not_inherit_legacy_roots(self):
        self.start();self.initialize({'roots':{}});request=self.receive()
        self.roots(request,[{'uri':self.repo.as_uri()}]);self.assertFalse(self.brief()['isError'])
        meta={P+'protocolVersion':'2026-07-28',P+'clientCapabilities':{}}
        self.assertTrue(self.brief(4,meta)['isError'])
        self.assertEqual([t['name'] for t in self.rpc(5,'tools/list',{'_meta':meta})['result']['tools']],['brief'])

    def test_bad_request_envelopes_and_early_notifications_do_not_bind(self):
        self.start()
        self.send(dict(jsonrpc='2.0',id=1,unexpected=True))
        self.assertEqual(self.receive()['error']['code'],-32600)
        self.rpc(2,'initialize',{'capabilities':{'roots':{'listChanged':True}}})
        self.send(dict(jsonrpc='2.0',method='notifications/roots/list_changed'))
        self.assertTrue(self.brief(3)['isError'])
        self.send(dict(jsonrpc='2.0',method='notifications/initialized'));request=self.receive()
        self.roots(request,[{'uri':self.repo.as_uri()}]);self.assertFalse(self.brief(4)['isError'])

    def test_deeply_malformed_link_is_skipped_without_ending_stdio(self):
        (self.repo/'.ws-start.json').write_text('{"files":{},"nested":'+'['*1500+'0'+']'*1500+'}')
        self.start();self.initialize({'roots':{}});request=self.receive()
        self.roots(request,[{'uri':self.repo.as_uri()}])
        self.assertTrue(self.brief()['isError'])
        self.assertEqual(self.rpc(4,'ping')['result'],{})
