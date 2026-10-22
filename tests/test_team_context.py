import json
import unittest
from unittest import mock
import test_sharing
from ws import core, knowledge, sharing
from mcp import server


class TeamContextTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def shared(self, text):
        item = knowledge.add(self.root, text, 'repo', True)
        plan = sharing.preview(self.root, item, author='teammate')
        sharing.apply(self.root, plan)
        return plan

    def test_brief_reads_relevant_card_with_provenance_without_body_or_writes(self):
        plan = self.shared('The receipt verifier expects a checksum field.')
        source = self.clone/plan['destination']
        core.checkpoint(self.root, 'T1', 'in_progress', 'Inspect the receipt verifier.')
        before = {p:p.read_bytes() for p in self.root.rglob('*') if p.is_file() and '.git' not in p.parts}
        reader = core.read_text
        def no_body(path, *args, **kwargs):
            if path == source: raise AssertionError('brief must use the valid card')
            return reader(path, *args, **kwargs)
        with mock.patch('ws.core.read_text', side_effect=no_body): text = core.brief(self.root)
        self.assertIn('checksum', text); self.assertIn('untrusted', text)
        for value in ('teammate', plan['date'][:10]): self.assertIn(value, text)
        for value in (plan['entry'], plan['source_sha'][:8]): self.assertNotIn(value, text)
        self.assertLess(len(text.split()), 200)
        self.assertEqual(before, {p:p.read_bytes() for p in before})

    def test_private_decision_suppresses_potentially_conflicting_team_fact(self):
        self.shared('The rollout lane is old-lane and the receipt is old-receipt.')
        core.checkpoint(self.root, 'T1', 'in_progress', 'Finish the rollout.')
        core.remember(self.root, 'The rollout lane is new-lane and the receipt is new-receipt.')
        text = core.brief(self.root)
        self.assertIn('new-lane', text); self.assertNotIn('old-lane', text)
        self.assertIn('private memory wins', text)

    def test_unrelated_team_text_and_conflicted_source_do_not_become_context(self):
        plan = self.shared('Astronomy star catalog facts.')
        core.checkpoint(self.root, 'T1', 'in_progress', 'Inspect the receipt verifier.')
        self.assertNotIn('Astronomy', core.brief(self.root))
        source = self.clone/plan['destination']
        source.write_text(source.read_text()+'\n<<<<<<< a\nreceipt\n=======\nother\n>>>>>>> b\n')
        text = core.brief(self.root)
        self.assertNotIn('Astronomy', text); self.assertIn('Team warning:', text)

    def test_search_and_mcp_include_team_with_private_first_and_untrusted_label(self):
        self.shared('The receipt verifier needs a checksum. ' * 8)
        core.checkpoint(self.root, 'T1', 'in_progress', 'Inspect the receipt verifier.')
        core.remember(self.root, 'Use the local receipt verifier.')
        for results in (core.search(self.root, 'receipt'), core.search(self.root, 'receipt', category='repo')):
            self.assertTrue(any(r.get('layer') == 'team' for r in results))
            team = next(r for r in results if r.get('layer') == 'team')
            self.assertTrue(team['untrusted']); self.assertEqual(team['precedence'], 'private')
            self.assertNotEqual(results[0].get('layer'), 'team')
        for name, args in [('brief', {}), ('search_vault', {'query':'receipt'})]:
            reply = server.handle(self.root, {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}})
            self.assertFalse(reply['result']['isError'])
            self.assertIn('untrusted', reply['result']['content'][0]['text'])
            if name == 'brief': self.assertIn('checksum', reply['result']['content'][0]['text'])

    def test_long_private_checkpoint_keeps_correction_and_budget(self):
        for i in range(3): self.shared('The receipt checksum needs validation. ' * 15)
        core.checkpoint(self.root, 'T1', 'in_progress', 'Validate receipt checksums. ' * 20,
            notes={'Handoff':'Background context. '*80+'\nDecision: keep the revised lane.', 'Blockers':'Waiting for review. '*15})
        text=core.brief(self.root)
        self.assertIn('revised lane', text); self.assertLess(len(text.split()),200)

    def test_default_search_can_open_uncached_ordinary_team_task_on_demand(self):
        path = core.task_path(self.root, 'T1')
        text = core.set_section(path.read_text(), 'Objective', 'background '*40+' quokkaretry marker')
        path.write_text(text)
        plan = sharing.preview(self.root, 'task:T1'); sharing.apply(self.root, plan)
        hits = core.search(self.root, 'quokkaretry')
        self.assertTrue(any(h.get('layer') == 'team' for h in hits))

    def test_related_partial_overlap_card_follows_private_decision(self):
        self.shared('The receipt verifier needs a checksum.')
        core.checkpoint(self.root,'T1','in_progress','Inspect the receipt verifier.')
        core.remember(self.root,'Use the local receipt verifier.')
        text=core.brief(self.root)
        self.assertIn('checksum',text);self.assertIn('untrusted',text)
        self.assertLess(text.index('Decision: Use the local receipt verifier.'),text.index('checksum'))
        self.assertLess(len(text.split()),200)
