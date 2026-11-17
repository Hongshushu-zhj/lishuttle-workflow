"""Versioned preferences and explicit, previewed import of legacy configuration."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import shutil
import tempfile
import ntpath
import posixpath
from file_safety import atomic_write
from project_config import ProjectStore, FIELDS, MACHINE_FIELDS, PROJECT_FIELDS, atomic_json, project_id
from task_schema import LOCAL_PATHS


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


class _PreferencesVersionError(ValueError):
    """A future format must never be replaced by an older backup."""


class PreferencesStore:
    KEYS = {'onboarding_complete', 'compact_mode', 'log_follow', 'scan_roots', 'log_panel_height', 'last_section', 'theme'}

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    @staticmethod
    def _load(path):
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, dict) and type(data.get('schema_version')) is int and data['schema_version'] > 1:
            raise _PreferencesVersionError('设置数据版本不兼容，请使用更新版本应用')
        if (not isinstance(data, dict) or type(data.get('schema_version')) is not int
                or data['schema_version'] != 1 or not isinstance(data.get('values'), dict)):
            raise ValueError('设置数据结构损坏')
        return data

    def read(self):
        with self.lock:
            recovery = None
            try:
                data = self._load(self.path) if self.path.exists() else {'schema_version': 1, 'values': {}}
            except _PreferencesVersionError:
                raise
            except (ValueError, UnicodeError):
                backup = self.path.with_suffix('.json.bak')
                try:
                    data = self._load(backup)
                except (OSError, ValueError) as error:
                    raise ValueError('设置文件损坏且无可读备份，请保留原文件后重新配置') from error
                recovery = dict(available=True, message='设置文件损坏，当前显示上次备份；保存后恢复，损坏原件将另存。')
            result = dict(data, revision=digest(data))
            if recovery:
                result.update(recovery=recovery, revision=digest({'data': data, 'damaged': hashlib.sha256(self.path.read_bytes()).hexdigest()}))
            return result

    def write(self, values, revision):
        if not isinstance(values, dict) or set(values) - self.KEYS:
            raise ValueError('不支持的桌面设置项')
        for key, value in values.items():
            if key in ('onboarding_complete', 'compact_mode', 'log_follow') and type(value) is not bool:
                raise ValueError('设置必须为布尔值：' + key)
            if key == 'theme' and value != 'light':
                raise ValueError('首版主题为 light')
            if key == 'last_section' and value not in ('project', 'build', 'inputs', 'assembly', 'check', 'run', 'history', 'settings', 'help'):
                raise ValueError('无效页面')
            if key == 'log_panel_height' and (type(value) is not int or not 120 <= value <= 600):
                raise ValueError('日志高度必须为 120 到 600')
            if key == 'scan_roots' and (not isinstance(value, list) or len(value) > 16 or any(not isinstance(p, str) or len(p) > 32767 for p in value)):
                raise ValueError('扫描目录列表无效')
        with self.lock:
            current = self.read()
            if not revision or revision != current['revision']:
                raise ValueError('桌面设置已变化，请刷新后重试')
            data = {'schema_version': 1, 'values': dict(current['values'], **values)}
            if current.get('recovery'):
                stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + secrets.token_hex(4)
                atomic_write(str(self.path) + '.corrupt-' + stamp, self.path.read_bytes())
            elif self.path.exists():
                atomic_json(self.path.with_suffix('.json.bak'), {k: v for k, v in current.items() if k != 'revision'})
            atomic_json(self.path, data)
            return self.read()


class LegacyImporter:
    def __init__(self, store, backup_dir, runs_dir=None):
        self.store = store
        self.backup_dir = Path(backup_dir)
        self.runs_dir = Path(runs_dir or self.store.env_file.parent.parent / 'runs')

    @staticmethod
    def _absolute(value):
        return isinstance(value, str) and (Path(value).is_absolute() or ntpath.isabs(value) and bool(ntpath.splitdrive(value)[0]))

    @staticmethod
    def _normal_path(value):
        windows = bool(ntpath.splitdrive(value)[0])
        normal = (ntpath.normpath(value) if windows else posixpath.normpath(value)).replace('\\', '/')
        return normal, windows

    @staticmethod
    def _available(value, directory=False):
        try:
            return Path(value).is_dir() if directory else Path(value).exists()
        except OSError:
            # Historical shares can be offline or access-restricted. Mapping
            # remains lexical; inability to inspect a path means unavailable.
            return False

    @classmethod
    def _mappings(cls, values):
        if values is None:
            return []
        if not isinstance(values, list) or len(values) > 16:
            raise ValueError('路径替换必须为最多 16 组目录前缀')
        mappings, seen = [], set()
        for value in values:
            if not isinstance(value, dict) or set(value) != {'from', 'to'}:
                raise ValueError('路径替换必须包含 from 和 to 目录')
            pair = {}
            for key in ('from', 'to'):
                text = value[key]
                if (not cls._absolute(text) or len(text) > 32767
                        or any(ord(char) < 32 or char in '<>"|?*' for char in text)
                        or text.startswith(('\\\\?\\', '\\\\.\\'))
                        or '..' in text.replace('\\', '/').split('/')):
                    raise ValueError('路径替换必须使用不含控制字符的完整目录')
                normal, windows = cls._normal_path(text)
                try:
                    not_directory = Path(normal).exists() and not Path(normal).is_dir()
                except OSError:
                    not_directory = False
                if not_directory:
                    raise ValueError('路径替换前缀必须为目录')
                pair[key] = normal
            normal, windows = cls._normal_path(pair['from'])
            identity = normal.casefold() if windows or os.name == 'nt' else normal
            if identity in seen:
                raise ValueError('路径替换的来源前缀不能重复')
            seen.add(identity)
            mappings.append(pair)
        return mappings

    @classmethod
    def _relocate(cls, source, mappings):
        updated, changes = deepcopy(source), []
        ordered = sorted(mappings, key=lambda pair:len(pair['from']), reverse=True)

        def replace(value, field):
            if not cls._absolute(value):
                return value
            normal, windows = cls._normal_path(value)
            comparable = normal.casefold() if windows or os.name == 'nt' else normal
            for pair in ordered:
                prefix = pair['from']
                comparison = prefix.casefold() if windows or os.name == 'nt' else prefix
                if comparable != comparison and not comparable.startswith(comparison.rstrip('/') + '/'):
                    continue
                suffix = normal[len(prefix):].lstrip('/')
                result = pair['to'].rstrip('/') + '/' + suffix if suffix else pair['to']
                if result != value:
                    changes.append(dict(field=field, old=value, new=result, exists=cls._available(result)))
                return result
            return value

        profiles, identities = {}, {}
        profile_fields = {'CONFIG_SRC','DLL_ROOT','DLL_SRC','MAP_ROOT','GONGCAN_ROOT','OUT_ROOT','DT_ROOT','BUILD_SUBDIR','INSTALL_SUBDIR'}
        for key, profile in updated['profiles'].items():
            field = 'profiles.' + key
            profile['path'] = replace(profile['path'], field + '.path')
            new_key = project_id(profile['path'])
            if new_key in profiles:
                raise ValueError('路径替换后项目目录冲突，请调整映射')
            for name in sorted(profile_fields & profile['values'].keys()):
                profile['values'][name] = replace(profile['values'][name], field + '.values.' + name)
            bindings = {}
            for binding_key, binding in profile.get('bindings', {}).items():
                binding_field = field + '.bindings.' + binding_key
                new_binding_key = binding_key
                try:
                    parts = json.loads(binding_key)
                except (ValueError, TypeError):
                    parts = None
                if (isinstance(parts, list) and len(parts) == 3 and all(isinstance(part, str) for part in parts)
                        and cls._absolute(parts[0])):
                    relocated = [replace(part, binding_field + '.key[' + str(index) + ']') for index, part in enumerate(parts)]
                    if relocated != parts:
                        relocated[0] = os.path.normcase(os.path.realpath(relocated[0]))
                        new_binding_key = json.dumps(relocated, ensure_ascii=False)
                if new_binding_key in bindings:
                    raise ValueError('路径替换后任务绑定冲突，请调整映射')
                if isinstance(binding, dict):
                    for name in ('engineering_file', 'schema_source', 'polygon_file'):
                        if name in binding:
                            binding[name] = replace(binding[name], binding_field + '.' + name)
                    overrides = binding.get('path_overrides')
                    if isinstance(overrides, dict):
                        for name in sorted(LOCAL_PATHS & overrides.keys()):
                            overrides[name] = replace(overrides[name], binding_field + '.path_overrides.' + name)
                bindings[new_binding_key] = binding
            profile['bindings'] = bindings
            profiles[new_key], identities[key] = profile, new_key
        updated['profiles'] = profiles
        if updated['active']:
            updated['active'] = identities[updated['active']]
        for name in sorted(MACHINE_FIELDS):
            if name in updated['machine']['values']:
                updated['machine']['values'][name] = replace(updated['machine']['values'][name], 'machine.values.' + name)
        return updated, changes

    def _source(self, source_root):
        if not isinstance(source_root, str) or not Path(source_root).is_absolute():
            raise ValueError('请选择旧工作流的完整目录')
        root = Path(source_root).resolve()
        if root == self.store.env_file.parent.parent.resolve():
            raise ValueError('不能将当前用户数据目录导入自身')
        candidates = [root / 'env/project-profiles.json', root / 'env/local-win.env', root / 'env/projects.json']
        if not any(path.is_file() for path in candidates):
            raise ValueError('未找到旧项目配置，请选择包含 env 的工作流目录')
        if any(path.is_file() and path.stat().st_size > 4194304 for path in candidates):
            raise ValueError('旧配置文件过大，拒绝导入')
        source = ProjectStore(root / 'env/local-win.env')
        data = source._read(persist=False)
        registry = root / 'env/projects.json'
        if registry.is_file():
            listed = json.loads(registry.read_text(encoding='utf-8-sig')).get('projects')
            if not isinstance(listed, list) or len(listed) > 1000:
                raise ValueError('旧项目列表格式不兼容')
            for path in listed:
                if not isinstance(path, str) or not Path(path).is_absolute():
                    raise ValueError('旧项目列表包含无效目录')
                data['profiles'].setdefault(project_id(path), ProjectStore._blank(path))
        self._validate(data)
        return root, data

    @staticmethod
    def _validate(data):
        if data.get('version') != 1 or not isinstance(data.get('profiles'), dict) or len(data['profiles']) > 1000:
            raise ValueError('项目配置版本或格式不兼容')
        for key, profile in data['profiles'].items():
            if (not isinstance(profile, dict) or not isinstance(profile.get('path'), str)
                or not Path(profile['path']).is_absolute() or project_id(profile['path']) != key):
                raise ValueError('项目标识和目录不一致')
            if not isinstance(profile.get('values'), dict) or set(profile['values']) - set(PROJECT_FIELDS):
                raise ValueError('项目配置字段不兼容')
            if not isinstance(profile.get('bindings', {}), dict):
                raise ValueError('任务绑定格式不兼容')
            if type(profile.get('revision')) is not int or profile['revision'] < 1:
                raise ValueError('项目修订无效')
            for value in profile['values'].values():
                if not isinstance(value, str) or any(c in value for c in '\0\r\n"'):
                    raise ValueError('项目配置必须是合法单行文本')
        machine = data.get('machine', {})
        values = machine.get('values', {})
        if not isinstance(values, dict) or set(values) - set(MACHINE_FIELDS) or type(machine.get('revision', 1)) is not int:
            raise ValueError('本机配置字段不兼容')
        if any(not isinstance(v, str) or any(c in v for c in '\0\r\n"') for v in values.values()):
            raise ValueError('本机工具路径无效')
        if data.get('active') and data['active'] not in data['profiles']:
            raise ValueError('当前项目标识不存在')

    def _history(self, root, include_history):
        if type(include_history) is not bool:
            raise ValueError('历史导入选项必须为布尔值')
        if not include_history:
            return []
        base = root / '.lishuttle-runs'
        if not base.is_dir():
            return []
        records, file_count, byte_count = [], 0, 0
        for directory in sorted(base.iterdir()):
            if len(records) >= 1000:
                raise ValueError('旧历史超过 1000 项，请分批整理后导入')
            if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
                continue
            metadata = directory / 'session.json'
            if not metadata.is_file() or metadata.stat().st_size > 4194304:
                continue
            try:
                record = json.loads(metadata.read_text(encoding='utf-8'))
            except (ValueError, UnicodeError):
                continue
            if (not isinstance(record, dict) or record.get('version') != 1 or str(record.get('sid')) != directory.name or
                record.get('status') in ('running', 'finalizing') or
                not isinstance(record.get('context'), dict) or not isinstance(record.get('archive'), dict)):
                continue
            files = []
            for walk_root, directories, names in os.walk(directory, followlinks=False):
                parent = Path(walk_root)
                directories[:] = [name for name in directories if not (parent / name).is_symlink() and not (parent / name).is_junction()]
                for name in sorted(names):
                    path = parent / name
                    if path.is_symlink() or path.is_junction():
                        raise ValueError('历史包含链接文件，请移除链接后导入')
                    if not path.resolve().is_relative_to(directory.resolve()):
                        raise ValueError('历史文件超出所选目录')
                    size = path.stat().st_size
                    file_count += 1
                    byte_count += size
                    if file_count > 5000 or byte_count > 536870912:
                        raise ValueError('本次历史超过 5000 文件或 512 MiB，请缩小旧历史目录后导入')
                    checksum = hashlib.sha256()
                    with path.open('rb') as stream:
                        for chunk in iter(lambda: stream.read(1048576), b''):
                            checksum.update(chunk)
                    files.append(dict(relative=path.relative_to(directory).as_posix(), size=size, sha256=checksum.hexdigest()))
            records.append(dict(directory=str(directory), record=record, files=files))
        return records

    def _copy_history(self, root, histories):
        if not histories:
            return []
        existing = set()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        for metadata in self.runs_dir.glob('*/session.json'):
            try:
                data = json.loads(metadata.read_text(encoding='utf-8'))
                old = data.get('imported_from', {}) if isinstance(data, dict) else {}
                if not isinstance(old, dict):
                    continue
                existing.add((old.get('source_root'), str(old.get('sid'))))
            except (ValueError, OSError):
                continue
        created = []
        try:
            for entry in histories:
                record = deepcopy(entry['record'])
                identity = (root.as_posix(), str(record['sid']))
                if identity in existing:
                    continue
                while True:
                    sid = secrets.randbits(51) or 1
                    destination = self.runs_dir / str(sid)
                    if not destination.exists():
                        break
                temporary = Path(tempfile.mkdtemp(prefix='.import-', dir=self.runs_dir))
                try:
                    source = Path(entry['directory'])
                    for item in entry['files']:
                        original = source / item['relative']
                        copied = temporary / item['relative']
                        copied.parent.mkdir(parents=True, exist_ok=True)
                        checksum = hashlib.sha256()
                        with original.open('rb') as stream, copied.open('xb') as output:
                            for chunk in iter(lambda: stream.read(1048576), b''):
                                checksum.update(chunk)
                                output.write(chunk)
                        if checksum.hexdigest() != item['sha256']:
                            raise ValueError('历史文件已变化，请重新预览后导入')
                    old_archive = Path(record['archive'].get('dir') or entry['directory'])
                    checked = {os.path.normcase(str(Path(item['relative']))) for item in entry['files']}
                    archive_issues, snapshot_issues = [], []
                    def remap(value, snapshot=False):
                        if isinstance(value, list):
                            return [remap(item, snapshot) for item in value]
                        if isinstance(value, dict):
                            mapped = {key: remap(item, snapshot) for key, item in value.items()}
                            if isinstance(value.get('archive_path'), str):
                                try:
                                    relative = Path(value['archive_path']).relative_to(old_archive)
                                    if '..' in relative.parts or os.path.normcase(str(relative)) not in checked:
                                        raise ValueError()
                                    mapped['archive_path'] = str(destination / relative)
                                except ValueError:
                                    mapped['archive_path'] = ''
                                    mapped['status'] = 'unavailable'
                                    message = '历史归档文件缺失或未安全复制，导入时不可用'
                                    mapped['error'] = message
                                    (snapshot_issues if snapshot else archive_issues).append(
                                        {'path': value['archive_path'], 'message': message})
                            return mapped
                        return value
                    # Availability is migration metadata, independent of the
                    # frozen computation result and original runtime context.
                    record['archive'] = remap(record['archive'])
                    if 'snapshots' in record:
                        record['snapshots'] = remap(record['snapshots'], snapshot=True)
                    if archive_issues:
                        record['archive']['issues'] = list(record['archive'].get('issues') or []) + archive_issues
                    if snapshot_issues:
                        record['snapshot_issues'] = list(record.get('snapshot_issues') or []) + snapshot_issues
                    if archive_issues or snapshot_issues:
                        record['archive']['status'] = 'incomplete'
                    record['imported_from'] = dict(source_root=root.as_posix(), sid=record['sid'])
                    record['sid'] = sid
                    record['archive']['dir'] = str(destination)
                    record['owner_pid'] = 0
                    atomic_json(temporary / 'session.json', record)
                    temporary.rename(destination)
                    created.append(destination)
                finally:
                    if temporary.exists():
                        shutil.rmtree(temporary)
            return created
        except BaseException:
            for directory in created:
                shutil.rmtree(directory)
            raise

    def _preview(self, root, source, target, history, mappings, path_changes, original):
        conflicts = [dict(path=p['path'], reason='已有同一项目，保留桌面版配置') for key, p in source['profiles'].items() if key in target['profiles']]
        projects = [dict(path=p['path'], exists=self._available(p['path'], directory=True)) for p in source['profiles'].values()]
        warnings = ['仅替换预览列出的配置路径；不可用路径需要重新定位。真实任务、XML 内容、地图与结果不会复制或改写。']
        return dict(source_root=root.as_posix(), token=digest({'root': str(root), 'original': original, 'source': source,
                'target': target, 'history': history, 'path_mappings': mappings, 'path_changes': path_changes}),
            projects=projects, conflicts=conflicts, warnings=warnings,
            path_mappings=mappings, path_changes=path_changes,
            summary=dict(projects=len(projects), bindings=sum(len(p.get('bindings', {})) for p in source['profiles'].values()),
                machine_fields=sum(bool(value) for value in source['machine']['values'].values()),
                history_sessions=len(history), history_bytes=sum(item['size'] for entry in history for item in entry['files'])))

    def preview(self, source_root, include_history=False, path_mappings=None):
        root, original = self._source(source_root)
        mappings = self._mappings(path_mappings)
        source, path_changes = self._relocate(original, mappings)
        history = self._history(root, include_history)
        with self.store._locked():
            target = self.store._read(persist=False)
            return self._preview(root, source, target, history, mappings, path_changes, original)

    def apply(self, source_root, token, include_history=False, path_mappings=None):
        root, original = self._source(source_root)
        mappings = self._mappings(path_mappings)
        source, path_changes = self._relocate(original, mappings)
        history = self._history(root, include_history)
        with self.store._locked():
            target = self.store._read(persist=False)
            preview = self._preview(root, source, target, history, mappings, path_changes, original)
            if not token or not secrets.compare_digest(str(token), preview['token']):
                raise ValueError('配置已变化，请重新预览导入范围')
            updated = deepcopy(target)
            count = bindings = 0
            for key, profile in source['profiles'].items():
                if key in updated['profiles']:
                    continue
                updated['profiles'][key] = deepcopy(profile)
                # Saved runtime selections are content/build-specific; require explicit reactivation.
                updated['profiles'][key].pop('runtime_selections', None)
                count += 1
                bindings += len(profile.get('bindings', {}))
            machine_values = updated['machine']['values']
            fill = {key: value for key, value in source['machine']['values'].items() if value and not machine_values.get(key)}
            ProjectStore._update_machine(updated, fill)
            if not updated['active']:
                updated['active'] = source.get('active') or next(iter(updated['profiles']), '')
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + secrets.token_hex(4)
            backup = self.backup_dir / ('import-' + stamp + '.json')
            atomic_json(backup, target)
            created = self._copy_history(root, history)
            try:
                atomic_json(self.store.file, updated)
            except BaseException:
                for directory in created:
                    shutil.rmtree(directory)
                raise
            return dict(ok=True, imported=dict(projects=count, bindings=bindings, history=len(created)), backup=backup.as_posix(), warnings=preview['warnings'])
