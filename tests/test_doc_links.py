"""Relative Markdown links in the public docs must point to an existing file and heading."""
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
# [text](target "title"): the target may hold one level of balanced parentheses or be wrapped in <...>.
LINK = re.compile(r'\[[^\]]*\]\(\s*(<[^>]*>|(?:[^()\s]|\([^()\s]*\))*)(?:\s+(?:"[^"]*"|\'[^\']*\'))?\s*\)')
FENCE = re.compile(r'^\s*(`{3,}|~{3,})(.*)$')
REFDEF = re.compile(r'^ {0,3}\[([^\]]+)\]:\s*<?([^\s>]+)')
REFUSE = re.compile(r'\[([^\]]+)\]\[([^\]]*)\]')
HEADING = re.compile(r'^ {0,3}#{1,6}\s+(.*?)\s*#*\s*$')
# 'file:line: target' entries that are known-broken and intentionally skipped, each with a reason.
ALLOWLIST = {}


def doc_files():
    files = [ROOT / n for n in ('README.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'llms.txt', 'llms-full.txt', 'bench/README.md')]
    files += sorted((ROOT / 'docs').rglob('*.md'))
    files += sorted(ROOT.glob('packs/*/AGENTS.snippet.md'))
    files += sorted(ROOT.glob('skills/**/SKILL.md'))
    return [f for f in files if f.exists()]


def lines_outside_fences(path):
    fence = None  # (marker char, length) of the open fence; only a same-char, no-shorter marker closes it
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        match = FENCE.match(line)
        if fence is None and match and not (match.group(1)[0] == '`' and '`' in match.group(2)):
            fence = (match.group(1)[0], len(match.group(1)))
        elif fence is not None:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1] and not match.group(2).strip():
                fence = None
        else:
            yield number, line


def slug(text):
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)  # a link in a heading contributes its text only
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


def link_targets(path):
    """(line, target) for inline links and reference definitions, plus (line, None, ref) for an undefined reference."""
    lines = list(lines_outside_fences(path))
    defined = {m.group(1).lower() for _, line in lines for m in [REFDEF.match(line)] if m}
    for number, line in lines:
        definition = REFDEF.match(line)
        if definition:
            yield number, definition.group(2)
            continue
        clean = re.sub(r'`[^`]*`', '', line)
        for target in LINK.findall(clean):
            yield number, target[1:-1] if target[:1] == '<' else target
        for text, ref in REFUSE.findall(clean):
            if (ref or text).lower() not in defined:
                yield number, None, ref or text


def file_problems(path, rel):
    problems = []
    for item in link_targets(path):
        number, target = item[:2]
        if target is None:
            problems.append(f'{rel}:{number}: [{item[2]}] has no definition')
            continue
        if re.match(r'^[a-z][a-z0-9+.-]*:', target) or any(x in target for x in ('<', '{{', ' ')) or not target:
            continue
        name, _, anchor = target.partition('#')
        dest = path if not name else (path.parent / unquote(name)).resolve()
        entry = f'{rel}:{number}: {target}'
        ok = dest.exists() and (not anchor or dest.suffix != '.md' or unquote(anchor).lower() in anchors(dest))
        if not ok and entry not in ALLOWLIST:
            problems.append(entry)
    return problems


def broken_links():
    return [p for path in doc_files() for p in file_problems(path, path.relative_to(ROOT).as_posix())]


class DocLinkTests(unittest.TestCase):
    def test_relative_links_and_anchors_resolve(self):
        self.assertEqual(broken_links(), [], 'broken doc links (file:line: target)')

    def test_slug_matches_github(self):
        self.assertEqual(slug('Hello, World! v1.2 `x`'), 'hello-world-v12-x')
        self.assertEqual(slug('[Install](setup.md)'), 'install')

    def problems(self, text, **extra):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            (tmp / 'a.md').write_text(text, encoding='utf-8')
            for name, body in extra.items():
                (tmp / name).write_text(body, encoding='utf-8')
            _anchors.clear()
            return file_problems(tmp / 'a.md', 'a.md')

    def test_reference_links_are_checked(self):
        self.assertEqual(self.problems('[guide][setup]\n\n[setup]: missing.md\n'), ['a.md:3: missing.md'])
        self.assertEqual(self.problems('[guide][nope]\n'), ['a.md:1: [nope] has no definition'])
        self.assertEqual(self.problems('[guide][setup]\n[Setup][]\n\n[setup]: b.md\n', **{'b.md': 'x'}), [])

    def test_inline_link_targets_with_parentheses_and_titles(self):
        self.assertEqual(self.problems('[x](b_(1).md) [y](b_(1).md "Title")\n', **{'b_(1).md': 'x'}), [])
        self.assertEqual(self.problems('[x](missing.md "Title") [y](gone.md \'T\')\n'), ['a.md:1: missing.md', 'a.md:1: gone.md'])

    def test_fence_closes_only_with_matching_marker(self):
        text = '```\n~~~\n```\n[x](missing.md)\n'
        self.assertEqual(self.problems(text), ['a.md:4: missing.md'])
        self.assertEqual(self.problems('~~~~\n```\n[x](missing.md)\n~~~~\n'), [])

    def test_heading_with_link_gets_text_anchor(self):
        self.assertEqual(self.problems('## [Install](b.md)\n\n[go](#install)\n', **{'b.md': 'x'}), [])


if __name__ == '__main__':
    unittest.main()
