"""Relative Markdown links in the public docs must point to an existing file and heading."""
import re
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'\[[^\]]*\]\(([^)]*)\)')
FENCE = re.compile(r'^\s*(```|~~~)')
HEADING = re.compile(r'^ {0,3}#{1,6}\s+(.*?)\s*#*\s*$')
# 'file:line: target' entries that are known-broken and intentionally skipped, each with a reason.
ALLOWLIST = {}


def doc_files():
    files = [ROOT / n for n in ('README.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'llms.txt', 'bench/README.md')]
    files += sorted((ROOT / 'docs').rglob('*.md'))
    files += sorted(ROOT.glob('packs/*/AGENTS.snippet.md'))
    files += sorted(ROOT.glob('skills/**/SKILL.md'))
    return [f for f in files if f.exists()]


def lines_outside_fences(path):
    fenced = False
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            yield number, line


def slug(text):
    text = re.sub(r'[^\w\- ]', '', text.lower())
    return text.replace(' ', '-')


_anchors = {}


def anchors(path):
    if path not in _anchors:
        seen, found = {}, set()
        for _, line in lines_outside_fences(path):
            match = HEADING.match(line)
            if match:
                base = slug(match.group(1))
                count = seen.get(base, 0)
                seen[base] = count + 1
                found.add(base if count == 0 else f'{base}-{count}')
        _anchors[path] = found
    return _anchors[path]


def broken_links():
    broken = []
    for path in doc_files():
        rel = path.relative_to(ROOT).as_posix()
        for number, line in lines_outside_fences(path):
            for target in LINK.findall(re.sub(r'`[^`]*`', '', line)):
                if re.match(r'^[a-z][a-z0-9+.-]*:', target) or any(x in target for x in ('<', '{{', ' ')) or not target:
                    continue
                name, _, anchor = target.partition('#')
                dest = path if not name else (path.parent / unquote(name)).resolve()
                entry = f'{rel}:{number}: {target}'
                ok = dest.exists() and (not anchor or dest.suffix != '.md' or unquote(anchor).lower() in anchors(dest))
                if not ok and entry not in ALLOWLIST:
                    broken.append(entry)
    return broken


class DocLinkTests(unittest.TestCase):
    def test_relative_links_and_anchors_resolve(self):
        self.assertEqual(broken_links(), [], 'broken doc links (file:line: target)')

    def test_slug_matches_github(self):
        self.assertEqual(slug('Hello, World! v1.2 `x`'), 'hello-world-v12-x')


if __name__ == '__main__':
    unittest.main()
