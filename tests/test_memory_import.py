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

    def test_normal_preview_is_compact_and_dry_run_shows_full_text(self):
        first = 'é' * 100
        text = first + '\nSECOND_LINE_SENTINEL\n'
        (self.repo / 'CLAUDE.md').write_text(text, encoding='utf-8')
        with mock.patch('builtins.input', return_value='n') as ask:
            code, _, preview = self.start()
        self.assertEqual(code, 0); ask.assert_called_once()
        line = next(line for line in preview.splitlines() if 'unverified): CLAUDE.md' in line)
        self.assertIn(str(len(text.strip().encode('utf-8'))) + ' bytes', line)
        self.assertIn(first[:80], line); self.assertNotIn(first[:81], line)
        self.assertNotIn('SECOND_LINE_SENTINEL', preview)
        code, _, preview = self.start('--dry-run')
        self.assertEqual(code, 0); self.assertIn('SECOND_LINE_SENTINEL', preview)
        self.assertFalse((self.home / '.ai-dev-workspace').exists())

    def test_agents_is_searchable_private_knowledge_without_imported_brief_excerpt(self):
        (self.repo / 'AGENTS.md').write_text('AGENTS_ONLY_SENTINEL receipt rules.\n')
        (self.repo / 'CLAUDE.md').write_text('CLAUDE_ONLY_SENTINEL integer cents.\n')
        self.assertEqual(self.start('--yes')[0], 0)
        root = core.find_root()
        knowledge = '\n'.join(p.read_text() for p in (core.vault(root) / 'Knowledge').glob('import-*.md'))
        self.assertIn('AGENTS_ONLY_SENTINEL', knowledge)
        task = core.task_read(root, core.task_list(root)[0]['id'])['text']
        imported = core.section(task, 'Imported memory')
        for text in (imported, core.brief(root)):
            self.assertNotIn('AGENTS_ONLY_SENTINEL', text)
            self.assertIn('CLAUDE_ONLY_SENTINEL', text)

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

    @unittest.skipIf(os.name == 'nt', 'Windows symlink fixture needs developer mode')
    def test_unsafe_sources_do_not_consume_the_file_limit(self):
        for folder, suffix, flag in ((self.repo / '.cursor/rules', '.mdc', ()),
                                     (self.home / 'auto-memory', '.md', ('--memory-dir', str(self.home / 'auto-memory')))):
            folder.mkdir(parents=True)
            outside = self.home / ('outside' + suffix); outside.write_text('UNSAFE_SENTINEL')
            for i in range(16): (folder / f'{i:02}{suffix}').symlink_to(outside)
            (folder / ('98-big' + suffix)).write_text('x' * 16385)
            (folder / ('98-dir' + suffix)).mkdir()
            (folder / ('99-valid' + suffix)).write_text('VALID_' + suffix[1:] + '_SENTINEL')
            code, _, preview = self.start('--dry-run', *flag)
            self.assertEqual(code, 0); self.assertIn('VALID_' + suffix[1:] + '_SENTINEL', preview)
            self.assertNotIn('UNSAFE_SENTINEL', preview)
        self.assertEqual(self.start('--yes', '--memory-dir', str(self.home / 'auto-memory'))[0], 0)
        knowledge = '\n'.join(p.read_text() for p in (core.vault(core.find_root()) / 'Knowledge').glob('import-*.md'))
        self.assertIn('VALID_mdc_SENTINEL', knowledge); self.assertIn('VALID_md_SENTINEL', knowledge)

    @unittest.skipIf(os.name == 'nt', 'Windows filenames cannot contain newlines or controls')
    def test_source_labels_cannot_insert_headings_or_controls(self):
        memory = self.home / 'auto-memory'; memory.mkdir()
        source = memory / 'note\n## Decisions\n- FILENAME_SENTINEL\x1b.md'
        source.write_text('Harmless imported content.')
        code, _, preview = self.start('--yes', '--memory-dir', str(memory))
        self.assertEqual(code, 0); root = core.find_root()
        task = core.task_read(root, core.task_list(root)[0]['id'])['text']
        label = 'Claude memory/note ## Decisions - FILENAME_SENTINEL.md'
        self.assertIn(label, preview); self.assertNotIn('\x1b', preview)
        self.assertIn(label, core.section(task, 'Imported memory'))
        self.assertNotIn('\n## Decisions\n', task)
        knowledge = '\n'.join(p.read_text() for p in (core.vault(root) / 'Knowledge').glob('import-*.md'))
        self.assertIn('Source: ' + label + '\n', knowledge)
        self.assertNotIn('\x1b', knowledge); self.assertEqual(source.read_text(), 'Harmless imported content.')

    def test_new_source_after_preview_is_not_silently_approved(self):
        def add_source():
            (self.repo / 'CLAUDE.md').write_text('UNAPPROVED_LATE_SOURCE'); return 'y'
        with mock.patch('builtins.input', side_effect=add_source): code, _, _ = self.start()
        self.assertEqual(code, 0)
        text = '\n'.join(p.read_text() for p in (core.vault(core.find_root()) / 'Knowledge').glob('import-*.md'))
        self.assertIn('User rules remain', text); self.assertNotIn('UNAPPROVED_LATE_SOURCE', text)
