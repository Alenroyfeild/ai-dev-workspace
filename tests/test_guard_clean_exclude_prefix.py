"""git clean accepts unique prefixes of --exclude and consumes the next argument as the pattern; string-only probes."""
import os
import tempfile
import unittest
from unittest import mock

from ws import guards


class CleanExcludePrefixTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        environment = mock.patch.dict(os.environ, {'HOME': home.name, 'USERPROFILE': home.name,
                                                   'CODEX_HOME': os.path.join(home.name, '.codex')}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def check(self, command, denied):
        for wrapped in (command, 'env ' + command):
            with self.subTest(command=wrapped):
                self.assertEqual(bool(guards.command_reason(wrapped)), denied, wrapped)

    def test_prefix_consumes_next_argument(self):
        for command in ('git clean -f --e -n', 'git clean -f --ex -n', 'git clean -f --excl -n'): self.check(command, True)

    def test_prefix_with_real_dry_run_is_allowed(self):
        self.check('git clean -fn --e x', False)
        self.check('git clean -f --e x -n', False)

    def test_equals_form_keeps_next_argument(self):
        self.check('git clean -f --exclude=-n', True)
        self.check('git clean -f --e=-n', True)
