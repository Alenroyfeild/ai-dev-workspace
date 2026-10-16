"""Hostile repository fixtures for shared CLI/MCP root discovery."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from ws import core
from testutil import isolate_home

KIT = Path(__file__).resolve().parents[1]


class RootDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        isolate_home(self, self.base)
        self.repo = self.base / 'hostile-repo'; self.repo.mkdir()
        self.nested = self.repo / 'src'; self.nested.mkdir()
        self.root = self.base / 'private-memory'
        core.init(self.root, 'Synthetic', clients=[])
        cfg = core.config(self.root); cfg['repos'] = [str(self.repo)]
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        self.link = self.repo / '.ws-start.json'
        self.link.write_text(json.dumps({'workspace': str(self.root), 'files': {}}))
        (self.repo / 'workspace.json').write_text('{"vault":"decoy"}')
        self.env = dict(os.environ, WS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1')
        self.env.pop('WS_ROOT', None)

    def test_valid_link_wins_over_hostile_colocated_workspace(self):
        for start in (self.repo, self.nested):
            with self.subTest(start=start):
                self.assertEqual(core.find_root(start), self.root)

    def test_invalid_link_never_falls_back_to_repo_or_ancestor(self):
        # Both decoy workspace files must be ignored even when link validation fails.
        (self.base / 'workspace.json').write_text('{}')
        for raw in ('{', '{}', '{"files":{},"workspace":null}',
                    '{"files":{},"workspace":[]}',
                    json.dumps({'files': {}, 'workspace': str(self.base/'missing')}),
                    json.dumps({'files': {}, 'workspace': str(self.base)})):
            with self.subTest(raw=raw):
                self.link.write_text(raw)
                before = {p: p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
                with self.assertRaises(core.WsError): core.find_root(self.nested)
                self.assertEqual(before, {p: p.read_bytes() for p in self.base.rglob('*') if p.is_file()})

    def test_nonregular_link_stops_discovery(self):
        self.link.unlink(); self.link.mkdir()
        with self.assertRaises(core.WsError): core.find_root(self.repo)
        self.link.rmdir()
        if hasattr(os, 'mkfifo'):
            os.mkfifo(self.link)
            try:
                with self.assertRaises(core.WsError): core.find_root(self.repo)
            finally: self.link.unlink()

    def test_forged_link_cannot_register_repo_itself_as_private_workspace(self):
        for target in (self.repo, self.repo / 'forged-memory'):
            with self.subTest(target=target):
                target.mkdir(exist_ok=True)
                (target / 'workspace.json').write_text(json.dumps({'repos': [str(self.repo)]}))
                self.link.write_text(json.dumps({'workspace': str(target), 'files': {}}))
                with self.assertRaises(core.WsError): core.find_root(self.nested)

    def test_symlink_and_dangling_link_stop_discovery(self):
        self.link.unlink()
        try: self.link.symlink_to(self.base / 'missing-link')
        except (OSError, NotImplementedError): self.skipTest('Symlinks unavailable')
        with self.assertRaises(core.WsError): core.find_root(self.repo)
        target = self.base / 'missing-link'
        target.write_text(json.dumps({'workspace': str(self.root), 'files': {}}))
        with self.assertRaises(core.WsError): core.find_root(self.repo)

    def test_explicit_start_environment_and_standalone_workspace_stay_supported(self):
        with mock.patch.dict(os.environ, WS_ROOT=str(self.nested)):
            self.assertEqual(core.find_root(), self.root)
            self.assertEqual(core.find_root(self.root), self.root)
        self.link.unlink()
        self.assertEqual(core.find_root(self.repo), self.repo)

    def test_cli_and_rootless_mcp_use_private_link_not_repo_workspace(self):
        core.task_new(self.root, 'T1', 'Synthetic private task')
        core.claim(self.root, 'T1', 'fixture')
        core.remember(self.root, 'Store totals as integer cents.')
        cli = subprocess.run([sys.executable, str(KIT/'bin/ws'), 'brief'], cwd=self.nested,
                             env=self.env, text=True, capture_output=True, timeout=15)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertIn('integer cents', cli.stdout)
        requests = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25'}},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'brief', 'arguments': {}}}]
        server = subprocess.run([sys.executable, str(KIT/'mcp/server.py')], cwd=self.nested,
                                env=self.env, text=True, input='\n'.join(map(json.dumps, requests))+'\n',
                                capture_output=True, timeout=15)
        self.assertEqual(server.returncode, 0, server.stderr)
        self.assertIn('integer cents', server.stdout)
