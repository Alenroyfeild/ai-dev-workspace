import unittest

from ws import core


class RedactTokenTests(unittest.TestCase):
    def test_bare_prefixed_tokens_are_redacted(self):
        for token in ('ghp_' + 'A1b2' * 9, 'github_pat_' + 'x1' * 25, 'sk-' + 'Z9y8' * 6, 'xoxb-1234567890-abcdef', 'AKIA' + 'ABCD1234EFGH5678'):
            with self.subTest(token):
                text = core.redact(f'use {token} for the deploy')
                self.assertNotIn(token, text)
                self.assertIn('[REDACTED]', text)

    def test_every_slack_token_prefix_is_redacted(self):
        for prefix in 'xoxa xoxb xoxc xoxd xoxe xoxp xoxr xoxs'.split():
            with self.subTest(prefix):
                token = prefix + '-' + 'A' * 30
                self.assertNotIn(token, core.redact(f'use {token} now'))

    def test_more_provider_token_families_are_redacted(self):
        tokens = ('glpat-' + 'aB3_' * 6, 'AIza' + 'Sy9-' * 8 + 'abc', 'AIza' + 'x' * 34 + '-', 'npm_' + 'aB3x' * 9,
                  'hf_' + 'aB3x' * 8, 'sk_live_' + 'aB3x' * 6, 'sk_test_' + 'aB3x' * 6, 'rk_live_' + 'aB3x' * 6,
                  'rk_test_' + 'aB3x' * 6, 'sk-ant-api03-' + 'aB3x' * 6)
        for token in tokens:
            with self.subTest(token):
                text = core.redact(f'use {token} for the deploy')
                self.assertNotIn(token[:-1], text)
                self.assertEqual(text, 'use [REDACTED] for the deploy')

    def test_ordinary_words_are_left_alone(self):
        for text in ('ask-the-team before deploying', 'the sk- prefix is documented', 'AKIA is an AWS key prefix',
                     'hf_config and npm_install are names', 'AIzaYZ is too short', 'sk_live_short and glpat-short',
                     'The quick brown fox jumps over the lazy dog.'):
            with self.subTest(text): self.assertEqual(core.redact(text), text)
