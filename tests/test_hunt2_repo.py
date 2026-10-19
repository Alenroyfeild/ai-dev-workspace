import contextlib
import io
import json
import shutil
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from ws import cli, core, repo as wsrepo


class Hunt2RepoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve(); self.home = self.base / 'home'; self.home.mkdir()
        self.repo = self.base / 'repo'; self.repo.mkdir()
        patch = mock.patch.dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home), CODEX_HOME=str(self.home / '.codex'), WS_OFFLINE='1', WS_ROOT='')
        patch.start(); self.addCleanup(patch.stop)
        self.git('init', '-q', '-b', 'feature/synthetic')
        (self.repo / 'pkg').mkdir(); (self.repo / 'pkg/a.txt').write_text('a\n')
        self.git('add', '.'); self.git('-c', 'user.name=F', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'fixture')
        self.old = Path.cwd(); os.chdir(self.repo); self.addCleanup(os.chdir, self.old)
        detection = mock.patch('ws.setup.detect', return_value=[]); detection.start(); self.addCleanup(detection.stop)

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.repo), *args], check=True, capture_output=True)

    def ws(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_start_from_subdirectory_refuses_tracked_files_like_the_root(self):
        self.mcp = b'{"mcpServers": {"mine": {"command": "x"}}}\n'
        (self.repo / '.mcp.json').write_bytes(self.mcp); self.git('add', '.mcp.json')
        os.chdir(self.repo / 'pkg')
        code, _, err = self.ws('start', '--yes')
        self.assertEqual(code, 2); self.assertIn('tracked', err)
        self.assertEqual((self.repo / '.mcp.json').read_bytes(), self.mcp)
        self.assertFalse((self.repo / '.ws-start.json').exists())

    def test_moved_repo_can_be_relinked_by_start_and_undone(self):
        self.assertEqual(self.ws('start', '--yes')[0], 0)
        moved = self.base / 'moved'; self.repo.rename(moved); os.chdir(moved); self.repo = moved
        code, _, err = self.ws('start', '--yes')
        self.assertEqual(code, 0, err)
        root = core.find_root(moved)
        self.assertEqual(core.config(root)['repos'], [str(moved)])
        self.assertIn('/.ws-start.json', (moved / '.git/info/exclude').read_text())
        self.assertEqual(self.ws('start', '--undo')[0], 0)
        self.assertFalse((moved / '.ws-start.json').exists())
        self.assertNotIn('ws:start', (moved / '.git/info/exclude').read_text())

    def test_moved_repo_undo_works_from_the_new_location(self):
        self.assertEqual(self.ws('start', '--yes')[0], 0)
        moved = self.base / 'moved'; self.repo.rename(moved); os.chdir(moved); self.repo = moved
        code, _, err = self.ws('start', '--undo')
        self.assertEqual(code, 0, err)
        self.assertNotIn('ws:start', (moved / '.git/info/exclude').read_text())

    def test_branch_with_line_separator_is_refused_before_any_write(self):
        self.git('checkout', '-q', '-b', 'feat x')
        for _ in range(2):  # a rerun must not report success either
            code, _, err = self.ws('start', '--yes')
            self.assertEqual(code, 2); self.assertIn('line break', err)
            self.assertFalse((self.repo / '.ws-start.json').exists())
            self.assertFalse((self.repo / 'CLAUDE.local.md').exists())

    def test_relink_drops_only_the_moved_from_path_and_keeps_a_missing_other_repo(self):
        self.assertEqual(self.ws('start', '--yes')[0], 0)
        root = core.find_root(self.repo); cfg = core.config(root)
        away = str(self.base / 'unmounted-drive' / 'other'); cfg['repos'].append(away)
        (root / 'workspace.json').write_text(json.dumps(cfg))
        moved = self.base / 'moved'; self.repo.rename(moved); os.chdir(moved); self.repo = moved
        self.assertEqual(self.ws('start', '--yes')[0], 0)
        self.assertEqual(core.config(root)['repos'], [away, str(moved)])

    def test_copied_repo_with_symlinked_exclude_is_refused_and_original_untouched(self):
        self.assertEqual(self.ws('start', '--yes')[0], 0)
        original = self.repo / '.git/info/exclude'; before = original.read_bytes()
        copied = self.base / 'copy'; shutil.copytree(self.repo, copied, ignore=shutil.ignore_patterns('*.lock'))
        link = copied / '.git/info/exclude'; link.unlink(); link.symlink_to(original)
        os.chdir(copied); self.repo = copied
        for args in (('start', '--undo'), ('start', '--yes')):
            code, _, err = self.ws(*args)
            self.assertEqual(code, 2, args); self.assertIn('symlink', err)
            self.assertEqual(original.read_bytes(), before)
        self.assertNotIn(str(copied), core.config(core.find_root(self.base / 'repo'))['repos'])

    def test_interrupted_relink_is_finished_by_a_retry_and_undo_works(self):
        self.assertEqual(self.ws('start', '--yes')[0], 0)
        old = self.repo; moved = self.base / 'moved'; old.rename(moved); os.chdir(moved); self.repo = moved
        root = Path(wsrepo.load(moved)['workspace']); real = core.atomic_write
        def stop(path, data):
            if Path(path) == moved / wsrepo.LINK: raise OSError('synthetic interruption after config write')
            return real(path, data)
        with mock.patch.object(core, 'atomic_write', side_effect=stop): self.assertNotEqual(self.ws('start', '--yes')[0], 0)
        self.assertIn(str(moved), core.config(root)['repos'])
        self.assertEqual(wsrepo.load(moved)['exclude'], str(old / '.git/info/exclude'))
        code, _, err = self.ws('start', '--yes'); self.assertEqual(code, 0, err)
        self.assertEqual(wsrepo.load(moved)['exclude'], str(moved / '.git/info/exclude'))
        self.assertEqual(core.config(root)['repos'], [str(moved)])
        code, _, err = self.ws('start', '--undo'); self.assertEqual(code, 0, err)
        self.assertNotIn('ws:start', (moved / '.git/info/exclude').read_text())
