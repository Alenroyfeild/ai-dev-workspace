import json
import importlib.util
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from zipfile import ZipFile

from ws import cli, packaging


ROOT = Path(__file__).resolve().parents[1]
HAS_BUILD_TOOLS = all(importlib.util.find_spec(name) for name in ('setuptools', 'wheel'))


class PackagingTests(unittest.TestCase):
    def test_beta_kit_version_is_published_as_pep440(self):
        version = json.loads((ROOT / 'kit.json').read_text())['version']
        self.assertEqual(packaging.package_version(version), '0.1.0b5')

    def test_cli_prints_kit_version_without_a_command(self):
        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as exit_info:
            cli.main(['--version'])
        self.assertEqual(exit_info.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), 'ws 0.1.0-beta.5')

    def _check_plugin_versions(self, root):
        kit_version = json.loads((root / 'kit.json').read_text(encoding='utf-8'))['version']
        manifests = (
            '.claude-plugin/plugin.json',
            '.codex-plugin/plugin.json',
            '.cursor-plugin/plugin.json',
        )
        marketplaces = (
            '.claude-plugin/marketplace.json',
            '.cursor-plugin/marketplace.json',
        )
        for rel in manifests:
            data = json.loads((root / rel).read_text(encoding='utf-8'))
            self.assertEqual(data.get('version'), kit_version, f'{rel} version mismatch')
        for rel in marketplaces:
            data = json.loads((root / rel).read_text(encoding='utf-8'))
            self.assertEqual(data['plugins'][0].get('version'), kit_version, f'{rel} version mismatch')

    def test_plugin_manifest_and_marketplace_versions_equal_kit_json(self):
        self._check_plugin_versions(ROOT)

    def test_plugin_version_parity_fails_if_any_file_differs(self):
        kit_version = json.loads((ROOT / 'kit.json').read_text(encoding='utf-8'))['version']
        all_targets = [
            ('.claude-plugin/plugin.json', False),
            ('.codex-plugin/plugin.json', False),
            ('.cursor-plugin/plugin.json', False),
            ('.claude-plugin/marketplace.json', True),
            ('.cursor-plugin/marketplace.json', True),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            (tmp_root / 'kit.json').write_text(json.dumps({'version': kit_version}), encoding='utf-8')
            for rel, is_market in all_targets:
                target_path = tmp_root / rel
                target_path.parent.mkdir(parents=True, exist_ok=True)
                content = {'plugins': [{'version': kit_version}]} if is_market else {'version': kit_version}
                target_path.write_text(json.dumps(content), encoding='utf-8')

            for rel, is_market in all_targets:
                with self.subTest(differing=rel):
                    target_path = tmp_root / rel
                    mismatched = {'plugins': [{'version': '0.0.0-mismatch'}]} if is_market else {'version': '0.0.0-mismatch'}
                    target_path.write_text(json.dumps(mismatched), encoding='utf-8')

                    with self.assertRaises(AssertionError):
                        self._check_plugin_versions(tmp_root)

                    restored = {'plugins': [{'version': kit_version}]} if is_market else {'version': kit_version}
                    target_path.write_text(json.dumps(restored), encoding='utf-8')

    @unittest.skipUnless(HAS_BUILD_TOOLS, 'setuptools and wheel are needed for artifact builds')
    def test_pip_builds_a_wheel_from_the_sdist(self):
        # pip and pipx build source installs through PEP 517, where the source folder is not importable by default.
        with tempfile.TemporaryDirectory() as temp:
            subprocess.run([sys.executable, 'setup.py', 'sdist', '--dist-dir', temp], cwd=ROOT, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            source = next(Path(temp).glob('*.tar.gz'))
            built = subprocess.run([sys.executable, '-m', 'pip', 'wheel', str(source), '--no-deps', '--no-build-isolation',
                                    '-w', temp], cwd=temp, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stdout[-2000:] + built.stderr[-2000:])
            self.assertTrue(list(Path(temp).glob('*.whl')))

    @unittest.skipUnless(HAS_BUILD_TOOLS, 'setuptools and wheel are needed for artifact builds')
    def test_sdist_and_wheel_include_pep440_metadata_and_runtime_files(self):
        with tempfile.TemporaryDirectory() as temp:
            dist = Path(temp)
            subprocess.run(
                [sys.executable, 'setup.py', 'sdist', '--dist-dir', temp,
                 'bdist_wheel', '--dist-dir', temp],
                cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            wheel = next(dist.glob('*.whl'))
            source = next(dist.glob('*.tar.gz'))
            with ZipFile(wheel) as archive:
                names = archive.namelist()
                self.assertFalse(any('/build/' in '/' + name for name in names), 'video build artifacts in wheel')
                metadata = archive.read(next(name for name in names if name.endswith('.dist-info/METADATA'))).decode()
                self.assertIn('Version: 0.1.0b5\n', metadata)
                self.assertNotIn('](docs/', metadata)  # relative README links break on the PyPI page
                self.assertIn('](https://github.com/Alenroyfeild/ai-dev-workspace/blob/main/docs/', metadata)
                self.assertIn('Project-URL: Changelog, ', metadata)
                self.assertIn('Classifier: Programming Language :: Python :: 3.12', metadata)
                self.assertIn('ws/cli.py', names)
                self.assertIn('ws/template/AGENTS.md', names)
            with tarfile.open(source, 'r:gz') as archive:
                self.assertFalse(any('/build/' in item.name for item in archive.getmembers()),
                                 'video build artifacts in sdist')
                metadata = next(item for item in archive.getmembers() if item.name.endswith('/PKG-INFO'))
                body = archive.extractfile(metadata).read().decode()
                self.assertIn('Version: 0.1.0b5\n', body)
                self.assertTrue(any(item.name.endswith('/ws/cli.py') for item in archive.getmembers()))


if __name__ == '__main__':
    unittest.main()
