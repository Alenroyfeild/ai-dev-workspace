import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ws import core, knowledge, sharing, team, team_sync
from testutil import rmtree_owned


class OnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The published team repo is read-only for every test, so build it once; each test links its own peer to it.
        cls.shared = Path(tempfile.mkdtemp()).resolve()
        cls.addClassCleanup(rmtree_owned, cls.shared, cls.shared)
        cls.host, cls.remote = cls.shared / 'host-memory', cls.shared / 'team.git'
        home = cls.shared / 'host-home'; home.mkdir()
        with mock.patch.dict(os.environ, HOME=str(home), USERPROFILE=str(home), WS_OFFLINE='1'):
            core.init(cls.host, 'host', clients=[])
            team._git(cls.shared, 'init', '--bare', '-q', str(cls.remote))
            team.manage(cls.host, 'init', str(cls.remote), apply=True, attest=True)
            for category, text in [('product', 'The product tracks household budgets.'),
                                   ('domain', 'Store totals as integer cents.'),
                                   ('repo', 'Storage tests live in the ledger directory.'),
                                   ('runbook', 'Unrelated deployment runbook.')]:
                item = knowledge.add(cls.host, text, category, True)
                sharing.apply(cls.host, sharing.preview(cls.host, item, author='teammate'))
            knowledge.add(cls.host, 'Hidden personal product plan.', 'product')
            team_sync.apply(cls.host, team_sync.preview(cls.host))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.addCleanup(rmtree_owned, self.base, self.base)
        self.peer = self.base / 'peer-memory'
        with self.home('peer'):
            core.init(self.peer, 'peer', clients=[])
            team.manage(self.peer, 'link', str(self.remote), apply=True, attest=True)

    def home(self, label):
        home = self.base / (label + '-home')
        home.mkdir(exist_ok=True)
        return mock.patch.dict(os.environ, HOME=str(home), USERPROFILE=str(home), WS_OFFLINE='1')

    def test_new_teammate_without_task_gets_three_categories_from_cards_without_writes(self):
        # Exercise Git's Windows CRLF checkout even on POSIX.
        for body in (self.peer / '.ws/team/entries').glob('*.md'):
            if not body.name.endswith('.index.md'):
                body.write_bytes(body.read_text().replace('\r\n', '\n').replace('\n', '\r\n').encode())
        # This test requires valid cards; CRLF changes their recorded byte size.
        for card in (self.peer / '.ws/team/entries').glob('*.index.md'):
            body = card.with_name(card.name.replace('.index.md', '.md'))
            body.write_bytes(body.read_text().replace('\r\n', '\n').encode())
            stamp = body.stat().st_mtime_ns + 1000000
            os.utime(card, ns=(stamp, stamp))
        before = {p: p.read_bytes() for p in self.peer.rglob('*') if p.is_file()}
        reader = core.read_text
        def cards_only(path, *args, **kwargs):
            if Path(path).parent.name == 'entries' and not str(path).endswith('.index.md'):
                raise AssertionError('orientation must use valid index cards')
            return reader(path, *args, **kwargs)
        with self.home('peer'), mock.patch.object(core, 'read_text', side_effect=cards_only):
            text = core.brief(self.peer)
        for phrase in ('household budgets', 'integer cents', 'ledger directory', 'untrusted', 'teammate'):
            self.assertIn(phrase, text)
        for phrase in ('Hidden personal', 'deployment runbook'):
            self.assertNotIn(phrase, text)
        self.assertLess(len(text.split()), 200)
        self.assertEqual(before, {p: p.read_bytes() for p in self.peer.rglob('*') if p.is_file()})

    def test_empty_branch_task_gets_orientation_then_private_decision_wins(self):
        with self.home('peer'):
            core.task_new(self.peer, 'feature-ledger', 'Ledger changes')
            core.claim(self.peer, 'feature-ledger', 'synthetic')
            self.assertIn('household budgets', core.brief(self.peer))
            core.remember(self.peer, 'Store totals as integer units.')
            text = core.brief(self.peer)
        self.assertIn('integer units', text)
        self.assertNotIn('integer cents', text)
        self.assertLess(len(text.split()), 200)

    def test_bad_team_identity_warns_without_exposing_source_text(self):
        manifest = self.peer / '.ws/team/team.json'
        record = json.loads(manifest.read_text()); record['id'] = 'wrong'
        manifest.write_text(json.dumps(record))
        with self.home('peer'):
            text = core.brief(self.peer)
        self.assertIn('Team warning:', text)
        self.assertNotIn('household budgets', text)

    def test_saved_next_action_switches_to_task_relevance(self):
        with self.home('peer'):
            core.task_new(self.peer, 'T1', 'Unrelated work')
            core.claim(self.peer, 'T1', 'synthetic')
            self.assertIn('household budgets', core.brief(self.peer))
            core.checkpoint(self.peer, 'T1', 'in_progress', 'Inspect the invoice exporter.')
            text = core.brief(self.peer)
        self.assertIn('Inspect the invoice exporter.', text)
        self.assertNotIn('household budgets', text)
        self.assertNotIn('Team product', text)

    def test_unlinked_workspace_keeps_existing_no_task_guidance(self):
        with self.home('peer'):
            plain = self.base / 'plain'
            core.init(plain, 'plain', clients=[])
            self.assertEqual(core.brief(plain), 'No in-progress task. Find or create the task before working.')

    def test_hook_created_branch_task_gets_orientation_until_something_is_saved(self):
        import subprocess
        subprocess.run(['git', '-C', str(self.peer), 'init', '-q', '-b', 'GR-88-feature'], check=True, capture_output=True)
        with self.home('peer'):
            task = core.session_task(self.peer, str(self.peer))
            self.assertIn('household budgets', core.brief(self.peer))
            core.remember(self.peer, 'Store totals as integer units.')
            self.assertNotIn('household budgets', core.brief(self.peer))
        self.assertTrue(task.startswith('BR-'))
