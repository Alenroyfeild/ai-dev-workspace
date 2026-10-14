"""Shared test helpers: structural home isolation and Windows-safe temp cleanup."""
import os
import shutil
import stat
import sys
from pathlib import Path
from unittest import mock


def isolate_home(case, tmp):
    """Point HOME and USERPROFILE at a per-test dir inside `tmp` until the test ends.

    Path.home()/expanduser('~') read USERPROFILE first on Windows (HOMEDRIVE+HOMEPATH only as a fallback,
    HOME is ignored since 3.8) and HOME on POSIX, so setting both covers every OS. Tests that patch
    their own home simply override this.
    """
    home = Path(tmp) / '_home'
    home.mkdir(parents=True, exist_ok=True)
    patch = mock.patch.dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    patch.start()
    case.addCleanup(patch.stop)
    return home


def rmtree_owned(path, root):
    """Remove `path`; on error clear the read-only bit (git objects on Windows) only for real paths inside `root`."""
    top = Path(root).resolve()

    def fix(func, failing, _exc):
        if os.path.islink(failing) or not Path(failing).resolve().is_relative_to(top):
            raise
        os.chmod(failing, stat.S_IRWXU)
        func(failing)

    shutil.rmtree(path, **{('onexc' if sys.version_info >= (3, 12) else 'onerror'): fix})
