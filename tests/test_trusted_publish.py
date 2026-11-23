import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tarfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/pypi-publish.yml'
VERIFY = ROOT / 'bin/verify-publish-tag'


class TrustedPublishWorkflowTests(unittest.TestCase):
    def workflow(self):
        self.assertTrue(WORKFLOW.is_file(), 'workflow missing')
        return WORKFLOW.read_text(encoding='utf-8')

    def test_manual_only_tag_input_and_no_secret_tokens(self):
        text = self.workflow()
        self.assertRegex(text, r'(?m)^\s*workflow_dispatch:\s*$')
        self.assertRegex(text, r'(?m)^\s*tag:\s*$')
        trigger = text.split('\npermissions:', 1)[0]
        self.assertRegex(trigger, r'(?m)^on:\s*\n  workflow_dispatch:\s*$')
        self.assertNotRegex(trigger, r'(?i)\bpush\b')
        self.assertNotRegex(text, r'(?i)\bsecrets\s*[.\[]')
        self.assertNotRegex(text, r'(?im)^\s*(username|password)\s*:')

    def test_oidc_protected_environment_and_pinned_publish_action(self):
        text = self.workflow()
        self.assertRegex(text, r'(?m)^\s*id-token:\s*write\s*$')
        self.assertRegex(text, r'(?m)^\s*contents:\s*read\s*$')
        self.assertRegex(text, r'(?m)^\s*(?:name:\s*)?pypi\s*$|^\s*environment:\s*pypi\s*$')
        self.assertRegex(text, r'(?m)^\s*(?:-\s*)?uses:\s*pypa/gh-action-pypi-publish@[0-9a-f]{40}(?:\s|$)')
        self.assertIn('git archive', text)
        self.assertIn('bin/verify-publish-tag', text)
        self.assertIn('python -m build --no-isolation', text)
        build = text.split('  build:', 1)[1].split('  publish:', 1)[0]
        publish = text.split('  publish:', 1)[1]
        self.assertIn("if: github.ref == 'refs/heads/main'", build)
        self.assertNotIn('id-token:', build)
        self.assertIn('id-token: write', publish)
        self.assertLess(build.index('bin/verify-publish-tag'), build.index('python -m build --no-isolation'))
        self.assertIn('bin/normalize-sdist', build)
        for action in re.findall(r'(?m)^\s*(?:-\s*)?uses:\s*([^\s#]+)', text):
            self.assertRegex(action, r'@[0-9a-f]{40}$')


