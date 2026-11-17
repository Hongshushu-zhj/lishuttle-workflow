"""Isolated production desktop UI acceptance with in-memory business fixtures.

Build desktop-ui first. Uses installed Chrome/Edge and Playwright. Never starts
LiShuttle, writes a project, or imports the user's actual data.
"""
from __future__ import annotations

import json
import re
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
from workflow_browser_check import Fixture, Handler, ROOT, STATE, TASK, EXTERNAL_XML, browser_path

ARTIFACTS = ROOT / '.superpowers' / 'desktop-ui-acceptance'


class DesktopFixture(Fixture):
    def __init__(self, empty=False):
        super().__init__()
        self.empty = empty
        self.preferences = {'log_follow': True, 'compact_mode': False}
        self.preference_revision = 'prefs-1'
        self.run_polls = 0

    def state(self):
        state = super().state()
        state['function_info'] = [dict(name=f, label=f, desc='Isolated acceptance fixture')
                                  for f in state['functions']]
        if self.empty:
            state.update(project='', projects=[], project_config={}, machine_config={},
                         build_workflow={}, cities=[], tasks=[], functions=[], function_info=[])
        return state

    def reply(self, endpoint, body):
        if endpoint == 'desktop_preferences':
            if 'values' in body:
                assert body['revision'] == self.preference_revision
                assert set(body['values']) <= {'schema_version', 'onboarding_complete', 'compact_mode',
                    'log_follow', 'scan_roots', 'log_panel_height', 'last_section', 'theme'}
                self.preferences = body['values']
                self.preference_revision = 'prefs-2'
            return dict(schema_version=1, values=self.preferences, revision=self.preference_revision)
        if endpoint == 'output_stream':
            return dict(legacy=True)
        if endpoint == 'preview_build_target':
            return dict(build_values=self.state()['project_config'], dll=dict(source='C:/fixture/ThirdPart/Dll/Release',mode='Release',exists=True))
        if endpoint == 'desktop_info':
            return dict(version='0.1.0', channel='dev', data_dir='C:/fixture/desktop-data', resource_root='C:/fixture/resources')
        if endpoint == 'discover_start':
            self.requests.append((endpoint, body))
            assert body['roots'] == ['C:/fixture/search']
            return dict(id='scan-1')
        if endpoint == 'discover_status':
            return dict(id='scan-1', status='done', visited=12, skipped=[], limited=False, results=[
                dict(kind='engine', path='C:/fixture/found-engine', label='Detected engine', evidence=['LiShuttle header and CMakeLists'])])
        if endpoint == 'run':
            self.requests.append((endpoint, body))
            assert body.get('_project') == self.project
            assert body.get('_revision') == '1'
            self.runtime = dict(busy=True, sid=704, phase='running', label='fixture run')
            return dict(sid=704, runtime=self.runtime, context=dict(project=self.project, func=body['func'], task_name='actual-A'))
        if endpoint == 'output' and str(body.get('sid', [''])[0]) == '704':
            self.run_polls += 1
            since = int(body.get('since', ['0'])[0])
            lines = [f'current run line {i}' for i in range(503)]
            next_since = min(since + 500, len(lines))
            more = next_since < len(lines)
            if not more:
                self.runtime = dict(busy=False, phase='idle')
            return dict(lines=lines[since:next_since], total=len(lines), next_since=next_since,
                has_more=more, status='done', exit=0, context=dict(project=self.project, func='pred', task_name='actual-A'),
                result=dict(verdict='unconfirmed', process=dict(status='exited'), artifacts=dict(status='unconfirmed'),
                    business=dict(status='unconfirmed')), archive=dict(status='complete'))
        if endpoint == 'csv_save':
            assert body.get('format_revision') == 'format-1'
            assert body.get('header_lines') == 2
        return super().reply(endpoint, body)


