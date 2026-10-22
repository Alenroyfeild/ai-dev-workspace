import json

from test_ws import Base
from ws import core


class DigestKeySpanTests(Base):
    def test_key_body_never_reappears_in_selected_lines(self):
        body = 'SYNTHETIC_KEY_BODY_123456789'
        for label in ('PRIVATE KEY', 'RSA PRIVATE KEY', 'PGP PRIVATE KEY BLOCK'):
            for closed in (False, True):
                with self.subTest(label=label, closed=closed):
                    lines = ['public start', '-----BEGIN ' + label + '-----',
                             'error: ' + body, body, body]
                    if closed:
                        lines += ['-----END ' + label + '-----', 'error: public after']
                    raw = '\n'.join(lines) + '\n'
                    path = self.root / 'synthetic.log'
                    path.write_text(raw)
                    result = core.digest_file(path, root=self.root, focus='public')
                    self.assertNotIn(body, json.dumps(result))
                    self.assertEqual(core.digest_file(path, root=self.root, focus='KEY_BODY')['focus_matches'], [])
                    self.assertEqual(result['bytes'], len(raw))
                    self.assertEqual(result['lines'], raw.count('\n') + 1)
                    self.assertIn('L1: public start', result['focus_matches'])
                    if closed:
                        self.assertEqual(result['problems'], ['L7 (x1): error: public after'])
                        self.assertIn('L7: error: public after', result['focus_matches'])
                    else:
                        self.assertEqual(result['distinct_problem_lines'], 0)
