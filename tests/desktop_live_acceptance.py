"""Real authenticated service/UI acceptance, using disposable projects only."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'platform/backend'), str(ROOT / 'scripts'), str(ROOT / 'tests')]
import core
import desktop_entry
from dll_dependencies import resolve_dll
from project_config import ProjectStore
from run_guard import RuntimeGuard
from run_history import RunHistory
from server import Api, ROUTES
from workflow_browser_check import STATE, browser_path
from playwright.sync_api import sync_playwright, expect


def check():
    output = ROOT / '.superpowers/sdd/2026-11-17/live-browser'
    output.mkdir(parents=True, exist_ok=True)
    evidence = []
    with tempfile.TemporaryDirectory(prefix='桌面验收 ') as temporary:
        directory = Path(temporary)
        project = directory / 'engine'
        (project / 'LiShuttle').mkdir(parents=True)
        (project / 'CMakeLists.txt').write_text('project(fixture)')
        (project / 'LiShuttle/CMakeLists.txt').write_text('add_executable(lishuttle main.cpp)')
        presets = []
        for mode in ('Debug', 'Release'):
            name = mode.lower()
            presets.append(dict(name=name, generator='Ninja', binaryDir='${sourceDir}/build/' + name,
                                cacheVariables={'CMAKE_BUILD_TYPE': mode}))
            binary = project / 'build' / name / 'Bin'
            binary.mkdir(parents=True)
            (binary / 'lishuttle.exe').write_bytes(b'not executable, acceptance fixture')
            dll = project / 'ThirdPart/Dll' / mode
            dll.mkdir(parents=True)
            (dll / 'dependency.dll').write_bytes(mode.encode())
        (project / 'SwanUtility/incl').mkdir(parents=True)
        (project / 'SwanUtility/incl/LiShuttleTypes.h').write_text('// fixture')
        (project / 'CMakePresets.json').write_text(json.dumps(dict(version=3, configurePresets=presets)))
        store = ProjectStore(directory / 'local-win.env')
        store.select(project)
        store.save(dict(PRESET='release', BUILD_SUBDIR='build/release', EXE_NAME='lishuttle.exe', DLL_ROOT='ThirdPart/Dll'))
        guard = RuntimeGuard()
        runner = core.Runner(guard=guard, history=RunHistory(directory / 'runs'))
        with patch.object(core, 'ENV_FILE', str(store.env_file)), patch.object(core, 'RUNTIME', guard), patch.object(core, 'RUNNER', runner):
            def state(_):
                env = store.load(read_only=True)
                value = copy.deepcopy(STATE)
                value.update(project=env['PROJECT_DIR'], projects=[env['PROJECT_DIR']], preset=env['PRESET'],
                             project_config={key: env.get(key, '') for key in core.FIELDS}, machine_config={},
                             profile_id=env['PROJECT_PROFILE_ID'], profile_revision=env['PROJECT_PROFILE_REVISION'],
                             machine_revision=env['MACHINE_CONFIG_REVISION'], build_workflow=core.describe_build(env),
                             runtime=guard.snapshot(), cities=[], tasks=[], functions=[], function_info=[])
                return value
            def start(_):
                code = "import sys,time;sys.stdout.write('中文半行');sys.stdout.flush();time.sleep(1.5);print('完成');print('\\x1b[31mERROR test\\x1b[0m');print('tail',end='',flush=True)"
                sid = runner.start([sys.executable, '-u', '-c', code], temporary, 'fixture',
                                   env={**__import__('os').environ, 'LISHUTTLE_LOG_ENCODING':'utf-8', 'PYTHONIOENCODING':'utf-8'},
                                   context={'project':str(project), 'operation':'doctor'})
                return dict(sid=sid, runtime=guard.snapshot())
            def history(_):
                records = []
                for sid in runner.sessions:
                    record = runner.history.get(sid)
                    records.append(dict(record, verdict=(record.get('result') or {}).get('verdict', 'pending')))
                return dict(runs=records, total=len(records))
            routes = dict(ROUTES)
            routes.update({('GET','state'):state, ('POST','apply_build_target'):Api.apply_build_target,
                ('GET','history'):history, ('POST','toolkit'):start,
                ('GET','runtime_state'):lambda _:guard.snapshot(),
                ('GET','desktop_preferences'):lambda _:dict(values={},revision='one'),
                ('GET','desktop_info'):lambda _:dict(version='0.1.1', python_runtime=dict(path=sys.executable,version=sys.version.split()[0],available=True,bundled=False))})
            server = desktop_entry.create_server(ROOT / 'desktop-ui/dist', 's'*48, 'fixture_session', routes)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch.object(Api, 'state', staticmethod(state)), sync_playwright() as playwright:
                    browser = playwright.chromium.launch(executable_path=browser_path(), headless=True)
                    context = browser.new_context(viewport=dict(width=1366,height=900))
                    context.add_cookies([dict(name='fixture_session',value='s'*48,url=server.origin,httpOnly=True,sameSite='Strict')])
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error:errors.append(str(error)))
                    page.goto(server.origin)
                    expect(page.locator('.loading-state')).to_have_count(0)
                    page.get_by_test_id('stage-1').click()
                    selector = page.locator('label.field').filter(has_text='构建预设').locator('.el-select')
                    selector.click()
                    page.locator('.el-select-dropdown__item:visible').filter(has_text='debug').first.click()
                    expect(page.get_by_text('ThirdPart/Dll/Debug',exact=True).first).to_be_visible()
                    page.get_by_role('button',name='使用已有程序',exact=True).click()
                    expect(page.get_by_test_id('stage-2')).to_have_class(__import__('re').compile('active'))
                    assert store.load(read_only=True)['DLL_SRC'] == 'ThirdPart/Dll/Debug'
                    page.get_by_test_id('stage-1').click()
                    page.screenshot(path=str(output/'dll-debug.png'),full_page=True)
                    evidence.append('Actual API preset preview/application resolves Dll/Debug')
                    page.get_by_role('button',name='运行体检',exact=True).click()
                    expect(page.locator('.log-content')).to_contain_text('中文半行',timeout=5000)
                    sid = next(iter(runner.sessions))
                    assert runner.output(sid)['status'] != 'done', 'partial output must appear before process exit'
                    page.screenshot(path=str(output/'partial-output.png'),full_page=True)
                    evidence.append('Authenticated live stream displayed a flushed Chinese half-line before exit')
                    expect(page.locator('.log-content')).to_contain_text('tail',timeout=10000)
                    expect(page.locator('.log-connection')).to_contain_text('完整日志已读取',timeout=10000)
                    assert '\x1b' not in page.locator('.log-content').inner_text()
                    with page.expect_download() as download_info:
                        page.get_by_role('button',name='完整另存为',exact=True).click()
                    exported = directory / 'exported.log'
                    download_info.value.save_as(exported)
                    content = exported.read_text(encoding='utf-8')
                    assert '中文半行完成' in content and 'tail' in content
                    evidence.append('Actual streaming download preserved the complete session output')
                    evidence.append(dict(errors=errors))
                    browser.close()
                    assert not errors, errors
            finally:
                server.stopping.set()
                server.shutdown()
                server.server_close()
                runner.shutdown()
    print(json.dumps(dict(passed=evidence,fixture_only=True),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    check()
