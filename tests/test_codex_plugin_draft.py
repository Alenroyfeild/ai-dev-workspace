import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


KIT = Path(__file__).resolve().parents[1]


class CodexPluginDraftTests(unittest.TestCase):
    def test_manifest_and_available_marketplace_use_plugin_root_paths(self):
        manifest = json.loads((KIT / '.codex-plugin/plugin.json').read_text())
        self.assertEqual(manifest['name'], 'ai-dev-workspace')
        self.assertEqual(manifest['hooks'], './hooks/codex-hooks.json')
        self.assertTrue((KIT / manifest['hooks']).is_file())
        # Native MCP cwd is an integration gate, not a guessed plugin-root connection.
        self.assertNotIn('mcpServers', manifest)
        market = json.loads((KIT / '.agents/plugins/marketplace.json').read_text())
        plugin, = market['plugins']
        self.assertEqual(plugin['name'], manifest['name'])
        self.assertEqual(plugin['source'], {'source': 'local', 'path': './'})
        self.assertEqual(plugin['policy']['installation'], 'AVAILABLE')

    def test_hook_commands_preserve_fixture_root_cwd_payload_and_client(self):
        hooks = json.loads((KIT / 'hooks/codex-hooks.json').read_text())['hooks']
        self.assertEqual(set(hooks), {'SessionStart', 'Stop'})
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            plugin = base / "plugin root ' $ % & ü"; (plugin / 'bin').mkdir(parents=True)
            repo = base / 'sample repo'; repo.mkdir()
            home = base / 'home'; home.mkdir()
            # Exercise the actual shell command; the future runtime is independently owned.
            (plugin / 'bin/ws-plugin').write_text(
                'import json,os,sys\n'
                'print(json.dumps(dict(args=sys.argv[1:],cwd=os.getcwd(),payload=json.load(sys.stdin))))\n')
            env = dict(os.environ, HOME=str(home), USERPROFILE=str(home),
                       CODEX_HOME=str(home / '.codex'), CLAUDE_PLUGIN_ROOT=str(plugin),
                       PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
            for event, entries in hooks.items():
                entry, = entries; hook, = entry['hooks']
                self.assertEqual(hook['type'], 'command')
                payload = dict(hook_event_name=event, cwd=str(repo), prompt='receipt → cents')
                result = subprocess.run(hook['command'], shell=True, cwd=repo, env=env,
                                        input=json.dumps(payload), capture_output=True,
                                        text=True, encoding='utf-8', timeout=15, check=True)
                observed = json.loads(result.stdout)
                self.assertEqual(observed['args'], ['--client', 'codex'])
                self.assertEqual(Path(observed['cwd']).resolve(), repo.resolve())
                self.assertEqual(observed['payload'], payload)
            self.assertFalse((home / '.codex').exists())
