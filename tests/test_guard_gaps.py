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
