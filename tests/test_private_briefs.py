"""Legacy task text and Git hunks must be filtered before reaching workers."""
import json
from pathlib import Path
from unittest import mock

from test_ws import Base
from testutil import seeded_repo
from ws import core, orchestration, workers


class PrivateBriefTests(Base):
    home = '/home/' + 'fixture-private-user'
    private = 'hidden fixture decision'

    def setUp(self):
        super().setUp()
        self.repo = self.root.parent / 'fixture-repo'
        self.repo.mkdir()
        seeded_repo(self.repo, 'feature/fixture', {'calc.py': 'answer = 1\n'})
        cfg = core.config(self.root)
        cfg['repos'] = [str(self.repo)]
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        core.task_new(self.root, 'P-1', 'Fixture', objective='Replace me', repo=str(self.repo))
        self.task = core.task_path(self.root, 'P-1')
        self.task.write_text(self.task.read_text().replace(
            'Replace me', f'Inspect {self.home}/notes and {Path.home().as_posix()}/memo\n'
            f'<private>{self.private}\nsecond private line</private>\nKeep this.'))

    def assert_filtered(self, brief):
        for value in (self.private, 'second private line', self.home, Path.home().as_posix(), '<private>'):
            self.assertNotIn(value, brief)
        self.assertIn('Inspect ~/notes', brief)
        self.assertIn('~/memo', brief)
        self.assertIn('Keep this.', brief)

    def test_delegate_uses_filtered_text_for_saved_brief_and_gateway(self):
        path = self.root / 'routing.json'
        routing = json.loads(path.read_text())
        routing['_ws_managed']['providers']['fixture'] = dict(
            kind='openai-compatible', base_url='http://127.0.0.1:1/v1', model='fixture')
        routing['role_overrides']['reviewer'] = {'preference': ['fixture']}
        path.write_text(json.dumps(routing))
        (self.repo / 'calc.py').write_text(f'answer = 2  # <private>diff-only canary</private> {self.home}/code\n')
        original = self.task.read_bytes()
        result = orchestration.delegate(self.root, 'P-1', 'reviewer', diff='HEAD')
        self.assertEqual(self.task.read_bytes(), original)
        with mock.patch('ws.orchestration.gateway.run', return_value=(0, 'calc.py:1: Fixture.', 0, 0, False)) as gateway:
            run = orchestration.delegate(self.root, 'P-1', 'reviewer', run=True, diff='HEAD')
        gateway.assert_called_once()
        payload = gateway.call_args.args[2]
        self.assertEqual(payload, Path(run['brief']).read_text(encoding='utf-8'))
        for brief in (payload, Path(result['brief']).read_text(encoding='utf-8')):
            with self.subTest(output=brief):
                self.assert_filtered(brief)
                self.assertNotIn(str(self.repo.resolve()), brief)
                self.assertNotIn('diff-only canary', brief)
                self.assertIn('~/code', brief)
                self.assertIn('answer = 2', brief)
                self.assertIn('## Allowed paths\n.', brief)

    def test_prepared_worker_brief_filters_legacy_sections_without_altering_task(self):
        core.claim(self.root, 'P-1', 'lead')
        original = self.task.read_bytes()
        with mock.patch('ws.orchestration.route', return_value=dict(provider='codex', model='fixture', effort='low', available=False)):
            result = workers.prepare(self.root, 'P-1', ['calc.py'], apply=True)
        brief = Path(result['brief']).read_text(encoding='utf-8')
        self.assert_filtered(brief)
        self.assertIn('## Allowed paths\ncalc.py', brief)
        self.assertEqual(self.task.read_bytes(), original)
