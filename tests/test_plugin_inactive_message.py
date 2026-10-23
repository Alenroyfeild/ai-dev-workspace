"""Failing-first tests: inactive plugin surfaces state exactly how to enable memory.

PLG7b — Anti1 (agy/anti1-PLG7b)

Surfaces:
  1. NO_WORKSPACE constant (mcp/server.py): the error text returned by tools/call when
     root is None, including in plugin-inactive mode.
  2. Brief tool description in plugin-inactive mode (listed as the only tool).
  3. SKILL.md prerequisite lines for handoff, pickup, lesson.

All three must tell the user:
  - Install: pipx install ai-dev-workspace --pip-args='--pre'
  - Activate: ws start

The hook stays silent (no stdout); nothing here changes ws/plugin_runtime.py output.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location('workspace_mcp', KIT / 'mcp' / 'server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

INSTALL_CMD = "pipx install ai-dev-workspace --pip-args='--pre'"
WS_START_CMD = 'ws start'


class NoWorkspaceMessageTests(unittest.TestCase):
    """NO_WORKSPACE constant must contain the install command and ws start."""

    def test_no_workspace_contains_pipx_install(self):
        self.assertIn(INSTALL_CMD, server.NO_WORKSPACE,
                      f'NO_WORKSPACE must tell users to run: {INSTALL_CMD!r}')

    def test_no_workspace_contains_ws_start(self):
        self.assertIn(WS_START_CMD, server.NO_WORKSPACE,
                      f'NO_WORKSPACE must tell users to run: {WS_START_CMD!r}')

    def test_no_workspace_still_mentions_pass_workspace_root(self):
        # Existing non-plugin callers rely on --workspace-root hint; keep it.
        self.assertIn('--workspace-root', server.NO_WORKSPACE)

    def test_tools_call_brief_outside_plugin_returns_no_workspace_message(self):
        """tools/call brief with root=None returns the NO_WORKSPACE text."""
        reply = server.handle(None, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                     'params': {'name': 'brief', 'arguments': {}}})
        self.assertTrue(reply['result']['isError'])
        text = reply['result']['content'][0]['text']
        self.assertIn(INSTALL_CMD, text)
        self.assertIn(WS_START_CMD, text)


class PluginInactiveMcpTests(unittest.TestCase):
    """In plugin-inactive mode (--plugin, no .ws-start.json) the brief tool is the
    only listed tool and its call returns the enable-memory hint."""

    def _run_plugin(self, cwd):
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
             'params': {'protocolVersion': '2025-11-25'}},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
             'params': {'name': 'brief', 'arguments': {}}},
        ]
        env = {k: v for k, v in os.environ.items() if k != 'WS_ROOT'}
        env['WS_OFFLINE'] = '1'
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        result = subprocess.run(
            [sys.executable, str(KIT / 'mcp' / 'server.py'), '--plugin'],
            cwd=cwd, env=env,
            input='\n'.join(map(json.dumps, messages)) + '\n',
            text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return [json.loads(line)['result'] for line in result.stdout.splitlines()]

    def test_plugin_inactive_brief_tool_is_listed(self):
        with tempfile.TemporaryDirectory() as d:
            replies = self._run_plugin(d)
            tools = [t['name'] for t in replies[1]['tools']]
            self.assertIn('brief', tools)

    def test_plugin_inactive_brief_call_returns_install_hint(self):
        with tempfile.TemporaryDirectory() as d:
            replies = self._run_plugin(d)
            self.assertTrue(replies[2]['isError'])
            text = replies[2]['content'][0]['text']
            self.assertIn(INSTALL_CMD, text,
                          'brief tool in plugin-inactive mode must show pipx install command')

    def test_plugin_inactive_brief_call_returns_ws_start_hint(self):
        with tempfile.TemporaryDirectory() as d:
            replies = self._run_plugin(d)
            text = replies[2]['content'][0]['text']
            self.assertIn(WS_START_CMD, text,
                          'brief tool in plugin-inactive mode must show ws start command')


class SkillPrerequisiteTests(unittest.TestCase):
    """Each skill's SKILL.md must mention the exact enable steps when ws is absent."""

    SKILLS = ['handoff', 'pickup', 'lesson']
    SKILLS_DIR = KIT / 'skills'

    def _skill_text(self, name):
        return (self.SKILLS_DIR / name / 'SKILL.md').read_text()

    def test_handoff_skill_mentions_pipx_install(self):
        self.assertIn(INSTALL_CMD, self._skill_text('handoff'),
                      f'handoff/SKILL.md must contain: {INSTALL_CMD!r}')

    def test_handoff_skill_mentions_ws_start(self):
        self.assertIn(WS_START_CMD, self._skill_text('handoff'),
                      f'handoff/SKILL.md must contain: {WS_START_CMD!r}')

    def test_pickup_skill_mentions_pipx_install(self):
        self.assertIn(INSTALL_CMD, self._skill_text('pickup'),
                      f'pickup/SKILL.md must contain: {INSTALL_CMD!r}')

    def test_pickup_skill_mentions_ws_start(self):
        self.assertIn(WS_START_CMD, self._skill_text('pickup'),
                      f'pickup/SKILL.md must contain: {WS_START_CMD!r}')

    def test_lesson_skill_mentions_pipx_install(self):
        self.assertIn(INSTALL_CMD, self._skill_text('lesson'),
                      f'lesson/SKILL.md must contain: {INSTALL_CMD!r}')

    def test_lesson_skill_mentions_ws_start(self):
        self.assertIn(WS_START_CMD, self._skill_text('lesson'),
                      f'lesson/SKILL.md must contain: {WS_START_CMD!r}')


if __name__ == '__main__':
    unittest.main()
