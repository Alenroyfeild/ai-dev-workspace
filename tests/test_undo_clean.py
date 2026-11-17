"""End-to-end deletion tests using disposable repositories and homes."""
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from testutil import needs_symlinks, run_ws, seeded_repo


KIT = Path(__file__).resolve().parents[1]


def snapshot_files(root):
    files = {}
    for path in root.rglob('*'):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            files[name] = ('symlink', os.readlink(path))
        elif path.is_file():
            files[name] = ('file', hashlib.sha256(path.read_bytes()).hexdigest())
    return files


class UndoCleanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / 'home'
        self.home.mkdir()
        (self.home / 'unrelated.txt').write_text('Keep this user file.\n', encoding='utf-8')
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('WS_', 'GIT_')) and key not in (
                        'CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'GEMINI_CLI_HOME', 'PYTHONPATH')}
        self.env.update(HOME=str(self.home), USERPROFILE=str(self.home), CODEX_HOME=str(self.home / '.codex'),
                        CLAUDE_CONFIG_DIR=str(self.home / '.claude'), XDG_CONFIG_HOME=str(self.home / '.config'),
                        APPDATA=str(self.home / '.config'), LOCALAPPDATA=str(self.home / '.local'),
                        PYTHONDONTWRITEBYTECODE='1', WS_OFFLINE='1')

    def make_repo(self, parent, name):
        project = self.base / parent / name
        project.mkdir(parents=True)
        seeded_repo(project, 'feature/undo-clean', {'README.md': 'Keep this tracked file.\n'})
        (project / '.git' / 'info' / 'exclude').write_text('user-private-file\n', encoding='utf-8')
        return project

    def ws(self, project, *args, answer=None):
        return subprocess.run([sys.executable, str(KIT / 'bin' / 'ws'), *args],
                              cwd=project, env=self.env, capture_output=True, text=True,
                              input=answer, timeout=120)

    def started(self, project, *args):
        run = self.ws(project, 'start', '--yes', *args)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_start_undo_and_documented_cleanup_leave_no_new_files(self):
        project = self.make_repo('one', "toy project's")
        before_home = snapshot_files(self.home)
        before_repo = snapshot_files(project)
        self.started(project)
        workspace = self.home / '.ai-dev-workspace' / project.name
        self.assertTrue((workspace / 'workspace.json').is_file())
        run = self.ws(project, 'start', '--undo', '--delete-memory', '--yes')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(str(workspace), run.stdout + run.stderr)
        self.assertRegex(run.stdout + run.stderr, r'1\s+task')
        self.assertEqual(snapshot_files(project), before_repo)
        self.assertEqual(snapshot_files(self.home), before_home)
        self.assertIn('ws start --undo --delete-memory',
                      (KIT / 'docs' / 'REPO-START.md').read_text(encoding='utf-8'))

    def test_decline_or_closed_input_leaves_everything_untouched(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        workspace = self.home / '.ai-dev-workspace' / project.name
        before_repo, before_home = snapshot_files(project), snapshot_files(self.home)
        for answer in ('n\n', ''):
            with self.subTest(answer=repr(answer)):
                run = self.ws(project, 'start', '--undo', '--delete-memory', answer=answer)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn(str(workspace), run.stdout + run.stderr)
                self.assertRegex(run.stdout + run.stderr, r'1\s+task')
                self.assertEqual(snapshot_files(project), before_repo)
                self.assertEqual(snapshot_files(self.home), before_home)

    def test_workspace_change_during_confirmation_keeps_new_file_and_repo_wiring(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        workspace = self.home / '.ai-dev-workspace' / project.name
        before_repo = snapshot_files(project)
        process = subprocess.Popen([sys.executable, str(KIT / 'bin' / 'ws'), 'start', '--undo', '--delete-memory'],
                                   cwd=project, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, bufsize=1)
        preview = process.stderr.readline()
        self.assertIn(str(workspace), preview)
        late = workspace / 'late-note.txt'
        late.write_text('Created while confirmation was open.\n', encoding='utf-8')
        stdout, stderr = process.communicate(input='y\n', timeout=120)
        self.assertNotEqual(process.returncode, 0, stdout + stderr)
        self.assertEqual(snapshot_files(project), before_repo)
        self.assertEqual(late.read_text(encoding='utf-8'), 'Created while confirmation was open.\n')

    @needs_symlinks
    def test_workspace_swapped_for_symlink_during_confirmation_does_not_write_outside(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        workspace = self.home / '.ai-dev-workspace' / project.name
        actual = workspace.with_name('saved-workspace')
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'keep.txt').write_text('External data.\n', encoding='utf-8')
        before_repo = snapshot_files(project)
        before_outside = snapshot_files(outside)
        process = subprocess.Popen([sys.executable, str(KIT / 'bin' / 'ws'), 'start', '--undo', '--delete-memory'],
                                   cwd=project, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, bufsize=1)
        preview = process.stderr.readline()
        self.assertIn(str(workspace), preview)
        workspace.rename(actual)
        workspace.symlink_to(outside, target_is_directory=True)
        before_actual = snapshot_files(actual)
        stdout, stderr = process.communicate(input='y\n', timeout=120)
        self.assertNotEqual(process.returncode, 0, stdout + stderr)
        self.assertEqual(snapshot_files(project), before_repo)
        self.assertEqual(snapshot_files(actual), before_actual)
        self.assertEqual(snapshot_files(outside), before_outside)

    def test_interactive_yes_removes_recorded_custom_workspace(self):
        project = self.make_repo('one', 'project')
        default = self.home / '.ai-dev-workspace' / project.name
        default.mkdir(parents=True)
        (default / 'keep.txt').write_text('Unrelated default memory.\n', encoding='utf-8')
        workspace = self.base / 'custom memory'
        self.started(project, '--workspace', str(workspace))
        run = self.ws(project, 'start', '--undo', '--delete-memory', answer='y\n')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn(str(workspace), run.stdout + run.stderr)
        self.assertFalse(workspace.exists())
        self.assertEqual((default / 'keep.txt').read_text(encoding='utf-8'), 'Unrelated default memory.\n')

    def test_same_named_repos_do_not_delete_each_others_memory(self):
        first = self.make_repo('one', 'same-name')
        second = self.make_repo('two', 'same-name')
        second_workspace = self.base / 'separate-memory'
        self.started(first)
        self.started(second, '--workspace', str(second_workspace))
        before_second = snapshot_files(second)
        before_memory = snapshot_files(second_workspace)
        run = self.ws(first, 'start', '--undo', '--delete-memory', '--yes')
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertFalse((self.home / '.ai-dev-workspace' / first.name).exists())
        self.assertEqual(snapshot_files(second), before_second)
        self.assertEqual(snapshot_files(second_workspace), before_memory)

    def test_another_repo_wired_to_workspace_refuses_before_undo(self):
        first = self.make_repo('one', 'same-name')
        second = self.make_repo('two', 'same-name')
        self.started(first)
        workspace = self.home / '.ai-dev-workspace' / first.name
        config_path = workspace / 'workspace.json'
        config = json.loads(config_path.read_text(encoding='utf-8'))
        config['repos'].append(str(second))
        config_path.write_text(json.dumps(config), encoding='utf-8')
        self.started(second, '--workspace', str(workspace))
        before_first = snapshot_files(first)
        before_second = snapshot_files(second)
        before_memory = snapshot_files(workspace)
        run = self.ws(first, 'start', '--undo', '--delete-memory', '--yes')
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('still wired', (run.stdout + run.stderr).lower())
        self.assertIn(str(workspace), run.stdout + run.stderr)
        self.assertRegex(run.stdout + run.stderr, r'\d+\s+task')
        self.assertEqual(snapshot_files(first), before_first)
        self.assertEqual(snapshot_files(second), before_second)
        self.assertEqual(snapshot_files(workspace), before_memory)

    @needs_symlinks
    def test_normal_start_preserves_support_for_internal_workspace_symlink(self):
        from ws import core

        project = self.make_repo('one', 'project')
        workspace = self.base / 'workspace'
        with mock.patch.dict(os.environ, self.env, clear=True):
            core.init(workspace, 'fixture', repos=[str(project)], clients=[])
        private = workspace / '.ws'
        internal = workspace / 'internal-storage'
        if private.exists():
            private.rename(internal)
        else:
            internal.mkdir()
        private.symlink_to(internal, target_is_directory=True)
        run = self.ws(project, 'start', '--yes', '--workspace', str(workspace))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertTrue((project / '.ws-start.json').is_file())
        self.assertTrue(private.is_symlink())

    def test_new_repo_registration_waits_for_workspace_deletion_guard(self):
        from ws import safe_delete

        first = self.make_repo('one', 'shared')
        second = self.make_repo('two', 'shared')
        self.started(first)
        workspace = self.home / '.ai-dev-workspace' / first.name
        config_path = workspace / 'workspace.json'
        config = json.loads(config_path.read_text(encoding='utf-8'))
        config['repos'].append(str(second))
        config_path.write_text(json.dumps(config), encoding='utf-8')
        marker = self.base / 'guard-attempted'
        script = (
            'import contextlib, os, pathlib, sys\n'
            'from ws import cli, repo\n'
            'owner = repo.safe_delete if os.name == "nt" else repo.core\n'
            'name = "guard" if os.name == "nt" else "lock"\n'
            'original = getattr(owner, name)\n'
            '@contextlib.contextmanager\n'
            'def observed(root):\n'
            '    pathlib.Path(sys.argv[1]).write_text("attempted")\n'
            '    with original(root): yield\n'
            'setattr(owner, name, observed)\n'
            'sys.exit(cli.main(["start", "--yes", "--workspace", sys.argv[2]]))\n'
        )
        env = dict(self.env, PYTHONPATH=str(KIT))
        with safe_delete.guard(workspace):
            process = subprocess.Popen([sys.executable, '-c', script, str(marker), str(workspace)],
                                       cwd=second, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            deadline = time.monotonic() + 30
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(marker.exists(), 'second start did not reach its registration guard')
            self.assertIsNone(process.poll())
            self.assertFalse((second / '.ws-start.json').exists())
        stdout, stderr = process.communicate(timeout=120)
        self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertTrue((second / '.ws-start.json').is_file())

    @needs_symlinks
    def test_workspace_symlinks_never_delete_external_files(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        workspace = self.home / '.ai-dev-workspace' / project.name
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'keep.txt').write_text('External data.\n', encoding='utf-8')
        (workspace / 'outside-link').symlink_to(outside, target_is_directory=True)
        run = self.ws(project, 'start', '--undo', '--delete-memory', '--yes')
        if run.returncode:
            self.assertTrue((workspace / 'workspace.json').is_file())
        else:
            self.assertFalse(workspace.exists())
        self.assertEqual((outside / 'keep.txt').read_text(encoding='utf-8'), 'External data.\n')

    @needs_symlinks
    def test_replaced_workspace_symlink_refuses_without_touching_repo(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        workspace = self.home / '.ai-dev-workspace' / project.name
        actual = workspace.with_name('saved-workspace')
        workspace.rename(actual)
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'keep.txt').write_text('External data.\n', encoding='utf-8')
        workspace.symlink_to(outside, target_is_directory=True)
        before_repo = snapshot_files(project)
        before_actual = snapshot_files(actual)
        run = self.ws(project, 'start', '--undo', '--delete-memory', '--yes')
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(snapshot_files(project), before_repo)
        self.assertEqual(snapshot_files(actual), before_actual)
        self.assertEqual((outside / 'keep.txt').read_text(encoding='utf-8'), 'External data.\n')

    @needs_symlinks
    def test_preview_scan_does_not_traverse_a_replaced_directory(self):
        from ws import safe_delete

        root = self.base / 'workspace'
        root.mkdir()
        (root / 'workspace.json').write_text('{}', encoding='utf-8')
        victim = root / 'victim'
        victim.mkdir()
        outside = self.base / 'external'
        outside.mkdir()
        (outside / 'keep.txt').write_text('External data.\n', encoding='utf-8')
        root_info = root.stat()
        outside_info = outside.stat()
        original = os.scandir
        replaced, traversed = [], []

        class SwapAfterScan:
            def __init__(self, scan):
                self.scan = scan

            def __enter__(self):
                entries = list(self.scan)
                victim.rmdir()
                victim.symlink_to(outside, target_is_directory=True)
                replaced.append(True)
                return iter(entries)

            def __exit__(self, *args):
                self.scan.close()

        def scanning(target):
            scan = original(target)
            info = os.fstat(target) if isinstance(target, int) else Path(target).stat()
            if (info.st_dev, info.st_ino) == (outside_info.st_dev, outside_info.st_ino):
                traversed.append(True)
            if not replaced and (info.st_dev, info.st_ino) == (root_info.st_dev, root_info.st_ino):
                return SwapAfterScan(scan)
            return scan

        with mock.patch.object(safe_delete.os, 'scandir', side_effect=scanning) as patched:
            with mock.patch.object(safe_delete.os, 'supports_fd', os.supports_fd | {patched}):
                try:
                    safe_delete.inspect(root)
                except OSError:
                    pass
        self.assertTrue(replaced)
        self.assertFalse(traversed)
        self.assertEqual((outside / 'keep.txt').read_text(encoding='utf-8'), 'External data.\n')

    @needs_symlinks
    def test_directory_replaced_by_symlink_during_deletion_keeps_external_data(self):
        from ws import safe_delete

        root = self.base / 'workspace'
        root.mkdir()
        (root / 'workspace.json').write_text('{}', encoding='utf-8')
        victim = root / 'victim'
        victim.mkdir()
        outside = self.base / 'external'
        outside.mkdir()
        sentinel = outside / 'keep.txt'
        sentinel.write_text('External data.\n', encoding='utf-8')
        _, identity, _ = safe_delete.inspect(root)
        root_info = root.stat()
        original = os.scandir
        replaced = []

        class SwapAfterScan:
            def __init__(self, scan):
                self.scan = scan

            def __enter__(self):
                entries = list(self.scan)
                victim.rmdir()
                victim.symlink_to(outside, target_is_directory=True)
                replaced.append(True)
                return iter(entries)

            def __exit__(self, *args):
                self.scan.close()

        def scanning(target):
            scan = original(target)
            info = os.fstat(target) if isinstance(target, int) else Path(target).stat()
            if not replaced and (info.st_dev, info.st_ino) == (root_info.st_dev, root_info.st_ino):
                return SwapAfterScan(scan)
            return scan

        with mock.patch.object(safe_delete.os, 'scandir', side_effect=scanning) as patched:
            supported = os.supports_fd | {patched}
            with mock.patch.object(safe_delete.os, 'supports_fd', supported):
                try:
                    safe_delete.remove(root, identity)
                except OSError:
                    pass
        self.assertTrue(replaced)
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'External data.\n')

    def test_new_file_during_deletion_is_not_removed(self):
        from ws import safe_delete

        root = self.base / 'workspace'
        root.mkdir()
        (root / 'workspace.json').write_text('{}', encoding='utf-8')
        victim = root / 'victim'
        victim.mkdir()
        _, identity, entries = safe_delete.inspect(root)
        root_info = root.stat()
        original = os.scandir
        inserted = []

        class AddAfterScan:
            def __init__(self, scan):
                self.scan = scan

            def __enter__(self):
                entries = list(self.scan)
                (victim / 'late.txt').write_text('Late data.\n', encoding='utf-8')
                inserted.append(True)
                return iter(entries)

            def __exit__(self, *args):
                self.scan.close()

        def scanning(target):
            scan = original(target)
            info = os.fstat(target) if isinstance(target, int) else Path(target).stat()
            if not inserted and (info.st_dev, info.st_ino) == (root_info.st_dev, root_info.st_ino):
                return AddAfterScan(scan)
            return scan

        with mock.patch.object(safe_delete.os, 'scandir', side_effect=scanning) as patched:
            with mock.patch.object(safe_delete.os, 'supports_fd', os.supports_fd | {patched}):
                with self.assertRaises(OSError):
                    safe_delete.remove(root, identity, entries)
        self.assertTrue(inserted)
        self.assertEqual((victim / 'late.txt').read_text(encoding='utf-8'), 'Late data.\n')

    def test_delete_memory_without_undo_is_refused_untouched(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        before_repo, before_home = snapshot_files(project), snapshot_files(self.home)
        run = self.ws(project, 'start', '--delete-memory', '--yes')
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(snapshot_files(project), before_repo)
        self.assertEqual(snapshot_files(self.home), before_home)

    def test_forged_workspace_inside_repo_is_not_deleted(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        original = self.home / '.ai-dev-workspace' / project.name
        nested = project / 'nested-memory'
        shutil.copytree(original, nested)
        record = project / '.ws-start.json'
        state = json.loads(record.read_text(encoding='utf-8'))
        state['workspace'] = str(nested)
        record.write_text(json.dumps(state), encoding='utf-8')
        before_repo, before_home = snapshot_files(project), snapshot_files(self.home)
        run = self.ws(project, 'start', '--undo', '--delete-memory', '--yes')
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(snapshot_files(project), before_repo)
        self.assertEqual(snapshot_files(self.home), before_home)

    def test_forged_home_workspace_refuses_before_undo(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        record = project / '.ws-start.json'
        state = json.loads(record.read_text(encoding='utf-8'))
        state['workspace'] = str(self.home)
        record.write_text(json.dumps(state), encoding='utf-8')
        (self.home / 'workspace.json').write_text(json.dumps({'repos': [str(project)]}), encoding='utf-8')
        before_repo, before_home = snapshot_files(project), snapshot_files(self.home)
        run = self.ws(project, 'start', '--undo', '--delete-memory', '--yes')
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(snapshot_files(project), before_repo)
        self.assertEqual(snapshot_files(self.home), before_home)

    @needs_symlinks
    def test_symlinked_manifest_is_not_followed_or_deleted(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        workspace = self.home / '.ai-dev-workspace' / project.name
        manifest = workspace / 'workspace.json'
        external = self.base / 'external-manifest.json'
        external.write_bytes(manifest.read_bytes())
        manifest.unlink()
        manifest.symlink_to(external)
        before_repo, before_home = snapshot_files(project), snapshot_files(self.home)
        before_external = external.read_bytes()
        run = self.ws(project, 'start', '--undo', '--delete-memory', '--yes')
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(snapshot_files(project), before_repo)
        self.assertEqual(snapshot_files(self.home), before_home)
        self.assertEqual(external.read_bytes(), before_external)

    def test_listed_repo_inside_workspace_is_not_deleted(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        workspace = self.home / '.ai-dev-workspace' / project.name
        nested = workspace / 'other-repo'
        nested.mkdir()
        seeded_repo(nested, 'feature/other', {'README.md': 'Other repository data.\n'})
        config_path = workspace / 'workspace.json'
        config = json.loads(config_path.read_text(encoding='utf-8'))
        config['repos'].append(str(nested))
        config_path.write_text(json.dumps(config), encoding='utf-8')
        before_repo, before_home = snapshot_files(project), snapshot_files(self.home)
        run = self.ws(project, 'start', '--undo', '--delete-memory', '--yes')
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(snapshot_files(project), before_repo)
        self.assertEqual(snapshot_files(self.home), before_home)
        self.assertEqual((nested / 'README.md').read_text(encoding='utf-8'), 'Other repository data.\n')

    def test_missing_other_repo_is_not_treated_as_unwired(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        workspace = self.home / '.ai-dev-workspace' / project.name
        config_path = workspace / 'workspace.json'
        config = json.loads(config_path.read_text(encoding='utf-8'))
        config['repos'].append(str(self.base / 'unavailable-repo'))
        config_path.write_text(json.dumps(config), encoding='utf-8')
        before_repo, before_home = snapshot_files(project), snapshot_files(self.home)
        run = self.ws(project, 'start', '--undo', '--delete-memory', '--yes')
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(snapshot_files(project), before_repo)
        self.assertEqual(snapshot_files(self.home), before_home)

    def test_preview_counts_each_task_file(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        workspace = self.home / '.ai-dev-workspace' / project.name
        tasks = workspace / 'vault' / 'Tasks'
        original = next(tasks.glob('*.md'))
        (tasks / 'another.md').write_bytes(original.read_bytes())
        run = self.ws(project, 'start', '--undo', '--delete-memory', answer='n\n')
        self.assertNotEqual(run.returncode, 0)
        self.assertIn(str(workspace), run.stdout + run.stderr)
        self.assertRegex(run.stdout + run.stderr, r'2\s+task')

    def test_delete_failure_reports_undo_and_preserves_remaining_memory(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        workspace = self.home / '.ai-dev-workspace' / project.name
        before_memory = snapshot_files(workspace)
        with mock.patch('ws.safe_delete.remove', side_effect=PermissionError('fixture failure')):
            run = run_ws('start', '--undo', '--delete-memory', '--yes', cwd=project, env=self.env)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('wiring was removed', run.stderr)
        self.assertIn(str(workspace), run.stderr)
        self.assertEqual(snapshot_files(workspace), before_memory)
        self.assertFalse((project / '.ws-start.json').exists())

    @needs_symlinks
    def test_lock_swapped_for_symlink_during_confirmation_never_writes_outside(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        workspace = self.home / '.ai-dev-workspace' / project.name
        lock = workspace / '.ws' / 'lock'
        outside = self.base / 'outside-lock'
        outside.write_text('External data.\n', encoding='utf-8')
        before_repo = snapshot_files(project)
        process = subprocess.Popen([sys.executable, str(KIT / 'bin' / 'ws'), 'start', '--undo', '--delete-memory'],
                                   cwd=project, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, bufsize=1)
        preview = process.stderr.readline()
        self.assertIn(str(workspace), preview)
        lock.unlink()
        lock.symlink_to(outside)
        stdout, stderr = process.communicate(input='y\n', timeout=120)
        self.assertNotEqual(process.returncode, 0, stdout + stderr)
        self.assertEqual(snapshot_files(project), before_repo)
        self.assertEqual(outside.read_text(encoding='utf-8'), 'External data.\n')

    def test_partial_undo_keeps_memory(self):
        project = self.make_repo('one', 'project')
        self.started(project)
        workspace = self.home / '.ai-dev-workspace' / project.name
        local = project / 'CLAUDE.local.md'
        local.write_text('User edited local instructions.\n', encoding='utf-8')
        before_memory = snapshot_files(workspace)
        run = self.ws(project, 'start', '--undo', '--delete-memory', '--yes')
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(local.read_text(encoding='utf-8'), 'User edited local instructions.\n')
        self.assertEqual(snapshot_files(workspace), before_memory)


if __name__ == '__main__':
    unittest.main()
