import json
import os
import subprocess
import sys
from pathlib import Path
from test_ws import Base
from testutil import needs_symlinks
from ws import core
from mcp import server


class CompactRecallTests(Base):
    def call(self, args):
        return server.handle(self.root, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': 'search_vault', 'arguments': args}})

    def test_metadata_first_then_explicit_private_safe_details(self):
        path = core.vault(self.root) / 'Project/receipts.md'
        path.write_text('---\ntitle: Receipt policy\ncreated: 2026-10-22\n---\n\nReceipt checksum policy.\n' + 'Long receipt text. ' * 100 + '<private>HIDDEN_321</private>')
        result = self.call({'query': 'receipt'})['result']
        rows = json.loads(result['content'][0]['text'])
        row = next(r for r in rows if r['id'].endswith('receipts.md'))
        self.assertEqual(row['title'], 'Receipt policy'); self.assertEqual(row['date'], '2026-10-22')
        self.assertNotIn('Long receipt', str(rows)); self.assertNotIn('lines', row)
        result = self.call({'detail': row['id']})['result']
        self.assertFalse(result['isError'], result)
        body = json.loads(result['content'][0]['text'])['content']
        self.assertIn('Long receipt', body); self.assertNotIn('HIDDEN_321', body)
        self.assertEqual(len(server.CORE_TOOLS), 7)

    def test_saved_date_survives_an_empty_created_field(self):
        path = core.vault(self.root) / 'Project/dated.md'
        for created, date, expected in (('', '2026-01-02', '2026-01-02'),
                                        ('2026-01-01', '2026-01-02', '2026-01-01'),
                                        ('', '', '2000-01-01')):
            with self.subTest(created=created, date=date):
                path.write_text(f'---\ntitle: Dated receipt\ncreated: {created}\ndate: {date}\n---\nReceipt checksum.\n')
                os.utime(path, (946684800, 946684800))
                rows = json.loads(self.call({'query': 'receipt'})['result']['content'][0]['text'])
                row = next(row for row in rows if row['id'].endswith('dated.md'))
                self.assertEqual(row['date'], expected)
                detail = json.loads(self.call({'detail': row['id']})['result']['content'][0]['text'])
                self.assertEqual(detail['date'], expected)

    def test_match_after_detail_window_still_returns_metadata(self):
        path = core.vault(self.root) / 'Project/long.md'
        path.write_text('Padding text. ' * 2000 + 'lateuniqueword')
        rows = json.loads(self.call({'query': 'lateuniqueword'})['result']['content'][0]['text'])
        self.assertTrue(any(row['id'].endswith('long.md') for row in rows))

    def test_case_variants_of_local_notes_and_run_logs_never_reach_recall(self):
        vault = core.vault(self.root)
        run_dir = vault / 'rUnS'
        run_dir.mkdir(exist_ok=True)
        canary = 'recall exclusion fixture'
        for path in (vault / 'Project/work.LoCaL.md', run_dir / 'event.md'):
            path.write_text(canary, encoding='utf-8')
            identifier = path.relative_to(self.root).as_posix()
            with self.subTest(id=identifier):
                result = self.call({'detail': identifier})['result']
                self.assertTrue(result['isError'])
                self.assertNotIn(canary, str(result))
        ordinary = vault / 'Project/work.locale.md'
        ordinary.write_text('ordinary recall fixture', encoding='utf-8')
        rows = json.loads(self.call({'query': 'recall fixture'})['result']['content'][0]['text'])
        self.assertEqual([row['id'] for row in rows], [ordinary.relative_to(self.root).as_posix()])

    def test_team_local_only_id_is_refused_regardless_of_case(self):
        team_id = 'a' * 32
        clone = self.root / '.ws/team'
        entries = clone / 'entries'
        entries.mkdir(parents=True)
        (clone / 'team.json').write_text(json.dumps(dict(kind='ai-dev-workspace-team', schema_version=1, id=team_id)))
        config = core.config(self.root)
        config['team_workspace'] = {'path': '.ws/team', 'id': team_id}
        (self.root / 'workspace.json').write_text(json.dumps(config))
        (entries / 'fixture.LOCAL.md').write_text(
            f'---\nid: fixture.LOCAL\nteam: {team_id}\nsource: knowledge:fixture\ncategory: repo\n---\n\nlocal team canary\n',
            encoding='utf-8')
        result = self.call({'detail': 'team:fixture.LOCAL'})['result']
        self.assertTrue(result['isError'])
        self.assertNotIn('local team canary', str(result))

    def test_real_stdio_metadata_then_detail(self):
        path = core.vault(self.root) / 'Project/stdio.md'; path.write_text('# Receipt policy\nReceipt checksum.\n')
        messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'fixture', 'version': '1'}}},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                    {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'search_vault', 'arguments': {'query': 'receipt'}}},
                    {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'search_vault', 'arguments': {'detail': 'vault/Project/stdio.md'}}}]
        result = subprocess.run([sys.executable, str(Path(server.__file__)), '--root', str(self.root)],
                                input='\n'.join(map(json.dumps, messages)) + '\n', text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(replies[1]['result']['tools']), 7)
        self.assertIn('Receipt checksum', replies[3]['result']['content'][0]['text'])

    @needs_symlinks
    def test_hostile_detail_ids_and_symlink_escape_refuse(self):
        outside = self.root.parent / 'outside.md'; outside.write_text('Private outside.')
        link = core.vault(self.root) / 'Project/link.md'; link.symlink_to(outside)
        personal = core.vault(self.root) / 'Project/work.local.md'; personal.write_text('Private outside.')
        for identifier in ('../outside.md', str(outside), 'workspace.json', 'vault/Project/link.md', 'vault/.hidden.md', 'vault/Project/work.local.md'):
            result = self.call({'detail': identifier})
            self.assertTrue(result.get('error') or result['result']['isError'], result)
            self.assertNotIn('Private outside', str(result))
