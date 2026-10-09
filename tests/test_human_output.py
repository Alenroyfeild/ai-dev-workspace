import io
import json
import os
from contextlib import redirect_stdout
from unittest import mock
from test_ws import Base
from ws import cli


class HumanOutputTests(Base):
    def render(self, value, tty=True, env=None):
        buffer = io.StringIO()
        with mock.patch.object(cli.sys.stdout, 'isatty', return_value=tty, create=True), \
                mock.patch.dict(os.environ, env or {}), redirect_stdout(buffer):
            buffer.isatty = lambda: tty
            cli.out(value)
        return buffer.getvalue()

    def test_terminal_gets_plain_lines_and_scripts_keep_json(self):
        value = {'task': 'APP-1', 'connected': True, 'linked': [], 'mcp': {'ok': True, 'steps': ['initialize', 'status']}}
        text = self.render(value)
        for line in ('task: APP-1', 'connected: yes', 'linked: none', 'mcp:', '  ok: yes', '  steps: initialize, status'):
            self.assertIn(line, text)
        self.assertEqual(json.loads(self.render(value, tty=False)), value)
        self.assertEqual(json.loads(self.render(value, env={'WS_JSON': '1'})), value)
        self.assertIn('- name: a', self.render([{'name': 'a', 'level': 'recommended'}]))

    def test_init_does_not_print_codex_config_to_everyone(self):
        proc = self.run_ws('init', str(self.root.parent / 'fresh-ws'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('[mcp_servers', proc.stdout)
        self.assertIn('ws connect codex', proc.stdout)
        self.assertIn('ws connect claude', proc.stdout)

    def run_ws(self, *args):
        import subprocess, sys
        from test_ws import KIT
        return subprocess.run([sys.executable, str(KIT / 'bin/ws'), *args], capture_output=True, text=True,
                              env=dict(os.environ, WS_OFFLINE='1', HOME=str(self.root.parent / 'home')))
