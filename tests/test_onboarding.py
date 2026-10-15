import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ws import core, knowledge, sharing, team, team_sync
from testutil import rmtree_owned


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.addCleanup(rmtree_owned, self.base, self.base)
        self.host, self.peer = self.base / 'host-memory', self.base / 'peer-memory'
        self.remote = self.base / 'team.git'
        with self.home('host'):
            core.init(self.host, 'host', clients=[])
            team._git(self.base, 'init', '--bare', '-q', str(self.remote))
            team.manage(self.host, 'init', str(self.remote), apply=True, attest=True)
            for category, text in [('product', 'The product tracks household budgets.'),
                                   ('domain', 'Store totals as integer cents.'),
                                   ('repo', 'Storage tests live in the ledger directory.'),
                                   ('runbook', 'Unrelated deployment runbook.')]:
                item = knowledge.add(self.host, text, category, True)
                sharing.apply(self.host, sharing.preview(self.host, item, author='teammate'))
            knowledge.add(self.host, 'Hidden personal product plan.', 'product')
            team_sync.apply(self.host, team_sync.preview(self.host))
        with self.home('peer'):
            core.init(self.peer, 'peer', clients=[])
            team.manage(self.peer, 'link', str(self.remote), apply=True, attest=True)

    def home(self, label):
        home = self.base / (label + '-home')
        home.mkdir(exist_ok=True)
        return mock.patch.dict(os.environ, HOME=str(home), USERPROFILE=str(home), WS_OFFLINE='1')

    def test_new_teammate_without_task_gets_three_categories_from_cards_without_writes(self):
        # Git checkout order can make a valid card look older than its body.
        for card in (self.peer / '.ws/team/entries').glob('*.index.md'):
            body = card.with_name(card.name.replace('.index.md', '.md'))
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

    def test_unlinked_workspace_keeps_existing_no_task_guidance(self):
        with self.home('peer'):
            plain = self.base / 'plain'
            core.init(plain, 'plain', clients=[])
            self.assertEqual(core.brief(plain), 'No in-progress task. Find or create the task before working.')
