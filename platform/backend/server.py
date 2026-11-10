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
import re
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
from run_guard import RuntimeBusy

STATIC = os.path.join(PLATFORM, "frontend")
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".png": "image/png", ".svg": "image/svg+xml"}


PROJECT_LOCK = threading.RLock()


def runtime_operation(fn):
    """Reserve before any project/config read that might persist a migration."""
    @wraps(fn)
    def wrapped(payload):
        try:
            labels = {'run':'运行', 'toolkit':'工具任务', 'render':'装配', 'select_project':'切换项目',
                      'csv_save':'保存工参', 'csv_column':'修改工参', 'param_write':'修改参数',
                      'param_default':'恢复参数', 'cleanup_configs':'清理配置',
                      'enable_indoor_building_export':'启用室内建筑导出',
                      'activate_runtime_config':'选择已有运行配置', 'import_runtime_config':'导入运行配置'}
            label = labels.get(fn.__name__, '更新配置')
            if fn.__name__ == 'toolkit' and isinstance(payload, dict):
                label = {'build':'编译','stage':'装配','doctor':'体检'}.get(payload.get('step'), label)
            with core.RUNTIME.operation(label) as token:
                source_write = fn.__name__ == 'enable_indoor_building_export' or (
                    fn.__name__ == 'toolkit' and isinstance(payload, dict) and payload.get('step') == 'build')
                core.RUNTIME.acquire_resources(token, core.runtime_resources(core.load_env(), source=source_write))
                return fn(payload)
        except RuntimeBusy as exc:
            return exc.response()
    return wrapped


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


def revision_required(body, *fields):
    if any(not isinstance(body.get(field), str) or not body[field] for field in fields):
        message = '缺少文件内容版本，请重新加载后保存；当前草稿已保留'
        return dict(ok=False, code='REVISION_REQUIRED', error=message, message=message)
    return None


def editor_error(error):
    conflict = isinstance(error, core.FileConflict)
    message = ('文件已变化，请重新加载后保存；当前草稿已保留。' if conflict else '保存未完成，当前草稿已保留。') + str(error)
    return dict(ok=False, code='FILE_CONFLICT' if conflict else 'SAVE_FAILED', error=message, message=message)


