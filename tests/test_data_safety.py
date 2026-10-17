import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest import mock
from test_ws import Base, KIT
from ws import core


class ConcurrentWriteTests(Base):
    def holder(self, seconds):
        ready = threading.Event()
        def hold():
            with core.lock(self.root):
                ready.set(); time.sleep(seconds)
        thread = threading.Thread(target=hold); thread.start(); ready.wait(5)
        return thread

    def test_a_writer_waits_for_a_short_lock_instead_of_failing(self):
        core.claim(self.root, 'T-1', 'synthetic')
        thread = self.holder(0.4)
        try: core.remember(self.root, 'use Postgres, not SQLite')
        finally: thread.join()
        self.assertIn('Decision: use Postgres', core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff'])

    def test_concurrent_remember_and_checkpoint_lose_nothing(self):
        core.claim(self.root, 'T-1', 'synthetic')
        errors = []
        def run(call, *args):
            try: call(self.root, *args)
            except core.WsError as exc: errors.append(str(exc))
        threads = [threading.Thread(target=run, args=(core.remember, f'decision number {i}')) for i in range(6)]
        threads += [threading.Thread(target=run, args=(core.checkpoint, 'T-1', 'in_progress', f'next step {i}')) for i in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(errors, [])
        record = core.task_read(self.root, 'T-1', ['Handoff'])
        for i in range(6): self.assertIn(f'decision number {i}', record['sections']['Handoff'])
        self.assertEqual(record['meta']['checkpoint_count'], '4')

    def test_stop_hook_waits_for_the_lock_and_still_captures(self):
        core.claim(self.root, 'T-1', 'synthetic')
        transcript = self.root / 'session.jsonl'
        transcript.write_text(json.dumps({'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'name': 'Read'}, {'type': 'text', 'text': 'Next step: add the migration.'}]}}))
        thread = self.holder(0.8)
        try:
            result = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'nudge', '--hook'], cwd=self.root, capture_output=True, text=True,
                                    input=json.dumps({'hook_event_name': 'Stop', 'transcript_path': str(transcript)}))
        finally: thread.join()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('add the migration', core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff'])


class DeadEndTests(Base):
    def test_a_later_dead_end_does_not_erase_earlier_ones(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'x', notes={'Do not redo': 'Session cookies: break the mobile app'})
        core.checkpoint(self.root, 'T-1', 'in_progress', 'y', notes={'Do not redo': 'Polling every second: trips the rate limit',
                                                                    'Failures': 'Multipart upload: server rejects it'})
        core.checkpoint(self.root, 'T-1', 'in_progress', 'z', notes={'Failures': 'Retry loop: still 429', 'Do not redo': 'Polling every second: trips the rate limit'})
        sections = core.task_read(self.root, 'T-1', ['Do not redo', 'Failures'])['sections']
        self.assertIn('Session cookies', sections['Do not redo'])
        self.assertEqual(sections['Do not redo'].count('Polling every second'), 1)
        self.assertIn('Multipart upload', sections['Failures'])
        self.assertIn('Retry loop', sections['Failures'])


class PackWriteTests(Base):
    def test_pack_add_takes_the_workspace_lock(self):
        with mock.patch.object(core, 'LOCK_WAIT', 0, create=True), core.lock(self.root):
            with self.assertRaisesRegex(core.WsError, 'Another workspace update'):
                core.pack_add(self.root, 'ios')

    def test_pack_add_writes_workspace_json_atomically(self):
        original = (self.root / 'workspace.json').read_bytes()
        real = core.atomic_write
        def failing(path, text):
            if Path(path).name == 'workspace.json': raise OSError('disk full')
            return real(path, text)
        with mock.patch.object(core, 'atomic_write', failing):
            with self.assertRaises(OSError): core.pack_add(self.root, 'obsidian')
        self.assertEqual((self.root / 'workspace.json').read_bytes(), original)

    def test_private_pack_keeps_non_ascii_rules_under_a_legacy_locale(self):
        source = Path(self.tmp.name) / 'pack'; (source / 'vault').mkdir(parents=True)
        (source / 'pack.json').write_text(json.dumps(dict(name='private-team', version='1.0', kind='domain', description='Synthetic')))
        (source / 'AGENTS.snippet.md').write_text('Synthetic rule.\n')
        (self.root / 'AGENTS.md').write_text('# Rules\nAlways use the → arrow.\n', encoding='utf-8')
        env = {**os.environ, 'HOME': self.tmp.name, 'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0', 'LC_ALL': 'en_US.ISO8859-1'}
        for command in (['add', '--from', str(source)], ['remove', 'private-team']):
            proc = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'pack', *command], cwd=self.root, env=env, text=True, capture_output=True, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn('Always use the → arrow.', (self.root / 'AGENTS.md').read_text(encoding='utf-8'))
