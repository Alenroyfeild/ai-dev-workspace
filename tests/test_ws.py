import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
from ws import core  # noqa: E402
from mcp import server  # noqa: E402


class PackagingTests(unittest.TestCase):
    def test_installed_layout_finds_assets_and_uses_its_interpreter(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            package = base / 'site/ws'
            ignore = shutil.ignore_patterns('__pycache__', '*.pyc', 'runtime')
            shutil.copytree(KIT / 'ws', package, ignore=ignore)
            for name in ('template', 'packs', 'skills', 'mcp', 'bin'):
                shutil.copytree(KIT / name, package / name, ignore=ignore)
            shutil.copy2(KIT / 'kit.json', package / 'kit.json')
            script = ('from pathlib import Path; import sys; from ws import core; '
                      'root=Path("workspace"); core.init(root, "synthetic"); '
                      'core.pack_add(root, "obsidian"); '
                      'assert core.KIT == Path(core.__file__).resolve().parent; '
                      'assert core.mcp_command(root)["command"] == sys.executable; '
                      'assert (core.KIT / "skills/thinkbeforeact/SKILL.md").is_file(); '
                      'assert (root / "vault/.obsidian/app.json").is_file(); '
                      'print(core.brief(root))')
            proc = subprocess.run([sys.executable, '-c', script], cwd=base,
                                  env={**os.environ, 'PYTHONPATH': str(base / 'site'), 'WS_OFFLINE': '1'},
                                  capture_output=True, text=True, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn('No in-progress task', proc.stdout)

    def test_package_update_prints_pipx_guidance_without_network(self):
        from ws import cli
        with mock.patch.object(core, 'PACKAGED', True, create=True), \
                mock.patch.object(core, 'check_update', side_effect=AssertionError('network check')), \
                mock.patch.object(core.subprocess, 'run', side_effect=AssertionError('git command')), \
                mock.patch('builtins.print') as output:
            self.assertEqual(cli.main(['update']), 0)
            self.assertIn('pipx upgrade ai-dev-workspace', output.call_args[0][0])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'w'
        core.init(self.root, 'demo', ['ios'])
        core.task_new(self.root, 'T-1', 'Fix crash', 'Crash on empty email')

    def tearDown(self):
        self.tmp.cleanup()


class TaskTests(Base):
    def test_init_preserves_existing_files_and_stages_collisions(self):
        target = Path(self.tmp.name) / 'existing'
        files = ['AGENTS.md', 'CLAUDE.md', '.mcp.json', 'vault/Runbooks/iOS build triage.md']
        for name in files:
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'user content\r\n')
        result = core.init(target, 'demo', ['ios'])
        for name in files:
            path = target / name
            self.assertEqual(path.read_bytes(), b'user content\r\n')
            self.assertTrue(path.with_name(path.name + '.ws-new').is_file())
        self.assertEqual(len(result['collisions']), 4)

    def test_pack_add_preserves_rules_runbooks_and_existing_sidecar(self):
        book = self.root / 'vault/Runbooks/iOS build triage.md'
        book.write_text('user runbook')
        sidecar = book.with_name(book.name + '.ws-new')
        sidecar.write_text('user sidecar')
        rules = (self.root / 'AGENTS.md').read_bytes()
        core.pack_add(self.root, 'ios')
        self.assertEqual(book.read_text(), 'user runbook')
        self.assertEqual(sidecar.read_text(), 'user sidecar')
        self.assertTrue(book.with_name(book.name + '.ws-new.1').is_file())
        core.pack_add(self.root, 'obsidian')
        after = (self.root / 'AGENTS.md').read_bytes()
        self.assertTrue(after.startswith(rules.rstrip(b'\n')))
        self.assertIn(b'## Obsidian pack', after)
        core.pack_add(self.root, 'obsidian')
        self.assertEqual((self.root / 'AGENTS.md').read_bytes(), after)

    def test_interrupted_init_can_retry_without_overwriting(self):
        target = Path(self.tmp.name) / 'retry'
        target.mkdir()
        (target / 'CLAUDE.md').write_text('user rules')
        write = core.write_preserving
        def interrupted(path, data, collisions):
            if Path(path).name == 'AGENTS.md':
                raise OSError('synthetic interruption')
            return write(path, data, collisions)
        with mock.patch.object(core, 'write_preserving', side_effect=interrupted), self.assertRaises(OSError):
            core.init(target, 'demo')
        self.assertFalse((target / 'workspace.json').exists())
        core.init(target, 'demo')
        self.assertEqual((target / 'CLAUDE.md').read_text(), 'user rules')
        self.assertTrue(core.validate(target)['valid'])
    def test_memory_hooks_and_brief_are_bounded(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect the synthetic guard',
                        notes={'Blockers': 'No blocker', 'Evidence': 'synthetic'})
        core.lesson_add(self.root, 'Crash repeated → test the empty input')
        brief = core.brief(self.root)
        self.assertIn('Inspect the synthetic guard', brief)
        self.assertIn('No blocker', brief)
        self.assertIn('Crash repeated', brief)
        core.checkpoint(self.root, 'T-1', 'in_progress', 'word ' * 300)
        self.assertLess(len(core.brief(self.root).split()), 200)
        for name in ('.claude/settings.json', '.codex/hooks.json'):
            hooks = json.loads((self.root / name).read_text())['hooks']
            self.assertEqual(set(hooks), {'SessionStart', 'PreCompact', 'Stop'})

    def test_hook_settings_collision_keeps_user_content(self):
        target = Path(self.tmp.name) / 'hooks'
        settings = target / '.claude/settings.json'
        settings.parent.mkdir(parents=True)
        settings.write_text('{"user": true}')
        core.init(target, 'hooks')
        self.assertEqual(settings.read_text(), '{"user": true}')
        self.assertTrue(settings.with_name('settings.json.ws-new').exists())

    def test_nudge_requires_stale_claim_and_checkpoint_resets_it(self):
        with mock.patch.object(core, 'now', return_value='2026-01-01T00:00:00+00:00'):
            token = core.claim(self.root, 'T-1', 'synthetic')['token']
        with mock.patch.object(core, 'now', return_value='2026-01-01T00:29:59+00:00'):
            self.assertEqual(core.nudge(self.root), '')
        with mock.patch.object(core, 'now', return_value='2026-01-01T00:30:00+00:00'):
            self.assertIn('T-1', core.nudge(self.root))
            core.checkpoint(self.root, 'T-1', 'in_progress', 'next', worker='synthetic', token=token)
            self.assertEqual(core.nudge(self.root), '')
        core.release(self.root, 'T-1', 'synthetic', token)
        self.assertEqual(core.nudge(self.root), '')
    def test_connect_clients_and_doctor_status(self):
        core.connect(self.root, 'cursor')
        rep = core.doctor(self.root)['clients']
        self.assertTrue(rep['claude'])
        self.assertTrue(rep['cursor'])
        config = json.loads((self.root / '.cursor/mcp.json').read_text())
        self.assertIn('ai-dev-workspace', config['mcpServers'])
        self.assertEqual(core.connect(self.root, 'cursor')['connected'], True)

    def test_connect_preserves_conflicting_project_configuration(self):
        path = self.root / '.mcp.json'
        path.write_text('{"mcpServers": {"synthetic": {}}}')
        before = path.read_bytes()
        result = core.connect(self.root, 'claude')
        self.assertFalse(result['connected'])
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(path.with_name('.mcp.json.ws-new').exists())

    def test_codex_connect_prints_then_writes_with_backup(self):
        with mock.patch.object(Path, 'home', return_value=Path(self.tmp.name)):
            path = Path(self.tmp.name) / '.codex/config.toml'
            path.parent.mkdir()
            path.write_text('# synthetic user settings\n')
            original = path.read_bytes()
            preview = core.connect(self.root, 'codex')
            self.assertIn('[mcp_servers.ai-dev-workspace]', preview['config'])
            self.assertEqual(path.read_bytes(), original)
            result = core.connect(self.root, 'codex', write=True)
            self.assertEqual(Path(result['backup']).read_bytes(), original)
            self.assertTrue(core.doctor(self.root)['clients']['codex'])
            self.assertTrue(core.connect(self.root, 'codex', write=True)['connected'])

    def test_codex_connect_refuses_conflicting_global_entry(self):
        with mock.patch.object(Path, 'home', return_value=Path(self.tmp.name)):
            path = Path(self.tmp.name) / '.codex/config.toml'
            path.parent.mkdir()
            for content in ("[mcp_servers.'ai-dev-workspace']\ncommand = 'other'\n", 'mcp_servers = {}\n'):
                path.write_text(content)
                with self.assertRaises(core.WsError):
                    core.connect(self.root, 'codex', write=True)
                self.assertEqual(path.read_text(), content)

    def test_init_installs_template_pack_and_mcp_config(self):
        self.assertTrue((self.root / 'vault/Runbooks/iOS build triage.md').exists())
        self.assertIn('## iOS pack', (self.root / 'AGENTS.md').read_text())
        mcp = json.loads((self.root / '.mcp.json').read_text())
        self.assertIn('server.py', mcp['mcpServers']['ai-dev-workspace']['args'][0])
        with self.assertRaises(core.WsError):
            core.init(self.root, 'again')

    def test_unknown_pack_rejected(self):
        with self.assertRaises(core.WsError):
            core.init(Path(self.tmp.name) / 'x', 'x', ['nope'])

    def test_pack_add_is_idempotent(self):
        core.pack_add(self.root, 'obsidian')
        core.pack_add(self.root, 'obsidian')
        self.assertEqual(core.config(self.root)['packs'], ['ios', 'obsidian'])
        self.assertEqual((self.root / 'AGENTS.md').read_text().count('## Obsidian pack'), 1)
        self.assertTrue((self.root / 'vault/.obsidian/app.json').exists())

    def test_every_pack_is_idempotent_after_rendering_kit_path(self):
        for name in core.available_packs():
            core.pack_add(self.root, name)
            core.pack_add(self.root, name)
            snippet = (core.KIT / 'packs' / name / 'AGENTS.snippet.md').read_text().replace('<kit>', str(core.KIT)).strip()
            self.assertEqual((self.root / 'AGENTS.md').read_text().count(snippet), 1, name)

    def test_empty_section_write_keeps_next_heading(self):
        # Regression: writing an empty section used to swallow the following heading.
        text = core.task_read(self.root, 'T-1')['text']
        self.assertIn('## Acceptance criteria', text)
        self.assertEqual(core.section(text, 'Objective'), 'Crash on empty email')
        self.assertEqual(core.section(text, 'Acceptance criteria'), '')
        self.assertTrue(core.validate(self.root)['valid'], core.validate(self.root))

    def test_claim_checkpoint_release(self):
        token = core.claim(self.root, 'T-1', 'claude')['token']
        with self.assertRaises(core.WsError):
            core.claim(self.root, 'T-1', 'codex')
        with self.assertRaises(core.WsError):
            core.checkpoint(self.root, 'T-1', 'in_progress', 'x', worker='codex', token='bad')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Add guard', worker='claude', token=token,
                        notes={'Evidence': 'Login.swift:42'})
        sec = core.task_read(self.root, 'T-1', ['Next action', 'Evidence'])['sections']
        self.assertEqual(sec, {'Next action': 'Add guard', 'Evidence': 'Login.swift:42'})
        core.release(self.root, 'T-1', 'claude', token)
        core.claim(self.root, 'T-1', 'codex')
        # Regression: our own claim_token must not look like a leaked secret.
        self.assertEqual(core.validate(self.root)['warnings'], [])

    def test_local_claim_defaults_cover_daily_loop_and_mcp(self):
        claim = core.claim(self.root, 'T-1', 'terra')
        stored = self.root / '.ws/claims/T-1.json'
        self.assertEqual(json.loads(stored.read_text()), {'worker': 'terra', 'token': claim['token']})
        reply = server.handle(self.root, {'jsonrpc': '2.0', 'method': 'tools/call', 'id': 1, 'params': {
            'name': 'checkpoint', 'arguments': {'id': 'T-1', 'status': 'in_progress', 'next': 'Run the tests'}}})
        self.assertFalse(reply['result']['isError'])
        core.checkpoint(self.root, 'T-1', 'review', 'Review the change')
        core.release(self.root, 'T-1')
        self.assertFalse(stored.exists())

    def test_setup_daily_loop_runs_in_a_fresh_workspace(self):
        root = Path(self.tmp.name) / 'daily-loop'

        def ws(*args):
            return subprocess.run([sys.executable, str(KIT / 'bin/ws'), *args], cwd=root,
                                  text=True, capture_output=True, check=True)

        subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'init', str(root), '--name', 'daily'],
                       text=True, capture_output=True, check=True)
        ws('task', 'new', 'T-1', 'Fix crash')
        ws('task', 'find', 'T-1')
        ws('claim', 'T-1', '--worker', 'me')
        ws('checkpoint', 'T-1', '--status', 'in_progress', '--next', 'Run the tests')
        ws('lesson', 'add', 'A failed test revealed the missing default → test the daily loop')
        ws('feedback', 'add', 'The loop was easy to run', '--kind', 'friction')
        ws('release', 'T-1')

    def test_concurrent_claim_has_one_winner(self):
        barrier = threading.Barrier(4)

        def attempt(worker):
            barrier.wait()
            try:
                return core.claim(self.root, 'T-1', worker)
            except core.WsError:
                return None
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            results = list(pool.map(attempt, ['a', 'b', 'c', 'd']))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_stale_checkpoint_rejected_and_next_required(self):
        sha = core.task_read(self.root, 'T-1')['sha']
        core.checkpoint(self.root, 'T-1', 'ready', 'first')
        with self.assertRaises(core.WsError):
            core.checkpoint(self.root, 'T-1', 'ready', 'second', expected_sha=sha)
        with self.assertRaises(core.WsError):
            core.checkpoint(self.root, 'T-1', 'ready', '   ')
        with self.assertRaises(core.WsError):
            core.checkpoint(self.root, 'T-1', 'finished', 'x')

    def test_secrets_redacted_on_write(self):
        core.checkpoint(self.root, 'T-1', 'ready', 'call with Bearer abcdefghijklmnop123', notes={'Evidence': 'api_key=sk-1234567890abcdef'})
        text = core.task_read(self.root, 'T-1')['text']
        self.assertNotIn('abcdefghijklmnop123', text)
        self.assertNotIn('sk-1234567890abcdef', text)

    def test_new_task_redacts_title_and_metadata(self):
        markers = ['password=' + 'A' * 16, 'secret=' + 'B' * 16, 'api_key=' + 'C' * 16]
        core.task_new(self.root, 'T-2', markers[0], branch=markers[1], repo=markers[2])
        text = core.task_read(self.root, 'T-2')['text']
        for marker in markers:
            self.assertNotIn(marker, text)
        self.assertEqual(text.count('[REDACTED]'), 3)

    def test_single_line_task_fields_reject_newlines(self):
        for values in ({'title': 'a\nb'}, {'branch': 'a\rb'}, {'repo': 'a\nb'}):
            with self.subTest(values=values), self.assertRaises(core.WsError):
                core.task_new(self.root, 'T-2', **{'title': 'ordinary', **values})
        self.assertFalse((self.root / 'vault/Tasks/T-2.md').exists())

    def test_bad_ids_rejected(self):
        for bad in ('../x', 'a/b', '', '.hidden'):
            with self.assertRaises(core.WsError):
                core.task_path(self.root, bad)

    def test_validate_reports_broken_link_and_missing_section(self):
        (self.root / 'vault/Product/Note.md').write_text('See [[Nowhere]].\n')
        path = self.root / 'vault/Tasks/T-1.md'
        path.write_text(path.read_text().replace('## Checks\n', ''))
        errors = core.validate(self.root)['errors']
        self.assertTrue(any('[[Nowhere]]' in e for e in errors))
        self.assertTrue(any('missing section Checks' in e for e in errors))


