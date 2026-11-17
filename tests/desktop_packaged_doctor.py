"""Run the shipped doctor with no system Python and a disposable fake project."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def check(resources, output):
    resources = resources.resolve()
    workflow = resources / 'workflow'
    interpreter = resources / 'python/python.exe'
    # This check must exercise the package's import layout and code, not the
    # source tree or an available system interpreter.
    assert Path(sys.executable).resolve() == interpreter.resolve(), sys.executable
    import project_config
    assert Path(project_config.__file__).resolve().is_relative_to(workflow)
    evidence = dict(interpreter=str(interpreter), systemPythonInPath=False,
                    checks=[], realEngineExecuted=False)
    with tempfile.TemporaryDirectory(prefix='桌面 体检 fixture ') as temporary:
        root = Path(temporary)
        project = root / '引擎 项目'
        files = ('CMakeLists.txt', 'CMakePresets.json', 'ThirdPart/Lib/uplancommon.lib',
                 'ThirdPart/Lib/lishuttlectl.lib', 'ThirdPart/Dll/Debug/uplancommon.dll',
                 'ThirdPart/Dll/Debug/lishuttlectl.dll', 'ThirdPart/Config/log4cpp.conf',
                 'ThirdPart/Config/lishuttlesign', 'build/debug/Bin/fixture.exe',
                 'build/debug/Bin/runtimelibrary/runtimeschema.xml')
        for name in files:
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'fixture only, never executed')
        for name in ('ThirdPart/Config/runtimelibrary', 'ThirdPart/Config/models',
                     'ThirdPart/Config/antennas', 'maps', 'tasks', 'outputs'):
            (project / name).mkdir(parents=True, exist_ok=True)
        values = dict(PROJECT_DIR=project.as_posix(), PRESET='debug',
                      BUILD_SUBDIR='build/debug', INSTALL_SUBDIR='install/debug',
                      EXE_NAME='fixture.exe', CONFIG_SRC='ThirdPart/Config',
                      DLL_ROOT='ThirdPart/Dll', DLL_SRC='ThirdPart/Dll/Debug',
                      MAP_ROOT=(project / 'maps').as_posix(),
                      GONGCAN_ROOT=(project / 'tasks').as_posix(),
                      OUT_ROOT=(project / 'outputs').as_posix())
        for key, filename in (('CMAKE', 'cmake.exe'), ('NINJA', 'ninja.exe'),
                              ('VCVARS', 'vcvars64.bat')):
            target = root / '工具 链' / filename
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(b'fixture only, never executed')
            values[key] = target.as_posix()
        snapshot = Path(project_config.write_snapshot(values, root / 'snapshots'))
        system32 = Path(os.environ['SystemRoot']) / 'System32'
        env = {key: value for key, value in os.environ.items()
               if key not in ('PYTHONHOME', 'PYTHONPATH', 'LISHUTTLE_CONFIG_SNAPSHOT',
                              'LISHUTTLE_PYTHON')}
        env.update(PATH=str(system32), LISHUTTLE_PYTHON=str(interpreter),
                   LISHUTTLE_CONFIG_SNAPSHOT=str(snapshot),
                   TEMP=str(root), TMP=str(root), PYTHONDONTWRITEBYTECODE='1')
        completed = subprocess.run([str(system32 / 'cmd.exe'), '/d', '/v:off', '/c',
                                    str(workflow / 'scripts/doctor_local.bat')],
                                   cwd=workflow, env=env, capture_output=True, timeout=30)
        console = (completed.stdout + completed.stderr).decode('gbk', errors='replace')
        assert completed.returncode == 0, console
        assert 'Python validation failed' not in console, console
        assert '找不到 python' not in console.lower(), console
        assert '[错误]' not in console and '[缺失]' not in console, console
        assert '关键项全部就位' in console, console
        assert 'ThirdPart\\Dll' in console and 'vcvars64.bat' in console, console
        evidence['checks'] = ['Packaged modules and interpreter used',
                              'Real shipped doctor and profile loader completed',
                              'Chinese and spaced fixture paths supported',
                              'All fixture tool, DLL, configuration and data checks passed']
    output.mkdir(parents=True, exist_ok=True)
    (output / 'packaged-doctor.log').write_text(console, encoding='utf-8')
    (output / 'packaged-doctor.json').write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    check(args.resources, args.output)
