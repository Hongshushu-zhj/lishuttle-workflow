"""Read current Bin XML and explicitly import byte-preserving local copies.

Discovery, descriptions and previews never create files. Imported copies have no
assembly manifest: XML remains the only source of their runtime parameters.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET

from file_safety import FileTransaction
from project_config import validate_runtime_schema_name
from task_schema import LOCAL_PATHS, runtime_scene

_IMPORT_KEY = secrets.token_bytes(32)
_IMPORT_LOCK = threading.RLock()


def _canonical(path):
    return os.path.normcase(os.path.realpath(path))


def _is_link(path):
    path = Path(path)
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        return True
    try:
        return bool(getattr(path.lstat(), 'st_file_attributes', 0)
                    & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))
    except FileNotFoundError:
        return False


def _bin_directory(env):
    project, build = env.get('PROJECT_DIR'), env.get('BUILD_SUBDIR')
    if not isinstance(project, str) or not project.strip():
        raise ValueError('请先选择本地项目')
    if not isinstance(build, str) or not build.strip() or any(char in build for char in '\0\r\n'):
        raise ValueError('请先配置当前项目的构建目录')
    return Path(os.path.realpath(Path(project) / build.replace('\\', os.sep) / 'Bin'))


def runtime_directory(env):
    """Return the current runtime directory without creating it or following links."""
    binary = _bin_directory(env)
    runtime = binary / 'runtimelibrary'
    if _is_link(runtime) or Path(_canonical(runtime)).parent != Path(_canonical(binary)):
        raise ValueError('运行配置目录不能是链接或位于当前 Bin 目录之外')
    if runtime.exists() and not runtime.is_dir():
        raise ValueError('当前运行配置目录不是文件夹')
    return str(runtime).replace('\\', '/')


def runtime_scope(env):
    """Use the actual Bin path so equivalent paths share one execution selection."""
    return hashlib.sha256(_canonical(_bin_directory(env)).encode('utf-8')).hexdigest()[:20]


def resolve_runtime_config(env, schema):
    """Resolve one safe local filename; a not-yet-created file is permitted."""
    validate_runtime_schema_name(schema)
    runtime = Path(runtime_directory(env))
    path = runtime / schema
    if _is_link(path) or Path(_canonical(path)).parent != Path(_canonical(runtime)):
        raise ValueError('运行配置不能是链接或位于当前运行目录之外')
    if path.exists() and not path.is_file():
        raise ValueError('运行配置必须是 XML 文件，不能是目录')
    return path


def _read_runtime(path):
    try:
        with open(path, 'rb') as stream:
            raw = stream.read()
            metadata = os.fstat(stream.fileno())
        root = ET.fromstring(raw.decode('utf-8-sig'))
    except (OSError, UnicodeError, ET.ParseError, ValueError) as exc:
        raise ValueError(f'无法读取有效的 UTF-8 运行配置 XML：{path}：{exc}') from exc
    if root.tag != 'RuntimeSchema':
        raise ValueError(f'不是 RuntimeSchema 运行配置：{path}')
    return raw, root, metadata


def _resource_path(binary, value):
    if not value:
        return ''
    return os.path.abspath(os.path.join(binary, value.replace('\\', os.sep))).replace('\\', '/')


def _description(env, path, schema, raw, root, metadata):
    binary = _bin_directory(env)
    values = {}
    for child in root:
        if isinstance(child.tag, str) and child.tag not in values:
            values[child.tag] = child.text or ''
    paths = {tag: values[tag] for tag in sorted(LOCAL_PATHS) if tag in values}
    resolved = {tag: _resource_path(binary, value) for tag, value in paths.items()}
    warnings = []
    name = root.get('name', '')
    output = resolved.get('PathlossDirectory', '')
    out_dir = _resource_path(output, name) if output and name else ''
    if not name:
        warnings.append('RuntimeSchema 缺少 name，运行前需补齐任务名')
    if not output:
        warnings.append('缺少 PathlossDirectory，无法确定真实输出目录')
    for tag, path_value in resolved.items():
        if tag != 'PathlossDirectory' and path_value and not os.path.exists(path_value):
            warnings.append(f'{tag} 指向的资源不存在：{path_value}')
    duplicates = [tag for tag, count in Counter(child.tag for child in root).items() if count > 1]
    if duplicates:
        warnings.append('保留原 XML 重复字段，运行前请检查：' + '、'.join(duplicates))
    return {'schema': schema, 'runtime_name': name, 'name': name,
            'scene': runtime_scene(values), 'revision': hashlib.sha256(raw).hexdigest(),
            'file': str(path).replace('\\', '/'), 'path': str(path).replace('\\', '/'), 'out_dir': out_dir,
            'engineering_file': resolved.get('EngineeringFilePath', ''),
            'values': values, 'params': dict(values), 'paths': paths, 'resolved_paths': resolved,
            'warnings': warnings, 'valid': True, 'loadable': True, 'reason': '',
            'modified': datetime.fromtimestamp(metadata.st_mtime, timezone.utc).isoformat(),
            'modified_time': metadata.st_mtime}


def describe_runtime_config(env, schema):
    path = resolve_runtime_config(env, schema)
    return _description(env, path, schema, *_read_runtime(path))


def list_runtime_configs(env):
    runtime = Path(runtime_directory(env))
    configs = []
    if runtime.is_dir():
        for path in sorted(runtime.iterdir(), key=lambda candidate: candidate.name.casefold()):
            if path.suffix.lower() != '.xml' or _is_link(path) or not path.is_file():
                continue
            try:
                resolve_runtime_config(env, path.name)
            except ValueError:
                continue
            try:
                configs.append(describe_runtime_config(env, path.name))
            except ValueError as exc:
                # Valid XML belonging to another schema is not a runtime entry.
                if str(exc).startswith('不是 RuntimeSchema'):
                    continue
                revision, modified, modified_time = '', '', None
                try:
                    with open(path, 'rb') as source:
                        revision = hashlib.sha256(source.read()).hexdigest()
                        modified_time = os.fstat(source.fileno()).st_mtime
                    modified = datetime.fromtimestamp(modified_time, timezone.utc).isoformat()
                except OSError:
                    pass  # Keep an unreadable/disappearing entry disabled with its cause.
                configs.append({'schema': path.name, 'file': path.as_posix(), 'path': path.as_posix(),
                    'runtime_name': '', 'name': '', 'scene': '', 'revision': revision,
                    'out_dir': '', 'engineering_file': '', 'values': {}, 'params': {},
                    'warnings': [], 'valid': False, 'loadable': False, 'reason': str(exc),
                    'modified': modified, 'modified_time': modified_time})
    return {'directory': runtime.as_posix(), 'scope': runtime_scope(env), 'configs': configs}


def _source_path(source):
    if not isinstance(source, str) or not source or any(char in source for char in '\0\r\n'):
        raise ValueError('请输入本机已有 XML 的绝对路径')
    path = Path(source)
    if not path.is_absolute():
        raise ValueError('导入源必须是本机 XML 的绝对路径')
    if not path.is_file():
        raise ValueError('导入源 XML 不存在或不是文件')
    return path.resolve()


def _state(path):
    """Fingerprint an existence assertion, including broken links and directories."""
    path = Path(path)
    if not os.path.lexists(path):
        return 'missing'
    if _is_link(path):
        return 'link:' + _canonical(path)
    if not path.is_file():
        return 'directory'
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _preview(env, source, destination_schema):
    source_path = _source_path(source)
    destination = resolve_runtime_config(env, destination_schema)
    raw, root, metadata = _read_runtime(source_path)
    description = _description(env, source_path, destination_schema, raw, root, metadata)
    manifest = Path(str(destination) + '.manifest.json')
    same_file = destination.is_file() and os.path.samefile(source_path, destination)
    destination_state, manifest_state = _state(destination), _state(manifest)
    conflict = not same_file and (destination_state != 'missing' or manifest_state != 'missing')
    binding = {'project': _canonical(env['PROJECT_DIR']),
        'profile': env.get('PROJECT_PROFILE_ID', ''), 'revision': env.get('PROJECT_PROFILE_REVISION', ''),
        'scope': runtime_scope(env), 'source': _canonical(source_path),
        'source_revision': description['revision'], 'destination': _canonical(destination),
        'destination_state': destination_state, 'manifest_state': manifest_state}
    serialized = json.dumps(binding, sort_keys=True, ensure_ascii=False).encode('utf-8')
    token = hmac.new(_IMPORT_KEY, serialized, hashlib.sha256).hexdigest()
    preview = dict(description, source=source_path.as_posix(), destination=destination.as_posix(),
        destination_schema=destination_schema, source_revision=description['revision'],
        scope=runtime_scope(env), same_file=same_file, activation_only=same_file,
        conflict=conflict, can_import=not conflict, token=token,
        conflict_reason='目标 XML 或同名装配 manifest 已存在，请改名或直接使用当前配置' if conflict else '')
    preview['description'] = dict(description)
    return preview, raw, destination, manifest


def preview_runtime_import(env, source, destination_schema):
    return _preview(env, source, destination_schema)[0]


def import_runtime_config(env, source, destination_schema, token):
    """Revalidate a preview and atomically publish a new complete file, never replace."""
    if not isinstance(token, str) or not token:
        raise ValueError('请先预览导入，再确认当前预览')
    with _IMPORT_LOCK:
        preview, raw, destination, manifest = _preview(env, source, destination_schema)
        if not hmac.compare_digest(token, preview['token']):
            raise ValueError('导入预览已变化或失效，请重新预览')
        if preview['conflict']:
            raise ValueError(preview['conflict_reason'])
        if preview['same_file']:
            return dict(describe_runtime_config(env, destination_schema), imported=False,
                        same_file=True, activation_only=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.' + destination.name + '.',
                                                 suffix='.tmp', dir=destination.parent)
        temporary = Path(temporary)
        cleanup_warning = ''
        try:
            with os.fdopen(descriptor, 'wb') as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            # Preparation can take time. Recheck all preview assertions before publication.
            current, _, checked_destination, _ = _preview(env, source, destination_schema)
            if not hmac.compare_digest(token, current['token']) or checked_destination != destination:
                raise ValueError('导入预览已变化，请重新预览')
            with FileTransaction() as transaction:
                transaction.touch(destination)
                if os.path.lexists(destination) or os.path.lexists(manifest):
                    transaction.discard_snapshot(destination)
                    raise ValueError('目标 XML 或同名 manifest 已存在，导入发生冲突')
                try:
                    # Hard-link publication is atomic and cannot overwrite another writer.
                    # Filesystems without this guarantee fail without a partial target.
                    os.link(temporary, destination)
                except BaseException:
                    transaction.discard_snapshot(destination)
                    raise
                if os.path.lexists(manifest):
                    # Preserve an external replacement/edit even when reporting a conflict.
                    if (not os.path.samefile(temporary, destination)
                            or _state(destination) != preview['revision']):
                        transaction.discard_snapshot(destination)
                    raise ValueError('同名 manifest 已出现，导入发生冲突')
                transaction.commit()
        finally:
            original_error = sys.exc_info()[1]
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_warning = f'导入临时文件尚未清理：{temporary}；{exc}'
                if original_error is not None and hasattr(original_error, 'add_note'):
                    original_error.add_note(cleanup_warning)
        result = dict(describe_runtime_config(env, destination_schema), imported=True,
                      same_file=False, activation_only=False)
        if cleanup_warning:
            result['cleanup_warning'] = cleanup_warning
        return result
