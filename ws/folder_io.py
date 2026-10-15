"""Bind source writes to the previewed directory; never replace existing leaves."""
from contextlib import contextmanager
import os
from . import core

DIR_FD = os.name != 'nt'


def check(folder, identity, written=None):
    try:
        info = folder.stat()
        valid = [info.st_dev, info.st_ino] == identity
    except OSError:
        valid = False
    if not valid:
        detail = f' Write may have reached {written}; inspect it before retrying.' if written else ''
        raise core.WsError('Folder identity changed; stop and preview again.' + detail)


@contextmanager
def directory(folder, identity, written=None):
    """One write operation per context on Windows, with an exact recovery path."""
    if not DIR_FD:
        check(folder, identity)
        try: yield None
        finally: check(folder, identity, written)
        return
    fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if [info.st_dev, info.st_ino] != identity:
            raise core.WsError('Folder identity changed; stop and preview again.')
        yield fd
    finally: os.close(fd)


def create(folder, identity, name, text):
    with directory(folder, identity, folder/name) as fd:
        if fd is None:
            stream = (folder/name).open('x', encoding='utf-8', newline='')
        else:
            leaf = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            stream = os.fdopen(leaf, 'w', encoding='utf-8', newline='')
        with stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
