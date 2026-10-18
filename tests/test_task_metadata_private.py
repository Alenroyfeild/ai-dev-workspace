import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ws import core


class TaskMetadataPrivateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'; self.home = Path(self.tmp.name) / 'home'; self.home.mkdir()
        patch = mock.patch.dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home), CODEX_HOME=str(self.home / '.codex'), WS_OFFLINE='1')
        patch.start(); self.addCleanup(patch.stop)
        core.init(self.root, 'synthetic', repos=[], clients=[])

    def test_private_markers_in_branch_or_repo_are_refused(self):
        for field, value in (('branch', 'feature/<private>x</private>'), ('repo', '/tmp/<private>x</private>'),
                             ('branch', 'fix/<private>unclosed'), ('repo', '/tmp/x#private')):
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(core.WsError, 'cannot contain private markers'):
                    core.task_new(self.root, 'P-1', 'Synthetic', **{field: value})
                self.assertFalse(core.task_path(self.root, 'P-1').exists())

    def test_ordinary_branch_and_repo_are_kept(self):
        core.task_new(self.root, 'P-2', 'Synthetic', branch='feature/a#1', repo='/tmp/work')
        meta = core.task_read(self.root, 'P-2', ['Objective'])['meta']
        self.assertEqual((meta['branch'], meta['repo']), ('feature/a#1', '/tmp/work'))
