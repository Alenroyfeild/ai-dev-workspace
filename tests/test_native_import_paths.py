import json
import os
from pathlib import Path

from test_native_memory import NativeBase
from ws import core, native


class NativeImportPathTests(NativeBase):
    def relative_repos(self):
        cfg = core.config(self.root); cfg['repos'] = ['ios']
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        intended = self.root / 'ios'; intended.mkdir()
        elsewhere = Path(self.tmp.name) / 'elsewhere'; elsewhere.mkdir()
        unrelated = elsewhere / 'ios'; unrelated.mkdir()
        previous = Path.cwd(); os.chdir(elsewhere)
        self.addCleanup(os.chdir, previous)
        return intended, unrelated

    def test_claude_relative_repo_uses_workspace_not_current_directory(self):
        intended, unrelated = self.relative_repos()
        self.memory(self.claude_dir(intended), 'wanted', 'WORKSPACE_RULE')
        self.memory(self.claude_dir(unrelated), 'unrelated', 'OTHER_REPO_CANARY')
        sources = {p: p.read_bytes() for p in self.home.rglob('*.md')}
        before = self.handoff()
        preview = native.import_native(self.root, 'claude')
        self.assertEqual(self.handoff(), before)
        self.assertIn('WORKSPACE_RULE', json.dumps(preview))
        self.assertNotIn('OTHER_REPO_CANARY', json.dumps(preview))
        native.import_native(self.root, 'claude', yes=True)
        self.assertIn('WORKSPACE_RULE', self.handoff())
        self.assertNotIn('OTHER_REPO_CANARY', self.handoff())
        self.assertEqual({p: p.read_bytes() for p in sources}, sources)

    def test_codex_relative_repo_never_uses_unrelated_current_directory(self):
        intended, unrelated = self.relative_repos()
        # Short names have no basename heuristic, isolating the absolute-path match.
        self.memories_db([('wanted', 'Worked in ' + str(intended.resolve()), 'WORKSPACE_RULE', 'wanted', 2),
                          ('other', 'Worked in ' + str(unrelated.resolve()), 'OTHER_REPO_CANARY', 'other', 1)])
        database = self.codex / 'memories_1.sqlite'; before = database.read_bytes()
        preview = native.import_native(self.root, 'codex')
        self.assertIn('WORKSPACE_RULE', json.dumps(preview))
        self.assertNotIn('OTHER_REPO_CANARY', json.dumps(preview))
        native.import_native(self.root, 'codex', yes=True)
        self.assertIn('WORKSPACE_RULE', self.handoff())
        self.assertNotIn('OTHER_REPO_CANARY', self.handoff())
        self.assertEqual(database.read_bytes(), before)
