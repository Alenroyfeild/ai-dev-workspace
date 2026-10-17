from test_ws import Base
from ws import core


class RememberPrefixTests(Base):
    def test_typed_decision_prefix_is_not_doubled(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.remember(self.root, 'Decision: prices are integer cents', 'T-1')
        handoff = core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']
        self.assertIn('Decision: prices are integer cents', handoff)
        self.assertNotIn('Decision: Decision:', handoff + core.brief(self.root))
        with self.assertRaises(core.WsError): core.remember(self.root, 'Decision:   ', 'T-1')
