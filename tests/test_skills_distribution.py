import unittest
from pathlib import Path

from ws import core


ROOT = Path(__file__).resolve().parents[1]


class SkillDistributionTests(unittest.TestCase):
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
