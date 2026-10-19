import unittest

from testutil import run_ws as ws


class DailyHelpTests(unittest.TestCase):
    def test_help_tells_a_new_user_how_to_see_every_command(self):
        for args in (('--help',), ('help',)):
            result = ws(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('ws help all', result.stdout)
            self.assertNotIn('init ', result.stdout)  # still the short daily list

    def test_daily_command_options_all_have_help_text(self):
        for args, words in ((('checkpoint',), ('--next', '--note', '--token')), (('claim',), ('--worker',)), (('remember',), ('--team', '--author')),
                            (('know', 'add'), ('--team', '--category')), (('lesson', 'add'), ('--tag', '--team')),
                            (('feedback', 'add'), ('--kind',)), (('upgrade',), ('--dry-run',)), (('search',), ('--category',))):
            text = ' '.join(ws(*args, '--help').stdout.split())
            for word in words:
                self.assertRegex(text, rf'{word}\b[^-]*?[a-z]{{3,}}', (args, word))
                self.assertNotRegex(text, rf'{word}(?: [A-Z]+)? (?=-)', (args, word))  # next option follows directly: no help

    def test_task_and_know_subcommands_are_described(self):
        for group, names in (('task', ('new', 'list', 'find', 'show')), ('know', ('add', 'list', 'show')), ('lesson', ('add', 'search'))):
            text = ws(group, '--help').stdout
            for name in names:
                line = next(l for l in text.splitlines() if l.startswith(f'    {name} '))
                self.assertGreater(len(line.split(None, 1)[1].strip()), 8, (group, name))


if __name__ == '__main__':
    unittest.main()
