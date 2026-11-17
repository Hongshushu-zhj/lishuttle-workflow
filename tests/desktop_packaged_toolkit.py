"""Compile a disposable C++ project through the real desktop control/API path."""
import argparse
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request


def check(workflow, interpreter, output, vs_root):
    workflow, interpreter = workflow.resolve(), interpreter.resolve()
    tools = dict(VS_ROOT=vs_root.as_posix(),
                 CMAKE=(vs_root / 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe').as_posix(),
                 NINJA=(vs_root / 'Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe').as_posix(),
                 VCVARS=(vs_root / 'VC/Auxiliary/Build/vcvars64.bat').as_posix())
    for key in ('CMAKE', 'NINJA', 'VCVARS'):
        assert Path(tools[key]).is_file(), (key, tools[key])
    output.mkdir(parents=True, exist_ok=True)
    evidence = dict(interpreter=str(interpreter), workflow=str(workflow), toolchain=tools,
                    checks=[], realEngineExecuted=False, sessions=[])
    with tempfile.TemporaryDirectory(prefix='桌面 编译 fixture ') as temporary:
        root = Path(temporary)
        project = root / '引擎 项目'
        def write(name, contents):
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding='utf-8')
        write('CMakeLists.txt', 'cmake_minimum_required(VERSION 3.20)\n'
              'project(desktop_fixture LANGUAGES CXX)\n'
              'set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/Bin")\n'
              'add_subdirectory(LiShuttle)\n')
        write('LiShuttle/CMakeLists.txt', 'add_executable(lishuttle main.cpp)\n')
        write('LiShuttle/main.cpp', '#include <cstdio>\nint main() { puts("DESKTOP_FIXTURE_OK"); return 0; }\n')
        write('SwanUtility/incl/LiShuttleTypes.h', '// Temporary fixture; no engine implementation.\n')
        presets = [dict(name='x64-' + mode.lower(), generator='Ninja',
                        binaryDir='${sourceDir}/out/build/${presetName}',
                        cacheVariables=dict(CMAKE_BUILD_TYPE=mode,
                                            CMAKE_CXX_COMPILER='cl.exe',
                                            CMAKE_INSTALL_PREFIX='${sourceDir}/out/install/${presetName}'))
                   for mode in ('Debug', 'Release')]
        write('CMakePresets.json', json.dumps(dict(version=3, configurePresets=presets)))
        for name in ('ThirdPart/Lib/uplancommon.lib', 'ThirdPart/Lib/lishuttlectl.lib',
                     'ThirdPart/Dll/Debug/uplancommon.dll', 'ThirdPart/Dll/Debug/lishuttlectl.dll',
                     'ThirdPart/Dll/Release/uplancommon.dll', 'ThirdPart/Dll/Release/lishuttlectl.dll',
                     'ThirdPart/Config/log4cpp.conf', 'ThirdPart/Config/lishuttlesign'):
            write(name, 'Fixture only; never loaded.\n')
        for name in ('ThirdPart/Config/runtimelibrary', 'ThirdPart/Config/models',
                     'ThirdPart/Config/antennas', 'maps', 'tasks', 'outputs'):
            (project / name).mkdir(parents=True, exist_ok=True)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith('LISHUTTLE_') and key not in ('PYTHONPATH', 'PYTHONHOME')}
        env.update(PATH=str(Path(os.environ['SystemRoot']) / 'System32'),
                   PYTHONDONTWRITEBYTECODE='1', TEMP=str(root), TMP=str(root))
        proc = subprocess.Popen([str(interpreter), '-B', '-u',
                                 str(workflow / 'platform/backend/desktop_supervisor.py')],
                                cwd=workflow, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding='utf-8')
        messages, errors = queue.Queue(), []
        def read_messages():
            for line in proc.stdout:
                messages.put(json.loads(line))
        def read_errors():
            errors.extend(proc.stderr)
        threading.Thread(target=read_messages, daemon=True).start()
        threading.Thread(target=read_errors, daemon=True).start()
        def control(payload):
            proc.stdin.write(json.dumps(payload) + '\n')
            proc.stdin.flush()
        secret = secrets.token_hex(32)
        control(dict(data_dir=str(root / 'data'), resource_root=str(workflow),
                     static_dir=str(workflow / 'desktop-ui/dist'),
                     session_secret=secret, cookie_name='fixture_session'))
        try:
            ready = messages.get(timeout=20)
            assert ready['type'] == 'ready', ready
            origin = ready['origin']
            def request(endpoint, payload=None):
                data = None if payload is None else json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(origin + '/api/' + endpoint, data=data,
                    headers={'Content-Type': 'application/json', 'Origin': origin,
                             'Cookie': 'fixture_session=' + secret})
                with urllib.request.urlopen(req, timeout=25) as response:
                    result = json.load(response)
                assert not result.get('error'), result
                return result
            state = request('select_project', dict(path=project.as_posix()))
            def scoped(values):
                return dict(values, _project=state['project'], _revision=state['profile_revision'],
                            _machine_revision=state['machine_revision'])
            state = request('save_machine_config', scoped(dict(values=tools)))
            values = dict(CONFIG_SRC='ThirdPart/Config', DLL_ROOT='ThirdPart/Dll',
                          MAP_ROOT=(project / 'maps').as_posix(),
                          GONGCAN_ROOT=(project / 'tasks').as_posix(),
                          OUT_ROOT=(project / 'outputs').as_posix())
            state = request('save_project_config', scoped(dict(values=values)))
            def task(step, preset=None):
                nonlocal state
                state = request('state')
                body = dict(step=step)
                if preset:
                    body.update(preset=preset, values=dict(DLL_ROOT='ThirdPart/Dll'))
                started = request('toolkit', scoped(body))
                sid = started['sid']
                deadline = time.monotonic() + 120
                live_output = False
                while time.monotonic() < deadline:
                    result = request('output?sid=' + str(sid) + '&limit=5000')
                    live_output |= bool(result.get('lines')) and result.get('status') != 'done'
                    if result.get('status') == 'done':
                        break
                    time.sleep(.1)
                else:
                    request('stop', dict(sid=sid))
                    raise AssertionError('Desktop task did not finish: ' + str(result))
                console = '\n'.join(result['lines'])
                name = step + ('-' + preset if preset else '')
                (output / (name + '.log')).write_text(console, encoding='utf-8')
                assert result['exit'] == 0, console
                assert 'Python validation failed' not in console, console
                assert '找不到 python' not in console, console
                evidence['sessions'].append(dict(step=step, preset=preset, sid=sid,
                    exit=result['exit'], liveOutput=live_output, status=result['status']))
                assert not request('runtime_state')['busy'], result
                return console
            for mode in ('release', 'debug'):
                preset = 'x64-' + mode
                console = task('build', preset)
                assert 'Building CXX object' in console and 'Linking CXX executable' in console, console
                exe = project / 'out/build' / preset / 'Bin/lishuttle.exe'
                assert exe.is_file(), console
                completed = subprocess.run([str(exe)], stdin=subprocess.DEVNULL,
                    capture_output=True, timeout=5)
                assert completed.returncode == 0 and b'DESKTOP_FIXTURE_OK' in completed.stdout
                evidence['checks'].append('Real CMake/Ninja/MSVC build and fixture execution: ' + preset)
                state = request('state')
                assert state['project_config']['DLL_SRC'].endswith('/' + mode.capitalize()), state['project_config']
                doctor = task('doctor', preset)
                assert '关键项全部就位' in doctor and '[缺失]' not in doctor and '[错误]' not in doctor, doctor
                evidence['checks'].append('Doctor through desktop API with matching DLL directory: ' + preset)
            control(dict(type='activity', request_id='toolkit-completed'))
            activity = messages.get(timeout=10)
            assert activity['type'] == 'activity' and not activity['busy'], activity
            control(dict(type='shutdown', request_id='fixture-close'))
            stopped = messages.get(timeout=15)
            assert stopped == dict(type='shutdown', request_id='fixture-close', status='stopped'), stopped
            assert proc.wait(timeout=15) == 0
            evidence['checks'].extend(['Lifecycle pipe stayed open throughout all tasks',
                'Task logs visible before completion; runtime guard released',
                'Supervisor relayed activity and graceful shutdown after compilation',
                'Only disposable project and isolated user data used; PATH has no system Python'])
            assert all(session['liveOutput'] for session in evidence['sessions'] if session['step'] == 'build'), evidence
        finally:
            if proc.poll() is None:
                proc.stdin.close()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                if not pipe.closed:
                    pipe.close()
            (output / 'toolkit-service.log').write_text(''.join(errors), encoding='utf-8')
    (output / 'packaged-toolkit.json').write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--vs-root', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    workflow = args.resources / 'workflow' if args.resources else root
    interpreter = args.resources / 'python/python.exe' if args.resources else Path(sys.executable)
    check(workflow, interpreter, args.output, args.vs_root)
