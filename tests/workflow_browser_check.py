"""Optional isolated browser QA: python tests/workflow_browser_check.py.

Requires locally installed Playwright and Chrome/Edge; installs nothing. The
temporary HTTP server serves only frontend assets and in-memory API fixtures.
No application server, project configuration, XML, CSV or engine is touched.
"""
from __future__ import annotations

import json
import hashlib
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
from parameter_catalog import parse_document, build_catalog, replace_scalar
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
PROJECT_B = 'C:/fixture/project-B'
EXTERNAL_XML = 'C:/fixture/external/original.xml'


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
        self.project = STATE['project']
        self.runtime_xml = {}
        self.runtime_selected = {}
        for project, name, depth in ((STATE['project'], 'actual-A', '3'), (PROJECT_B, 'actual-B', '8')):
            raw = ('\ufeff<RuntimeSchema name="' + name + '">\r\n<!-- preserve existing -->\r\n'
                '<MapFormat>indoor</MapFormat><EngineeringFilePath>C:/fixture/external-' + name + '/ap.csv</EngineeringFilePath>'
                '<PathlossDirectory>C:/fixture/custom-output</PathlossDirectory><MaxDeepth>' + depth + '</MaxDeepth>'
                '<Unknown>keep exact bytes</Unknown>\r\n</RuntimeSchema>\r\n').encode('utf-8')
            self.runtime_xml[project] = {'saved.xml': raw}
            self.runtime_selected[project] = None
        self.external_xml = self.runtime_xml[STATE['project']]['saved.xml'].replace(b'actual-A', b'external-root')

    def state(self):
        return dict(STATE, project=self.project, projects=[STATE['project'], PROJECT_B],
                    profile_id='fixture-A' if self.project == STATE['project'] else 'fixture-B', runtime=self.runtime)

    def runtime_description(self, schema, raw=None):
        raw = self.runtime_xml[self.project][schema] if raw is None else raw
        document = parse_document(raw)
        values = document['values']
        return dict(schema=schema, runtime_name=document['name'], scene='indoor', loadable=True,
            revision=hashlib.sha256(raw).hexdigest(), modified='2026-11-10T01:00:00+00:00',
            file=self.project + '/build/release/Bin/runtimelibrary/' + schema,
            engineering_file=values['EngineeringFilePath'],
            out_dir=values['PathlossDirectory'] + '/' + document['name'])

    def runtime_scope(self):
        return 'scope-A' if self.project == STATE['project'] else 'scope-B'

    def activate_runtime(self, body):
        description = self.runtime_description(body['schema'])
        if body.get('scope') != self.runtime_scope() or body.get('revision') != description['revision']:
            return dict(ok=False, code='FILE_CONFLICT', error='Fixture current XML changed; refresh the list')
        self.runtime_selected[self.project] = dict(schema=body['schema'], revision=description['revision'],
            func=body['func'], task_id=str(body['task_id']))
        return dict(ok=True, job=dict(schema=body['schema'], name=description['runtime_name'],
            func=body['func'], taskId=str(body['task_id']), outDir=description['out_dir'], mode='existing'),
            revision=description['revision'], inputs=dict(engineering_file=description['engineering_file'], reason=''),
            validation_required=True)

    def import_preview(self, body):
        assert body['source'] == EXTERNAL_XML, body
        description = self.runtime_description(body['destination_schema'], self.external_xml)
        conflict = body['destination_schema'] in self.runtime_xml[self.project]
        token = hashlib.sha256((self.project + body['source'] + body['destination_schema'] +
                               description['revision'] + str(conflict)).encode()).hexdigest()
        return dict(source=body['source'], destination=description['file'], description=description,
            runtime_name=description['runtime_name'], out_dir=description['out_dir'], scope=self.runtime_scope(),
            conflict=conflict, same_file=False, token=token, warnings=[])

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
            return self.state()
        if endpoint == 'select_project':
            assert body['path'] in self.runtime_xml, body
            self.project = body['path']
            return self.state()
        if endpoint == 'runtime_configs':
            return dict(directory=self.project + '/build/release/Bin/runtimelibrary', scope=self.runtime_scope(),
                configs=[self.runtime_description(schema) for schema in self.runtime_xml[self.project]],
                selected=self.runtime_selected[self.project])
        if endpoint == 'activate_runtime_config':
            return self.activate_runtime(body)
        if endpoint == 'preview_runtime_import':
            return self.import_preview(body)
        if endpoint == 'import_runtime_config':
            preview = self.import_preview(body)
            if preview['token'] != body['token'] or preview['conflict']:
                return dict(ok=False, code='FILE_CONFLICT', error='Fixture import preview changed; preview again')
            self.runtime_xml[self.project][body['destination_schema']] = self.external_xml
            return dict(self.activate_runtime(dict(body, schema=body['destination_schema'],
                revision=preview['description']['revision'])), imported=True)
        if endpoint == "runtime_state":
            return self.runtime
        if endpoint == 'history':
            runs = [dict(self.historical_result(sid), created_at='2026-11-09T01:00:00+00:00',
                         result=dict(verdict='success' if sid == 701 else 'unconfirmed')) for sid in (701, 702)]
            return dict(runs=runs, total=2, limit=10, offset=0)
        if endpoint == 'results':
            if body.get('schema'):
                description = self.runtime_description(body['schema'][0])
                return dict(dir=description['out_dir'], exists=True, associated=False, verdict='unconfirmed',
                            files=[dict(rel='fixture.dem', size=8)], log_tail=[], errors=[])
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
            schema = body.get('schema', [''])[0]
            if schema in self.runtime_xml[self.project]:
                description = self.runtime_description(schema)
                document = parse_document(self.runtime_xml[self.project][schema])
                return dict(build_catalog(document, PARAM_SPEC, function), values=document['values'],
                    file=description['file'], schema_name=description['runtime_name'], revision=description['revision'],
                    inputs=dict(engineering_file=description['engineering_file'], reason=''))
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
            schema = body.get('schema', '')
            if schema in self.runtime_xml[self.project]:
                description = self.runtime_description(schema)
                if body.get('revision') != description['revision']:
                    return dict(ok=False, code='FILE_CONFLICT', error='Fixture XML conflict: 文件已变化，草稿已保留')
                self.runtime_xml[self.project][schema] = replace_scalar(self.runtime_xml[self.project][schema], body['tag'], body['value'])
                return dict(ok=True, target='schema', revision=self.runtime_description(schema)['revision'])
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
            return dict(self.csv_grid(), path=body.get('path', [TASK['engineering_file']])[0])
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


