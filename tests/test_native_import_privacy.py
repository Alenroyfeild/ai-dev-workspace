import json

from test_native_memory import NativeBase
from ws import native


class NativeImportPrivacyTests(NativeBase):
    def test_claude_private_markers_are_checked_before_truncation_or_metadata(self):
        directory = self.claude_dir(self.repo)
        self.memory(directory, 'public', 'Use integer cents.')
        private = {'tag.md': 'PRIVATE_TAG #private',
                   'header.md': '---\ndescription: PRIVATE_HEADER #PRIVATE\n---\nbody',
                   'slash.md': '\ufeff /private\nPRIVATE_SLASH',
                   'late.md': 'PRIVATE_LATE\n' + ('x' * 21000) + '\n#private'}
        for name, text in private.items():
            (directory / name).write_text(text, encoding='utf-8')
        before = {p: p.read_bytes() for p in directory.iterdir()}
        result = native.import_native(self.root, 'claude', yes=True)
        self.assertEqual([i['text'] for i in result['items']], ['public: Use integer cents.'])
        self.assertNotIn('PRIVATE_', self.handoff())
        self.assertEqual(before, {p: p.read_bytes() for p in directory.iterdir()})

    def test_codex_and_gemini_privacy_markers_are_respected(self):
        self.memories_db([('1', 'myapp-repo #private', 'PRIVATE_RAW', 'raw', 3),
                          ('2', 'myapp-repo', '/private PRIVATE_SUMMARY', 'summary', 2),
                          ('3', 'myapp-repo', 'Use cents.', 'public', 1)])
        self.assertEqual([i['text'] for i in native.collect(self.root, 'codex')], ['Use cents.'])
        folder = self.home / '.gemini'; folder.mkdir()
        path = folder / 'GEMINI.md'
        path.write_text('/private\n## Gemini Added Memories\n- PRIVATE_GEMINI\n', encoding='utf-8')
        self.assertEqual(native.collect(self.root, 'gemini'), [])
        path.write_text('## Gemini Added Memories\n- Public memory #private\n', encoding='utf-8')
        self.assertEqual(native.collect(self.root, 'gemini'), [])

    def test_bom_frontmatter_and_controls_are_safe_for_every_client(self):
        unsafe = 'Use cents.\x1b[31m\x1b]0;title\x07 \u202e \x00 <private>HIDDEN</private>'
        directory = self.claude_dir(self.repo)
        (directory / 'rule.md').write_text('\ufeff---\nname: money\ndescription: ' + unsafe + '\n---\nbody', encoding='utf-8')
        self.memories_db([('1', 'myapp-repo', unsafe, 'slug\u202e', 1)])
        folder = self.home / '.gemini'; folder.mkdir()
        (folder / 'GEMINI.md').write_text('## Gemini Added Memories\n- ' + unsafe, encoding='utf-8')
        result = native.import_native(self.root, yes=True)
        self.assertEqual(len(result['items']), 3)
        self.assertIn('money: Use cents.', result['items'][0]['text'])
        for item in result['items']:
            for field in ('text', 'source'):
                self.assertTrue(all(c.isprintable() for c in item[field]), repr(item[field]))
        self.assertNotIn('HIDDEN', json.dumps(result))
        self.assertNotIn('HIDDEN', self.handoff())
