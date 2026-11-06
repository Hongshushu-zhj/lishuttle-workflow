"""Optional isolated browser QA: python tests/workflow_browser_check.py.

Requires locally installed Playwright and Chrome/Edge; installs nothing. The
temporary HTTP server serves only frontend assets and in-memory API fixtures.
No application server, project configuration, XML, CSV or engine is touched.
"""
from __future__ import annotations

import json
import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
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
        self.unknown = []

    def reply(self, endpoint, body):
        self.requests.append((endpoint, body))
        if endpoint == "state":
            return STATE
        if endpoint == "runtime_state":
            return self.runtime
        if endpoint == "detect_project_config":
            return dict(values={}, presets=BUILD["presets"], warnings=[])
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
            return dict(schema_ok=True, render_exit=0, schema_name="source-job.xml",
                        runtime_name="source-job", func=body["func"], task_id=body["task_id"],
                        out_dir="C:/fixture/outputs/source-job", render_output="Fixture assembly complete", copied=[])
        if endpoint == "params":
            return dict(function="pred", file="C:/fixture/project/Bin/source-job.xml", values={"CalcRadius": self.radius},
                        groups=[dict(group="Prediction", rows=[dict(name="CalcRadius", label="计算半径", type="float",
                            desc="Fixture editable parameter", recommended=True, classification="current")])])
        if endpoint == "preflight":
            return dict(ok=True, issues=[], context=dict(mode=dict(requested="ground", effective="ground")))
        if endpoint == "param_write":
            if self.fail_parameter_once:
                return dict(ok=False, error="Fixture parameter save failed")
            self.radius = body["value"]
            return dict(ok=True, target="xml")
        if endpoint == "csv":
            return dict(path=TASK["engineering_file"], encoding="utf-8", header_zh=["编号"],
                        header_en=["CellID"], rows=[["1"]])
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
            page.locator('input[name="func"][value="commsensing"]').check()
            expect(page.locator("#assembly-summary")).to_contain_text("请重新装配")
            expect(page.locator("#btn-run")).to_be_disabled()
            passed.append("function change marks prior assembly stale and blocks run")
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