class Api:
    """路由表：method + path 前缀 → 处理函数。"""

    @staticmethod
    @project_operation
    def runtime_configs(_):
        from runtime_configs import list_runtime_configs
        try:
            env = core.load_env()
            listing = list_runtime_configs(env)
            listing['selected'] = Api._runtime_selection(env, listing['scope'])
            return listing
        except (ValueError, OSError) as exc:
            return {'error': str(exc)}

    @staticmethod
    def _runtime_selection(env, scope):
        try:
            return core.ProjectStore(core.ENV_FILE).runtime_selection(scope,
                project=env['PROJECT_DIR'], read_only=True)
        except (ValueError, KeyError):
            return None  # Old or temporarily unregistered profiles have no selection.

    @staticmethod
    def _runtime_execution(body):
        func = body.get('func', '')
        supported = {row['name'] for row in core.ordered_functions()}
        if not isinstance(func, str) or not func or func not in supported:
            raise ValueError('请选择当前项目支持的运行功能')
        task_id = str(body.get('task_id', '1'))
        if not re.fullmatch(r'[0-9]{1,10}', task_id) or int(task_id) > 2147483647:
            raise ValueError('任务 ID 必须是 0 到 2147483647 的整数')
        return func, task_id

    @staticmethod
    def _check_runtime_scope(env, body):
        from runtime_configs import runtime_scope
        if not body.get('scope') or body['scope'] != runtime_scope(env):
            raise ValueError('运行目录已变化，请刷新当前构建的配置列表后重试')

    @staticmethod
    def _remember_runtime(env, description, func, task_id):
        from runtime_configs import runtime_scope
        core.ProjectStore(core.ENV_FILE).runtime_selection(runtime_scope(env),
            dict(schema=description['schema'], revision=description['revision'],
                 func=func, task_id=str(task_id)), project=env['PROJECT_DIR'])

    @staticmethod
    def _loaded_runtime(description, func, task_id):
        return dict(ok=True, job=dict(schema=description['schema'], name=description['runtime_name'],
            func=func, taskId=str(task_id), outDir=description['out_dir'], mode='existing'),
            revision=description['revision'], inputs=core.schema_inputs(description['schema']),
            validation_required=True, warnings=description.get('warnings', []))

    @staticmethod
    @runtime_operation
    @project_operation
    def activate_runtime_config(body):
        from runtime_configs import describe_runtime_config
        invalid = revision_required(body, 'revision')
        if invalid:
            return invalid
        try:
            env = core.load_env()
            Api._check_runtime_scope(env, body)
            func, task_id = Api._runtime_execution(body)
            description = describe_runtime_config(env, body.get('schema', ''))
            if not description['loadable']:
                raise ValueError(description['reason'])
            if description['revision'] != body['revision']:
                raise core.FileConflict('运行 XML 已变化，请刷新列表后重新选择')
            Api._remember_runtime(env, description, func, task_id)
            return Api._loaded_runtime(description, func, task_id)
        except (ValueError, OSError) as exc:
            return editor_error(exc)

    @staticmethod
    @project_operation
    def preview_runtime_import(body):
        from runtime_configs import preview_runtime_import
        try:
            env = core.load_env()
            Api._check_runtime_scope(env, body)
            preview = preview_runtime_import(env, body.get('source', ''), body.get('destination_schema', ''))
            description = preview.get('description', {})
            return dict(preview, runtime_name=description.get('runtime_name', ''),
                        out_dir=description.get('out_dir', ''), warnings=description.get('warnings', []))
        except (ValueError, OSError) as exc:
            return editor_error(exc)

    @staticmethod
    @runtime_operation
    @project_operation
    def import_runtime_config(body):
        from runtime_configs import import_runtime_config
        try:
            env = core.load_env()
            Api._check_runtime_scope(env, body)
            func, task_id = Api._runtime_execution(body)
            description = import_runtime_config(env, body.get('source', ''),
                body.get('destination_schema', ''), body.get('token', ''))
            result = dict(Api._loaded_runtime(description, func, task_id), imported=description.get('imported', False))
            if description.get('cleanup_warning'):
                result['cleanup_warning'] = description['cleanup_warning']
            try:
                Api._remember_runtime(env, description, func, task_id)
            except (ValueError, OSError) as exc:
                result['selection_warning'] = 'XML 已导入，但未能记忆本次选择：' + str(exc)
            return result
        except (ValueError, OSError) as exc:
            return editor_error(exc)

    @staticmethod
    @project_operation
    def state(_):
        store = core.ProjectStore(core.ENV_FILE)
        try:
            with core.RUNTIME.operation('检测本机工具'):
                machine = store.setup_machine()
                # Tool discovery can update the revision, but never while a run owns it.
                core.PROJECT_CONTEXT.set(store.load(allow_empty=True))
        except RuntimeBusy:
            env = core.load_env()
            machine = {'values': {key: env.get(key, '') for key in core.MACHINE_FIELDS},
                       'candidates': {}, 'filled': [], 'deferred': True}
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
                "func_source": "来自 " + current_project + "/SwanUtility/incl/LiShuttleTypes.h",
                'runtime': core.runtime_state(env)}

    @staticmethod
    @runtime_operation
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
    @runtime_operation
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
            env = core.load_env()
            try:
                with core.RUNTIME.operation('刷新构建状态'):
                    env = core.sync_executable(core.ProjectStore(core.ENV_FILE), env)
            except RuntimeBusy:
                pass  # Describe the pinned configuration without implicit persistence.
            core.PROJECT_CONTEXT.set(env)
            return {'build_workflow': core.describe_build(env),
                    'build_values': {key:env.get(key,'') for key in core.BUILD_FIELDS},
                    'profile_revision': env['PROJECT_PROFILE_REVISION']}
        except (ValueError, OSError) as exc:
            return {'error': str(exc)}

    @staticmethod
    @runtime_operation
    @project_operation
    def save_machine_config(body):
        try:
            store = core.ProjectStore(core.ENV_FILE)
            store.save_machine(body.get('values', {}), body.get('_machine_revision'))
            return Api.state(None)
        except (ValueError, OSError) as exc:
            return {'error': str(exc)}

    @staticmethod
    @runtime_operation
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
            binding = core.ProjectStore(core.ENV_FILE).binding(key, project=env['PROJECT_DIR'],
                read_only=True)
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
    @runtime_operation
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
    @runtime_operation
    @project_operation
    def set_map_root(body):
        path = body.get("path", "").replace("\\", "/")
        if not os.path.isdir(path):
            return {"error": f"目录不存在：{path}"}
        core.save_env_keys(MAP_ROOT=path)
        cities, map_root = core.scan_cities()
        return {"map_root": map_root, "cities": cities, "profile_revision": core.load_env().get('PROJECT_PROFILE_REVISION', '')}

    @staticmethod
    @runtime_operation
    @project_operation
    def set_gongcan_root(body):
        path = body.get("path", "").replace("\\", "/")
        if not os.path.isdir(path):
            return {"error": f"目录不存在：{path}"}
        core.save_env_keys(GONGCAN_ROOT=path)
        tasks, gongcan_root = core.scan_tasks()
        return {"gongcan_root": gongcan_root, "tasks": tasks, "profile_revision": core.load_env().get('PROJECT_PROFILE_REVISION', '')}

    @staticmethod
    @runtime_operation
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
                return {'error': '配置或路径选择已变化，请重新预览后确认装配',
                        'code': 'PREVIEW_STALE'}
        class GenerationFailed(Exception):
            pass

        result = dict(schema_name=f'{job_name}.xml', func=func, task_id=task_id,
                      schema_ok=False, generated=False, render_status='failed',
                      assembly_status='failed', copied=[])
        schema_path = core.schema_path(result['schema_name'])
        try:
            with core.FileTransaction() as transaction:
                # Register only the outputs this operation can touch, before the
                # child renderer or resource helper mutates any of them.
                transaction.touch(schema_path)
                transaction.touch(schema_path + '.manifest.json')
                result['base_resources'] = core.ensure_runtime_resources(env, transaction=transaction)
                job_file = core.build_job_env(job_name, func, task_id, task,
                                               city_name, city_kind, transaction=transaction)
                result['job_file'] = job_file
                generation = core.run_render(job_file, transaction=transaction)
                result.update(render_exit=generation['exit_code'], render_output=generation['output'],
                              generated=generation['generated'], render_status=generation['status'])
                if not generation['generated'] or generation['status'] not in ('ready', 'missing_inputs'):
                    raise GenerationFailed()
                result['schema_ok'] = True
                result['generation_attempt'] = generation['attempt_id']
                result['missing_inputs'] = generation.get('missing_inputs', [])
                if preview:
                    result.update(runtime_name=preview['runtime_name'], out_dir=preview['out_dir'],
                                  path_changes=preview['changes'], warnings=preview['warnings'])
                groups = tuple(key for key, enabled in (
                    ('antenna', copy_antennas), ('model', copy_files and not reuse)) if enabled)
                if groups:
                    result['copied'] = core.assemble_files(task, env, groups=groups, transaction=transaction)
                details = core.runtime_details(schema_path, os.path.dirname(os.path.dirname(schema_path)))
                result.update(runtime_name=details['name'], out_dir=details['out_dir'])
        except GenerationFailed:
            result.update(schema_ok=False, generated=False, render_status='failed',
                          assembly_status='rolled_back', copied=[])
            result['render_output'] += '\n[已撤销] 本次装配改动已撤销，保留装配前的文件状态。'
            return result
        except (OSError, ValueError) as exc:
            recovery_dir = getattr(exc, 'recovery_dir', None)
            result.update(error=f'装配失败：{exc}', schema_ok=False, generated=False,
                          render_status='failed', copied=[],
                          assembly_status='recovery_required' if recovery_dir else 'rolled_back')
            result['render_output'] = result.get('render_output', '') + f'\n[装配失败] {exc}'
            if recovery_dir:
                result['recovery_dir'] = recovery_dir
                result['render_output'] += '\n[需核对恢复] 请保留上述快照，核对文件状态后恢复。'
            else:
                result['render_output'] += '\n[已撤销] 本次装配改动已撤销，保留装配前的文件状态。'
            return result
        result['assembly_status'] = 'applied'
        try:
            from runtime_configs import describe_runtime_config
            Api._remember_runtime(env, describe_runtime_config(env, result['schema_name']), func, task_id)
        except (ValueError, OSError, KeyError) as exc:
            result['selection_warning'] = f'运行单已保存，上次选择未能记忆：{exc}'
        if result['render_exit'] == 0:
            try:
                previous = body.get('previous_schema', '')
                if previous and (os.path.basename(previous) != previous or not previous.endswith('.xml')):
                    raise ValueError('上次运行配置文件名无效')
                args = (core.load_env(), result['schema_name'], func, task_id, city_kind)
                result['vs_launch'] = (core.sync_vs_launch(*args, previous_schema=previous)
                                       if previous else core.sync_vs_launch(*args))
            except (OSError, ValueError) as exc:
                result['vs_launch_warning'] = f'Visual Studio 启动项未同步：{exc}；请检查 .vs/launch.vs.json'
        return result

    @staticmethod
    def preview_render(body):
        return Api.render(dict(body, use_existing_schema=True, preview_only=True))

    @staticmethod
    @runtime_operation
    @project_operation
    def cleanup_configs(body):
        from runtime_cleanup import cleanup_plan, apply_cleanup
        with core.RUNNER.lock:
            if any(s.get('status') == 'running' for s in core.RUNNER.sessions.values()):
                return {'error': '平台仍有运行或编译进程，请结束后再清理'}
        try:
            env = core.load_env()
            keep = body.get('keep_schema', '')
            if not keep:
                from runtime_configs import runtime_scope
                saved = Api._runtime_selection(env, runtime_scope(env))
                candidate = (saved or {}).get('schema', '')
                if candidate and os.path.isfile(core.schema_path(candidate)):
                    keep = candidate
            plan = cleanup_plan(env, core.JOBS_DIR, core.ROOT, keep)
            if body.get('apply'):
                if body.get('token') != plan['token']:
                    return {'error': '配置文件已变化，请重新预览清理范围'}
                return apply_cleanup(plan, os.path.join(core.ROOT, 'docs', 'runtime-config-archives'))
            return {key: value for key, value in plan.items() if not key.startswith('_')}
        except (ValueError, OSError, KeyError) as exc:
            return {'error': f'配置清理未执行：{exc}'}

    @staticmethod
    @project_operation
    def indoor_building_export(_):
        from indoor_building_export import inspect
        return inspect(core.load_env())

    @staticmethod
    @runtime_operation
    @project_operation
    def enable_indoor_building_export(body):
        invalid = revision_required(body, 'revision')
        if invalid:
            return invalid
        from indoor_building_export import enable
        try:
            return dict(enable(core.load_env(), body['revision']), ok=True)
        except (ValueError, OSError) as exc:
            return editor_error(exc)

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
        extra = {}
        if func == 'predindoor':
            from indoor_building_export import inspect
            extra['indoor_building_export'] = inspect(core.load_env())
        return {**catalog, **extra, "file": path, "schema_name": document['name'], "values": document['values'],
                "revision": document['revision'],
                "inputs": core.schema_inputs(schema, document),
                "param_sources": {'DefaultCalcRadius': core.radius_source(schema)},
                "thirdpart_defaults": core.thirdpart_defaults(document['values'])}

    @staticmethod
    @runtime_operation
    @project_operation
    def param_default(body):
        tag = body.get('tag', '')
        if tag == 'DefaultCalcRadius':
            return {'ok': False, 'message': '小区计算半径以 CSV 为准，请修改工参半径；XML 仅提供默认值'}
        invalid = revision_required(body, 'revision')
        if invalid:
            return invalid
        try:
            _, document = core.read_schema_document(body.get('schema', ''))
            if document is None:
                return {'ok': False, 'message': '读不到当前运行单，请先装配后重新加载'}
            if document['revision'] != body['revision']:
                raise core.FileConflict('运行 XML 已变化，请重新加载后再保存')
            default = core.thirdpart_defaults(document['values']).get(tag)
            if not default or not default['available']:
                return {'ok': False, 'message': (default or {}).get('reason', '当前项目样例没有此参数的默认值')}
            result = core.write_schema_param(body.get('schema', ''), tag, default['value'],
                expected_revision=body['revision'], return_revision=True)
            response = dict(ok=result[0], message=result[1], value=default['value'], source=default['source'])
            if result[0]:
                response['revision'] = result[2]
            return response
        except (ValueError, OSError) as exc:
            return editor_error(exc)

    @staticmethod
    @runtime_operation
    @project_operation
    def param_write(body):
        schema = body.get("schema", "")
        tag = body.get("tag", "")
        value = str(body.get("value", ""))
        fields = ('revision', 'source_revision', 'format_revision') if tag == 'DefaultCalcRadius' else ('revision',)
        invalid = revision_required(body, *fields)
        if invalid:
            return invalid
        try:
            result = core.write_schema_param(schema, tag, value, expected_revision=body['revision'],
                source_revision=body.get('source_revision'), format_revision=body.get('format_revision'), return_revision=True)
            response = dict(ok=result[0], message=result[1],
                target='engineering_csv' if tag == 'DefaultCalcRadius' else 'schema',
                values=result[3] if len(result) > 3 else {})
            if result[0]:
                if tag == 'DefaultCalcRadius':
                    response.update(revision=body['revision'], source_revision=result[2])
                else:
                    response['revision'] = result[2]
            return response
        except (ValueError, OSError) as exc:
            return editor_error(exc)

    @staticmethod
    @project_operation
    def csv_get(query):
        try:
            path = query.get('path', [''])[0]
            context = core.csv_editor_context(path, query.get('schema', [''])[0])
            return core.read_csv_grid(path, **context)
        except (ValueError, OSError) as exc:
            return dict(error=str(exc))

    @staticmethod
    @runtime_operation
    @project_operation
    def csv_save(body):
        invalid = revision_required(body, 'revision', 'format_revision')
        if invalid:
            return invalid
        try:
            context = core.csv_editor_context(body['path'], body.get('schema', ''))
            result = core.save_csv_grid(body['path'], body.get('header_zh'), body.get('header_en'), body['rows'],
                expected_revision=body['revision'], expected_format_revision=body['format_revision'],
                header_rows=body.get('header_rows'), header_lines=body.get('header_lines'),
                return_revision=True, **context)
            response = dict(ok=result[0], message=result[1])
            if result[0]:
                response['revision'] = result[2]
            return response
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return editor_error(exc)

    @staticmethod
    @runtime_operation
    @project_operation
    def csv_column(body):
        invalid = revision_required(body, 'revision', 'format_revision')
        if invalid:
            return invalid
        try:
            context = core.csv_editor_context(body['path'], body.get('schema', ''))
            result = core.set_csv_column(body['path'], body['column'], str(body['value']),
                expected_revision=body['revision'], expected_format_revision=body['format_revision'],
                column_index=body.get('column_index'), return_revision=True, **context)
            response = dict(ok=result[0], message=result[1])
            if result[0]:
                response['revision'] = result[2]
            return response
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return editor_error(exc)

    @staticmethod
    @runtime_operation
    @project_operation
    def run(body):
        schema = body.get("schema", "")
        func = body.get("func", "pl")
        task_id = str(body.get("task_id", "1"))
        try:
            sid, exe = core.start_lishuttle(schema, func, task_id)
        except core.PreflightRejected as exc:
            return {'error': str(exc), 'code': 'PREFLIGHT_FAILED', 'preflight': exc.report,
                    'issues': exc.report['issues']}
        if sid is None:
            return {"error": exe}
        return {"sid": sid, "exe": exe, 'runtime': core.RUNTIME.snapshot(),
                'context': core.RUNNER.output(sid, 0).get('context', {})}

    @staticmethod
    @project_operation
    def preflight(body):
        return core.check_run(body.get('schema', ''), body.get('func', 'pl'), str(body.get('task_id', '1')))

    @staticmethod
    def runtime_state(_):
        return core.runtime_state()

    @staticmethod
    @runtime_operation
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
                return {'sid':sid, 'bat':bat, 'build_values':values, 'runtime':core.RUNTIME.snapshot(),
                        'profile_revision':env.get('PROJECT_PROFILE_REVISION'), 'build_workflow':core.describe_build(env)}
            except (ValueError, OSError) as exc:
                return {'error':str(exc), 'issues':[{'key':'PRESET','target':'build-mode','section':'build','message':str(exc)}]}
        sid, bat = core.start_toolkit(body.get("step", "doctor"))
        if sid is None:
            return {'error': bat}
        return {"sid": sid, "bat": bat, 'runtime':core.RUNTIME.snapshot()}

    @staticmethod
    def output(query):
        sid = int(query.get("sid", ["0"])[0])
        since = int(query.get("since", ["0"])[0])
        limit = max(1, min(5000, int(query.get('limit', ['500'])[0])))
        return core.RUNNER.output(sid, since, limit=limit)

    @staticmethod
    @project_operation
    def history(query):
        return core.recent_runs(core.load_env().get('PROJECT_DIR', ''),
            limit=query.get('limit', ['20'])[0], offset=query.get('offset', ['0'])[0])

    @staticmethod
    def stop(body):
        return {"stopped": core.RUNNER.stop(int(body.get("sid", "0")))}

    @staticmethod
    def results(query):
        if query.get('sid'):
            return core.session_results(int(query['sid'][0]))
        return Api.job_results(query)

    @staticmethod
    @project_operation
    def job_results(query):
        try:
            schema = query.get('schema', [''])[0]
            return (core.results(schema_name=schema) if schema else core.results(query.get('job', [''])[0]))
        except (ValueError, OSError) as exc:
            return {'error': str(exc)}

    @staticmethod
    def open_folder(body):
        path = body.get("path", "")
        if os.path.isdir(path) and sys.platform == "win32":
            os.startfile(path)  # noqa: S606
            return {"ok": True}
        return {"error": f"目录不存在：{path}"}


