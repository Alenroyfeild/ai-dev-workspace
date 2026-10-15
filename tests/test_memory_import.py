import json
import os
import re
import subprocess
import unittest
from unittest import mock
import test_start
from ws import core


class MemoryImportTests(unittest.TestCase):
    setUp = test_start.StartTests.setUp
    start = test_start.StartTests.start

    def sources(self):
        files = {'CLAUDE.md': 'Payments use integer cents.\n',
                 'AGENTS.md': 'Keep receipt currency codes.\n',
                 '.cursorrules': 'Use the existing receipt parser.\n',
                 '.cursor/rules/payments.mdc': '---\nalwaysApply: true\n---\nNo float totals.\n'}
        for name, text in files.items():
            path = self.repo / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        memory = self.home / 'auto-memory'; memory.mkdir()
        (memory / 'MEMORY.md').write_text('Receipt requests need idempotency keys.\n')
        return files, memory

    def test_preview_one_consent_private_copies_first_brief_and_clean_undo(self):
        files, memory = self.sources()
        originals = {self.repo / n: (self.repo / n).read_bytes() for n in files}
        originals[memory / 'MEMORY.md'] = (memory / 'MEMORY.md').read_bytes()
        subprocess.run(['git', 'add', '.'], check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'memory'], check=True)
        code, _, preview = self.start('--dry-run', '--memory-dir', str(memory))
        self.assertEqual(code, 0); self.assertIn('Payments use integer cents', preview)
        self.assertIn('private knowledge', preview); self.assertFalse((self.home / '.ai-dev-workspace').exists())
        with mock.patch('builtins.input', return_value='y') as ask:
            self.assertEqual(self.start('--memory-dir', str(memory))[0], 0)
        ask.assert_called_once(); root = core.find_root()
        entries = list((core.vault(root) / 'Knowledge').glob('import-*.md'))
        self.assertEqual(len(entries), 5)
        self.assertTrue(all('scope: private' in p.read_text() for p in entries))
        self.assertIn('integer cents', core.brief(root)); self.assertIn('unverified', core.brief(root))
        self.assertIn('idempotency keys', '\n'.join(p.read_text() for p in entries))
        self.assertEqual(self.start('--yes')[0], 0)
        self.assertEqual(self.start('--undo')[0], 0)
        self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain']), b'')
        self.assertEqual({p: p.read_bytes() for p in originals}, originals)
        self.assertEqual(self.start('--yes', '--memory-dir', str(memory))[0], 0)
        self.assertEqual(len(list((core.vault(root) / 'Knowledge').glob('import-*.md'))), 5)

    def test_default_claude_memory_is_repo_scoped(self):
        project = re.sub(r'[^A-Za-z0-9]', '-', str(self.repo.resolve()))
        memory = self.home / '.claude/projects' / project / 'memory'; memory.mkdir(parents=True)
        (memory / 'MEMORY.md').write_text('Saved receipt decision.')
        other = self.home / '.claude/projects/other/memory'; other.mkdir(parents=True)
        (other / 'MEMORY.md').write_text('OTHER_PROJECT_SENTINEL')
        with mock.patch.dict(os.environ, CLAUDE_CONFIG_DIR='', CLAUDE_CODE_PROJECT_DIR_NAME=''):
            self.assertEqual(self.start('--yes')[0], 0)
        text = '\n'.join(p.read_text() for p in (core.vault(core.find_root()) / 'Knowledge').glob('import-*.md'))
        self.assertIn('Saved receipt decision', text); self.assertNotIn('OTHER_PROJECT_SENTINEL', text)

    def test_decline_and_opt_out_do_not_import(self):
        _, memory = self.sources()
        with mock.patch('builtins.input', return_value='n') as ask:
            self.assertEqual(self.start('--memory-dir', str(memory))[0], 0)
        ask.assert_called_once(); self.assertFalse((self.home / '.ai-dev-workspace').exists())
        self.assertEqual(self.start('--yes', '--no-import')[0], 0)
        self.assertFalse(list((core.vault(core.find_root()) / 'Knowledge').glob('import-*.md')))

    def test_source_change_during_consent_rejected_before_setup(self):
        def change():
            (self.repo / 'AGENTS.md').write_text('Changed after preview.'); return 'y'
        with mock.patch('builtins.input', side_effect=change): code, _, _ = self.start()
        self.assertEqual(code, 2); self.assertFalse((self.home / '.ai-dev-workspace').exists())

    def test_redaction_private_markers_oversize_and_no_directive_following(self):
        (self.repo / 'AGENTS.md').write_text('token=syntheticsecret123456\n<private>PRIVATE_SENTINEL</private>\n@outside.md\n')
        (self.repo / 'CLAUDE.md').write_text('#private keep this out')
        (self.repo / '.cursorrules').write_text('x' * 70000)
        self.assertEqual(self.start('--yes')[0], 0)
        text = '\n'.join(p.read_text() for p in (core.vault(core.find_root()) / 'Knowledge').glob('import-*.md'))
        self.assertNotIn('syntheticsecret123456', text); self.assertNotIn('PRIVATE_SENTINEL', text)
        self.assertNotIn('keep this out', text); self.assertNotIn('x' * 100, text)

    @unittest.skipIf(os.name == 'nt', 'Windows symlink fixture needs developer mode')
    def test_symlink_sources_do_not_import(self):
        outside = self.home / 'outside.md'; outside.write_text('PRIVATE_SENTINEL')
        (self.repo / 'CLAUDE.md').symlink_to(outside)
        self.assertEqual(self.start('--yes')[0], 0)
        text = '\n'.join(p.read_text() for p in (core.vault(core.find_root()) / 'Knowledge').glob('import-*.md'))
        self.assertNotIn('PRIVATE_SENTINEL', text)

    @unittest.skipIf(os.name == 'nt', 'Windows symlink fixture needs developer mode')
    def test_custom_memory_symlink_parent_outside_home_is_skipped(self):
        outside = self.repo.parent.resolve() / 'other-memory'; outside.mkdir()
        (outside / 'child').mkdir()
        (outside / 'child/MEMORY.md').write_text('ESCAPED_MEMORY_SENTINEL')
        parent = self.repo.parent.resolve() / 'linked-memory'; parent.symlink_to(outside, target_is_directory=True)
        code, _, preview = self.start('--yes', '--memory-dir', str(parent / 'child'))
        self.assertEqual(code, 0)
        text = '\n'.join(p.read_text() for p in (core.vault(core.find_root()) / 'Knowledge').glob('import-*.md'))
        self.assertNotIn('ESCAPED_MEMORY_SENTINEL', text)

    def test_rule_file_limit_is_visible_in_preview(self):
        rules = self.repo / '.cursor/rules'; rules.mkdir(parents=True)
        for i in range(17): (rules / f'{i:02}.mdc').write_text('Receipt rule.')
        code, _, preview = self.start('--dry-run')
        self.assertEqual(code, 0); self.assertIn('1 Cursor rule file(s) skipped: 16-file limit', preview)

    def test_new_source_after_preview_is_not_silently_approved(self):
        def add_source():
            (self.repo / 'CLAUDE.md').write_text('UNAPPROVED_LATE_SOURCE'); return 'y'
        with mock.patch('builtins.input', side_effect=add_source): code, _, _ = self.start()
        self.assertEqual(code, 0)
        text = '\n'.join(p.read_text() for p in (core.vault(core.find_root()) / 'Knowledge').glob('import-*.md'))
        self.assertIn('User rules remain', text); self.assertNotIn('UNAPPROVED_LATE_SOURCE', text)
