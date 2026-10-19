import json
import time

from test_ws import Base
from ws import core


class PgpKeyTests(Base):
    def test_pgp_private_key_block_is_redacted(self):
        key = '-----BEGIN PGP PRIVATE KEY BLOCK-----\nlQdGBF4PGPBODY\n-----END PGP PRIVATE KEY BLOCK-----'
        out = core.redact(f'before {key} after')
        self.assertNotIn('PGPBODY', out)
        self.assertEqual(out, 'before [REDACTED] after')
        self.assertIsNotNone(core.SECRET_RE.search(key))

    def test_pgp_block_without_end_hides_the_rest(self):
        self.assertNotIn('PGPBODY', core.redact('-----BEGIN PGP PRIVATE KEY BLOCK-----\nPGPBODY'))


class JwtLinearTests(Base):
    def test_repeated_jwt_prefix_is_not_quadratic(self):
        start = time.monotonic()
        core.redact('eyJ-' * 100_000)  # 400 KB; was ~57 s
        self.assertLess(time.monotonic() - start, 3)

    def test_normal_jwt_is_still_redacted(self):
        jwt = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk'
        self.assertEqual(core.redact(f'auth {jwt} done'), 'auth [REDACTED] done')
        big = 'eyJhbGciOiJIUzI1NiJ9.eyJ' + 'a' * 6000 + '.sig'
        self.assertEqual(core.redact(big), '[REDACTED]')


class PrivateSpanTests(Base):
    def _handoff(self, text):
        path = core.task_path(self.root, 'T-1')
        raw = core.set_section(path.read_text(), 'Handoff', text)
        path.write_text(core.set_meta(raw, {'updated': core.now()}))

    def test_multiline_private_span_does_not_leak_into_pr_notes_or_recap(self):
        self._handoff('Notes: <private>\nDecision: SECRETD discount\nReason: SECRETR term\n</private>\nDecision: public choice PUBLICD')
        for out in (core.pr_notes(self.root, 'T-1')['markdown'], json.dumps(core.recap(self.root)), core.recap(self.root)['markdown']):
            self.assertNotIn('SECRETD', out); self.assertNotIn('SECRETR', out)
            self.assertIn('PUBLICD', out)

    def test_tag_variants_are_private_tags(self):
        for opener, closer in (('<private x=1>', '</private>'), ('<private >', '</private>'), ('< private>', '</ private>'), ('<PRIVATE\tx>', '< / private >')):
            with self.subTest(opener):
                self.assertEqual(core.strip_private(f'a {opener}LEAK{closer} b', ''), 'a  b')
                self.assertNotIn('LEAK', core.plain_text(f'a {opener}LEAK{closer} b'))
        self.assertEqual(core.strip_private('a <privately>keep</privately> b', ''), 'a <privately>keep</privately> b')

    def test_variants_do_not_reach_remember_pr_notes_or_recap(self):
        core.remember(self.root, 'B <private x=1>LEAKTWO</private> b', 'T-1')
        core.remember(self.root, 'A < private >LEAKONE</ private > a', 'T-1')
        for out in (core.pr_notes(self.root, 'T-1')['markdown'], core.recap(self.root)['markdown']):
            self.assertNotIn('LEAK', out)

    def test_tag_regex_is_not_quadratic(self):
        for text in ('<private ' * 50_000, '<' + ' ' * 200_000):
            start = time.monotonic()
            core.strip_private(text)
            self.assertLess(time.monotonic() - start, 3)
