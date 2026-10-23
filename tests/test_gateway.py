import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from test_ws import Base
from ws import cli, core, orchestration

ENV = 'WS_TEST_GATEWAY_KEY'
KEY = 'gw' + '-secret-' + 'value' + '-0123456789'  # built from parts; never a real credential


class Fake:
    """Local OpenAI-compatible server on 127.0.0.1 and a random port; records every request."""
    def __init__(self, status=200, content='UNVERIFIED sample.py:1 gateway finding', delay=0, location=None):
        self.requests = []; outer = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                outer.requests.append(dict(path=self.path, auth=self.headers.get('Authorization'), body=json.loads(body or b'{}')))
                time.sleep(delay)
                if location:
                    self.send_response(302); self.send_header('Location', location); self.end_headers(); return
                text = content.replace('{key}', KEY)
                payload = json.dumps({'choices': [{'message': {'content': text}}], 'usage': {'prompt_tokens': 7, 'completion_tokens': 3}}) if status == 200 \
                    else json.dumps({'error': 'bad key ' + KEY})
                self.send_response(status); self.send_header('Content-Type', 'application/json'); self.end_headers()
                try: self.wfile.write(payload.encode())
                except OSError: pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/v1'

    def close(self): self.server.shutdown(); self.server.server_close()


class GatewayTests(Base):
    def serve(self, **kw):
        fake = Fake(**kw); self.addCleanup(fake.close); return fake

    def configure(self, url, preference=None, **entry):
        path = self.root / 'routing.json'; data = json.loads(path.read_text())
        data['_ws_managed']['providers']['gw'] = dict({'kind': 'openai-compatible', 'base_url': url, 'model': 'test-model', 'api_key_env': ENV}, **entry)
        data['role_overrides']['explorer'] = {'preference': preference or ['gw']}
        path.write_text(json.dumps(data))

    def environ(self, **extra):
        directory = self.root / 'gw-bin'; directory.mkdir(exist_ok=True)
        return mock.patch.dict(os.environ, dict({ENV: KEY, 'PATH': str(directory)}, **extra))

    def codex(self, code):
        directory = self.root / 'gw-bin'; directory.mkdir(exist_ok=True)
        path = directory / ('codex.cmd' if os.name == 'nt' else 'codex')
        if os.name == 'nt':
            (directory / 'codex.py').write_text(code + '\n'); path.write_text('@echo off\n"' + sys.executable + '" "' + str(directory / 'codex.py') + '" %*\n')
        else:
            path.write_text('#!' + sys.executable + '\n' + code + '\n'); path.chmod(0o755)

    def assertKeyAbsent(self, *texts):
        for text in texts: self.assertNotIn(KEY, text)
        for path in self.root.rglob('*'):
            if path.is_file() and not path.is_symlink():
                try: self.assertNotIn(KEY, path.read_text(errors='replace'), str(path))
                except OSError: pass

    def test_run_posts_the_brief_with_the_key_from_env_and_logs_usage(self):
        fake = self.serve()
        self.configure(fake.url)
        # A dead proxy in the environment must not be used for a loopback gateway.
        with self.environ(HTTP_PROXY='http://127.0.0.1:9', http_proxy='http://127.0.0.1:9'):
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(len(fake.requests), 1)
        request = fake.requests[0]
        self.assertEqual(request['path'], '/v1/chat/completions')
        self.assertEqual(request['auth'], 'Bearer ' + KEY)
        self.assertEqual(request['body']['model'], 'test-model')
        self.assertIn('Bounded delegation', request['body']['messages'][0]['content'])
        self.assertIn('gateway finding', Path(result['output']).read_text())
        entry = core.run_entries(self.root, 'T-1')[0]
        self.assertEqual((entry['provider'], entry['model'], entry['result'], entry['tokens_in'], entry['tokens_out']), ('gw', 'test-model', 'ok', 7, 3))
        self.assertIn('never stored', result['command'])
        self.assertKeyAbsent(json.dumps(result), cli.readable(result), result['command'])

    def test_key_is_scrubbed_from_replies_and_errors(self):
        self.configure(self.serve(content='the key is {key}').url)
        with self.environ():
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
        self.assertIn('[REDACTED]', Path(result['output']).read_text())
        self.assertKeyAbsent(json.dumps(result))
        failing = self.serve(status=500)
        self.configure(failing.url)
        with self.environ():
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
        self.assertEqual(result['exit_code'], 1)
        self.assertIn('HTTP 500', Path(result['output']).read_text())
        self.assertKeyAbsent(json.dumps(result))

    def test_nothing_is_sent_unless_the_gateway_is_routed_to(self):
        fake = self.serve()
        self.configure(fake.url, preference=['codex'])
        self.codex('print("UNVERIFIED sample.py:1 local finding")')
        with self.environ():
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
            orchestration.route(self.root, 'explorer'); core.doctor(self.root)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(fake.requests, [])

    def test_missing_key_env_makes_it_unavailable_without_a_request(self):
        fake = self.serve()
        self.configure(fake.url)
        directory = self.root / 'gw-bin'; directory.mkdir(exist_ok=True)
        with mock.patch.dict(os.environ, {'PATH': str(directory)}):
            os.environ.pop(ENV, None)
            binding = orchestration.route(self.root, 'explorer')
            self.assertFalse(binding['available'])
            self.assertIn(ENV + ' is not set', binding['skipped'][0]['reason'])
            self.assertIn(ENV, cli.text_route(binding))
            with self.assertRaises(core.WsError): orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
        self.assertEqual(fake.requests, [])

    def test_bad_entries_are_refused_without_echoing_secrets(self):
        bad = [('file:///etc/passwd', {}), ('ftp://127.0.0.1/v1', {}), ('http://user:pw@127.0.0.1:1/v1', {}),
               ('http://127.0.0.1:1/v1?token=abc', {}), ('127.0.0.1:1/v1', {}), ('http://127.0.0.1:1/v1', {'api_key_env': KEY}),
               ('http://gateway.example.invalid/v1', {}), ('http://gateway.example.invalid/v1', {'kind': 'other'})]
        for url, extra in bad[:-2]:
            with self.subTest(url=url, extra=extra):
                self.configure(url, **extra)
                with self.environ(), self.assertRaises(core.WsError) as caught: orchestration.route(self.root, 'explorer')
                self.assertNotIn(KEY, str(caught.exception)); self.assertNotIn('pw@', str(caught.exception))
        self.configure('http://gateway.example.invalid/v1')  # clear-text non-loopback with a key
        with self.environ(), self.assertRaisesRegex(core.WsError, 'https'): orchestration.route(self.root, 'explorer')
        self.configure('http://127.0.0.1:1/v1', kind='other')
        with self.environ(), self.assertRaisesRegex(core.WsError, 'kind'): orchestration.route(self.root, 'explorer')

    def test_non_loopback_is_allowed_but_printed_clearly_and_not_contacted_on_prepare(self):
        self.configure('https://gateway.example.invalid/v1')
        with self.environ(), mock.patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('no network on prepare')):
            binding = orchestration.route(self.root, 'explorer')
            self.assertTrue(binding['available'])
            self.assertIn('not loopback', cli.text_route(binding))
            result = orchestration.delegate(self.root, 'T-1', 'explorer')
        self.assertIn('not loopback', result['warning'])
        self.configure('http://gateway.example.invalid/v1', api_key_env=None)  # no key: clear text is permitted but still printed
        with self.environ():
            self.assertIn('not loopback', orchestration.route(self.root, 'explorer')['model_warning'])
        self.configure('http://localhost:20128/v1')
        with self.environ(): self.assertEqual(orchestration.route(self.root, 'explorer')['model_warning'], '')

    def test_prepare_only_mode_never_runs_the_gateway(self):
        fake = self.serve(); self.configure(fake.url)
        path = self.root / 'routing.json'; data = json.loads(path.read_text()); data['delegation_mode'] = 'prepare-only'; path.write_text(json.dumps(data))
        with self.environ(), self.assertRaises(core.WsError): orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
        self.assertEqual(fake.requests, [])

    def test_gateway_failure_falls_back_to_the_next_provider(self):
        failing = self.serve(status=503)
        self.configure(failing.url, preference=['gw', 'codex'])
        self.codex('print("UNVERIFIED sample.py:1 local finding")')
        with self.environ():
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
        self.assertEqual([(a['provider'], a['status']) for a in result['provider_attempts']], [('gw', 'failed'), ('codex', 'ok')])
        self.assertEqual([(e['provider'], e['result']) for e in core.run_entries(self.root, 'T-1')], [('gw', 'failed'), ('codex', 'ok')])
        self.assertKeyAbsent(json.dumps(result))

    def test_unreachable_gateway_and_unset_key_fall_back_too(self):
        self.configure('http://127.0.0.1:9/v1', preference=['gw', 'codex'])  # discard port: nothing listens
        self.codex('print("UNVERIFIED sample.py:1 local finding")')
        with self.environ():
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
        self.assertEqual([(a['provider'], a['status']) for a in result['provider_attempts']], [('gw', 'failed'), ('codex', 'ok')])
        self.assertIn('could not be reached', core.run_entries(self.root, 'T-1')[0]['note'])
        directory = self.root / 'gw-bin'
        with mock.patch.dict(os.environ, {'PATH': str(directory)}):
            os.environ.pop(ENV, None)
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
        self.assertEqual([(a['provider'], a['status']) for a in result['provider_attempts']], [('gw', 'skipped'), ('codex', 'ok')])

    def test_redirects_are_not_followed_so_the_key_cannot_travel(self):
        target = self.serve()
        redirector = self.serve(location=target.url + '/chat/completions')
        self.configure(redirector.url)
        with self.environ():
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(target.requests, [])

    def test_slow_gateway_is_a_timeout_attempt(self):
        self.set_timeout(1)
        self.configure(self.serve(delay=3).url)
        with self.environ():
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
        self.assertEqual([(a['provider'], a['status']) for a in result['provider_attempts']], [('gw', 'timeout')])
        self.assertEqual(result['exit_code'], 124)

    def set_timeout(self, seconds):
        path = self.root / 'routing.json'; data = json.loads(path.read_text()); data['timeout_seconds'] = seconds; path.write_text(json.dumps(data))
