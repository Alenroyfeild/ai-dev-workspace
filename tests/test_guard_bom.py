"""PowerShell/editor UTF-8 BOMs must not disable hook-config protection."""
import json
import os
import subprocess
import unittest

from test_ws import Base
from ws import guards, core, repo


class GuardBomTests(Base):
    @unittest.skipUnless(os.name == 'nt', 'Native Windows junction fixture')
    def test_agents_junction_is_refused_without_changing_target(self):
        code = self.root.parent / 'code'; code.mkdir()
        target = code / 'user-agents'; target.mkdir()
        before = {name: b'\xef\xbb\xbf{\r\n "user": true\r\n}\r\n'
                  for name in ('hooks.json', 'mcp_config.json')}
        for name, data in before.items(): (target / name).write_bytes(data)
        junction = code / '.agents'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(target)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            for name, data in before.items():
                with self.subTest(name=name), self.assertRaises(core.WsError):
                    repo.path(code, '.agents/' + name)
                self.assertEqual((target / name).read_bytes(), data)
        finally:
            os.rmdir(junction)  # unlink the junction, never recurse into its target

    def test_bom_and_crlf_configs_cannot_drop_guard(self):
        config = {'hooks': {'PreToolUse': [{'hooks': [{'command': 'ws guard --hook'}]}]}}
        for name in ('.claude/settings.local.json', '.codex/hooks.json'):
            target = self.root / name; target.parent.mkdir(exist_ok=True)
            for before_bom in ('', '\ufeff'):
                for after_bom in ('', '\ufeff'):
                    with self.subTest(name=name, before_bom=bool(before_bom), after_bom=bool(after_bom)):
                        target.write_bytes((before_bom + json.dumps(config, indent=2).replace('\n', '\r\n')).encode())
                        reason = guards.reason('Write', {'file_path': str(target), 'content': after_bom + '{}'})
                        self.assertIn('switch the ws guards hook off', reason)

    def test_bom_preserving_edits_allow_but_disable_all_is_denied(self):
        config = {'hooks': {'PreToolUse': [{'hooks': [{'command': 'ws guard --hook'}]}]}}
        target = self.root / '.codex/hooks.json'; target.parent.mkdir(exist_ok=True)
        target.write_bytes(('\ufeff' + json.dumps(config)).encode())
        self.assertEqual(guards.reason('Write', {'file_path': str(target), 'content': '\ufeff' + json.dumps(config)}), '')
        config['disableAllHooks'] = True
        self.assertIn('switch the ws guards hook off', guards.reason(
            'Write', {'file_path': str(target), 'content': '\ufeff' + json.dumps(config)}))