class LargeFixture(DesktopFixture):
    def reply(self, endpoint, body):
        if endpoint == 'csv':
            return dict(path=body.get('path', [TASK['engineering_file']])[0], encoding='utf-8',
                revision='csv-large', format_revision='format-large', header_lines=2,
                header_rows=[[f'字段{i}' for i in range(30)], [f'Field{i}' for i in range(30)]],
                rows=[[f'{r}-{c}' for c in range(30)] for r in range(10000)], editable=True)
        if endpoint == 'history':
            offset = int(body.get('offset', ['0'])[0])
            limit = int(body.get('limit', ['20'])[0])
            runs = [dict(self.historical_result(701+i), created_at='2026-11-09T01:00:00+00:00',
                result=dict(verdict='success')) for i in range(offset, min(offset+limit, 500))]
            return dict(runs=runs, total=500, offset=offset, limit=limit)
        if endpoint == 'output':
            since = int(body.get('since', ['0'])[0])
            limit = int(body.get('limit', ['500'])[0])
            end = min(since+limit, 100000)
            return dict(lines=[f'large log line {i}' for i in range(since, end)], total=100000,
                next_since=end, has_more=end<100000, status='done', exit=0,
                context=dict(project=self.project, func='pred'), result=dict(verdict='unconfirmed'))
        return super().reply(endpoint, body)


class DesktopHandler(Handler):
    def __init__(self, *args, fixture, **kwargs):
        self.fixture = fixture
        SimpleHTTPRequestHandler.__init__(self, *args, directory=str(ROOT / 'desktop-ui' / 'dist'), **kwargs)


def serve(fixture):
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(DesktopHandler, fixture=fixture))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f'http://127.0.0.1:{server.server_port}'


def settled(page):
    expect(page.locator('.loading-state')).to_have_count(0)
    expect(page.locator('.spinner')).to_have_count(0)


def stage(page, index):
    if not page.get_by_test_id(f'stage-{index}').count():
        page.locator('.main-navigation').get_by_role('button', name='工作台', exact=True).click()
    page.get_by_test_id(f'stage-{index}').click()


def select_option(page, locator, label):
    locator.click()
    page.locator('.el-select-dropdown__item:visible').filter(has_text=label).first.click()


def check_scaling(page, checks):
    for width,height in ((1366,768),(1093,614),(911,512),(683,384)):
        page.set_viewport_size(dict(width=width,height=height))
        page.locator('.main-navigation').get_by_role('button',name='工作台',exact=True).click()
        stage(page,0)
        expect(page.get_by_test_id('project-add')).to_be_visible()
        bounds=page.locator('.desktop-shell').bounding_box()
        assert bounds and bounds['x']>=0 and bounds['width']<=width+1, (width,bounds)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
        for button in page.locator('.stage-footer button').all():
            if not button.is_visible(): continue
            box=button.bounding_box()
            assert box and box['x']>=0 and box['x']+box['width']<=width+1 and box['y']>=0 and box['y']+box['height']<=height+1, (width,box)
        field=page.get_by_test_id('project-path').locator('input')
        field.scroll_into_view_if_needed()
        box=field.bounding_box()
        footer=page.locator('.stage-footer').bounding_box()
        main=page.locator('.page-scroll').bounding_box()
        assert box and main and footer and box['y']>=main['y'] and box['y']+box['height']<=footer['y']+1,(width,box,footer)
        page.screenshot(path=str(ARTIFACTS/f'scale-{width}x{height}.png'),full_page=True)
    checks.append('1366x768 screen at logical 100/125/150/200 percent layout widths')


