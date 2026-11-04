"""String-only guard probes; no destructive command is executed."""
import os
import tempfile
import unittest
from unittest import mock

from ws import guards


class FindGuardGapTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(); self.addCleanup(home.cleanup)
        patch = mock.patch.dict(os.environ, HOME=home.name, USERPROFILE=home.name)
        patch.start(); self.addCleanup(patch.stop)

    def test_destructive_find_on_root_or_home_is_denied(self):
        commands = ('find / -delete', 'find ~ -type f -delete',
                    'find "$HOME" -exec rm {} \\;',
                    'find ${HOME}/. -exec /bin/rm -f {} +',
                    'sudo find -H / -execdir env rm -f {} \\;',
                    'find -L ~ -name cache -o -delete',
                    'find -f / -delete', 'cd ~ && find . -delete',
                    'cd / && find -delete',
                    r'find / \( -name cache -o -delete \)')
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(guards.command_reason(command))

    def test_local_cleanup_and_nondestructive_find_stay_allowed(self):
        commands = ('find ./build -delete', 'find "$HOME/project/build" -delete',
                    'find ./build -exec rm {} \\;', 'find / -print',
                    'find / -name -delete -print', 'find / -exec echo -delete \\;',
                    'find / -printf -delete', 'find / -maxdepth 0 -print',
                    'find ./build -path / -delete',
                    'echo "find / -delete"', 'find / -exec printf rm \\;')
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(guards.command_reason(command), '')
    def test_bsd_traversal_flags_do_not_hide_find_roots(self):
        for option in ('-d', '-E', '-x', '-dsx'):
            with self.subTest(option=option):
                self.assertTrue(guards.command_reason(f'find {option} / -delete'))
                self.assertTrue(guards.command_reason(f'find {option} "$HOME" -exec rm {{}} \\;'))

    def test_bsd_find_local_cleanup_and_reads_stay_allowed(self):
        for command in ('find -dsx ./build -delete', 'find -E / -print',
                        'find -d / -name -delete -print'):
            with self.subTest(command=command):
                self.assertEqual(guards.command_reason(command), '')


