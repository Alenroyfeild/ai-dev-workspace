import contextlib
import io
import json
from pathlib import Path

from test_ws import Base
from ws import cli, core


class DoctorCacheTests(Base):
    def test_damaged_optional_cache_does_not_hide_workspace_health(self):
        cache = Path.home() / '.cache/ai-dev-workspace/update.json'
        cache.parent.mkdir(parents=True)
        for payload in (b'{}', b'[]', b'{', b'{"result": []}', b'\xff'):
            with self.subTest(payload=payload):
                cache.write_bytes(payload)
                for root in (None, self.root):
                    self.assertTrue(core.doctor(root)['core']['python3'])
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = cli.main(['--workspace-root', str(self.root), 'doctor', '--json'])
                self.assertEqual(code, 0)
                report = json.loads(out.getvalue())
                self.assertNotIn('workspace_error', report)
                self.assertEqual(Path(report['workspace']).resolve(), self.root.resolve())

    def test_valid_cached_update_is_still_shown(self):
        cache = Path.home() / '.cache/ai-dev-workspace/update.json'
        cache.parent.mkdir(parents=True)
        cache.write_text(json.dumps({'result': {'latest': '0.2.0', 'update_available': True}}))
        kit = core.doctor(self.root)['kit']
        self.assertEqual(kit['latest'], '0.2.0')
        self.assertTrue(kit['update_available'])
