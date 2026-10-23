import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDES = ('share-memory-claude-code-codex.md', 'keep-decisions-without-background-ai.md',
          'stop-retrying-failed-approaches.md')


class DiscoverabilityTests(unittest.TestCase):
    def metadata(self):
        tree = ast.parse((ROOT / 'setup.py').read_text(encoding='utf-8'))
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == 'setup')
        return {kw.arg: kw.value for kw in call.keywords}

    def test_search_metadata_names_memory_skills_and_secondary_client(self):
        words = set(ast.literal_eval(self.metadata()['keywords']).split())
        self.assertTrue({'ai-memory', 'agent-skills', 'antigravity'} <= words)
        urls = self.metadata()['project_urls']
        labels = {ast.literal_eval(key) for key in urls.keys}
        self.assertTrue({'Tutorial', 'Client verification'} <= labels)

    def test_both_summaries_state_release_channels_and_runtime_limits(self):
        for name in ('llms.txt', 'llms-full.txt'):
            with self.subTest(file=name):
                text = (ROOT / name).read_text(encoding='utf-8')
                for value in ('0.1.0b6', '## Stable', '## Preview', '## Coming next',
                              'pipx install ai-dev-workspace', 'ws start', 'fixture-tested',
                              'best-effort', 'not a security boundary'):
                    self.assertIn(value, text)
                self.assertNotIn('5/5 runs', text)

    def test_released_guides_use_main_links_instead_of_dev_paths(self):
        for name in ('llms.txt', 'llms-full.txt'):
            text = (ROOT / name).read_text(encoding='utf-8')
            for guide in GUIDES:
                self.assertTrue((ROOT / 'docs/guides' / guide).is_file())
                self.assertIn('/blob/main/docs/guides/' + guide, text)
                self.assertNotIn('/blob/dev/docs/guides/' + guide, text)
