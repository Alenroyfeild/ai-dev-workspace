"""Records written by each released beta must still load and work with the current kit (EXIT-04 proof).

tests/fixtures/records/<tag>/ holds the portable records (workspace.json, tasks, learnings, knowledge)
that the tag's own `ws` wrote from synthetic text; __REPO__ stands for the code checkout path.
"""
import json
import re
import subprocess
from pathlib import Path
from test_ws import Base
from ws import core

CORPUS = Path(__file__).resolve().parent / 'fixtures/records'
FUTURE = Path(__file__).resolve().parent / 'fixtures/records-future'  # synthetic records from a kit newer than this one
DECISION = 'Prices are integer cents'
NEXT = 'Finish the cents conversion in price.py'
# Tags whose records fail with the current kit: tag -> reason (the subTest is then skipped).
KNOWN_FAILURES = {}
# Errors the current kit still reports for a tag's records (beta.4's fresh-task error was fixed in #187).
OWN_VALIDATE_ERRORS = {}


def fill(src, repo):
    where = json.dumps(str(repo))[1:-1] if src.suffix == '.json' else str(repo)  # a Windows path needs JSON escaping
    return src.read_text(encoding='utf-8').replace('__REPO__', where)


class RecordCorpusTests(Base):
    def git(self, repo, *args):
        cmd = ['git', '-C', str(repo), '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', '-c', 'core.hooksPath=/dev/null', *args]
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()

    def restore(self, tag, corpus=CORPUS):
        base = Path(self.tmp.name) / tag
        root, repo = base / 'ws', base / 'repo'
        repo.mkdir(parents=True)
        self.git(repo, 'init', '-q'); self.git(repo, 'commit', '-q', '--allow-empty', '-m', 'init')
        for src in (corpus / tag).rglob('*'):
            if src.is_file():
                dst = root / src.relative_to(corpus / tag)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(fill(src, repo), encoding='utf-8')
        return root

    def check(self, tag):
        root = self.restore(tag)
        report = core.validate(root)
        self.assertEqual(report['errors'], OWN_VALIDATE_ERRORS.get(tag, []))
        task = core.task_find(root, 'PRICE-1')
        self.assertEqual([t['id'] for t in task], ['PRICE-1'])
        self.assertEqual(task[0]['next'], NEXT)
        self.assertIn('PRICE-1', [t['id'] for t in core.task_list(root)])
        self.assertIn(DECISION, core.brief(root, 'PRICE-1'))
        self.assertIn(DECISION, core.recap(root, '2026-10-16')['markdown'])
        self.assertIn(DECISION, core.pr_notes(root, 'PRICE-1')['markdown'])
        self.assertTrue(core.upgrade_workspace(root, dry_run=True)['dry_run'])
        before = core.task_read(root, 'PRICE-1')
        meta = core.parse_meta(before['text'])
        core.checkpoint(root, 'PRICE-1', 'in_progress', 'Add the rounding test.', worker=meta['claimed_by'],
                        token=meta['claim_token'], notes={'Findings': 'Synthetic finding.'})
        after = core.task_read(root, 'PRICE-1')
        self.assertEqual(core.section(after['text'], 'Next action'), 'Add the rounding test.')
        self.assertIn(DECISION, core.brief(root, 'PRICE-1'))
        for name in re.findall(r'^## (.+?)[ \t]*$', before['text'], re.M):
            if name not in ('Next action', 'Findings'):
                self.assertIn(core.section(before['text'], name), core.section(after['text'], name), name)
        self.assertIn('Synthetic finding.', core.section(after['text'], 'Findings'))
        self.assertEqual(core.task_format(core.parse_meta(after['text'])), 1)  # a released file reads as format 1 ...
        self.assertNotIn('format', core.parse_meta(after['text']))  # ... and a checkpoint does not rewrite it to say so
        self.assertEqual(core.lesson_search(root, 'cents')[0][:12], '- 2026-10-16')

    def test_records_from_every_release_still_load(self):
        tags = sorted(p.name for p in CORPUS.iterdir() if p.is_dir())
        self.assertGreaterEqual(len(tags), 4)
        for tag in tags:
            with self.subTest(tag=tag):
                if tag in KNOWN_FAILURES:
                    self.skipTest(f'known: {KNOWN_FAILURES[tag]}')
                self.check(tag)

    def test_newer_format_records_are_read_only_and_never_rewritten(self):
        root = self.restore('format-99', FUTURE)
        task, ledger = root / 'vault/Tasks/FUT-1.md', root / 'vault/Learnings.md'
        before = task.read_bytes()
        self.assertEqual(core.validate(root)['errors'], [])
        found = core.task_find(root, 'FUT-1')
        self.assertEqual([t['id'] for t in found], ['FUT-1'])
        self.assertIn('format 99', found[0]['format_warning'])
        brief = core.brief(root, 'FUT-1')
        self.assertIn('Wait for the kit update', brief)
        self.assertEqual(brief.count('written by a newer ai-dev-workspace (format 99)'), 1)
        recap = core.recap(root, '2026-01-01')['markdown']
        self.assertIn('Totals are kept as ledger entries', recap)
        self.assertEqual(recap.count('written by a newer ai-dev-workspace (format 99)'), 1)
        self.assertTrue(core.upgrade_workspace(root, dry_run=True)['dry_run'])
        writes = (lambda: core.claim(root, 'FUT-1', 'w'), lambda: core.remember(root, 'use ledgers', 'FUT-1'),
                  lambda: core.checkpoint(root, 'FUT-1', 'in_progress', 'Next.', worker='w', token='t'))
        for write in writes:
            with self.assertRaisesRegex(core.WsError, r'written by a newer ai-dev-workspace \(format 99\); update the kit'):
                write()
        self.assertEqual(task.read_bytes(), before)
        lessons, lesson_before = core.lesson_search(root, 'ledger'), ledger.read_bytes()
        self.assertIn('"format": 99', lessons[0])  # shown as written
        self.assertIn('Keep future ledger totals', ' '.join(core.relevant_lessons(root, core.task_find(root, 'FUT-1')[0])))
        core.lesson_add(root, 'Round half up when converting cents', paths=['price.py'])
        self.assertTrue(ledger.read_bytes().startswith(lesson_before))  # the newer lesson is kept byte for byte

    def test_appending_a_lesson_keeps_crlf_newer_lesson_bytes(self):
        root = self.restore('format-99', FUTURE)
        ledger = root / 'vault/Learnings.md'
        ledger.write_bytes(ledger.read_bytes().replace(b'\n', b'\r\n'))
        before = ledger.read_bytes()
        core.lesson_add(root, 'Round half up when converting cents', paths=['price.py'])
        after = ledger.read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertTrue(after[len(before):].endswith(b'\r\n'))  # the new line uses the file's line ending

    def test_task_with_a_late_newer_format_key_is_not_overwritten(self):
        path = Path(self.tmp.name) / 'late/Tasks/T.md'
        path.parent.mkdir(parents=True)
        text = '---\npadding: ' + 'x' * 5000 + '\nformat: 99\n---\nfuture task\n'
        path.write_text(text, encoding='utf-8')
        with self.assertRaisesRegex(core.WsError, 'format 99'):
            core.atomic_write(path, 'replacement\n')
        self.assertEqual(path.read_text(encoding='utf-8'), text)

    def test_task_with_unterminated_oversized_frontmatter_is_refused(self):
        path = Path(self.tmp.name) / 'big/Tasks/T.md'
        path.parent.mkdir(parents=True)
        text = '---\npadding: ' + 'x' * (core.MAX_FRONTMATTER + 10) + '\n'
        path.write_text(text, encoding='utf-8')
        with self.assertRaisesRegex(core.WsError, 'frontmatter over'):
            core.atomic_write(path, 'replacement\n')
        self.assertEqual(path.read_text(encoding='utf-8'), text)

    def test_json_fixtures_stay_valid_for_a_backslash_repo_path(self):
        for src in (*CORPUS.rglob('*.json'), *FUTURE.rglob('*.json')):
            json.loads(fill(src, 'C:\\Users\\x\\repo'))

    def test_fixtures_hold_no_absolute_paths_or_claims(self):
        for corpus in (CORPUS, FUTURE):
            for path in corpus.rglob('*'):
                if path.is_file():
                    self.assertNotRegex(path.read_text(encoding='utf-8'), r'/(tmp|private|Users|home)/', path)
                    self.assertNotIn('.ws', path.relative_to(corpus).parts)
