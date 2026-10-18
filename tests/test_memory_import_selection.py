import contextlib
import io
import os
import unittest

import test_start
from ws import memory_import


class MemoryImportSelectionTests(unittest.TestCase):
    setUp = test_start.StartTests.setUp
    start = test_start.StartTests.start

    def test_newest_topics_are_selected_without_the_claude_index(self):
        memory = self.home / 'auto-memory'; memory.mkdir()
        index = memory / 'MEMORY.md'; index.write_text('INDEX_ONLY_SENTINEL', encoding='utf-8')
        os.utime(index, (1000, 1000))
        for n in range(20):
            p = memory / f'{n:02}.md'; p.write_text(f'Topic {n}.', encoding='utf-8')
            os.utime(p, (100 + n, 100 + n))
        with contextlib.redirect_stderr(io.StringIO()):
            rows = memory_import.preview(self.repo, memory)
        topics = [r['path'].name for r in rows if r['base'] == memory]
        self.assertEqual(topics, [f'{n:02}.md' for n in range(19, 3, -1)])
        self.assertEqual(index.read_text(encoding='utf-8'), 'INDEX_ONLY_SENTINEL')

