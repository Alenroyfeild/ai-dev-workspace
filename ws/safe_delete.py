"""Workspace deletion without traversing replaced symlinks or junctions."""
import contextlib
import errno
import hashlib
import os
from pathlib import Path
import stat
import time

from . import core


def _open_posix_directory(path):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextlib.contextmanager
def guard(root, protect_lock=False):
    """Serialize repo registration and deletion for the same local workspace."""
    if os.name != 'nt':
        directory = _open_posix_directory(Path(root))
        try:
            try:
                os.mkdir('.ws', 0o700, dir_fd=directory)
            except FileExistsError:
                pass
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            private = os.open('.ws', flags, dir_fd=directory)
            try:
                lock_fd = os.open('lock', os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
                                  0o600, dir_fd=private)
                with os.fdopen(lock_fd, 'a+b') as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise core.WsError('The workspace lock is not a regular file.')
                    deadline = time.monotonic() + core.LOCK_WAIT
                    while True:
                        try:
                            core.file_lock(stream)
                            break
                        except OSError as exc:
                            if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                                raise
                            if time.monotonic() >= deadline:
                                raise core.WsError('Another workspace update is running; retry in a moment.')
                            time.sleep(0.05)
                    try:
                        yield None
                    finally:
                        core.file_lock(stream, release=True)
            finally:
                os.close(private)
        finally:
            os.close(directory)
        return

    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel.ReleaseMutex.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    name = 'Local\\ai-dev-workspace-' + hashlib.sha256(str(root).casefold().encode('utf-8')).hexdigest()
    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        outcome = kernel.WaitForSingleObject(handle, 4000)
        if outcome not in (0, 0x80):  # WAIT_OBJECT_0 or WAIT_ABANDONED
            raise core.WsError('Another workspace update is running; retry in a moment.')
        acquired = True
        with contextlib.ExitStack() as pinned:
            if protect_lock:
                api = _WindowsFiles()
                for path in reversed((Path(root) / '.ws' / 'lock').parents):
                    _, info = pinned.enter_context(api.opened(path))
                    if info.attributes & 0x400:
                        raise OSError('A workspace parent became a reparse point.')
                _, info = pinned.enter_context(api.opened(Path(root) / '.ws' / 'lock'))
                if info.attributes & 0x400:
                    raise OSError('The workspace lock became a reparse point.')
            yield pinned
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def _snapshot_posix(root):
    if not (os.open in os.supports_dir_fd and os.scandir in os.supports_fd
            and hasattr(os, 'O_NOFOLLOW') and hasattr(os, 'O_DIRECTORY')):
        raise OSError('This platform cannot safely inspect a workspace without following symlinks.')
    root_fd = _open_posix_directory(root)
    entries = []

    def visit(fd, prefix):
        with os.scandir(fd) as scan:
            found = list(scan)
        for entry in found:
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise OSError('Workspace contains a symlink.')
            relative = prefix / entry.name
            entries.append((relative.as_posix(), info.st_dev, info.st_ino, info.st_mode,
                            info.st_size, info.st_mtime_ns, info.st_ctime_ns))
            if stat.S_ISDIR(info.st_mode):
                child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    if not os.path.samestat(info, os.fstat(child)):
                        raise OSError('A workspace directory changed during inspection.')
                    visit(child, relative)
                finally:
                    os.close(child)

    try:
        manifest_fd = os.open('workspace.json', os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0),
                              dir_fd=root_fd)
        with os.fdopen(manifest_fd, 'rb') as manifest:
            if not stat.S_ISREG(os.fstat(manifest.fileno()).st_mode):
                raise OSError('The workspace manifest is not a regular file.')
            contents = manifest.read(core.MAX_READ_BYTES + 1)
        if len(contents) > core.MAX_READ_BYTES:
            raise OSError('The workspace manifest is too large to inspect safely.')
        visit(root_fd, Path())
        info = os.fstat(root_fd)
        return contents, (info.st_dev, info.st_ino), tuple(sorted(entries))
    finally:
        os.close(root_fd)


def _snapshot_windows(root):
    api = _WindowsFiles()
    entries = []

    def visit(directory, prefix):
        with os.scandir(core.long_path(directory)) as scan:
            names = [entry.name for entry in scan]
        for name in names:
            item = directory / name
            with api.opened(item) as (_, info):
                if info.attributes & 0x400:
                    raise OSError('Workspace contains a reparse point.')
                current = item.lstat()
                relative = prefix / name
                volume, index = api.identity(info)
                entries.append((relative.as_posix(), volume, index, current.st_mode,
                                current.st_size, current.st_mtime_ns, current.st_ctime_ns))
                if info.attributes & 0x10:
                    visit(item, relative)

    with contextlib.ExitStack() as stack:
        for directory in [*reversed(root.parents), root]:
            _, info = stack.enter_context(api.opened(directory))
            if info.attributes & 0x400:
                raise OSError('A workspace path is a reparse point.')
        identity = api.identity(info)
        manifest = root / 'workspace.json'
        _, info = stack.enter_context(api.opened(manifest))
        if info.attributes & (0x400 | 0x10):
            raise OSError('The workspace manifest is not a regular file.')
        with manifest.open('rb') as stream:
            contents = stream.read(core.MAX_READ_BYTES + 1)
        if len(contents) > core.MAX_READ_BYTES:
            raise OSError('The workspace manifest is too large to inspect safely.')
        visit(root, Path())
        return contents, identity, tuple(sorted(entries))


def inspect(root):
    """Read the manifest and collect a no-follow snapshot of the workspace."""
    root = Path(root)
    return _snapshot_windows(root) if os.name == 'nt' else _snapshot_posix(root)


