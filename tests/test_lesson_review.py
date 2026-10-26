import datetime
import json
from unittest import mock
from test_ws import Base
from testutil import run_ws, needs_symlinks
from ws import core


class LessonReviewTests(Base):
    def write_lessons(self, text):
        path = core.vault(self.root) / 'Learnings.md'
        path.write_text(text, encoding='utf-8')
        return path

    def test_default_is_strictly_older_than_sixty_days_and_sorts_oldest_first(self):
        self.write_lessons('- 2026-08-26 Review retry budgets. #tests\n'
                           '- 2026-08-27 Boundary lesson stays out.\n'
                           '- 2026-01-01 Older lesson comes first.\n'
                           '- 2026-10-26 Fresh lesson stays out.\n')
        with mock.patch.object(core, 'now', return_value='2026-10-26T12:00:00Z'):
            result = core.lesson_review(self.root)
        self.assertEqual(result['before'], '2026-08-27')
        self.assertEqual([r['date'] for r in result['lessons']], ['2026-01-01', '2026-08-26'])
        self.assertEqual(result['lessons'][1]['age_days'], 61)
        self.assertIn('date stamps', result['basis'])

    def test_invalid_and_undated_lessons_are_reported_not_inferred(self):
        self.write_lessons('- A legacy undated lesson.\n- 2026-02-30 Invalid calendar date.\n'
                           '- 2027-01-01 Future lesson.\n')
        with mock.patch.object(core, 'now', return_value='2026-10-26T12:00:00Z'):
            result = core.lesson_review(self.root, 0)
        self.assertEqual(result['lessons'], [])
        self.assertEqual(result['undated'], 2)

    def test_metadata_private_spans_and_secrets_do_not_leak(self):
        token = 'ghp_' + 'aB12' * 10
        self.write_lessons('- 2026-01-01 Review retries <private>hidden phrase</private> ' + token +
                           ' <!-- ws:lesson {"format":1,"paths":["hidden/*"],"area":"hidden-area"} -->\n'
                           '<private>\n- 2020-01-01 Multiline hidden lesson.\n</private>\n'
                           '- 2020-01-01 Tagged hidden lesson. #private\n')
        result = core.lesson_review(self.root)
        self.assertEqual(len(result['lessons']), 1)
        shown = json.dumps(result)
        for value in ('hidden phrase', 'hidden/*', 'hidden-area', 'Multiline hidden lesson', 'Tagged hidden lesson', token):
            self.assertNotIn(value, shown)
        self.assertIn('Review retries', shown)

    def test_days_handles_leap_boundary_and_rejects_invalid_windows(self):
        self.write_lessons('- 2024-02-28 Old leap-year lesson.\n- 2024-02-29 Boundary lesson.\n')
        with mock.patch.object(core, 'now', return_value='2024-03-01T12:00:00Z'):
            result = core.lesson_review(self.root, 1)
        self.assertEqual([r['date'] for r in result['lessons']], ['2024-02-28'])
        for value in (-1, True, '60', 10**20):
            with self.subTest(value=value), self.assertRaises(core.WsError):
                core.lesson_review(self.root, value)

    def test_missing_log_and_review_are_read_only(self):
        path = core.vault(self.root) / 'Learnings.md'
        if path.exists(): path.unlink()
        self.assertEqual(core.lesson_review(self.root)['lessons'], [])
        self.assertFalse(path.exists())
        self.write_lessons('- 2020-01-01 Keep this old lesson exactly as saved.\n')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        core.lesson_review(self.root)
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_cli_review_custom_days_and_invalid_days(self):
        self.write_lessons('- 2000-01-01 A very old lesson for manual review.\n')
        result = run_ws('--workspace-root', self.root, 'lesson', 'review', '--days', '30')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['days'], 30)
        self.assertIn('manual review', result.stdout)
        for days in ('-1', 'nonsense'):
            result = run_ws('--workspace-root', self.root, 'lesson', 'review', '--days', days)
            self.assertNotEqual(result.returncode, 0)

    @needs_symlinks
    def test_log_symlink_cannot_read_outside_workspace(self):
        path = core.vault(self.root) / 'Learnings.md'
        if path.exists(): path.unlink()
        outside = self.root.parent / 'outside-lessons.md'
        outside.write_text('- 2000-01-01 Unrelated outside workspace text.\n')
        path.symlink_to(outside)
        with self.assertRaises(core.WsError): core.lesson_review(self.root)
