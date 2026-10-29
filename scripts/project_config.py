"""Single local configuration source for the web application and command line."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('PRESET', 'BUILD_SUBDIR', 'INSTALL_SUBDIR', 'EXE_NAME', 'VS_ROOT',
          'CMAKE', 'NINJA', 'VCVARS', 'CONFIG_SRC', 'DLL_SRC', 'MAP_ROOT',
          'OUT_ROOT', 'DT_ROOT', 'GONGCAN_ROOT')
MACHINE_FIELDS = ('VS_ROOT', 'CMAKE', 'NINJA', 'VCVARS')
PROJECT_FIELDS = tuple(key for key in FIELDS if key not in MACHINE_FIELDS)
IDENTITY = ('PROJECT_DIR', 'PROJECT_PROFILE_ID', 'PROJECT_PROFILE_REVISION')
LOCK = threading.RLock()


def validate_operation(env, operation):
    required = {'doctor': ['PROJECT_DIR'],
                'build': ['PROJECT_DIR', 'PRESET', 'BUILD_SUBDIR', 'CMAKE', 'NINJA', 'VCVARS'],
                'stage': ['PROJECT_DIR', 'BUILD_SUBDIR', 'EXE_NAME', 'CONFIG_SRC', 'DLL_SRC'],
                'run': ['PROJECT_DIR', 'BUILD_SUBDIR', 'EXE_NAME']}
    if operation not in required:
        raise ValueError('未知项目工具')
    missing = [key for key in required[operation] if not env.get(key)]
    if missing:
        raise ValueError('当前项目配置未完成，请先填写：' + '、'.join(missing))


def project_id(path):
    canonical = os.path.normcase(os.path.realpath(os.path.expanduser(str(path))))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:20]


def read_legacy(path):
    values = {}
    if Path(path).is_file():
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"\'')
    return values


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ProjectStore:
    def __init__(self, env_file=None, store_file=None):
        self.env_file = Path(env_file or ROOT / 'env/local-win.env')
        self.file = Path(store_file or self.env_file.with_name('project-profiles.json'))

    @contextmanager
    def _locked(self):
        # Serialize CLI and web read-modify-write operations across processes.
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with LOCK, open(str(self.file) + '.lock', 'a+b') as lock:
            if lock.tell() == 0:
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                lock.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _read(self):
        legacy = {}
        if self.file.is_file():
            data = json.loads(self.file.read_text(encoding='utf-8'))
            if data.get('version') != 1 or not isinstance(data.get('profiles'), dict):
                raise ValueError('项目档案格式不支持，请检查 project-profiles.json')
        else:
            legacy = read_legacy(self.env_file)
            data = {'version': 1, 'active': '', 'profiles': {}}
            if legacy.get('PROJECT_DIR'):
                path = legacy['PROJECT_DIR']
                key = project_id(path)
                data['active'] = key
                data['profiles'][key] = self._blank(path)
                data['profiles'][key]['values'].update({k: legacy[k] for k in FIELDS if k in legacy})
            backup = Path(str(self.env_file) + '.profiles.bak')
            if self.env_file.is_file() and not backup.exists():
                shutil.copy2(self.env_file, backup)
        if 'machine' not in data:
            # Use the active profile only; never combine conflicting old toolchains.
            backup = Path(str(self.file) + '.machine.bak')
            if self.file.is_file() and not backup.exists():
                shutil.copy2(self.file, backup)
            active = data['profiles'].get(data['active'], {}).get('values', legacy)
            data['machine'] = {'revision': 1, 'values': {key: active.get(key, '') for key in MACHINE_FIELDS}}
            for profile in data['profiles'].values():
                for key in MACHINE_FIELDS:
                    profile['values'].pop(key, None)
            atomic_json(self.file, data)
        retired = [profile for profile in data['profiles'].values() if 'CASE_ROOT' in profile['values']]
        if retired:
            backup = Path(str(self.file) + '.retired-fields.bak')
            if not backup.exists():
                shutil.copy2(self.file, backup)
            for profile in retired:
                profile['values'].pop('CASE_ROOT')
                profile['revision'] += 1
            atomic_json(self.file, data)
        return data

    @staticmethod
    def _blank(path):
        return {'path': os.path.realpath(os.path.expanduser(str(path))).replace('\\', '/'),
                'revision': 1, 'values': {key: '' for key in PROJECT_FIELDS}, 'bindings': {}}

    @staticmethod
    def _env(key, profile, data):
        return dict(profile['values'], **data['machine']['values'],
                    MACHINE_CONFIG_REVISION=str(data['machine'].get('revision', 1)), PROJECT_DIR=profile['path'],
                    PROJECT_PROFILE_ID=key, PROJECT_PROFILE_REVISION=str(profile['revision']))

    def load(self, project=None, allow_empty=False):
        with self._locked():
            data = self._read()
            key = project_id(project) if project else data['active']
            if allow_empty and not project and not key:
                return dict(dict.fromkeys(FIELDS + IDENTITY, ''), **data['machine']['values'],
                            MACHINE_CONFIG_REVISION=str(data['machine'].get('revision', 1)))
            if key not in data['profiles']:
                raise ValueError('尚未配置本地项目，请在网页添加项目并保存配置')
            return self._env(key, data['profiles'][key], data)

    def paths(self):
        with self._locked():
            return [p['path'] for p in self._read()['profiles'].values()]

    def select(self, path):
        with self._locked():
            data = self._read()
            key = project_id(path)
            if key not in data['profiles']:
                data['profiles'][key] = self._blank(path)
            data['active'] = key
            atomic_json(self.file, data)
            return self._env(key, data['profiles'][key], data)

    def save(self, values, revision=None, project=None):
        if not isinstance(values, dict) or set(values) - set(FIELDS):
            raise ValueError('不支持的项目配置字段；项目目录只能通过项目选择切换')
        if any(not isinstance(v, str) or any(c in v for c in '\r\n\0"') for v in values.values()):
            raise ValueError('配置必须是单行文本，不允许双引号、换行或空字符')
        with self._locked():
            data = self._read()
            key = project_id(project) if project else data['active']
            if key not in data['profiles']:
                raise ValueError('请先添加并选择本地项目')
            profile = data['profiles'][key]
            if revision is not None and str(revision) != str(profile['revision']):
                raise ValueError('项目配置已变化，请刷新后重试')
            machine_changed = self._update_machine(data, {k:v for k,v in values.items() if k in MACHINE_FIELDS})
            profile['values'].update({k:v for k,v in values.items() if k in PROJECT_FIELDS})
            if not machine_changed:
                profile['revision'] += 1
            atomic_json(self.file, data)
            return self._env(key, profile, data)

    @staticmethod
    def _update_machine(data, values):
        machine = data['machine']['values']
        if not any(machine.get(key, '') != value for key,value in values.items()):
            return False
        machine.update(values)
        data['machine']['revision'] = data['machine'].get('revision', 1) + 1
        for profile in data['profiles'].values():
            profile['revision'] += 1
        return True

    def save_machine(self, values, revision=None):
        if not isinstance(values, dict) or set(values) - set(MACHINE_FIELDS):
            raise ValueError('本机工具链仅支持 VS_ROOT、CMAKE、NINJA、VCVARS')
        if any(not isinstance(v, str) or any(c in v for c in '\r\n\0"') for v in values.values()):
            raise ValueError('配置必须是单行文本，不允许双引号、换行或空字符')
        with self._locked():
            data = self._read()
            if revision is not None and str(revision) != str(data['machine'].get('revision', 1)):
                raise ValueError('本机工具配置已变化，请刷新后重试')
            if self._update_machine(data, values):
                atomic_json(self.file, data)
            return dict(data['machine']['values'])

    def setup_machine(self, machine=None, force=False):
        """Persist only verified missing tools; explicit/saved paths always win."""
        with self._locked():
            current = dict(self._read()['machine']['values'])
        if machine is None and not force and all(current.get(key) for key in MACHINE_FIELDS):
            return {'values': current, 'candidates': {}, 'filled': []}
        if machine is None:
            from project_detection import machine_tools
            machine = machine_tools()
        from project_detection import matching_toolchain
        candidates = {key: [str(path).replace('\\','/') for path in machine.get(key, [])
                           if (Path(path).is_dir() if key == 'VS_ROOT' else Path(path).is_file())]
                      for key in MACHINE_FIELDS}
        with self._locked():
            data = self._read()
            current = data['machine']['values']
            preferred = current.get('VS_ROOT') or next(iter(candidates['VS_ROOT']), '')
            linked = matching_toolchain(machine.get('toolchains', {}), preferred)
            fill = {}
            for key in MACHINE_FIELDS:
                if current.get(key):
                    continue
                proposed = linked.get(key) or next(iter(candidates[key]), '')
                if proposed and proposed in candidates[key]:
                    fill[key] = proposed
            if self._update_machine(data, fill):
                atomic_json(self.file, data)
            return {'values': dict(current), 'candidates': dict(candidates, toolchains=machine.get('toolchains', {})),
                    'filled': list(fill)}

    def binding(self, key, value=None, project=None):
        with self._locked():
            data = self._read()
            profile = data['profiles'][project_id(project) if project else data['active']]
            if value is not None:
                profile['bindings'][key] = value
                atomic_json(self.file, data)
            return profile['bindings'].get(key)


def write_snapshot(env, directory=None):
    directory = Path(directory or ROOT / 'env/snapshots')
    digest = hashlib.sha256(json.dumps(env, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    path = directory / (digest + '.json')
    if not path.is_file():
        atomic_json(path, env)
    return str(path)


def load_local(env_file=None, project=None, snapshot=None):
    snapshot = snapshot or os.environ.get('LISHUTTLE_CONFIG_SNAPSHOT')
    if snapshot:
        env = json.loads(Path(snapshot).read_text(encoding='utf-8'))
        if not isinstance(env, dict) or not env.get('PROJECT_DIR') or any(not isinstance(v, str) for v in env.values()):
            raise ValueError('无效的项目配置快照')
        if project and project_id(project) != project_id(env['PROJECT_DIR']):
            raise ValueError('指定项目与配置快照不一致')
        return env
    return ProjectStore(env_file).load(project)


def main():
    parser = argparse.ArgumentParser(description='本地项目配置快照')
    parser.add_argument('--project', help='已登记的本地项目目录')
    parser.add_argument('--snapshot', action='store_true')
    parser.add_argument('--setup-machine', action='store_true', help='自动搜索并保存本机缺少的工具链配置')
    parser.add_argument('--show-machine', action='store_true', help='显示本机全局工具链，无需先登记项目')
    parser.add_argument('--set-machine', action='append', metavar='KEY=VALUE', help='设置一个本机工具路径，可重复使用')
    args = parser.parse_args()
    if args.setup_machine or args.show_machine or args.set_machine:
        if args.snapshot or args.project:
            parser.error('本机工具配置不能与 --project / --snapshot 同时使用')
        store = ProjectStore()
        if args.set_machine:
            values = {}
            for entry in args.set_machine:
                key, separator, value = entry.partition('=')
                if not separator:
                    parser.error('--set-machine 需要 KEY=VALUE')
                values[key] = value.replace('\\','/')
            store.save_machine(values)
        current = store.load(allow_empty=True)
        result = store.setup_machine(force=True) if args.setup_machine else {'values': {
            key: current[key] for key in MACHINE_FIELDS}}
        result['config_file'] = str(store.file).replace('\\', '/')
        result['missing'] = [key for key in MACHINE_FIELDS if not result['values'].get(key)]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    env = load_local(project=args.project)
    if args.snapshot:
        print(write_snapshot(env))
    else:
        print(json.dumps(env, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f'[错误] {exc}')
