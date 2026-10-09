import contextlib
import io
import json
import os
import re
import sqlite3
from pathlib import Path
from unittest import mock

from test_ws import Base
from ws import cli, core, native


class NativeBase(Base):
    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self.home, self.codex = base / 'home', base / 'home' / '.codex'
        self.repo = base / 'myapp-repo'
        self.repo.mkdir(); self.home.mkdir()
        cfg = core.config(self.root); cfg['repos'] = [str(self.repo)]
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        for patch in (mock.patch.object(Path, 'home', return_value=self.home),
                      mock.patch.dict(os.environ, {'CODEX_HOME': str(self.codex)})):
            patch.start(); self.addCleanup(patch.stop)
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Fix it')

    def claude_dir(self, path):
        slug = re.sub(r'[^A-Za-z0-9]', '-', str(path.resolve()))
        d = self.home / '.claude/projects' / slug / 'memory'
        d.mkdir(parents=True, exist_ok=True); return d

    def memory(self, directory, name, description):
        (directory / f'{name}.md').write_text(f'---\nname: {name}\ndescription: "{description}"\n---\nbody text\n')

    def codex_db(self, name, ddl, rows, sql):
        self.codex.mkdir(exist_ok=True)
        with sqlite3.connect(self.codex / name) as db:
            db.execute(ddl); db.executemany(sql, rows)

    def memories_db(self, rows):
        self.codex_db('memories_1.sqlite',
                      'create table stage1_outputs(thread_id text, raw_memory text, rollout_summary text, rollout_slug text, generated_at int)',
                      rows, 'insert into stage1_outputs values (?,?,?,?,?)')

    def goals_db(self, rows):
        self.codex_db('goals_1.sqlite',
                      'create table thread_goals(thread_id text, goal_id text, objective text, status text)',
                      rows, 'insert into thread_goals values (?,?,?,?)')

    def handoff(self):
        return core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']


