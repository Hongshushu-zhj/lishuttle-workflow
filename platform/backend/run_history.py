"""Disk-backed local run records and immutable copies of their evidence.

Only explicitly selected files are copied. Original products are never moved,
and shared engine logs are labelled as changed during a run, not as exclusive
evidence of that run. Validation conclusions remain frozen even if the current
products change or an archive copy fails.
"""

from datetime import datetime, timezone
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import warnings


_CHUNK = 1024 * 1024
_SESSION_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z')


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _pid_alive(pid):
    """Check liveness without sending a signal (especially on Windows)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied is not evidence of death
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _fingerprint(path):
    path = Path(path)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(_CHUNK), b''):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OSError('文件在读取期间发生变化')
    return {'size': after.st_size, 'mtime_ns': after.st_mtime_ns, 'sha256': digest.hexdigest()}


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode('utf-8')


def _json_copy(value):
    return json.loads(_json_bytes(value))


def _cleanup_temporary(path):
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        # Cleanup cannot undo a committed replace or mask an earlier I/O error.
        try:
            warnings.warn(f'运行历史临时文件待清理：{path}；{error}', RuntimeWarning, stacklevel=2)
        except RuntimeWarning:
            pass


def _atomic_json(path, value):
    """Replace metadata on the same filesystem without a partially written JSON."""
    descriptor, name = tempfile.mkstemp(prefix='.session-', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as destination:
            destination.write(_json_bytes(value))
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, path)
    finally:
        _cleanup_temporary(temporary)


class RunHistory:
    """A lazily created store; constructing or reading an absent store is read-only."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self._lock = threading.RLock()

    def _directory(self, sid):
        key = str(sid)
        if not _SESSION_ID.fullmatch(key) or isinstance(sid, bool):
            raise ValueError('无效的运行会话编号')
        directory = self.root / key
        if not directory.resolve().is_relative_to(self.root):
            raise ValueError('运行会话路径超出历史目录')
        return directory

    def _read(self, sid):
        path = self._directory(sid) / 'session.json'
        try:
            with path.open(encoding='utf-8') as source:
                record = json.load(source)
            if (not isinstance(record, dict) or record.get('version') != 1 or
                    str(record.get('sid')) != str(sid) or
                    not isinstance(record.get('context'), dict) or
                    not isinstance(record.get('archive'), dict)):
                return None
            return record
        except (FileNotFoundError, json.JSONDecodeError, UnicodeError):
            return None

    def _write(self, record):
        _atomic_json(self._directory(record['sid']) / 'session.json', record)

    def _copy_file(self, source, destination, expected_sha256=None):
        """Stream to a temporary copy, then verify and publish it atomically."""
        source, destination = Path(source), Path(destination)
        before = source.stat()
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix='.archive-', suffix='.tmp', dir=destination.parent)
        temporary = Path(name)
        digest = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(descriptor, 'wb') as archived:
                with source.open('rb') as original:
                    for chunk in iter(lambda: original.read(_CHUNK), b''):
                        archived.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    archived.flush()
                    os.fsync(archived.fileno())
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise OSError('文件在归档期间发生变化')
            checksum = digest.hexdigest()
            if expected_sha256 and checksum != expected_sha256:
                raise OSError('文件内容与本次验证摘要不一致')
            os.replace(temporary, destination)
            return {'sha256': checksum, 'size': size, 'mtime_ns': after.st_mtime_ns}
        finally:
            _cleanup_temporary(temporary)

    @staticmethod
    def _source_path(value, cwd):
        path = Path(value)
        return (path if path.is_absolute() else Path(cwd) / path).resolve()

    @staticmethod
    def _log_paths(context, cwd):
        paths = []
        for directory in (context.get('bin_dir') or cwd, context.get('out_dir')):
            if directory:
                path = str(Path(directory).resolve() / 'uplan.log')
                if path not in paths:
                    paths.append(path)
        return paths

    def create(self, sid, label, context, command, cwd, baseline=None):
        with self._lock:
            directory = self._directory(sid)
            directory.mkdir(parents=True, exist_ok=False)
            context = _json_copy(context or {})
            record = {'version': 1, 'sid': sid, 'label': str(label), 'status': 'running',
                      'exit': None, 'created_at': _now(), 'finished_at': None,
                      'owner_pid': os.getpid(), 'command': _json_copy(command), 'cwd': str(cwd),
                      'context': context, 'baseline': _json_copy(baseline), 'result': None,
                      'cancelled': False, 'internal_error': '', 'snapshots': [],
                      'snapshot_issues': [], 'log_baseline': {},
                      'archive': {'status': 'pending', 'dir': str(directory), 'files': [], 'issues': []}}
            for name, value in (('context', context), ('command', command), ('baseline', baseline)):
                path = directory / (name + '.json')
                _atomic_json(path, value)
            schema_value = context.get('schema_path')
            if not schema_value and context.get('bin_dir') and context.get('schema_name'):
                schema_value = str(Path(context['bin_dir']) / 'runtimelibrary' / context['schema_name'])
            if schema_value:
                schema = self._source_path(schema_value, cwd)
                for kind, source in (('schema', schema), ('manifest', Path(str(schema) + '.manifest.json'))):
                    if kind == 'manifest' and not source.exists():
                        continue
                    target = directory / 'inputs' / (kind + ('.xml' if kind == 'schema' else '.json'))
                    try:
                        fingerprint = self._copy_file(source, target,
                            context.get('schema_digest') if kind == 'schema' else None)
                        record['snapshots'].append(dict(kind=kind, source=str(source), archive_path=str(target),
                                                        **fingerprint))
                    except OSError as error:
                        record['snapshot_issues'].append({'path': str(source), 'message': str(error)})
            for path in self._log_paths(context, cwd):
                try:
                    record['log_baseline'][path] = _fingerprint(path)
                except FileNotFoundError:
                    record['log_baseline'][path] = None
                except OSError as error:
                    record['log_baseline'][path] = {'error': str(error)}
            (directory / 'console.log').touch(exist_ok=False)
            self._write(record)
            return copy.deepcopy(record)

    def append(self, sid, line):
        with self._lock:
            if not (self._directory(sid) / 'session.json').is_file():
                raise KeyError('会话不存在')
            with (self._directory(sid) / 'console.log').open('a', encoding='utf-8', newline='\n') as log:
                log.write(str(line).rstrip('\r\n') + '\n')
                log.flush()

    def _archive_entry(self, record, source, kind, expected_sha256=None, **extra):
        source = Path(source)
        token = hashlib.sha256(os.path.normcase(str(source)).encode('utf-8')).hexdigest()
        # The source basename never participates in destination path construction.
        destination = self._directory(record['sid']) / 'artifacts' / (token + source.suffix[:20])
        entry = dict(kind=kind, source=str(source), path=str(source), status='archived', **extra)
        if expected_sha256:
            entry['expected_sha256'] = expected_sha256
        try:
            entry.update(self._copy_file(source, destination, expected_sha256))
            entry['archive_path'] = str(destination)
        except OSError as error:
            entry.update(status='unavailable', error=str(error))
            record['archive']['issues'].append({'path': str(source), 'message': str(error)})
        record['archive']['files'].append(entry)

    def finish(self, sid, status, exit_code, result, cancelled=False, internal_error=''):
        with self._lock:
            record = self._read(sid)
            if record is None:
                raise KeyError('会话不存在')
            if record.get('finished_at'):
                return copy.deepcopy(record)
            record.update(status=status, exit=exit_code, result=_json_copy(result),
                          cancelled=bool(cancelled), internal_error=str(internal_error or ''), finished_at=_now())
            record['archive'] = {'status': 'complete', 'dir': str(self._directory(sid)), 'files': [], 'issues': []}
            report = record['result'] if isinstance(record['result'], dict) else {}
            candidates = {}
            base = report.get('dir') or record['cwd']
            for item in list(report.get('files') or []) + list((report.get('artifacts') or {}).get('checked') or []):
                if not isinstance(item, dict):
                    continue
                value = item.get('path') or item.get('rel')
                if not value:
                    continue
                source = self._source_path(value, base)
                key = os.path.normcase(str(source))
                existing = candidates.setdefault(key, {'path': source})
                if item.get('sha256'):
                    existing['sha256'] = item['sha256']
            for item in candidates.values():
                self._archive_entry(record, item['path'], 'artifact', item.get('sha256'))
            for value, earlier in record.get('log_baseline', {}).items():
                try:
                    current = _fingerprint(value)
                except FileNotFoundError:
                    continue
                except OSError as error:
                    record['archive']['issues'].append({'path': value, 'message': str(error)})
                    continue
                if earlier is None or (isinstance(earlier, dict) and earlier.get('sha256') and
                                       earlier['sha256'] != current['sha256']):
                    self._archive_entry(record, value, 'engine_log', current['sha256'],
                                        attribution='new_during_run' if earlier is None else 'changed_during_run')
                elif isinstance(earlier, dict) and earlier.get('error'):
                    record['archive']['issues'].append({'path': value, 'message': '运行前日志不可读，无法确认本次来源'})
            if record['archive']['issues'] or record['snapshot_issues']:
                record['archive']['status'] = 'incomplete'
            self._write(record)
            return copy.deepcopy(record)

    def get(self, sid):
        with self._lock:
            try:
                record = self._read(sid)
            except ValueError:
                return None
            if record and record.get('status') in ('running', 'finalizing') and not _pid_alive(record.get('owner_pid')):
                record.update(status='interrupted', finished_at=_now(), exit=None,
                              internal_error='平台进程已结束，本次运行未完成收尾')
                record['result'] = {'verdict': 'unconfirmed', 'issues': [
                    {'severity': 'warning', 'code': 'RUN_INTERRUPTED', 'message': record['internal_error']}]}
                record['archive']['status'] = 'incomplete'
                record['recovery_persisted'] = True
                try:
                    self._write(record)
                except OSError as error:
                    record['recovery_persisted'] = False
                    record['internal_error'] += f'；中断状态保存失败：{error}'
                    record['result']['issues'].append({'severity': 'warning',
                        'code': 'HISTORY_RECOVERY_SAVE_FAILED', 'message': str(error)})
            return copy.deepcopy(record)

    def list(self, project='', limit=20, offset=0):
        if not self.root.exists():
            return []
        records = []
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            try:
                record = self.get(directory.name)
            except (OSError, ValueError):
                continue
            if record and (not project or record.get('context', {}).get('project') == project):
                records.append(record)
        records.sort(key=lambda item: (item.get('created_at', ''), str(item.get('sid', ''))), reverse=True)
        offset, limit = max(0, int(offset)), max(0, int(limit))
        return records[offset:offset + limit]

    def output(self, sid, since=0, limit=None):
        record = self.get(sid)
        if record is None:
            return {'error': '会话不存在', 'code': 'SESSION_NOT_FOUND'}
        since = max(0, int(since))
        limit = None if limit is None else max(0, int(limit))
        lines, total = [], 0
        try:
            with (self._directory(sid) / 'console.log').open(encoding='utf-8', errors='replace') as log:
                for total, line in enumerate(log, start=1):
                    if total > since and (limit is None or len(lines) < limit):
                        lines.append(line.rstrip('\r\n'))
        except FileNotFoundError:
            pass
        return dict(lines=lines, total=total, next=min(since, total) + len(lines),
                    next_since=min(since, total) + len(lines),
                    has_more=since + len(lines) < total,
                    **{key: copy.deepcopy(record.get(key)) for key in
                       ('status', 'exit', 'label', 'context', 'result', 'cancelled', 'internal_error', 'archive')})

    def current(self, sid):
        record = self.get(sid)
        files = []
        if record:
            for archived in record.get('archive', {}).get('files', []):
                if archived.get('kind') != 'artifact':
                    continue
                item = {'path': archived['source'], 'status': 'unconfirmed'}
                # An archive checksum describes copy time. Only the checksum
                # produced by validation can establish a historical match.
                expected = archived.get('expected_sha256')
                try:
                    actual = _fingerprint(archived['source'])
                    item.update(sha256=actual['sha256'], size=actual['size'])
                    if expected:
                        item['status'] = 'matched' if actual['sha256'] == expected else 'changed'
                except FileNotFoundError:
                    item['status'] = 'missing'
                except OSError as error:
                    item['error'] = str(error)
                files.append(item)
        states = {item['status'] for item in files}
        status = ('missing' if 'missing' in states else 'changed' if 'changed' in states else
                  'unconfirmed' if not states or 'unconfirmed' in states else 'matched')
        return {'status': status, 'files': files}
