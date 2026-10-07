import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConceptsTests(unittest.TestCase):
    def test_examples_run_in_a_throwaway_workspace(self):
        page = ROOT / 'docs/CONCEPTS.md'
        text = page.read_text()
        for concept in ('workspace', 'task record', 'claim', 'checkpoint', 'brief',
                        'capture', 'lessons', 'routing', 'delegate', 'assist', 'packs'):
            self.assertIn(concept, text.lower())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, fixture, workspace, fake_bin = (root / name for name in ('home', 'fixture', 'workspace', 'bin'))
            home.mkdir(); fixture.mkdir(); fake_bin.mkdir()
            (fixture / 'README.md').write_text('Synthetic concepts fixture.\n')
            (fake_bin / 'codex').write_text('#!/bin/sh\nexit 97\n')
            (fake_bin / 'codex').chmod(0o755)
            env = dict(os.environ, HOME=str(home), USER='demo', WS_ROOT=str(workspace),
                       PATH=str(fake_bin) + os.pathsep + os.environ['PATH'])

            def run(*args):
                result = subprocess.run([sys.executable, str(ROOT / 'bin/ws'), *args], env=env,
                                         cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout

            run('init', str(workspace), '--name', 'concepts', '--repo', str(fixture))
            run('connect', 'claude')
            run('task', 'new', 'DEMO-2', 'Make a sample change', '--objective', 'Test each concept.')
            run('claim', 'DEMO-2')
            run('checkpoint', 'DEMO-2', '--status', 'in_progress', '--next', 'Review the fixture.')
            run('brief')
            run('lesson', 'add', 'Preserve user data.', '--tag', 'demo')
            self.assertIn('available', run('route', 'explorer'))
            run('delegate', 'DEMO-2', '--role', 'explorer')
            run('assist')
            run('packs')


if __name__ == '__main__':
    unittest.main()
