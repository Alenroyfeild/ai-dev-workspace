import importlib.machinery
import importlib.util
import unittest

ROOT = __import__('pathlib').Path(__file__).resolve().parents[1]
LOADER = importlib.machinery.SourceFileLoader('release_verify', str(ROOT / 'bin/release-verify'))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
verify_script = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(verify_script)


class ReleaseVerifyTests(unittest.TestCase):
    def setUp(self):
        self.version = '0.1.0b7'
        self.pypi = {'info': {'version': self.version}}
        self.release = {'tag_name': 'v0.1.0-beta.7', 'draft': False}
        self.registry = {'server': {'name': 'io.github.Alenroyfeild/ai-dev-workspace',
                                    'version': self.version}}
        self.files = {
            'README.md': 'ai-dev-workspace (v0.1.0-beta.7 on PyPI)\nLive-checked on beta.5 (2026-10-22)',
            'llms.txt': 'published 0.1.0b7\nLive-checked on beta.5 (2026-10-22)',
            'llms-full.txt': 'published 0.1.0b7',
        }
        self.manifests = {
            'kit.json': {'version': '0.1.0-beta.7'},
            'server.json': {'version': self.version,
                            'packages': [{'version': self.version}]},
            '.claude-plugin/plugin.json': {'version': '0.1.0-beta.7'},
            '.claude-plugin/marketplace.json': {'plugins': [{'version': '0.1.0-beta.7'}]},
            '.codex-plugin/plugin.json': {'version': '0.1.0-beta.7'},
            '.cursor-plugin/plugin.json': {'version': '0.1.0-beta.7'},
            '.cursor-plugin/marketplace.json': {'plugins': [{'version': '0.1.0-beta.7'}]},
        }

    def verify(self):
        json_by_url = {
            verify_script.PYPI_URL: self.pypi,
            verify_script.RELEASE_URL: self.release,
            verify_script.REGISTRY_URL: self.registry,
        }
        def fetch_json(url):
            return json_by_url[url]
        def fetch_text(url):
            path = url.rsplit('/', 1)[-1]
            return self.files[path]
        def fetch_manifest(path):
            return self.manifests[path]
        return verify_script.verify(self.version, fetch_json=fetch_json, fetch_text=fetch_text,
                                    fetch_manifest=fetch_manifest, video_check=lambda _: (0, 'videos ready'))

    def test_all_release_surfaces_current_and_plugin_labels_informational(self):
        problems, notices = self.verify()
        self.assertEqual(problems, [])
        self.assertTrue(any('plugin live-check label' in item for item in notices))

    def test_each_external_and_repository_surface_reports_stale(self):
        cases = (
            ('PyPI', lambda: self.pypi['info'].update(version='0.1.0b6')),
            ('GitHub Release', lambda: self.release.update(tag_name='v0.1.0-beta.6')),
            ('MCP Registry', lambda: self.registry['server'].update(version='0.1.0b6')),
            ('README.md', lambda: self.files.update({'README.md': 'old version'})),
            ('llms.txt', lambda: self.files.update({'llms.txt': 'old version'})),
            ('llms-full.txt', lambda: self.files.update({'llms-full.txt': 'old version'})),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                self.setUp()
                mutate()
                problems, _ = self.verify()
                self.assertTrue(any(label in item for item in problems), problems)

    def test_manifest_and_video_failures_are_named(self):
        self.manifests['.cursor-plugin/plugin.json']['version'] = '0.1.0-beta.6'
        self.files['llms-full.txt'] = 'old version'
        json_by_url = {verify_script.PYPI_URL: self.pypi, verify_script.RELEASE_URL: self.release,
                       verify_script.REGISTRY_URL: self.registry}
        problems, _ = verify_script.verify(
            self.version, fetch_json=lambda url: json_by_url[url],
            fetch_text=lambda url: self.files[url.rsplit('/', 1)[-1]],
            fetch_manifest=lambda path: self.manifests[path],
            video_check=lambda _: (1, 'videos.json latest is old'),
        )
        self.assertTrue(any('.cursor-plugin/plugin.json' in item for item in problems), problems)
        self.assertTrue(any('llms-full.txt' in item for item in problems), problems)
        self.assertTrue(any('videos.json' in item for item in problems), problems)

    def test_every_manifest_path_is_checked(self):
        for path in verify_script.MANIFESTS:
            with self.subTest(path=path):
                self.setUp()
                def stale_version(data):
                    if isinstance(data, dict):
                        for key, value in data.items():
                            if key == 'version':
                                data[key] = 'old-version'
                                return True
                            if stale_version(value):
                                return True
                    elif isinstance(data, list):
                        for value in data:
                            if stale_version(value):
                                return True
                    return False
                self.assertTrue(stale_version(self.manifests[path]))
                problems, _ = self.verify()
                self.assertTrue(any(path in item for item in problems), problems)

    def test_unavailable_surface_is_reported_without_stopping_other_checks(self):
        def fetch_json(url):
            if url == verify_script.RELEASE_URL:
                raise OSError('offline')
            return {verify_script.PYPI_URL: self.pypi,
                    verify_script.REGISTRY_URL: self.registry}[url]
        problems, _ = verify_script.verify(
            self.version, fetch_json=fetch_json,
            fetch_text=lambda url: self.files[url.rsplit('/', 1)[-1]],
            fetch_manifest=lambda path: self.manifests[path],
            video_check=lambda _: (0, 'videos ready'),
        )
        self.assertEqual(len(problems), 1)
        self.assertIn('GitHub Release: unable to verify (offline)', problems[0])


if __name__ == '__main__':
    unittest.main()
