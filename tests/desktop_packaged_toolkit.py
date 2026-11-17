"""Exercise an isolated fixture through the real desktop supervisor and HTTP API.

The compiled C++ fixture prints its arguments; it does not implement LiShuttle
or produce business results. A zero process exit must never become business
success. Both a source checkout and packaged --resources are supported.
"""
import argparse
import csv
import io
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
import urllib.error
from urllib.parse import urlencode
import xml.etree.ElementTree as ET


def fixture_inputs(write):
    """Small, valid outdoor inputs matching the reviewed preflight contract."""
    header = ['Cell ID', 'Cell Name', 'Site ID', 'Site Name', 'Longitude', 'Latitude',
        'Layer', 'Physical Cell ID', 'Height (m)', 'Azimuth (°)', 'Mechanical Downtilt (°)',
        'Additional Electrical Downtilt (°)', 'SenseTilt', 'Antenna', 'SenseAntenna',
        'Number of Transmission Antennas', 'Number of Reception Antennas', 'Max Power (dBm)',
        'EPRE per antenna port', 'Bandwidth', 'Channel Number', 'Main Propagation Model',
        'Main Resolution', 'Traffic Load (DL) (%)', 'Traffic Load (UL) (%)',
        'Main Calculation Radius (m)', 'Transmission losses (dB)', 'Reception losses (dB)',
        'Noise Figure (dB)', 'Miscellaneous Losses', 'Feeder Equipment', 'Feeder Length(m)',
        'TMA Equipment', 'Transmitter Equipment', 'Active', 'Transmitter Type', 'Cell Type',
        'Channel Allocation Status', 'Frequency Band', 'SenseActive', 'SensePower', 'CityCode']
    row = ['c1', 'cell', 'site1', 'site', '119.000000', '26.000000', '1', '1', '20',
        '90', '0', '0', '0', 'omni', 'omni', '4', '4', '40', '14', '100', '504990',
        'LiShuttleModel_1', '5', '15', '15', '800', '2', '2', '4', '0', '', '0', '',
        '0', '1', '1', 'NR', '0', '20', '1', '14', '350900']
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerows([header, header, row])
    write('tasks/室外 任务/cells.csv', stream.getvalue())
    write('tasks/室外 任务/cells.txt', '119,26\n119.01,26\n119.01,26.01\n')
    cell_format = dict(CellId='A', SiteId='C', Longitude='E', Latitude='F', PCI='H',
        AntennaHeight='I', Azimuth='J', Tilt='K', ElecTilt='L', SenseTilt='M', Antenna='N',
        SenseAntenna='O', TxNumber='P', RxNumber='Q', MaxPower='R', EPRE='S', BandWidth='T',
        ChannelNumber='U', PropagationModel='V', Resolution='W', DLTrafficLoad='X',
        ULTrafficLoad='Y', CalcRadius='Z', TxLoss='AA', RxLoss='AB', NoiseFigure='AC',
        MiscellaneousLoss='AD', FeederEquipment='AE', FeederLength='AF', TMAEquipment='AG',
        Active='AI', CellType='AK', SenseActive='AN', SensePower='AO', SenseNoiseFigure='AC')
    write('ThirdPart/Config/cellformat.xml', '<TableFormat><HeaderLines>2</HeaderLines>' +
          ''.join(f'<{key}>{value}</{key}>' for key, value in cell_format.items()) + '</TableFormat>')
    write('ThirdPart/Config/runtimelibrary/scenesettings.xml', '<Cluttersettings>'
          '<SceneInformation><SceneID>0</SceneID><OtoIModel>0</OtoIModel><PenetrationLoss>20</PenetrationLoss>'
          '<LinearLoss>0.2</LinearLoss><FloorHeight>3</FloorHeight><FloorLoss>10</FloorLoss>'
          '</SceneInformation></Cluttersettings>')
    write('ThirdPart/Config/models/LiShuttleModel.xml', '<PropagationCategory name="LiShuttleModel">'
          '<Model ID="1"><ModelName>Sub6G</ModelName><K0>28</K0><Knear>22</Knear><Kfar>40</Kfar>'
          '<Kh>-9</Kh><K0_nlos>28</K0_nlos><Knear_nlos>22</Knear_nlos><Kfar_nlos>40</Kfar_nlos>'
          '<Kh_nlos>-9</Kh_nlos></Model></PropagationCategory>')
    write('ThirdPart/Config/antennas/antenna.xml', '<AntennaSettings><AntennaEntity name="omni">'
          '<MaxGain>11</MaxGain><Broadcast_Beam_FILE>omni.txt</Broadcast_Beam_FILE>'
          '</AntennaEntity></AntennaSettings>')
    write('ThirdPart/Config/antennas/omni.txt', 'HORIZONTAL 360\n' +
          ''.join(f'{i} 0\n' for i in range(360)) + 'VERTICAL 360\n' +
          ''.join(f'{i} 0\n' for i in range(360)))
    write('maps/测试 地图/heights/projection.txt', 'WGS-84\n50\nUTM\n0 117 500000 0\n')
    for kind in ('heights', 'clutter', 'buildings', 'buildvector'):
        write(f'maps/测试 地图/{kind}/index.txt', 'tile.dat 0 10 0 10 5\n')
        write(f'maps/测试 地图/{kind}/tile.dat', b'\x01' * 8)
    write('maps/测试 地图/clutter/menu.txt', '1 urban\n')
    write('ThirdPart/Config/config/cluttermatchsettings.xml', '<ClutterMatchSettings/>')
    sample = ('<?xml version="1.0" encoding="utf-8"?>\n<RuntimeSchema name="sample">\n'
        '<!-- disposable acceptance fixture; no production business inputs -->\n'
        '<EngineeringFilePath>sample.csv</EngineeringFilePath><PathlossDirectory>outputs</PathlossDirectory>'
        '<ProjectionFilePath>heights/projection.txt</ProjectionFilePath>'
        '<HeightIndexPath>heights/index.txt</HeightIndexPath>'
        '<ClutterIndexPath>clutter/index.txt</ClutterIndexPath><ClutterMenuPath>clutter/menu.txt</ClutterMenuPath>'
        '<BuildingIndexPath>buildings/index.txt</BuildingIndexPath><BulidVectorIndexPath>buildvector/index.txt</BulidVectorIndexPath>'
        '<ClutterMatchPath/><PolygonFilePath/><SceneSettingsPath/>'
        '<MapFormat>PLANET</MapFormat><SpatialCalcMode>ground</SpatialCalcMode><UsingBuildingPolygon>false</UsingBuildingPolygon>'
        '<MaxCalcHeight>10</MaxCalcHeight><DefaultFloorHeight>3</DefaultFloorHeight>'
        '<DefaultCalcResolution>5</DefaultCalcResolution><CpuLoad>80</CpuLoad></RuntimeSchema>\n')
    write('ThirdPart/Config/runtimelibrary/runtimeschema.xml', sample)
    write('tasks/室外 任务/原始 运行配置.xml', sample)