class RemoteDeletionGuardTests(unittest.TestCase):
    def test_remote_deletion_is_denied_for_every_branch(self):
        commands = ('git push origin :main', 'git push origin :feature/topic',
                    'git push origin +:dev', 'git push origin :refs/heads/master',
                    'git push origin HEAD:feature :other',
                    'git push --delete origin main', 'git push origin --delete topic',
                    'git push origin -d feature', 'git push -du origin feature',
                    'sudo git -C repo push origin :topic',
                    'git push origin -- :topic', 'git push origin :topic -- -n')
        for command in commands:
            with self.subTest(command=command):
                reason = guards.command_reason(command)
                for text in ('deleted for everyone', 'gh pr merge --delete-branch',
                             'GitHub UI', 'WS_GUARDS=off'):
                    self.assertIn(text, reason)

    def test_dry_runs_updates_and_literal_data_are_allowed(self):
        commands = ('git push -n origin :main', 'git push origin --dry-run :topic',
                    'git push --delete origin topic --dry-run', 'git push -dn origin topic',
                    'git push -nd origin topic', 'git push origin -n -d feature',
                    'git push origin HEAD:main', 'git push origin :',
                    'git push origin -- -d', 'git push git@example.invalid:repo HEAD:main',
                    'echo "git push origin :main"')
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(guards.command_reason(command), '')
    def test_push_options_do_not_trip_remote_deletion_guard(self):
        commands = ('git push -odev origin main', 'git push -odraft origin main',
                    'git push -o -d origin main', 'git push --push-option -d origin main',
                    'git push --push-option=dev origin main')
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(guards.command_reason(command), '')
    def test_push_delete_flags_stay_denied(self):
        commands = ('git push -d origin feat', 'git push -fd origin feat',
                    'git push origin --delete feat')
        for command in commands:
            with self.subTest(command=command):
                reason = guards.command_reason(command)
                self.assertIn('deleted for everyone', reason)

    def test_push_unique_prefix_and_mirror_prune_are_denied(self):
        commands = (
            'git push origin --del feat',
            'git push origin --dele feat',
            'git push origin --delet feat',
            'git push origin --de feat',
            'git push --del origin feat',
            'git push --dele origin feat',
            'git push --prune origin',
            'git push --prune origin refs/heads/*:refs/heads/*',
            'git push --pru origin',
            'git push --prun origin',
            'git push --mirror origin',
            'git push --mir origin',
            'git push --m origin',
        )
        for command in commands:
            with self.subTest(command=command):
                reason = guards.command_reason(command)
                self.assertIn('deleted for everyone', reason)

    def test_push_ambiguous_prefixes_and_dry_runs_are_allowed(self):
        commands = (
            'git push --p origin main',
            'git push --pr origin main',
            'git push --d origin main',
            'git push origin main',
            'git push --push-option=dev origin main',
            'git push --porcelain origin main',
            'git push --progress origin main',
            'git push --del --dry-run origin feat',
            'git push -n --dele origin feat',
            'git push --mirror --dry-run origin',
            'git push -n --mirror origin',
            'git push --m -n origin',
            'git push --prune --dry-run origin',
            'git push -n --prune origin',
            'git push --pru -n origin',
            'git push --dry --prune origin',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(guards.command_reason(command), '')

    def test_guard_hunt_4_and_opposing_flags_and_config_bypasses_are_denied(self):
        commands = (
            ('git reset --h', 'throws away uncommitted work'),
            ('git reset -q --h', 'throws away uncommitted work'),
            ('git clean --forc', 'deletes untracked files'),
            ('git clean --for', 'deletes untracked files'),
            ('git clean --fo', 'deletes untracked files'),
            ('git clean --f', 'deletes untracked files'),
            ('git clean -d --forc', 'deletes untracked files'),
            ('rm --rec ~', 'delete your home folder'),
            ('rm --recurse ~', 'delete your home folder'),
            ('rm --r ~', 'delete your home folder'),
            ('rm -f --rec /', 'delete your home folder or the filesystem root'),
            ('git -c clean.requireForce=false clean', 'deletes untracked files'),
            ('git -c clean.requireForce=0 clean', 'deletes untracked files'),
            ('git -c clean.requireForce=no clean -d', 'deletes untracked files'),
            ('git -c clean.requireforce=off clean', 'deletes untracked files'),
            ('git push --dry-run --no-dry-run origin :feat', 'deleted for everyone'),
            ('git push -n --no-dry-run origin :feat', 'deleted for everyone'),
            ('git push --dry-run --no-dr origin :feat', 'deleted for everyone'),
            ('git push --dry-run --no-dry origin --delete feat', 'deleted for everyone'),
            ('git push --dry-run --no-dry-run origin --force', 'Force push rewrites shared history'),
            ('git -c remote.origin.mirror=true push origin', 'deleted for everyone'),
            ('git -c remote.origin.mirror=1 push origin', 'deleted for everyone'),
            ('git -c remote.origin.mirror push origin', 'deleted for everyone'),
            ('git -c remote.upstream.mirror=yes push upstream', 'deleted for everyone'),
            ('git -c remote.origin.push=+refs/heads/*:refs/heads/* push origin', 'Force push rewrites shared history'),
        )
        for command, expected in commands:
            with self.subTest(command=command):
                reason = guards.command_reason(command)
                self.assertIn(expected, reason)

    def test_guard_hunt_4_and_config_allow_controls(self):
        commands = (
            'git push --no-dry-run --dry-run origin :feat',
            'git push --no-dry-run -n origin :feat',
            'git push --no-dry-run --dry origin :feat',
            'git -c remote.origin.mirror=false push origin main',
            'git -c remote.origin.mirror=0 push origin main',
            'git -c clean.requireForce=true clean',
            'git -c clean.requireForce=false clean -n',
            'git -c clean.requireForce=false clean --dry-run',
            'git -c clean.requireForce=false clean --no-dry-run -n',
            'git clean -n',
            'git reset',
            'rm file.txt',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(guards.command_reason(command), '')

    def test_guard_hunt_5_groups_4_to_10_bypass_denials(self):
        cases = (
            ('R03', 'git -c Clean.RequireForce=true -c clean.requireforce=true -c Clean.RequireForce=false clean', 'deletes untracked files'),
            ('B14', 'git -c Clean.RequireForce=00 clean', 'deletes untracked files'),
            ('B15', 'git -c Clean.RequireForce=-0 clean', 'deletes untracked files'),
            ('B16', 'git -c Clean.RequireForce=+0 clean', 'deletes untracked files'),
            ('B_0k', 'git -c clean.requireForce=0k clean', 'deletes untracked files'),
            ('B_0x0', 'git -c clean.requireForce=0x0 clean', 'deletes untracked files'),
            ('B_space_0', 'git -c "clean.requireForce= 0" clean', 'deletes untracked files'),
            ('F02', 'git -c remote.fixture.dot.url=../sink.git -c remote.fixture.dot.push=+refs/heads/main:refs/heads/main push fixture.dot', 'Force push rewrites shared history'),
            ('F04', 'git -c remote.fixture.push=+refs/heads/main:refs/heads/main -c remote.fixture.push=refs/heads/victim:refs/heads/victim push fixture', 'Force push rewrites shared history'),
            ('F07', 'git -c remote.fixture.push=:refs/heads/victim push fixture', 'deleted for everyone'),
            ('F08', 'git -c remote.fixture.push=+refs/heads/main:refs/heads/main push --no-force fixture', 'Force push rewrites shared history'),
            ('F09', 'git -c remote.fixture.dot.url=../sink.git -c remote.fixture.dot.mirror=true push fixture.dot', 'deleted for everyone'),
            ('D08', 'git clean -f --dry-run --no-d', 'deletes untracked files'),
        )
        for probe_id, command, expected in cases:
            with self.subTest(probe_id=probe_id, command=command):
                reason = guards.command_reason(command)
                self.assertIn(expected, reason)

    def test_guard_hunt_5_controls_and_allowlist(self):
        allow_commands = (
            ('B09', 'git -c Clean.RequireForce=true clean'),
            ('B10', 'git -c Clean.RequireForce=yes clean'),
            ('B11', 'git -c Clean.RequireForce=on clean'),
            ('B12', 'git -c Clean.RequireForce=1 clean'),
            ('B13', 'git -c Clean.RequireForce clean'),
            ('R01', 'git -c clean.requireForce=false -c clean.requireForce=true clean'),
            ('R04', 'git -c Clean.RequireForce=false -c clean.requireforce=false -c Clean.RequireForce=true clean'),
            ('F06', 'git -c remote.unused.mirror=true push fixture main'),
            ('D02', 'git clean -f --dr'),
            ('D03', 'git clean -f --dry'),
            ('D04', 'git clean -f --dry-'),
            ('D05', 'git clean -f --dry-r'),
            ('D06', 'git clean -f --dry-ru'),
            ('D07', 'git clean -f --dry-run'),
        )
        for probe_id, command in allow_commands:
            with self.subTest(probe_id=probe_id, command=command):
                self.assertEqual(guards.command_reason(command), '')

        deny_commands = (
            ('F05', 'git -c remote.fixture.push=+refs/heads/main:refs/heads/main push fixture main', 'Force push rewrites shared history'),
            ('D01', 'git clean -f --d', 'deletes untracked files'),
        )
        for probe_id, command, expected in deny_commands:
            with self.subTest(probe_id=probe_id, command=command):
                reason = guards.command_reason(command)
                self.assertIn(expected, reason)
