import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


KIT = Path(__file__).resolve().parents[1]


class CodexPluginDraftTests(unittest.TestCase):
    def test_manifest_uses_plugin_root_paths_without_advertising_a_package(self):
        manifest = json.loads((KIT / '.codex-plugin/plugin.json').read_text())
        self.assertEqual(manifest['name'], 'ai-dev-workspace')
        self.assertEqual(manifest['hooks'], './hooks/codex-hooks.json')
        self.assertTrue((KIT / manifest['hooks']).is_file())
        # Native MCP cwd is an integration gate, not a guessed plugin-root connection.
        self.assertNotIn('mcpServers', manifest)
        self.assertFalse((KIT / '.agents/plugins/marketplace.json').exists())

    def test_hook_commands_isolate_imports_and_preserve_root_cwd_payload(self):
        hooks = json.loads((KIT / 'hooks/codex-hooks.json').read_text())['hooks']
        self.assertEqual(set(hooks), {'SessionStart', 'Stop'})
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            plugin = base / "plugin root ' $ % & ü"; (plugin / 'bin').mkdir(parents=True)
            repo = base / 'sample repo'; repo.mkdir()
            home = base / 'home'; home.mkdir()
            (repo / 'runpy.py').write_text("raise RuntimeError('UNTRUSTED_REPO_RUNPY_EXECUTED')\n")
            poison = base / 'poison path'; poison.mkdir()
            (poison / 'sitecustomize.py').write_text("raise RuntimeError('UNTRUSTED_PYTHONPATH_IMPORTED')\n")
            # Exercise the actual shell command; the future runtime is independently owned.
            (plugin / 'bin/ws-plugin').write_text(
                'import json,os,sys\n'
                'print(json.dumps(dict(args=sys.argv[1:],cwd=os.getcwd(),payload=json.load(sys.stdin))))\n')
            env = dict(os.environ, HOME=str(home), USERPROFILE=str(home),
                       CODEX_HOME=str(home / '.codex'), CLAUDE_PLUGIN_ROOT=str(plugin),
                       PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONPATH=str(poison))
            for event, entries in hooks.items():
                entry, = entries; hook, = entry['hooks']
                self.assertEqual(hook['type'], 'command')
                payload = dict(hook_event_name=event, cwd=str(repo), prompt='receipt → cents')
                result = subprocess.run(hook['command'], shell=True, cwd=repo, env=env,
                                        input=json.dumps(payload), capture_output=True,
                                        text=True, encoding='utf-8', timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                observed = json.loads(result.stdout)
                self.assertNotIn('UNTRUSTED_', result.stderr)
                self.assertEqual(observed['args'], ['--client', 'codex'])
                self.assertEqual(Path(observed['cwd']).resolve(), repo.resolve())
                self.assertEqual(observed['payload'], payload)
            self.assertFalse((home / '.codex').exists())
