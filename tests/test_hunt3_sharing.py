"""Bug hunt round 3: sharing, knowledge, lessons, folder metadata and snooze dates."""
import contextlib
import datetime
import io
import json
import os
import unittest
from unittest import mock
import test_sharing
import test_team_folder
from test_ws import Base
from ws import assist, cards, core, knowledge, sharing


class PortableTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def test_closing_tags_survive_but_local_paths_are_still_localized(self):
        text = 'wrap in <form>x</form> or <div>y</div> and ```</pre>``` but not <br/>'
        self.assertEqual(sharing.portable(self.root, text), text)
        out = sharing.portable(self.root, 'see /Users/bob/clients/app.py, (/etc/hosts) and C:\\Users\\bob\\x.txt in <b>bold</b>')
        self.assertNotIn('bob', out); self.assertNotIn('/etc', out); self.assertIn('<b>bold</b>', out)
        self.assertEqual(out.count('[local path]'), 3)

    def test_bracketed_local_paths_are_localized_but_closing_tags_survive(self):
        out = sharing.portable(self.root, 'see </opt/synthetic-private/file.txt> and <C:\\synthetic-private\\file.txt> in <b>x</b> </div >')
        self.assertNotIn('synthetic-private', out); self.assertIn('<b>x</b> </div >', out)

    def test_private_summary_keeps_closing_tags(self):
        item = knowledge.add(self.root, 'wrap in <form>x</form> tag', 'repo')
        self.assertIn('</form>', knowledge.list_entries(self.root)['entries'][0]['summary'])
        self.assertTrue(item)


class CategoryFilterTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def test_mixed_case_category_filter_matches_stored_category(self):
        knowledge.add(self.root, 'Receipt policy belongs in the product guide', 'product')
        self.assertEqual(len(knowledge.list_entries(self.root, 'Product')['entries']), 1)


class BrokenNoteTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def note(self, header, name='a' * 32):
        path = core.vault(self.root) / 'Knowledge'; path.mkdir(exist_ok=True)
        (path / (name + '.md')).write_bytes(('---\nid: ' + name + '\nscope: private\n' + header + '---\n\nhand edited\n').encode())
        return name

    def test_bad_category_note_is_skipped_with_a_warning_naming_the_file(self):
        name = self.note('category: ops\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err): item = knowledge.add(self.root, 'plain private note about gadgets', 'other')
        self.assertTrue(item.startswith('knowledge:'))
        self.assertIn(name + '.md', err.getvalue())
        self.assertEqual([r['id'] for r in knowledge.list_entries(self.root, 'other')['entries']], [item.split(':')[1]])

    def test_category_is_case_insensitive_and_bom_is_tolerated(self):
        self.note('category: Runbook\n', 'b' * 32)
        path = core.vault(self.root) / 'Knowledge' / ('c' * 32 + '.md')
        path.write_bytes(b'\xef\xbb\xbf---\nid: ' + b'c' * 32 + b'\nscope: private\ncategory: repo\n---\n\nbom note\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err): knowledge.add(self.root, 'another private note', 'RePo')
        self.assertEqual(err.getvalue(), '')
        by_id = {r['id']: r['category'] for r in knowledge.list_entries(self.root)['entries']}
        self.assertEqual(by_id['b' * 32], 'runbook'); self.assertEqual(by_id['c' * 32], 'repo')

    def test_team_share_skips_broken_private_note(self):
        name = self.note('category: ops\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err): item = knowledge.add(self.root, 'Shared queue contract.', 'domain', True)
        self.assertIn(name + '.md', err.getvalue())
        self.assertTrue(sharing.preview(self.root, item)['content'])


class CatalogCapTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def test_search_by_category_sees_every_note_and_capped_listing_is_newest_first(self):
        folder = core.vault(self.root) / 'Knowledge'; folder.mkdir(exist_ok=True)
        for i in range(130):
            name = f'{i:032x}'
            (folder / (name + '.md')).write_text(f'---\nid: {name}\nscope: private\ncategory: domain\ncreated: x\n---\n\nneedle{i:03d} fact\n')
            os.utime(folder / (name + '.md'), (1000 + i, 1000 + i))
        cards.write(self.root, cards.plan(self.root, 'private'))
        for word in ('needle000', 'needle050', 'needle129'):
            self.assertEqual(len(core.search(self.root, word, category='domain')), 1, word)
        listing = knowledge.list_entries(self.root, limit=5)
        self.assertEqual([r['id'] for r in listing['entries']], [f'{i:032x}' for i in (129, 128, 127, 126, 125)])
        self.assertIn('newest 5 of 130', listing['warnings'][0])
        self.assertTrue(listing['warnings'][0].startswith(knowledge.CAP_PREFIX))


class LessonRelevanceTests(Base):
    def test_stopwords_alone_do_not_make_a_lesson_relevant(self):
        core.task_new(self.root, 'D-1', 'Fix the date formatting for the report'); core.claim(self.root, 'D-1', 'synthetic')
        core.checkpoint(self.root, 'D-1', 'in_progress', 'Continue.')
        core.lesson_add(self.root, 'Migrations on the staging cluster need a lock for the whole run.')
        core.lesson_add(self.root, 'Kafka offsets must be committed after the batch for the consumer.')
        core.lesson_add(self.root, 'Report exports hit a timezone bug when formatting naive dates.')
        brief = core.brief(self.root)
        self.assertIn('Report exports', brief)
        self.assertNotIn('Migrations', brief); self.assertNotIn('Kafka', brief)

    def test_search_ignores_metadata_comment_and_short_queries(self):
        core.lesson_add(self.root, 'Cached values expired; reuse stable receipts.', paths=['src/*.py'], area='serialization')
        self.assertEqual(core.lesson_search(self.root, 'serialization'), [])
        self.assertEqual(core.lesson_search(self.root, 'paths'), [])
        self.assertEqual(len(core.lesson_search(self.root, 'receipts')), 1)
        with self.assertRaises(core.WsError): core.lesson_search(self.root, 'ab')
        self.assertEqual(len(core.lesson_search(self.root, '')), 1)


    def test_search_on_a_long_space_run_is_linear(self):
        import time
        core.lesson_add(self.root, 'Cached values expired; reuse stable receipts.', paths=['src/*.py'], area='serialization')
        path = core.vault(self.root) / 'Learnings.md'
        path.write_text(path.read_text(encoding='utf-8') + '- ' + ' ' * 200000 + 'tail\n', encoding='utf-8')
        start = time.perf_counter(); found = core.lesson_search(self.root, 'receipts tail')
        self.assertLess(time.perf_counter() - start, 2.0)
        self.assertEqual(len(found), 2)
        self.assertEqual(core.lesson_search(self.root, 'serialization'), [])  # the metadata comment is still ignored

class FolderJunkTests(unittest.TestCase):
    setUp = test_team_folder.TeamFolderTests.setUp
    link = test_team_folder.TeamFolderTests.link
    record = test_team_folder.TeamFolderTests.record

    def test_os_metadata_files_never_stop_a_pull_or_get_copied(self):
        from ws import team_auto
        self.link()
        names = ('desktop.ini', 'Thumbs.db', '._team.json', '._x.md', '.localized', '~$lock.tmp', '.dropbox.cache', 'a.tmp.drivedownload', '.~lock.x.ods#')
        for folder in (self.folder, self.folder / 'entries'):
            for name in names: (folder / name).write_text('metadata')
        for name in ('.Spotlight-V100', '.fseventsd', '.TemporaryItems'): (self.folder / name).mkdir()
        self.assertFalse(team_auto.pull(self.root)['updated'])
        mirror = self.root / '.ws/team'
        self.assertEqual([p.name for p in mirror.rglob('*') if p.name in names], [])
        (self.folder / 'conflicted copy.md').write_text('real stray file')
        with self.assertRaises(core.WsError): team_auto.pull(self.root)


class SnoozeDateTests(Base):
    def decide(self, until):
        repo = self.root / 'repo'; repo.mkdir(exist_ok=True); (repo / 'README.md').write_text('# S\n')
        cfg = core.config(self.root); cfg['repos'] = [str(repo)]
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        with mock.patch.object(core, 'tools', return_value=[]), mock.patch.object(assist, 'cost_data', return_value=({}, {})):
            return assist.decide(self.root, 'map', 'snoozed', until)

    def test_compact_week_and_past_dates_are_refused_and_iso_future_is_stored(self):
        today = datetime.date.fromisoformat(core.now()[:10])
        for bad in ('20991001', '2099-W43-1', (today - datetime.timedelta(days=1)).isoformat(), today.isoformat(), '', None, '2099-13-01'):
            with self.assertRaises(core.WsError, msg=bad): self.decide(bad)
        future = (today + datetime.timedelta(days=3)).isoformat()
        self.assertEqual(self.decide(future)['until'], future)


if __name__ == '__main__':
    unittest.main()