def check_existing_runtime(page, fixture, passed):
    def settled():
        page.wait_for_function('!S.inputTransition && !S.runtimeActivationPending && !S.runtimeExecutionPending && !S.pendingRequests && !S.parameterWrites')

    existing_before = dict(fixture.runtime_xml[STATE['project']])
    other_before = dict(fixture.runtime_xml[PROJECT_B])
    renders = fixture.render_count
    expect(page.locator('#runtime-config-mode')).to_have_value('existing')
    expect(page.locator('#runtime-config-select option')).to_have_count(2)
    page.locator('input[name="func"][value="predindoor"]').check()
    page.locator('#task-id').fill('7')
    page.locator('#task-id').press('Tab')
    page.locator('#runtime-config-select').select_option('saved.xml')
    page.locator('#btn-runtime-config-use').click()
    depth = page.locator('#params-area input[data-tag="MaxDeepth"]')
    expect(depth).to_have_value('3')
    settled()
    expect(page.locator('#job-name')).to_have_value('actual-A')
    expect(page.locator('#job-name')).to_have_attribute('readonly', '')
    expect(page.locator('#csv-path')).to_have_value('C:/fixture/external-actual-A/ap.csv')
    expect(page.locator('#btn-preflight')).to_be_enabled()
    expect(page.locator('#btn-render')).to_be_disabled()
    expect(page.locator('#btn-run')).to_be_disabled()
    assert fixture.runtime_xml[STATE['project']] == existing_before
    assert page.evaluate('S.job.schema') == 'saved.xml'
    passed.append('existing XML loads byte-preserving parameters and actual CSV without a task package or assembly')

    page.locator('#csv-editor summary').click()
    page.locator('#btn-csv-load').click()
    expect(page.locator('#csv-wrap td[contenteditable]')).to_have_count(2)
    csv_request = [body for endpoint, body in fixture.requests if endpoint == 'csv'][-1]
    assert csv_request['path'] == ['C:/fixture/external-actual-A/ap.csv'], csv_request
    page.locator('#csv-wrap td[contenteditable]').first.fill('existing-draft')
    page.locator('#project').select_option(PROJECT_B)
    expect(page.locator('#project')).to_have_value(STATE['project'])
    expect(page.locator('#csv-wrap td[contenteditable]').first).to_have_text('existing-draft')
    page.locator('#btn-csv-discard').click()
    expect(page.locator('#csv-wrap td[contenteditable]').first).to_have_text('1')
    passed.append('existing XML CSV comes from its actual path and an unsaved CSV blocks project switching')

    depth.fill('4')
    depth.press('Tab')
    expect(page.locator('#hint')).to_contain_text('MaxDeepth 已写入')
    settled()
    saved_a = fixture.runtime_xml[STATE['project']]['saved.xml']
    assert parse_document(saved_a)['values']['MaxDeepth'] == '4'
    assert b'<!-- preserve existing -->' in saved_a and b'<Unknown>keep exact bytes</Unknown>' in saved_a
    page.locator('#btn-preflight').click()
    expect(page.locator('#btn-run')).to_be_enabled()
    page.locator('#project').select_option(PROJECT_B)
    expect(page.locator('#current-project-path')).to_have_text(PROJECT_B)
    settled()
    assert page.evaluate('S.job === null && S.sid === 0 && S.runVerdict === null')
    page.locator('#runtime-config-select').select_option('saved.xml')
    page.locator('#btn-runtime-config-use').click()
    expect(page.locator('#job-name')).to_have_value('actual-B')
    expect(page.locator('#csv-path')).to_have_value('C:/fixture/external-actual-B/ap.csv')
    settled()
    page.locator('#project').select_option(STATE['project'])
    expect(page.locator('#job-name')).to_have_value('actual-A')
    expect(page.locator('#params-area input[data-tag="MaxDeepth"]')).to_have_value('4')
    settled()
    expect(page.locator('#btn-run')).to_be_disabled()
    assert page.evaluate('S.sid === 0 && S.runVerdict === null && !S.workflow.preflight')
    assert fixture.runtime_xml[STATE['project']]['saved.xml'] == saved_a
    assert fixture.runtime_xml[PROJECT_B] == other_before
    page.reload(wait_until='networkidle')
    expect(page.locator('#params-area input[data-tag="MaxDeepth"]')).to_have_value('4')
    expect(page.locator('#task-id')).to_have_value('7')
    settled()
    expect(page.locator('#btn-run')).to_be_disabled()
    assert page.evaluate('S.job.schema === "saved.xml" && S.job.name === "actual-A" && S.sid === 0 && !S.workflow.preflight')
    page.evaluate("document.querySelectorAll('.workflow-stage').forEach(stage => stage.open = true)")
    page.screenshot(path=str(ROOT / 'docs/superpowers/screenshots/workflow-runtime-config.png'), full_page=True)
    passed.append('A to B to A and page reload restore the saved parameter with project isolation and fresh preflight required')

    page.locator('#btn-preflight').click()
    expect(page.locator('#btn-run')).to_be_enabled()
    page.locator('input[name="func"][value="pred"]').check()
    settled()
    page.locator('#task-id').fill('8')
    page.locator('#task-id').press('Tab')
    settled()
    expect(page.locator('#assembly-summary')).to_contain_text('已加载')
    expect(page.locator('#btn-preflight')).to_be_enabled()
    expect(page.locator('#btn-run')).to_be_disabled()
    assert page.evaluate('S.job.func === "pred" && S.job.taskId === "8" && S.job.name === "actual-A"')
    assert fixture.runtime_selected[STATE['project']]['task_id'] == '8'
    page.locator('#btn-preflight').click()
    expect(page.locator('#btn-run')).to_be_enabled()
    assert fixture.render_count == renders
    passed.append('function and task ID changes persist, retain loaded XML and need only preflight')

    page.locator('#btn-results').click()
    expect(page.locator('#result-files')).to_contain_text('fixture.dem')
    directory_request = [body for endpoint, body in fixture.requests if endpoint == 'results'][-1]
    assert directory_request.get('schema') == ['saved.xml'] and 'job' not in directory_request, directory_request
    assert page.evaluate('lastResultsDir') == 'C:/fixture/custom-output/actual-A'
    expect(page.locator('#result-status')).not_to_have_class('badge ok')
    passed.append('directory browsing uses the real schema filename and XML output/name without restoring a success verdict')

    page.locator('#runtime-config-mode').select_option('import')
    page.locator('#runtime-import-source').fill(EXTERNAL_XML)
    page.locator('#runtime-import-name').fill('saved.xml')
    page.locator('#btn-runtime-import-preview').click()
    expect(page.locator('#runtime-import-preview-text')).to_contain_text('已存在')
    expect(page.locator('#btn-runtime-import-apply')).to_be_disabled()
    expect(page.locator('#btn-runtime-import-existing')).to_be_enabled()
    page.locator('#runtime-import-name').fill('imported.xml')
    expect(page.locator('#runtime-import-preview')).to_be_hidden()
    expect(page.locator('#btn-runtime-import-apply')).to_be_disabled()
    page.locator('#btn-runtime-import-preview').click()
    expect(page.locator('#btn-runtime-import-apply')).to_be_enabled()
    fixture.external_xml = fixture.external_xml.replace(b'keep exact bytes', b'externally changed bytes')
    source_before = fixture.external_xml
    page.locator('#btn-runtime-import-apply').click()
    expect(page.locator('#hint')).to_contain_text('Fixture import preview changed')
    assert 'imported.xml' not in fixture.runtime_xml[STATE['project']]
    expect(page.locator('#runtime-import-source')).to_have_value(EXTERNAL_XML)
    expect(page.locator('#runtime-import-name')).to_have_value('imported.xml')
    settled()
    page.locator('#btn-runtime-import-preview').click()
    expect(page.locator('#btn-runtime-import-apply')).to_be_enabled()
    page.locator('#btn-runtime-import-apply').click()
    expect(page.locator('#runtime-config-mode')).to_have_value('existing')
    expect(page.locator('#runtime-config-select')).to_have_value('imported.xml')
    expect(page.locator('#job-name')).to_have_value('external-root')
    settled()
    assert fixture.external_xml == source_before
    assert fixture.runtime_xml[STATE['project']]['imported.xml'] == source_before
    assert fixture.runtime_xml[STATE['project']]['saved.xml'] == saved_a
    assert fixture.render_count == renders
    assert not any(endpoint == 'run' for endpoint, _ in fixture.requests)
    passed.append('import refuses same-name files, invalidates edited previews, rejects changed sources and copies bytes without changing the source')


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
            check_existing_runtime(page, fixture, passed)
            page.locator('#runtime-config-mode').select_option('new')
            page.locator('input[name="func"][value="pred"]').check()
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
