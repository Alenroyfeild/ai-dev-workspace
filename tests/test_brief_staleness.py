import subprocess
from test_ws import Base
from ws import core


class BriefStalenessTests(Base):
    def git(self, repo, *args):
        cmd = ['git', '-C', str(repo), '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', '-c', 'core.hooksPath=/dev/null', *args]
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, repo, name, body):
        (repo / name).write_text(body)
        self.git(repo, 'add', '.'); self.git(repo, 'commit', '-qm', name + body)
        return self.git(repo, 'rev-parse', 'HEAD')

    def repo(self, next_action='Finish export.py output.'):
        repo = self.root / 'fixture'; repo.mkdir()
        self.git(repo, 'init', '-q')
        self.base = self.commit(repo, 'export.py', 'v1\n')
        self.commit(repo, 'other.py', 'v1\n')
        core.task_new(self.root, 'ST-1', 'Publish daily output', repo=str(repo))
        core.claim(self.root, 'ST-1', 'synthetic')
        core.checkpoint(self.root, 'ST-1', 'in_progress', next_action)
        return repo

    def test_checkpoint_records_repo_head(self):
        repo = self.repo()
        self.assertEqual(core.task_read(self.root, 'ST-1', ['Objective'])['meta']['checkpoint_commit'], self.git(repo, 'rev-parse', 'HEAD'))

    def test_changed_file_named_in_next_action_warns(self):
        repo = self.repo()
        head = self.git(repo, 'rev-parse', '--short=7', 'HEAD')
        self.commit(repo, 'export.py', 'v2\n')
        brief = core.brief(self.root)
        self.assertIn(f'Memory check: written at {head}; changed since: export.py (verify before acting).', brief)
        self.assertLess(len(brief.split()), 200)

    def test_unrelated_change_is_silent(self):
        repo = self.repo()
        self.commit(repo, 'other.py', 'v2\n')
        self.assertNotIn('Memory check', core.brief(self.root))

    def test_no_repo_is_silent(self):
        core.claim(self.root, 'T-1', 'synthetic'); core.checkpoint(self.root, 'T-1', 'in_progress', 'Fix export.py.')
        self.assertNotIn('checkpoint_commit', core.task_read(self.root, 'T-1', ['Objective'])['meta'])
        self.assertNotIn('Memory check', core.brief(self.root))

    def test_reset_behind_checkpoint_warns_rollback_only(self):
        repo = self.repo()
        self.commit(repo, 'export.py', 'v2\n')
        core.checkpoint(self.root, 'ST-1', 'in_progress', 'Finish export.py output.')
        saved = self.git(repo, 'rev-parse', '--short=7', 'HEAD')
        self.git(repo, 'reset', '-q', '--hard', self.base)
        brief = core.brief(self.root)
        self.assertIn(f'Memory check: code is behind the saved checkpoint ({saved}); the work it describes may be undone.', brief)
        self.assertNotIn('changed since', brief)

    def test_more_than_three_lessons_are_counted_and_gone_paths_marked(self):
        repo = self.repo()
        for i in range(4): core.lesson_add(self.root, f'Publish daily output rule {i} avoids failures')
        core.lesson_add(self.root, 'Publish daily output stale rule survives refactors.', paths=['removed/*.py'])
        core.lesson_add(self.root, 'Publish daily output live rule guards exports.', paths=['*.py'])
        brief = core.brief(self.root)
        self.assertEqual(brief.count('\nLesson: '), 3)
        self.assertIn('Lessons: 3 more (ws lesson search)', brief)
        self.assertLess(len(brief.split()), 200)
        lines = [l for l in core.relevant_lessons(self.root, {'id': 'ST-1', 'title': 'Publish daily output'})]
        self.assertEqual([l for l in lines if '(paths gone)' in l], [l for l in lines if 'stale rule' in l])
        self.assertTrue(any('live rule' in l and 'paths gone' not in l for l in lines))

    def test_deleted_file_named_in_next_action_is_reported_gone(self):
        repo = self.repo()
        self.git(repo, 'rm', '-q', 'export.py'); self.git(repo, 'commit', '-qm', 'drop export')
        brief = core.brief(self.root)
        self.assertIn('gone since: export.py', brief)
        self.assertNotIn('changed since', brief)

    def test_renamed_file_names_its_new_path(self):
        repo = self.repo()
        self.git(repo, 'mv', 'export.py', 'publish.py'); self.git(repo, 'commit', '-qm', 'rename export')
        self.assertIn('gone since: export.py (now publish.py)', core.brief(self.root))

    def test_uncommitted_delete_is_reported_gone(self):
        repo = self.repo()
        (repo / 'export.py').unlink()
        self.assertIn('gone since: export.py', core.brief(self.root))

    def test_file_named_only_in_a_saved_decision_is_checked(self):
        repo = self.repo('Finish the output.')
        core.checkpoint(self.root, 'ST-1', 'in_progress', 'Finish the output.', notes={'Handoff': 'Decision: keep export.py as the only writer.'})
        self.git(repo, 'rm', '-q', 'export.py'); self.git(repo, 'commit', '-qm', 'drop export')
        self.assertIn('gone since: export.py', core.brief(self.root))

    def test_same_basename_elsewhere_is_not_reported_gone(self):
        repo = self.repo('Finish src/export.py output.')
        (repo / 'src').mkdir(); (repo / 'tests').mkdir()
        self.commit(repo, 'src/export.py', 'v1\n'); self.commit(repo, 'tests/export.py', 'v1\n')
        core.checkpoint(self.root, 'ST-1', 'in_progress', 'Finish src/export.py output.')
        self.git(repo, 'rm', '-q', 'export.py', 'tests/export.py'); self.git(repo, 'commit', '-qm', 'drop two')
        self.assertNotIn('gone since', core.brief(self.root))
        self.git(repo, 'rm', '-q', 'src/export.py'); self.git(repo, 'commit', '-qm', 'drop src')
        self.assertIn('gone since: export.py', core.brief(self.root))  # the named full path is gone

    def test_backup_name_is_not_a_mention_but_dot_slash_path_is(self):
        repo = self.repo('Delete export.py.bak later.')
        (repo / 'export.py').unlink()
        self.assertNotIn('gone since', core.brief(self.root))
        core.checkpoint(self.root, 'ST-1', 'in_progress', 'Review ./export.py output.')
        self.assertIn('gone since: export.py', core.brief(self.root))

    def dirty_checkpoint(self):
        repo = self.repo()
        (repo / 'export.py').write_text('half done\n')
        core.checkpoint(self.root, 'ST-1', 'in_progress', 'Finish the output.')
        return repo

    def test_checkpoint_records_uncommitted_paths(self):
        self.dirty_checkpoint()
        self.assertEqual(core.task_read(self.root, 'ST-1', ['Objective'])['meta']['checkpoint_dirty'], '["export.py"]')

    def test_discarded_uncommitted_edits_warn(self):
        repo = self.dirty_checkpoint()
        self.git(repo, 'checkout', '--', 'export.py')
        self.assertIn('uncommitted edits gone: export.py (stashed or reset?)', core.brief(self.root))

    def test_kept_or_committed_edits_are_silent(self):
        repo = self.dirty_checkpoint()
        self.assertNotIn('Memory check', core.brief(self.root))
        self.git(repo, 'commit', '-qam', 'finish export')
        self.assertNotIn('gone', core.brief(self.root))
