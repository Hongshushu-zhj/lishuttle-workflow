"""Desktop-only route composition; ordinary browser server stays unchanged."""
from functools import wraps
import os
from pathlib import Path
import threading

import core
from discovery import DiscoveryManager
from migration import LegacyImporter, PreferencesStore
from run_guard import RuntimeBusy
from runtime_paths import resolve_paths

SCANNER = DiscoveryManager()
_STORES = {}
_STORE_LOCK = threading.Lock()


def _prefs():
    path = Path(resolve_paths().preferences_file)
    with _STORE_LOCK:
        return _STORES.setdefault(str(path), PreferencesStore(path))


def _error_boundary(fn):
    @wraps(fn)
    def wrapped(body):
        try:
            return fn(body or {})
        except RuntimeBusy as exc:
            return exc.response()
        except (ValueError, OSError, KeyError, TypeError) as exc:
            code = 'PREVIEW_STALE' if '重新预览' in str(exc) else 'FILE_CONFLICT' if '已变化' in str(exc) else 'INVALID_INPUT'
            return dict(ok=False, error=str(exc), message=str(exc), code=code)
    return wrapped


def _write(label):
    def decorate(fn):
        @_error_boundary
        @wraps(fn)
        def wrapped(body):
            from server import PROJECT_LOCK, project_operation
            with core.RUNTIME.operation(label):
                with PROJECT_LOCK:
                    return project_operation(fn)(body)
        return wrapped
    return decorate


@_error_boundary
def desktop_info(_):
    paths = resolve_paths()
    return dict(version='0.1.0', channel=os.environ.get('LISHUTTLE_DESKTOP_CHANNEL', 'dev'),
        data_dir=str(paths.data_root), resource_root=str(paths.resource_root),
        logs_dir=str(paths.logs_dir), schema_version=1)


@_error_boundary
def preferences_get(_):
    return _prefs().read()


@_write('保存桌面设置')
def preferences_save(body):
    return _prefs().write(body.get('values'), body.get('revision'))


@_error_boundary
def discover_start(body):
    return dict(id=SCANNER.start(body.get('roots'), body.get('max_depth', 4), body.get('max_entries', 20000)))


def _id(body):
    value = body.get('id', '')
    if isinstance(value, list):
        value = value[0] if value else ''
    if not isinstance(value, str):
        raise ValueError('扫描 ID 无效')
    return value


@_error_boundary
def discover_status(query):
    return SCANNER.status(_id(query))


@_error_boundary
def discover_cancel(body):
    return SCANNER.cancel(_id(body))


@_error_boundary
def legacy_preview(body):
    paths = resolve_paths()
    importer = LegacyImporter(core.ProjectStore(core.ENV_FILE), paths.maintenance_dir, paths.runs_dir)
    return importer.preview(body.get('source_root'), body.get('include_history', False), body.get('path_mappings'))


@_write('导入旧版项目配置')
def legacy_apply(body):
    paths = resolve_paths()
    importer = LegacyImporter(core.ProjectStore(core.ENV_FILE), paths.maintenance_dir, paths.runs_dir)
    return importer.apply(body.get('source_root'), body.get('token'), body.get('include_history', False), body.get('path_mappings'))


ROUTES = {
    ('GET', 'desktop_info'): desktop_info,
    ('GET', 'desktop_preferences'): preferences_get,
    ('POST', 'desktop_preferences'): preferences_save,
    ('POST', 'discover_start'): discover_start,
    ('GET', 'discover_status'): discover_status,
    ('POST', 'discover_cancel'): discover_cancel,
    ('POST', 'legacy_import_preview'): legacy_preview,
    ('POST', 'legacy_import_apply'): legacy_apply,
}


def close():
    SCANNER.close()
