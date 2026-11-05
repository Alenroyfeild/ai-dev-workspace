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
        self.assertIn('10 lessons OK', result.stdout)

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
            # Typed lines show only the lesson command: no internal check text on screen.
            self.assertEqual(typed[1:], ['Type ' + self.video.vhs_string(c) for c in data['commands']])

    def test_typed_commands_with_quotes_use_a_vhs_string_without_escapes(self):
        # VHS strings have no escape sequences, so a JSON-style \" breaks the tape parser.
        data = {'commands': ['ws lesson add "Mocked DB hid a bad migration" --tag testing', "echo 'single' \"double\""]}
        with tempfile.TemporaryDirectory() as temp:
            tape = self.video.tape(data, Path(temp), Path(temp) / 'raw.mp4')
        typed = [line[len('Type '):] for line in tape.splitlines() if line.startswith('Type ')][1:]
        self.assertEqual(len(typed), 2)
        for text, command in zip(typed, data['commands']):
            quote = text[0]
            self.assertIn(quote, '"\'`')
            self.assertEqual(text[-1], quote)
            self.assertNotIn(quote, text[1:-1])
            self.assertTrue(text[1:-1].startswith(command))
        with self.assertRaises(ValueError):
            self.video.vhs_string('a " b \' c ` d')

    def test_steps_wait_on_the_prompt_because_vhs_screen_match_ignores_scrolled_output(self):
        # Wait+Screen reads the top of the buffer, so a long `ws start` output never matched its marker.
        with tempfile.TemporaryDirectory() as temp:
            data = self.video.parse(self.lesson(temp))
            tape = self.video.tape(data, Path(temp), Path(temp) / 'raw.mp4')
            self.assertNotIn('Wait+Screen', tape)
            self.assertIn('Wait+Line /^\\$$/', tape)
            self.assertIn('Set WaitTimeout', tape)
            setup = self.video.setup_script(Path('/x/python'), Path('/x/repo'))
            self.assertIn('PROMPT_COMMAND=', setup)
            self.assertIn('FAILED $ ', setup)
            self.assertNotIn('\nPS1="$ "\n', setup)

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

    # --- version-synced video links (docs/video/videos.json) ---
    def videos(self, temp, **latest):
        path = Path(temp) / 'videos.json'
        entry = dict({'explainer': None, 'tour': None, 'shorts': {'Guards': None}}, **latest)
        path.write_text(__import__('json').dumps({'latest': '9.9', 'releases': {'9.9': entry}}))
        return path

    def test_videos_json_accepts_only_youtube_links(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(self.video.links_block(self.video.load_videos(self.videos(temp))), '')
            with self.assertRaisesRegex(ValueError, 'only YouTube'):
                self.video.load_videos(self.videos(temp, explainer='https://example.com/v.mp4'))

    def test_links_block_lists_uploaded_videos_and_rewrite_is_idempotent(self):
        url = 'https://youtu.be/' + 'a' * 11
        with tempfile.TemporaryDirectory() as temp:
            data = self.video.load_videos(self.videos(temp, explainer=url, shorts={'Guards': url}))
            root = Path(temp)
            (root / 'docs').mkdir()
            for name in self.video.LINKED:
                (root / name).write_text('top\n<!-- videos:start -->\nold\n<!-- videos:end -->\nend\n')
            self.video.write_links(data, root)
            once = (root / 'README.md').read_text()
            self.video.write_links(data, root)
            self.assertEqual((root / 'README.md').read_text(), once)
            self.assertIn('[Watch the 2-minute explainer](' + url + ')', once)
            self.assertIn('[Guards](' + url + ')', once)
            self.assertNotIn('old', once)

    def test_readme_and_tutorial_video_blocks_match_videos_json(self):
        data = self.video.load_videos()
        block = self.video.START + '\n' + self.video.links_block(data) + self.video.END
        for name in self.video.LINKED:
            self.assertIn(block, (ROOT / name).read_text(encoding='utf-8'), name + ': run bin/make-video --links')

    def test_release_check_names_missing_steps(self):
        with tempfile.TemporaryDirectory() as temp:
            data = self.video.load_videos(self.videos(temp))
            problems = self.video.release_check(data, '9.9')
            self.assertTrue(any('explainer not uploaded' in p for p in problems))
            self.assertTrue(any('latest is 9.9' in p for p in self.video.release_check(data, '10.0')))
