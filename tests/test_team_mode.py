import subprocess
from test_ws import Base
from ws import core

GIT = ['git', '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', '-c', 'core.hooksPath=/dev/null']
CONFLICT = ('---\nid: C-1\nstatus: in_progress\n<<<<<<< HEAD\nclaimed_by: alice\n=======\nclaimed_by: bob\n>>>>>>> origin/main\n---\n\n# Clash\n\n'
            '## Objective\n\n## Next action\n<<<<<<< HEAD\nDo A.\n=======\nDo B.\n>>>>>>> origin/main\n')


def git(path, *args):
    subprocess.run([*GIT, '-C', str(path), *args], check=True, capture_output=True)


class TeamBriefTests(Base):
    def test_local_ready_claim_beats_teammate_active_task(self):
        core.claim(self.root, 'T-1', 'synthetic-local')
        self.other('APP-1', 'synthetic-remote')
        brief = core.brief(self.root)
        self.assertIn('Task T-1', brief)
        self.assertIn('Others working: APP-1', brief)

    def test_unmatched_teammate_task_is_not_selected(self):
        self.other('APP-1', 'synthetic-remote')
        brief = core.brief(self.root)
        self.assertNotIn('Task APP-1', brief)
        self.assertIn('Others working: APP-1', brief)

    def app(self, branch):
        app = self.root / 'app'; app.mkdir(exist_ok=True)
        git(app, 'init', '-q', '-b', branch)
        (app / 'a.txt').write_text('x\n'); git(app, 'add', '.'); git(app, 'commit', '-qm', 'init')
        return app

    def other(self, task_id, who, branch='', repo='', status='in_progress'):
        core.task_new(self.root, task_id, f'Work {task_id}', branch=branch, repo=repo)
        path = core.task_path(self.root, task_id)
        path.write_text(core.set_meta(path.read_text(), {'status': status, 'claimed_by': who, 'claim_token': 'theirs' + task_id}))

    def test_branch_match_wins_and_others_listed(self):
        app = self.app('feature/x')
        self.other('APP-1', 'alice', branch='feature/y', repo=str(app))
        self.other('APP-2', 'bob', branch='feature/x', repo=str(app))
        brief = core.brief(self.root)
        self.assertIn('Task APP-2', brief)
        self.assertIn('Others working: APP-1 (alice)', brief)
        self.assertNotIn('APP-2 (bob)', brief)

    def test_own_local_claim_beats_branch_and_others_capped_at_three(self):
        app = self.app('feature/x')
        self.other('APP-9', 'bob', branch='feature/x', repo=str(app))
        for i, who in enumerate(('a', 'b', 'c', 'd')): self.other(f'APP-{i}', who)
        core.claim(self.root, 'T-1', 'me'); core.checkpoint(self.root, 'T-1', 'in_progress', 'Continue.')
        brief = core.brief(self.root)
        self.assertIn('Task T-1', brief)
        line = next(l for l in brief.splitlines() if l.startswith('Others working: '))
        self.assertEqual(line.count('('), 3)
        self.assertLess(len(brief.split()), 200)

    def test_others_shown_when_no_task_is_active(self):
        self.other('APP-1', 'alice', status='ready')
        self.assertIn('Others working: APP-1 (alice)', core.brief(self.root))


class TeamDoctorTests(Base):
    def setUp(self):
        super().setUp()
        git(self.root, 'init', '-q')

    def team(self):
        return core.doctor(self.root).get('team')

    def test_not_a_git_repo_skips_team_checks(self):
        subprocess.run(['rm', '-rf', str(self.root / '.git')], check=True)
        self.assertIsNone(self.team())

    def test_clean_workspace_has_no_warnings(self):
        git(self.root, 'add', '.')
        self.assertEqual(self.team(), {'warnings': []})

    def test_unignored_ws_dir_and_tracked_claims_warn(self):
        (self.root / '.gitignore').write_text('')
        claim = self.root / '.ws/claims/T-1.json'; claim.parent.mkdir(parents=True); claim.write_text('{"token": "x"}\n')
        git(self.root, 'add', '-f', '.')
        warnings = ' '.join(self.team()['warnings'])
        self.assertIn('.ws/ is not ignored', warnings)
        self.assertIn('tracked', warnings)

    def test_tracked_secret_reported_by_location_not_value(self):
        note = core.vault(self.root) / 'Notes.md'
        note.write_text('fine\napi_key = abcdef1234567890abcdef\n')
        git(self.root, 'add', '.')
        warnings = self.team()['warnings']
        self.assertTrue(any('vault/Notes.md:2' in w for w in warnings), warnings)
        self.assertNotIn('abcdef1234567890abcdef', ' '.join(warnings))

    def test_untracked_secret_is_not_a_team_warning(self):
        (core.vault(self.root) / 'Notes.md').write_text('api_key = abcdef1234567890abcdef\n')
        self.assertEqual(self.team(), {'warnings': []})

    def test_large_tracked_note_reports_skipped_secret_check(self):
        (core.vault(self.root) / 'Notes.md').write_text('x' * 1_000_001)
        git(self.root, 'add', '.')
        self.assertIn('not checked', ' '.join(self.team()['warnings']))

    def test_staged_secret_is_visible_after_working_copy_is_cleaned(self):
        note = core.vault(self.root) / 'Notes.md'
        note.write_text('api_key = abcdef1234567890abcdef\n')
        git(self.root, 'add', '.')
        note.write_text('clean working copy\n')
        warnings = ' '.join(self.team()['warnings'])
        self.assertIn('vault/Notes.md:1', warnings)
        self.assertIn('staged', warnings)
        self.assertNotIn('abcdef1234567890abcdef', warnings)


class ConflictedTaskTests(Base):
    def setUp(self):
        super().setUp()
        core.task_path(self.root, 'C-1').write_text(CONFLICT)

    def test_reads_do_not_crash_and_report_conflicted(self):
        entry = next(t for t in core.task_list(self.root) if t['id'] == 'C-1')
        self.assertEqual(entry['status'], 'conflicted')
        self.assertIn('<<<<<<<', core.task_read(self.root, 'C-1')['text'])
        self.assertTrue(core.task_read(self.root, 'C-1', ['Next action'])['conflicted'])
        self.assertNotIn('C-1', core.brief(self.root))
        self.assertEqual(core.status(self.root)['tasks']['conflicted'], 1)
        self.assertEqual(core.task_next(self.root)['waiting'], 0)

    def test_status_and_doctor_carry_a_fix_hint(self):
        for item in (core.status(self.root)['conflicted'], core.doctor(self.root)['conflicted']):
            self.assertEqual(len(item), 1)
            self.assertIn('C-1', item[0]); self.assertIn('git add', item[0])
        self.assertFalse(core.doctor(self.root)['valid'])

    def test_writes_refuse_with_a_hint(self):
        for call in (lambda: core.claim(self.root, 'C-1', 'me'), lambda: core.checkpoint(self.root, 'C-1', 'in_progress', 'Go.')):
            with self.assertRaisesRegex(core.WsError, 'conflict'): call()


if __name__ == '__main__':
    import unittest; unittest.main()
