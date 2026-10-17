import contextlib
import io

from test_ws import Base
from ws import cli


class SyncHintTests(Base):
    def test_sync_without_a_team_names_the_command(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(['--workspace-root', str(self.root), 'sync', '--dry-run'])
        self.assertNotEqual(code, 0)
        self.assertIn('`ws team link <private-repo>`', err.getvalue())
        self.assertNotIn('ws --help', err.getvalue())  # the specific command replaces the generic hint
