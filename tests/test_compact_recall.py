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
