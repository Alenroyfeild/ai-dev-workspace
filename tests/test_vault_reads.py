import datetime
import os
import subprocess
import types
import unittest
from pathlib import Path
from unittest import mock

from test_ws import Base
from ws import cli, core, scope


def notes(root, **files):
    for name, text in files.items():
        path = core.vault(root) / name.replace('__', '/'); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)


class BadByteTests(Base):
    """One non-UTF-8 byte in a hand-edited vault file must not crash reads, and validate must name it."""
    def test_display_commands_survive_and_validate_names_the_file(self):
        vault = core.vault(self.root)
        core.lesson_add(self.root, 'Cache needs a restart after deploy → restart it')
        core.feedback_add(self.root, 'a problem worth noting', 'bug')
        for name in ('Learnings.md', 'Feedback.md'):
            with open(vault / name, 'ab') as f: f.write(b'\n- it\x92s here\n')
        with open(vault / 'Tasks/T-1.md', 'ab') as f: f.write(b'\x92')
        runs = vault / 'Runs'; runs.mkdir(exist_ok=True)
        (runs / 'T-1.jsonl').write_bytes(b'{"provider":"x","tokens_in":1,"tokens_out":1,"seconds":1,"result":"ok","note":"\x92"}\n')
        self.assertTrue(core.lesson_search(self.root, 'restart'))
        core.feedback_list(self.root); core.task_read(self.root, 'T-1'); core.status(self.root); core.run_entries(self.root, 'T-1')
        report = core.validate(self.root)
        self.assertFalse(report['valid'])
        for name in ('Tasks/T-1.md', 'Learnings.md', 'Feedback.md', 'Runs/T-1.jsonl'):
            self.assertTrue(any(name in e.replace(os.sep, '/') and 'not valid UTF-8 (byte offset ' in e for e in report['errors']), (name, report['errors']))

    def test_rewrites_refuse_with_a_clear_error_naming_the_file(self):
        vault = core.vault(self.root)
        with open(vault / 'Tasks/T-1.md', 'ab') as f: f.write(b'\x92')
        with self.assertRaisesRegex(core.WsError, r'T-1\.md is not valid UTF-8'):
            core.claim(self.root, 'T-1', 'w')
        (vault / 'Learnings.md').write_bytes(b'# L\n\x92\n')
        with self.assertRaisesRegex(core.WsError, r'Learnings\.md is not valid UTF-8'):
            core.lesson_add(self.root, 'Another lesson that is long enough')


class DotDirectoryTests(Base):
    def test_trash_and_obsidian_are_not_searched_or_validated(self):
        notes(self.root, **{'.trash__Gone.md': 'quokka [[nowhere]]', '.obsidian__plugins__foo__README.md': 'quokka [[nope]] token=ghp_' + 'a' * 36,
                            'Kept.md': 'quokka lives here'})
        hits = str(core.search(self.root, 'quokka'))
        self.assertIn('Kept.md', hits); self.assertNotIn('Gone', hits); self.assertNotIn('README', hits)
        self.assertEqual(core.validate(self.root)['errors'], [])
        self.assertEqual(core.validate(self.root)['warnings'], [])