class MainAncestryTests(unittest.TestCase):
    def test_workflow_guards_ancestry_before_archive(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        guard = 'git merge-base --is-ancestor "$commit" origin/main'
        self.assertIn(guard, text)
        self.assertLess(text.index('commit=$(git rev-parse'), text.index(guard))
        self.assertLess(text.index(guard), text.index('git archive'))
        line = next(line for line in text.splitlines() if guard in line)
        self.assertIn('exit 1', line)

    @unittest.skipUnless(shutil.which('git') and shutil.which('bash'), 'git and bash required')
    def test_workflow_guard_rejects_off_main_commit(self):
        text = WORKFLOW.read_text(encoding='utf-8')
        guard = next((line.strip() for line in text.splitlines()
                      if 'git merge-base --is-ancestor "$commit" origin/main' in line), None)
        self.assertIsNotNone(guard, 'workflow ancestry guard missing')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            env = dict(os.environ, HOME=d, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
            def git(*args):
                result = subprocess.run(['git', *args], cwd=root, env=env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout.strip()
            git('init', '-q')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-qm', 'main')
            main = git('rev-parse', 'HEAD')
            git('update-ref', 'refs/remotes/origin/main', main)
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty', '-qm', 'off-main')
            other = git('rev-parse', 'HEAD')
            for commit, accepted in ((main, True), (other, False), ('0' * 40, False)):
                with self.subTest(commit=commit):
                    result = subprocess.run([shutil.which('bash'), '-c', guard], cwd=root,
                                            env=dict(env, commit=commit), text=True, capture_output=True)
                    self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)


class EmergencyFallbackTests(unittest.TestCase):
    def test_manual_upload_is_emergency_only_and_token_is_not_stored(self):
        doc = (ROOT / 'docs/MAINTAINING.md').read_text(encoding='utf-8')
        section = doc.split('6. **PyPI publication:**', 1)[1].split('7. **MCP registry publication:**', 1)[0]
        self.assertLess(section.index('gh workflow run pypi-publish.yml'), section.index('Emergency-only fallback'))
        self.assertIn('project-scoped token', section)
        self.assertIn('typed into the terminal', section)
        self.assertIn('never stored', section)
        self.assertIn('revoke', section.lower())
        self.assertIn('twine upload', section)
        self.assertIn('--config-file /dev/null', section)


class TagValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'kit.json').write_text(json.dumps({'version': '0.2.0'}))
        (self.root / 'CHANGELOG.md').write_text('# Changelog\n\n## 0.2.0 (2026-11-20)\n')

    def validate(self, tag):
        return subprocess.run([sys.executable, str(VERIFY), tag, str(self.root)], text=True,
                              capture_output=True, env={**os.environ, 'WS_OFFLINE': '1'})

    def test_matching_release_and_beta_are_accepted(self):
        r = self.validate('v0.2.0')
        self.assertEqual(r.returncode, 0, r.stderr)
        (self.root / 'kit.json').write_text(json.dumps({'version': '0.1.0-beta.7'}))
        (self.root / 'CHANGELOG.md').write_text('## 0.1.0-beta.7 (2026-11-04)\n')
        r = self.validate('v0.1.0-beta.7')
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_mismatched_kit_or_changelog_refused(self):
        for tag in ('v0.1.0', '0.2.0', 'v0.2.0;echo bad', 'v0.2.0/../../other'):
            with self.subTest(tag=tag):
                self.assertNotEqual(self.validate(tag).returncode, 0)
        for content in ('## 0.2.01 (2026-11-20)\n', '## 0.2.0 (Unreleased)\n', '## 0.2.0 (2026-02-30)\n', '## 0.1.0 (2026-11-20)\n'):
            with self.subTest(changelog=content):
                (self.root / 'CHANGELOG.md').write_text(content)
                self.assertNotEqual(self.validate('v0.2.0').returncode, 0)

    def test_missing_or_invalid_metadata_refused(self):
        for invalid in ('not json', '{}', '{"version": null}'):
            with self.subTest(kit=invalid):
                (self.root / 'kit.json').write_text(invalid)
                self.assertNotEqual(self.validate('v0.2.0').returncode, 0)
        (self.root / 'kit.json').unlink()
        self.assertNotEqual(self.validate('v0.2.0').returncode, 0)


class ReproducibleSdistTests(unittest.TestCase):
    def test_archive_metadata_does_not_change_hash_or_contents(self):
        with tempfile.TemporaryDirectory() as d:
            outputs = []
            for index in range(2):
                archive = Path(d) / ('build%d.tar.gz' % index)
                with gzip.GzipFile(filename=str(archive), mode='wb', mtime=index + 1) as zipped:
                    with tarfile.open(fileobj=zipped, mode='w') as tar:
                        for name in (('pkg/a', 'pkg/b') if index == 0 else ('pkg/b', 'pkg/a')):
                            data = name.encode()
                            info = tarfile.TarInfo(name)
                            info.size = len(data); info.mtime = index + 123; info.uid = index + 22
                            tar.addfile(info, io.BytesIO(data))
                result = subprocess.run([sys.executable, str(ROOT / 'bin/normalize-sdist'), str(archive), '1700000000'],
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs.append(hashlib.sha256(archive.read_bytes()).hexdigest())
                with tarfile.open(archive, 'r:gz') as tar:
                    self.assertEqual(tar.extractfile('pkg/a').read(), b'pkg/a')
                    self.assertEqual(tar.extractfile('pkg/b').read(), b'pkg/b')
            self.assertEqual(outputs[0], outputs[1])
