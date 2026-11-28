import hashlib
import json
from pathlib import Path
import shutil

from test_ws import Base, KIT
from testutil import run_ws
from ws import core, upgrade


class RepoWiringHintTests(Base):
    def setUp(self):
        super().setUp()
        self.project = Path(self.tmp.name).resolve() / 'repo with spaces'
        shutil.copytree(KIT / 'tests/fixtures/repo-wiring-beta6', self.project)
        state_path = self.project / '.ws-start.json'
        state = json.loads(state_path.read_text())
        state['workspace'] = str(self.root)
        state_path.write_text(json.dumps(state))
        cfg = core.config(self.root)
        cfg['repos'] = [str(self.project)]
        (self.root / 'workspace.json').write_text(json.dumps(cfg))

    def snapshot(self):
        return {str(p.relative_to(self.project)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.project.rglob('*') if p.is_file()}

    def test_old_wiring_is_reported_in_upgrade_and_both_status_formats(self):
        for edited in (False, True):
            with self.subTest(edited=edited):
                cfg = core.config(self.root)
                cfg['kit_version'] = '0.1.0-beta.6'
                (self.root / 'workspace.json').write_text(json.dumps(cfg))
                if edited:
                    with (self.project / '.codex/config.toml').open('a') as out:
                        out.write('# user edit\n')
                before = self.snapshot()
                state = core.status(self.root)['repo_wiring'][0]
                self.assertEqual(state, dict(repo=str(self.project), kit_version='0.1.0-beta.6',
                                             current=False, blocked_by=['.codex/config.toml'] if edited else []))
                migration = upgrade.migration_result(self.root, {})
                self.assertIn(f'Repo wiring for {self.project}: 0.1.0-beta.6 -> run: cd ', migration)
                self.assertIn('&& ws start', migration)
                if edited:
                    self.assertIn('first fix .codex/config.toml: ws connect codex prints the expected block', migration)
                result = run_ws('--workspace-root', self.root, 'upgrade', '--yes')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'Repo wiring for {self.project}:', result.stderr)
                if edited:
                    self.assertIn('first fix .codex/config.toml', result.stderr)
                for args in (('status', '--text'), ('status', '--json')):
                    result = run_ws('--workspace-root', self.root, *args)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if '--text' in args:
                        self.assertIn('&& ws start', result.stdout)
                        if edited:
                            self.assertIn('first fix .codex/config.toml', result.stdout)
                    else:
                        self.assertEqual(json.loads(result.stdout)['repo_wiring'], [state])
                self.assertEqual(before, self.snapshot())

    def test_current_and_newer_wiring_do_not_suggest_a_refresh(self):
        path = self.project / '.ws-start.json'
        for version in (core.kit_meta()['version'], '99.0.0'):
            state = json.loads(path.read_text())
            state['kit_version'] = version
            path.write_text(json.dumps(state))
            text = upgrade.migration_result(self.root, {})
            self.assertNotIn('-> run: cd ', text)

    def test_customization_with_current_codex_block_is_not_a_blocker(self):
        (self.project / '.codex/config.toml').write_text(
            'model = "fixture"\n' + core.codex_mcp_config(self.root))
        self.assertEqual(core.status(self.root)['repo_wiring'][0]['blocked_by'], [])

    def test_multiple_repos_and_damaged_record_are_reported_without_writes(self):
        other = self.project.parent / 'other'
        other.mkdir()
        record = other / '.ws-start.json'
        record.write_text('{"kit_version":"0.2.0","files":{}}')
        cfg = core.config(self.root)
        cfg['repos'].append(str(other))
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        self.assertEqual(len(core.status(self.root)['repo_wiring']), 2)
        record.write_text('invalid record')
        before = record.read_bytes()
        state = core.status(self.root)['repo_wiring'][1]
        self.assertIsNone(state['kit_version'])
        self.assertEqual(state['blocked_by'], ['.ws-start.json'])
        self.assertEqual(record.read_bytes(), before)

