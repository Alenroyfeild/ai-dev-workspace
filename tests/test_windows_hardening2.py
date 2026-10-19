"""Second Windows audit (B2, B6, C4, C5), simulated on any OS; windows-latest runs the junction and symlink fixtures."""
import json
import os
import subprocess
import tempfile
import types
import unittest
from pathlib import Path, PureWindowsPath
from unittest import mock

from testutil import needs_symlinks
from test_ws import Base
from ws import core, orchestration, packs, team_folder, workers

MOUNT_POINT = 0xA0000003


def junction_lstat(fake, real=os.lstat):
    """os.lstat that reports `fake` as a Windows junction (mount-point reparse tag)."""
    def lstat(path, *args, **kwargs):
        if os.fspath(path) == os.fspath(fake): return types.SimpleNamespace(st_reparse_tag=MOUNT_POINT)
        return real(path, *args, **kwargs)
    return lstat


class JunctionTests(Base):
    def test_is_link_sees_a_junction_only_on_windows(self):
        folder = self.root / 'plain'; folder.mkdir()
        with mock.patch.object(core, 'WINDOWS', False): self.assertFalse(core.is_link(folder))
        with mock.patch.object(core, 'WINDOWS', True), mock.patch.object(os, 'lstat', junction_lstat(folder)):
            self.assertTrue(core.is_link(folder))
            self.assertFalse(core.is_link(self.root))
        with mock.patch.object(core, 'WINDOWS', False), mock.patch.object(os, 'lstat', junction_lstat(folder)): self.assertFalse(core.is_link(folder))

    def test_private_pack_refuses_a_junction_inside_it(self):
        pack = (self.root.parent / 'pack').resolve(); (pack / 'sub').mkdir(parents=True)
        (pack / 'pack.json').write_text(json.dumps(dict(name='p', version='1', kind='rules', description='d')))
        with mock.patch.object(core, 'WINDOWS', True), mock.patch.object(os, 'lstat', junction_lstat(pack / 'sub')):
            with self.assertRaises(core.WsError): packs.load(pack)

    @unittest.skipUnless(os.name == 'nt', 'mklink /J exists only on Windows')
    def test_real_junction_is_detected_and_refused_by_a_pack(self):
        pack = self.root.parent / 'jpack'; pack.mkdir(); outside = self.root.parent / 'jout'; outside.mkdir()
        (pack / 'pack.json').write_text(json.dumps(dict(name='p', version='1', kind='rules', description='d')))
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(pack / 'link'), str(outside)], check=True, capture_output=True)
        self.assertTrue(core.is_link(pack / 'link'))
        with self.assertRaises(core.WsError): packs.load(pack)


class DriveRedirectTests(Base):
    def test_mapped_and_subst_drives_are_recognized_by_drive_and_tail(self):
        W = PureWindowsPath
        self.assertTrue(team_folder._drive_redirect(W('Z:/team'), W('//srv/share/team')))
        self.assertTrue(team_folder._drive_redirect(W('X:/a/team'), W('C:/real/a/team')))
        self.assertFalse(team_folder._drive_redirect(W('C:/a/alias'), W('C:/a/shared')))  # same drive: a real symlink
        self.assertFalse(team_folder._drive_redirect(W('Z:/alias'), W('C:/other/shared')))  # different tail
        self.assertFalse(team_folder._drive_redirect(Path('/a/team'), Path('/b/a/team')))  # POSIX has no drives

    def folder(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); base = Path(tmp.name).resolve()
        real = base / 'shared'; real.mkdir(); (real / 'team.json').write_text(json.dumps(
            {'kind': 'ai-dev-workspace-team', 'schema_version': 1, 'id': 'a' * 32}))
        return base, real

    @needs_symlinks
    def test_snapshot_accepts_a_redirected_drive_but_not_a_symlink_alias(self):
        base, real = self.folder(); alias = base / 'alias'; alias.symlink_to(real, target_is_directory=True)
        with self.assertRaises(core.WsError): team_folder.snapshot(self.root, alias)
        with mock.patch.object(core, 'WINDOWS', True), self.assertRaises(core.WsError): team_folder.snapshot(self.root, alias)
        with mock.patch.object(core, 'WINDOWS', True), mock.patch.object(team_folder, '_drive_redirect', return_value=True):
            with self.assertRaises(core.WsError): team_folder.snapshot(self.root, alias)  # a link in the path is never a drive map
            with mock.patch.object(core, 'is_link', return_value=False): data = team_folder.snapshot(self.root, alias)
        self.assertEqual(data['source'], str(real))


class CmdShimTests(Base):
    binding = dict(executable=r'C:\npm\codex.CMD', model='gpt', effort='high', headless=['-C', '{repo}', '-'], prepare=None)

    def test_batch_shim_refuses_cmd_metacharacters_in_paths_and_prompts(self):
        with mock.patch.object(core, 'WINDOWS', True):
            for repo in (r'C:\work\R&D', r'C:\work\100%', r'C:\work\a^b', r'C:\work\a!b'):
                with self.assertRaises(core.WsError, msg=repo): orchestration.worker_command(self.binding, repo)
            self.assertEqual(orchestration.worker_command(self.binding, r'C:\work\R D')[1:], ['-C', r'C:\work\R D', '-'])
            prompt = dict(self.binding, headless=None, prepare=['--print', '{prompt}'])
            with self.assertRaises(core.WsError): orchestration.worker_command(prompt, r'C:\work', 'a & calc')
            with self.assertRaises(core.WsError): orchestration.worker_command(dict(self.binding, executable=r'C:\R&D\codex.cmd'), r'C:\work')

    def test_real_executables_and_other_systems_keep_such_paths(self):
        exe = dict(self.binding, executable=r'C:\bin\codex.exe')
        with mock.patch.object(core, 'WINDOWS', True): self.assertEqual(orchestration.worker_command(exe, r'C:\work\R&D')[2], r'C:\work\R&D')
        with mock.patch.object(core, 'WINDOWS', False): self.assertEqual(orchestration.worker_command(self.binding, '/work/R&D')[2], '/work/R&D')


class LongPathTests(Base):
    def test_long_path_prefixes_only_deep_windows_paths(self):
        deep = 'C:\\' + '\\'.join(['d' * 40] * 6) + '\\f.json'
        with mock.patch.object(core, 'WINDOWS', True), mock.patch.object(os.path, 'abspath', side_effect=lambda p: p):
            self.assertEqual(str(core.long_path(deep)), '\\\\?\\' + deep)
            self.assertEqual(str(core.long_path('\\\\srv\\share\\' + deep[3:])), '\\\\?\\UNC\\srv\\share\\' + deep[3:])
            self.assertEqual(str(core.long_path('\\\\?\\' + deep)), '\\\\?\\' + deep)
            self.assertEqual(str(core.long_path('C:\\short\\f.json')), 'C:\\short\\f.json')
        with mock.patch.object(core, 'WINDOWS', False): self.assertEqual(str(core.long_path(deep)), deep)  # not Windows

    def test_worker_git_enables_long_paths(self):
        with mock.patch.object(workers.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'', b'')) as run:
            workers.git(self.root, 'status')
        self.assertIn('core.longpaths=true', run.call_args[0][0])
