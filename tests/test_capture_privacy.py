import json
from test_ws import Base
from ws import core


def user(text):
    return {'type': 'user', 'message': {'content': text}}


def assistant(text):
    return {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read'}, {'type': 'text', 'text': text}]}}


class CapturePrivacyTests(Base):
    def capture(self, *entries):
        core.claim(self.root, 'T-1', 'synthetic')
        path = self.root / 'privacy.jsonl'
        path.write_text('\n'.join(map(json.dumps, entries)))
        captured = core.capture_decisions(self.root, str(path))
        return captured, core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']

    def test_private_block_removed_across_lines_and_case(self):
        _, handoff = self.capture(
            user('We must keep the amber lane. <PRIVATE>we must use the hunter2 vault\nalways</Private> Never skip tests.'),
            assistant('Done. <private>internal codename</private> Next step: ship.'))
        self.assertIn('amber lane', handoff); self.assertIn('Never skip tests', handoff)
        self.assertNotIn('hunter2', handoff); self.assertNotIn('codename', handoff)

    def test_private_tag_and_command_skip_whole_message(self):
        _, handoff = self.capture(
            user('We must keep the amber lane.'),
            user('We must leak cobalt #private'),
            user('/private we must leak teal'),
            assistant('visible summary'),
            assistant('summary with #private zinc'))
        self.assertIn('amber lane', handoff)
        for word in ('cobalt', 'teal', 'zinc'):
            self.assertNotIn(word, handoff)

    def test_local_paths_become_tilde_and_workspace_dot(self):
        _, handoff = self.capture(
            user(f'We must edit {self.root}/src/a.py and /Users/alice/code/app/b.py and /home/bob/x.py '
                 f'and C:\\Users\\carol\\proj\\c.py, never touch src/Users/dave/d.py.'),
            assistant('Next step: open /Users/alice/notes.'))
        self.assertIn('./src/a.py', handoff); self.assertIn('~/code/app/b.py', handoff)
        self.assertIn('~/x.py', handoff); self.assertIn('~/proj/c.py', handoff)
        self.assertIn('src/Users/dave/d.py', handoff); self.assertIn('~/notes', handoff)
        for leak in ('alice', 'bob', 'carol', str(self.root)):
            self.assertNotIn(leak, handoff)

    def test_auth_headers_url_credentials_and_env_secrets_redacted(self):
        _, handoff = self.capture(user(
            'We must not log Authorization: Basic dXNlcjpwYXNz and https://bob:s3cret@example.com/x '
            'and STRIPE_SECRET_KEY=sk_abc and DB_PASSWORD="hunter2" and GH_TOKEN=ghp1 always.'),
            assistant('ok'))
        for leak in ('dXNlcjpwYXNz', 's3cret', 'sk_abc', 'hunter2', 'ghp1'):
            self.assertNotIn(leak, handoff)
        self.assertIn('example.com/x', handoff)

    def test_ordinary_words_not_over_redacted(self):
        self.assertEqual('Basic configuration. The token budget; key=ok PASSWORD policy.',
                         core.redact('Basic configuration. The token budget; key=ok PASSWORD policy.'))

    def test_capture_false_disables_and_doctor_reports(self):
        cfg = core.config(self.root); cfg['capture'] = False
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        captured, handoff = self.capture(user('We must keep amber.'), assistant('done'))
        self.assertFalse(captured); self.assertNotIn('amber', handoff)
        self.assertEqual('disabled_by_config', core.capture_health(self.root)['reason'])