def check_large(p,checks,errors):
    large=LargeFixture()
    server,origin=serve(large)
    try:
        browser=p.chromium.launch(executable_path=browser_path(),headless=True)
        page=browser.new_page(viewport=dict(width=1366,height=900))
        page.on('pageerror',lambda err:errors.append(str(err)))
        page.add_init_script("window.__saved=[];window.desktop={setDirty:()=>{},saveText:async v=>{window.__saved.push(v);return {saved:true}},exportSessionLog:async v=>{window.__saved.push(v);return {saved:true}},info:async()=>({version:'0.1.0',channel:'dev'})}")
        page.goto(origin)
        settled(page)
        stage(page,2)
        select_option(page,page.get_by_test_id('runtime-select'),'saved.xml')
        page.get_by_test_id('runtime-activate').click()
        page.get_by_role('tab',name='工参 CSV · 手动保存').click()
        start=time.perf_counter()
        page.get_by_test_id('csv-load').click()
        expect(page.get_by_text('utf-8 · 2 行表头 · 10000 行数据',exact=False)).to_be_visible(timeout=30000)
        csv_seconds=round(time.perf_counter()-start,3)
        assert page.get_by_test_id('csv-cell').count()<2000, 'CSV must render a viewport, not 300000 inputs'
        page.locator('.main-navigation').get_by_role('button',name='运行记录',exact=True).click()
        expect(page.get_by_text('当前项目 · 共 500 条记录',exact=True)).to_be_visible()
        assert page.get_by_role('button',name='查看会话',exact=True).count()==20
        page.get_by_role('button',name='查看会话',exact=True).first.click()
        start=time.perf_counter()
        expect(page.get_by_text('large log line 99999',exact=False)).to_be_visible(timeout=120000)
        log_seconds=round(time.perf_counter()-start,3)
        assert page.locator('.log-content>div').count()<=3000
        following=page.locator('.log-content').evaluate('(e)=>e.scrollHeight-e.scrollTop-e.clientHeight')
        assert following<40, f'follow stopped at bounded capacity: {following}'
        page.get_by_role('button',name='完整另存为',exact=True).click()
        page.wait_for_function('window.__saved.length===1',timeout=30000)
        saved=page.evaluate('window.__saved[0]')
        assert saved == {'sid':701}, saved  # Native bridge exports by trusted SID, not aggregated renderer text.
        browser.close()
        checks.append(dict(scale_fixture=dict(csv_rows=10000,csv_columns=30,log_lines=100000,history_records=500),
            csv_load_seconds=csv_seconds,log_drain_seconds=log_seconds))
    finally:
        server.shutdown()
        server.server_close()


