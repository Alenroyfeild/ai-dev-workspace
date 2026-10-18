import contextlib
import io
import json
import os
import unittest
from unittest import mock
import test_sharing
from ws import cli, core, knowledge, scope, sharing, team, team_ui


class TeamUxTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def run_cli(self, *args, tty=False, root=None, answer='n'):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(cli, 'human', return_value=tty), mock.patch('builtins.input', return_value=answer):
            code = cli.main(['--workspace-root', str(root or self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def test_private_note_keeps_text_and_paths_but_still_redacts_secrets(self):
        item = knowledge.add(self.root, 'Public fact\nfigure #private\nsee /Users/dev/app token=abcdefgh12345678', 'repo')
        text = (core.vault(self.root) / 'Knowledge' / (item.split(':')[1] + '.md')).read_text()
        self.assertIn('figure #private\nsee /Users/dev/app', text)  # stored as written
        self.assertNotIn('abcdefgh12345678', text)
        self.assertEqual(len(knowledge.list_entries(self.root, 'repo', 'private')['entries']), 1)
        # cards and summaries are derived, so they still drop the markers
        self.assertNotIn('figure', knowledge.show(self.root, 'private:' + item.split(':')[1])['content'])

    def test_private_note_with_open_marker_is_saved_and_indexed(self):
        item = knowledge.add(self.root, 'Keep <private>this open span', 'repo')
        self.assertTrue(knowledge.list_entries(self.root, 'repo', 'private')['entries'])
        self.assertIn('<private>this open span', (core.vault(self.root) / 'Knowledge' / (item.split(':')[1] + '.md')).read_text())

    def test_sharing_a_private_note_later_still_strips_markers_and_paths(self):
        item = knowledge.add(self.root, 'Public fact\nsecret figure #private\nsee /Users/dev/app/notes', 'repo')
        scope.record(self.root, item, 'team')
        content = sharing.preview(self.root, item)['content']
        self.assertIn('Public fact', content)
        for gone in ('secret figure', '#private', '/Users/dev'): self.assertNotIn(gone, content)

    def test_team_note_that_is_all_private_says_nothing_saved_or_shared(self):
        for text in ('whole line is #private', '<private>everything</private>'):
            with self.assertRaises(core.WsError) as caught: knowledge.add(self.root, text, 'repo', True)
            self.assertIn('not saved', str(caught.exception).lower()); self.assertIn('nothing was shared', str(caught.exception).lower())
        self.assertFalse(list((core.vault(self.root) / 'Knowledge').glob('*.md')))

    def test_terminal_preview_is_a_short_summary_and_scripts_keep_json(self):
        text = 'Payments API rejects floats ' + 'x' * 80
        code, out, _ = self.run_cli('know', 'add', text, '--category', 'domain', '--team', tty=True)
        self.assertEqual(code, 0)
        self.assertIn('+ domain Payments API rejects floats ' + 'x' * 80 + '\n', out)  # the whole published text
        self.assertIn(str(self.remote), out); self.assertLess(len(out.splitlines()), 15)
        for raw in ('"content"', 'artifact_diff', 'source_sha'): self.assertNotIn(raw, out)
        self.assertIn('[y/N]', out)
        code, out, _ = self.run_cli('know', 'add', 'Second note for scripts.', '--team', tty=False)
        self.assertIn('"artifact_diff"', out); self.assertIn('"content"', out)

    def test_text_after_character_100_is_visible_at_consent(self):
        text = 'Deploy notes ' + 'word ' * 25 + 'hunter2-late-private-detail'
        self.assertGreater(text.index('hunter2'), 100)
        code, out, _ = self.run_cli('know', 'add', text, '--team', tty=True)
        self.assertIn('hunter2-late-private-detail', out)
        code, out, _ = self.run_cli('know', 'add', 'x' * 700, '--team', tty=True)
        self.assertIn('x' * 600 + '\u2026 (100 more characters; WS_JSON=1 shows all)', out); self.assertNotIn('x' * 601, out)
        self.run_cli('know', 'add', text, '--team', '--yes')
        sync = team_ui.sync({'remote': 'r', 'files': {'entries/' + 'a' * 32 + '.md': '---\ncategory: repo\n---\n' + sharing.HEADER_END + text + '\n'}})
        self.assertIn('hunter2-late-private-detail', sync)

    def test_terminal_unshare_summary_marks_removal(self):
        code, out, _ = self.run_cli('know', 'add', 'Remove me later.', '--team', '--yes', tty=False)
        entry = knowledge.list_entries(self.root, layer='private')['entries'][0]['key'].split(':')[1]
        code, out, _ = self.run_cli('unshare', 'knowledge:' + entry, tty=True)
        self.assertIn('- other Remove me later.', out)

    def test_team_init_prints_once_with_yes_and_a_summary_at_a_terminal(self):
        other = self.base / 'other.git'; team._git(self.base, 'init', '--bare', '-q', str(other))
        fresh = self.base / 'fresh'; core.init(fresh, 'synthetic', clients=[])
        code, out, _ = self.run_cli('team', 'init', str(other), '--yes', '--attest-private', root=fresh)
        self.assertEqual(code, 0); json.loads(out)  # one document, not preview then result
        fresh2 = self.base / 'fresh2'; core.init(fresh2, 'synthetic', clients=[])
        code, out, _ = self.run_cli('team', 'init', str(self.base / 'x.git'), '--dry-run', '--attest-private', tty=True, root=fresh2)
        self.assertIn('Team init', out); self.assertNotIn('"changes"', out); self.assertNotIn('changes:', out)

    def test_team_status_without_entries_says_so(self):
        code, out, err = self.run_cli('team', 'status')
        self.assertEqual(code, 0); self.assertIn('No team status', err); self.assertEqual(json.loads(out)['entries'], [])

    def test_sync_prints_a_one_line_count_summary(self):
        self.run_cli('know', 'add', 'Queue contract note.', '--team', '--yes')
        code, _, err = self.run_cli('sync', '--yes')
        self.assertEqual(code, 0); self.assertIn('published 1', err)
        code, _, err = self.run_cli('sync', '--yes')
        self.assertIn('nothing to publish', err)

    def test_sync_summary_counts_pulled_notes(self):
        self.run_cli('know', 'add', 'Note one.', '--team', '--yes'); self.run_cli('sync', '--yes')
        mate = self.base / 'mate'; core.init(mate, 'synthetic', clients=[])
        self.assertEqual(self.run_cli('team', 'link', str(self.remote), '--yes', '--attest-private', root=mate)[0], 0)
        self.run_cli('know', 'add', 'Note two.', '--team', '--yes'); self.run_cli('sync', '--yes')
        code, _, err = self.run_cli('sync', '--yes', root=mate)
        self.assertEqual(code, 0); self.assertIn('pulled 1 new', err)

    def test_sync_line_wording(self):
        self.assertEqual(team_ui.sync_line({'a': '1', 'b': '1'}, {'a': '2', 'b': '1', 'c': '1'}, ['entries/' + 'a' * 32 + '.md']),
                         'Team sync: pulled 1 new, 1 updated; published 1.')
        self.assertEqual(team_ui.sync_line({}, {}, None), 'Team sync: nothing new from the team; nothing to publish.')

    def test_link_to_an_unpublished_remote_tells_the_host_what_to_run(self):
        empty = self.base / 'empty.git'; team._git(self.base, 'init', '--bare', '-q', str(empty))
        mate = self.base / 'mate2'; core.init(mate, 'synthetic', clients=[])
        code, _, err = self.run_cli('team', 'link', str(empty), '--yes', '--attest-private', root=mate)
        self.assertNotEqual(code, 0); self.assertIn('ws team init', err); self.assertIn('ws sync', err)
