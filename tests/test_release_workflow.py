import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='release-workflow-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'gh.log'
        self.notes = self.root / 'notes.md'
        self.notes.write_text('release notes')
        fake = self.bin / 'gh'
        fake.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$GH_LOG"
if [ "$1 $2" = "release view" ]; then exit "$GH_VIEW_STATUS"; fi
if [ "$1 $2" = "release create" ]; then exit 0; fi
exit 2
''')
        fake.chmod(0o755)

    def publish(self, view_status):
        env = {**os.environ, 'GH_LOG': str(self.log), 'GH_VIEW_STATUS': str(view_status),
               'PATH': f"{self.bin}:{os.environ.get('PATH', '')}"}
        return subprocess.run([ROOT / 'bin' / 'publish-release', 'v0.1.0-beta.3', str(self.notes)],
                              env=env, text=True, capture_output=True)

    def test_existing_release_skips_create(self):
        result = self.publish(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('already exists', result.stdout)
        self.assertEqual(self.log.read_text().splitlines(), ['release view v0.1.0-beta.3'])

    def test_missing_release_is_created(self):
        result = self.publish(1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines(), [
            'release view v0.1.0-beta.3',
            f'release create v0.1.0-beta.3 --title v0.1.0-beta.3 --notes-file {self.notes}',
        ])

    def test_workflow_uses_tested_publisher(self):
        workflow = (ROOT / '.github/workflows/release.yml').read_text()
        self.assertIn('bin/publish-release "$GITHUB_REF_NAME" notes.md', workflow)


if __name__ == '__main__':
    unittest.main()