class ValidateLinkTests(Base):
    def test_valid_obsidian_forms_pass(self):
        notes(self.root, **{'Assets__diagram.png': 'x', 'README.md': '# r', 'Learnings2.md': '# l',
                            'Guide.md': '![[diagram.png]] [[readme]] [[Tasks/T-1.md]] [[Tasks/../Learnings2]]\n```\n[[example-in-fence]]\n```\nand `[[inline]]` here [[Learnings2#h|alias]]'})
        self.assertEqual(core.validate(self.root)['errors'], [])

    def test_real_broken_links_still_fail(self):
        notes(self.root, **{'Guide.md': '[[missing]] ![[missing.png]]'})
        self.assertEqual(len(core.validate(self.root)['errors']), 2)

    def test_duplicate_keys_missing_dependency_and_cycles_warn(self):
        core.task_new(self.root, 'T-2', 'Second', 'x'); core.task_new(self.root, 'T-3', 'Third', 'x')
        for tid, extra in (('T-1', 'depends_on: T-2'), ('T-2', 'depends_on: T-1'), ('T-3', 'depends_on: GONE\nstatus: done')):
            path = core.task_path(self.root, tid); path.write_text(path.read_text().replace('\n---', '\n' + extra + '\n---', 1))
        report = core.validate(self.root)
        self.assertTrue(report['valid'], report['errors'])
        text = '\n'.join(report['warnings'])
        self.assertIn('T-3.md: duplicate frontmatter key status', text)
        self.assertIn('T-3.md: depends_on names missing task GONE', text)
        self.assertIn('T-1.md: depends_on forms a dependency cycle', text)
        self.assertIn('T-2.md: depends_on forms a dependency cycle', text)


class RepoPathTests(Base):
    def test_one_rule_for_relative_and_tilde_repos(self):
        self.assertEqual(core.repo_path(self.root, '../repo1'), (self.root.parent / 'repo1').resolve())
        self.assertEqual(core.repo_path(self.root, '~/x'), (Path.home() / 'x').resolve())
        elsewhere = Path(self.tmp.name) / 'elsewhere'; elsewhere.mkdir()
        repo = Path(self.tmp.name) / 'repo1'; subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        core.task_new(self.root, 'T-9', 'Rel', 'x', repo='../repo1')
        cfg = core.config(self.root); cfg['repos'] = [str(repo)]
        (self.root / 'workspace.json').write_text(__import__('json').dumps(cfg))
        cwd = os.getcwd(); os.chdir(elsewhere)
        try: self.assertTrue(core._task_git(self.root, 'T-9', 'rev-parse', '--show-toplevel').strip())
        finally: os.chdir(cwd)

    def test_graphify_report_of_a_relative_repo_is_found_from_a_nested_cwd(self):
        report = self.root.parent / 'repo1/graphify-out/GRAPH_REPORT.md'; report.parent.mkdir(parents=True)
        report.write_text('quokka architecture\n')
        cfg = core.config(self.root); cfg['repos'] = ['../repo1']
        (self.root / 'workspace.json').write_text(__import__('json').dumps(cfg))
        nested = Path(self.tmp.name) / 'other/nested'; nested.mkdir(parents=True)
        cwd = os.getcwd(); os.chdir(nested)
        try: hits = core.search(self.root, 'quokka')
        finally: os.chdir(cwd)
        self.assertIn('GRAPH_REPORT.md', str(hits))


class RecapClockTests(Base):
    def test_cutoff_uses_utc_day_like_updated_stamps(self):
        path = core.task_path(self.root, 'T-1')
        path.write_text(core.set_meta(path.read_text(), {'updated': '2026-10-19T06:37:01+00:00'}))
        real = datetime
        class Date(real.date):
            @classmethod
            def today(cls): return cls(2026, 10, 20)  # local date already ahead of UTC
        class DateTime(real.datetime):
            @classmethod
            def now(cls, tz=None): return cls(2026, 10, 19, 20, 0, tzinfo=tz)
        fake = types.SimpleNamespace(date=Date, datetime=DateTime, timezone=real.timezone, timedelta=real.timedelta)
        with mock.patch.object(core, 'datetime', fake):
            self.assertEqual([t['id'] for t in core.recap(self.root, '0d')['tasks']], ['T-1'])


class ScopeMissingTests(Base):
    def test_missing_lesson_directory_gives_a_clear_message(self):
        for kind in ('lesson', 'decision'):
            with self.assertRaisesRegex(core.WsError, rf'No {kind} record abc; kinds are task, decision, lesson, knowledge'):
                scope.record(self.root, f'{kind}:abc')


if __name__ == '__main__':
    unittest.main()
