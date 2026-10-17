import contextlib
import io
import unittest
from unittest import mock

from test_ws import Base
from ws import cli, core


class ErrorHintTests(Base):
    def ws(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch('sys.stdin', io.StringIO('')):
            code = cli.main(['--workspace-root', str(self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def test_next_hint_follows_a_sentence_and_names_the_failing_command(self):
        code, _, err = self.ws('feedback', 'link', '9', 'http://x')
        self.assertEqual(code, 2)
        self.assertIn('issues/12. Next: run `ws feedback --help`.', err)
        self.assertIn('. Next: run `ws pack --help`.', self.ws('pack', 'add', 'nosuch')[2])

    def test_offline_messages_read_as_sentences(self):
        with mock.patch.dict('os.environ', {'WS_OFFLINE': '1'}):
            _, out, _ = self.ws('update', '--check')
        self.assertIn('Offline mode: update checks skipped while WS_OFFLINE=1.', out)

    def test_unknown_assistant_and_role_list_the_valid_choices(self):
        err = self.ws('setup', '--assistants', 'nosuch')[2]
        self.assertIn('Unknown assistant nosuch. Choose from: claude, codex', err)
        self.assertNotIn('routing preset', err)
        self.assertIn('Unknown role nosuch. Choose from: lead, planner', self.ws('route', 'nosuch')[2])

    def test_team_flag_without_a_team_says_the_record_was_saved_locally(self):
        for args in (('know', 'add', 'Queues stay bounded.', '--team'), ('lesson', 'add', 'Queue grew -> bound it.', '--team'),
                     ('remember', 'Queues stay bounded.', '--team', '--task', 'T-1')):
            core.claim(self.root, 'T-1', 'synthetic') if args[0] == 'remember' else None
            code, _, err = self.ws(*args)
            self.assertEqual(code, 2)
            self.assertIn('Saved locally, not shared: Link a private team first: run `ws team link <private-repo>`.', err)


    def test_malformed_team_manifest_still_says_saved_locally(self):
        import json
        cfg = core.config(self.root); cfg['team_workspace'] = {'path': '.ws/team', 'id': 'a' * 32}
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        (self.root / '.ws/team').mkdir(parents=True, exist_ok=True); (self.root / '.ws/team/team.json').write_text('{not json')
        code, _, err = self.ws('know', 'add', 'Queues stay bounded.', '--team')
        self.assertEqual(code, 2)
        self.assertIn('Saved locally, not shared:', err)
        self.assertNotIn('Traceback', err)


if __name__ == '__main__':
    unittest.main()
