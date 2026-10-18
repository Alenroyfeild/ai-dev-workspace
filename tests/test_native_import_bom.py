from test_native_memory import NativeBase
from ws import native


class NativeImportBomTests(NativeBase):
    def test_bom_frontmatter_imports_the_description_without_changing_source(self):
        path = self.claude_dir(self.repo) / 'money.md'
        path.write_text('\ufeff---\nname: money\ndescription: Use integer cents.\n---\nBody text.\n', encoding='utf-8')
        before = path.read_bytes()
        result = native.import_native(self.root, 'claude', yes=True)
        self.assertEqual([i['text'] for i in result['items']], ['money: Use integer cents.'])
        self.assertEqual(path.read_bytes(), before)

    def test_bom_only_memory_is_empty(self):
        (self.claude_dir(self.repo) / 'empty.md').write_text('\ufeff', encoding='utf-8')
        self.assertEqual(native.collect(self.root, 'claude'), [])
