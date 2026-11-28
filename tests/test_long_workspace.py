"""Long-lived synthetic workspace: upgrade and memory behavior, with documented gaps."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fixtures.long_workspace import EARLY_SEARCH, LATEST_DECISION, NEXT_ACTION, create
from testutil import rmtree_owned
from ws import core

KIT = Path(__file__).resolve().parents[1]


def snapshot(root):
    result = {}
    for path in root.rglob('*'):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[name] = ('link', os.readlink(path))
        elif path.is_file():
            result[name] = ('file', hashlib.sha256(path.read_bytes()).hexdigest())
        elif path.is_dir():
            result[name] = ('dir', '')
    return result


class LongWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ws-long-fixture-')
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / 'home'
        self.workspace, self.repo = create(self.home)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('WS_', 'GIT_')) and k not in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'PYTHONPATH')}
        self.env.update(HOME=str(self.home), USERPROFILE=str(self.home), CODEX_HOME=str(self.home / '.codex'),
                        CLAUDE_CONFIG_DIR=str(self.home / '.claude'), XDG_CONFIG_HOME=str(self.home / '.config'),
                        APPDATA=str(self.home / '.config'), LOCALAPPDATA=str(self.home / '.local'),
                        WS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        patch = mock.patch.dict(os.environ, self.env, clear=True)
        patch.start(); self.addCleanup(patch.stop)

    def tearDown(self):
        rmtree_owned(self.temp.name, self.temp.name)
        self.temp.cleanup()

    def ws(self, *args):
        return subprocess.run([sys.executable, str(KIT / 'bin/ws'), *args], cwd=self.repo,
                              env=self.env, text=True, capture_output=True, timeout=120)

    def test_fixture_has_the_intended_synthetic_shape(self):
        text = (self.workspace / 'vault/Tasks/main.md').read_text(encoding='utf-8')
        meta = core.parse_meta(text); handoff = core.section(text, 'Handoff')
        self.assertEqual(meta['checkpoint_count'], '130')
        self.assertEqual(handoff.count('Checkpoint '), 130)
        self.assertIn('on 2026-10-01 keeps ' + EARLY_SEARCH, handoff)
        for section in ('Objective', 'Acceptance criteria', 'Evidence', 'Findings', 'Checks'):
            self.assertEqual(core.section(text, section), '')
        self.assertEqual(handoff.count('Decision:'), 50)
        self.assertEqual(handoff.count('<!-- ws:captured:'), 14)
        self.assertGreater(len(handoff.encode()), 28000)
        self.assertLess(len(handoff.encode()), 35000)
        self.assertEqual(core.current_branch(self.repo), 'main')
        self.assertEqual(core.config(self.workspace)['kit_version'], '0.1.0-beta.6')
        state = json.loads((self.repo / '.ws-start.json').read_text())
        self.assertEqual(state['kit_version'], '0.1.0-beta.6')
        config = self.repo / '.codex/config.toml'
        self.assertIn('enabled = false', config.read_text())
        self.assertNotEqual(state['files']['.codex/config.toml']['sha'], hashlib.sha256(config.read_bytes()).hexdigest())
        self.assertIn('Checkpoint 130 (2026-10-25)', handoff)
        self.assertIn('Syntheticparagraphwithmissingspaces', handoff)
        self.assertEqual(len(core._list_items(core.section(text, 'Do not redo'))), 1)

    def test_synthetic_task_is_deterministic_across_disposable_homes(self):
        second_workspace, second_repo = create(self.base / 'other-home')
        first = (self.workspace / 'vault/Tasks/main.md').read_text(encoding='utf-8').replace(self.repo.as_posix(), '<repo>')
        second = (second_workspace / 'vault/Tasks/main.md').read_text(encoding='utf-8').replace(second_repo.as_posix(), '<repo>')
        self.assertEqual(first, second)
        self.assertEqual((self.workspace / '.ws/claims/main.json').read_bytes(),
                         (second_workspace / '.ws/claims/main.json').read_bytes())

    def test_upgrade_preview_is_read_only_and_apply_backs_up_existing_changes(self):
        before = snapshot(self.home); workspace_before = snapshot(self.workspace)
        task_before = (self.workspace / 'vault/Tasks/main.md').read_bytes()
        dry = self.ws('upgrade', '--dry-run')
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertEqual(snapshot(self.home), before)
        applied = self.ws('upgrade', '--yes')
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        after = snapshot(self.home); prefix = self.workspace.relative_to(self.home).as_posix() + '/'
        self.assertEqual({k: v for k, v in before.items() if not k.startswith(prefix)},
                         {k: v for k, v in after.items() if not k.startswith(prefix)})
        self.assertEqual((self.workspace / 'vault/Tasks/main.md').read_bytes(), task_before)
        brief = self.ws('brief')
        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertIn(LATEST_DECISION, brief.stdout)
        self.assertIn(NEXT_ACTION, brief.stdout)
        search = self.ws('search', EARLY_SEARCH)
        self.assertEqual(search.returncode, 0, search.stderr)
        self.assertTrue(any(EARLY_SEARCH in ' '.join(row['lines']) for row in json.loads(search.stdout)))
        workspace_after = snapshot(self.workspace)
        changed = [name for name, value in workspace_before.items() if name in workspace_after and workspace_after[name] != value]
        self.assertTrue(changed, 'upgrade should change at least one existing workspace file')
        for name in changed:
            with self.subTest(path=name):
                backups = list((self.workspace / '.ws/backups').glob('*/' + name))
                self.assertTrue(any(hashlib.sha256(path.read_bytes()).hexdigest() == workspace_before[name][1] for path in backups))

    @unittest.expectedFailure
    def test_upgrade_names_outdated_repo_and_fix_command(self):
        # MIG-WIRING-HINT: current result reports a version but not the repo and repair command.
        result = self.ws('upgrade', '--yes')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        status = self.ws('status')
        self.assertEqual(status.returncode, 0, status.stderr)
        outputs = (result.stdout + result.stderr, status.stdout + status.stderr)
        self.assertTrue(any((str(self.repo) in text or self.repo.as_posix() in text) and 'ws start' in text
                            for text in outputs), 'neither migration result nor status names the repo and fix command')

    def test_brief_contains_latest_decision_and_next_action(self):
        result = self.ws('brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(LATEST_DECISION, result.stdout)
        self.assertIn(NEXT_ACTION, result.stdout)

    @unittest.expectedFailure
    def test_brief_does_not_cut_an_item_mid_sentence(self):
        # MEM-COMPACT: the current brief clips an over-budget item with an inline ellipsis.
        result = self.ws('brief')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('[…]', result.stdout)

    def test_capture_into_large_task_is_bounded(self):
        transcript = self.home / 'synthetic-transcript.jsonl'
        entries = [
            {'type': 'user', 'message': {'content': 'Decided: only synthetic amber should be kept.'}},
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read'},
                                                         {'type': 'text', 'text': 'Next step: review synthetic amber.'}]}},
        ]
        transcript.write_text('\n'.join(map(json.dumps, entries)) + '\n', encoding='utf-8')
        self.assertTrue(core.capture_decisions(self.workspace, str(transcript), 'claude'))
        handoff = core.task_read(self.workspace, 'main', ['Handoff'])['sections']['Handoff']
        marker = '<!-- ws:captured:' + core.digest_text(str(transcript.resolve()))[:16] + ' -->'
        block = handoff.split(marker, 1)[1].split('<!-- /ws:captured -->', 1)[0]
        self.assertIn('synthetic amber', block)
        self.assertLessEqual(len(block.split()), 150)
        self.assertEqual(handoff.count('<!-- ws:captured:'), 15)

    def test_search_finds_a_first_week_decision(self):
        result = self.ws('search', EARLY_SEARCH)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        self.assertTrue(any('Tasks/main.md' in row['path'] and EARLY_SEARCH in ' '.join(row['lines']) for row in rows))
