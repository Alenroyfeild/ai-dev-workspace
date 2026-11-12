"""Synthetic identifiers, issue-bound only; no issue is created."""
import os
import urllib.parse
from unittest import mock

from test_ws import Base
from ws import core, feedback_privacy


class FeedbackPrivacyTests(Base):
    def preview(self, value):
        path = core.vault(self.root) / 'Feedback.md'
        path.unlink(missing_ok=True)
        core.feedback_add(self.root, 'Report: ' + value)
        before = path.read_bytes()
        result = core.feedback_submit(self.root, 1)
        self.assertEqual(path.read_bytes(), before, 'preview changed local feedback')
        return result

    def hidden(self, value):
        result = self.preview(value)
        self.assertNotIn(value, result['title'])
        self.assertNotIn(value, result['body'])
        self.assertIn('[REDACTED]', result['body'])

    def test_luhn_cards_raw_spaced_and_dashed(self):
        cards = ('4532015112830366', '5425233430109903', '378282246310005', '6011000990139424',
                 '4222222222222', '4000000000000000006')
        for card in cards:
            for separator in ('', ' ', '-', '  ', ' - '):
                value = separator.join(card[i:i+4] for i in range(0, len(card), 4))
                with self.subTest(value=value): self.hidden(value)

    def test_valid_ibans_raw_and_spaced(self):
        for iban in ('DE89370400440532013000', 'GB29NWBK60161331926819',
                     'FR1420041010050500013M02606', 'NL91ABNA0417164300'):
            for value in (iban, ' '.join(iban[i:i+4] for i in range(0, len(iban), 4))):
                with self.subTest(value=value): self.hidden(value)

    def test_checksum_valid_cards_and_ibans_with_group_separators(self):
        for separator in ('.', '\t', '\u00a0', '/', '_', '-'):
            for groups in (('4532', '0151', '1283', '0366'),
                           ('DE89', '3704', '0044', '0532', '0130', '00')):
                value = separator.join(groups)
                with self.subTest(separator=separator, groups=groups):
                    self.assertEqual(feedback_privacy.issue_text(value), '[REDACTED]')
                    self.hidden(value)

    def test_overlapping_valid_card_spans_hide_the_entire_match(self):
        value = 'Terminal 1000 4532 0151 1283 0366 completed'
        expected = 'Terminal [REDACTED] completed'
        self.assertEqual(feedback_privacy.issue_text(value), expected)
        preview = self.preview(value)
        self.assertIn(expected, preview['title'])
        self.assertIn(expected, preview['body'])

    def test_dotted_versions_addresses_and_dates_beside_grouped_identifiers_stay(self):
        controls = 'v1.123456789.3, IP 192.168.1.1, date 2026-11-12'
        value = '4532.0151.1283.0366; ' + controls
        self.assertEqual(feedback_privacy.issue_text(value), '[REDACTED]; ' + controls)

    def test_spaced_card_next_to_another_numeric_field(self):
        card = '4532 0151 1283 0366'
        for prefix, suffix in (('', ' 321'), ('321 ', ''), ('', '-999')):
            with self.subTest(prefix=prefix, suffix=suffix):
                self.assertIn(prefix + '[REDACTED]' + suffix,
                              self.preview(prefix + card + suffix)['body'])

    def test_standalone_accounts_and_sentence_punctuation(self):
        for value in ('123456789', '1234567890', '123456789012', '12345678901234',
                      '1234567890123456', '123456789012345678'):
            with self.subTest(value=value): self.hidden(value)
        self.assertNotIn('123456789012', self.preview('Account: 123456789012.')['body'])

    def test_bare_tokens_built_from_parts_are_hidden_before_title_truncation(self):
        for prefix in ('lin_' + 'api_', 'ntn_', 'secret_', 'ya29.', 'pypi-'):
            with self.subTest(prefix=prefix): self.hidden(prefix + ('Ab3_' * 16))

    def test_names_amounts_and_variable_need_manual_review(self):
        value = 'Example Person paid $1,234.56; secret_key is a variable'
        result = self.preview(value)
        self.assertIn(value, result['body'])
        self.assertIn('Check for names, amounts and account details before submitting', result['note'].splitlines())

    def test_invalid_checksums_are_not_card_or_iban_matches(self):
        for value in ('4532 0151 1283 0367', 'DE00 3704 0044 0532 0130 00'):
            with self.subTest(value=value): self.assertIn(value, self.preview(value)['body'])

    def test_numeric_segments_in_url_paths_versions_and_hashes_stay(self):
        for value in ('https://example.invalid/items/123456789012', 'v1.123456789.3',
                      'abc123456789012def', '2026-11-05', '1234567890123456789012345678901234567890'):
            with self.subTest(value=value): self.assertIn(value, self.preview(value)['body'])
        self.assertNotIn('123456789012', self.preview('https://example.invalid/path?account=123456789012')['body'])

    def test_multiple_ibans_and_trailing_prose(self):
        values = ('DE89 3704 0044 0532 0130 00', 'GB29 NWBK 6016 1331 9268 19')
        body = self.preview(values[0] + ' and ' + values[1] + ' details')['body']
        for value in values: self.assertNotIn(value, body)
        self.assertIn('details', body)

    def test_external_routes_share_the_redacted_preview(self):
        value = '4532015112830366'
        preview = self.preview(value)
        with mock.patch.dict(os.environ, {'WS_OFFLINE': '0'}):
            link = core.feedback_submit(self.root, 1, yes=True, use_gh='')
            args = urllib.parse.parse_qs(urllib.parse.urlsplit(link['open_this_url']).query)
            self.assertEqual(args['title'], [preview['title']])
            self.assertEqual(args['body'], [preview['body']])
            with mock.patch.object(core.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='https://github.com/fixture/kit/issues/1\n')) as command:
                core.feedback_submit(self.root, 1, yes=True, use_gh='fake-gh')
            argv = command.call_args.args[0]
            self.assertEqual(argv[argv.index('-t')+1], preview['title'])
            self.assertEqual(argv[argv.index('-b')+1], preview['body'])

    def test_generic_redaction_and_local_note_text_are_unchanged(self):
        value = '123456789012'
        self.assertEqual(core.redact(value), value)
        self.preview(value)
        self.assertIn(value, (core.vault(self.root) / 'Feedback.md').read_text())

    def test_all_fifteen_probe_controls_are_preserved(self):
        for value in CONTROLS:
            with self.subTest(value=value):
                result = self.preview(value)
                self.assertIn(value, result['title'])
                self.assertIn(value, result['body'])


CONTROLS = ['0.1.0-beta.7', '0.1.0b7', 'v1.2.3', '2026.11.5', '5f3713a0400e3cb441ff69c4af122c9edf728489', '5f3713a', '5f3713a0400e', '2026-11-05', '2026-11-05T10:00:00Z', '#376', 'PR #380', 'localhost:8080', '200 OK', '192.168.1.1', 'f609915c-bd33-4237-8d0c-b8c7ed6c616a']
