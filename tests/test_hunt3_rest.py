"""Bug hunt round 3: input-robustness and wording fixes (feedback, Runs lines, Codeburn shapes, deep JSON, sync, recap, --folder, pr-notes)."""
import contextlib
import io
import json
import os
import re
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import test_sharing
import test_team_folder
from test_ws import Base
from ws import assist, cli, core, knowledge, sharing, team_ui


def run_cli(root, *args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch('builtins.input', return_value='n'):
        code = cli.main(['--workspace-root', str(root), *args])
    return code, out.getvalue(), err.getvalue()


class FeedbackTests(Base):
    def test_submit_preview_localizes_home_paths(self):  # 4
        core.feedback_add(self.root, 'path /Users/bob/clients/acme/app.py leaks', 'bug')
        preview = core.feedback_submit(self.root, 1)
        self.assertNotIn('/Users/bob', preview['title'] + preview['body'])

    def test_gh_success_with_empty_output_is_an_error_not_an_index_error(self):  # 27
        core.feedback_add(self.root, 'something broke', 'bug')
        done = subprocess.CompletedProcess([], 0, stdout='', stderr='')  # mocked: a shebang-only fake gh cannot run on Windows
        with mock.patch.dict(os.environ, {'WS_OFFLINE': '0'}), mock.patch.object(core.subprocess, 'run', return_value=done) as run, \
                self.assertRaisesRegex(core.WsError, 'no issue URL.*ws feedback link 1'):
            core.feedback_submit(self.root, 1, yes=True, use_gh='gh')
        self.assertEqual(run.call_args.args[0][:3], ['gh', 'issue', 'create'])

    @unittest.skipIf(os.name == 'nt', 'POSIX fake CLI shebang; the mocked test above is portable')
    def test_real_fake_gh_executable_with_empty_output(self):
        core.feedback_add(self.root, 'something broke', 'bug')
        gh = Path(self.tmp.name) / 'gh'
        gh.write_text('#!/bin/sh\nexit 0\n'); gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        with mock.patch.dict(os.environ, {'WS_OFFLINE': '0'}), self.assertRaisesRegex(core.WsError, 'no issue URL.*ws feedback link 1'):
            core.feedback_submit(self.root, 1, yes=True, use_gh=str(gh))


class RunsLineTests(Base):
    def setUp(self):
        super().setUp()
        core.run_log(self.root, 'T-1', 'plan', 'claude', seconds=0.48816745799999994)
        self.runs = core.vault(self.root) / 'Runs/T-1.jsonl'

    def append(self, *lines):
        with self.runs.open('a') as f: f.write(''.join(line + '\n' for line in lines))

    def test_bad_lines_are_skipped_with_one_named_warning(self):  # 8
        self.append('{"foo": 1}', '{"at":"x","step":"s","provider":"p","model":"","tokens_in":"5","tokens_out":0,"seconds":0,"result":"ok"}',
                    '{torn', '[1]', '{"at":"x","step":"s","provider":"p","model":"","tokens_in":1,"tokens_out":1,"seconds":0,"result":"failed","checks":["x"]}')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(len(core.run_entries(self.root, 'T-1')), 1)
            self.assertEqual(core.run_report(self.root)['steps'], 1)
            self.assertIn('Total tokens', core.trace(self.root, 'T-1'))
        self.assertEqual(err.getvalue().count('skipped 5 unreadable line(s) in vault/Runs/T-1.jsonl'), 3)  # once per read

    def test_wrong_shaped_check_lists_cannot_crash_repeat_guard(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'x')
        line = '{"at":"x","step":"s","provider":"p","model":"","tokens_in":1,"tokens_out":1,"seconds":0,"result":"ok","checks":%s}'
        self.append(*(line % bad for bad in ('["x"]', '5', 'null', '[{"command":"a"}]')))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(core.repeat_guard(self.root), '')
            assist.suggestions(self.root)

    def test_trace_rounds_seconds(self):  # 26
        text = core.trace(self.root, 'T-1')
        self.assertIn('seconds: 0.49', text); self.assertNotIn('0.4881', text)


class CodeburnShapeTests(Base):
    def suggest(self, report, usage):
        with mock.patch.object(assist, 'cost_data', return_value=(report, usage)):
            return assist.suggestions(self.root, True)

    def test_unknown_shapes_are_ignored(self):  # 9
        for report, usage in (([], None), (None, []), ({'findings': 5}, {}), ({'findings': ['x']}, {'mcp': 'x'}),
                              ({}, {'mcp': [{'Calls': 3}]}), ({}, {'mcp': [{'Server': 'a', 'Calls': '3'}, 4]}),
                              ({'findings': [{'id': 'a1', 'title': None, 'explanation': None, 'estimatedSavingsUSD': '12'}]}, {})):
            self.suggest(report, usage)

    def test_good_finding_still_reported_and_string_saving_tolerated(self):
        items = self.suggest({'findings': [{'id': 'a1', 'title': 'Big', 'explanation': 'e', 'estimatedSavingsUSD': '12'}]}, {})
        self.assertIn('cost-a1', [i['id'] for i in items])


class DeepJsonTests(Base):
    def test_digest_and_paste_survive_very_deep_json(self):  # 11
        deep = '[' * 200000 + ']' * 200000
        saved = core.paste_save(self.root, deep)
        self.assertIn('lines', saved['digest'])
        self.assertEqual(saved['digest'].get('json_shape'), 'JSON nested too deeply to summarize')
        code, out, err = run_cli(self.root, 'digest', str(saved['path']))
        self.assertEqual(code, 0, err)


class DamagedFileTests(Base):
    def test_torn_assist_state_names_the_file_and_recovery(self):  # 28
        (self.root / '.ws/assist.json').write_text('{"torn')
        code, _, err = run_cli(self.root, 'assist')
        self.assertEqual(code, 2)
        self.assertIn('.ws/assist.json is damaged', err); self.assertIn('keep a copy', err)

    def test_load_json_names_file(self):
        with self.assertRaisesRegex(core.WsError, r'\.ws/shares\.json is damaged'):
            core.load_json('{"torn', '.ws/shares.json')


class DamagedSharesTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def test_torn_shares_json_names_the_file(self):
        (self.root / '.ws/shares.json').write_text('{"torn')
        with self.assertRaisesRegex(core.WsError, r'\.ws/shares\.json is damaged'):
            sharing.preview(self.root, 'task:T1', author='tester')


class SyncLineTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def test_pending_files_are_not_called_nothing(self):  # 20
        line = team_ui.sync_line({}, {}, None, 2)
        self.assertIn('2 file(s) pending', line); self.assertNotIn('nothing to publish', line)
        self.assertIn('nothing to publish', team_ui.sync_line({}, {}, None, 0))

    def test_dry_run_with_a_plan_says_pending(self):
        knowledge.add(self.root, 'Queue contract note.', 'repo', True)
        code, _, err = run_cli(self.root, 'sync', '--dry-run')
        self.assertEqual(code, 0); self.assertIn('pending', err); self.assertNotIn('nothing to publish', err)


class RecapEscapeTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def test_apostrophes_stay_plain_in_the_team_section(self):  # 23
        note = {'author': 'bob', 'date': core.now()[:10], 'category': 'domain', 'summary': "Bob's tip <b>"}
        with mock.patch('ws.knowledge.list_entries', return_value={'entries': [note]}):
            md = core.recap(self.root)['markdown']
        self.assertIn("Bob's tip &lt;b&gt;", md); self.assertNotIn('&#x27;', md)


class FolderFlagTests(unittest.TestCase):
    setUp = test_team_folder.TeamFolderTests.setUp
    record = test_team_folder.TeamFolderTests.record

    def test_folder_flag_takes_its_path_in_either_order(self):  # 24
        for args in (('--folder', str(self.folder)), (str(self.folder), '--folder')):
            code, out, err = run_cli(self.root, 'team', 'link', *args, '--attest-private', '--dry-run')
            self.assertEqual(code, 0, err)
            self.assertNotIn('unrecognized', err)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run_cli(self.root, 'team', 'link', 'other', '--folder', str(self.folder), '--dry-run')


class CapturedScanTests(Base):
    def test_unterminated_markers_are_linear(self):  # 31
        path = core.task_path(self.root, 'T-1')  # written directly: checkpoint itself is slow on this input
        path.write_text(core.set_section(path.read_text(), 'Handoff', 'Decision: keep\n' + '<!-- ws:captured:a -->\n' * 20000))
        start = time.time()
        md = core.pr_notes(self.root, 'T-1')['markdown']
        self.assertLess(time.time() - start, 3)
        self.assertIn('keep', md)

    def test_drop_captured_matches_the_old_regex_semantics(self):
        old = lambda s: re.sub(r'<!-- ws:captured:.*\Z', '', re.sub(r'<!-- ws:captured:.*?<!-- /ws:captured -->', '', s, flags=re.S), flags=re.S)
        s, e = '<!-- ws:captured:x -->', '<!-- /ws:captured -->'
        for text in ('', 'a', f'a{s}b{e}c', f'a{s}b', f'{s}{s}b{e}c{s}d', f'a{e}b', f'{s}1{e}{s}2{e}tail', f'x{s}1{e}y{s}'):
            self.assertEqual(core._drop_captured(text), old(text), text)


if __name__ == '__main__':
    unittest.main()
