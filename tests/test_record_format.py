"""EXIT-04: new task and lesson records carry `format: 1`; a missing marker reads as 1 and is never added to old files."""
import json
import re
from test_ws import Base
from ws import core


def strip_format(path):
    path.write_text(re.sub(r'^format:.*\n', '', path.read_text(encoding='utf-8'), flags=re.M), encoding='utf-8')


class RecordFormatTests(Base):
    def test_new_task_records_format_one(self):
        text = core.task_read(self.root, 'T-1')['text']
        self.assertEqual(core.parse_meta(text)['format'], str(core.TASK_FORMAT))
        self.assertEqual(core.TASK_FORMAT, 1)

    def test_new_task_has_format_even_when_the_workspace_template_is_old(self):
        strip_format(self.root / 'vault/Templates/Task.md')
        core.task_new(self.root, 'T-2', 'Second')
        self.assertEqual(core.parse_meta(core.task_read(self.root, 'T-2')['text'])['format'], '1')

    def test_kit_template_has_format_marker(self):
        template = (core.KIT / 'template/vault/Templates/Task.md').read_text(encoding='utf-8')
        self.assertEqual(core.parse_meta(template)['format'], '1')

    def test_missing_or_odd_format_reads_as_one(self):
        for meta in ({}, {'format': ''}, {'format': 'x'}, {'format': '1'}):
            self.assertEqual(core.task_format(meta), 1)
        self.assertEqual(core.task_format({'format': '3'}), 3)

    def test_new_lesson_metadata_records_format(self):
        core.lesson_add(self.root, 'Always run the migration dry run first', paths=['db/*.py'])
        line = core.lesson_search(self.root, 'migration')[0]
        self.assertEqual(json.loads(re.search(r'<!-- ws:lesson (.*?) -->$', line)[1])['format'], core.LESSON_FORMAT)

    def test_checkpoint_never_adds_format_to_an_old_task(self):
        path = self.root / 'vault/Tasks/T-1.md'
        strip_format(path)
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Go on.')
        self.assertNotIn('format', core.parse_meta(path.read_text(encoding='utf-8')))


class NewerFormatTests(Base):
    def newer(self):
        path = self.root / 'vault/Tasks/T-1.md'
        path.write_text(path.read_text(encoding='utf-8').replace('format: 1', 'format: 2'), encoding='utf-8')
        return path, path.read_bytes()

    def test_writes_refuse_and_leave_the_file_alone(self):
        core.task_new(self.root, 'T-2', 'Other')
        path, before = self.newer()
        for write in (lambda: core.claim(self.root, 'T-1', 'w'), lambda: core.remember(self.root, 'a decision', 'T-1'),
                      lambda: core.checkpoint(self.root, 'T-1', 'in_progress', 'Go on.'),
                      lambda: core.task_depend(self.root, 'T-1', 'T-2')):
            with self.assertRaisesRegex(core.WsError, r'written by a newer ai-dev-workspace \(format 2\); update the kit'):
                write()
        self.assertEqual(path.read_bytes(), before)

    def test_reads_still_work_and_warn_once(self):
        self.newer()
        self.assertIn('format 2', core.task_find(self.root, 'T-1')[0]['format_warning'])
        self.assertEqual(core.brief(self.root, 'T-1').count('newer ai-dev-workspace'), 1)
        self.assertEqual(core.task_read(self.root, 'T-1')['task'], 'T-1')


class WindowsLineEndingTests(Base):
    def test_crlf_newer_task_is_still_read_only_and_warns(self):
        path = self.root / 'vault/Tasks/T-1.md'
        path.write_bytes(path.read_bytes().replace(b'format: 1', b'format: 2').replace(b'\n', b'\r\n'))
        before = path.read_bytes()
        with self.assertRaisesRegex(core.WsError, r'format 2'):
            core.atomic_write(path, 'replacement\n')
        with self.assertRaisesRegex(core.WsError, r'format 2'):
            core.claim(self.root, 'T-1', 'w')
        self.assertEqual(path.read_bytes(), before)
        self.assertIn('format 2', core.task_find(self.root, 'T-1')[0]['format_warning'])
        self.assertEqual(core.brief(self.root, 'T-1').count('newer ai-dev-workspace'), 1)

    def test_bom_newer_task_is_still_read_only(self):
        path = self.root / 'vault/Tasks/T-1.md'
        path.write_bytes(b'\xef\xbb\xbf' + path.read_bytes().replace(b'format: 1', b'format: 2').replace(b'\n', b'\r\n'))
        with self.assertRaisesRegex(core.WsError, r'format 2'):
            core.atomic_write(path, 'replacement\n')
