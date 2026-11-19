"""GUARD-HUNT-5 groups 1-3: string-only probes; never execute payloads."""
import os
import shlex
import tempfile
import unittest
from unittest import mock

from ws import guards


class GitConfigAliasTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        environment = mock.patch.dict(os.environ, {
            'HOME': home.name, 'USERPROFILE': home.name,
            'CODEX_HOME': os.path.join(home.name, '.codex'),
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def deny(self, command):
        commands = (command,) if command.startswith('env ') else (command, 'env ' + command)
        for wrapped in commands:
            with self.subTest(command=wrapped):
                self.assertTrue(guards.command_reason(wrapped), wrapped)

    def allow(self, command):
        for wrapped in (command, 'env ' + command):
            with self.subTest(command=wrapped):
                self.assertEqual(guards.command_reason(wrapped), '', wrapped)

    def test_C01_config_env_false(self):
        self.deny('FLAG=false git --config-env=clean.requireForce=FLAG clean')

    def test_C03_config_env_empty(self):
        self.deny("FLAG='' git --config-env=clean.requireForce=FLAG clean")

    def test_C07_config_env_forced_refspec(self):
        self.deny('FLAG=+refs/heads/main:refs/heads/main git --config-env=remote.fixture.push=FLAG push fixture')

    def test_C09_config_env_separate_argument(self):
        self.deny('FLAG=false git --config-env clean.requireForce=FLAG clean')

    def test_E01_count_clean(self):
        self.deny('GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=clean.requireForce GIT_CONFIG_VALUE_0=false git clean')

    def test_E02_count_mirror(self):
        self.deny('GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=remote.fixture.mirror GIT_CONFIG_VALUE_0=true git push fixture')

    def test_E03_count_forced_refspec(self):
        self.deny('GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=remote.fixture.push GIT_CONFIG_VALUE_0=+refs/heads/main:refs/heads/main git push fixture')

    def test_E04_count_repeated_key(self):
        self.deny('GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=clean.requireForce GIT_CONFIG_VALUE_0=true GIT_CONFIG_KEY_1=clean.requireForce GIT_CONFIG_VALUE_1=false git clean')

    def test_E06_env_wrapper(self):
        self.deny('env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=clean.requireForce GIT_CONFIG_VALUE_0=false git clean')

    def parameters(self, value, command):
        self.deny('GIT_CONFIG_PARAMETERS=' + shlex.quote(value) + ' git ' + command)

    def test_E07_parameters_clean(self):
        self.parameters("'clean.requireForce=false'", 'clean')

    def test_E08_parameters_mirror(self):
        self.parameters("'remote.fixture.mirror=true'", 'push fixture')

    def test_E09_parameters_forced_refspec(self):
        self.parameters("'remote.fixture.push=+refs/heads/main:refs/heads/main'", 'push fixture')

    def test_E10_parameters_repeated_key(self):
        self.parameters("'clean.requireForce=true' 'clean.requireForce=false'", 'clean')

    def test_A01_reset_alias(self):
        self.deny("git -c 'alias.x=reset --hard' x")

    def test_A02_clean_alias(self):
        self.deny("git -c 'alias.x=clean -f' x")

    def test_A03_force_push_alias(self):
        self.deny("git -c 'alias.x=push --force fixture main' x")

    def test_A04_delete_push_alias(self):
        self.deny("git -c 'alias.x=push --delete fixture victim' x")

    def test_A05_shell_alias(self):
        self.deny("git -c 'alias.x=!rm -rf ~' x")

    def test_A08_alias_chain(self):
        self.deny("git -c alias.x=y -c 'alias.y=reset --hard' x")

    # Policy controls: guarded env config is denied even if Git itself would refuse.
    def test_C02_guarded_config_env_true_still_denied(self):
        self.deny('FLAG=true git --config-env=clean.requireForce=FLAG clean')

    def test_C04_missing_config_env_value_is_denied(self):
        self.deny('git --config-env=clean.requireForce=UNSET_FLAG clean')

    def test_E05_explicit_safe_override_does_not_allow_env_config(self):
        self.deny('GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=clean.requireForce GIT_CONFIG_VALUE_0=false git -c clean.requireForce=true clean')

    def test_A06_status_alias_is_allowed(self):
        self.allow("git -c 'alias.x=status --short' x")

    def test_A07_dry_run_alias_is_allowed(self):
        self.allow("git -c 'alias.x=push --force --dry-run fixture main' x")

    def test_guarded_env_alias_and_both_config_env_forms_are_denied(self):
        self.deny("FLAG='reset --hard' git --config-env=alias.x=FLAG x")
        self.deny("FLAG='reset --hard' git --config-env alias.x=FLAG x")
        self.deny("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.x GIT_CONFIG_VALUE_0='reset --hard' git x")
        self.parameters("'alias.x=reset --hard'", 'x')

    def test_unknown_inline_config_is_denied(self):
        self.deny('FLAG=$VALUE git --config-env=clean.requireForce=FLAG clean')
        self.deny('GIT_CONFIG_COUNT=$COUNT GIT_CONFIG_KEY_0=$KEY GIT_CONFIG_VALUE_0=$VALUE git clean')
        self.deny('GIT_CONFIG_PARAMETERS=$CONFIG git clean')

    def test_alias_loop_and_unexpandable_aliases_are_denied(self):
        self.deny('git -c alias.x=y -c alias.y=x x')
        self.deny('git -c alias.x=y x')
        self.deny('git -c alias.x= x')
        self.deny('git -c ' + shlex.quote("alias.x='unterminated") + ' x')

    def test_five_alias_expansions_are_allowed_but_six_are_denied(self):
        five = "git -c alias.a=b -c alias.b=c -c alias.c=d -c alias.d=e -c 'alias.e=status --short' a"
        six = "git -c alias.a=b -c alias.b=c -c alias.c=d -c alias.d=e -c alias.e=f -c 'alias.f=status --short' a"
        self.allow(five)
        self.deny(six)

    def test_alias_arguments_reach_existing_checker(self):
        self.deny('git -c alias.x=reset x --hard')
        self.allow('git -c alias.x=clean x -n')

    def test_unused_alias_and_benign_shell_alias_are_allowed(self):
        self.allow("git -c 'alias.x=reset --hard' status --short")
        self.allow("git -c 'alias.x=!printf ok' x")

    def test_alias_does_not_override_a_builtin(self):
        self.deny("git -c 'alias.reset=status --short' reset --hard")

    def test_clean_exclude_attached_pattern_is_not_dry_run(self):
        self.deny('git clean -f -enothing')

    def test_clean_exclude_clustered_pattern_is_not_dry_run(self):
        self.deny('git clean -fenothing')

    def test_clean_exclude_separate_pattern_stays_denied(self):
        self.deny('git clean -f -e nothing')

    def test_clean_exclude_preserves_real_dry_run(self):
        self.allow('git clean -fn -e x')

    def test_clean_exclude_option_looking_pattern_is_not_dry_run(self):
        self.deny('git clean -f -e -n')
