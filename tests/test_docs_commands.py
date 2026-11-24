import re
import subprocess
import sys
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]


def parser_commands():
    """Top-level command names from `ws help all` (indented four spaces under Commands)."""
    out = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'help', 'all'], capture_output=True, text=True, check=True).stdout
    return re.findall(r'^    ([a-z][a-z-]*)(?:\s{2,}|$)', out.split('\nCommands:')[1], re.M)


def documented(docs, name):
    return re.search(r'`ws ' + re.escape(name) + r'(?=[\s`\[<"])', docs) is not None


def core_command_paths(text):
    """Count command paths outside explicitly Experimental Markdown sections."""
    kept, experimental_level, fenced = [], None, False
    tick = chr(96)
    for line in text.splitlines():
        if line.startswith(tick * 3):
            fenced = not fenced
            continue
        heading = re.match(r'^(#{1,6})\s+(.+)', line) if not fenced else None
        if heading:
            level, title = len(heading[1]), heading[2]
            if experimental_level is not None and level <= experimental_level:
                experimental_level = None
            if re.search(r'\bExperimental\b', title, re.I):
                experimental_level = min(experimental_level or level, level)
        if experimental_level is None:
            kept.extend([line] if fenced else re.findall(tick + '([^' + tick + ']+)' + tick, line))
    commands = set()
    groups = {'task', 'lesson', 'know', 'sessions', 'import', 'team', 'pack', 'worker', 'run', 'help', 'feedback'}
    code = '\n'.join(kept)
    for match in re.finditer(r'\bws[ \t]+([a-z][a-z-]*)(?:[ \t]+([a-z][a-z-]*))?(?:[ \t]+([a-z][a-z-]*))?', code):
        path = ['ws', match[1]]
        if match[1] in groups and match[2]:
            path.append(match[2])
            if match[1] == 'run' and match[2] == 'import' and match[3]:
                path.append(match[3])
        commands.add(' '.join(path))
    return commands


class CommandsDocTests(unittest.TestCase):
    def test_readme_and_reference_expose_at_most_ten_core_command_paths(self):
        union = set()
        for name in ('README.md', 'docs/COMMANDS.md'):
            paths = core_command_paths((KIT / name).read_text(encoding='utf-8'))
            with self.subTest(file=name):
                self.assertLessEqual(len(paths), 10, sorted(paths))
            union.update(paths)
        self.assertLessEqual(len(union), 10, sorted(union))

    def test_command_count_tracks_subcommands_flags_and_section_boundaries(self):
        tick = chr(96)
        text = ('## Core\nws task find branch\nws start --yes\nws start --undo\n'
                '## Experimental\nws task import input\n### Details\nws team sync\n'
                '## Other\nws lesson add "text"\n')
        text = '\n'.join(tick + line + tick if line.startswith('ws ') else line for line in text.splitlines())
        text = text.replace('## Experimental', tick * 3 + 'sh\nws brief\n' + tick * 3 + '\n## Experimental')
        self.assertEqual(core_command_paths(text), {'ws task find', 'ws start', 'ws brief', 'ws lesson add'})

    def test_every_top_level_command_is_in_commands_md(self):
        docs = (KIT / 'docs/COMMANDS.md').read_text(encoding='utf-8')
        names = parser_commands()
        self.assertGreater(len(names), 30, names)
        self.assertEqual([n for n in names if not documented(docs, n)], [], 'add these commands to docs/COMMANDS.md')

    def test_check_catches_a_missing_name(self):
        self.assertFalse(documented('`ws status` and `ws start --yes`', 'nudge'))
        self.assertTrue(documented('| `ws nudge` | x |', 'nudge'))


if __name__ == '__main__':
    unittest.main()