ROUTES = {
    ("GET", "state"): Api.state,
    ("GET", "runtime_configs"): Api.runtime_configs,
    ("POST", "activate_runtime_config"): Api.activate_runtime_config,
    ("POST", "preview_runtime_import"): Api.preview_runtime_import,
    ("POST", "import_runtime_config"): Api.import_runtime_config,
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
    ("GET", "indoor_building_export"): Api.indoor_building_export,
    ("POST", "enable_indoor_building_export"): Api.enable_indoor_building_export,
    ("POST", "param_write"): Api.param_write,
    ("POST", "param_default"): Api.param_default,
    ("GET", "csv"): Api.csv_get,
    ("POST", "csv_save"): Api.csv_save,
    ("POST", "csv_column"): Api.csv_column,
    ("POST", "run"): Api.run,
    ("POST", "preflight"): Api.preflight,
    ("GET", "runtime_state"): Api.runtime_state,
    ("POST", "toolkit"): Api.toolkit,
    ("GET", "output"): Api.output,
    ("GET", "history"): Api.history,
    ("POST", "stop"): Api.stop,
    ("GET", "results"): Api.results,
    ("POST", "open_folder"): Api.open_folder,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 安静模式
        pass

    def _json(self, obj, code=200):
        if isinstance(obj, dict):
            if obj.get('code') in ('RUNTIME_BUSY', 'FILE_CONFLICT'):
                code = 409
            elif obj.get('code') == 'REVISION_REQUIRED':
                code = 400
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
    finally:
        core.RUNNER.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
