from test_ws import Base
from ws import core, lesson_rules
from testutil import run_ws, needs_symlinks


class LessonPromotionTests(Base):
    def test_three_repetitions_suggest_without_writing_and_command_drafts(self):
        text = 'Cache invalidation requires bounded retries before release.'
        for _ in range(2): core.lesson_add(self.root, text)
        self.assertEqual(lesson_rules.candidates(self.root), [])
        core.lesson_add(self.root, text)
        candidate = lesson_rules.candidates(self.root)[0]
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect cache retries.')
        self.assertIn('ws lesson promote ' + candidate['id'], core.brief(self.root))
        self.assertFalse((self.root / '.ws/rule-drafts').exists())
        result = lesson_rules.promote(self.root, candidate['id'])
        from pathlib import Path
        path = Path(result['draft']); self.assertIn('Draft for review', path.read_text())
        path.write_text('User edited draft.')
        lesson_rules.promote(self.root, candidate['id'])
        self.assertEqual(path.read_text(), 'User edited draft.')
        result = run_ws('lesson', 'promote', candidate['id'], cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Existing draft kept', result.stdout)

    def test_related_dead_end_counts_and_private_spans_do_not(self):
        text = 'Database migrations need transaction rollback tests.'
        for _ in range(2): core.lesson_add(self.root, text)
        path = core.task_path(self.root, 'T-1')
        path.write_text(core.set_section(path.read_text(), 'Do not redo', text))
        self.assertTrue(lesson_rules.candidates(self.root))
        path.write_text(core.set_section(path.read_text(), 'Do not redo', '<private>' + text + '</private>'))
        self.assertEqual(lesson_rules.candidates(self.root), [])
        with self.assertRaises(core.WsError): lesson_rules.promote(self.root, '../outside')

    @needs_symlinks
    def test_rule_draft_directory_cannot_escape(self):
        for _ in range(3): core.lesson_add(self.root, 'Cache invalidation requires bounded retries before release.')
        candidate = lesson_rules.candidates(self.root)[0]
        directory = self.root / '.ws/rule-drafts'; directory.parent.mkdir(exist_ok=True)
        outside = self.root.parent / 'outside'; outside.mkdir()
        directory.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(core.WsError): lesson_rules.promote(self.root, candidate['id'])
        self.assertEqual(list(outside.iterdir()), [])