def _remove_contents(fd, prefix, expected):
    with os.scandir(fd) as scan:
        entries = list(scan)
    for entry in entries:
        info = entry.stat(follow_symlinks=False)
        relative = prefix / entry.name
        current = (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if expected is not None and expected.get(relative.as_posix()) != current:
            raise OSError('Workspace contents changed during deletion.')
        if not stat.S_ISDIR(info.st_mode):
            os.unlink(entry.name, dir_fd=fd)
            continue
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        child = os.open(entry.name, flags, dir_fd=fd)
        try:
            if not os.path.samestat(info, os.fstat(child)):
                raise OSError('A workspace directory changed during deletion.')
            _remove_contents(child, relative, expected)
            current = os.stat(entry.name, dir_fd=fd, follow_symlinks=False)
            if not os.path.samestat(current, os.fstat(child)):
                raise OSError('A workspace directory changed during deletion.')
            os.rmdir(entry.name, dir_fd=fd)
        finally:
            os.close(child)


def _remove_posix(root, identity, expected):
    required = (os.open in os.supports_dir_fd and os.stat in os.supports_dir_fd
                and os.unlink in os.supports_dir_fd and os.rmdir in os.supports_dir_fd
                and os.scandir in os.supports_fd and hasattr(os, 'O_NOFOLLOW') and hasattr(os, 'O_DIRECTORY'))
    if not required:
        raise OSError('This platform cannot safely delete a workspace without following symlinks.')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = _open_posix_directory(root.parent)
    try:
        target = os.open(root.name, flags, dir_fd=parent)
        try:
            info = os.fstat(target)
            if (info.st_dev, info.st_ino) != identity:
                raise OSError('The recorded workspace changed during deletion.')
            _remove_contents(target, Path(), expected)
            current = os.stat(root.name, dir_fd=parent, follow_symlinks=False)
            if not os.path.samestat(current, os.fstat(target)):
                raise OSError('The recorded workspace changed during deletion.')
            os.rmdir(root.name, dir_fd=parent)
        finally:
            os.close(target)
    finally:
        os.close(parent)


class _WindowsFiles:
    """Pin names with Win32 handles and open reparse points without traversing them."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class FileInformation(ctypes.Structure):
            _fields_ = [('attributes', wintypes.DWORD), ('created', wintypes.FILETIME),
                        ('accessed', wintypes.FILETIME), ('written', wintypes.FILETIME),
                        ('volume', wintypes.DWORD), ('size_high', wintypes.DWORD),
                        ('size_low', wintypes.DWORD), ('links', wintypes.DWORD),
                        ('index_high', wintypes.DWORD), ('index_low', wintypes.DWORD)]

        class Disposition(ctypes.Structure):
            _fields_ = [('delete', ctypes.c_ubyte)]

        self.ctypes = ctypes
        self.FileInformation = FileInformation
        self.Disposition = Disposition
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.GetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.POINTER(FileInformation))
        self.kernel.GetFileInformationByHandle.restype = wintypes.BOOL
        self.kernel.SetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        self.kernel.SetFileInformationByHandle.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.CloseHandle.restype = wintypes.BOOL

    @contextlib.contextmanager
    def opened(self, path, delete=False):
        access = 0x80 | (0x10000 if delete else 0)  # FILE_READ_ATTRIBUTES, DELETE
        flags = 0x02000000 | 0x00200000  # BACKUP_SEMANTICS, OPEN_REPARSE_POINT
        handle = self.kernel.CreateFileW(str(core.long_path(path)), access, 0x1 | 0x2, None, 3, flags, None)
        if handle == self.ctypes.c_void_p(-1).value:
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        try:
            info = self.FileInformation()
            if not self.kernel.GetFileInformationByHandle(handle, self.ctypes.byref(info)):
                raise self.ctypes.WinError(self.ctypes.get_last_error())
            yield handle, info
        finally:
            self.kernel.CloseHandle(handle)

    @staticmethod
    def identity(info):
        return info.volume, (info.index_high << 32) | info.index_low

    def delete(self, handle):
        disposition = self.Disposition(1)
        if not self.kernel.SetFileInformationByHandle(
                handle, 4, self.ctypes.byref(disposition), self.ctypes.sizeof(disposition)):
            raise self.ctypes.WinError(self.ctypes.get_last_error())


def _remove_windows(root, identity, expected):
    api = _WindowsFiles()

    def remove_node(path, relative, top=False):
        with api.opened(path, delete=True) as (handle, info):
            is_directory = bool(info.attributes & 0x10)
            is_reparse = bool(info.attributes & 0x400)
            if top and (api.identity(info) != identity or not is_directory or is_reparse):
                raise OSError('The recorded workspace changed during deletion.')
            if not top and expected is not None:
                current = path.lstat()
                volume, index = api.identity(info)
                details = (volume, index, current.st_mode, current.st_size, current.st_mtime_ns, current.st_ctime_ns)
                if expected.get(relative.as_posix()) != details:
                    raise OSError('Workspace contents changed during deletion.')
            if is_directory and not is_reparse:
                with os.scandir(core.long_path(path)) as scan:
                    names = [entry.name for entry in scan]
                for name in names:
                    remove_node(path / name, relative / name)
            api.delete(handle)

    with contextlib.ExitStack() as stack:
        for parent in reversed(root.parents):
            _, info = stack.enter_context(api.opened(parent))
            if info.attributes & 0x400:
                raise OSError('A workspace parent became a reparse point.')
        remove_node(root, Path(), top=True)


def remove(root, identity, entries=None):
    """Delete only the original directory, without traversing symlinks or junctions."""
    root = Path(root)
    expected = {item[0]: item[1:] for item in entries} if entries is not None else None
    if os.name == 'nt':
        _remove_windows(root, identity, expected)
    else:
        _remove_posix(root, identity, expected)
