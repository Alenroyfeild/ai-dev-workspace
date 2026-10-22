import contextlib
import io
import sqlite3
from unittest import mock
from test_ws import Base
from ws import claude_mem, core
from testutil import run_ws


class ClaudeMemImportTests(Base):
    def setUp(self):
        super().setUp()
        self.root = self.root.resolve()
        self.db = (self.root.parent / 'source.db').resolve()
        with sqlite3.connect(str(self.db)) as db:
            db.execute('CREATE TABLE observations(id INTEGER PRIMARY KEY, project TEXT, type TEXT, created_at TEXT, title TEXT, narrative TEXT, facts TEXT)')
            for row in [(1, 'sample', 'decision', '2026-10-22', 'Use receipts', 'Keep checksum receipts.', '[]'),
                        (2, 'other', 'lesson', '2026-10-22', 'Other project', 'Do not import this.', '[]'),
                        (3, 'sample', 'lesson', '2026-10-22', 'Hidden', '#private excluded', '[]')]:
                db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?,?)', row)

    def test_preview_and_confirm_private_idempotent_source_unchanged(self):
        before = self.db.read_bytes()
        plan = claude_mem.import_store(self.root, self.db, 'sample')
        self.assertEqual(len(plan['items']), 1)
        self.assertFalse(list((core.vault(self.root) / 'Decisions').glob('*.md')))
        with mock.patch('builtins.input', return_value='n'), contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(claude_mem.import_store(self.root, self.db, 'sample', True)['saved'])
        with mock.patch('builtins.input', return_value='y'), contextlib.redirect_stdout(io.StringIO()):
            saved = claude_mem.import_store(self.root, self.db, 'sample', True)
        path = next((core.vault(self.root) / 'Decisions').glob('*.md'))
        self.assertIn('scope: private', path.read_text())
        self.assertIn('unverified', path.read_text())
        with mock.patch('builtins.input', return_value='y'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(claude_mem.import_store(self.root, self.db, 'sample', True)['saved'], saved['saved'])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertFalse(self.db.with_name('source.db-wal').exists())

    def test_source_changed_after_preview_and_wal_refuse(self):
        def change(_):
            with sqlite3.connect(str(self.db)) as db: db.execute("UPDATE observations SET narrative='Changed' WHERE id=1")
            return 'y'
        with mock.patch('builtins.input', side_effect=change), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(core.WsError):
            claude_mem.import_store(self.root, self.db, 'sample', True)
        self.db.with_name('source.db-wal').write_bytes(b'active WAL')
        with self.assertRaises(core.WsError): claude_mem.import_store(self.root, self.db, 'sample')

    def test_unknown_schema_and_privacy(self):
        with sqlite3.connect(str(self.db)) as db:
            db.execute('UPDATE observations SET narrative=? WHERE id=1',
                       ('Public <private>HIDDEN_123</private> ' + 'ghp_' + 'A1b2' * 10,))
        plan = claude_mem.import_store(self.root, self.db, 'sample')
        self.assertNotIn('HIDDEN_123', str(plan)); self.assertNotIn('ghp_', str(plan))
        with sqlite3.connect(str(self.db)) as db: db.execute('DROP TABLE observations')
        with self.assertRaises(core.WsError): claude_mem.import_store(self.root, self.db, 'sample')

    def test_cli_preview_then_confirm(self):
        args = ('import', 'claude-mem', '--db', str(self.db), '--project', 'sample')
        preview = run_ws(*args, cwd=self.root)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn('Use receipts', preview.stdout)
        saved = run_ws(*args, '--apply', cwd=self.root, input='y\n')
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertIn('scope: private', next((core.vault(self.root) / 'Decisions').glob('*.md')).read_text())
