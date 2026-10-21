import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fragment_errors(directory):
    errors = []
    for path in sorted(directory.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            errors.append(path.name)
            continue
        lines = text.splitlines()
        if (len(lines) != 1
                or not re.fullmatch(r"(Fixed|Added|Changed): \S.*", lines[0])):
            errors.append(path.name)
    return errors


class ChangelogFragmentTests(unittest.TestCase):
    def test_repository_fragments(self):
        directory = ROOT / "changelog.d"
        self.assertTrue(directory.is_dir(), "changelog.d must exist")
        self.assertEqual(fragment_errors(directory), [])

    def test_accepts_categories_and_ignores_readme(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "README.md").write_text("Format guide\n\nExamples\n", encoding="utf-8")
            for category in ("Fixed", "Added", "Changed"):
                with self.subTest(category=category):
                    (directory / "codex-example.md").write_text(
                        category + ": `ws brief`: résumé is readable.\n", encoding="utf-8")
                    self.assertEqual(fragment_errors(directory), [])

    def test_rejects_empty_multiline_unknown_and_non_utf8_fragments(self):
        invalid = (b"", b"Fixed: \n", b"Fixed:  \n", b"New: text\n",
                   b"- Fixed: text\n", b"Added: text\n\n", b"Changed: one\nFixed: two\n",
                   b"Fixed: \xff\n")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for contents in invalid:
                with self.subTest(contents=contents):
                    (directory / "bad.md").write_bytes(contents)
                    self.assertEqual(fragment_errors(directory), ["bad.md"])
