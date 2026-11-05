import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ws import core
from mcp import server
from testutil import isolate_home, rmtree_owned


class ClaimNextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(rmtree_owned, self.tmp.name, self.tmp.name)
        isolate_home(self, self.tmp.name)
        self.root = Path(self.tmp.name) / 'workspace'
        core.init(self.root, 'fixture')

    def add(self, task, **meta):
        core.task_new(self.root, task, task)
        path = core.task_path(self.root, task)
        path.write_text(core.set_meta(path.read_text(), {'status': 'ready', **meta}), encoding='utf-8')
        return path

    def workers(self):
        env = dict(os.environ, WS_ROOT=str(self.root))
        cmd = [sys.executable, '-m', 'ws.cli', 'task', 'next', '--worker']
        procs = [subprocess.Popen(cmd + [w], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) for w in ('worker1', 'worker2')]
        return [(p.returncode, out, err) for p in procs for out, err in [p.communicate(timeout=30)]]

    def test_two_processes_choose_distinct_tasks(self):
        self.add('A'); self.add('B')
        result = self.workers()
        self.assertEqual([r[0] for r in result], [0, 0], result)
        self.assertEqual({json.loads(r[1])['task'] for r in result}, {'A', 'B'})

    def test_one_task_has_only_one_winner(self):
        self.add('A')
        result = self.workers()
        self.assertEqual(sum(r[0] == 0 for r in result), 1, result)
        self.assertEqual(core.parse_meta(core.task_path(self.root, 'A').read_text())['claimed_by'] in ('worker1', 'worker2'), True)

    def test_skips_unsafe_or_ineligible_records(self):
        self.add('A-claimed', claimed_by='other', claim_token='their-token')
        self.add('B-blocked', status='blocked')
        p = self.add('C-conflict'); p.write_text(p.read_text() + '\n<<<<<<< ours\nx\n=======\ny\n>>>>>>> theirs\n')
        self.add('D-newer', format=str(core.TASK_FORMAT + 1))
        self.add('E-missing', depends_on='MISSING')
        self.add('F-valid')
        self.assertEqual(core.claim_next(self.root, 'worker')['task'], 'F-valid')

    def test_stale_observation_cannot_release_renewed_claim(self):
        self.add('A')
        old = core.claim_next(self.root, 'worker')
        core.release(self.root, 'A', old['worker'], old['token'])
        new = core.claim_next(self.root, 'worker')
        with self.assertRaises(core.WsError): core.release(self.root, 'A', old['worker'], old['token'])
        self.assertEqual(core.parse_meta(core.task_path(self.root, 'A').read_text())['claim_token'], new['token'])

    def test_foreign_id_cannot_make_blocked_task_eligible(self):
        self.add('A', status='blocked')
        self.add('B')
        p = self.add('Z', id='A')
        self.assertEqual(core.claim_next(self.root, 'worker')['task'], 'B')
        self.assertFalse(core.parse_meta(core.task_path(self.root, 'A').read_text()).get('claimed_by'))
        self.assertEqual(core.parse_meta(p.read_text())['id'], 'A')

    def test_foreign_id_cannot_make_blocked_dependency_done(self):
        self.add('A', depends_on='D')
        self.add('B')
        self.add('D', status='blocked')
        self.add('Z', id='D', status='done')
        self.assertEqual(core.claim_next(self.root, 'worker')['task'], 'B')
        self.assertFalse(core.parse_meta(core.task_path(self.root, 'A').read_text()).get('claimed_by'))

    def test_crash_between_local_and_task_writes_leaves_selectable_task(self):
        self.add('A')
        original = core.atomic_write
        def interrupted(path, data):
            if path == core.task_path(self.root, 'A'): raise OSError('simulated interruption')
            return original(path, data)
        with mock.patch.object(core, 'atomic_write', side_effect=interrupted):
            with self.assertRaises(OSError): core.claim_next(self.root, 'worker')
        self.assertFalse(core.parse_meta(core.task_path(self.root, 'A').read_text()).get('claimed_by'))
        self.assertEqual(core.claim_next(self.root, 'next')['task'], 'A')

    def test_local_write_failure_never_claims_the_task(self):
        self.add('A')
        original = core.atomic_write
        def interrupted(path, data):
            if path == core._local_claim_path(self.root, 'A'): raise OSError('simulated interruption')
            return original(path, data)
        with mock.patch.object(core, 'atomic_write', side_effect=interrupted):
            with self.assertRaises(OSError): core.claim_next(self.root, 'worker')
        self.assertFalse(core.parse_meta(core.task_path(self.root, 'A').read_text()).get('claimed_by'))

    def test_existing_claim_command_resumes_a_selected_claim(self):
        self.add('A')
        claim = core.claim_next(self.root, 'worker')
        resumed = core.claim(self.root, 'A', 'worker')
        self.assertTrue(resumed['resumed'])
        self.assertEqual(resumed['token'], claim['token'])

    def test_mcp_selects_and_returns_claim(self):
        self.add('A')
        response = server.handle(self.root, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'claim_next_task', 'arguments': {'worker': 'mcp-worker'}}})
        self.assertFalse(response['result']['isError'], response)
        result = json.loads(response['result']['content'][0]['text'])
        self.assertEqual(result['task'], 'A')
        self.assertTrue(result['token'])