class KnowledgeTests(Base):
    def test_search_returns_snippets_ranked(self):
        hits = core.search(self.root, 'simulator logs')
        self.assertEqual(hits[0]['path'], 'vault/Runbooks/iOS Simulator debugging.md')
        self.assertTrue(all(len(h['lines']) <= 3 for h in hits))

    def test_lessons_and_feedback(self):
        core.lesson_add(self.root, 'Force unwrap crashed login → guard user input', ['swift'])
        self.assertEqual(len(core.lesson_search(self.root, 'unwrap')), 1)
        self.assertEqual(core.lesson_search(self.root, 'kubernetes'), [])
        core.feedback_add(self.root, 'init should ask for the repo', 'friction')
        self.assertEqual(len(core.feedback_list(self.root)), 1)
        with self.assertRaises(core.WsError):
            core.feedback_add(self.root, 'x', 'rant')

    def test_digest_json_shape_and_log_dedupe(self):
        j = Path(self.tmp.name) / 'a.json'
        j.write_text(json.dumps({'users': [{'id': 1, 'name': 'x'}] * 50, 'ok': True}))
        self.assertEqual(core.digest_file(j)['json_shape']['users'][0], '50 items')
        log = Path(self.tmp.name) / 'b.log'
        log.write_text('start\nerror: failed at 1\nerror: failed at 2\nfine\n')
        d = core.digest_file(log)
        self.assertEqual(d['distinct_problem_lines'], 1)
        self.assertIn('(x2)', d['problems'][0])

    def test_digest_redacts_before_number_normalization(self):
        log = Path(self.tmp.name) / 'log.txt'
        marker = 'password=' + '1' * 16
        log.write_text('error: ' + marker + '\n')
        digest = core.digest_file(log)
        self.assertIn('[REDACTED]', digest['problems'][0])
        self.assertNotIn(marker, json.dumps(digest))

    def test_digest_redacts_json_keys_and_path(self):
        marker = 'secret=' + 'J' * 16
        path = Path(self.tmp.name) / (marker + '.json')
        path.write_text(json.dumps({marker: 1}))
        self.assertNotIn(marker, json.dumps(core.digest_file(path)))

    def test_lesson_feedback_and_run_fields_are_redacted(self):
        markers = ['token=' + 'D' * 16, 'password=' + 'E' * 16,
                   'secret=' + 'F' * 16, 'api_key=' + 'G' * 16,
                   'token=' + 'H' * 16]
        core.lesson_add(self.root, 'A useful rule for the next run', [markers[0]])
        core.feedback_add(self.root, 'An ordinary suggestion', source=markers[1])
        core.run_log(self.root, 'T-1', markers[2], markers[3], model=markers[4])
        files = [self.root / 'vault/Learnings.md', self.root / 'vault/Feedback.md',
                 self.root / 'vault/Runs/T-1.jsonl']
        stored = '\n'.join(path.read_text() for path in files)
        for marker in markers:
            self.assertNotIn(marker, stored)
        self.assertEqual(stored.count('[REDACTED]'), len(markers))

    def test_single_line_labels_reject_newlines(self):
        cases = (
            lambda: core.lesson_add(self.root, 'A useful rule for the next run', ['a\nb']),
            lambda: core.feedback_add(self.root, 'A suggestion', source='a\rb'),
            lambda: core.run_log(self.root, 'T-1', 'a\nb', 'worker'),
            lambda: core.run_log(self.root, 'T-1', 'step', 'worker', model='a\rb'),
        )
        for call in cases:
            with self.subTest(call=call), self.assertRaises(core.WsError):
                call()

    def test_run_log_and_report(self):
        core.run_log(self.root, 'T-1', 'explore', 'codex', 'gpt-6-luna', 1000, 200, 30, 'ok')
        core.run_log(self.root, 'T-1', 'review', 'claude', 'opus', 3000, 400, 20, 'rejected')
        rep = core.run_report(self.root, 'T-1')
        self.assertEqual(rep['steps'], 2)
        self.assertEqual(rep['by_provider']['claude']['failed'], 1)
        with self.assertRaises(core.WsError):
            core.run_log(self.root, 'T-1', 'x', 'codex', result='great')

    def test_doctor_recommends_missing_optional_tools(self):
        with mock.patch.object(core.shutil, 'which', return_value=None), mock.patch.object(core, '_has_app', return_value=False):
            rep = core.doctor(self.root)
        needs = {r['needs'] for r in rep['recommended']}
        self.assertEqual(needs, {'ollama', 'Obsidian', 'codex'})
        self.assertTrue(all('install' in r for r in rep['recommended']))