def cleanup_service(owner, proc, evidence, output, errors):
    """Attempt every cleanup action and retain evidence even if a pipe breaks."""
    issues = evidence.setdefault('cleanup_errors', [])

    def attempt(label, action):
        try:
            return action()
        except Exception as exc:
            issues.append(dict(step=label, type=type(exc).__name__, message=str(exc)))
            evidence['status'] = 'failed'
            evidence.setdefault('failure', dict(type='CleanupFailed', message='Desktop fixture cleanup was incomplete'))

    def persist():
        attempt('write_service_log', lambda: (output / 'toolkit-service.log').write_text(
            ''.join(errors), encoding='utf-8'))
        attempt('write_evidence', lambda: (output / 'packaged-toolkit.json').write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'))

    original_status = evidence.get('status', 'failed')
    if original_status == 'passed':
        evidence['status'] = 'cleaning_up'
    persist()  # Never leave an old successful record if cleanup then wedges.
    if evidence['status'] == 'cleaning_up':
        evidence['status'] = original_status
    try:
        if proc is not None and attempt('poll', proc.poll) is None:
            attempt('close_stdin', proc.stdin.close)
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired as exc:
                issues.append(dict(step='graceful_wait', type=type(exc).__name__, message=str(exc)))
                evidence['status'] = 'failed'
                if owner is not None:
                    attempt('terminate_owner', owner.terminate)
                attempt('wait_after_terminate', lambda: proc.wait(timeout=5))
            except Exception as exc:
                issues.append(dict(step='wait', type=type(exc).__name__, message=str(exc)))
                evidence['status'] = 'failed'
    finally:
        try:
            if owner is not None:
                attempt('close_owner_job', owner.close)
        finally:
            if proc is not None:
                for name in ('stdin', 'stdout', 'stderr'):
                    def close_pipe(name=name):
                        pipe = getattr(proc, name, None)
                        if pipe is not None and not pipe.closed:
                            pipe.close()
                    attempt('close_' + name, close_pipe)
            persist()
    return issues


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
                    checks=[], realEngineExecuted=False, sessions=[], requests=[], status='running')
    with tempfile.TemporaryDirectory(prefix='桌面 编译 fixture ') as temporary:
        root = Path(temporary)
        project = root / '引擎 项目'
        def write(name, contents):
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(contents, bytes):
                target.write_bytes(contents)
            else:
                target.write_text(contents, encoding='utf-8')
        write('CMakeLists.txt', 'cmake_minimum_required(VERSION 3.20)\n'
              'project(desktop_fixture LANGUAGES CXX)\n'
              'set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/Bin")\n'
              'add_subdirectory(LiShuttle)\n')
        write('LiShuttle/CMakeLists.txt', 'add_executable(lishuttle main.cpp)\n')
        write('LiShuttle/main.cpp', '#include <cstdio>\n#include <thread>\n#include <chrono>\n'
              'int main(int argc, char** argv) { puts("DESKTOP_FIXTURE_OK"); '
              'for (int i=1; i<argc; ++i) printf("FIXTURE_ARG_%d=%s\\n", i, argv[i]); '
              'fflush(stdout); std::this_thread::sleep_for(std::chrono::milliseconds(900)); '
              'puts("DESKTOP_FIXTURE_FINISHED_NO_BUSINESS_PRODUCTS"); fflush(stdout); return 0; }\n')
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
        fixture_inputs(write)
        source_inputs = {path: path.read_bytes() for folder in ('tasks', 'maps', 'ThirdPart/Config')
                         for path in (project / folder).rglob('*') if path.is_file()}
        env = {key: value for key, value in os.environ.items()
               if not key.startswith('LISHUTTLE_') and key not in ('PYTHONPATH', 'PYTHONHOME')}
        env.update(PATH=str(Path(os.environ['SystemRoot']) / 'System32'),
                   PYTHONDONTWRITEBYTECODE='1', TEMP=str(root), TMP=str(root))
        for key, relative in dict(USERPROFILE='用户 目录', HOME='用户 目录',
                APPDATA='用户 目录/AppData/Roaming', LOCALAPPDATA='用户 目录/AppData/Local').items():
            directory = root / relative
            directory.mkdir(parents=True, exist_ok=True)
            env[key] = str(directory)
        # A separate owner Job ensures a wedged HTTP handler cannot orphan the
        # supervisor/entry/renderer tree, even before graceful shutdown is fixed.
        sys.path.insert(0, str(workflow / 'platform/backend'))
        from desktop_supervisor import ServiceProcess
        owner = proc = None
        messages, errors = queue.Queue(), []
        def read_messages():
            for line in proc.stdout:
                messages.put(json.loads(line))
        def read_errors():
            errors.extend(proc.stderr)
        def control(payload):
            proc.stdin.write(json.dumps(payload) + '\n')
            proc.stdin.flush()
        secret = secrets.token_hex(32)
        try:
            owner = ServiceProcess([str(interpreter), '-B', '-u',
                str(workflow / 'platform/backend/desktop_supervisor.py')], str(workflow), env=env)
            proc = owner.proc
            for name in ('stdin', 'stdout', 'stderr'):
                setattr(proc, name, io.TextIOWrapper(getattr(proc, name), encoding='utf-8', newline='\n'))
            threading.Thread(target=read_messages, daemon=True).start()
            threading.Thread(target=read_errors, daemon=True).start()
            control(dict(data_dir=str(root / 'data'), resource_root=str(workflow),
                         static_dir=str(workflow / 'desktop-ui/dist'),
                         session_secret=secret, cookie_name='fixture_session'))
            ready = messages.get(timeout=20)
            assert ready['type'] == 'ready', ready
            origin = ready['origin']
            def request(endpoint, payload=None, timeout=25, expected_status=200, allow_error=False):
                begun = time.monotonic()
                data = None if payload is None else json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(origin + '/api/' + endpoint, data=data,
                    headers={'Content-Type': 'application/json', 'Origin': origin,
                             'Cookie': 'fixture_session=' + secret})
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as response:
                        status, result = response.status, json.load(response)
                except urllib.error.HTTPError as response:
                    status, result = response.code, json.load(response)
                except (TimeoutError, OSError) as exc:
                    evidence['requests'].append(dict(endpoint=endpoint, status='failed',
                        error=type(exc).__name__, seconds=round(time.monotonic() - begun, 3)))
                    raise
                evidence['requests'].append(dict(endpoint=endpoint, status=status,
                    seconds=round(time.monotonic() - begun, 3)))
                assert status == expected_status, result
                assert allow_error or expected_status != 200 or not result.get('error'), result
                return result
            try:
                urllib.request.urlopen(origin + '/api/state', timeout=5)
            except urllib.error.HTTPError as response:
                assert response.code == 401 and json.load(response)['code'] == 'UNAUTHORIZED'
            else:
                raise AssertionError('Unauthenticated API request unexpectedly succeeded')
            evidence['checks'].append('Real HTTP API rejects missing authentication')
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
            selected = next(task for task in state['tasks'] if task['name'] == '室外 任务')
            assert selected['engineering_file'] == selected['engineering_candidates'][0], selected
            assert selected['kind'] == 'outdoor' and selected['schema_candidates'], selected
            assert next(city for city in state['cities'] if city['name'] == '测试 地图')['kind'] == 'outdoor'
            assert all(state['machine_config'][key] == value for key, value in tools.items()), state['machine_config']
            assert all(state['project_config'][key] == value for key, value in values.items()), state['project_config']
            evidence['checks'].append('Project/machine configuration read back and task/map/engineering discovered')
            info = request('desktop_info')
            assert Path(info['data_dir']) == root / 'data', info
            prefs = request('desktop_preferences')
            prefs = request('desktop_preferences', dict(revision=prefs['revision'],
                values=dict(prefs['values'], compact_mode=True)))
            assert request('desktop_preferences')['values']['compact_mode'], prefs
            binding = dict(task=selected, engineering_file=selected['engineering_file'],
                schema_source=selected['schema_candidates'][0]['path'], city='测试 地图',
                sync_engineering=True, polygon_file=selected['txts'][0], path_overrides={})
            saved_binding = request('save_task_binding', scoped(binding))
            loaded_binding = request('task_binding', scoped(binding))
            assert loaded_binding['binding'] == saved_binding['binding'], loaded_binding
            evidence['checks'].append('Task selection binding and desktop preferences persist in isolated data')
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
                    capture_output=True, timeout=5, env=env)
                assert completed.returncode == 0 and b'DESKTOP_FIXTURE_OK' in completed.stdout
                state = request('state')
                render_body = dict(job_name='desktop-fixture', func='pred', task_id='007',
                    city='测试 地图', city_kind='outdoor',
                    task=selected, engineering_file=selected['engineering_file'])
                assembled = request('render', scoped(render_body), timeout=10)
                assert assembled['generated'] and assembled['assembly_status'] == 'applied', assembled
                assert assembled['render_status'] == 'ready' and assembled['render_exit'] == 0, assembled
                (output / ('render-' + preset + '.json')).write_text(
                    json.dumps(assembled, ensure_ascii=False, indent=2), encoding='utf-8')
                binary = exe.parent
                schema_path = binary / 'runtimelibrary/desktop-fixture.xml'
                parsed = ET.parse(schema_path).getroot()
                assert parsed.get('name') == 'desktop-fixture'
                assert Path(parsed.findtext('EngineeringFilePath')) == Path(selected['engineering_file'])
                assert Path(parsed.findtext('PathlossDirectory')) == project / 'outputs'
                original_xml = schema_path.read_bytes()
                original_attempt = assembled['generation_attempt']
                # Repeat assembly must regenerate the selected XML and receipt,
                # preserving user-managed runtime resources and unrelated XML.
                customized = binary / 'antennas/customized.txt'
                customized.write_bytes(b'LOCAL RESOURCE MUST SURVIVE\r\n')
                unrelated = binary / 'runtimelibrary/用户 已存配置.xml'
                unrelated.write_bytes(b'<RuntimeSchema name="keep"><CpuLoad>17</CpuLoad></RuntimeSchema>')
                protected = {customized: customized.read_bytes(), unrelated: unrelated.read_bytes(),
                    binary / 'models/LiShuttleModel.xml': (binary / 'models/LiShuttleModel.xml').read_bytes()}
                repeated = request('render', scoped(render_body), timeout=10)
                assert repeated['generated'] and repeated['assembly_status'] == 'applied', repeated
                assert repeated['generation_attempt'] != original_attempt, repeated
                assert schema_path.read_bytes() == original_xml
                assert all(path.read_bytes() == contents for path, contents in protected.items())
                assert not repeated['base_resources']['copied'], repeated['base_resources']
                control(dict(type='activity', request_id='render-' + preset))
                activity = messages.get(timeout=5)
                assert activity['type'] == 'activity' and activity['request_id'] == 'render-' + preset and not activity['busy'], activity
                evidence['checks'].append('Fresh/repeated XML assembly, distinct receipts and preserved resources: ' + preset)
                evidence['checks'].append('Real CMake/Ninja/MSVC build and fixture execution: ' + preset)
                state = request('state')
                assert state['project_config']['DLL_SRC'].endswith('/' + mode.capitalize()), state['project_config']
                doctor = task('doctor', preset)
                assert '关键项全部就位' in doctor and '[缺失]' not in doctor and '[错误]' not in doctor, doctor
                evidence['checks'].append('Doctor through desktop API with matching DLL directory: ' + preset)
            # Existing task XML takes the same real renderer path after a
            # validated preview; source inputs remain untouched.
            state = request('state')
            reuse_body = dict(binding, job_name='desktop-existing', func='pred', task_id='007',
                city_kind='outdoor', use_existing_schema=True)
            preview = request('preview_render', scoped(reuse_body))
            assert preview['token'] and preview['runtime_name'] == 'desktop-existing', preview
            stale = request('render', scoped(dict(reuse_body, preview_token='invalid')),
                expected_status=409)
            assert stale['code'] == 'PREVIEW_STALE', stale
            reused = request('render', scoped(dict(reuse_body, preview_token=preview['token'])), timeout=10)
            assert reused['schema_ok'] and reused['assembly_status'] == 'applied', reused
            evidence['checks'].append('Existing task XML preview rejects stale token then assembles correctly')
            schema = reused['schema_name']
            query = urlencode(dict(schema=schema, func='pred'))
            params = request('params?' + query)
            assert params['values']['CpuLoad'] == '80' and len(params['revision']) == 64, params
            changed = request('param_write', scoped(dict(schema=schema, tag='CpuLoad',
                value='37', revision=params['revision'])))
            assert changed['ok'] and changed['revision'] != params['revision'], changed
            conflict = request('param_write', scoped(dict(schema=schema, tag='CpuLoad',
                value='99', revision=params['revision'])), expected_status=409)
            assert conflict['code'] == 'FILE_CONFLICT', conflict
            params = request('params?' + query)
            assert params['values']['CpuLoad'] == '37', params['values']
            evidence['checks'].append('Parameter read/save, content revision and stale-write protection')
            execution = dict(schema=schema, func='pred', task_id='007')
            invalid = request('param_write', scoped(dict(schema=schema,
                tag='DefaultCalcResolution', value='0', revision=params['revision'])))
            rejected = request('preflight', scoped(execution))
            assert not rejected['ok'] and 'INVALID_RESOLUTION' in {i['code'] for i in rejected['issues']}, rejected
            refused = request('run', scoped(execution), allow_error=True)
            assert refused['code'] == 'PREFLIGHT_FAILED' and not refused.get('sid'), refused
            assert not request('runtime_state')['busy']
            restored = request('param_write', scoped(dict(schema=schema,
                tag='DefaultCalcResolution', value='5', revision=invalid['revision'])))
            assert restored['ok'], restored
            preflight = request('preflight', scoped(execution))
            (output / 'preflight.json').write_text(json.dumps(preflight, ensure_ascii=False, indent=2), encoding='utf-8')
            assert preflight['ok'], preflight['issues']
            assert preflight['context']['engineering']['rows'] == 1, preflight['context']['engineering']
            listing = request('runtime_configs')
            entry = next(item for item in listing['configs'] if item['schema'] == schema)
            active = request('activate_runtime_config', scoped(dict(execution,
                revision=entry['revision'], scope=listing['scope'])))
            assert active['ok'] and active['job']['schema'] == schema, active
            assert request('runtime_configs')['selected']['schema'] == schema
            evidence['checks'].append('Invalid preflight blocks launch; corrected inputs pass and runtime selection persists')
            started = request('run', scoped(execution))
            sid = started['sid']
            assert Path(started['exe']) == project / 'out/build/x64-debug/Bin/lishuttle.exe', started
            assert started['context']['task_id'] == '007' and started['context']['schema_name'] == schema, started
            assert request('runtime_state')['busy']
            busy = request('render', scoped(render_body), expected_status=409)
            assert busy['code'] == 'RUNTIME_BUSY', busy
            control(dict(type='activity', request_id='fixture-running'))
            activity = messages.get(timeout=5)
            assert activity['busy'] and activity['activity']['sid'] == sid, activity
            deadline, live_output = time.monotonic() + 20, False
            while time.monotonic() < deadline:
                result = request('output?' + urlencode(dict(sid=sid, limit=5000)))
                live_output |= bool(result['lines']) and result['status'] != 'done'
                if result['status'] == 'done':
                    break
                time.sleep(.05)
            else:
                request('stop', dict(sid=sid))
                raise AssertionError('Compiled fixture run did not finish')
            console = '\n'.join(result['lines'])
            (output / 'fixture-run.log').write_text(console, encoding='utf-8')
            assert result['exit'] == 0 and live_output, result
            for marker in ('DESKTOP_FIXTURE_OK', 'FIXTURE_ARG_1=-f', 'FIXTURE_ARG_2=pred',
                    'FIXTURE_ARG_3=-t', 'FIXTURE_ARG_4=007', 'FIXTURE_ARG_5=-c',
                    'FIXTURE_ARG_6=' + schema, 'DESKTOP_FIXTURE_FINISHED_NO_BUSINESS_PRODUCTS'):
                assert marker in console, (marker, console)
            first = request('output?' + urlencode(dict(sid=sid, since=0, limit=1)))
            rest = request('output?' + urlencode(dict(sid=sid, since=first['next_since'], limit=5000)))
            assert first['has_more'] and first['lines'] + rest['lines'] == result['lines']
            assert not rest['has_more'] and rest['next_since'] == result['total']
            assert not request('runtime_state')['busy']
            report = request('results?sid=' + str(sid))
            assert report['associated'] and report['historical'] and report['status'] == 'done', report
            assert report['process']['status'] == 'exited' and report['process']['exit_code'] == 0, report
            assert report['verdict'] in ('failed', 'unconfirmed'), report
            assert report['artifacts']['status'] != 'valid' and report['business']['status'] != 'usable', report
            assert report['issues'] and not report['files'], report
            # Missing fixture products also make artifact archiving incomplete;
            # that is the correct statement, not an acceptance failure to hide.
            assert report['archive']['status'] == 'incomplete' and report['archive']['issues'], report['archive']
            assert all(item['status'] == 'unavailable' for item in report['archive']['files']), report['archive']
            history = request('history?limit=100')
            (output / 'fixture-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            (output / 'fixture-history.json').write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')
            archived = next((item for item in history['runs'] if item['sid'] == sid), None)
            assert archived is not None, dict(message='Current project history omitted the completed fixture run',
                sid=sid, current_project=state['project'], run_project=report['context']['project'], history=history)
            assert archived['result']['verdict'] == report['verdict'], archived
            assert archived['context']['schema_name'] == schema and archived['context']['task_id'] == '007', archived
            assert Path(archived['archive']['dir']).is_relative_to(root / 'data/runs'), archived
            assert request('history?offset=0&limit=1')['total'] == history['total']
            assert request('history?offset=1&limit=1')['runs'][0]['sid'] != request('history?offset=0&limit=1')['runs'][0]['sid']
            export_req = urllib.request.Request(origin + '/api/export_log?sid=' + str(sid),
                headers={'Origin': origin, 'Cookie': 'fixture_session=' + secret})
            with urllib.request.urlopen(export_req, timeout=10) as response:
                exported = response.read().decode('utf-8-sig')
            assert 'DESKTOP_FIXTURE_OK' in exported and 'NO_BUSINESS_PRODUCTS' in exported
            evidence['sessions'].append(dict(step='fixture-run', sid=sid, exit=result['exit'],
                liveOutput=live_output, status=result['status'], verdict=report['verdict'],
                process=report['process'], artifacts=report['artifacts']['status'], business=report['business']['status']))
            evidence['checks'].extend(['Compiled fixture launched through authenticated API with pinned context and expected arguments',
                'Live/paged logs and log export match; busy guard prevents concurrent assembly',
                'History and session-bound results preserve process exit without claiming business success',
                'Missing business products are explicitly failed/unconfirmed and archive is incomplete'])
            control(dict(type='activity', request_id='toolkit-completed'))
            activity = messages.get(timeout=10)
            assert activity['type'] == 'activity' and not activity['busy'], activity
            control(dict(type='shutdown', request_id='fixture-close'))
            stopped = messages.get(timeout=15)
            assert stopped == dict(type='shutdown', request_id='fixture-close', status='stopped'), stopped
            assert proc.wait(timeout=15) == 0
            owner.close()
            # Restart the real service against the same disposable desktop
            # data, so history/config persistence is verified beyond RAM.
            owner = ServiceProcess([str(interpreter), '-B', '-u',
                str(workflow / 'platform/backend/desktop_supervisor.py')], str(workflow), env=env)
            proc = owner.proc
            for name in ('stdin', 'stdout', 'stderr'):
                setattr(proc, name, io.TextIOWrapper(getattr(proc, name), encoding='utf-8', newline='\n'))
            threading.Thread(target=read_messages, daemon=True).start()
            threading.Thread(target=read_errors, daemon=True).start()
            control(dict(data_dir=str(root / 'data'), resource_root=str(workflow),
                static_dir=str(workflow / 'desktop-ui/dist'), session_secret=secret,
                cookie_name='fixture_session'))
            ready = messages.get(timeout=20)
            assert ready['type'] == 'ready', ready
            origin = ready['origin']
            persisted_state = request('state')
            assert persisted_state['project'] == state['project'], persisted_state['project']
            assert request('desktop_preferences')['values']['compact_mode']
            assert request('params?' + query)['values']['CpuLoad'] == '37'
            persisted = request('results?sid=' + str(sid))
            assert persisted['associated'] and persisted['verdict'] == report['verdict'], persisted
            assert request('output?' + urlencode(dict(sid=sid, limit=5000)))['lines'] == result['lines']
            assert any(item['sid'] == sid for item in request('history?limit=100')['runs'])
            assert request('runtime_configs')['selected']['schema'] == schema
            assert not request('runtime_state')['busy']
            control(dict(type='shutdown', request_id='fixture-restart-close'))
            stopped = messages.get(timeout=15)
            assert stopped == dict(type='shutdown', request_id='fixture-restart-close', status='stopped'), stopped
            assert proc.wait(timeout=15) == 0
            evidence['checks'].extend(['Lifecycle pipe stayed open throughout all tasks',
                'Task logs visible before completion; runtime guard released',
                'Supervisor relayed activity and graceful shutdown after compilation and restart',
                'Saved configuration, runtime selection, console and history survive a real service restart',
                'Only disposable project and isolated user data used; PATH has no system Python'])
            assert all(session['liveOutput'] for session in evidence['sessions'] if session['step'] == 'build'), evidence
            assert all(path.read_bytes() == contents for path, contents in source_inputs.items())
            evidence['checks'].append('Original fixture CSV, task XML, maps and configuration sources remain unchanged')
            evidence['status'] = 'passed'
        except BaseException as exc:
            evidence.update(status='failed', failure=dict(type=type(exc).__name__, message=str(exc)))
            raise
        finally:
            cleanup_errors = cleanup_service(owner, proc, evidence, output, errors)
            if cleanup_errors and sys.exc_info()[0] is None:
                raise AssertionError('Desktop fixture cleanup failed: ' + str(cleanup_errors))
    # Keep per-request timings in the evidence file; polling should not flood
    # the terminal with hundreds of otherwise identical output requests.
    print(json.dumps({key: value for key, value in evidence.items() if key != 'requests'},
                     ensure_ascii=False, indent=2))


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
