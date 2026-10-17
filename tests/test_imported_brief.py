from unittest import mock

from test_ws import Base
from ws import core, knowledge, native


class ImportedBriefTests(Base):
    def test_native_import_is_unverified_and_does_not_replace_onboarding(self):
        item = dict(client='claude', source='claude:rules.md', text='Use integer cents.')
        with mock.patch.object(native, 'collect', return_value=[item]):
            native.import_native(self.root, 'claude', task='T-1', yes=True)
        with mock.patch.object(knowledge, 'onboarding_fields', return_value=[('Team domain:', 'TEAM_ORIENTATION', 8)]):
            brief, summary = core.brief_and_summary(self.root, 'T-1')
        self.assertIn('Imported context (unverified): claude: Use integer cents.', brief)
        self.assertNotIn('Explicit Handoff', brief)
        self.assertIn('TEAM_ORIENTATION', brief)
        self.assertNotIn('Remembered:', summary)
        self.assertIn('No saved memory yet', summary)

    def test_explicit_decision_and_captured_context_keep_their_labels(self):
        path = core.task_path(self.root, 'T-1')
        handoff = ('Decision: Use euros.\n\n### Imported 2026-10-17 (unverified, from codex)\n'
                   '- Use cents.\n<!-- /ws:imported -->\n\n'
                   '### Captured 2026-10-17\nUser constraints: Keep receipts.\n<!-- /ws:captured -->')
        path.write_text(core.set_section(path.read_text(encoding='utf-8'), 'Handoff', handoff), encoding='utf-8')
        brief = core.brief(self.root, 'T-1')
        self.assertIn('Explicit Handoff (saved task record): Decision: Use euros.', brief)
        self.assertIn('Captured last session (unverified):', brief)
        self.assertIn('Imported context (unverified): codex: Use cents.', brief)

    def test_imported_items_are_whole_even_when_the_brief_budget_is_tight(self):
        first = 'Claude memory/first.md: ' + ' '.join(['FIRST'] * 18) + ' (import-first)'
        second = 'Claude memory/second.md: ' + ' '.join(['SECOND'] * 18) + ' (import-second)'
        for prefix_words in (0, 150, 175):
            with self.subTest(prefix_words=prefix_words):
                brief = core._bounded_brief([('', ' '.join(['saved'] * prefix_words), 190),
                                            ('Imported context (unverified):', first + '\n' + second, 35)])
                for item, sentinel in ((first, 'FIRST'), (second, 'SECOND')):
                    if sentinel in brief:
                        self.assertIn(item, brief)
                self.assertNotIn('[…]', brief)
                self.assertLessEqual(len(brief.split()), 200)
        brief = core._bounded_brief([('Imported context (unverified):', first + '\n' + second, 35)])
        self.assertIn('(+1 more in task record)', brief)
