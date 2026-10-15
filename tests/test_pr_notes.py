import contextlib
import io
from pathlib import Path
from unittest import mock

from test_ws import Base
from ws import cli, core


class PrNotesTests(Base):
    def notes(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'pr-notes', *args]), 0)
        return output.getvalue()

    def test_golden_output_is_saved_explicit_text_only_and_read_only(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'review', 'Ask for review.', notes={
            'Handoff': 'Decision: Store integer cents.\nReason: Avoid rounding.\n\n'
                       '<!-- ws:captured:fixture -->\nDecision: Unverified guess.\n<!-- /ws:captured -->',
            'Checks': '- Storage tests passed (saved result).',
        })
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with mock.patch('subprocess.run', side_effect=AssertionError('no external command')), \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('no network')):
            self.assertEqual(self.notes('T-1'), (Path(__file__).parent / 'fixtures/pr-notes.md').read_text())
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_implicit_task_requires_one_local_claim_and_empty_fields_are_honest(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'pr-notes']), 2)
        core.claim(self.root, 'T-1', 'synthetic')
        text = self.notes()
        self.assertIn('T-1', text)
        self.assertEqual(text.count('Not recorded.'), 2)

    def test_private_text_and_secrets_are_not_printed(self):
        path = core.task_path(self.root, 'T-1')
        text = core.set_section(path.read_text(), 'Handoff',
                                'Decision: Use cents.\nReason: <private>hidden</private> precise.\n'
                                'Decision: internal #private\nDecision: API_KEY=abcd1234efgh5678ijkl')
        path.write_text(text)
        output = self.notes('T-1')
        self.assertIn('[REDACTED]', output)
        for omitted in ('hidden', 'internal', 'abcd1234efgh5678ijkl'):
            self.assertNotIn(omitted, output)

    def test_conflict_refuses_instead_of_printing_a_chosen_side(self):
        path = core.task_path(self.root, 'T-1')
        path.write_text(path.read_text() + '\n<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\n')
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'pr-notes', 'T-1']), 2)

    def test_malformed_capture_is_refused_instead_of_becoming_explicit(self):
        path = core.task_path(self.root, 'T-1')
        original = path.read_text()
        for capture in ('<!-- ws:captured:fixture -->\nDecision: Unverified guess.',
                        '### Captured today\nDecision: Unverified guess.\n<!-- /ws:captured -->',
                        '<!-- ws:captured:one --><!-- ws:captured:two -->\nDecision: Guess.\n<!-- /ws:captured -->',
                        '<!-- ws:captured:broken -->\nDecision: Old guess.\n'
                        '<!-- ws:captured:new -->\nDecision: New guess.\n<!-- /ws:captured -->'):
            with self.subTest(capture=capture):
                path.write_text(core.set_section(original, 'Handoff', capture))
                with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(['--workspace-root', str(self.root), 'pr-notes', 'T-1']), 2)

    def test_derived_source_metadata_is_redacted_too(self):
        import json
        secret = 'abcd1234efgh5678ijkl'
        name = 'API_KEY=' + secret
        (self.root / 'vault').rename(self.root / name)
        cfg = core.config(self.root); cfg['vault'] = name
        core.atomic_write(self.root / 'workspace.json', json.dumps(cfg))
        output = self.notes('T-1')
        self.assertIn('[REDACTED]', output)
        self.assertNotIn(secret, output)