def check():
    assert (ROOT / 'desktop-ui' / 'dist' / 'index.html').is_file(), 'Build desktop-ui first'
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    fixture = DesktopFixture()
    server, origin = serve(fixture)
    checks, errors = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=browser_path(), headless=True)
            page = browser.new_page(viewport=dict(width=1366, height=900), device_scale_factor=1)
            page.on('pageerror', lambda err: errors.append(str(err)))
            # Native bridge stub records only the public capability calls.
            page.add_init_script("window.__dirty=[]; window.__saved=[]; window.desktop={setDirty:v=>window.__dirty.push(v),saveText:async v=>{window.__saved.push(v);return {saved:true,path:'C:/fixture/export.log'}},exportSessionLog:async v=>{window.__saved.push(v);return {saved:true,path:'C:/fixture/export.log'}},pickDirectory:async()=>null,pickFile:async()=>null,openPath:async()=>{},info:async()=>({version:'0.1.0',channel:'dev',dataDir:'C:/fixture/desktop-data',resourceRoot:'C:/fixture/resources'})}")
            page.goto(origin)
            expect(page.get_by_text('服务已连接', exact=True)).to_be_visible()
            settled(page)
            expect(page.locator('.page-heading h1')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'horizontal page overflow'
            page.screenshot(path=str(ARTIFACTS / 'project-1366.png'), full_page=True)
            checks.append('production workspace at 1366 px')

            stage(page, 2)
            select_option(page, page.get_by_test_id('runtime-select'), 'saved.xml')
            page.get_by_test_id('runtime-activate').click()
            expect(page.get_by_role('textbox', name='MaxDeepth', exact=True)).to_have_count(0)  # pred scope hides indoor-only field
            settled(page)
            assert fixture.render_count == 0
            assert any(n == 'activate_runtime_config' and b.get('scope') == 'scope-A' and b.get('revision') for n, b in fixture.requests)
            checks.append('existing XML loads with revision, without rendering')

            select_option(page, page.locator('.scope-select'), '全部已识别参数')
            depth = page.get_by_role('textbox', name='MaxDeepth', exact=True)
            expect(depth).to_have_value('3')
            original = fixture.runtime_xml[fixture.project]['saved.xml']
            depth.fill('9')
            depth.press('Tab')
            expect(page.get_by_text('XML 已保存，原文件保留 .bak 备份。', exact=True)).to_be_visible()
            assert fixture.runtime_xml[fixture.project]['saved.xml'] == original.replace(b'<MaxDeepth>3</MaxDeepth>', b'<MaxDeepth>9</MaxDeepth>')
            checks.append('XML autosave preserves source bytes outside scalar')

            page.get_by_role('tab', name='工参 CSV · 手动保存').click()
            page.get_by_test_id('csv-load').click()
            cell = page.get_by_test_id('csv-cell').first
            expect(cell).to_have_value('1')
            cell.fill('42')
            expect(page.get_by_test_id('preflight')).to_be_disabled()
            assert page.evaluate('window.__dirty.at(-1)') is True
            stage(page, 0)
            expect(page.get_by_role('button', name='刷新状态', exact=True)).to_be_disabled()
            assert not any(n == 'select_project' for n, _ in fixture.requests)
            stage(page, 4)
            page.get_by_test_id('csv-save').click()
            expect(page.get_by_text('Fixture CSV saved', exact=True)).to_be_visible()
            assert fixture.csv_rows[0][0] == '42'
            assert page.evaluate('window.__dirty.at(-1)') is False
            checks.append('CSV explicit save, format guards and native dirty state')

            page.get_by_test_id('preflight').click()
            expect(page.get_by_text('当前版本检查通过', exact=True)).to_be_visible()
            stage(page, 5)
            run_button = page.get_by_test_id('run')
            expect(run_button).to_be_enabled()
            run_button.click()
            expect(page.get_by_text('完整日志已读取', exact=True)).to_be_visible(timeout=15000)
            assert fixture.run_polls >= 2
            assert any(n == 'run' for n, _ in fixture.requests)
            expect(page.get_by_text('未确认', exact=True).first).to_be_visible()
            checks.append('preflight, pinned run sid and terminal log pagination')
            stage(page,4)
            page.get_by_role('tab',name='工参 CSV · 手动保存').click()
            saved_calls=sum(n=='csv_save' for n,_ in fixture.requests)
            page.get_by_test_id('csv-cell').first.fill('unknown-draft')
            page.route('**/api/csv_save',lambda route:route.abort('failed'))
            page.get_by_test_id('csv-save').click()
            expect(page.locator('.critical-banner')).to_be_visible()
            expect(page.get_by_test_id('csv-save')).to_be_disabled()
            page.unroute('**/api/csv_save')
            page.get_by_role('button',name='放弃草稿并读取当前文件',exact=True).click()
            expect(page.get_by_test_id('csv-cell').first).to_have_value('42')
            expect(page.locator('.critical-banner')).to_have_count(0)
            assert saved_calls==sum(n=='csv_save' for n,_ in fixture.requests), 'unknown write was retried'
            checks.append('unknown CSV write permits explicit read reconciliation without retry')
            stage(page,5)
            page.screenshot(path=str(ARTIFACTS / 'results-1366.png'), full_page=True)

            page.locator('.main-navigation').get_by_role('button', name='运行记录', exact=True).click()
            expect(page.get_by_test_id('history')).to_be_visible()
            page.get_by_role('button', name='查看会话', exact=True).first.click()
            expect(page.get_by_text('history line 502', exact=False)).to_be_visible(timeout=15000)
            expect(page.get_by_text('当时成功，当前文件已变化', exact=True)).to_be_visible()
            assert str(page.locator('.log-drawer').inner_text()).find('701') >= 0
            checks.append('fixed historical sid with full paginated logs')

            page.locator('.main-navigation').get_by_role('button', name='环境与路径', exact=True).click()
            expect(page.get_by_test_id('settings')).to_be_visible()
            page.get_by_text('紧凑工作空间', exact=True).click()
            page.get_by_role('button', name='保存偏好', exact=True).click()
            expect(page.get_by_text('桌面偏好已保存。', exact=True)).to_be_visible()
            assert fixture.preferences['compact_mode'] is True
            discovery = page.get_by_test_id('discovery')
            discovery.locator('input').first.fill('C:/fixture/search')
            discovery.get_by_role('button', name='开始发现', exact=True).click()
            expect(page.get_by_text('Detected engine', exact=True)).to_be_visible()
            discovery.get_by_role('button', name='填入草稿', exact=True).click()
            expect(page.get_by_test_id('project-path').locator('input')).to_have_value('C:/fixture/found-engine')
            assert not any(n == 'select_project' for n, _ in fixture.requests)
            checks.append('preferences and discovery only populate explicit project draft')

            page.set_viewport_size(dict(width=1920, height=1080))
            page.screenshot(path=str(ARTIFACTS / 'project-1920.png'), full_page=True)
            assert not fixture.unknown, fixture.unknown
            assert not errors, errors
            browser.close()

            browser = p.chromium.launch(executable_path=browser_path(), headless=True)
            page = browser.new_page(viewport=dict(width=1366, height=900))
            page.on('pageerror', lambda err: errors.append(str(err)))
            page.goto(origin)
            settled(page)
            stage(page, 2)
            page.get_by_role('button', name=re.compile('^原字节副本导入')).click()
            page.locator('label.path-field').filter(has_text='源 XML 文件').locator('input').fill(EXTERNAL_XML)
            page.locator('label.field').filter(has_text='目标文件名').locator('input').fill('imported.xml')
            source_bytes = fixture.external_xml
            page.get_by_role('button', name='预览导入', exact=True).click()
            expect(page.get_by_role('button', name='确认原字节导入', exact=True)).to_be_enabled()
            page.get_by_role('button', name='确认原字节导入', exact=True).click()
            expect(page.get_by_text('原字节副本已导入；源 XML 保持原样，路径未改写。', exact=True)).to_be_visible()
            assert fixture.runtime_xml[fixture.project]['imported.xml'] == source_bytes
            checks.append('external XML import adds exact byte copy after preview')

            stage(page, 2)
            page.get_by_role('button', name=re.compile('^新建与路径适配')).click()
            select_option(page, page.locator('label.field').filter(has=page.get_by_text('任务', exact=True)).locator('.el-select'), TASK['name'])
            select_option(page, page.locator('section.card').filter(has=page.get_by_role('heading', name='地图与场景', exact=True)).locator('.el-select'), 'Example city')
            page.locator('label.field').filter(has_text='新运行任务名').locator('input').fill('fixture-adapt')
            page.locator('.stage-footer').get_by_role('button', name='预览任务装配', exact=True).click()
            expect(page.get_by_text('预览有效', exact=True)).to_be_visible()
            assert any(n=='preview_render' for n,_ in fixture.requests)
            confirm = page.get_by_role('button', name='确认装配当前预览', exact=True)
            expect(confirm).to_be_enabled()
            confirm.click()
            expect(page.get_by_text('Fixture recoverable assembly error', exact=True)).to_be_visible()
            expect(confirm).to_be_enabled()
            assert fixture.render_count == 1
            confirm.click()
            expect(page.get_by_test_id('preflight')).to_be_visible()
            assert fixture.render_count == 2
            checks.append('task XML adaptation keeps reusable preview after recoverable error')
            browser.close()

            empty = DesktopFixture(empty=True)
            empty_server, empty_origin = serve(empty)
            try:
                browser = p.chromium.launch(executable_path=browser_path(), headless=True)
                page = browser.new_page(viewport=dict(width=1366, height=900))
                page.on('pageerror', lambda err: errors.append(str(err)))
                page.goto(empty_origin)
                settled(page)
                expect(page.get_by_text('从一个引擎项目开始', exact=False)).to_be_visible()
                page.screenshot(path=str(ARTIFACTS / 'onboarding-1366.png'), full_page=True)
                check_scaling(page,checks)
                assert not empty.unknown, empty.unknown
                browser.close()
                checks.append('empty first-run onboarding')
            finally:
                empty_server.shutdown()
                empty_server.server_close()
            check_large(p,checks,errors)
    finally:
        server.shutdown()
        server.server_close()
    report = dict(passed=checks, pageerrors=errors, fixture_only=True)
    (ARTIFACTS / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    check()
