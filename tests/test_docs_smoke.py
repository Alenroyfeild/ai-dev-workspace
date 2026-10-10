import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
from ws import core


def code_block(path, heading):
    lines = path.read_text(encoding='utf-8').splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(heading))
    opening = next(i for i in range(start + 1, len(lines)) if lines[i].startswith('```'))
    closing = next(i for i in range(opening + 1, len(lines)) if lines[i].startswith('```'))
    return '\n'.join(lines[opening + 1:closing]) + '\n'


@unittest.skipIf(os.name == 'nt', 'The documented quick-start shell blocks use POSIX syntax.')
class DocsSmokeTests(unittest.TestCase):
    def test_quick_start_blocks_run_in_throwaway_workspaces(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); home = base / 'home'; fakebin = base / 'bin'
            home.mkdir(); fakebin.mkdir()
            (home / 'code').mkdir()
            (home / 'code/myapp').mkdir()
            ws = fakebin / 'ws'; ws.symlink_to(KIT / 'bin/ws')
            pipx = fakebin / 'pipx'
            pipx.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$PIPX_LOG"\n')
            pipx.chmod(0o755)
            git = fakebin / 'git'
            git.write_text(f'''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
if args[:1] == ['clone'] and args[1].startswith('https://github.com/Alenroyfeild/ai-dev-workspace'):
    args[1] = os.environ['WS_KIT_SOURCE']
os.execv({shutil.which('git')!r}, [{shutil.which('git')!r}, *args])
''')
            git.chmod(0o755)
            env = dict(os.environ, HOME=str(home), USER='synthetic', PATH=str(fakebin) + os.pathsep + os.environ['PATH'],
                       PIPX_LOG=str(base / 'pipx.log'), WS_KIT_SOURCE=str(KIT),
                       GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=str(base / 'gitconfig'),
                       GIT_AUTHOR_NAME='Synthetic', GIT_AUTHOR_EMAIL='synthetic@example.invalid',
                       GIT_COMMITTER_NAME='Synthetic', GIT_COMMITTER_EMAIL='synthetic@example.invalid')
            commands = (
                (KIT / 'README.md', '## Quick start', base),
                (KIT / 'docs/SETUP.md', '## 1. Install the kit', base),
                (KIT / 'docs/SETUP.md', '## 2. Create a workspace', base),
            )
            for document, heading, cwd in commands:
                result = subprocess.run(['/bin/bash', '-e', '-c', code_block(document, heading)], cwd=cwd,
                                        env=env, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, f'{document.name} {heading}: {result.stderr}')
            self.assertTrue((base / 'pipx.log').is_file())  # fake pipx records the documented install; no install runs
            workspace = base / 'my-workspace'
            core.init(workspace, 'team-smoke')
            core.task_new(workspace, 'T-1', 'Synthetic task')
            remote = base / 'team.git'
            subprocess.run([shutil.which('git'), 'init', '--bare', str(remote)], check=True, capture_output=True)
            env['WORKSPACE_REMOTE'] = str(remote)
            result = subprocess.run(['/bin/bash', '-e', '-c', code_block(KIT / 'docs/TEAM.md', '## Set up')],
                                    cwd=base, env=env, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, f'TEAM.md setup: {result.stderr}')
            claim = re.search(r'`(ws claim[^`]+)`', (KIT / 'docs/TEAM.md').read_text(encoding='utf-8'))
            self.assertIsNotNone(claim)
            result = subprocess.run(['/bin/bash', '-e', '-c', claim[1]], cwd=workspace, env=env,
                                    text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, f'TEAM.md claim: {result.stderr}')

    def test_checkpoint_help_and_errors_list_valid_note_sections(self):
        expected = ', '.join(core.REQUIRED + ('Findings', 'Failures', 'Risks', 'Do not redo'))
        help_result = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'checkpoint', '--help'],
                                     cwd=KIT, text=True, capture_output=True)
        self.assertEqual(help_result.returncode, 0)
        self.assertIn(expected, ' '.join(help_result.stdout.split()))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'w'; core.init(root, 'smoke'); core.task_new(root, 'T-1', 'Synthetic')
            bad = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'checkpoint', 'T-1', '--status', 'in_progress',
                                  '--next', 'Inspect the fixture', '--note', 'Nope=x'], cwd=root, text=True, capture_output=True)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn('Valid note sections: ' + expected, bad.stderr)
