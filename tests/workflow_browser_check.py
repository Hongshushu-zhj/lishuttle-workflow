"""Optional isolated browser QA: python tests/workflow_browser_check.py.

Requires locally installed Playwright and Chrome/Edge; installs nothing. The
temporary HTTP server serves only frontend assets and in-memory API fixtures.
No application server, project configuration, XML, CSV or engine is touched.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'platform/backend')]
from parameter_catalog import parse_document, build_catalog
PARAM_SPEC = json.loads((ROOT / 'platform/backend/params_spec.json').read_text(encoding='utf-8'))
CONFIG = dict(PRESET="release", BUILD_SUBDIR="build/release", INSTALL_SUBDIR="install",
              EXE_NAME="lishuttle.exe", CONFIG_SRC="C:/fixture/ThirdPart/config",
              DLL_SRC="C:/fixture/ThirdPart/bin", MAP_ROOT="C:/fixture/maps",
              GONGCAN_ROOT="C:/fixture/tasks", OUT_ROOT="C:/fixture/outputs")
BUILD = dict(built=True, directory_exists=True,
             executable="C:/fixture/project/build/release/Bin/lishuttle.exe",
             presets={"release": {"build_type": "Release", "values": CONFIG}})
TASK = dict(name="Outdoor sample", kind="outdoor", dir="C:/fixture/tasks/sample",
            detect="已识别室外工参", engineering_reason="已识别室外工参",
            engineering_file="C:/fixture/tasks/sample/cells.csv",
            engineering_candidates=["C:/fixture/tasks/sample/cells.csv"],
            engineering_kinds={"C:/fixture/tasks/sample/cells.csv": "outdoor"},
            schema_candidates=[dict(path="C:/fixture/tasks/sample/source.xml",
                                    name="source-job", kind="outdoor")],
            txts=[], has_antennas=False)
STATE = dict(project="C:/fixture/project", projects=["C:/fixture/project"],
             profile_id="fixture", profile_revision="1", machine_revision="1",
             project_config=CONFIG, machine_config={}, build_workflow=BUILD,
             functions=["pred", "commsensing", "predindoor", "cali"],
             cities=[dict(name="Example city", kind="outdoor", dir="C:/fixture/maps/city", checks=[])],
             tasks=[TASK], map_root=CONFIG["MAP_ROOT"], gongcan_root=CONFIG["GONGCAN_ROOT"],
             preset="release", out_root=CONFIG["OUT_ROOT"], runtime=dict(busy=False, phase="idle"))


class Fixture:
    def __init__(self):
        self.requests = []
        self.runtime = dict(busy=False, phase="idle")
        self.render_count = 0
        self.radius = "1000"
        self.fail_parameter_once = False
        self.xml_revision = 1
        self.csv_revision = 1
        self.csv_headers = [["编号"], ["Cell ID"]]
        self.csv_rows = [["1"], ["2"]]
        self.csv_editable = True
        self.unknown = []
        self.current_files = 'changed'
        self.building_enabled = False
        self.building_revision = 1
        self.indoor_values = dict(MapFormat='indoor', MapPath='C:/fixture/maps/indoor',
            EngineeringFilePath='C:/fixture/ap.csv', PathlossDirectory='C:/fixture/outputs',
            MaxRayNumber='8', MaxDeepth='6', MaxReflection='4', MaxDiffraction='2', MaxPenetration='2',
            MinimumWallLength='0.2', DefaultCalcResolution='1', DefaultUEHeight='1',
            IndoorRxPowerSF='10', IndoorSinrSF='2', IsForcedCalc='true')

    def building_status(self):
        return dict(supported=True, enabled=self.building_enabled, revision=f'source-{self.building_revision}',
                    requires_rebuild=True, path='C:/fixture/project/Propagation/Frame/src/PathLossofIndoorEngine.cpp')

    def historical_result(self, sid=701):
        return dict(sid=sid, historical=True, associated=True, historical_verdict='success' if sid == 701 else 'unconfirmed',
                    verdict='success' if sid == 701 else 'unconfirmed', status='done' if sid == 701 else 'interrupted',
                    exit=0 if sid == 701 else None, label='Fixture historical run',
                    context=dict(project=STATE['project'], task_name='archived-task', func='pred'),
                    dir='C:/fixture/outputs/archived-task', exists=self.current_files != 'missing',
                    current_files=dict(status=self.current_files, files=[]),
                    archive=dict(status='complete' if sid == 701 else 'incomplete', dir='C:/fixture/archives/' + str(sid)),
                    process=dict(status='exited' if sid == 701 else 'interrupted', exit=0 if sid == 701 else None),
                    artifacts=dict(status='valid' if sid == 701 else 'unconfirmed'), business=dict(status='usable'),
                    files=[dict(rel='RSRP.dem', size=8)], log_tail=['historical evidence'], issues=[], errors=[])

    def csv_grid(self):
        return dict(path=TASK["engineering_file"], encoding="utf-8", revision=f"csv-{self.csv_revision}",
                    format_revision="format-1", header_lines=len(self.csv_headers),
                    header_rows=self.csv_headers, header_zh=self.csv_headers[0] if self.csv_headers else [],
                    header_en=self.csv_headers[1] if len(self.csv_headers) > 1 else [],
                    rows=self.csv_rows, columns={"CellId": 0}, editable=self.csv_editable,
                    read_only_reason="Fixture unknown format" if not self.csv_editable else "")

    def reply(self, endpoint, body):
        self.requests.append((endpoint, body))
        if endpoint == "state":
            return STATE
        if endpoint == "runtime_state":
            return self.runtime
        if endpoint == 'history':
            runs = [dict(self.historical_result(sid), created_at='2026-11-09T01:00:00+00:00',
                         result=dict(verdict='success' if sid == 701 else 'unconfirmed')) for sid in (701, 702)]
            return dict(runs=runs, total=2, limit=10, offset=0)
        if endpoint == 'results':
            return self.historical_result(int(body.get('sid', ['701'])[0]))
        if endpoint == 'output':
            sid = int(body.get('sid', ['701'])[0])
            if sid == 703:
                self.runtime = dict(busy=False, phase='idle')
                return dict(lines=['Fixture build complete'], total=1, next_since=1, has_more=False,
                            status='done', exit=0, label='build', result=dict(verdict='success'),
                            context=dict(project=STATE['project'], operation='build'))
            since, limit = int(body.get('since', ['0'])[0]), int(body.get('limit', ['500'])[0])
            lines = [f'history line {index}' for index in range(503 if sid == 701 else 1)]
            report = self.historical_result(sid)
            return dict(lines=lines[since:since + limit], total=len(lines), next_since=min(len(lines), since + limit),
                        has_more=since + limit < len(lines), status=report['status'], exit=report['exit'],
                        result=dict(verdict=report['verdict']), context=report['context'], archive=report['archive'], label=report['label'])
        if endpoint == 'open_folder':
            return dict(ok=True)
        if endpoint == 'indoor_building_export':
            return self.building_status()
        if endpoint == 'enable_indoor_building_export':
            assert body['revision'] == f'source-{self.building_revision}'
            self.building_enabled = True
            self.building_revision += 1
            return dict(self.building_status(), ok=True, changed=True)
        if endpoint == 'toolkit':
            assert body['step'] == 'build'
            self.runtime = dict(busy=True, phase='running', sid=703, label='build', operation='build')
            return dict(sid=703, runtime=self.runtime, build_values=CONFIG, profile_revision='1')
        if endpoint == "detect_project_config":
            return dict(values={}, fields={}, presets=BUILD["presets"], warnings=[])
        if endpoint == "build_status":
            return dict(build_values={k: CONFIG[k] for k in ("PRESET", "BUILD_SUBDIR", "INSTALL_SUBDIR", "EXE_NAME")},
                        build_workflow=BUILD)
        if endpoint == "local_paths":
            return dict(values={}, unresolved={}, warnings=[])
        if endpoint == "task_binding":
            return dict(binding=None)
        if endpoint == "validate_setup":
            return dict(ok=True, issues=[])
        if endpoint == "preview_render":
            return dict(source=TASK["schema_candidates"][0]["path"],
                        destination="C:/fixture/project/build/release/Bin/source-job.xml",
                        runtime_name="source-job", out_dir="C:/fixture/outputs/source-job",
                        token="isolated-preview-token", warnings=[],
                        changes=[dict(tag="MapPath", old="X:/original/map", new="C:/fixture/maps/city")])
        if endpoint == "render":
            self.render_count += 1
            if self.render_count == 1:
                return dict(error="Fixture recoverable assembly error")
            return dict(schema_ok=True, generated=True, render_status="ready", render_exit=0, schema_name="source-job.xml",
                        runtime_name="source-job", func=body["func"], task_id=body["task_id"],
                        out_dir="C:/fixture/outputs/source-job", render_output="Fixture assembly complete", copied=[])
        if endpoint == "params":
            function = body.get('func', ['pred'])[0]
            if function == 'predindoor':
                raw = ('<RuntimeSchema name="source-job">' + ''.join(
                    f'<{tag}>{value}</{tag}>' for tag, value in self.indoor_values.items()) + '</RuntimeSchema>').encode()
                document = parse_document(raw)
                return dict(build_catalog(document, PARAM_SPEC, function), values=document['values'],
                    file='C:/fixture/project/Bin/source-job.xml', revision=f'xml-{self.xml_revision}',
                    indoor_building_export=self.building_status(), thirdpart_defaults={
                        tag: dict(available=True, value=value,
                                  source='C:/fixture/ThirdPart/config/runtimelibrary/indoorruntimeschema.xml')
                        for tag, value in self.indoor_values.items()})
            return dict(function=function, indoor_building_export=self.building_status() if function == 'predindoor' else None,
                        file="C:/fixture/project/Bin/source-job.xml", revision=f"xml-{self.xml_revision}", values={"CalcRadius": self.radius},
                        groups=[dict(group="Prediction", rows=[dict(name="CalcRadius", label="计算半径", type="float",
                            desc="Fixture editable parameter", recommended=True, classification="current")])])
        if endpoint == "preflight":
            return dict(ok=True, issues=[], context=dict(mode=dict(requested="ground", effective="ground")))
        if endpoint == 'param_default':
            assert body['tag'] == 'MaxDeepth'
            assert body['revision'] == f'xml-{self.xml_revision}'
            self.indoor_values['MaxDeepth'] = '6'
            self.xml_revision += 1
            return dict(ok=True, revision=f'xml-{self.xml_revision}', value='6')
        if endpoint == "param_write":
            if self.fail_parameter_once:
                return dict(ok=False, error="Fixture parameter save failed")
            if body.get("revision") != f"xml-{self.xml_revision}":
                return dict(ok=False, code="FILE_CONFLICT", error="Fixture XML conflict: 文件已变化，请重新加载，草稿已保留")
            if body['tag'] in self.indoor_values:
                self.indoor_values[body['tag']] = body['value']
            else:
                self.radius = body["value"]
            self.xml_revision += 1
            return dict(ok=True, target="schema", revision=f"xml-{self.xml_revision}")
        if endpoint == "csv":
            return self.csv_grid()
        if endpoint == "csv_save":
            if body.get("revision") != f"csv-{self.csv_revision}":
                return dict(ok=False, code="FILE_CONFLICT", error="Fixture CSV conflict: 文件已变化，请重新加载，草稿已保留")
            assert body["header_rows"] == self.csv_headers, body
            assert len(body["rows"]) == 2, body
            self.csv_rows = body["rows"]
            self.csv_revision += 1
            return dict(ok=True, message="Fixture CSV saved", revision=f"csv-{self.csv_revision}")
        self.unknown.append(endpoint)
        return dict(error="Unexpected fixture endpoint: " + endpoint)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, fixture, **kwargs):
        self.fixture = fixture
        super().__init__(*args, directory=str(ROOT / "platform/frontend"), **kwargs)

    def log_message(self, *_):
        pass

    def api(self):
        endpoint = urlparse(self.path).path.removeprefix("/api/")
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        if self.command == 'GET':
            body = parse_qs(urlparse(self.path).query)
        payload = json.dumps(self.fixture.reply(endpoint, body)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.startswith("/api/"):
            self.api()
        else:
            super().do_GET()

    def do_POST(self):
        if not self.path.startswith("/api/"):
            self.send_error(405)
            return
        self.api()


def browser_path():
    candidates = [os.environ.get("WORKFLOW_BROWSER", ""),
                  r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("Set WORKFLOW_BROWSER to an installed Chromium browser; no download is performed")


def check():
    fixture = Fixture()
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, fixture=fixture))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    screenshots = ROOT / "docs/superpowers/screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    errors = []
    passed = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=browser_path(), headless=True)
            context = browser.new_context(viewport=dict(width=1440, height=1000), reduced_motion="reduce")
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(error.stack))
            page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="networkidle")
            expect(page.locator("#workflow-nav button")).to_have_count(6)
            assert not errors, errors
            passed.append("bootstrap, six stage navigation, no pageerrors")
            expect(page.locator('#stage-project #project')).to_have_value(STATE['project'])
            expect(page.locator('#stage-project #current-project-path')).to_have_text(STATE['project'])
            expect(page.locator('#current-project-name')).to_have_text('当前项目：project')
            expect(page.locator('header #project, header #env-note')).to_have_count(0)
            passed.append("project selection, identity and environment stay together in the project stage")
            for name in ('project', 'build', 'inputs', 'assembly', 'check', 'run'):
                stage = page.locator('#stage-' + name)
                summary = stage.locator(':scope > summary')
                collapse = summary.locator('.stage-toggle-collapse')
                expect(collapse).to_be_visible()
                assert summary.locator('.stage-toggle').bounding_box()['height'] >= 44
                collapse.click()
                expect(summary.locator('.stage-toggle-expand')).to_be_visible()
                expect(stage.locator(':scope > .stage-body')).to_be_hidden()
                summary.focus()
                summary.press('Enter')
                expect(collapse).to_be_visible()
                expect(stage.locator(':scope > .stage-body')).to_be_visible()
                summary.press('Space')
                expect(summary.locator('.stage-toggle-expand')).to_be_visible()
                summary.locator('.stage-toggle-expand').click()
                expect(collapse).to_be_visible()
            passed.append("all six visible controls support click, Enter and Space without changing workflow readiness")
            expect(page.locator("#btn-build")).to_be_disabled()
            expect(page.locator("#btn-use-executable")).to_be_enabled()
            page.locator("#btn-use-executable").click()
            expect(page.locator("#hint")).to_contain_text("已使用匹配程序")
            assert not any(name == "toolkit" for name, _ in fixture.requests)
            passed.append("existing executable reuse with empty compiler settings")
            page.locator("#task-list .task").click()
            page.locator("#city-list .city").click()
            page.locator("#job-name").fill("Browser fixture")
            page.locator("#job-name").dispatch_event("change")
            page.locator("#use-existing-schema").check()
            page.locator('[data-workflow-stage="assembly"]').click()
            page.locator("#btn-render").click()
            apply = page.locator("#btn-apply-schema")
            expect(apply).to_be_enabled()
            expect(page.locator("#schema-preview-text")).to_contain_text("MapPath")
            passed.append("task/city selection and existing XML path difference preview")
            fixture.runtime = dict(busy=True, phase="preparing", label="Fixture operation", sid=None)
            page.evaluate("refreshRuntimeState()")
            expect(apply).to_be_disabled()
            fixture.runtime = dict(busy=False, phase="idle")
            page.evaluate("refreshRuntimeState()")
            expect(apply).to_be_enabled()
            passed.append("busy then idle preserves a valid preview")
            apply.click()
            expect(page.locator("#hint")).to_contain_text("Fixture recoverable assembly error")
            expect(apply).to_be_enabled()
            apply.click()
            expect(page.locator('#params-area [data-tag="CalcRadius"]')).to_be_visible()
            assert fixture.render_count == 2
            passed.append("ordinary apply error allows manual retry, successful assembly loads parameters")
            page.locator("#btn-preflight").click()
            expect(page.locator("#btn-run")).to_be_enabled()
            parameter = page.locator('#params-area [data-tag="CalcRadius"]')
            parameter.fill("1250")
            parameter.press("Tab")
            expect(page.locator("#hint")).to_contain_text("已写入")
            expect(page.locator("#btn-run")).to_be_disabled()
            expect(page.locator("#preflight-report")).to_contain_text("已过期")
            expect(page.locator("#assembly-summary")).to_contain_text("已装配")
            passed.append("successful XML parameter save invalidates preflight and preserves assembly")
            fixture.fail_parameter_once = True
            parameter.fill("1300")
            parameter.press("Tab")
            expect(page.locator("#hint")).to_contain_text("Fixture parameter save failed")
            expect(page.locator("#btn-params-save")).to_be_visible()
            expect(page.locator("#btn-params-discard")).to_be_visible()
            page.locator("#params-search").fill("different filter")
            expect(parameter).to_have_value("1300")
            fixture.fail_parameter_once = False
            page.locator("#btn-params-save").click()
            expect(page.locator("#btn-params-save")).to_be_hidden()
            expect(parameter).to_have_value("1300")
            fixture.fail_parameter_once = True
            parameter.fill("1400")
            parameter.press("Tab")
            expect(page.locator("#btn-params-discard")).to_be_visible()
            page.locator("#btn-params-discard").click()
            expect(page.locator('#params-area [data-tag="CalcRadius"]')).to_have_value("1300")
            fixture.fail_parameter_once = False
            passed.append("failed XML autosave retains draft across filtering, exposes retry and explicit discard")
            fixture.radius = "external-value"
            fixture.xml_revision += 1
            parameter = page.locator('#params-area [data-tag="CalcRadius"]')
            parameter.fill("local-draft")
            parameter.press("Tab")
            expect(page.locator("#hint")).to_contain_text("Fixture XML conflict")
            expect(parameter).to_have_value("local-draft")
            page.locator("#btn-params-save").click()
            expect(page.locator("#hint")).to_contain_text("Fixture XML conflict")
            assert fixture.radius == "external-value"
            page.locator("#btn-params-discard").click()
            expect(page.locator('#params-area [data-tag="CalcRadius"]')).to_have_value("external-value")
            passed.append("external XML edit conflicts on save and retry, keeps local draft until explicit reload")
            page.locator("#csv-editor summary").click()
            page.locator("#btn-csv-load").click()
            cell = page.locator("#csv-wrap td[contenteditable]").first
            cell.fill("2")
            expect(page.locator("#btn-csv-discard")).to_be_visible()
            page.locator('input[name="func"][value="cali"]').click()
            expect(page.locator('input[name="func"][value="pred"]')).to_be_checked()
            expect(cell).to_have_text("2")
            page.locator("#btn-csv-discard").click()
            expect(page.locator("#csv-wrap td[contenteditable]").first).to_have_text("1")
            expect(page.locator("#btn-csv-discard")).to_be_hidden()
            passed.append("unsaved CSV blocks input change and explicit discard reloads saved content")
            fixture.csv_rows = [["external"], ["2"]]
            fixture.csv_revision += 1
            cell = page.locator("#csv-wrap td[contenteditable]").first
            cell.fill("csv-draft")
            page.locator("#btn-csv-save").click()
            expect(page.locator("#hint")).to_contain_text("Fixture CSV conflict")
            expect(cell).to_have_text("csv-draft")
            expect(page.locator("#btn-csv-discard")).to_be_visible()
            assert fixture.csv_rows[0] == ["external"]
            page.locator("#btn-csv-discard").click()
            expect(page.locator("#csv-wrap td[contenteditable]").first).to_have_text("external")
            passed.append("external CSV edit conflicts and keeps full table draft until explicit reload")
            for count in (2, 1, 0):
                fixture.csv_headers = [["编号"], ["Cell ID"]][:count]
                fixture.csv_revision += 1
                page.locator("#btn-csv-load").click()
                cells = page.locator("#csv-wrap td[contenteditable]")
                expect(cells).to_have_count(2)
                cells.first.fill(f"first-{count}")
                page.locator("#btn-csv-save").click()
                expect(page.locator("#btn-csv-discard")).to_be_hidden()
                assert fixture.csv_rows == [[f"first-{count}"], ["2"]]
                cells.last.fill(f"second-{count}")
                page.locator("#btn-csv-save").click()
                expect(page.locator("#btn-csv-discard")).to_be_hidden()
                assert fixture.csv_rows == [[f"first-{count}"], [f"second-{count}"]]
                fixture.csv_rows = [["external"], ["2"]]
            passed.append("two, one and zero header rows preserve both records and advance revision after each save")
            fixture.csv_editable = False
            page.locator("#btn-csv-load").click()
            expect(page.locator("#csv-wrap td[contenteditable]")).to_have_count(0)
            expect(page.locator("#csv-msg")).to_contain_text("Fixture unknown format")
            saves = sum(name == 'csv_save' for name, _ in fixture.requests)
            page.evaluate("saveCsv()")
            assert sum(name == 'csv_save' for name, _ in fixture.requests) == saves
            passed.append("unknown engineering format is read only in the browser")
            page.locator('input[name="func"][value="commsensing"]').check()
            expect(page.locator("#assembly-summary")).to_contain_text("请重新装配")
            expect(page.locator("#btn-run")).to_be_disabled()
            passed.append("function change marks prior assembly stale and blocks run")
            page.locator('input[name="func"][value="predindoor"]').check()
            page.evaluate('loadParams()')
            page.locator('#params-search').fill('')
            for tag in ('MaxDeepth', 'MaxReflection', 'MaxDiffraction', 'MaxPenetration',
                        'MaxRayNumber', 'IndoorRxPowerSF', 'IndoorSinrSF'):
                expect(page.locator(f'input[data-tag="{tag}"]')).to_have_value(fixture.indoor_values[tag])
            expect(page.locator('#params-source')).to_contain_text('无需重新编译')
            depth = page.locator('input[data-tag="MaxDeepth"]')
            depth.fill('3')
            depth.press('Tab')
            expect(page.locator('#hint')).to_contain_text('MaxDeepth 已写入')
            assert fixture.indoor_values['MaxDeepth'] == '3'
            assert fixture.indoor_values['IsForcedCalc'] == 'true'
            default = page.locator('button[data-default-tag="MaxDeepth"]')
            expect(default).to_have_attribute('title', re.compile('indoorruntimeschema.xml'))
            default.click()
            expect(page.locator('input[data-tag="MaxDeepth"]')).to_have_value('6')
            passed.append('indoor ray and scaling parameters display, save to XML and restore the indoor sample default')
            expect(page.locator('#indoor-building-panel')).to_be_visible()
            expect(page.locator('#indoor-building-status')).to_contain_text('未开启')
            page.locator('#btn-enable-indoor-building').click()
            expect(page.locator('#indoor-building-status')).to_contain_text('重新编译')
            expect(page.locator('#btn-enable-indoor-building')).to_be_disabled()
            page.locator('#params-search').fill('CalcRadius')
            expect(page.locator('#indoor-building-status')).to_contain_text('已开启')
            page.locator('#btn-indoor-building-build').click()
            expect(page.locator('#stage-build')).to_be_visible()
            passed.append('indoor export changes source only on click, preserves enabled status across filters and prompts rebuilding')
            page.evaluate("toolkit('build')")
            expect(page.locator('#run-connection')).to_have_text('日志已读取完整')
            expect(page.locator('#runtime-status')).to_have_text('平台空闲')
            assert page.evaluate('S.pollTimer === null && !S.runtime.busy && !S.inputTransition')
            page.locator('#build-mode').select_option('release')
            passed.append('finished build drains logs, refreshes program state and releases input and runtime locks')
            job_before_history = page.evaluate('JSON.stringify(S.job)')
            page.locator('[data-history-sid="701"]').click()
            expect(page.locator('#result-status')).to_contain_text('当时：成功')
            expect(page.locator('#result-status')).to_contain_text('当前文件：已变化')
            expect(page.locator('#result-status')).to_have_class('badge unknown')
            expect(page.locator('#btn-open-archive')).to_be_enabled()
            expect(page.locator('#run-connection')).to_have_text('历史日志已读取完整')
            expect(page.locator('#run-console')).to_contain_text('history line 502')
            assert page.evaluate('JSON.stringify(S.job)') == job_before_history
            passed.append('recent run preserves assembly, separates historical success from overwritten current files, drains all log pages')
            with page.expect_download() as download:
                page.locator('#btn-export-log').click()
            exported = Path(download.value.path()).read_text(encoding='utf-8-sig')
            assert 'history line 0' in exported and 'history line 502' in exported
            assert '日志行数：503' in exported
            page.locator('#btn-open-archive').click()
            expect(page.locator('#hint')).not_to_contain_text('打开失败')
            passed.append('historical export includes all 503 lines and archive folder is available')
            fixture.current_files = 'missing'
            page.locator('#btn-results').click()
            expect(page.locator('#result-status')).to_contain_text('有文件缺失')
            expect(page.locator('#result-files')).to_contain_text('当前输出目录不存在')
            expect(page.locator('#btn-open-archive')).to_be_enabled()
            passed.append('missing current output keeps historical evidence and archive accessible')
            page.locator('[data-history-sid="702"]').click()
            expect(page.locator('#run-connection')).to_have_text('历史日志已读取完整')
            expect(page.locator('#run-status')).to_contain_text('未确认')
            fixture.runtime = dict(busy=True, external=True, phase='running', label='Another instance', sid=999)
            page.evaluate('refreshRuntimeState(true)')
            expect(page.locator('#btn-stop')).to_be_disabled()
            assert page.evaluate('S.sid') == 702
            fixture.runtime = dict(busy=False, phase='idle')
            page.evaluate('refreshRuntimeState()')
            passed.append('interrupted history finishes reading; another instance cannot be cancelled or replace its console')
            page.evaluate("document.querySelectorAll('.workflow-stage').forEach(x=>x.open=true)")
            for width, filename in [(1440, "workflow-desktop.png"), (390, "workflow-mobile.png"), (320, "workflow-narrow.png")]:
                page.set_viewport_size(dict(width=width, height=1000))
                page.evaluate("scrollTo(0,0)")
                page.screenshot(path=str(screenshots / filename), full_page=True)
                dimensions = page.evaluate("({width:innerWidth, scroll:document.documentElement.scrollWidth})")
                assert dimensions["scroll"] <= dimensions["width"], dimensions
                for name in ('project', 'build', 'inputs', 'assembly', 'check', 'run'):
                    toggle = page.locator('#stage-' + name + ' > summary .stage-toggle')
                    expect(toggle.locator('.stage-toggle-collapse')).to_be_visible()
                    box = toggle.bounding_box()
                    assert box['width'] >= 72 and box['height'] >= 44, box
                passed.append(f"{width}px full page screenshot; no horizontal document overflow")
            long_project = "C:/fixture/" + "LongProjectName" * 16
            page.evaluate("state => applyProjectState(state)", {**STATE, "project": long_project, "projects": [long_project]})
            for width in (900, 1440):
                page.set_viewport_size(dict(width=width, height=1000))
                label = page.locator('#current-project-name')
                expect(label).to_contain_text('LongProjectName')
                dimensions = label.evaluate("node => ({width:node.clientWidth, scroll:node.scrollWidth})")
                assert dimensions['scroll'] <= dimensions['width'], dimensions
            passed.append("long project names wrap before status and toggle at tablet and desktop widths")
            assert not errors, errors
            assert not fixture.unknown, fixture.unknown
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(json.dumps(dict(passed=passed, pageerrors=errors,
                          api_endpoints=sorted(set(name for name, _ in fixture.requests))), indent=2))


if __name__ == "__main__":
    check()
