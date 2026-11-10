"""Small standard-library tools for recoverable local file updates.

Individual replacements are atomic on their destination filesystem. A transaction
recovers from observed Python exceptions; it is not a cross-file power-loss
transaction. Revision checks narrow, but cannot eliminate, the race with an
external process which ignores this protocol between the final check and replace.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import uuid
import warnings


class FileConflict(ValueError):
    """The current file content no longer matches the expected revision."""

    def __init__(self, message, recovery_dir=None):
        self.recovery_dir = str(recovery_dir) if recovery_dir is not None else None
        if self.recovery_dir is not None:
            message += f'; earlier transaction snapshots retained at: {self.recovery_dir}'
        super().__init__(message)


class FileRollbackError(OSError):
    """Recovery failed; snapshots remain at ``recovery_dir`` for manual recovery."""

    def __init__(self, recovery_dir, errors):
        self.recovery_dir = str(recovery_dir)
        self.errors = errors
        details = '; '.join(f'{path}: {error}' for path, error in errors)
        super().__init__(f'File rollback failed ({details}); recovery files: {self.recovery_dir}')


def file_revision(path) -> str:
    """Return a content SHA-256, or the literal ``missing`` for an absent file."""
    digest = hashlib.sha256()
    try:
        with open(path, 'rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
    except FileNotFoundError:
        return 'missing'
    return digest.hexdigest()


def _temporary_path(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    return descriptor, Path(name)


def _make_writable(path):
    path = Path(path)
    path.chmod(path.stat().st_mode | stat.S_IWRITE)


def _unlink_file(path):
    try:
        Path(path).unlink(missing_ok=True)
    except PermissionError:
        if os.name != 'nt':
            raise
        _make_writable(path)
        Path(path).unlink(missing_ok=True)


def _discard_snapshots(directory):
    def retry_read_only(function, path, exception_info):
        if os.name != 'nt' or not isinstance(exception_info[1], PermissionError):
            raise exception_info[1]
        _make_writable(path)
        function(path)
    shutil.rmtree(directory, onerror=retry_read_only)


def _warn_cleanup(path, error):
    try:
        warnings.warn(f'File cleanup pending at: {path}; {error}', RuntimeWarning, stacklevel=3)
    except RuntimeWarning:
        # Diagnostic policy must not change an already committed file result.
        pass


def _cleanup_prepared(temporaries):
    for temporary in temporaries:
        try:
            _unlink_file(temporary)
        except OSError as error:
            # Retain a busy temporary and report its exact location; this is
            # housekeeping, not a failed replacement or a failed rollback.
            _warn_cleanup(temporary, error)


def _prepare_bytes(path, data):
    descriptor, temporary = _temporary_path(path)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        _cleanup_prepared((temporary,))
        raise
    return temporary


def _prepare_copy(path, source):
    descriptor, temporary = _temporary_path(path)
    try:
        # Keep the originally writable handle while copy2 applies source mode
        # bits; reopening a copied read-only file for fsync fails on Windows.
        with os.fdopen(descriptor, 'r+b') as prepared:
            shutil.copy2(source, temporary)
            os.fsync(prepared.fileno())
    except BaseException:
        _cleanup_prepared((temporary,))
        raise
    return temporary


def _history_path(path):
    moment = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    return path.parent / '.lishuttle-history' / f'{path.name}.{moment}.{uuid.uuid4().hex}.bak'


class FileTransaction:
    """Snapshot only files explicitly touched, then restore them on exceptions.

    ``touch(path)`` must precede a caller's direct mutation. ``write`` and ``copy``
    register their destinations automatically. Snapshots are stored on disk, not
    as copies of entire resource directories or large maps in memory.
    """

    def __init__(self):
        self.recovery_dir = None
        self._files = {}
        self._retained = {}
        self._snapshot_serial = 0
        self._closed = False
        self._rollback_failed = False

    def __enter__(self):
        if self._closed:
            raise RuntimeError('File transaction is already closed')
        return self

    def _ensure_recovery(self):
        if self.recovery_dir is None:
            self.recovery_dir = tempfile.mkdtemp(prefix='lishuttle-rollback-')

    def touch(self, path):
        if self._closed:
            raise RuntimeError('File transaction is already closed')
        path = Path(os.path.abspath(path))
        if path in self._files:
            return path
        self._ensure_recovery()
        snapshot = None
        if path.exists():
            if not path.is_file():
                raise IsADirectoryError(path)
            snapshot = Path(self.recovery_dir) / f'{self._snapshot_serial:04d}-{path.name}.snapshot'
            shutil.copy2(path, snapshot)
        self._snapshot_serial += 1
        self._files[path] = snapshot
        recorded = dict(self._retained)
        recorded.update(self._files)
        mapping = {str(target): str(old) if old else None for target, old in recorded.items()}
        (Path(self.recovery_dir) / 'recovery.json').write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')
        return path

    def discard_snapshot(self, path, preserve=False):
        """Exclude an externally edited path from rollback.

        Newly registered, unpublished paths can simply be discarded. If this
        transaction had an earlier snapshot, ``preserve=True`` retains the
        recovery directory while leaving the external content untouched.
        """
        path = Path(os.path.abspath(path))
        if path in self._files:
            snapshot = self._files.pop(path)
            if preserve:
                self._retained[path] = snapshot
        return self.recovery_dir if path in self._retained else None

    def write(self, path, data: bytes, backup=False, expected_revision=None) -> str:
        return _atomic_write(path, data, backup, expected_revision, outer=self)

    def copy(self, source, destination, backup=False):
        """Copy through a temporary file, optionally preserving prior versions.

        Resources and snapshots use streamed copies; even a large resource is
        never loaded into memory as a complete bytes object.
        """
        destination = Path(os.path.abspath(destination))
        original_revision = file_revision(destination)
        temporaries = []
        try:
            replacement = _prepare_copy(destination, source)
            temporaries.append(replacement)
            backup_path = history = backup_temporary = history_temporary = None
            if backup and original_revision != 'missing':
                backup_path = Path(str(destination) + '.bak')
                history = _history_path(destination)
                history.parent.mkdir(parents=True, exist_ok=True)
                backup_temporary = _prepare_copy(backup_path, destination)
                temporaries.append(backup_temporary)
                # The mutable .bak and immutable version must have separate
                # storage, even when history is published through a hard link.
                history_temporary = _prepare_copy(history, backup_temporary)
                temporaries.append(history_temporary)
            _publish_prepared(destination, replacement, original_revision,
                              backup_path, backup_temporary, history,
                              history_temporary, outer=self)
        finally:
            _cleanup_prepared(temporaries)
        return destination

    def commit(self):
        if self._closed:
            return
        # Targets have already been published (or successfully restored). A
        # busy recovery snapshot must not turn that result into a save failure.
        self._closed = True
        if self.recovery_dir is not None and not self._retained:
            try:
                _discard_snapshots(self.recovery_dir)
            except OSError as error:
                _warn_cleanup(self.recovery_dir, error)

    def rollback(self):
        if self._closed:
            return
        errors = []
        for path, snapshot in reversed(list(self._files.items())):
            temporary = None
            try:
                if snapshot is None:
                    _unlink_file(path)
                elif file_revision(path) != file_revision(snapshot):
                    descriptor, temporary = _temporary_path(path)
                    os.close(descriptor)
                    shutil.copy2(snapshot, temporary)
                    if os.name == 'nt' and path.exists():
                        _make_writable(path)
                    os.replace(temporary, path)
            except Exception as error:
                errors.append((str(path), error))
            finally:
                if temporary is not None:
                    try:
                        _unlink_file(temporary)
                    except Exception as error:
                        errors.append((f'{path} temporary {temporary}', error))
        if errors:
            self._rollback_failed = True
            raise FileRollbackError(self.recovery_dir, errors)
        self.commit()

    def __exit__(self, kind, error, traceback):
        if self._rollback_failed:
            return False
        if kind is None:
            self.commit()
        else:
            try:
                self.rollback()
            except FileRollbackError as recovery_error:
                raise recovery_error from error
        return False


def atomic_write(path, data: bytes, backup=False, expected_revision=None) -> str:
    """Replace a file from a same-directory temporary, returning its new revision.

    With ``backup=True``, the previous content becomes both ``<path>.bak`` and a
    unique immutable history entry. A failure restores the old destination and
    backups. ``expected_revision`` is checked before preparation and again just
    before commit. Even when omitted, edits made during preparation are detected.
    """
    return _atomic_write(path, data, backup, expected_revision)


def _atomic_write(path, data, backup, expected_revision, outer=None):
    if not isinstance(data, bytes):
        raise TypeError('atomic_write data must be bytes')
    path = Path(os.path.abspath(path))
    original_revision = file_revision(path)
    if expected_revision is not None and original_revision != expected_revision:
        raise _external_conflict(path, f'File changed: {path}', outer)
    old_data = path.read_bytes() if original_revision != 'missing' and backup else None
    temporaries = []
    try:
        replacement = _prepare_bytes(path, data)
        temporaries.append(replacement)
        backup_path = Path(str(path) + '.bak') if old_data is not None else None
        history = _history_path(path) if old_data is not None else None
        backup_temporary = history_temporary = None
        if old_data is not None:
            backup_temporary = _prepare_bytes(backup_path, old_data)
            temporaries.append(backup_temporary)
            history_temporary = _prepare_bytes(history, old_data)
            temporaries.append(history_temporary)
        _publish_prepared(path, replacement, original_revision, backup_path,
                          backup_temporary, history, history_temporary, outer)
        return hashlib.sha256(data).hexdigest()
    finally:
        _cleanup_prepared(temporaries)


def _publish_prepared(path, replacement, original_revision, backup_path,
                      backup_temporary, history, history_temporary, outer=None):
    # No target has been changed yet. A conflict here must preserve the external
    # edit rather than restore the content read at entry.
    if file_revision(path) != original_revision:
        raise _external_conflict(path, f'File changed while preparing write: {path}', outer)
    with FileTransaction() as transaction:
        registered = []
        for touched in (path, backup_path, history):
            if touched is not None:
                transaction.touch(touched)
                if outer is not None:
                    is_new = touched not in outer._files
                    outer.touch(touched)
                    if is_new:
                        registered.append(touched)
        if file_revision(path) != original_revision:
            # Snapshot preparation may involve disk I/O too. Nothing has been
            # published; discard snapshots without undoing this edit.
            conflict = _external_conflict(path, f'File changed before commit: {path}',
                                          outer, registered)
            transaction.commit()
            raise conflict
        os.replace(replacement, path)
        if backup_path is not None:
            _publish_history(history_temporary, history)
            os.replace(backup_temporary, backup_path)


def _external_conflict(path, message, outer, newly_registered=()):
    recovery_dir = None
    if outer is not None:
        had_prior_snapshot = path in outer._files and path not in newly_registered
        for registered in newly_registered:
            outer.discard_snapshot(registered)
        if had_prior_snapshot:
            recovery_dir = outer.discard_snapshot(path, preserve=True)
        elif path in outer._retained:
            recovery_dir = outer.recovery_dir
    return FileConflict(message, recovery_dir)


def _publish_history(source, history):
    # Prefer atomic publication, with an exclusive streamed fallback on drives
    # which do not support hard links. Neither route replaces an existing entry.
    try:
        os.link(source, history)
    except FileExistsError:
        raise
    except OSError:
        with open(source, 'rb') as original, open(history, 'xb') as output:
            shutil.copyfileobj(original, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
