import json
import subprocess
import sys
from unittest import mock
from pathlib import Path
from test_ws import Base, KIT
from ws import core


class UpgradeTests(Base):
    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def old_workspace(self):
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

    def test_old_fixture_preview_sidecars_and_second_run(self):
        self.old_workspace()
        rules, hooks = self.root / 'AGENTS.md', self.root / '.claude/settings.json'
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

    def test_dry_run_prints_a_short_summary_and_diff_flag_the_full_diff(self):
        self.old_workspace()
        (self.root / '.claude/settings.json').unlink()  # a beta.4 kit never had one, so upgrade adds it
        run = lambda *a: subprocess.run([sys.executable, str(KIT / 'bin/ws'), *a], cwd=self.root, capture_output=True, text=True)
        before = self.snapshot()
        short, full = run('upgrade', '--dry-run'), run('upgrade', '--dry-run', '--diff')
        self.assertEqual((short.returncode, full.returncode, before), (0, 0, self.snapshot()))
        self.assertLess(len(short.stdout.splitlines()), 30)
        self.assertGreater(len(full.stdout.splitlines()), 400)
        self.assertIn('--dry-run --diff', short.stdout)
        self.assertNotIn('--- routing.json', short.stdout)
        self.assertIn('--- routing.json', full.stdout)
        self.assertIn('+ .claude/settings.json (new: hooks for Claude Code)', short.stdout)
        self.assertIn('+ .codex/hooks.json (new: hooks for Codex)', short.stdout)
        self.assertRegex(short.stdout, r'~ workspace\.json \(changed, \d+ lines; keys ')

    def confirm_run(self, *args, stdin):
        return subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'upgrade', *args], cwd=self.root, capture_output=True, text=True, input=stdin)

    def test_upgrade_previews_then_asks_before_applying(self):
        self.old_workspace(); before = self.snapshot()
        no = self.confirm_run(stdin='n\n')
        self.assertEqual((no.returncode, before), (0, self.snapshot()))  # declined: nothing written
        self.assertIn('Apply this upgrade? [y/N]', no.stderr)
        self.assertIn('+ routing.json (new: managed routing defaults)', no.stdout)  # summary shown before the prompt
        result = self.confirm_run(stdin='')  # no answer at all, like a script or an assistant shell
        self.assertEqual(result.returncode, 2); self.assertIn('ws upgrade --yes or --dry-run', result.stderr)
        self.assertEqual(before, self.snapshot())
        yes = self.confirm_run('--yes', stdin='')
        self.assertEqual(yes.returncode, 0); self.assertNotIn('[y/N]', yes.stderr)
        self.assertTrue((self.root / 'routing.json').exists())
        self.assertEqual(self.confirm_run(stdin='').stdout.splitlines()[0], 'No changes.')  # nothing to apply, nothing to ask

    def test_piped_answer_applies_like_ws_start_and_closed_input_refuses(self):
        self.old_workspace()
        self.assertEqual(self.confirm_run(stdin='y\n').returncode, 0)  # same EOF semantics as ws start: an answer is an answer
        self.assertTrue((self.root / 'routing.json').exists())

    def test_files_changing_during_the_prompt_refuse_with_no_writes(self):
        from io import StringIO
        from contextlib import redirect_stderr, redirect_stdout
        from ws import cli
        self.old_workspace(); settings = self.root / '.claude/settings.json'
        def answer(*args): settings.unlink(); return 'y'  # a previewed .ws-new sidecar would become active hooks
        before = self.snapshot(); before.pop('.claude/settings.json'); err = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(err), mock.patch('builtins.input', side_effect=answer):
            result = cli.main(['--workspace-root', str(self.root), 'upgrade'])
        self.assertEqual(result, 2); self.assertIn('Workspace changed during confirmation; run ws upgrade again', err.getvalue())
        after = self.snapshot(); after.pop('.ws/lock', None)  # the empty lock file is not a managed write
        self.assertEqual(before, after)  # settings stays deleted, nothing else written

    def test_json_key_summary(self):
        from ws.upgrade import json_keys
        self.assertEqual(json_keys(b'{"a": {"x": 1, "y": 2}, "b": 1}', b'{"a": {"x": 1, "y": 3, "z": 4}}'), '+1 -1 ~1')
        self.assertEqual(json_keys(b'', b'{}'), '')

    def test_managed_markdown_and_hook_objects_preserve_outside_bytes(self):
        rules = self.root / 'AGENTS.md'
        rules.write_bytes(('User prefix\n' + rules.read_text() + '\nUser suffix\n').encode())
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
