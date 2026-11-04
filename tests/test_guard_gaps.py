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
