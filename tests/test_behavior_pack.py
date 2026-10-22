import json
from pathlib import Path

from test_ws import Base
from ws import core, packs
from testutil import run_ws

KIT = Path(__file__).resolve().parents[1]


class BehaviorPackTests(Base):
    def test_behavior_pack_manifest_and_availability(self):
        self.assertIn('behavior', core.available_packs())
        manifest = core.pack_manifest('behavior')
        self.assertEqual(manifest['name'], 'behavior')
        self.assertEqual(manifest['kind'], 'rules')
        self.assertEqual(manifest['version'], '0.1.0')
        self.assertEqual(manifest['requires'], [])
        self.assertIn('guidelines', manifest['description'].lower())

    def test_behavior_pack_rules_content_and_budget(self):
        snippet_path = KIT / 'packs/behavior/AGENTS.snippet.md'
        self.assertTrue(snippet_path.is_file())
        text = snippet_path.read_text(encoding='utf-8')
        self.assertIn('## Behavior guidelines', text)
        self.assertIn('Think first', text)
        self.assertIn('Simplest change', text)
        self.assertIn('Surgical edits', text)
        self.assertIn('Verify work', text)
        words = text.split()
        self.assertLessEqual(len(words), 80, f'Snippet is too verbose: {len(words)} words')

    def test_pack_add_and_remove_lifecycle(self):
        # 1. pack add
        add_result = core.pack_add(self.root, 'behavior')
        self.assertTrue(add_result['installed'])
        self.assertIn('behavior', core.config(self.root)['packs'])
        rules_text = (self.root / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertIn('## Behavior guidelines', rules_text)

        # 2. idempotent
        core.pack_add(self.root, 'behavior')
        rules_text_again = (self.root / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertEqual(rules_text_again.count('## Behavior guidelines'), 1)

        # 3. pack remove
        remove_result = packs.remove(self.root, 'behavior')
        self.assertEqual(remove_result, {'pack': 'behavior', 'removed': True, 'kept': [], 'next': []})
        self.assertNotIn('behavior', core.config(self.root)['packs'])
        cleaned_rules = (self.root / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertNotIn('## Behavior guidelines', cleaned_rules)

    def test_cli_pack_add_and_remove(self):
        proc = run_ws('pack', 'add', 'behavior', cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn('behavior', core.config(self.root)['packs'])

        proc = run_ws('pack', 'remove', 'behavior', cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn('behavior', core.config(self.root)['packs'])
