"""Read-only discovery of this project's presets/resources and installed Windows tools."""
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import subprocess

from project_config import FIELDS


def slash(value):
    return str(value).replace('\\', '/')


def matching_toolchain(toolchains, root):
    """Windows installation paths are case insensitive and accept either slash."""
    canonical = ntpath.normcase(ntpath.normpath(str(root)))
    return next((values for path, values in toolchains.items()
                 if ntpath.normcase(ntpath.normpath(str(path))) == canonical), {})


def machine_tools():
    """Inspect registered VS installations and PATH, never execute project code."""
    result = {key: [] for key in ('VS_ROOT', 'CMAKE', 'NINJA', 'VCVARS')}
    result['toolchains'] = {}
    roots = []
    installer = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    if installer.is_file():
        try:
            run = subprocess.run([str(installer), '-all', '-products', '*', '-requires',
                'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-format', 'json', '-utf8'],
                capture_output=True, encoding='utf-8-sig', timeout=6, check=False)
            if run.returncode == 0:
                roots = [Path(item['installationPath']) for item in json.loads(run.stdout)
                         if item.get('installationPath') and item.get('isComplete', True)]
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    # File probes are useful when vswhere is unavailable; only existing tools qualify.
    for program_files in (os.environ.get('ProgramFiles', 'C:/Program Files'),
                          os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')):
        base = Path(program_files) / 'Microsoft Visual Studio'
        if base.is_dir():
            roots.extend(path for path in base.glob('*/*') if path.is_dir())
    for root in dict.fromkeys(roots):
        vcvars = root / 'VC/Auxiliary/Build/vcvars64.bat'
        if not vcvars.is_file():
            continue
        values = dict(VS_ROOT=slash(root), VCVARS=slash(vcvars))
        cmake = root / 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe'
        ninja = root / 'Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe'
        for key, path in (('CMAKE', cmake), ('NINJA', ninja)):
            if path.is_file():
                values[key] = slash(path)
        result['toolchains'][slash(root)] = values
        for key, value in values.items():
            if value not in result[key]:
                result[key].append(value)
    for key, names in (('CMAKE', ('cmake.exe', 'cmake')), ('NINJA', ('ninja.exe', 'ninja'))):
        for name in names:
            value = shutil.which(name)
            if value and Path(value).is_file() and slash(value) not in result[key]:
                result[key].append(slash(value))
    return result


def expand(value, project, name='', environment=None):
    if not isinstance(value, str):
        raise ValueError('路径不是文本')
    macros = dict(sourceDir=slash(project), sourceParentDir=slash(project.parent),
                  sourceDirName=project.name, presetName=name, hostSystemName='Windows')
    env = dict(os.environ, **{k: str(v) for k, v in (environment or {}).items() if v is not None})
    value = re.sub(r'\$penv\{([^}]+)\}', lambda m: os.environ.get(m[1], m[0]), value)
    value = re.sub(r'\$env\{([^}]+)\}', lambda m: env.get(m[1], m[0]), value)
    value = re.sub(r'\$\{([^}]+)\}', lambda m: macros.get(m[1], m[0]), value)
    if re.search(r'\$(?:\w+)?\{', value):
        raise ValueError('包含无法确定的宏：' + value)
    return value


def condition_matches(condition, project, name):
    if condition is None:
        return True
    if isinstance(condition, bool):
        return condition
    if not isinstance(condition, dict):
        raise ValueError('预设 condition 必须是对象或布尔值')
    kind = condition.get('type')
    if kind == 'const':
        return bool(condition.get('value'))
    if kind in ('allOf', 'anyOf'):
        results = [condition_matches(c, project, name) for c in condition.get('conditions', [])]
        return all(results) if kind == 'allOf' else any(results)
    if kind == 'not':
        return not condition_matches(condition.get('condition'), project, name)
    lhs = expand(condition.get('lhs', condition.get('string', '')), project, name)
    if kind in ('equals', 'notEquals'):
        equal = lhs == expand(condition.get('rhs', ''), project, name)
        return equal if kind == 'equals' else not equal
    if kind in ('inList', 'notInList'):
        found = lhs in [expand(v, project, name) for v in condition.get('list', [])]
        return found if kind == 'inList' else not found
    raise ValueError('无法确认当前平台条件：' + str(kind))


def read_presets(project, warnings):
    raw, sources, visited, resolved = {}, {}, set(), {}

    def read(path):
        path = path.resolve()
        if path in visited:
            return
        if len(visited) >= 32:
            raise ValueError('预设 include 文件过多')
        visited.add(path)
        if not path.is_file():
            raise ValueError('预设文件不存在：' + slash(path))
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError('预设文件顶层必须是对象：' + slash(path))
        if not isinstance(data.get('include', []), list) or not isinstance(data.get('configurePresets', []), list):
            raise ValueError('预设 include / configurePresets 必须是数组：' + slash(path))
        for include in data.get('include', []):
            read(path.parent / expand(include, project))
        for item in data.get('configurePresets', []):
            if not isinstance(item, dict) or not isinstance(item.get('name'), str):
                warnings.append('跳过缺少有效名称的预设：' + slash(path))
                continue
            name = item['name']
            if name in raw:
                warnings.append('重复预设名称：' + name)
                continue
            raw[name], sources[name] = item, slash(path)

    for filename in ('CMakePresets.json', 'CMakeUserPresets.json'):
        if (project / filename).is_file():
            try:
                read(project / filename)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                warnings.append(str(exc))

    def resolve(name, stack=()):
        if name in resolved:
            return resolved[name]
        if name in stack or name not in raw:
            raise ValueError('预设继承循环或父预设不存在：' + name)
        own = raw[name]
        parents = own.get('inherits', [])
        parents = [parents] if isinstance(parents, str) else parents
        merged = {}
        for parent in reversed(parents):
            inherited = resolve(parent, stack + (name,))
            for key, value in inherited.items():
                merged[key] = dict(merged.get(key, {}), **value) if key in ('cacheVariables', 'environment') else value
        for key, value in own.items():
            merged[key] = dict(merged.get(key, {}), **value) if key in ('cacheVariables', 'environment') else value
        merged['hidden'] = own.get('hidden', False)
        resolved[name] = merged
        return merged

    def relative(value, name, environment):
        path = Path(expand(value, project, name, environment))
        if not path.is_absolute():
            path = project / path
        try:
            return slash(path.resolve().relative_to(project.resolve()))
        except ValueError:
            raise ValueError('构建或安装目录在项目外，当前脚本不兼容')

    presets = {}
    for name in raw:
        try:
            item = resolve(name)
            if item['hidden'] or not condition_matches(item.get('condition'), project, name):
                continue
            if item.get('generator') != 'Ninja':
                raise ValueError('当前本地脚本仅自动配置 Ninja 预设')
            architecture = item.get('architecture', 'x64')
            architecture = architecture.get('value', 'x64') if isinstance(architecture, dict) else architecture
            if architecture.lower() not in ('x64', 'amd64'):
                raise ValueError('当前脚本使用 x64 MSVC 环境')
            values = {'PRESET': name}
            for key, field in (('binaryDir', 'BUILD_SUBDIR'), ('installDir', 'INSTALL_SUBDIR')):
                if item.get(key):
                    values[field] = relative(item[key], name, item.get('environment'))
            if not values.get('BUILD_SUBDIR'):
                raise ValueError('缺少可确定的 binaryDir')
            build_type = item.get('cacheVariables', {}).get('CMAKE_BUILD_TYPE', '')
            if isinstance(build_type, dict):
                build_type = build_type.get('value', '')
            presets[name] = dict(values=values, source=sources[name], label=item.get('displayName', name),
                                 build_type=build_type)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
            warnings.append(f'{name}：{exc}')
    return presets


def detect_project_config(env, machine=None):
    project = Path(env.get('PROJECT_DIR', ''))
    if not env.get('PROJECT_DIR') or not project.is_dir():
        raise ValueError('请先选择存在的本地项目')
    warnings = []
    fields = {key: dict(candidates=[], source='未检测到，请按实际目录填写', status='missing', value='') for key in FIELDS}

    def add(key, value, source, label=None):
        if not value:
            return
        value = slash(value)
        if not any(c['value'] == value for c in fields[key]['candidates']):
            fields[key]['candidates'].append(dict(value=value, source=source, label=label or value))

    presets = read_presets(project, warnings)
    executable = ''
    cmake = project / 'LiShuttle/CMakeLists.txt'
    if cmake.is_file():
        text = re.sub(r'#[^\n]*', '', cmake.read_text(encoding='utf-8-sig', errors='replace'))
        match = re.search(r'\bproject\s*\(\s*["\']?([\w.-]+)', text, re.I)
        targets = re.findall(r'\badd_executable\s*\(\s*["\']?([\w.${}-]+)', text, re.I)
        targets = [match[1] if target == '${PROJECT_NAME}' and match else target for target in targets]
        targets = [target for target in targets if re.fullmatch(r'[\w.-]+', target)]
        if len(set(targets)) == 1:
            executable = targets[0] + '.exe'
    for name, preset in presets.items():
        values = preset['values']
        binary = project / values['BUILD_SUBDIR'] / 'Bin'
        found = sorted(p.name for p in binary.glob('*.exe')) if binary.is_dir() else []
        if executable and (not found or executable in found):
            values['EXE_NAME'] = executable
        elif 'lishuttle.exe' in found:
            values['EXE_NAME'] = 'lishuttle.exe'
        elif len(found) == 1:
            values['EXE_NAME'] = found[0]
        preset['built'] = bool(values.get('EXE_NAME') and (binary / values['EXE_NAME']).is_file())
        mode = 'Debug' if preset['build_type'] == 'Debug' else 'Release' if preset['build_type'] in ('Release', 'RelWithDebInfo', 'MinSizeRel') else ''
        if mode and (project / 'ThirdPart/Dll' / mode).is_dir():
            values['DLL_SRC'] = 'ThirdPart/Dll/' + mode
        for key, value in values.items():
            label = value if key == 'EXE_NAME' else f'{preset["label"]} · {value}'
            add(key, value, preset['source'], label + (' · 已编译' if key == 'PRESET' and preset['built'] else ''))
    for relative in ('ThirdPart/Config', 'Config'):
        if (project / relative / 'runtimelibrary/runtimeschema.xml').is_file():
            add('CONFIG_SRC', relative, slash(project / relative))
    for relative in ('ThirdPart/Dll/Release', 'ThirdPart/Dll/Debug'):
        if (project / relative).is_dir():
            add('DLL_SRC', relative, slash(project / relative))
    directories = dict(MAP_ROOT=('map', 'maps'), GONGCAN_ROOT=('gongcan', 'tasks'),
                       OUT_ROOT=('pathloss', 'outputs'), DT_ROOT=('drivetest',))
    for key, names in directories.items():
        for base in (project, project.parent):
            for name in names:
                path = base / name
                if path.is_dir():
                    if key == 'MAP_ROOT' and not any((child / 'heights/index.txt').is_file() or
                         (child / 'building.das').is_file() for child in path.iterdir() if child.is_dir()):
                        continue
                    add(key, path, '项目内已有目录' if base == project else '项目同级已有目录（共享候选）')
    machine = machine_tools() if machine is None else machine
    toolchains = machine.get('toolchains', {})
    for key in ('VS_ROOT', 'CMAKE', 'NINJA', 'VCVARS'):
        for value in machine.get(key, []):
            if Path(value).is_dir() if key == 'VS_ROOT' else Path(value).is_file():
                add(key, value, '本机 VS 安装及 PATH 文件检测')
    preferred = env.get('PRESET') or next(iter(sorted(presets, key=lambda name:
        (not presets[name]['built'], presets[name]['build_type'] == 'Debug', name))), '')
    linked = presets.get(preferred, {}).get('values', {})
    preferred_vs = env.get('VS_ROOT') or next(iter(machine.get('VS_ROOT', [])), '')
    linked_tools = matching_toolchain(toolchains, preferred_vs)
    values = {}
    for key in FIELDS:
        field = fields[key]
        saved = env.get(key, '')
        choices = field['candidates']
        if saved:
            value, status, source = saved, 'saved', '当前项目已保存配置'
        elif key in linked_tools and any(c['value'] == linked_tools[key] for c in choices):
            value, status, source = linked_tools[key], 'detected', '所选 VS 安装内的已验证工具'
        elif key in linked:
            value, status, source = linked[key], 'detected', presets[preferred]['source']
        elif key == 'PRESET' and preferred in presets:
            value, status, source = preferred, 'detected', presets[preferred]['source']
        elif key == 'DLL_SRC' and preferred in presets and key not in linked:
            value, status = '', 'choice' if choices else 'missing'
            source = '当前预设对应的 DLL 目录不存在，请确认兼容目录后手动选择'
        elif choices and (len(choices) == 1 or key in ('VS_ROOT', 'CMAKE', 'NINJA', 'VCVARS')):
            value, status, source = choices[0]['value'], 'detected', choices[0]['source']
        else:
            value, status = '', 'choice' if choices else 'missing'
            source = '检测到多个候选，请下拉选择' if choices else field['source']
        values[key] = value
        field.update(value=value, status=status, source=source)
    return dict(values=values, fields=fields, presets=presets, toolchains=toolchains, warnings=warnings)
