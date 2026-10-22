import json
from unittest import mock
from test_ws import Base
import test_audit
from ws import audit


class AuditRecommendationTests(Base):
    make_repo = test_audit.AuditTests.make_repo

    def test_stack_and_each_detected_client_have_read_only_commands(self):
        repo = self.make_repo(**{'pyproject.toml': '[tool.pytest.ini_options]\n',
            'package.json': json.dumps({'scripts': {'test': 'echo DO_NOT_EXECUTE'}}),
            '.github/workflows/test.yml': 'name: tests\n', '.cursor/mcp.json': '{}', '.gemini/settings.json': '{}'})
        before = {p.relative_to(repo): p.read_bytes() for p in repo.rglob('*') if p.is_file()}
        original = audit.subprocess.run
        with mock.patch.object(audit.subprocess, 'run', wraps=original) as calls:
            report = audit.audit(repo)
        self.assertEqual(report['stack']['languages'], ['Python', 'JavaScript/TypeScript'])
        self.assertIn('python3 -m pytest', report['stack']['tests'])
        self.assertIn('npm test', report['stack']['tests'])
        self.assertEqual(report['stack']['ci'], ['GitHub Actions'])
        self.assertEqual({r['client'] for r in report['recommendations']}, {'cursor', 'gemini'})
        self.assertTrue(all('command' in row for row in report['recommendations']))
        self.assertTrue(all(call.args[0][0] == 'git' for call in calls.call_args_list))
        self.assertEqual(before, {p.relative_to(repo): p.read_bytes() for p in repo.rglob('*') if p.is_file()})
        self.assertNotIn('DO_NOT_EXECUTE', str(report))

    def test_unknown_stack_and_malformed_manifest_make_no_install_assumptions(self):
        repo = self.make_repo(**{'package.json': '{bad', '.codex/hooks.json': '{}'})
        report = audit.audit(repo)
        self.assertEqual(report['stack']['tests'], [])
        self.assertEqual({r['client'] for r in report['recommendations']}, {'codex'})
        self.assertNotIn('install', str(report['recommendations']).lower())

    def test_linked_clients_are_allowlisted_and_external_manifests_ignored(self):
        repo = self.make_repo(**{'.ws-start.json': '{}'})
        outside = self.root.parent / 'outside.json'
        outside.write_text('{"scripts":{"test":"secret"}}')
        try: (repo / 'package.json').symlink_to(outside)
        except OSError: self.skipTest('symlinks unavailable')
        with mock.patch('ws.core.find_root', return_value=self.root), mock.patch('ws.repo.load',
                return_value={'assistants': ['cursor', 'gemini', 'untrusted; command']}):
            report = audit.audit(repo)
        self.assertEqual(report['stack']['languages'], [])
        self.assertEqual([r['command'] for r in report['recommendations']], ['ws connect cursor', 'ws connect gemini'])