class MapTests(unittest.TestCase):
    def test_map_fixture_preserves_notes_and_is_available_over_mcp(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo, root = tmp / 'repo', tmp / 'workspace'
            (repo / 'src').mkdir(parents=True)
            (repo / 'README.md').write_text('# Fixture app\n')
            (repo / 'package.json').write_text(json.dumps({'scripts': {'build': 'vite build', 'test': 'vitest', 'dev': 'vite'}}))
            (repo / 'Makefile').write_text('test:\n\tpytest\n')
            (repo / 'src/app.py').write_text('print("app")\n')
            (repo / 'src/util.py').write_text('print("util")\n')
            (repo / 'node_modules/dep').mkdir(parents=True)
            (repo / 'node_modules/dep/index.js').write_text('ignored')
            (repo / '.gitignore').write_text('node_modules/\n')
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=fixture', '-c',
                            'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
            core.init(root, 'fixture', repos=[repo])
            path = root / 'vault/Project/Codebase map.md'
            text = path.read_text()
            self.assertIn('Fixture app', text)
            self.assertIn('Python: 2', text)
            self.assertIn('npm run build', text)
            self.assertIn('make test', text)
            self.assertNotIn('JavaScript', text)
            self.assertNotIn('node_modules', text)
            path.write_text(text + '\n## User notes\nKeep this.\n')
            result = core.codebase_map(root)
            self.assertEqual(result['repo'], str(repo.resolve()))
            self.assertIn('Keep this.', path.read_text())
            reply = server.handle(root, {'jsonrpc': '2.0', 'method': 'tools/call', 'id': 1, 'params': {
                'name': 'codebase_map', 'arguments': {}}})
            self.assertFalse(reply['result']['isError'])


class InterfaceTests(Base):
    def test_mcp_invalid_inputs_keep_server_alive(self):
        bad = [[], None, {'id': 1, 'method': 'ping'},
               {'jsonrpc': '2.0', 'id': True, 'method': 'ping'},
               {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call'},
               {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': None}]
        calls = [('read_task', {'id': 42}), ('read_task', {'id': 'T-1', 'sections': [None]}),
                 ('read_task', {'id': 'T-1', 'extra': True}), ('find_task', []),
                 ('checkpoint', {'id': 'T-1', 'status': 'ready', 'next': 'x', 'notes': {'Evidence': []}}),
                 ('log_step', {'task': 'T-1', 'step': 'x', 'provider': 'x', 'tokens_in': True}),
                 ('log_step', {'task': 'T-1', 'step': 'x', 'provider': 'x', 'seconds': float('inf')})]
        bad += [{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                 'params': {'name': name, 'arguments': args}} for name, args in calls]
        for message in bad:
            with self.subTest(message=message):
                ping = {'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}
                proc = subprocess.run([sys.executable, str(KIT / 'mcp/server.py'), '--root', str(self.root)],
                                      input=json.dumps(message) + '\n' + json.dumps(ping) + '\n',
                                      capture_output=True, text=True, timeout=10)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                replies = list(map(json.loads, proc.stdout.splitlines()))
                self.assertIn(replies[0]['error']['code'], (-32600, -32602))
                self.assertEqual(replies[-1], {'jsonrpc': '2.0', 'id': 2, 'result': {}})
    def test_stop_hook_does_not_repeat_checkpoint_request(self):
        with mock.patch.object(core, 'now', return_value='2020-01-01T00:00:00+00:00'):
            core.claim(self.root, 'T-1', 'synthetic')
        for active in (False, True):
            proc = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'nudge', '--hook'],
                                  cwd=self.root, input=json.dumps({'hook_event_name': 'Stop', 'stop_hook_active': active}),
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            reply = json.loads(proc.stdout)
            self.assertEqual(reply, {} if active else {'decision': 'block', 'reason': core.nudge(self.root)})

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(KIT / 'bin/ws'), *args], cwd=self.root, capture_output=True, text=True)

    def test_cli_round_trip_and_errors(self):
        self.assertEqual(self.run_cli('task', 'find', 'crash').returncode, 0)
        bad = self.run_cli('claim', 'NOPE', '--worker', 'x')
        self.assertEqual(bad.returncode, 2)
        self.assertIn('ws:', bad.stderr)

    def test_mcp_server_handshake_list_and_call(self):
        msgs = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'find_task', 'arguments': {'ref': 'T-1'}}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'read_task', 'arguments': {'id': 'missing'}}},
            {'jsonrpc': '2.0', 'id': 5, 'method': 'nope'},
        ]
        proc = subprocess.run([sys.executable, str(KIT / 'mcp/server.py'), '--root', str(self.root)],
                              input='\n'.join(json.dumps(m) for m in msgs) + '\n', capture_output=True, text=True, timeout=30)
        replies = {r['id']: r for r in map(json.loads, proc.stdout.splitlines())}
        self.assertEqual(set(replies), {1, 2, 3, 4, 5})  # no reply to the notification
        self.assertEqual(replies[1]['result']['serverInfo']['name'], 'ai-dev-workspace')
        names = {t['name'] for t in replies[2]['result']['tools']}
        self.assertTrue({'find_task', 'checkpoint', 'search_vault', 'log_step'} <= names)
        for tool in replies[2]['result']['tools']:
            self.assertNotIn('optional', json.dumps(tool['inputSchema']))
        self.assertIn('T-1', replies[3]['result']['content'][0]['text'])
        self.assertTrue(replies[4]['result']['isError'])
        self.assertEqual(replies[5]['error']['code'], -32601)


