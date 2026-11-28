import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from bench import rollout_run, rollout_transport
from ws import core


class RolloutDriverTests(unittest.TestCase):
    def test_decisions_driver_saves_two_failed_completions_before_stopping(self):
        from bench import run
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / 'decisions.json'
            completed = {'completed': True}; failed = {'completed': False}
            with mock.patch('sys.argv', ['bench/run.py', '-n', '3', '--output', str(output)]), \
                    mock.patch.object(run.shutil, 'which', return_value='fake-codex'), \
                    mock.patch.object(run, 'command', return_value=SimpleNamespace(stdout='fixture')), \
                    mock.patch.object(run, 'create', side_effect=lambda root, data: root.mkdir()), \
                    mock.patch.object(run, 'prepare_snapshot'), \
                    mock.patch.object(run, 'score', return_value={'tests_pass': False, 'checks': {}}), \
                    mock.patch.object(run, 'session', side_effect=[completed, failed.copy(), failed.copy()]) as worker, \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'two consecutive transport failures'): run.main()
            self.assertEqual(worker.call_count, 3)
            result = json.loads(output.read_text())
            self.assertEqual(len(result['runs']), 2)
            self.assertFalse(any(row['success'] for row in result['runs']))

    def test_two_failed_transports_stop_and_keep_both_attempts(self):
        with tempfile.TemporaryDirectory() as d:
            args = argparse.Namespace(n=5, seed=42, output=Path(d) / 'result.json')
            benchmark = SimpleNamespace(seed=lambda n: n,
                trial=mock.Mock(side_effect=lambda *a: {'result': 'inconclusive', 'calls': [{'completed': False, 'exit_code': 1}]}),
                run=SimpleNamespace(KIT=Path(d), command=lambda *a: SimpleNamespace(stdout='fixture')))
            with contextlib.redirect_stdout(io.StringIO()):
                completed = rollout_run.run_trials(benchmark, args, Path(d) / 'absent-auth')
            self.assertFalse(completed)
            self.assertEqual(benchmark.trial.call_count, 2)
            result = json.loads(args.output.read_text())
            self.assertEqual(len(result['runs']), 2)
            self.assertEqual(result['stopped'], 'two consecutive transport failures')

    @unittest.skipIf(os.name == 'nt', 'Rollout fixtures and process isolation are proved on POSIX')
    def test_prepared_memory_is_saved_before_completion_changes_it(self):
        from bench import rollout
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {'HOME': d, 'CODEX_HOME': d + '/.codex'}):
            root = Path(d) / 'fixture'; calls = []
            expected = rollout.seed(42)
            def worker(root, home, prompt, workspace, auth, *args):
                calls.append(prompt)
                if len(calls) == 1: (root / 'repo/.step-log').write_text('prepare\n')
                if len(calls) == 2:
                    core.checkpoint(root, 'BENCH-1', 'in_progress', 'Finish the manifest.',
                                    notes={'Handoff': 'Decision: use cobalt.'})
                if len(calls) == 3:
                    core.checkpoint(root, 'BENCH-1', 'in_progress', 'Completed.', notes={'Handoff': 'Completion note.'})
                    rollout.reference(root / 'repo', expected)
                return {'completed': True}, 'done', 'synthetic-session'
            with mock.patch.object(rollout, 'session', side_effect=worker), mock.patch.object(rollout, 'cost', return_value=None):
                result = rollout.trial(root, expected, 'workspace', Path(d) / 'absent-auth')
            self.assertIn('use cobalt', result['prepared_memory']['brief'])
            self.assertIn('use cobalt', result['prepared_memory']['handoff'])
            self.assertNotIn('Completion note', result['prepared_memory']['handoff'])
            self.assertEqual(result['catchup']['health']['outcome'], 'not_run')
            self.assertFalse(result['catchup']['health_updated'])

    @unittest.skipIf(os.name == 'nt', 'Rollout fixtures require POSIX')
    def test_workspace_replays_real_catchup_before_snapshot_with_isolated_completion(self):
        from bench import rollout
        sid = '11111111-1111-4111-8111-111111111111'
        for arm in ('workspace', 'workspace-explicit'):
            with self.subTest(arm=arm), tempfile.TemporaryDirectory() as d, \
                    mock.patch.dict(os.environ, {'HOME': d, 'CODEX_HOME': d + '/.codex', 'WS_OFFLINE': '1'}):
                root = Path(d).resolve() / 'fixture'; expected = rollout.seed(42); calls = []; seen = {}
                def message(role, value):
                    return {'type': 'response_item', 'payload': {'type': 'message', 'role': role,
                        'content': [{'type': 'input_text' if role == 'user' else 'output_text', 'text': value}]}}
                def worker(root, home, prompt, workspace, auth, *args):
                    calls.append(home)
                    if len(calls) == 1:
                        (root / 'repo/.step-log').write_text('prepare\n')
                        path = home / '.codex/sessions/2026/11/28' / ('rollout-' + sid + '.jsonl')
                        path.parent.mkdir(parents=True, exist_ok=True); seen['source'] = path
                        entries = [ {'type': 'session_meta', 'payload': {'id': sid, 'timestamp': '2026-11-28T01:00:00Z'}},
                                    message('user', 'Decided: only ' + expected['old_lane'] + '.'),
                                    {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'read_file'}},
                                    message('assistant', 'Next step: investigate.')]
                        path.write_text('\n'.join(map(json.dumps, entries)) + '\n')
                        with mock.patch.dict(os.environ, {'HOME': str(home), 'CODEX_HOME': str(home / '.codex')}):
                            self.assertTrue(core.capture_decisions(root, str(path), 'codex', 'BENCH-1', sid))
                    elif len(calls) == 2:
                        with seen['source'].open('a') as f:
                            f.write(json.dumps(message('user', 'Correction: decided to use ' + expected['lane'] + '; only receipt ' + expected['receipt'] + ' is valid.')) + '\n')
                    else:
                        self.assertNotEqual(home, calls[0])
                        self.assertFalse((home / '.codex/sessions').exists())
                        self.assertFalse(seen['source'].exists(), 'investigation transcript must be removed before completion')
                        self.assertFalse(calls[0].exists(), 'investigation home must not be exposed to completion')
                        rollout.reference(root / 'repo', expected)
                    return {'completed': True}, 'done', sid
                with mock.patch.object(rollout, 'session', side_effect=worker), mock.patch.object(rollout, 'cost', return_value=None):
                    result = rollout.trial(root, expected, arm, Path(d) / 'absent-auth')
                self.assertEqual(result['catchup']['exit_code'], 0)
                self.assertEqual(result['catchup']['health']['outcome'], 'captured')
                self.assertTrue(result['catchup']['health_updated'])
                self.assertIn(expected['lane'], result['prepared_memory']['handoff'])
                self.assertIn(expected['receipt'], result['prepared_memory']['handoff'])
                self.assertIn(expected['lane'], result['prepared_memory']['brief'])
                self.assertEqual(len(calls), 3)

    @unittest.skipIf(os.name == 'nt', 'Rollout fixtures require POSIX')
    def test_non_workspace_arms_do_not_replay_catchup_or_share_homes(self):
        from bench import rollout
        for arm in ('baseline', 'markdown'):
            with self.subTest(arm=arm), tempfile.TemporaryDirectory() as d:
                calls = []
                def worker(root, home, prompt, workspace, auth, *args):
                    calls.append(home)
                    if len(calls) == 1:
                        (root / 'repo/.step-log').write_text('prepare\n')
                        home.mkdir(parents=True); (home / 'unchanged-marker').write_text('fixture')
                    if len(calls) == 3:
                        self.assertNotEqual(home, calls[0])
                        self.assertFalse((home / '.codex/sessions').exists())
                        self.assertTrue((calls[0] / 'unchanged-marker').exists())
                    return {'completed': True}, 'done', 'fixture-session'
                with mock.patch.object(rollout, 'session', side_effect=worker), \
                        mock.patch.object(rollout, 'cost', return_value=None), \
                        mock.patch.object(rollout, 'replay_session_start', side_effect=AssertionError('unexpected catch-up')) as replay:
                    result = rollout.trial(Path(d) / 'fixture', rollout.seed(42), arm, Path(d) / 'absent-auth')
                replay.assert_not_called()
                self.assertNotIn('catchup', result)
                self.assertEqual(len(calls), 3)

    @unittest.skipIf(os.name == 'nt', 'Symlink fixture requires POSIX')
    def test_catchup_refuses_symlinked_investigation_home(self):
        from bench import rollout
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); root = base / 'root'; root.mkdir()
            outside = base / 'outside'; outside.mkdir()
            home = base / 'home'; home.symlink_to(outside, target_is_directory=True)
            with mock.patch.object(rollout.subprocess, 'run') as execute:
                result = rollout.replay_session_start(root, home)
            self.assertEqual(result['error'], 'unsafe_home')
            self.assertIsNone(result['exit_code'])
            execute.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'Rollout fixtures require POSIX')
    def test_failed_catchup_is_recorded_and_does_not_start_completion(self):
        from bench import rollout
        with tempfile.TemporaryDirectory() as d:
            calls = []
            def worker(root, home, prompt, workspace, auth, *args):
                calls.append(home)
                if len(calls) == 1: (root / 'repo/.step-log').write_text('prepare\n')
                return {'completed': True}, 'done', 'fixture-session'
            failure = {'exit_code': 7, 'health': {'outcome': 'not_run', 'reason': 'not_run'}, 'health_updated': False}
            with mock.patch.object(rollout, 'session', side_effect=worker), \
                    mock.patch.object(rollout, 'replay_session_start', return_value=failure):
                result = rollout.trial(Path(d) / 'fixture', rollout.seed(42), 'workspace', Path(d) / 'absent-auth')
            self.assertEqual(result['result'], 'inconclusive')
            self.assertEqual(result['catchup'], failure)
            self.assertEqual(len(calls), 2)

    @unittest.skipIf(os.name == 'nt', 'Rollout fixtures require POSIX')
    def test_explicit_workspace_prompt_and_original_arm_prompts(self):
        from bench import rollout
        expected = rollout.seed(42)
        for arm in ('baseline', 'workspace', 'markdown', 'verbatim', 'workspace-explicit'):
            with self.subTest(arm=arm), tempfile.TemporaryDirectory() as d, \
                    mock.patch.dict(os.environ, {'HOME': d, 'CODEX_HOME': d + '/.codex'}):
                calls = []
                def worker(root, home, prompt, workspace, auth, *args):
                    calls.append((prompt, workspace))
                    if len(calls) == 1:
                        (root / 'repo/.step-log').write_text('prepare\n')
                    return {'completed': True}, '', 'synthetic-session'
                # The existing verbatim candidate invokes the workspace trial unchanged.
                trial_arm = 'workspace' if arm == 'verbatim' else arm
                with mock.patch.object(rollout, 'session', side_effect=worker):
                    result = rollout.trial(Path(d) / 'fixture', expected, trial_arm, Path(d) / 'no-auth')
                correction = rollout.DATA['correct'].format(**expected)
                if arm == 'markdown':
                    suffix = ' Save these facts and the next step in HANDOFF.md outside repo.'
                elif arm == 'workspace-explicit':
                    suffix = (' Save the corrected facts and the next step with `ws checkpoint BENCH-1 '
                              '--status in_progress --next "<exact next step>" --note "Handoff=<corrected facts>"`; '
                              'never write a hand-written file.')
                else:
                    suffix = ' Do not write notes manually; stop now.'
                self.assertEqual(calls[0][0].encode(), rollout.DATA['investigate'].format(**expected).encode())
                self.assertEqual(calls[1][0].encode(), (correction + suffix).encode())
                self.assertEqual(calls[2][0].encode(), rollout.DATA['complete'].encode())
                self.assertEqual(calls[1][1], arm in ('workspace', 'verbatim', 'workspace-explicit'))
                self.assertEqual(result['arm'], trial_arm)

    def test_fifth_arm_is_appended_with_the_same_seeds_and_recorded_name(self):
        with tempfile.TemporaryDirectory() as d:
            args = argparse.Namespace(n=5, seed=42, output=Path(d) / 'result.json', verbatim_kit=Path(d) / 'candidate')
            seen = []
            def trial(root, expected, arm, auth):
                seen.append((arm, expected))
                return {'arm': arm, 'result': 'pass', 'calls': [{'completed': True}]}
            def candidate(kit, root, expected, auth, benchmark):
                return trial(root, expected, 'verbatim', auth)
            benchmark = SimpleNamespace(seed=lambda n: n, trial=trial,
                run=SimpleNamespace(KIT=Path(d), HERE=Path(d) / 'bench',
                    command=lambda command, path: SimpleNamespace(stdout='' if command[-1] == '--porcelain' else 'fixture')))
            with mock.patch.object(rollout_run, 'candidate_trial', side_effect=candidate), contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(rollout_run.run_trials(benchmark, args, Path(d) / 'no-auth'))
            result = json.loads(args.output.read_text())
            order = ('baseline', 'workspace', 'markdown', 'verbatim', 'workspace-explicit')
            for i in range(5):
                self.assertEqual(seen[i*5:i*5+5], [(arm, 42+i) for arm in order])
                self.assertEqual([row['arm'] for row in result['runs'][i*5:i*5+5]], list(order))
                self.assertEqual([row['seed_index'] for row in result['runs'][i*5:i*5+5]], [i]*5)

    def test_five_arms_use_same_seeds_and_persist_all_50_trials(self):
        with tempfile.TemporaryDirectory() as d:
            args = argparse.Namespace(n=10, seed=42, output=Path(d) / 'result.json',
                                      verbatim_kit=Path(d) / 'candidate')
            seen = []
            def normal(root, expected, arm, auth):
                seen.append((arm, expected))
                return {'arm': arm, 'result': 'pass', 'calls': [{'completed': True}]}
            def candidate(kit, root, expected, auth, benchmark):
                seen.append(('verbatim', expected))
                return {'arm': 'verbatim', 'result': 'pass', 'calls': [{'completed': True}]}
            benchmark = SimpleNamespace(seed=lambda n: n, trial=normal,
                run=SimpleNamespace(KIT=Path(d), HERE=Path(d) / 'bench',
                                    command=lambda command, path: SimpleNamespace(stdout='' if command[-1] == '--porcelain' else 'fixture')))
            with mock.patch.object(rollout_run, 'candidate_trial', side_effect=candidate), \
                    contextlib.redirect_stdout(io.StringIO()):
                completed = rollout_run.run_trials(benchmark, args, Path(d) / 'absent-auth')
            self.assertTrue(completed)
            result = json.loads(args.output.read_text())
            self.assertEqual(len(result['runs']), 50)
            for index in range(10):
                self.assertEqual(seen[index * 5:index * 5 + 5],
                                 [(arm, 42 + index) for arm in ('baseline', 'workspace', 'markdown', 'verbatim', 'workspace-explicit')])
                self.assertEqual([run['seed_index'] for run in result['runs'][index * 5:index * 5 + 5]], [index] * 5)

    def test_fourth_arm_refuses_dirty_candidate_before_running_models(self):
        with tempfile.TemporaryDirectory() as d:
            args = argparse.Namespace(n=10, seed=42, output=Path(d) / 'result.json',
                                      verbatim_kit=Path(d) / 'candidate')
            benchmark = SimpleNamespace(seed=lambda n: n, trial=mock.Mock(),
                run=SimpleNamespace(KIT=Path(d), HERE=Path(d) / 'bench',
                    command=lambda command, path: SimpleNamespace(stdout=' M ws/core.py' if command[-1] == '--porcelain' else 'fixture')))
            with self.assertRaisesRegex(RuntimeError, 'candidate checkout must be clean'):
                rollout_run.run_trials(benchmark, args, Path(d) / 'absent-auth')
            benchmark.trial.assert_not_called()

    def test_changed_candidate_invalidates_the_trial_and_keeps_prior_results(self):
        with tempfile.TemporaryDirectory() as d:
            candidate = Path(d) / 'candidate'
            args = argparse.Namespace(n=10, seed=42, output=Path(d) / 'result.json',
                                      verbatim_kit=candidate)
            status_checks = 0
            def command(argv, path):
                nonlocal status_checks
                if path == candidate and argv[-1] == '--porcelain':
                    status_checks += 1
                    return SimpleNamespace(stdout=' M ws/core.py' if status_checks >= 3 else '')
                return SimpleNamespace(stdout='fixture' if argv[-1] == 'HEAD' else '')
            benchmark = SimpleNamespace(seed=lambda n: n,
                trial=lambda root, expected, arm, auth: {'arm': arm, 'result': 'pass', 'calls': [{'completed': True}]},
                run=SimpleNamespace(KIT=Path(d), HERE=Path(d) / 'bench', command=command))
            with mock.patch.object(rollout_run, 'candidate_trial', return_value={'arm': 'verbatim', 'result': 'pass', 'calls': [{'completed': True, 'input_tokens': 10}]}), \
                    contextlib.redirect_stdout(io.StringIO()):
                completed = rollout_run.run_trials(benchmark, args, Path(d) / 'absent-auth')
            self.assertFalse(completed)
            result = json.loads(args.output.read_text())
            self.assertEqual([run['result'] for run in result['runs']], ['pass', 'pass', 'pass', 'inconclusive'])
            self.assertEqual(result['runs'][-1]['seed_index'], 0)
            self.assertEqual(result['runs'][-1]['calls'][0]['input_tokens'], 10)

    def test_candidate_failure_saves_the_failed_attempt_and_stops(self):
        with tempfile.TemporaryDirectory() as d:
            args = argparse.Namespace(n=10, seed=42, output=Path(d) / 'result.json',
                                      verbatim_kit=Path(d) / 'candidate')
            benchmark = SimpleNamespace(seed=lambda n: n,
                trial=lambda root, expected, arm, auth: {'arm': arm, 'result': 'pass', 'calls': [{'completed': True}]},
                run=SimpleNamespace(KIT=Path(d), HERE=Path(d) / 'bench',
                                    command=lambda command, path: SimpleNamespace(stdout='' if command[-1] == '--porcelain' else 'fixture')))
            with mock.patch.object(rollout_run, 'candidate_trial', side_effect=RuntimeError('fixture failure')), \
                    contextlib.redirect_stdout(io.StringIO()):
                completed = rollout_run.run_trials(benchmark, args, Path(d) / 'absent-auth')
            self.assertFalse(completed)
            result = json.loads(args.output.read_text())
            self.assertEqual(result['seed'], 42)
            self.assertEqual(len(result['runs']), 4)
            self.assertEqual(result['runs'][-1]['arm'], 'verbatim')
            self.assertEqual(result['runs'][-1]['result'], 'inconclusive')
            self.assertIn('candidate arm', result['stopped'])

    def test_candidate_trial_imports_candidate_ws_and_existing_benchmark_fixture(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            kit, harness = base / 'candidate', base / 'harness'
            (kit / 'ws').mkdir(parents=True)
            (kit / 'ws/__init__.py').write_text('')
            (kit / 'ws/core.py').write_text('MARKER = "candidate"\n')
            (harness / 'bench').mkdir(parents=True)
            (harness / 'bench/run.py').write_text('KIT = None\n')
            (harness / 'bench/rollout.py').write_text(
                'from bench import run\nfrom ws import core\n'
                'def trial(root, expected, arm, auth):\n'
                '    return {"arm": arm, "marker": core.MARKER, "kit": str(run.KIT), "expected": expected}\n')
            benchmark = SimpleNamespace(run=SimpleNamespace(HERE=harness / 'bench'))
            result = rollout_run.candidate_trial(kit, base / 'trial', {'fixture': 42},
                                                  base / 'absent-auth', benchmark)
            self.assertEqual(result, {'arm': 'verbatim', 'marker': 'candidate',
                                      'kit': str(kit.resolve()), 'expected': {'fixture': 42}})

    def test_interruption_keeps_completed_runs_without_seed_hints(self):
        with tempfile.TemporaryDirectory() as d:
            args = argparse.Namespace(n=5, seed=42, output=Path(d) / 'result.json')
            benchmark = SimpleNamespace(seed=lambda n: n, trial=mock.Mock(side_effect=[{'arm': 'baseline', 'result': 'abstention'}, RuntimeError('interrupted')]),
                run=SimpleNamespace(KIT=Path(d), command=lambda *a: SimpleNamespace(stdout='fixture')))
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                rollout_run.run_trials(benchmark, args, Path(d) / 'absent-auth')
            result = json.loads(args.output.read_text())
            self.assertEqual(len(result['runs']), 1); self.assertIsNone(result['seed'])
            benchmark.trial.side_effect = None; benchmark.trial.return_value = {'result': 'pass'}
            with contextlib.redirect_stdout(io.StringIO()): rollout_run.run_trials(benchmark, args, Path(d) / 'absent-auth')
            result = json.loads(args.output.read_text())
            self.assertEqual(result['seed'], 42); self.assertEqual(len(result['runs']), 20)


@unittest.skipIf(os.name == "nt", "Owned process cleanup uses POSIX process groups.")
class RolloutTransportTests(unittest.TestCase):
    def test_codex_event_stream_records_ordered_names_without_payloads(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {'WS_BENCH_PROVIDER': 'codex'}):
            root = Path(d); home = root / 'home'
            secret = 'PRIVATE_CANARY_741'
            def event(kind, ident, item_type, **fields):
                return {'type': kind, 'item': dict(id=ident, type=item_type, **fields)}
            events = [
                {'type': 'thread.started', 'thread_id': 'fixture-thread'},
                event('item.started', 'a', 'command_execution', command="/bin/zsh -lc 'ws brief --task PRIVATE_CANARY_741'"),
                event('item.started', 'b', 'command_execution', command='cat /private/PRIVATE_CANARY_741'),
                event('item.completed', 'b', 'command_execution', command='cat /private/PRIVATE_CANARY_741', aggregated_output=secret),
                event('item.completed', 'a', 'command_execution', command="/bin/zsh -lc 'ws brief --task PRIVATE_CANARY_741'", aggregated_output=secret),
                event('item.completed', 'c', 'mcp_tool_call', server=secret, tool='read_task', arguments={'path': secret}, result=secret),
                event('item.completed', 'd', 'command_execution', command='python3 /private/PRIVATE_CANARY_741'),
                event('item.completed', 'e', 'command_execution', command=secret + ' --arg'),
                {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 10}},
            ]
            worker = mock.Mock(returncode=0)
            worker.communicate.return_value = ('\n'.join(json.dumps(e) for e in events), '')
            with mock.patch.object(rollout_transport.subprocess, 'Popen', return_value=worker):
                call, _, _ = rollout_transport.session(root, home, 'fixture prompt', True, root / 'no-auth')
            self.assertEqual(call['tool_names'], ['ws brief', 'cat', 'mcp:read_task', 'python3', 'other'])
            self.assertNotIn(secret, json.dumps(call))
            self.assertNotIn('/private/', json.dumps(call))
            result_file = root / 'trial.json'
            rollout_run.save(result_file, {'seed': 42, 'runs': [{'calls': [call]}]})
            saved = json.loads(result_file.read_text())['runs'][0]['calls'][0]['tool_names']
            self.assertEqual(saved, ['ws brief', 'cat', 'mcp:read_task', 'python3', 'other'])
            self.assertNotIn(secret, result_file.read_text())

    def test_shell_names_never_include_untrusted_arguments_or_paths(self):
        cases = (
            ('ws --workspace-root /private/SECRET_741 checkpoint --note SECRET_741', 'ws checkpoint'),
            ('/usr/bin/python3 /private/SECRET_741', 'python3'),
            ('ws SECRET_741 --arg', 'ws'),
            ('/private/SECRET_741 --arg', 'other'),
            ('SECRET_741=secret', 'other'),
            ("bash -lc 'unterminated", 'other'),
        )
        for command, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(rollout_transport.shell_name(command), expected)

    def test_claude_event_stream_records_names_without_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); worker = mock.Mock(returncode=0)
            events = [
                {'type': 'assistant', 'message': {'content': [
                    {'type': 'tool_use', 'name': 'Read', 'input': {'file_path': '/private/SECRET_741'}},
                    {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'ws checkpoint BENCH-1 --note SECRET_741'}},
                    {'type': 'tool_use', 'name': 'mcp__ai-dev-workspace__brief', 'input': {'text': 'SECRET_741'}},
                    {'type': 'tool_use', 'name': 'SECRET_741', 'input': {}},
                ]}},
                {'type': 'result', 'session_id': 'fixture', 'result': '', 'usage': {}},
            ]
            worker.communicate.return_value = ('\n'.join(json.dumps(e) for e in events), '')
            with mock.patch.object(rollout_transport.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='2.1.300')), \
                    mock.patch.object(rollout_transport.subprocess, 'Popen', return_value=worker):
                call, _, _ = rollout_transport.claude_session(root, root / 'home', 'fixture', False)
            self.assertEqual(call['tool_names'], ['Read', 'ws checkpoint', 'mcp:brief', 'other'])
            self.assertNotIn('SECRET_741', json.dumps(call))
            self.assertNotIn('/private/', json.dumps(call))

    def test_claude_transport_does_not_inherit_secret_environment(self):
        allowed = {'PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TMPDIR', 'SHELL', 'TERM',
                   'WS_OFFLINE', 'WS_ROOT', 'PYTHONDONTWRITEBYTECODE'}
        fake_secrets = {'ANTHROPIC_API_KEY': 'fake-anthropic', 'OPENAI_API_KEY': 'fake-openai',
                        'GH_TOKEN': 'fake-gh', 'GITHUB_TOKEN': 'fake-github', 'WS_FAKE_SECRET': 'fake-other'}
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, fake_secrets):
            worker = mock.Mock(returncode=0)
            worker.communicate.return_value = ('{"type":"result","usage":{}}', '')
            with mock.patch.object(rollout_transport.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='2.1.300')) as version, \
                    mock.patch.object(rollout_transport.subprocess, 'Popen', return_value=worker) as launch:
                rollout_transport.claude_session(Path(d), Path(d) / 'home', 'synthetic', False)
            for child_env in (version.call_args.kwargs['env'], launch.call_args.kwargs['env']):
                self.assertTrue(set(child_env) <= allowed)
                self.assertTrue(fake_secrets.keys().isdisjoint(child_env))
                self.assertNotEqual(child_env['HOME'], os.environ.get('HOME'))

    def test_claude_benchmark_does_not_inherit_secret_environment(self):
        allowed = {'PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TMPDIR', 'SHELL', 'TERM',
                   'WS_OFFLINE', 'WS_ROOT', 'PYTHONDONTWRITEBYTECODE'}
        fake_secrets = {'ANTHROPIC_API_KEY': 'fake-anthropic', 'OPENAI_API_KEY': 'fake-openai',
                        'GH_TOKEN': 'fake-gh', 'GITHUB_TOKEN': 'fake-github', 'WS_FAKE_SECRET': 'fake-other'}
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, fake_secrets):
            worker = mock.Mock(returncode=0)
            worker.communicate.return_value = ('{"type":"result","usage":{}}', '')
            with mock.patch.object(rollout_transport.run.subprocess, 'Popen', return_value=worker) as launch:
                rollout_transport.run.session(Path(d), 'synthetic', 'claude', 'sonnet', False, Path(d) / 'absent')
            child_env = launch.call_args.kwargs['env']
            self.assertTrue(set(child_env) <= allowed)
            self.assertTrue(fake_secrets.keys().isdisjoint(child_env))
            self.assertNotEqual(child_env['HOME'], os.environ.get('HOME'))

    def test_claude_transport_isolates_home_and_preserves_resume(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {'WS_BENCH_PROVIDER': 'claude'}):
            root = Path(d) / 'fixture'; root.mkdir()
            home = Path(d) / 'home'
            worker = mock.Mock(returncode=0)
            worker.communicate.return_value = ('not json\n[]\n' + json.dumps({'type': 'result', 'session_id': 'synthetic-session',
                'result': 'Saved synthetic decision.', 'usage': {'input_tokens': 7, 'output_tokens': 3}, 'total_cost_usd': 0.01}), '')
            with mock.patch.object(rollout_transport.subprocess, 'Popen', return_value=worker) as launch, \
                    mock.patch.object(rollout_transport.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='2.1.300 (Claude Code)')):
                result, message, session = rollout_transport.session(root, home, 'synthetic prompt', False, Path(d) / 'absent', resume='prior-session')
            args = launch.call_args.args[0]; env = launch.call_args.kwargs['env']
            self.assertEqual(env['HOME'], str(home))
            self.assertNotIn('CLAUDE_CONFIG_DIR', env)
            self.assertEqual(args[args.index('--resume') + 1], 'prior-session')
            self.assertEqual(args[args.index('--mcp-config') + 1], '{"mcpServers": {}}')
            policy = json.loads(args[args.index('--settings') + 1])
            self.assertTrue(policy['permissions']['blockReadsOutsideWorkingDirectories'])
            self.assertTrue(policy['sandbox']['failIfUnavailable'])
            self.assertFalse(policy['sandbox']['allowUnsandboxedCommands'])
            self.assertFalse(policy['sandbox']['autoAllowBashIfSandboxed'])
            allowed = args[args.index('--allowedTools') + 1:args.index('--max-turns')]
            self.assertNotIn('Bash', allowed)
            self.assertTrue(result['completed']); self.assertEqual(result['input_tokens'], 7)
            self.assertEqual((message, session), ('Saved synthetic decision.', 'synthetic-session'))

    def test_claude_rejects_unsupported_isolation_version(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(rollout_transport.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='2.1.100')), \
                mock.patch.object(rollout_transport.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(RuntimeError, 'no fallback'):
                rollout_transport.claude_session(Path(d), Path(d) / 'home', 'synthetic', False)
            launch.assert_not_called()

    def test_claude_workspace_without_mcp_is_not_run(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(rollout_transport.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='2.1.300')), \
                mock.patch.object(rollout_transport.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(RuntimeError, 'MCP'):
                rollout_transport.claude_session(Path(d), Path(d) / 'home', 'synthetic', True)
            launch.assert_not_called()

    def test_claude_workspace_allows_only_its_mcp_server_tools(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / '.mcp.json').write_text(json.dumps({'mcpServers': {'ai-dev-workspace': core.mcp_command(root)}}))
            worker = mock.Mock(returncode=0); worker.communicate.return_value = ('{"type":"result","session_id":"synthetic","usage":{}}', '')
            with mock.patch.object(rollout_transport.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='2.1.300')), \
                    mock.patch.object(rollout_transport.subprocess, 'Popen', return_value=worker) as launch:
                rollout_transport.claude_session(root, root / 'home', 'synthetic', True)
            args = launch.call_args.args[0]
            allowed = args[args.index('--allowedTools') + 1:args.index('--max-turns')]
            self.assertIn('mcp__ai-dev-workspace__*', allowed)
            self.assertNotIn('mcp__*', allowed)
            self.assertIn('ai-dev-workspace', args[args.index('--mcp-config') + 1])

    def test_claude_rejects_replaced_fixture_mcp_command(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(rollout_transport.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='2.1.300')), \
                mock.patch.object(rollout_transport.subprocess, 'Popen') as launch:
            root = Path(d); (root / '.mcp.json').write_text('{"mcpServers":{"ai-dev-workspace":{"command":"synthetic-untrusted"}}}')
            with self.assertRaisesRegex(RuntimeError, 'MCP'):
                rollout_transport.claude_session(root, root / 'home', 'synthetic', True)
            launch.assert_not_called()

    def test_claude_interrupt_stops_owned_worker_group(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(rollout_transport.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='2.1.300')):
            worker = mock.Mock(pid=12345)
            worker.communicate.side_effect = [KeyboardInterrupt, ('', '')]
            with mock.patch.object(rollout_transport.subprocess, 'Popen', return_value=worker), mock.patch.object(rollout_transport.os, 'killpg') as stop:
                with self.assertRaises(KeyboardInterrupt):
                    rollout_transport.claude_session(Path(d), Path(d) / 'home', 'synthetic', False)
                stop.assert_called_once_with(12345, rollout_transport.signal.SIGKILL)

    def test_interrupt_stops_owned_worker_group(self):
        with tempfile.TemporaryDirectory() as d:
            worker = mock.Mock(pid=12345)
            worker.communicate.side_effect = [KeyboardInterrupt, ('', '')]
            with mock.patch.object(rollout_transport.subprocess, 'Popen', return_value=worker), mock.patch.object(rollout_transport.os, 'killpg') as stop:
                with self.assertRaises(KeyboardInterrupt):
                    rollout_transport.session(Path(d), Path(d) / 'home', 'synthetic', False, Path(d) / 'absent-auth')
                stop.assert_called_once_with(12345, rollout_transport.signal.SIGKILL)

    def test_resumed_usage_counts_only_increment(self):
        events = [{'type': 'turn.completed', 'usage': {'input_tokens': 17, 'output_tokens': 4, 'cached_input_tokens': 8}}]
        result = rollout_transport.usage(events, 0, {'input_tokens': 12, 'output_tokens': 1, 'cache_read_tokens': 4})
        self.assertEqual((result['input_tokens'], result['output_tokens'], result['cache_read_tokens']), (5, 3, 4))
