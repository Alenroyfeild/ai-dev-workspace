"""Records written by each released beta must still load and work with the current kit (EXIT-04 proof).

tests/fixtures/records/<tag>/ holds the portable records (workspace.json, tasks, learnings, knowledge)
that the tag's own `ws` wrote from synthetic text; __REPO__ stands for the code checkout path.
"""
import re
import subprocess
from pathlib import Path
from test_ws import Base
from ws import core

CORPUS = Path(__file__).resolve().parent / 'fixtures/records'
DECISION = 'Prices are integer cents'
NEXT = 'Finish the cents conversion in price.py'
# Tags whose records fail with the current kit: tag -> reason (the subTest is then skipped).
KNOWN_FAILURES = {}
# Errors the tag's own `ws validate` already reported on its own fresh workspace (not a compatibility break).
OWN_VALIDATE_ERRORS = {'v0.1.0-beta.4': ['main.md: empty Next action']}


class RecordCorpusTests(Base):
    def git(self, repo, *args):
        cmd = ['git', '-C', str(repo), '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', '-c', 'core.hooksPath=/dev/null', *args]
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()

    def restore(self, tag):
        base = Path(self.tmp.name) / tag
        root, repo = base / 'ws', base / 'repo'
        repo.mkdir(parents=True)
        self.git(repo, 'init', '-q'); self.git(repo, 'commit', '-q', '--allow-empty', '-m', 'init')
        for src in (CORPUS / tag).rglob('*'):
            if src.is_file():
                dst = root / src.relative_to(CORPUS / tag)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(src.read_text(encoding='utf-8').replace('__REPO__', str(repo)), encoding='utf-8')
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
        self.assertIn(DECISION, core.recap(root)['markdown'])
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

    def test_records_from_every_release_still_load(self):
        tags = sorted(p.name for p in CORPUS.iterdir() if p.is_dir())
        self.assertGreaterEqual(len(tags), 4)
        for tag in tags:
            with self.subTest(tag=tag):
                if tag in KNOWN_FAILURES:
                    self.skipTest(f'known: {KNOWN_FAILURES[tag]}')
                self.check(tag)

    def test_fixtures_hold_no_absolute_paths_or_claims(self):
        for path in CORPUS.rglob('*'):
            if path.is_file():
                self.assertNotRegex(path.read_text(encoding='utf-8'), r'/(tmp|private|Users|home)/', path)
                self.assertNotIn('.ws', path.relative_to(CORPUS).parts)
