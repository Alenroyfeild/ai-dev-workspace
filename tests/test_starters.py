from test_ws import Base
from ws import core, repo


class StarterPackTests(Base):
    def kind(self, **files):
        target = self.root.parent / ('r' + str(len(list(self.root.parent.iterdir()))))
        target.mkdir()
        for name, body in files.items():
            (target / name).mkdir() if body is None else (target / name).write_text(body)
        return repo.starter(target, self.root)

    def test_repo_types_are_detected(self):
        self.assertEqual(self.kind(**{'package.json': '{}'}), 'web')
        self.assertEqual(self.kind(**{'pyproject.toml': '[project]\nname = "x"\n'}), 'library')
        self.assertEqual(self.kind(**{'pyproject.toml': 'dependencies = ["torch>=2"]\n'}), 'ml')
        self.assertEqual(self.kind(**{'requirements.txt': 'scikit-learn\n', 'package.json': '{}'}), 'ml')
        self.assertEqual(self.kind(**{'App.xcodeproj': None, 'package.json': '{}'}), '')  # the test workspace already has ios
        cfg = core.config(self.root); cfg['packs'].remove('ios'); (self.root / 'workspace.json').write_text(__import__('json').dumps(cfg))
        self.assertEqual(self.kind(**{'App.xcodeproj': None, 'package.json': '{}'}), 'ios')
        self.assertEqual(self.kind(**{'README.md': 'x'}), '')

    def test_unreadable_files_and_plain_swift_packages(self):
        target = self.root.parent / 'broken'; target.mkdir()
        (target / 'requirements.txt').symlink_to(target / 'missing.txt')
        (target / 'pyproject.toml').write_text('[project]\nname = "x"\n')
        self.assertEqual(repo.starter(target, self.root), 'library')  # no crash, no ml hint
        cfg = core.config(self.root); cfg['packs'].remove('ios'); (self.root / 'workspace.json').write_text(__import__('json').dumps(cfg))
        self.assertEqual(self.kind(**{'Package.swift': '// swift-tools-version:5.9\nlet p = Package(name: "x", platforms: [.macOS(.v13), .linux])\n'}), '')
        self.assertEqual(self.kind(**{'Package.swift': 'let p = Package(name: "x", platforms: [.iOS(.v16)])\n'}), 'ios')

    def test_no_hint_once_the_pack_is_on(self):
        core.pack_add(self.root, 'web')
        self.assertEqual(self.kind(**{'package.json': '{}'}), '')

    def test_starter_packs_install_short_rules(self):
        for name in ('web', 'library', 'ml'):
            core.pack_add(self.root, name)
            snippet = (core.KIT / 'packs' / name / 'AGENTS.snippet.md').read_text()
            self.assertLess(len(snippet.split()), 100)  # loads every session
            self.assertIn(snippet.strip(), (self.root / 'AGENTS.md').read_text())
