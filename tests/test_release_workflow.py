import os
import shutil
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
if [ "$1 $2" = "release view" ]; then
  n=$(grep -c '^release view ' "$GH_LOG")
  status=$GH_VIEW_STATUS
  [ "$n" -eq 1 ] || status=$GH_VIEW_RECHECK_STATUS
  case "$status" in
    0) exit 0 ;;
    1) echo 'HTTP 404: Not Found' >&2; exit 1 ;;
    2) echo 'HTTP 502: Bad Gateway' >&2; exit 1 ;;
  esac
fi
if [ "$1 $2" = "release edit" ]; then
  exit 0
fi
if [ "$1 $2" = "release create" ]; then
  [ "$GH_CREATE_STATUS" -eq 0 ] || { echo 'HTTP 422: Release.tag_name already exists' >&2; exit "$GH_CREATE_STATUS"; }
  exit 0
fi
exit 2
''')
        fake.chmod(0o755)

    def publish(self, view_status, recheck_status=1, create_status=0):
        env = {**os.environ, 'GH_LOG': str(self.log), 'GH_VIEW_STATUS': str(view_status),
               'GH_VIEW_RECHECK_STATUS': str(recheck_status), 'GH_CREATE_STATUS': str(create_status),
               'PATH': os.pathsep.join((str(self.bin), os.environ.get('PATH', '')))}
        bash = shutil.which('bash')
        if not bash:
            self.skipTest('bash is required to exercise the release publisher')
        return subprocess.run([bash, str(ROOT / 'bin' / 'publish-release'), 'v0.1.0-beta.3', str(self.notes)],
                              env=env, text=True, capture_output=True)

    def test_existing_release_updates_notes_and_latest_state(self):
        result = self.publish(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('already exists; updated notes', result.stdout)
        self.assertEqual(self.log.read_text().splitlines(), [
            'release view v0.1.0-beta.3',
            f'release edit v0.1.0-beta.3 --notes-file {self.notes} --prerelease=false --latest',
        ])

    def test_missing_release_is_created(self):
        result = self.publish(1, create_status=0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines(), [
            'release view v0.1.0-beta.3',
            f'release create v0.1.0-beta.3 --title v0.1.0-beta.3 --notes-file {self.notes} --latest',
        ])

    def test_view_api_error_does_not_attempt_create(self):
        result = self.publish(2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('HTTP 502: Bad Gateway', result.stderr)
        self.assertEqual(self.log.read_text().splitlines(), ['release view v0.1.0-beta.3'])

    def test_concurrent_release_creation_is_success(self):
        result = self.publish(1, recheck_status=0, create_status=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('appeared during creation', result.stdout)
        self.assertEqual(self.log.read_text().splitlines(), [
            'release view v0.1.0-beta.3',
            f'release create v0.1.0-beta.3 --title v0.1.0-beta.3 --notes-file {self.notes} --latest',
            'release view v0.1.0-beta.3',
            f'release edit v0.1.0-beta.3 --notes-file {self.notes} --prerelease=false --latest',
        ])

    def test_create_failure_without_concurrent_release_is_reported(self):
        result = self.publish(1, recheck_status=1, create_status=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('HTTP 422: Release.tag_name already exists', result.stderr)
        self.assertEqual(self.log.read_text().splitlines(), [
            'release view v0.1.0-beta.3',
            f'release create v0.1.0-beta.3 --title v0.1.0-beta.3 --notes-file {self.notes} --latest',
            'release view v0.1.0-beta.3',
        ])

    def test_workflow_uses_tested_publisher(self):
        workflow = (ROOT / '.github/workflows/release.yml').read_text()
        self.assertIn('bin/publish-release "$GITHUB_REF_NAME" notes.md', workflow)
        self.assertIn('### Upgrade', workflow)


if __name__ == '__main__':
    unittest.main()
