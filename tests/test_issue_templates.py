import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IssueTemplateTests(unittest.TestCase):
    def test_fast_feedback_templates_have_short_prompts(self):
        for filename, name in (('feedback.yml', 'Something confused me'),
                               ('bug.yml', 'Something broke')):
            text = (ROOT / '.github' / 'ISSUE_TEMPLATE' / filename).read_text()
            self.assertIn(f'name: {name}', text)
            self.assertIn('type: textarea', text)
            self.assertLessEqual(text.count('type: textarea'), 2)
            self.assertIn('redact secrets', text.lower())
