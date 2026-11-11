from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ws import cli, core, support


REPO = 'example/project'
CLOSED = '2026-10-03T00:00:00Z'


def release(day, version, body='', draft=False):
    return {'published_at': f'2026-10-{day:02}T00:00:00Z',
            'tag_name': version, 'draft': draft, 'body': body}


class ReleaseMentionTests(unittest.TestCase):
    def setUp(self):
        offline = patch.dict(os.environ, {'WS_OFFLINE': '0'})
        offline.start()
        self.addCleanup(offline.stop)

    def scan(self, pages):
        seen = []

        def fetch(url):
            seen.append(url)
            return next(pages)

        return support.release_mention(REPO, 37, CLOSED, fetch), seen

    def test_pages_full_notes_and_keeps_earliest_exact_match(self):
        first = [release(25, 'v1.2.3', '#37')] * 30
        second = [
            release(24, 'v1.2.2', 'Fixed ' + 'x' * 1600 + ' example/project#37'),
            release(22, 'v1.2.1', '#376 other/project#37 https://github.com/other/project/issues/37'),
            release(20, 'v1.2.0', '#37', draft=True),
            release(2, 'v1.1.0', '#37'),
        ]
        result, seen = self.scan(iter([first, second]))
        self.assertEqual(result, {'version': '1.2.2', 'url': 'https://github.com/example/project/releases/tag/v1.2.2'})
        self.assertEqual(len(seen), 2)
        self.assertTrue(seen[1].endswith('?per_page=30&page=2'))

    def test_stops_at_closure_boundary(self):
        first = [release(22, 'v1.2.1', '#376')] * 29 + [release(3, 'v1.2.0', '#37')]
        result, seen = self.scan(iter([first]))
        self.assertIsNone(result)
        self.assertEqual(len(seen), 1)

    def test_accepts_issue_url_in_same_repo(self):
        result, _ = self.scan(iter([[release(20, 'v1.2.0', 'https://github.com/EXAMPLE/PROJECT/issues/37')]]))
        self.assertEqual(result['version'], '1.2.0')

    def test_rejects_unordered_and_malformed_history(self):
        current = release(25, 'v1.2.3', '#37')
        for batch in (
            {'message': 'API rate limit'},
            [current, release(1, 'v1.1.0'), release(7, 'v1.1.1', '#37')],
            [current, dict(release(10, 'v1.2.1'), published_at=None)],
            [current, release(10, 'v1.2.1\n<private>', '#37')],
        ):
            with self.subTest(batch=batch):
                self.assertIsNone(self.scan(iter([batch]))[0])

    def test_transport_failure_does_not_report_partial_match(self):
        def pages():
            yield [release(25, 'v1.2.3', '#37')] * 30
            raise OSError('fixture transport error')

        self.assertIsNone(self.scan(pages())[0])

    def test_offline_does_not_fetch(self):
        with patch.dict(os.environ, {'WS_OFFLINE': '1'}):
            result, seen = self.scan(iter([]))
        self.assertIsNone(result)
        self.assertEqual(seen, [])


class SupportDoctorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        home = base / 'home'
        home.mkdir()
        env = patch.dict(os.environ, {'HOME': str(home), 'USERPROFILE': str(home), 'WS_OFFLINE': '1'})
        env.start()
        self.addCleanup(env.stop)
        self.root = base / 'synthetic-workspace-name'
        core.init(self.root, 'synthetic-workspace-name', clients=[])
        self.config = self.root / 'workspace.json'

    def doctor(self):
        with redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err:
            with patch('urllib.request.urlopen', side_effect=AssertionError('unexpected network')):
                status = cli.main(['--workspace-root', str(self.root), 'doctor', '--support'])
        self.assertEqual(err.getvalue(), '')
        return status, json.loads(out.getvalue())

    def test_healthy_card_uses_counts_and_validated_stamps(self):
        with patch.object(core, 'client_connected', return_value=True):
            status, card = self.doctor()
        self.assertEqual(status, 0)
        self.assertEqual(card['status'], 'healthy')
        self.assertEqual(card['versions']['workspace_kit_stamp'], core.kit_meta()['version'])
        self.assertIsNone(card['versions']['workspace_template'])
        self.assertGreater(card['counts']['configured_clients'], 0)
        self.assertEqual(card['half_migrated']['detected'], False)
        self.assertNotIn('synthetic-workspace-name', json.dumps(card))

    def test_only_counts_and_fixed_labels_from_diagnostics(self):
        sensitive = 'Example Company /fixture/customer 9999999999 ' + 'sk-' + 'x' * 28
        cfg = core.config(self.root)
        cfg['kit_version'] = sensitive
        cfg['upgrade_pending'] = [sensitive]
        self.config.write_text(json.dumps(cfg), encoding='utf-8')
        (self.root / 'GEMINI.md').unlink()
        report = {'core': {'git': True, 'python3': True}, 'valid': True, 'upgrade_due': True,
                  'configured_clients': {'claude': True, sensitive: True}, 'stale_hooks': [sensitive],
                  'workspace': sensitive, 'packs': [{'name': sensitive}]}
        with patch.object(core, 'doctor', return_value=report):
            status, card = self.doctor()
        self.assertEqual(status, 1)
        self.assertEqual(card['counts']['configured_clients'], 1)
        self.assertEqual(card['counts']['missing_managed_blocks']['gemini']['instructions'], 1)
        self.assertEqual(card['counts']['pending_proposals'], 1)
        self.assertEqual(card['half_migrated'], {'detected': True, 'evidence': 'pending_proposals'})
        self.assertIsNone(card['versions']['workspace_kit_stamp'])
        for sentinel in ('Example Company', '/fixture/customer', '9999999999', 'sk-'):
            self.assertNotIn(sentinel, json.dumps(card))

    def test_split_version_stamps_indicate_partial_migration(self):
        cfg = core.config(self.root)
        cfg['kit_version'] = '0.0.1'
        self.config.write_text(json.dumps(cfg), encoding='utf-8')
        status, card = self.doctor()
        self.assertEqual(status, 1)
        self.assertEqual(card['half_migrated'], {'detected': True, 'evidence': 'split_version_stamps'})

    def test_corrupt_or_missing_workspace_has_no_raw_error(self):
        self.config.write_text('malformed sensitive-name', encoding='utf-8')
        for exists in (True, False):
            if not exists:
                self.config.unlink()
            with self.subTest(exists=exists):
                status, card = self.doctor()
                self.assertEqual(status, 2)
                self.assertIsNone(card['counts']['packs'])
                self.assertIsNone(card['half_migrated']['detected'])
                self.assertNotIn('sensitive-name', json.dumps(card))


if __name__ == '__main__':
    unittest.main()
