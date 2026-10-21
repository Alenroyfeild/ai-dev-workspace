"""Shared test helpers: structural home isolation and Windows-safe temp cleanup."""
import atexit
import contextlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import traceback
import unittest
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
    os.environ.pop('CLAUDE_CONFIG_DIR', None)  # restored by patch.dict; a real one would leak the developer's settings in
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


def _can_symlink():
    if os.name != 'nt': return True
    with tempfile.TemporaryDirectory() as tmp:
        try: os.symlink(tmp, os.path.join(tmp, 'link'), target_is_directory=True); return True
        except (OSError, NotImplementedError): return False


# Skips only where this host really cannot create symlinks (Windows without Developer Mode/admin); windows-latest can.
needs_symlinks = unittest.skipUnless(_can_symlink(), 'symlinks cannot be created on this host')


def run_ws(*args, cwd=None, input=None, env=None, check=False):
    """Run `ws <args>` in-process (no Python start-up per call) and return a subprocess.CompletedProcess.

    Use it where the test is about command behaviour. Keep a real `bin/ws` subprocess where the process
    boundary matters (encoding of real pipes, cwd discovery without --workspace-root, stdin EOF, locks).
    """
    from ws import cli
    stdin = io.TextIOWrapper(io.BytesIO((input or '').encode('utf-8')), encoding='utf-8')
    out, err = io.StringIO(), io.StringIO()
    previous = Path.cwd()
    with contextlib.ExitStack() as stack:
        if env is not None:
            stack.enter_context(mock.patch.dict(os.environ, env, clear=True))
        if 'COLUMNS' not in os.environ:  # a child with piped output wraps --help at 80 columns, whatever the terminal
            stack.enter_context(mock.patch.dict(os.environ, COLUMNS='80'))
        stack.enter_context(mock.patch.object(sys, 'stdin', stdin))
        stack.enter_context(contextlib.redirect_stdout(out))
        stack.enter_context(contextlib.redirect_stderr(err))
        if cwd is not None:
            os.chdir(cwd)
        try:
            code = cli.main([str(a) for a in args])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
            if isinstance(exc.code, str): print(exc.code, file=sys.stderr)
        except Exception:
            traceback.print_exc(file=sys.stderr); code = 1
        finally:
            os.chdir(previous)
    result = subprocess.CompletedProcess(['ws', *map(str, args)], code or 0, out.getvalue(), err.getvalue())
    if check:
        result.check_returncode()
    return result


_REPO_TEMPLATES = {}


def _drop_template(path):
    try:
        rmtree_owned(path, path)  # read-only git objects need the Windows-safe remover
    except OSError:
        pass


def seeded_repo(dest, branch, files, message='fixture'):
    """Make `dest` a git repo on `branch` with one commit of `files` ({name: text}).

    The repo is built once per process and then copied, so a test pays one directory copy instead of
    `git init`, `git add` and `git commit` (three process launches, slow on Windows).
    """
    key = (branch, message, tuple(sorted(files.items())))
    if key not in _REPO_TEMPLATES:
        template = Path(tempfile.mkdtemp(prefix='ws-test-repo-'))
        atexit.register(_drop_template, template)
        # No background maintenance: it can still hold .git/objects/maintenance.lock while the template is copied.
        git = lambda *a: subprocess.run(['git', '-c', 'maintenance.auto=false', '-c', 'gc.auto=0', *a], cwd=template, check=True, capture_output=True)
        git('init', '-q', '-b', branch)
        for name, text in files.items():
            (template / name).write_text(text)
        git('add', '.')
        git('-c', 'user.name=Fixture', '-c', 'user.email=f@example.invalid', 'commit', '-qm', message)
        _REPO_TEMPLATES[key] = template
    template = _REPO_TEMPLATES[key]

    def skip_git_locks(directory, names):  # only lock files under .git; a tracked Cargo.lock must be copied
        return [n for n in names if n.endswith('.lock') and '.git' in Path(directory).relative_to(template).parts]

    shutil.copytree(template, dest, symlinks=True, dirs_exist_ok=True, ignore=skip_git_locks)
