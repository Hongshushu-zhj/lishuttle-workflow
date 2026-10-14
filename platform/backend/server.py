#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
lishuttle 本地平台 Web 服务。

启动：
    双击工作流根目录的 启动平台.bat
    或：python platform/backend/server.py       # 启动并自动打开浏览器
        python platform/backend/server.py --port 9000

纯 Python 标准库实现，无第三方依赖。
接口全部是 /api/* 的 JSON；页面在 / 。
"""

import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))      # platform/backend
PLATFORM = os.path.dirname(HERE)                       # platform/
ROOT = os.path.dirname(PLATFORM)                       # 工作流根目录
sys.path.insert(0, HERE)

import core  # noqa: E402

STATIC = os.path.join(PLATFORM, "frontend")
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".png": "image/png", ".svg": "image/svg+xml"}


class Api:
    """路由表：method + path 前缀 → 处理函数。"""

    @staticmethod
    def state(_):
        projects, current_project = core.scan_projects()
        cities, map_root = core.scan_cities()
        tasks, gongcan_root = core.scan_tasks()
        env = core.load_env()
        funcs = core.ordered_functions()      # 按当前项目源码实际支持的功能
        return {"projects": projects, "project": current_project,
                "map_root": map_root, "cities": cities,
                "gongcan_root": gongcan_root, "tasks": tasks,
                "out_root": env.get("OUT_ROOT", ""), "preset": env.get("PRESET", ""),
                "function_info": funcs,
                "functions": [f["name"] for f in funcs],
                "func_source": "来自 " + current_project + "/SwanUtility/incl/LiShuttleTypes.h"}

    @staticmethod
    def select_project(body):
        path = body.get("path", "")
        if not os.path.isfile(os.path.join(path, "CMakePresets.json")):
            return {"error": f"{path} 不是有效的项目目录（缺 CMakePresets.json）"}
        core.save_env_keys(PROJECT_DIR=path.replace("\\", "/"))
        return Api.state(None)

    @staticmethod
    def set_map_root(body):
        path = body.get("path", "").replace("\\", "/")
        if not os.path.isdir(path):
            return {"error": f"目录不存在：{path}"}
        core.save_env_keys(MAP_ROOT=path)
        cities, map_root = core.scan_cities()
        return {"map_root": map_root, "cities": cities}

    @staticmethod
    def set_gongcan_root(body):
        path = body.get("path", "").replace("\\", "/")
        if not os.path.isdir(path):
            return {"error": f"目录不存在：{path}"}
        core.save_env_keys(GONGCAN_ROOT=path)
        tasks, gongcan_root = core.scan_tasks()
        return {"gongcan_root": gongcan_root, "tasks": tasks}

    @staticmethod
    def render(body):
        """装配并渲染：写 web-*.env → 调渲染脚本 → 可选复制共用文件。"""
        job_name = body.get("job_name") or ""
        func = body.get("func") or "pl"
        task_id = str(body.get("task_id", "1"))
        task = body.get("task")
        city_name = body.get("city") or ""
        city_kind = body.get("city_kind") or "outdoor"
        max_height = str(body.get("max_calc_height") or "3")
        floor_height = str(body.get("floor_height") or "3")
        copy_files = bool(body.get("copy_files"))

        if not job_name or not job_name.replace("-", "").replace("_", "").isalnum():
            return {"error": "任务名只能用字母数字、-、_"}
        if func in ("plindoor", "predindoor", "indoorrays") or city_kind == "indoor":
            city_kind = "indoor"
        # 室内覆盖预测是独立功能 indoorpred（用户确认），pred 只做室外
        if city_kind == "indoor" and func == "pl":
            func = "plindoor"
        elif city_kind == "indoor" and func == "pred":
            func = "predindoor"

        if not task:
            return {"error": "未选择工参任务"}
        job_file = core.build_job_env(job_name, func, task_id, task,
                                      city_name, city_kind, max_height, floor_height)
        rc, output = core.run_render(job_file)
        result = {"job_file": job_file, "render_exit": rc, "render_output": output,
                  "schema_name": f"{job_name}.xml", "func": func, "task_id": task_id,
                  "copied": []}
        schema_path = core.schema_path(result["schema_name"])
        result["schema_ok"] = os.path.isfile(schema_path)
        if copy_files and task:
            result["copied"] = core.assemble_files(task, core.load_env())
        return result

    @staticmethod
    def params(query):
        schema = query.get("schema", [""])[0]
        func = query.get("func", [""])[0]
        show_all = query.get("all", ["0"])[0] == "1"
        path, values, name = core.read_schema(schema)
        if not values:
            return {"error": f"读不到运行单 {schema}，先渲染一次"}
        spec = core.load_spec()
        groups = spec["groups"]
        rows_by_name = {p["name"]: p for p in spec["params"]}

        def func_match(p):
            f = p.get("func", "")
            return (not f) or (func in f.split(","))

        is_indoor = "MapPath" in values or values.get("MapFormat", "").lower() == "indoor"

        def applies_match(p):
            ap = p.get("applies", "both")
            return ap == "both" or ap == ("indoor" if is_indoor else "outdoor")

        out_groups = []
        seen = set()
        for g in groups:
            rows = []
            for p in spec["params"]:
                if p["group"] != g or not func_match(p) or not applies_match(p):
                    continue
                rows.append(p)
                seen.add(p["name"])
            if rows:
                out_groups.append({"group": g, "rows": rows})
        if show_all:
            extra = [{"name": k, "label": k, "group": "高级(字典未收录)", "type": "text",
                      "applies": "both", "desc": "运行单里有、参数字典未收录的字段"}
                     for k in values if k not in seen]
            if extra:
                out_groups.append({"group": "高级(字典未收录)", "rows": extra})
        return {"file": path, "schema_name": name, "values": values, "groups": out_groups}

    @staticmethod
    def param_write(body):
        schema = body.get("schema", "")
        tag = body.get("tag", "")
        value = str(body.get("value", ""))
        ok, msg = core.write_schema_param(schema, tag, value)
        return {"ok": ok, "message": msg, "values": core.read_schema(schema)[1]}

    @staticmethod
    def csv_get(query):
        return core.read_csv_grid(query.get("path", [""])[0])

    @staticmethod
    def csv_save(body):
        ok, msg = core.save_csv_grid(body["path"], body["header_zh"],
                                     body["header_en"], body["rows"])
        return {"ok": ok, "message": msg}

    @staticmethod
    def csv_column(body):
        ok, msg = core.set_csv_column(body["path"], body["column"], body["value"])
        return {"ok": ok, "message": msg}

    @staticmethod
    def run(body):
        schema = body.get("schema", "")
        func = body.get("func", "pl")
        task_id = str(body.get("task_id", "1"))
        sid, exe = core.start_lishuttle(schema, func, task_id)
        if sid is None:
            return {"error": exe}
        return {"sid": sid, "exe": exe}

    @staticmethod
    def toolkit(body):
        sid, bat = core.start_toolkit(body.get("step", "doctor"))
        return {"sid": sid, "bat": bat}

    @staticmethod
    def output(query):
        sid = int(query.get("sid", ["0"])[0])
        since = int(query.get("since", ["0"])[0])
        return core.RUNNER.output(sid, since)

    @staticmethod
    def stop(body):
        return {"stopped": core.RUNNER.stop(int(body.get("sid", "0")))}

    @staticmethod
    def results(query):
        return core.results(query.get("job", [""])[0])

    @staticmethod
    def open_folder(body):
        path = body.get("path", "")
        if os.path.isdir(path) and sys.platform == "win32":
            os.startfile(path)  # noqa: S606
            return {"ok": True}
        return {"error": f"目录不存在：{path}"}


ROUTES = {
    ("GET", "state"): Api.state,
    ("POST", "select_project"): Api.select_project,
    ("POST", "set_map_root"): Api.set_map_root,
    ("POST", "set_gongcan_root"): Api.set_gongcan_root,
    ("POST", "render"): Api.render,
    ("GET", "params"): Api.params,
    ("POST", "param_write"): Api.param_write,
    ("GET", "csv"): Api.csv_get,
    ("POST", "csv_save"): Api.csv_save,
    ("POST", "csv_column"): Api.csv_column,
    ("POST", "run"): Api.run,
    ("POST", "toolkit"): Api.toolkit,
    ("GET", "output"): Api.output,
    ("POST", "stop"): Api.stop,
    ("GET", "results"): Api.results,
    ("POST", "open_folder"): Api.open_folder,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 安静模式
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            name = parsed.path[len("/api/"):]
            fn = ROUTES.get(("GET", name))
            if not fn:
                return self._json({"error": f"未知接口 GET {name}"}, 404)
            try:
                return self._json(fn(parse_qs(parsed.query)))
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        # 静态文件
        rel = parsed.path.strip("/") or "index.html"
        full = os.path.join(STATIC, rel)
        if not os.path.abspath(full).startswith(os.path.abspath(STATIC)) \
                or not os.path.isfile(full):
            return self._json({"error": "not found"}, 404)
        data = open(full, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(os.path.splitext(full)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)
        name = parsed.path[len("/api/"):]
        fn = ROUTES.get(("POST", name))
        if not fn:
            return self._json({"error": f"未知接口 POST {name}"}, 404)
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "请求体不是合法 JSON"}, 400)
        try:
            return self._json(fn(body))
        except Exception as exc:  # noqa: BLE001
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


def main():
    port = 8641
    args = sys.argv[1:]
    if "--port" in args:
        port = int(args[args.index("--port") + 1])
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"lishuttle 本地平台已启动: {url}  (Ctrl+C 停止)")
    if "--no-browser" not in args:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
