import json
import os
from pathlib import Path
from unittest import mock

from mcp import server
from test_ws import Base
from testutil import needs_symlinks, run_ws, seeded_repo
from ws import core, packs, repo


class DigestHintTests(Base):
    old_cwd = None

    def tearDown(self):
        if self.old_cwd: os.chdir(self.old_cwd)  # Windows cannot delete a directory that is the cwd; addCleanup runs only after tearDown
        super().tearDown()

    def configure(self, **values):
        cfg = core.config(self.root); cfg.update(values)
        (self.root / 'workspace.json').write_text(json.dumps(cfg))

    def hint(self, response, **values):
        from ws import digest_hint
        return digest_hint.hook(self.root, dict(hook_event_name='PostToolUse', tool_response=response, **values))

    def test_opt_in_advertises_existing_tool_and_respects_custom_profile(self):
        self.assertNotIn('digest_file', server.listed_tools(self.root))
        self.configure(packs=['digest'])
        self.assertEqual(len(server.listed_tools(self.root)), 8)
        self.assertIn('digest_file', server.listed_tools(self.root))
        self.configure(mcp_tools=['brief'])
        self.assertEqual(server.listed_tools(self.root), ['brief'])

    def test_mcp_digest_is_scoped_and_redacted(self):
        self.configure(packs=['digest'])
        log = self.root / 'sample.log'; log.write_text('ERROR broken\n' * 100)
        def call(path):
            return server.handle(self.root, dict(jsonrpc='2.0', id=1, method='tools/call', params=dict(name='digest_file', arguments=dict(path=str(path)))))['result']
        self.assertFalse(call(log)['isError'])
        outside = Path(self.tmp.name) / 'outside.log'; outside.write_text('private')
        self.assertTrue(call(outside)['isError'])
        log.write_text('-----BEGIN PRIVATE KEY-----\nsensitive-body\n-----END PRIVATE KEY-----\n')
        self.assertNotIn('sensitive-body', json.dumps(call(log)))

    @needs_symlinks
    def test_mcp_digest_refuses_symlink_escape(self):
        outside = Path(self.tmp.name) / 'outside.log'; outside.write_text('private')
        link = self.root / 'escape.log'; link.symlink_to(outside)
        reply = server.handle(self.root, dict(jsonrpc='2.0', id=1, method='tools/call', params=dict(name='digest_file', arguments=dict(path=str(link)))))
        self.assertTrue(reply['result']['isError'])

    def test_native_codex_truncated_output_still_gets_a_hint(self):
        self.configure(packs=['digest'])
        self.assertIn('hookSpecificOutput', self.hint({'output': 'x' * 40000}))

    def test_threshold_bytes_privacy_and_no_writes(self):
        self.assertEqual(self.hint('x' * 40001), {})
        self.configure(packs=['digest'])
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(self.hint('x' * 40000), {})
        for response in ('PRIVATE-' + 'x' * 40001, 'é' * 20001, {'output': 'x' * 40001}):
            result = self.hint(response, tool_input={'path': '/private/secret'})
            self.assertEqual(set(result), {'hookSpecificOutput'})
            extra = result['hookSpecificOutput']
            self.assertEqual(extra['hookEventName'], 'PostToolUse')
            self.assertIn('ws digest <file>', extra['additionalContext'])
            self.assertNotIn('PRIVATE', json.dumps(result)); self.assertNotIn('/private/secret', json.dumps(result))
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_hook_lifecycle_coexists_with_discipline_and_undo_is_clean(self):
        directory = Path(self.tmp.name) / 'repo'; directory.mkdir(); seeded_repo(directory, 'feature/test', {'README.md': 'Fixture.\n'})
        self.configure(repos=[str(directory.resolve())])
        self.old_cwd = Path.cwd(); os.chdir(directory)
        with mock.patch('ws.setup.detect', return_value=[]):
            repo.start(yes=True, workspace=str(self.root))
            core.pack_add(self.root, 'discipline'); core.pack_add(self.root, 'digest'); repo.start(yes=True)
            for client, name in (('claude', '.claude/settings.local.json'), ('codex', '.codex/hooks.json')):
                text = (directory / name).read_text()
                self.assertIn('digest-hint', text)
                hooks = core.pack_hooks(self.root, client)
                self.assertIn('PostToolUse', hooks)
                if client == 'codex': self.assertEqual(len(hooks['PostToolUse']), 2)
            packs.remove(self.root, 'digest'); repo.start(yes=True)
            self.assertNotIn('digest-hint', (directory / '.codex/hooks.json').read_text())
            self.assertEqual(self.hint('x' * 40001), {})
            repo.start(remove=True)
        import subprocess
        self.assertEqual(subprocess.check_output(['git', '-C', str(directory), 'status', '--porcelain'], text=True), '')

    def test_cli_fails_open_for_missing_malformed_and_oversized_input(self):
        self.configure(packs=['digest'])
        for payload in ('', 'not json', '[]', '{}', '{"hook_event_name":"SessionStart","tool_response":"x"}'):
            result = run_ws('--workspace-root', self.root, 'digest-hint', '--hook', input=payload)
            self.assertEqual(result.returncode, 0, result.stderr); self.assertEqual(json.loads(result.stdout), {})

    def test_cli_over_limit_input_emits_size_only_hint_only_when_opted_in(self):
        with mock.patch.object(core, 'MAX_READ_BYTES', 16):
            payload = 'PRIVATE-' + 'x' * 17
            for packs in ([], ['digest']):
                self.configure(packs=packs)
                before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
                result = run_ws('--workspace-root', self.root, 'digest-hint', '--hook', input=payload)
                self.assertEqual(result.returncode, 0, result.stderr)
                out = json.loads(result.stdout)
                if not packs: self.assertEqual(out, {}); continue
                self.assertEqual(set(out), {'hookSpecificOutput'})
                message = out['hookSpecificOutput']['additionalContext']
                self.assertIn('Tool output is over 16 bytes', message); self.assertIn('ws digest <file>', message)
                self.assertNotIn('PRIVATE', result.stdout)
                self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
