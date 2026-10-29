"""Local build choices, artifact discovery and actionable setup requirements."""
from pathlib import Path

from project_detection import detect_project_config

BUILD_FIELDS = ('PRESET', 'BUILD_SUBDIR', 'INSTALL_SUBDIR', 'EXE_NAME', 'DLL_SRC')


def preset_mode(preset):
    kind = str(preset.get('build_type', '')).lower()
    if kind == 'debug':
        return 'debug'
    if kind in ('release', 'relwithdebinfo', 'minsizerel'):
        return 'release'
    return ''


def executable_name(env):
    if not env.get('PROJECT_DIR') or not env.get('BUILD_SUBDIR'):
        return ''
    binary = Path(env['PROJECT_DIR']) / env['BUILD_SUBDIR'] / 'Bin'
    names = sorted(path.name for path in binary.glob('*.exe') if path.is_file())
    expected = env.get('EXE_NAME', '')
    if expected and expected in names:
        return expected
    if 'lishuttle.exe' in names:
        return 'lishuttle.exe'
    return names[0] if len(names) == 1 else ''


def describe_build(env):
    result = dict(presets={}, modes={'debug': [], 'release': []}, selected=env.get('PRESET', ''),
                  selected_mode='', directory_exists=False, built=False, executable='', build_dir='', warnings=[])
    if not env.get('PROJECT_DIR') or not Path(env['PROJECT_DIR']).is_dir():
        return result
    detection = detect_project_config(env, machine={})
    result['warnings'] = detection['warnings']
    for name, preset in detection['presets'].items():
        mode = preset_mode(preset)
        if not mode:
            continue
        entry = dict(preset, mode=mode, directory_exists=(Path(env['PROJECT_DIR']) / preset['values']['BUILD_SUBDIR']).is_dir())
        result['presets'][name] = entry
        result['modes'][mode].append(name)
    for mode in result['modes']:
        result['modes'][mode].sort(key=lambda name: (not result['presets'][name]['built'], name))
    selected = result['presets'].get(result['selected'])
    if selected:
        result['selected_mode'] = selected['mode']
    subdir = env.get('BUILD_SUBDIR', '')
    if subdir:
        path = Path(env['PROJECT_DIR']) / subdir
        result['build_dir'] = path.as_posix()
        result['directory_exists'] = path.is_dir()
        result['executable'] = executable_name(env)
        result['built'] = bool(result['executable'])
    return result


def prepare_build(env, preset):
    status = describe_build(env)
    entry = status['presets'].get(preset)
    if not entry:
        raise ValueError('未找到可用于 Debug/Release 的 Windows x64 Ninja 预设，请检查项目 CMakePresets.json')
    values = {key: entry['values'].get(key, '') for key in BUILD_FIELDS}
    defaults = {item['values'].get('DLL_SRC') for item in status['presets'].values()}
    if env.get('DLL_SRC') and env['DLL_SRC'] not in defaults:
        values['DLL_SRC'] = env['DLL_SRC']
    if not env.get('CONFIG_SRC'):
        values['CONFIG_SRC'] = detect_project_config(env, machine={})['values'].get('CONFIG_SRC', '')
    return values


def sync_executable(store, env=None):
    env = dict(env) if env is not None else store.load()
    name = executable_name(env)
    if name and name != env.get('EXE_NAME'):
        env = store.save({'EXE_NAME': name}, env['PROJECT_PROFILE_REVISION'], env['PROJECT_DIR'])
    return env


def required_issues(env, operation='render'):
    issues = []

    def add(key, message, section='project', target=None):
        issues.append(dict(key=key, message=message, section=section, target=target or 'config-' + key))

    if not env.get('PROJECT_DIR') or not Path(env['PROJECT_DIR']).is_dir():
        add('PROJECT_DIR', '请先添加并选择本地引擎项目', 'project-add', 'project-path')
        return issues
    if operation == 'build':
        for key in ('CMAKE', 'NINJA', 'VCVARS'):
            if not env.get(key) or not Path(env[key]).is_file():
                add(key, f'本机工具 {key} 未配置或文件不存在，请自动检测或填写正确路径', 'machine')
        if not env.get('PRESET') or not env.get('BUILD_SUBDIR'):
            add('PRESET', '请选择 Debug 或 Release 对应的构建预设', 'build', 'build-mode')
        return issues
    if not env.get('BUILD_SUBDIR'):
        add('BUILD_SUBDIR', '请先选择 Debug/Release 并编译，构建目录由平台生成', 'build', 'build-mode')
    elif not executable_name(env):
        add('EXE_NAME', '当前构建配置尚无可识别的程序，请先编译；多个程序时请检查 CMake 主程序目标', 'build', 'btn-build')
    for key, label in (('CONFIG_SRC','基础配置源目录'), ('DLL_SRC','动态库源目录'),
                       ('MAP_ROOT','地图根目录'), ('GONGCAN_ROOT','工参任务根目录'), ('OUT_ROOT','结果根目录')):
        value = env.get(key, '')
        if not value:
            add(key, f'请填写并保存{label}（{key}）')
        elif key != 'OUT_ROOT' and not (Path(env['PROJECT_DIR']) / value).is_dir():
            add(key, f'{label}不存在，请检查路径（{key}）')
        elif key == 'OUT_ROOT' and Path(value).exists() and not Path(value).is_dir():
            add(key, '结果根目录不能指向文件，请选择文件夹')
    return issues
