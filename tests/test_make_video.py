import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class VideoTests(unittest.TestCase):
    def setUp(self):
        loader = importlib.machinery.SourceFileLoader('make_video', str(ROOT / 'bin/make-video'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.video = importlib.util.module_from_spec(spec)
        loader.exec_module(self.video)

    def lesson(self, directory):
        path = Path(directory) / '01-example.md'
        path.write_text('---\ntitle: Example\nduration_hint: 30s\nstatus: Stable\nws_version: 0.1.0b5\n'
                        '---\n## Problem\nLost context.\n## Steps\n```sh\nws demo\n```\n'
                        '## Guidance\nOffline illustration, not live client proof.\n')
        return path

    def test_parse_and_reject_missing_sections_and_unsafe_steps(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.lesson(temp)
            self.assertEqual(self.video.parse(path)['commands'], ['ws demo'])
            original = path.read_text()
            for bad in ('curl example.invalid', 'ws demo; curl example.invalid',
                        'ws demo > ~/.claude/settings.json', 'ws demo $(whoami)'):
                path.write_text(original.replace('ws demo', bad))
                with self.subTest(command=bad), self.assertRaises(ValueError):
                    self.video.parse(path)
            for missing in ('title:', 'duration_hint:', 'status:', 'ws_version:', '## Guidance'):
                path.write_text(original.replace(missing, 'missing'))
                with self.subTest(missing=missing), self.assertRaises(ValueError):
                    self.video.parse(path)

    def test_hash_skip_requires_matching_inputs_and_existing_clip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.lesson(temp)
            clip = Path(temp) / '01-example.mp4'
            record = self.video.fingerprint(path, 'settings')
            self.assertFalse(self.video.cached(path, record, clip, 'settings'))
            clip.write_bytes(b'video')
            self.assertTrue(self.video.cached(path, record, clip, 'settings'))
            self.assertFalse(self.video.cached(path, record, clip, 'new settings'))
            path.write_text(path.read_text() + '\nChanged guidance.\n')
            self.assertFalse(self.video.cached(path, record, clip, 'settings'))

    def test_check_does_not_probe_tools_or_render_and_checks_real_lessons(self):
        with patch.object(self.video.shutil, 'which', side_effect=AssertionError('tool probe')), \
                patch.object(self.video, 'render', side_effect=AssertionError('render')):
            self.assertEqual(self.video.main(['--check']), 0)
        result = subprocess.run([sys.executable, str(ROOT / 'bin/make-video'), '--check'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('8 lessons OK', result.stdout)

    def test_missing_tools_exit_two_without_executing_lessons(self):
        with patch.object(self.video.shutil, 'which', return_value=None), \
                patch.object(self.video, 'render', side_effect=AssertionError('render')):
            self.assertEqual(self.video.main([]), 2)

    def test_tape_reuses_demo_style_and_runs_only_in_disposable_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            data = self.video.parse(self.lesson(temp))
            tape = self.video.tape(data, Path(temp), Path(temp) / 'raw.mp4')
            for setting in (ROOT / 'docs/demo.tape').read_text().splitlines():
                if setting.startswith('Set '):
                    self.assertIn(setting, tape)
            self.assertIn('Hide', tape)
            self.assertIn('Show', tape)
            self.assertNotIn('bin/ws', tape)
            typed = [line for line in tape.splitlines() if line.startswith('Type ')]
            self.assertFalse(any('VIDEO_STEP_0_OK' in line for line in typed))

    def test_failed_render_never_replaces_clip_or_commits_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'docs/video').mkdir(parents=True)
            self.lesson(root / 'docs/video')
            (root / 'docs/demo.tape').write_text('Set Shell bash\n')
            python_arg = root / 'venv-python'
            def fail(path, data, clip, python):
                self.assertEqual(python, python_arg.absolute())
                clip.write_bytes(b'partial')
                raise OSError('encoder failed')
            with patch.object(self.video, 'ROOT', root), \
                    patch.object(self.video.Path, 'resolve', return_value=Path(sys.executable)), \
                    patch.object(self.video.shutil, 'which', return_value='tool'), \
                    patch.object(self.video, 'render', side_effect=fail):
                self.assertEqual(self.video.main(['--ws-python', str(python_arg)]), 2)
            self.assertFalse((root / 'build/video/01-example.mp4').exists())
            self.assertFalse((root / 'build/video/manifest.json').exists())

    def test_build_is_excluded_from_git_and_source_manifest(self):
        self.assertIn('build/', (ROOT / '.gitignore').read_text().splitlines())
        self.assertIn('prune build', (ROOT / 'MANIFEST.in').read_text().splitlines())