class ImportTests(NativeBase):
    def test_collects_claude_codex_gemini_with_redaction_and_matching(self):
        self.memory(self.claude_dir(self.root), 'never-commit', 'Never commit; token=abcdefghijklmnop1234')
        self.memory(self.claude_dir(self.repo), 'repo-rule', 'Use the repo linter')
        (self.claude_dir(self.root) / 'MEMORY.md').write_text('- [x](x.md) index only')
        other = self.home / 'elsewhere'; other.mkdir()
        self.memory(self.claude_dir(other), 'unrelated', 'Not ours')
        self.memories_db([('t1', 'worked in myapp-repo today', 'Summary: fixed the crash', 'fix-crash', 2),
                          ('t2', 'other project', 'Unrelated summary', 'x', 1)])
        (self.home / '.gemini').mkdir()
        (self.home / '.gemini/GEMINI.md').write_text('intro\n## Gemini Added Memories\n- likes tabs\n- uses pytest\n## Other\n- nope\n')
        items = native.collect(self.root)
        texts = {(i['client'], i['text']) for i in items}
        self.assertIn(('claude', 'repo-rule: Use the repo linter'), texts)
        self.assertIn(('codex', 'Summary: fixed the crash'), texts)
        self.assertIn(('gemini', 'likes tabs'), texts)
        self.assertEqual(len(items), 5)  # 2 claude + 1 codex + 2 gemini
        blob = json.dumps(items)
        self.assertNotIn('abcdefghijklmnop1234', blob); self.assertIn('[REDACTED]', blob)
        for bad in ('Not ours', 'Unrelated summary', 'nope', 'index only'):
            self.assertNotIn(bad, blob)

    def test_preview_writes_nothing_and_yes_appends_deduplicated_block(self):
        self.memory(self.claude_dir(self.repo), 'repo-rule', 'Use the repo linter')
        before = core.task_read(self.root, 'T-1')['text']
        preview = native.import_native(self.root, 'claude')
        self.assertEqual(preview['written'], []); self.assertEqual(before, core.task_read(self.root, 'T-1')['text'])
        result = native.import_native(self.root, 'claude', yes=True)
        self.assertEqual(result['written'], ['claude']); self.assertEqual(result['task'], 'T-1')
        self.assertRegex(self.handoff(), r'### Imported \d{4}-\d\d-\d\d \(unverified, from claude\)\n- repo-rule: Use the repo linter')
        again = native.import_native(self.root, 'claude', yes=True)
        self.assertEqual(again['written'], []); self.assertEqual(self.handoff().count('### Imported'), 1)

    def test_word_cap_per_client_and_max_20_preview(self):
        d = self.claude_dir(self.repo)
        for n in range(30): self.memory(d, f'm{n:02d}', ' '.join(f'w{n}x{k}' for k in range(30)))
        items = native.import_native(self.root, 'claude')['items']
        self.assertLessEqual(len(items), 20)
        native.import_native(self.root, 'claude', yes=True)
        body = re.search(r'from claude\)\n(.*?)\n<!-- /ws:imported', self.handoff(), re.S).group(1)
        self.assertLessEqual(len(body.split()), 150)

    def test_yes_needs_one_task_and_never_writes_native_stores(self):
        self.memory(self.claude_dir(self.repo), 'r', 'rule')
        store = self.home / '.claude'
        snap = {p: p.read_bytes() for p in store.rglob('*') if p.is_file()}
        core.task_new(self.root, 'T-2', 'Other'); core.checkpoint(self.root, 'T-2', 'in_progress', 'x')
        with self.assertRaises(core.WsError): native.import_native(self.root, 'claude', yes=True)
        self.assertEqual(native.import_native(self.root, 'claude', task='T-2', yes=True)['task'], 'T-2')
        self.assertEqual(snap, {p: p.read_bytes() for p in store.rglob('*') if p.is_file()})

    def test_missing_or_unknown_schema_is_skipped_silently(self):
        self.assertEqual(native.collect(self.root), [])
        self.codex.mkdir()
        sqlite3.connect(self.codex / 'memories_1.sqlite').execute('create table stage1_outputs(x int)').connection.commit()
        (self.codex / 'goals_1.sqlite').write_bytes(b'not sqlite')
        self.assertEqual(native.collect(self.root, 'codex'), [])
        self.assertIn('skipped', native.codex_goals(self.root))

    def test_cli_import_native(self):
        self.memory(self.claude_dir(self.repo), 'r', 'cli rule')
        with mock.patch('builtins.print') as output:
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'import', 'native', '--client', 'claude', '--yes']), 0)
        self.assertIn('cli rule', self.handoff()); self.assertIn('cli rule', output.call_args[0][0])


class GoalTests(NativeBase):
    def setUp(self):
        super().setUp()
        self.goals_db([('a', 'g1', 'Finish T-1 crash fix', 'active'), ('b', 'g2', 'Old T-1 work', 'complete'),
                       ('c', 'g3', 'Unrelated thing', 'active'), ('d', 'g4', 'fix crash follow-up', 'active'), ('e', 'g5', 'T-1 paused work', 'paused')])

    def test_counts_match_task_id_or_title(self):
        self.assertEqual(native.codex_goals(self.root)['active'], 2)  # T-1 id and "Fix crash" title
        self.assertEqual(native.codex_goals(self.root)['complete'], 1)

    def test_status_and_doctor_show_goals_and_doctor_gives_reason(self):
        self.assertEqual(core.status(self.root)['codex_goals'], {'active': 2, 'complete': 1})
        self.assertIn('Codex goals: 2 active, 1 complete', cli.text_status(core.status(self.root)))
        self.assertEqual(core.doctor(self.root)['codex_goals'], {'active': 2, 'complete': 1})
        (self.codex / 'goals_1.sqlite').unlink()
        self.assertIn('skipped', core.doctor(self.root)['codex_goals'])
        self.assertNotIn('codex_goals', core.status(self.root))

    def test_checkpoint_done_hints_on_active_goal_only(self):
        def run(status):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                cli.main(['--workspace-root', str(self.root), 'checkpoint', 'T-1', '--status', status, '--next', 'none'])
            return err.getvalue()
        self.assertIn('Codex goal still active: Finish T-1 crash fix \u2014 close it in Codex', run('done'))
        self.assertEqual(run('review'), '')
