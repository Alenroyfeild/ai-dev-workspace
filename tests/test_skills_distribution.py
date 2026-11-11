import re
import unittest
from itertools import combinations
from pathlib import Path

from ws import core


ROOT = Path(__file__).resolve().parents[1]

# Generic workspace terms do not distinguish routing intent. core.STOPWORDS
# does not currently remove either of these words.
LINT_COMMON = {'task', 'session'}
TRIGGERS = {
    'handoff': 'Save verified progress and checkpoint before handing off',
    'pickup': 'Resume the workspace and show saved blockers',
    'lesson': 'Record the requested mistake to rule lesson',
    'thinkbeforeact': 'Plan requested code changes and check risk',
}


def skill_words(value):
    return core._words(value) - LINT_COMMON


def lint_description(text):
    if not text.startswith('---\n') or '\n---\n' not in text[4:]:
        raise ValueError('missing frontmatter')
    description = core.parse_meta(text).get('description', '').strip()
    if not description or len(description) > 250 or not re.search(r'\bwhen\b', description, re.I):
        raise ValueError('description needs when and at most 250 characters')
    if len(skill_words(description)) < 4 or re.search(r'\b(?:help with anything|general purpose|all requests)\b', description, re.I):
        raise ValueError('description is too vague')
    return description


def trigger_winner(request, descriptions):
    scores = {name: len(skill_words(request) & skill_words(value)) for name, value in descriptions.items()}
    top = max(scores.values(), default=0)
    winners = [name for name, score in scores.items() if score == top]
    if not top or len(winners) != 1: raise ValueError('ambiguous or unmatched trigger')
    return winners[0]


def description_overlap(first, second):
    left, right = skill_words(first), skill_words(second)
    return len(left & right) / len(left | right) if left | right else 1.0


class SkillDistributionTests(unittest.TestCase):
    def test_four_descriptions_and_pinned_triggers_are_distinct(self):
        descriptions = {name: lint_description((ROOT / 'skills' / name / 'SKILL.md').read_text(encoding='utf-8'))
                        for name in TRIGGERS}
        for a, b in combinations(descriptions, 2):
            self.assertLess(description_overlap(descriptions[a], descriptions[b]), 0.5, (a, b))
        for expected, request in TRIGGERS.items():
            with self.subTest(request=request):
                self.assertEqual(trigger_winner(request, descriptions), expected)

    def test_lint_rejects_missing_intent_length_and_vague_descriptions(self):
        for bad in ('no frontmatter', '---\nname: x\n---\n',
                    '---\ndescription: Save helpful context for tasks.\n---\n',
                    '---\ndescription: Use when ' + 'long ' * 60 + '\n---\n',
                    '---\ndescription: Use when you need help with anything.\n---\n'):
            with self.subTest(bad=bad[:50]), self.assertRaises(ValueError): lint_description(bad)

    def test_trigger_scoring_rejects_ties_and_unmatched_requests(self):
        descriptions = {'first': 'Use when reviewing a draft', 'second': 'Use when editing a draft'}
        for request in ('draft', 'zebra'):
            with self.subTest(request=request), self.assertRaises(ValueError): trigger_winner(request, descriptions)

    def test_overlap_flags_identical_descriptions_and_ignores_common_task_words(self):
        self.assertGreaterEqual(description_overlap('Use when saving verified progress', 'Use when saving verified progress'), 0.5)
        self.assertNotIn('task', skill_words('task session evidence'))
        self.assertNotIn('session', skill_words('task session evidence'))

    def test_thinkbeforeact_skill_includes_verification_checklist(self):
        text = (ROOT / "skills/thinkbeforeact/SKILL.md").read_text(encoding="utf-8").lower()
        for phrase in ("verified", "outward", "failure path", "adversarial", "verification gate"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_repository_skills_have_discoverable_string_metadata(self):
        paths = sorted((ROOT / "skills").glob("*/SKILL.md"))
        self.assertEqual({p.parent.name for p in paths},
                         {"handoff", "lesson", "pickup", "thinkbeforeact"})
        names = []
        for path in paths:
            with self.subTest(skill=path.parent.name):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"))
                self.assertIn("\n---\n", text)
                meta = core.parse_meta(text)
                self.assertEqual(meta.get("name"), path.parent.name)
                self.assertRegex(meta["name"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                self.assertLessEqual(len(meta["name"]), 64)
                self.assertRegex(meta.get("description", ""), r"[A-Za-z].+\s.+")
                self.assertNotIn("internal: true", text.split("---", 2)[1])
                names.append(meta["name"])
        self.assertEqual(len(names), len(set(names)))

    def test_installed_skills_declare_runtime_prerequisites(self):
        for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
            with self.subTest(skill=path.parent.name):
                meta = core.parse_meta(path.read_text(encoding="utf-8"))
                compatibility = meta.get("compatibility", "")
                self.assertIn("ws on PATH", compatibility)
                self.assertIn("ws start", compatibility)

    def test_handoff_skill_records_environment_and_evidence_checklist(self):
        text = (ROOT / "skills/handoff/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("git status -sb", text)
        self.assertIn("unpushed commits", text)
        self.assertRegex(text, r"(?i)branch.*(?:pr|pull request|ci)")
        self.assertRegex(text, r"(?i)running processes|dev servers|tmux")
        self.assertRegex(text, r"(?i)attach|inspection")
        self.assertRegex(text, r"(?i)checks run")
        self.assertRegex(text, r"(?i)risks")

    def test_pickup_skill_checks_for_environment_drift_before_continuing(self):
        text = (ROOT / "skills/pickup/SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?i)drift")
        self.assertRegex(text, r"(?i)branch")
        self.assertRegex(text, r"(?i)uncommitted")
        self.assertRegex(text, r"(?i)failing checks")
        self.assertRegex(text, r"(?i)flag")
