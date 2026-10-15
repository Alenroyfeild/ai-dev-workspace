"""Descriptor-bound source creation and preview-checked replacement."""
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


@contextmanager
def parent(folder, identity, name, writing=False):
    from pathlib import PurePosixPath
    parts=PurePosixPath(name).parts
    if not parts or len(parts)>2 or any(p in ('.','..','/') for p in parts) or (len(parts)==2 and parts[0] not in ('entries','status')):
        raise core.WsError('Invalid shared file path.')
    path=folder/name;child=None
    with directory(folder,identity,path if writing else None) as fd:
        try:
            if len(parts)==2:
                if writing:
                    try:
                        if fd is None:
                            path.parent.mkdir();check(folder,identity,path.parent)
                        else: os.mkdir(parts[0],0o700,dir_fd=fd)
                    except FileExistsError: pass
                if fd is not None: child=os.open(parts[0],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            if fd is None and (path.parent.is_symlink() or path.is_symlink()):raise core.WsError('Shared paths must not use symlinks.')
            yield child if child is not None else fd, parts[-1] if fd is not None else path
        finally:
            if child is not None:os.close(child)


def _read(fd, leaf):
    import stat
    try: handle=os.open(leaf,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),**({'dir_fd':fd} if fd is not None else {}))
    except FileNotFoundError:return None
    with os.fdopen(handle,'r',encoding='utf-8',newline='') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise core.WsError('Shared file must be regular.')
        text=stream.read(1024*1024+1)
        if len(text.encode())>1024*1024:raise core.WsError('Shared file exceeds 1 MiB.')
        return text


def read(folder, identity, name):
    try:
        with parent(folder,identity,name) as (fd,leaf):return _read(fd,leaf)
    except FileNotFoundError:return None


def replace(folder, identity, name, text, expected):
    import uuid
    with parent(folder,identity,name,True) as (fd,leaf):
        if _read(fd,leaf)!=expected:raise core.WsError('Shared file changed; retain both copies and preview again: '+name)
        if text==expected:return
        if fd is None:
            if text is None:leaf.unlink()
            else:core.atomic_write(leaf,text)
        elif text is None:os.unlink(leaf,dir_fd=fd)
        else:
            temporary='.ws-'+uuid.uuid4().hex
            try:
                handle=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600,dir_fd=fd)
                with os.fdopen(handle,'w',encoding='utf-8',newline='') as stream:
                    stream.write(text);stream.flush();os.fsync(stream.fileno())
                os.replace(temporary,leaf,src_dir_fd=fd,dst_dir_fd=fd)
            finally:
                try:os.unlink(temporary,dir_fd=fd)
                except FileNotFoundError:pass
