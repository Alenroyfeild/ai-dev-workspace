import contextlib
import io
import time
from pathlib import Path
from test_ws import Base
from ws import cli, core, sharing


class NestedPrivateTests(Base):
    def test_nested_and_unclosed_private_spans_hide_everything_after_the_opener(self):
        for text, hidden in (('x <private>a <private>b</private> TAIL</private> y', 'TAIL'),
                             ('a <private>x</private> mid <private>y <private>z</private> TAIL', 'TAIL'),
                             ('use X <private>pw is <private>hunter</private> SECRETTAIL</private> done', 'SECRETTAIL')):
            with self.subTest(text):
                self.assertNotIn(hidden, core.strip_private(text))
                self.assertNotIn('private>', core.plain_text(text))
        self.assertEqual(core.strip_private('x <private>a <private>b</private> TAIL</private> y').split(), ['x', 'y'])
        self.assertEqual(core.strip_private('keep <PRIVATE>a</Private> this').split(), ['keep', 'this'])

    def test_remember_pr_notes_and_sharing_do_not_leak_the_tail(self):
        core.remember(self.root, 'use X <private>pw is <private>hunter</private> SECRETTAIL</private> done', 'T-1')
        handoff = core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']
        self.assertIn('use X', handoff); self.assertNotIn('SECRETTAIL', handoff); self.assertNotIn('</private>', handoff)
        self.assertNotIn('SECRETTAIL', core.pr_notes(self.root, 'T-1')['markdown'])
        self.assertNotIn('SECRETTAIL', sharing.derived(self.root, 'a <private>x <private>y</private> SECRETTAIL</private> b'))


class ReservedExistingTaskTests(Base):
    def test_existing_reserved_name_task_stays_usable_but_new_ones_are_refused(self):
        path = self.root / 'vault/Tasks/aux.md'
        path.write_text((self.root / 'vault/Tasks/T-1.md').read_text().replace('T-1', 'aux'))
        self.assertEqual(core.claim(self.root, 'aux', 'local')['task'], 'aux')
        core.checkpoint(self.root, 'aux', status='in_progress', next_action='go')
        self.assertEqual(core.task_read(self.root, 'aux', ['Handoff'])['meta']['status'], 'in_progress')
        with self.assertRaises(core.WsError):
            core.task_new(self.root, 'nul', 'New reserved')


class RedactSpeedTests(Base):
    def test_pathological_inputs_redact_quickly(self):
        for text in ('a-' * 50000, 'sk-' * 66000, '-----BEGIN PRIVATE KEY-----' * 7400):
            with self.subTest(text[:12]):
                start = time.monotonic(); core.redact(text)
                self.assertLess(time.monotonic() - start, 1.0)

    def test_redaction_still_covers_unterminated_keys_and_url_credentials(self):
        self.assertEqual(core.redact('x -----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY----- y'), 'x [REDACTED] y')
        two = '-----BEGIN PRIVATE KEY-----\nAAA\n-----BEGIN PRIVATE KEY-----\nBBB\n-----END PRIVATE KEY-----'
        self.assertNotRegex(core.redact(two), 'AAA|BBB')
        self.assertEqual(core.redact('no end -----BEGIN PRIVATE KEY----- here'), 'no end -----BEGIN PRIVATE KEY----- here')
        self.assertEqual(core.redact('a postgres://user:pw@host/db b'), 'a postgres://[REDACTED]@host/db b')
        self.assertEqual(core.redact('v1.2+x-y://u:p@h'), 'v1.2+x-y://[REDACTED]@h')


class BomTaskTests(Base):
    def test_task_file_with_bom_keeps_its_frontmatter(self):
        path = self.root / 'vault/Tasks/T-1.md'
        path.write_bytes(b'\xef\xbb\xbf' + path.read_bytes())
        self.assertEqual(core.task_read(self.root, 'T-1', ['Handoff'])['meta']['id'], 'T-1')
        self.assertEqual([t['status'] for t in core.task_list(self.root)], ['ready'])
        core.checkpoint(self.root, 'T-1', status='in_progress', next_action='go')
        self.assertEqual(core.task_read(self.root, 'T-1', ['Handoff'])['meta']['status'], 'in_progress')
        self.assertTrue(core.validate(self.root)['valid'], core.validate(self.root))


class Utf8ArgumentTests(Base):
    def test_lone_surrogate_argument_is_a_clean_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(['--workspace-root', str(self.root), 'remember', 'bad \ud800 x', '--task', 'T-1'])
        self.assertEqual(code, 2)
        self.assertIn('valid UTF-8', err.getvalue()); self.assertNotIn('Traceback', err.getvalue())


class PrivateReCallersTests(Base):
    def test_no_module_calls_private_re_sub(self):
        for path in (Path(core.__file__).parent).glob('*.py'):
            self.assertNotIn('PRIVATE_RE.sub', path.read_text(encoding='utf-8'), f'{path.name}: use core.strip_private()')
        self.assertIsNotNone(core.PRIVATE_RE)  # still importable for older branches
