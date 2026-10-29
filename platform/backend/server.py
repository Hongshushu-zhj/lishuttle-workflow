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
from functools import wraps
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


PROJECT_LOCK = threading.RLock()


def project_operation(fn):
    """项目切换与依赖当前项目的操作串行执行，拒绝旧页面的写入。"""
    @wraps(fn)
    def wrapped(payload):
        with PROJECT_LOCK:
            env = core.load_env()
            expected = payload.get('_project') if isinstance(payload, dict) else None
            if isinstance(expected, list):
                expected = expected[0]
            if expected and expected != env.get('PROJECT_DIR', '').replace('\\', '/'):
                return {'ok': False, 'error': '项目已切换，请刷新后重试', 'message': '项目已切换，请刷新后重试'}
            revision = payload.get('_revision') if isinstance(payload, dict) else None
            if isinstance(revision, list):
                revision = revision[0]
            if revision and str(revision) != env.get('PROJECT_PROFILE_REVISION'):
                return {'ok': False, 'error': '项目配置已变化，请刷新后重试', 'message': '项目配置已变化，请刷新后重试'}
            token = core.PROJECT_CONTEXT.set(env)
            try:
                return fn(payload)
            finally:
                core.PROJECT_CONTEXT.reset(token)
    return wrapped


class Api:
    """路由表：method + path 前缀 → 处理函数。"""

    @staticmethod
    @project_operation
    def state(_):
        store = core.ProjectStore(core.ENV_FILE)
        machine = store.setup_machine()
        # setup may persist tool discovery and invalidate the request's initial revision.
        core.PROJECT_CONTEXT.set(store.load(allow_empty=True))
        projects, current_project = core.scan_projects()
        cities, map_root = core.scan_cities()
        tasks, gongcan_root = core.scan_tasks()
        env = core.load_env()
        funcs = core.ordered_functions() if current_project else []
        return {"projects": projects, "project": current_project,
                "map_root": map_root, "cities": cities,
                "gongcan_root": gongcan_root, "tasks": tasks,
                "out_root": env.get("OUT_ROOT", ""), "preset": env.get("PRESET", ""),
                "project_config": {k: env.get(k, '') for k in core.FIELDS},
                "machine_config": {k: env.get(k, '') for k in core.MACHINE_FIELDS},
                "machine_revision": env.get('MACHINE_CONFIG_REVISION', ''),
                "machine_detection": machine,
                "build_workflow": core.describe_build(env),
                "profile_id": env.get('PROJECT_PROFILE_ID', ''),
                "profile_revision": env.get('PROJECT_PROFILE_REVISION', ''),
                "function_info": funcs,
                "functions": [f["name"] for f in funcs],
                "func_source": "来自 " + current_project + "/SwanUtility/incl/LiShuttleTypes.h"}

    @staticmethod
    @project_operation
    def select_project(body):
        path = body.get("path", "")
        result = core.add_project(path)
        if not result['ok']:
            return result
        core.save_env_keys(PROJECT_DIR=result['path'])
        return dict(Api.state(None), project_warnings=result['warnings'])

    @staticmethod
    def add_project(body):
        return Api.select_project(body)

    @staticmethod
    @project_operation
    def save_project_config(body):
        try:
            env = core.ProjectStore(core.ENV_FILE).save(body.get('values', {}),
                body.get('_revision'), project=core.load_env()['PROJECT_DIR'])
            core.PROJECT_CONTEXT.set(env)
            return Api.state(None)
        except (ValueError, OSError) as exc:
            return {'error': str(exc)}

    @staticmethod
    @project_operation
    def detect_project_config(body):
        try:
            return core.detect_project_config(core.load_env())
        except (ValueError, OSError) as exc:
            return {'error': str(exc)}

    @staticmethod
    @project_operation
    def validate_setup(body):
        issues = core.required_issues(core.load_env(), body.get('operation', 'render'))
        return {'ok': not issues, 'issues': issues}

    @staticmethod
    @project_operation
    def build_status(body):
        try:
            env = core.sync_executable(core.ProjectStore(core.ENV_FILE), core.load_env())
            core.PROJECT_CONTEXT.set(env)
            return {'build_workflow': core.describe_build(env),
                    'build_values': {key:env.get(key,'') for key in core.BUILD_FIELDS},
                    'profile_revision': env['PROJECT_PROFILE_REVISION']}
        except (ValueError, OSError) as exc:
            return {'error': str(exc)}

    @staticmethod
    @project_operation
    def save_machine_config(body):
        try:
            store = core.ProjectStore(core.ENV_FILE)
            store.save_machine(body.get('values', {}), body.get('_machine_revision'))
            return Api.state(None)
        except (ValueError, OSError) as exc:
            return {'error': str(exc)}

    @staticmethod
    @project_operation
    def detect_machine_config(body):
        try:
            store = core.ProjectStore(core.ENV_FILE)
            machine = store.setup_machine(force=True)
            return dict(Api.state(None), machine_detection=machine)
        except (ValueError, OSError) as exc:
            return {'error': str(exc)}

    @staticmethod
    def _binding_task(body):
        requested = body.get('task') or {}
        tasks, _ = core.scan_tasks()
        task = next((t for t in tasks if t['name'] == requested.get('name')
            and os.path.normcase(os.path.realpath(t['dir'])) == os.path.normcase(os.path.realpath(requested.get('dir', '')))), None)
        if task is None:
            raise ValueError('任务不存在，请重新扫描')
        engineering = body.get('engineering_file') or ''
        if engineering:
            engineering = core.validate_engineering(task, engineering)
        schema = body.get('schema_source') or ''
        if schema and schema not in [s['path'] for s in task.get('schema_candidates', [])]:
            raise ValueError('运行配置不属于当前任务，请重新选择')
        key = json.dumps([os.path.normcase(os.path.realpath(task['dir'])), engineering, schema], ensure_ascii=False)
        return task, key, engineering, schema

    @staticmethod
    @project_operation
    def task_binding(body):
        try:
            _, key, _, _ = Api._binding_task(body)
            env = core.load_env()
            binding = core.ProjectStore(core.ENV_FILE).binding(key, project=env['PROJECT_DIR'])
            return {'binding': binding}
        except (ValueError, OSError) as exc:
            return {'error': str(exc)}

    @staticmethod
    @project_operation
    def local_paths(body):
        """Return actual defaults from the same resolver used by rendering."""
        try:
            task, _, engineering, source = Api._binding_task(body)
            cities, _ = core.scan_cities()
            city = next((c for c in cities if c['name'] == body.get('city')), None)
            if not city:
                raise ValueError('请选择当前项目的地图')
            if not source:
                return {'values': {}, 'warnings': []}
            env = core.load_env()
            job = dict(JOB_NAME='local-path-preview', CITY=city['name'], SCHEMA_SOURCE=source,
                       ENGINEERING_FILE=engineering, SYNC_ENGINEERING='1')
            if task.get('scene'):
                job['SCENE_SETTINGS_FILE'] = task['scene']
            if city['kind'] == 'indoor':
                job.update(TEMPLATE='runtimeschema-indoor.xml.tpl', MAP_PATH=env['MAP_ROOT'].rstrip('/\\') + '/' + city['name'])
            _, root = core.read_runtime(source)
            values = core.local_path_values(core.build_table(env, job, require_complete=False), root, strict=False)
            values.pop('PolygonFilePath', None)
            values.pop('EngineeringFilePath', None)
            warnings = [f'{tag} 的自定义文件未在所选地图中找到，请填写本机路径' for tag, value in values.items()
                        if not value and tag in core.OUTDOOR_PATHS]
            unresolved = {}
            for tag, reason in {
                'PathlossDirectory': '当前项目未配置结果根目录 OUT_ROOT，请在顶部“项目配置”中填写。',
                'SceneSettingsPath': '未找到当前项目的场景配置，请填写 CONFIG_SRC / BUILD_SUBDIR，或指定本机场景文件。',
                'DriverTestFileDictionaryPath': '当前项目未配置路测目录 DT_ROOT；不使用路测时可留空。',
            }.items():
                if tag in values and not values[tag]:
                    unresolved[tag] = reason
            return {'values': values, 'warnings': warnings, 'unresolved': unresolved}
        except (ValueError, OSError) as exc:
            return {'error': str(exc)}

    @staticmethod
    @project_operation
    def save_task_binding(body):
        try:
            _, key, engineering, schema = Api._binding_task(body)
            cities, _ = core.scan_cities()
            city = next((c for c in cities if c['name'] == body.get('city')), None)
            if city is None:
                raise ValueError('对应地图不存在，请重新选择地图')
            if not engineering:
                raise ValueError('请明确选择工参，再保存地图对应关系')
            overrides = core.path_overrides(body.get('path_overrides', {}))
            if set(overrides) & {'EngineeringFilePath', 'PolygonFilePath'}:
                raise ValueError('工参及区域路径由上方文件选择决定')
            binding = {k: body.get(k) for k in ('polygon_file', 'sync_engineering')}
            binding.update(city=city['name'], city_kind=city['kind'], engineering_file=engineering,
                           schema_source=schema, path_overrides=overrides)
            env = core.load_env()
            core.ProjectStore(core.ENV_FILE).binding(key, binding, project=env['PROJECT_DIR'])
            return {'ok': True, 'binding': binding}
        except (ValueError, OSError) as exc:
            return {'error': str(exc)}

    @staticmethod
    @project_operation
    def set_map_root(body):
        path = body.get("path", "").replace("\\", "/")
        if not os.path.isdir(path):
            return {"error": f"目录不存在：{path}"}
        core.save_env_keys(MAP_ROOT=path)
        cities, map_root = core.scan_cities()
        return {"map_root": map_root, "cities": cities, "profile_revision": core.load_env().get('PROJECT_PROFILE_REVISION', '')}

    @staticmethod
    @project_operation
    def set_gongcan_root(body):
        path = body.get("path", "").replace("\\", "/")
        if not os.path.isdir(path):
            return {"error": f"目录不存在：{path}"}
        core.save_env_keys(GONGCAN_ROOT=path)
        tasks, gongcan_root = core.scan_tasks()
        return {"gongcan_root": gongcan_root, "tasks": tasks, "profile_revision": core.load_env().get('PROJECT_PROFILE_REVISION', '')}

    @staticmethod
    @project_operation
    def render(body):
        """装配并渲染：写 web-*.env → 调渲染脚本 → 可选复制共用文件。"""
        env = core.load_env()
        if env.get('PROJECT_PROFILE_ID'):
            issues = core.required_issues(env, 'render')
            if issues:
                return {'error': issues[0]['message'], 'issues': issues}
        job_name = body.get("job_name") or ""
        func = body.get("func") or "pl"
        task_id = str(body.get("task_id", "1"))
        task = body.get("task")
        city_name = body.get("city") or ""
        city_kind = body.get("city_kind") or "outdoor"
        copy_files = bool(body.get("copy_files"))
        copy_antennas = bool(body.get('copy_antennas', copy_files and not body.get('use_existing_schema')))

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
        # 不信任客户端缓存的 CSV 列表：按当前配置重新扫描并校验明确选择。
        tasks, _ = core.scan_tasks()
        current = next((t for t in tasks if t['name'] == task.get('name')
                        and os.path.normcase(os.path.realpath(t['dir']))
                        == os.path.normcase(os.path.realpath(task.get('dir', '')))), None)
        if current is None:
            return {"error": "任务已不存在，请重新扫描并选择"}
        try:
            reuse = bool(body.get('use_existing_schema'))
            selected = (core.validate_engineering(current, body.get('engineering_file'))
                        if not reuse or body.get('sync_engineering') or body.get('engineering_file') else '')
        except ValueError as exc:
            return {"error": str(exc)}

        current['engineering_file'] = selected
        task = current
        copy_antennas = copy_antennas and bool(task.get('has_antennas'))
        preview = None
        if reuse:
            try:
                preview = core.preview_task_schema(body, task, city_kind)
            except ValueError as exc:
                return {'error': str(exc)}
            if body.get('preview_only'):
                return preview
            if body.get('preview_token') != preview['token']:
                return {'error': '配置或路径选择已变化，请重新预览后确认装配'}
        try:
            base_resources = core.ensure_runtime_resources(core.load_env())
        except (OSError, ValueError) as exc:
            return {'error': f'基础运行资源装配失败：{exc}'}
        job_file = core.build_job_env(job_name, func, task_id, task,
                                      city_name, city_kind)
        rc, output = core.run_render(job_file)
        result = {"job_file": job_file, "render_exit": rc, "render_output": output,
                  "schema_name": f"{job_name}.xml", "func": func, "task_id": task_id,
                  "copied": [], "base_resources": base_resources}
        if preview:
            result.update(runtime_name=preview['runtime_name'], out_dir=preview['out_dir'],
                          path_changes=preview['changes'], warnings=preview['warnings'])
        schema_path = core.schema_path(result["schema_name"])
        result["schema_ok"] = os.path.isfile(schema_path)
        groups = tuple(key for key, enabled in (
            ('antenna', copy_antennas), ('model', copy_files and not reuse)) if enabled)
        if groups and task and result['schema_ok']:
            result["copied"] = core.assemble_files(task, core.load_env(), groups=groups)
        if rc == 0 and result['schema_ok']:
            try:
                previous = body.get('previous_schema', '')
                if previous and (os.path.basename(previous) != previous or not previous.endswith('.xml')):
                    raise ValueError('上次运行配置文件名无效')
                args = (core.load_env(), result['schema_name'], func, task_id, city_kind)
                result['vs_launch'] = (core.sync_vs_launch(*args, previous_schema=previous)
                                       if previous else core.sync_vs_launch(*args))
            except (OSError, ValueError) as exc:
                result['vs_launch_warning'] = f'Visual Studio 启动项未同步：{exc}；请检查 .vs/launch.vs.json'
        if result['schema_ok']:
            details = core.runtime_details(schema_path, os.path.dirname(os.path.dirname(schema_path)))
            result.update(runtime_name=details['name'], out_dir=details['out_dir'])
        return result

    @staticmethod
    def preview_render(body):
        return Api.render(dict(body, use_existing_schema=True, preview_only=True))

    @staticmethod
    @project_operation
    def cleanup_configs(body):
        from runtime_cleanup import cleanup_plan, apply_cleanup
        with core.RUNNER.lock:
            if any(s.get('status') == 'running' for s in core.RUNNER.sessions.values()):
                return {'error': '平台仍有运行或编译进程，请结束后再清理'}
        try:
            plan = cleanup_plan(core.load_env(), core.JOBS_DIR, core.ROOT, body.get('keep_schema', ''))
            if body.get('apply'):
                if body.get('token') != plan['token']:
                    return {'error': '配置文件已变化，请重新预览清理范围'}
                return apply_cleanup(plan, os.path.join(core.ROOT, 'docs', 'runtime-config-archives'))
            return {key: value for key, value in plan.items() if not key.startswith('_')}
        except (ValueError, OSError, KeyError) as exc:
            return {'error': f'配置清理未执行：{exc}'}

    @staticmethod
    @project_operation
    def params(query):
        schema = query.get("schema", [""])[0]
        func = query.get("func", [""])[0]
        show_all = query.get("all", ["1"])[0] == "1"
        try:
            path, document = core.read_schema_document(schema)
        except (ValueError, OSError) as exc:
            return {'error':str(exc)}
        if document is None:
            return {"error": f"读不到运行单 {schema}，先渲染一次"}
        catalog = core.build_catalog(document, core.load_spec(), func, show_all)
        if catalog['profile'].get('reviewed'):
            from function_profiles import source_review
            catalog['profile']['source_review'] = source_review(func, core.load_env().get('PROJECT_DIR', ''))
        return {**catalog, "file": path, "schema_name": document['name'], "values": document['values'],
                "param_sources": {'DefaultCalcRadius': core.radius_source(schema)},
                "thirdpart_defaults": core.thirdpart_defaults()}

    @staticmethod
    @project_operation
    def param_default(body):
        tag = body.get('tag', '')
        if tag == 'DefaultCalcRadius':
            return {'ok': False, 'message': '小区计算半径以 CSV 为准，请修改工参半径；XML 仅提供默认值'}
        default = core.thirdpart_defaults().get(tag)
        if not default or not default['available']:
            return {'ok': False, 'message': (default or {}).get('reason', '当前项目样例没有此参数的默认值')}
        ok, msg = core.write_schema_param(body.get('schema', ''), tag, default['value'])
        return dict(ok=ok, message=msg, value=default['value'], source=default['source'])

    @staticmethod
    @project_operation
    def param_write(body):
        schema = body.get("schema", "")
        tag = body.get("tag", "")
        value = str(body.get("value", ""))
        try:
            ok, msg = core.write_schema_param(schema, tag, value)
            values = core.read_schema(schema)[1]
        except (ValueError, OSError) as exc:
            ok, msg, values = False, str(exc), {}
        return {"ok": ok, "message": msg, "values": values,
                "target": 'engineering_csv' if tag == 'DefaultCalcRadius' else 'schema'}

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
    @project_operation
    def run(body):
        schema = body.get("schema", "")
        func = body.get("func", "pl")
        task_id = str(body.get("task_id", "1"))
        sid, exe = core.start_lishuttle(schema, func, task_id)
        if sid is None:
            return {"error": exe}
        return {"sid": sid, "exe": exe}

    @staticmethod
    @project_operation
    def toolkit(body):
        if body.get('step') == 'build':
            try:
                env = core.load_env()
                values = core.prepare_build(env, body.get('preset') or env.get('PRESET',''))
                issues = core.required_issues(dict(env, **values), 'build')
                if issues:
                    return {'error': issues[0]['message'], 'issues': issues}
                if any(env.get(key, '') != value for key,value in values.items()):
                    env = core.ProjectStore(core.ENV_FILE).save(values, env.get('PROJECT_PROFILE_REVISION'), env['PROJECT_DIR'])
                core.PROJECT_CONTEXT.set(env)
                sid, bat = core.start_toolkit('build')
                if sid is None:
                    return {'error': bat}
                return {'sid':sid, 'bat':bat, 'build_values':values,
                        'profile_revision':env.get('PROJECT_PROFILE_REVISION'), 'build_workflow':core.describe_build(env)}
            except (ValueError, OSError) as exc:
                return {'error':str(exc), 'issues':[{'key':'PRESET','target':'build-mode','section':'build','message':str(exc)}]}
        sid, bat = core.start_toolkit(body.get("step", "doctor"))
        if sid is None:
            return {'error': bat}
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
    @project_operation
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
    ("POST", "add_project"): Api.add_project,
    ("POST", "save_project_config"): Api.save_project_config,
    ("POST", "detect_project_config"): Api.detect_project_config,
    ("POST", "validate_setup"): Api.validate_setup,
    ("POST", "build_status"): Api.build_status,
    ("POST", "save_machine_config"): Api.save_machine_config,
    ("POST", "detect_machine_config"): Api.detect_machine_config,
    ("POST", "task_binding"): Api.task_binding,
    ("POST", "local_paths"): Api.local_paths,
    ("POST", "save_task_binding"): Api.save_task_binding,
    ("POST", "set_map_root"): Api.set_map_root,
    ("POST", "set_gongcan_root"): Api.set_gongcan_root,
    ("POST", "render"): Api.render,
    ("POST", "preview_render"): Api.preview_render,
    ("POST", "cleanup_configs"): Api.cleanup_configs,
    ("GET", "params"): Api.params,
    ("POST", "param_write"): Api.param_write,
    ("POST", "param_default"): Api.param_default,
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
