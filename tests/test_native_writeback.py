import json
import re
from test_ws import Base
from ws import core, upgrade

BLOCK = re.compile(r'<!--ws:managed:current-task:[^\n]*-->\n(.*?)\n<!--/ws:managed:current-task-->\n', re.S)


class NativeWritebackTests(Base):
    def put(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def start(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Fix the empty-email crash.')

    def test_checkpoint_updates_block_and_preserves_user_text(self):
        agents = self.root / 'AGENTS.md'; gemini = self.root / 'GEMINI.md'
        before = (agents.read_bytes(), gemini.read_bytes())
        copilot = self.put('.github/copilot-instructions.md', 'My rule.\n\nTail without newline')
        self.start()
        self.assertEqual((agents.read_bytes(), gemini.read_bytes()), before)  # hook clients already get the brief
        for path, original in ((copilot, 'My rule.\n\nTail without newline'),):
            text = path.read_text(encoding='utf-8')
            self.assertIn('Fix the empty-email crash.', BLOCK.search(text).group(1))
            self.assertEqual(BLOCK.sub('', text).rstrip('\n'), original.rstrip('\n'))
            self.assertTrue(text.startswith(original.rstrip('\n')))
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Add a regression test.')
        text = copilot.read_text(encoding='utf-8')
        self.assertEqual(len(BLOCK.findall(text)), 1)
        self.assertIn('Add a regression test.', text)
        self.assertNotIn('empty-email crash.', text)

    def test_block_equals_brief_and_says_none_when_idle(self):
        self.start()
        self.assertEqual(BLOCK.search((self.root / '.github/copilot-instructions.md').read_text()).group(1), core.brief(self.root))
        core.checkpoint(self.root, 'T-1', 'done', 'Nothing left.')
        self.assertEqual(BLOCK.search((self.root / '.github/copilot-instructions.md').read_text()).group(1), 'No task in progress.')

    def test_absent_files_are_not_created_and_claude_md_untouched(self):
        claude = self.put('CLAUDE.md', '@AGENTS.md\n')
        (self.root / '.github/copilot-instructions.md').unlink(); (self.root / 'GEMINI.md').unlink()
        self.start()
        self.assertFalse((self.root / '.github/copilot-instructions.md').exists())
        self.assertFalse((self.root / 'GEMINI.md').exists())
        self.assertFalse((self.root / '.cursor').exists())
        self.assertEqual(claude.read_text(), '@AGENTS.md\n')

    def test_cursor_rule_created_only_when_cursor_dir_exists(self):
        (self.root / '.cursor').mkdir()
        self.start()
        text = (self.root / '.cursor/rules/ws-current-task.mdc').read_text(encoding='utf-8')
        self.assertTrue(text.startswith('---\n'))
        self.assertIn('alwaysApply: true', text.split('---\n')[1])
        self.assertIn('Fix the empty-email crash.', text)

    def test_opt_out(self):
        cfg = core.config(self.root); cfg['native_writeback'] = False
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        (self.root / '.cursor').mkdir()
        before = (self.root / '.github/copilot-instructions.md').read_bytes()
        self.start()
        self.assertEqual((self.root / '.github/copilot-instructions.md').read_bytes(), before)
        self.assertFalse((self.root / '.cursor/rules').exists())

    def test_refresh_is_idempotent_and_does_not_rewrite(self):
        self.start()
        agents = self.root / '.github/copilot-instructions.md'
        first = agents.read_bytes(); mtime = agents.stat().st_mtime_ns
        self.assertEqual(core.refresh_native(self.root), [])
        self.assertEqual((agents.read_bytes(), agents.stat().st_mtime_ns), (first, mtime))

    def test_refresh_flag_writes_block_without_checkpoint(self):
        self.assertNotIn('current-task', (self.root / '.github/copilot-instructions.md').read_text())
        self.assertEqual(core.refresh_native(self.root), ['.github/copilot-instructions.md'])
        self.assertIn('No task in progress.', (self.root / '.github/copilot-instructions.md').read_text())

    def test_upgrade_reports_no_changes_after_writeback(self):
        core.upgrade_workspace(self.root)
        self.put('.github/copilot-instructions.md', 'Mine.\n\n' + upgrade.pointer_files()['.github/copilot-instructions.md'])
        self.start()
        self.assertEqual(core.upgrade_workspace(self.root)['changes'], [])

    def test_malformed_duplicate_block_is_left_alone(self):
        text = ('<!--ws:managed:current-task:1-->\na\n<!--/ws:managed:current-task-->\n' * 2)
        path = self.put('.github/copilot-instructions.md', text)
        self.start()
        self.assertEqual(path.read_text(), text)