class ReleaseFeedbackTests(Base):
    def setUp(self):
        super().setUp()
        self.env = mock.patch.dict(os.environ, {'WS_REPO': 'acme/kit', 'HOME': self.tmp.name, 'WS_OFFLINE': '0'})
        self.env.start()
        self.addCleanup(self.env.stop)
        core.feedback_add(self.root, 'init should ask for the repo; token=abcdefghijklmnop1234', 'friction')

    def test_submit_previews_redacted_until_yes(self):
        prev = core.feedback_submit(self.root, 1)
        self.assertIn('--yes', prev['note'])
        self.assertNotIn('abcdefghijklmnop1234', prev['body'])
        self.assertIn('kit version', prev['body'])

    def test_submit_redacts_title_before_truncation(self):
        marker = 'password=' + 'Q' * 80
        path = self.root / 'vault/Feedback.md'
        path.write_text(path.read_text().replace('[REDACTED]', marker))
        preview = core.feedback_submit(self.root, 1)
        self.assertIn('[REDACTED]', preview['title'])
        self.assertNotIn('password=', preview['title'])
        self.assertNotIn(marker, preview['body'])

    def test_submit_redacts_configured_pack_names_in_body(self):
        marker = 'secret=' + 'K' * 16
        path = self.root / 'workspace.json'
        cfg = json.loads(path.read_text())
        cfg['packs'].append(marker)
        path.write_text(json.dumps(cfg))
        preview = core.feedback_submit(self.root, 1)
        self.assertNotIn(marker, preview['body'])

    def test_submit_without_gh_gives_prefilled_url_then_link_and_sync(self):
        res = core.feedback_submit(self.root, 1, yes=True, use_gh=False)
        self.assertTrue(res['open_this_url'].startswith('https://github.com/acme/kit/issues/new?'))
        self.assertIn('labels=feedback%2Cfriction', res['open_this_url'])
        with self.assertRaises(core.WsError):
            core.feedback_link(self.root, 1, 'https://evil.example/x')
        core.feedback_link(self.root, 1, 'https://github.com/acme/kit/issues/7')
        with self.assertRaises(core.WsError):
            core.feedback_submit(self.root, 1, yes=True, use_gh=False)
        self.assertEqual(core.feedback_sync(self.root, fetch=lambda u: {'state': 'open'})['closed'], [])
        self.assertEqual(core.feedback_sync(self.root, fetch=lambda u: {'state': 'closed'})['closed'],
                         ['https://github.com/acme/kit/issues/7'])
        self.assertTrue(core.feedback_items(self.root)[0]['done'])

    def test_submit_with_gh_records_issue(self):
        fake = mock.Mock(returncode=0, stdout='https://github.com/acme/kit/issues/9\n', stderr='')
        with mock.patch.object(core.subprocess, 'run', return_value=fake) as run:
            res = core.feedback_submit(self.root, 1, yes=True, use_gh='/usr/bin/gh')
        self.assertEqual(res['issue'], 'https://github.com/acme/kit/issues/9')
        self.assertIn('acme/kit', run.call_args[0][0])
        self.assertEqual(core.feedback_items(self.root)[0]['issue'], 'https://github.com/acme/kit/issues/9')

    def test_update_check_compares_versions_and_caches(self):
        calls = []
        def fake(url):
            calls.append(url)
            return {'tag_name': 'v9.0.0', 'body': '- new thing', 'html_url': 'https://github.com/acme/kit/releases/v9.0.0'}
        with mock.patch.object(core, '_get_json', side_effect=fake):
            first = core.check_update(force=True)
            core.check_update()
        self.assertTrue(first['update_available'])
        self.assertEqual(len(calls), 1)
        self.assertIn('latest', core.doctor(self.root)['kit'])
        with mock.patch.object(core, '_get_json', side_effect=OSError('offline')):
            self.assertFalse(core.check_update(force=True)['update_available'])


    def test_notices_suggest_update_fix_and_unshared_feedback(self):
        core.feedback_add(self.root, 'love the digest', 'praise')
        core.feedback_add(self.root, 'search misses plurals', 'bug')
        core.feedback_link(self.root, 2, 'https://github.com/acme/kit/issues/3')
        def fake(url):
            if 'releases' in url:
                return {'tag_name': 'v0.2.0', 'body': '- Faster search', 'html_url': 'u'}
            return {'state': 'closed'}
        with mock.patch.object(core, '_get_json', side_effect=fake) as net:
            kinds = {n['kind']: n for n in core.notices(self.root)}
            again = core.notices(self.root)
        self.assertIn('0.2.0', kinds['update']['message'])
        self.assertIn('Faster search', kinds['update']['message'])
        self.assertEqual(kinds['update']['suggest'], 'ws update')
        self.assertEqual(kinds['fixed']['suggest'], 'ws update --check')
        self.assertEqual(kinds['feedback']['suggest'], 'ws feedback submit 1')  # item 1 unshared; praise not nagged
        self.assertNotIn('fixed', {n['kind'] for n in again})
        self.assertEqual(net.call_count, 2)  # one release check + one issue sync, then cached

    def test_version_order_handles_prereleases(self):
        v = core._vtuple
        self.assertTrue(v('0.1.0-beta.2') > v('0.1.0-beta.1'))
        self.assertTrue(v('0.1.0') > v('0.1.0-beta.9'))
        self.assertTrue(v('v0.2.0-beta.1') > v('0.1.0'))
        self.assertEqual(v('0.1.0'), v('v0.1.0'))

    def test_notices_offline_makes_no_network_calls(self):
        with mock.patch.dict(os.environ, {'WS_OFFLINE': '1'}), mock.patch.object(core, '_get_json', side_effect=AssertionError):
            kinds = [n['kind'] for n in core.notices(self.root)]
        self.assertEqual(kinds, ['feedback'])

    def test_offline_blocks_update_check(self):
        with mock.patch.dict(os.environ, {'WS_OFFLINE': '1'}), mock.patch.object(core, '_get_json', side_effect=AssertionError) as net:
            result = core.check_update(force=True)
        self.assertTrue(result['offline'])
        net.assert_not_called()

    def test_offline_blocks_update_pull(self):
        with mock.patch.dict(os.environ, {'WS_OFFLINE': '1'}), mock.patch.object(core.subprocess, 'run', side_effect=AssertionError) as run:
            result = core.update_kit()
        self.assertTrue(result['offline'])
        run.assert_not_called()

    def test_offline_blocks_feedback_submit(self):
        with mock.patch.dict(os.environ, {'WS_OFFLINE': '1'}), mock.patch.object(core.subprocess, 'run', side_effect=AssertionError) as run:
            result = core.feedback_submit(self.root, 1, yes=True, use_gh='/usr/bin/gh')
        self.assertTrue(result['offline'])
        run.assert_not_called()

    def test_offline_blocks_feedback_sync(self):
        core.feedback_link(self.root, 1, 'https://github.com/acme/kit/issues/7')
        fetch = mock.Mock(side_effect=AssertionError)
        with mock.patch.dict(os.environ, {'WS_OFFLINE': '1'}):
            result = core.feedback_sync(self.root, fetch=fetch)
        self.assertTrue(result['offline'])
        fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
