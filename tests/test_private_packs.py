import json
import os
import subprocess
import sys
from pathlib import Path
from test_ws import Base, KIT
from ws import core


class PrivatePackTests(Base):
    def setUp(self):
        super().setUp()
        self.source = Path(self.tmp.name) / 'private team'
        self.source.mkdir()
        (self.source / 'pack.json').write_text(json.dumps(dict(name='private-team', version='1.0', kind='domain', description='Synthetic private pack')))
        (self.source / 'AGENTS.snippet.md').write_text('Synthetic private rule v1.\n')
        (self.source / 'vault').mkdir()
        (self.source / 'vault/Team.md').write_text('Synthetic notes v1.\n')
        (self.source / 'vault/asset.bin').write_bytes(b'\xff\x00v1')

    def cli(self, *args):
        proc = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'pack', *args], cwd=self.root,
                              env={**os.environ, 'HOME': self.tmp.name, 'CODEX_HOME': str(Path(self.tmp.name) / '.codex')},
                              text=True, capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_private_add_upgrade_remove_preserves_user_edits(self):
        self.cli('add', '--from', str(self.source))
        cfg = core.config(self.root)
        self.assertEqual(cfg['local_packs']['private-team']['path'], str(self.source.resolve()))
        self.assertFalse((KIT / 'packs/private-team').exists())
        self.assertIn('packs', core.doctor(self.root))
        original = (self.root / 'AGENTS.md').read_text()
        self.cli('add', '--from', str(self.source))
        self.assertEqual(original, (self.root / 'AGENTS.md').read_text())
        (self.source / 'AGENTS.snippet.md').write_text('Synthetic private rule v2.\n')
        (self.source / 'vault/Team.md').write_text('Synthetic notes v2.\n')
        (self.source / 'vault/asset.bin').write_bytes(b'\xff\x00v2')
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        preview = core.upgrade_workspace(self.root, dry_run=True)
        self.assertTrue(any(c['path'] == 'vault/Team.md' for c in preview['changes']))
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        core.upgrade_workspace(self.root)
        self.assertIn('rule v2', (self.root / 'AGENTS.md').read_text())
        self.assertEqual((self.root / 'vault/Team.md').read_text(), 'Synthetic notes v2.\n')
        self.assertEqual((self.root / 'vault/asset.bin').read_bytes(), b'\xff\x00v2')
        self.assertEqual(core.upgrade_workspace(self.root)['changes'], [])
        (self.root / 'vault/Team.md').write_text('Edited user notes\n')
        result = self.cli('remove', 'private-team')
        self.assertIn('vault/Team.md', result['kept'])
        self.assertNotIn('private-team', core.config(self.root)['packs'])
        self.assertFalse((self.root / 'vault/asset.bin').exists())
        self.assertNotIn('Synthetic private rule', (self.root / 'AGENTS.md').read_text())
        self.assertEqual((self.root / 'vault/Team.md').read_text(), 'Edited user notes\n')
        self.cli('add', '--from', str(self.source))
        self.cli('remove', 'private-team')
        self.assertEqual((self.root / 'vault/Team.md').read_text(), 'Edited user notes\n')

    def test_invalid_manifest_and_symlinks_are_actionable_and_write_nothing(self):
        from ws import packs
        before = (self.root / 'workspace.json').read_bytes()
        for manifest in ({}, {'name': '../escape'}, {'name': 'ios', 'version': '1', 'kind': 'domain', 'description': 'collision'}):
            (self.source / 'pack.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(core.WsError, 'pack.json|bundled'):
                packs.add(self.root, self.source)
            self.assertEqual((self.root / 'workspace.json').read_bytes(), before)
        (self.source / 'pack.json').write_text(json.dumps(dict(name='private-team', version='1', kind='domain', description='test')))
        (self.source / 'vault/link').symlink_to(self.root / 'workspace.json')
        with self.assertRaisesRegex(core.WsError, 'symlink'):
            packs.add(self.root, self.source)
        self.assertEqual((self.root / 'workspace.json').read_bytes(), before)

    def test_upgrade_stages_edited_rules_and_files_and_remove_needs_no_source(self):
        self.cli('add', '--from', str(self.source))
        rules = self.root / 'AGENTS.md'
        rules.write_text(rules.read_text().replace('rule v1', 'user edited rule'))
        (self.root / 'vault/Team.md').write_text('User notes\n')
        (self.source / 'vault/Team.md').write_text('New private notes\n')
        core.upgrade_workspace(self.root)
        self.assertIn('user edited rule', rules.read_text())
        self.assertEqual((self.root / 'vault/Team.md').read_text(), 'User notes\n')
        self.assertEqual((self.root / 'vault/Team.md.ws-new').read_text(), 'New private notes\n')
        self.source.rename(self.source.with_name('offline-source'))
        result = self.cli('remove', 'private-team')
        self.assertEqual(set(result['kept']), {'AGENTS.md', 'vault/Team.md'})
