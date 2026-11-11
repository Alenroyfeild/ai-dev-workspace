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

    def test_full_boundary_page_cannot_prove_unseen_publication_order(self):
        first = [release(25, f'v1.2.{index}', '#37') for index in range(29)]
        first.append(release(3, 'v1.1.0'))
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


class FeedbackReleaseSyncTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'workspace'
        core.init(self.root, 'fixture', clients=[])
        core.feedback_add(self.root, 'The fixture issue', 'bug')
        self.url = f'https://github.com/{REPO}/issues/37'
        core.feedback_link(self.root, 1, self.url)
        self.sidecar = self.root / '.ws' / 'feedback-closures.json'
        offline = patch.dict(os.environ, {'WS_OFFLINE': '0'})
        offline.start()
        self.addCleanup(offline.stop)

    def test_sync_records_bounded_evidence_and_clears_it_on_reopen(self):
        calls = []
        sha = 'a' * 40

        def closed(url):
            calls.append(url)
            if '/releases?' in url:
                return [release(10, 'v1.2.1', 'Mention #37 plus arbitrary issue text')]
            if '/timeline?' in url:
                return [{'event': 'closed', 'created_at': CLOSED, 'actor': {'login': 'fixture-bot'},
                         'commit_id': sha, 'commit_url': f'https://api.github.com/repos/{REPO}/commits/{sha}'}]
            return {'state': 'closed', 'closed_at': CLOSED, 'body': 'arbitrary issue text'}

        first = support.sync_feedback(self.root, closed)
        self.assertEqual(first['closed'], [self.url])
        self.assertTrue(core.feedback_items(self.root)[0]['done'])
        record = json.loads(self.sidecar.read_text(encoding='utf-8'))['issues'][self.url]
        self.assertEqual(record['closing_actor'], 'fixture-bot')
        self.assertEqual(record['closing_reference'], f'https://github.com/{REPO}/commit/{sha}')
        self.assertEqual(record['release']['version'], '1.2.1')
        self.assertNotIn('arbitrary issue text', self.sidecar.read_text(encoding='utf-8'))
        self.assertEqual(support.sync_feedback(self.root, closed)['closed'], [])
        self.assertEqual(len(calls), 4)

        result = support.sync_feedback(self.root, lambda _: {'state': 'open'})
        self.assertEqual(result['reopened'], [self.url])
        self.assertFalse(core.feedback_items(self.root)[0]['done'])
        reopened = json.loads(self.sidecar.read_text(encoding='utf-8'))['issues'][self.url]
        self.assertEqual(reopened['state'], 'open')
        self.assertNotIn('release', reopened)

    def test_expired_release_cache_reports_unknown_when_refresh_fails(self):
        start = support.time.time_ns()

        def closed(url):
            if '/releases?' in url:
                return [release(10, 'v1.2.1', '#37')]
            if '/timeline?' in url:
                return []
            return {'state': 'closed', 'closed_at': CLOSED}

        with patch.object(support.time, 'time_ns', return_value=start):
            first = support.sync_feedback(self.root, closed)
        self.assertEqual(first['release_mentions'], [self.url])

        def rate_limit(url):
            if '/releases?' in url:
                raise OSError('rate limited')
            return closed(url)

        with patch.object(support.time, 'time_ns', return_value=start + 2 * 86400 * 10**9):
            next_result = support.sync_feedback(self.root, rate_limit)
        self.assertIsNone(next_result['closures'][self.url]['release'])
        self.assertEqual(next_result['release_mentions'], [])
        self.assertTrue(core.feedback_items(self.root)[0]['done'])

    def test_sidecar_permission_error_keeps_unverified_status_private(self):
        with patch.object(core, 'atomic_write', side_effect=PermissionError('fixture private path')):
            result = support.sync_feedback(self.root, lambda _: {'state': 'closed'})
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['closed'], [])
        self.assertNotIn('fixture private path', json.dumps(result))
        self.assertFalse(core.feedback_items(self.root)[0]['done'])

    def test_offline_does_not_read_or_create_a_sidecar(self):
        with patch.dict(os.environ, {'WS_OFFLINE': '1'}):
            result = support.sync_feedback(self.root, lambda _: self.fail('unexpected GitHub request'))
        self.assertTrue(result['offline'])
        self.assertFalse(self.sidecar.exists())

    def test_slow_sync_cannot_overwrite_newer_observation(self):
        def slow(url):
            if '/timeline?' in url or '/releases?' in url:
                return []
            support.sync_feedback(self.root, lambda _: {'state': 'open'})
            return {'state': 'closed', 'closed_at': CLOSED}

        self.assertEqual(support.sync_feedback(self.root, slow)['closed'], [])
        self.assertFalse(core.feedback_items(self.root)[0]['done'])
        current = json.loads(self.sidecar.read_text(encoding='utf-8'))['issues'][self.url]
        self.assertEqual(current['state'], 'open')


class ReleaseNoticeTests(unittest.TestCase):
    def test_notice_uses_release_evidence_and_installation_specific_commands(self):
        url = f'https://github.com/{REPO}/issues/37'
        evidence = {'version': '9.1.0', 'url': f'https://github.com/{REPO}/releases/tag/v9.1.0'}
        with patch.object(core, 'PACKAGED', False):
            checkout = support.feedback_notice(url, evidence)
        with patch.object(core, 'PACKAGED', True):
            packaged = support.feedback_notice(url, evidence)
        self.assertIn('Release 9.1.0 notes mention it', checkout['message'])
        self.assertIn(evidence['url'], checkout['message'])
        self.assertIn('ws update', checkout['message'])
        self.assertIn('ws upgrade --yes', checkout['message'])
        self.assertIn('pipx upgrade ai-dev-workspace', packaged['message'])
        self.assertIn('venv', packaged['message'])
        for notice in (checkout, packaged):
            self.assertEqual(notice['suggest'], 'ws update --check')
            self.assertNotIn('shipped', notice['message'])
        unknown = support.feedback_notice(url, None)
        self.assertIn('release not confirmed', unknown['message'])
        self.assertNotIn('ws upgrade', unknown['message'])


class AttachmentPreviewTests(unittest.TestCase):
    def test_digest_binds_exact_title_and_submitted_body(self):
        card = {'counts': {'packs': 1}}
        preview = support.attachment_preview('Title', 'Text', card)
        self.assertIn('\n  "counts": {', preview['body'])
        self.assertEqual(preview['support'], card)
        self.assertEqual(preview, support.attachment_preview('Title', 'Text', card))
        changed = (
            support.attachment_preview('Title!', 'Text', card),
            support.attachment_preview('Title', 'Text\n', card),
            support.attachment_preview('Title', 'Text', {'counts': {'packs': 2}}),
        )
        for other in changed:
            self.assertNotEqual(preview['preview_sha'], other['preview_sha'])


if __name__ == '__main__':
    unittest.main()
