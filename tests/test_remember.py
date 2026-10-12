from test_ws import Base
from ws import core


class RememberTests(Base):
    def claim(self, task='T-1'):
        core.claim(self.root, task, 'synthetic')

    def handoff(self, task='T-1'):
        return core.task_read(self.root, task, ['Handoff'])['sections']['Handoff']

    def test_saves_into_claimed_task_and_shows_in_brief(self):
        self.claim()
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Write the schema.')
        self.assertEqual(core.remember(self.root, 'use Postgres, not SQLite')['task'], 'T-1')
        self.assertIn('Decision: use Postgres, not SQLite', self.handoff())
        self.assertIn('use Postgres, not SQLite', core.brief(self.root))

    def test_decision_survives_a_later_handoff_checkpoint(self):
        # /handoff rewrites the Handoff section; remembered decisions must not vanish with it.
        self.claim()
        core.remember(self.root, 'use Postgres, not SQLite')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Write the migration.', notes={'Handoff': 'Login done; migration next.'})
        self.assertIn('Decision: use Postgres, not SQLite', self.handoff())
        self.assertIn('Login done', self.handoff())
        self.assertIn('use Postgres, not SQLite', core.brief(self.root))

    def test_secret_is_redacted(self):
        self.claim()
        core.remember(self.root, 'use API_KEY=abcd1234efgh5678ijkl for the vendor')
        self.assertNotIn('abcd1234efgh5678ijkl', self.handoff())
        self.assertIn('[REDACTED]', self.handoff())

    def test_private_text_is_not_stored(self):
        self.claim()
        core.remember(self.root, 'use Postgres <private>for acme</private>')
        self.assertNotIn('acme', self.handoff())
        with self.assertRaises(core.WsError):
            core.remember(self.root, 'never ship Friday #private')
        with self.assertRaises(core.WsError):
            core.remember(self.root, '<private>only secret words</private>')
        self.assertNotIn('Friday', self.handoff())

    def test_no_claim_or_several_claims_explain_what_to_do(self):
        with self.assertRaisesRegex(core.WsError, r'ws claim <ID>.*--task'):
            core.remember(self.root, 'use Postgres')
        core.task_new(self.root, 'T-2', 'Other')
        self.claim(); self.claim('T-2')
        with self.assertRaisesRegex(core.WsError, r'--task'):
            core.remember(self.root, 'use Postgres')

    def test_task_override_and_unknown_task(self):
        core.remember(self.root, 'use Postgres', task_id='T-1')
        self.assertIn('use Postgres', self.handoff())
        with self.assertRaises(Exception):
            core.remember(self.root, 'use Postgres', task_id='NOPE-9')

    def test_decision_stays_above_captured_block_and_is_not_captured(self):
        self.claim()
        path = core.task_path(self.root, 'T-1')
        path.write_text(core.set_section(path.read_text(), 'Handoff',
            '<!-- ws:captured:abc -->\n### Captured 2026-01-01 (unverified transcript)\nUser constraints:\n- never x\n<!-- /ws:captured -->'))
        core.remember(self.root, 'use Postgres')
        text = self.handoff()
        self.assertLess(text.index('Decision: use Postgres'), text.index('ws:captured'))
        self.assertIn('Explicit Handoff (saved task record): Decision: use Postgres', core.brief(self.root))
