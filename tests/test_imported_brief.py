from test_ws import Base
from ws import core


class ImportedBriefTests(Base):
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
