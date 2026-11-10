"""OS-owned resource leases shared by web services and local CLI processes.

Lock files are stable identities, never occupancy markers: only the operating
system byte/file lock decides ownership, including after a process is killed.
"""

import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time


DEFAULT_LOCK_DIR = Path(tempfile.gettempdir()) / 'lishuttle-resource-locks-v1'
OWNER_FIELDS = ('label', 'project', 'bin_dir', 'out_dir', 'operation', 'phase', 'sid')


class ResourceBusy(RuntimeError):
    code = 'RUNTIME_BUSY'

    def __init__(self, owner=None):
        self.owner = dict(owner or {})
        label = self.owner.get('label') or '另一平台或本地运行'
        super().__init__(f'运行资源正在被 {label} 使用，请等待结束后重试')


def normalize_resource(resource):
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(resource)))))


def _lock(stream):
    stream.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(stream):
    stream.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _read_owner(path):
    try:
        with open(path, 'rb') as stream:
            # Byte zero is locked on Windows; metadata lives after that byte.
            stream.seek(1)
            owner = json.loads(stream.read(16384).decode('utf-8'))
        if not isinstance(owner, dict):
            return {}
        return {key: value for key, value in owner.items()
                if key in OWNER_FIELDS + ('pid', 'started_at') and
                isinstance(value, (str, int, float))}
    except (OSError, ValueError, UnicodeError):
        return {}


class ResourceLease:
    def __init__(self, resources, lock_dir=None, owner=None):
        self.resources = sorted({normalize_resource(item) for item in resources if item})
        self.lock_dir = Path(lock_dir) if lock_dir is not None else DEFAULT_LOCK_DIR
        self.owner = {key: value for key, value in (owner or {}).items()
                      if key in OWNER_FIELDS and isinstance(value, (str, int, float))}
        self.owner.update(pid=os.getpid(), started_at=time.time())
        self._streams = []

    def acquire(self):
        if self._streams:
            return self
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        try:
            for resource in self.resources:
                name = hashlib.sha256(resource.encode('utf-8')).hexdigest() + '.lock'
                path = self.lock_dir / name
                stream = os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT, 0o600), 'r+b', buffering=0)
                try:
                    # Windows supports a byte lock past EOF, so acquire before
                    # initializing; concurrent constructors cannot write byte 0.
                    _lock(stream)
                except OSError as exc:
                    stream.close()
                    if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise ResourceBusy(_read_owner(path)) from exc
                    raise
                self._streams.append(stream)
                stream.seek(1)
                stream.write(json.dumps(self.owner, ensure_ascii=False).encode('utf-8'))
                stream.truncate()
            return self
        except BaseException:
            self.release()
            raise

    def release(self):
        streams, self._streams = self._streams, []
        for stream in reversed(streams):
            try:
                _unlock(stream)
            finally:
                stream.close()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()
