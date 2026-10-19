import time
from test_ws import Base
from ws import core

# Fake values built from parts, like the other token tests, so no full webhook literal sits in the source.
SLACK_HOST = 'https://hooks.slack' + '.com/'
SLACK = SLACK_HOST + 'services/T' + '0' * 8 + '/B' + '0' * 8 + '/' + 'X' * 24
SLACK_FLOW = SLACK_HOST + 'workflows/T' + '0' * 8 + '/A' + '0' * 8 + '/' + '0' * 18 + '/' + 'X' * 24
DISCORD = 'https://discord' + '.com/api/webhooks/' + '0' * 18 + '/' + 'X' * 32 + '_-xx'
DISCORD_APP = 'https://discordapp' + '.com/api/webhooks/' + '0' * 18 + '/' + 'X' * 32


class WebhookRedactionTests(Base):
    def test_slack_and_discord_webhook_urls_are_redacted(self):
        for url in (SLACK, SLACK_FLOW, DISCORD, DISCORD_APP):
            with self.subTest(url):
                out = core.redact(f'post to {url} now')
                self.assertEqual(out, 'post to [REDACTED] now')
                self.assertNotIn('XXXXXXXX', core.plain_text(f'use {url}'))

    def test_ordinary_slack_and_discord_urls_are_untouched(self):
        for url in ('https://slack.com/help', 'https://hooks.slack.com/', 'https://hooks.slack.com/services/',
                    'https://api.slack.com/messaging/webhooks', 'https://discord.com/api/webhooks',
                    'https://discord.com/channels/000000000000000000/000000000000000000'):
            with self.subTest(url):
                self.assertEqual(core.redact(f'see {url} ok'), f'see {url} ok')


class LessonLineSpeedTests(Base):
    def test_whitespace_heavy_lesson_line_is_ranked_quickly(self):
        (self.root / 'vault/Learnings.md').write_text('- 2026-01-01 fix crash lesson ' + ' ' * 200000 + 'tail\n')
        start = time.monotonic()
        lines = core.relevant_lessons(self.root, {'id': 'T-1', 'title': 'Fix crash'})
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertEqual(lines, ['- 2026-01-01 fix crash lesson ' + ' ' * 200000 + 'tail'])

    def test_metadata_comment_is_still_split_off_with_its_leading_space(self):
        core.lesson_add(self.root, 'Fix crash rule avoids failures', paths=['*.py'], area='crash')
        self.assertEqual([l.endswith('failures') for l in core.relevant_lessons(self.root, {'id': 'T-1', 'title': 'Fix crash'})], [True])
