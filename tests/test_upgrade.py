import json
import subprocess
from unittest import mock
from pathlib import Path
from test_ws import Base, KIT
from ws import core


class UpgradeTests(Base):
    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_old_fixture_preview_sidecars_and_second_run(self):
        self.root = Path(self.tmp.name) / 'old-workspace'
        # The first release's template (commit 9853713), stored as a fixture: CI checkouts are shallow.
        fixture = KIT / 'tests/fixtures/template-0.1.0-beta.1'
        for source in fixture.rglob('*'):
            if source.is_file():
                path = self.root / source.relative_to(fixture); path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(source.read_bytes())
        old = (self.root / 'AGENTS.md').read_bytes()
        rules = self.root / 'AGENTS.md'; rules.write_bytes(old + b'\nUser synthetic rule stays.\n')
        hooks = self.root / '.claude/settings.json'; hooks.parent.mkdir()
        hooks.write_bytes(b'{ "user": "keep spacing", "hooks": {} }\n')
        cfg = dict(schema_version=1, name='old fixture', packs=[], repos=[], vault='custom-vault', custom=True)
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        before = self.snapshot()
        preview = core.upgrade_workspace(self.root, dry_run=True)
        self.assertEqual(before, self.snapshot())
        self.assertTrue(any(c['path'] == 'AGENTS.md.ws-new' and 'ws:managed' in c['diff'] for c in preview['changes']))
        result = core.upgrade_workspace(self.root)
        self.assertEqual(result['changes'], preview['changes'])
        self.assertEqual(rules.read_bytes(), before['AGENTS.md'])
        self.assertEqual(hooks.read_bytes(), before['.claude/settings.json'])
        cfg = core.config(self.root)
        self.assertEqual((cfg['schema_version'], cfg['vault'], cfg['custom']), (2, 'custom-vault', True))
        self.assertIn('AGENTS.md', cfg['upgrade_pending'])
        self.assertTrue(list((self.root / '.ws/backups').rglob('workspace.json')))
        self.assertEqual(core.upgrade_workspace(self.root)['changes'], [])
        self.assertTrue((self.root / '.agents/skills/pickup/SKILL.md').exists())

    def test_managed_markdown_and_hook_objects_preserve_outside_bytes(self):
        rules = self.root / 'AGENTS.md'
        rules.write_text('User prefix\n' + rules.read_text() + '\nUser suffix\n')
        hook = self.root / '.claude/settings.json'
        text = hook.read_text()
        text = text[:-2] + ', "user": {"text": "braces { inside a string", "spaces":  3}\n}\n'
        hook.write_text(text)
        original_rules, original_hook = rules.read_bytes(), hook.read_bytes()
        current = core.kit_meta()['version']
        with mock.patch.object(core, 'kit_meta', return_value={'version': '9.0.0'}):
            preview = core.upgrade_workspace(self.root, dry_run=True)
            self.assertTrue(preview['changes'])
            core.upgrade_workspace(self.root)
            self.assertEqual(core.upgrade_workspace(self.root)['changes'], [])
        self.assertTrue(rules.read_bytes().startswith(b'User prefix\n'))
        self.assertTrue(rules.read_bytes().endswith(b'\nUser suffix\n'))
        self.assertEqual(original_rules.replace(current.encode(), b'9.0.0'), rules.read_bytes())
        self.assertEqual(original_hook.replace(current.encode(), b'9.0.0'), hook.read_bytes())
        self.assertEqual(json.loads(hook.read_text())['user']['spaces'], 3)
        self.assertTrue(list((self.root / '.ws/backups').rglob('AGENTS.md')))

    def test_edited_proposal_and_symlinks_are_not_overwritten(self):
        rules = self.root / 'AGENTS.md'; rules.write_text('Unmarked user file\n')
        proposal = self.root / 'AGENTS.md.ws-new'; proposal.write_text('Edited proposal\n')
        core.upgrade_workspace(self.root)
        self.assertEqual(proposal.read_text(), 'Edited proposal\n')
        self.assertTrue((self.root / 'AGENTS.md.ws-new.1').exists())
        rules.unlink(); rules.symlink_to(proposal)
        with self.assertRaises(core.WsError): core.upgrade_workspace(self.root)

    def test_ambiguous_hooks_stage_proposals_and_newer_schema_is_refused(self):
        path = self.root / '.claude/settings.json'
        data = json.loads(path.read_text())
        data['hooks']['Stop'][0]['hooks'].append(data['hooks']['Stop'][0]['hooks'][0])
        path.write_text(json.dumps(data)); before = path.read_bytes()
        core.upgrade_workspace(self.root)
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue((self.root / '.claude/settings.json.ws-new').exists())
        cfg = core.config(self.root); cfg['schema_version'] = 99
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        before = self.snapshot()
        with self.assertRaises(core.WsError): core.upgrade_workspace(self.root)
        self.assertEqual(before, self.snapshot())
