import subprocess
import sys
from unittest import mock
from test_ws import Base
from ws import core
from mcp import server


class LessonContextTests(Base):
    def repo(self):
        repo = self.root / 'fixture'; repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        (repo / 'export.py').write_text('original\n')
        (repo / 'unrelated.py').write_text('unchanged\n')
        self.commit(repo)
        core.task_new(self.root, 'PATH-1', 'Publish daily output', repo=str(repo))
        core.claim(self.root, 'PATH-1', 'synthetic')
        core.checkpoint(self.root, 'PATH-1', 'in_progress', 'Finish output.')
        return repo

    def commit(self, repo):
        subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'fixture'], check=True)

    def test_changed_paths_since_claim_rank_above_title_only(self):
        repo = self.repo()
        for i in range(4): core.lesson_add(self.root, f'Publish daily output rule {i} avoids unrelated failures')
        core.lesson_add(self.root, 'Never rebuild cached receipts; reuse the exporter instead.', paths=['*.py'], area='serialization')
        before = core.brief(self.root)
        self.assertNotIn('Never rebuild', before)
        (repo / 'unicode-é.py').write_text('changed\n'); self.commit(repo)
        result = core.brief(self.root)
        self.assertIn('Never rebuild', result)
        self.assertLess(result.index('Never rebuild'), result.index('Publish daily output rule'))
        core.claim(self.root, 'PATH-1', 'synthetic')  # resuming retains the original commit
        self.assertIn('Never rebuild', core.brief(self.root))
        with mock.patch.object(core.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertNotIn('Never rebuild', core.brief(self.root))

    def test_cli_mcp_tags_are_validated_redacted_and_area_ranked(self):
        core.claim(self.root, 'T-1', 'synthetic'); core.checkpoint(self.root, 'T-1', 'in_progress', 'Continue.')
        reply = server.handle(self.root, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'add_lesson', 'arguments': {'text': 'Cached values expired; reuse stable receipts.', 'paths': ['src/*.py'], 'area': 'crash'}}})
        self.assertFalse(reply['result']['isError'])
        self.assertIn('Cached values expired', core.brief(self.root))
        proc = subprocess.run([sys.executable, str(core.KIT / 'bin/ws'), '--workspace-root', str(self.root), 'lesson', 'add', 'Hidden values leaked; redact all cached logs.', '--path', 'tests/*', '--area', 'token=syntheticsecret123456'], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = (core.vault(self.root) / 'Learnings.md').read_text()
        self.assertIn('tests/*', text); self.assertNotIn('syntheticsecret123456', text)
        for pattern in ('../outside/*', '/absolute/*', 'C:\\outside\\*'):
            with self.assertRaises(core.WsError): core.lesson_add(self.root, 'Invalid paths must be rejected.', paths=[pattern])
