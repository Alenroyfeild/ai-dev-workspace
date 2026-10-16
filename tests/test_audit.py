import json
import subprocess
from test_ws import Base
from ws import audit, core, repo as repo_setup


class AuditTests(Base):
    def make_repo(self, **files):
        repo = self.root.parent / 'app'; repo.mkdir()
        subprocess.run(['git', '-C', str(repo), 'init', '-q'], check=True)
        for name, body in files.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True); (repo / name).write_text(body)
        return repo

    def checks(self, report):
        return {c['check']: c for c in report['checks']}

    def test_bare_repo_lists_setup_fixes_first(self):
        report = audit.audit(self.make_repo())
        self.assertEqual(report['score'], '3/6')
        self.assertIn('Add AGENTS.md', report['fixes'][0])
        self.assertIn('Run ws start', report['fixes'][1])
        self.assertEqual(len(report['fixes']), 2)  # memory and hooks share one ws start fix

    def test_broken_references_and_size_are_reported(self):
        body = 'See @docs/build.md and [style](STYLE.md) and `src/app.py`; `README.md` exists.\n' + 'word ' * 2100
        repo = self.make_repo(**{'AGENTS.md': body, 'README.md': 'x', 'src/app.py': ''})
        checks = self.checks(audit.audit(repo))
        self.assertEqual(checks['References']['detail'], 'AGENTS.md: docs/build.md, AGENTS.md: STYLE.md')
        self.assertFalse(checks['Instruction size']['ok'])
        self.assertIn('words loaded every session', checks['Instruction size']['detail'])

    def test_urls_emails_and_globs_are_not_references(self):
        repo = self.make_repo(**{'CLAUDE.md': 'Mail a@b.com, see [site](https://x.invalid/a.md), `src/*.py`.\n'})
        self.assertTrue(self.checks(audit.audit(repo))['References']['ok'])

    def test_too_many_mcp_servers(self):
        servers = {f's{i}': {'command': 'x'} for i in range(6)}
        repo = self.make_repo(**{'.mcp.json': json.dumps({'mcpServers': servers}), '.codex/config.toml': '[mcp_servers.s0]\n[mcp_servers.extra]\n'})
        check = self.checks(audit.audit(repo))['MCP budget']
        self.assertEqual((check['ok'], check['detail']), (False, '7 servers'))

    def test_connected_repo_checks_hooks_and_stale_tasks(self):
        import io, os
        from contextlib import redirect_stdout, redirect_stderr
        from unittest import mock
        repo = self.make_repo(**{'AGENTS.md': 'Run tests.\n'})
        cwd = os.getcwd(); os.chdir(repo); self.addCleanup(os.chdir, cwd)
        with mock.patch('ws.setup.detect', return_value=[]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            repo_setup.start(yes=True)
        root = core.find_root(repo)
        core.task_new(root, 'S-1', 'Old work'); core.claim(root, 'S-1', 'synthetic'); core.checkpoint(root, 'S-1', 'in_progress', 'Finish.')
        path = core.vault(root) / 'Tasks/S-1.md'
        path.write_text(path.read_text().replace('\nupdated: ', '\nupdated: 2001-01-01T00:00:00Z\nwas: ', 1))
        before = sorted(p.name for p in repo.iterdir())
        checks = self.checks(audit.audit(repo))
        self.assertTrue(checks['Memory']['ok'])
        self.assertTrue(checks['Session hooks']['ok'], checks['Session hooks'])
        self.assertIn('S-1', checks['Stale tasks']['detail'])
        self.assertEqual(sorted(p.name for p in repo.iterdir()), before)  # read-only

    def test_text_is_shareable(self):
        out = audit.text(audit.audit(self.make_repo()))
        self.assertTrue(out.startswith('AI setup audit for app: 3/6'))
        self.assertNotIn(str(self.root.parent), out)
