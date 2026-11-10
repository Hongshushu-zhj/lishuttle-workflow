#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
lishuttle 本地平台核心逻辑：识别器 / 文件读写 / 渲染调用 / 进程运行器。

设计约定（用户已确认）：
- 参数修改直接写进对应文件（先备份 .bak），文件是唯一事实；
- 室内外识别：以选定工参 CSV 的表头为准；
- 所有路径拼接复用 scripts/render_schema.py 已验证的逻辑（经 env/jobs 驱动）。
"""

import csv
from contextvars import ContextVar
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import hashlib
import tempfile
import math
import xml.etree.ElementTree as ET
from copy import deepcopy
import time
import secrets
from run_guard import RuntimeGuard
from managed_process import ManagedProcess
from run_history import RunHistory
from engineering import identify_engineering, validate_engineering, normalized, engineering_kind
from vs_launch import sync_launch

HERE = os.path.dirname(os.path.abspath(__file__))      # platform/backend
ROOT = os.path.dirname(os.path.dirname(HERE))          # 工作流根目录
SCRIPTS = os.path.join(ROOT, "scripts")
ENV_FILE = os.path.join(ROOT, "env", "local-win.env")
PROJECTS_FILE = os.path.join(ROOT, "env", "projects.json")
JOBS_DIR = os.path.join(ROOT, "jobs")
SPEC_FILE = os.path.join(HERE, "params_spec.json")

sys.path.insert(0, SCRIPTS)
from render_schema import read_env_file, build_table  # noqa: E402
from file_safety import atomic_write, file_revision, FileTransaction, FileConflict
from engineering_format import grid_layout, ALIASES, recognized_columns
from task_schema import schema_candidates, render_existing, runtime_details, path_overrides, read_runtime, local_path_values, OUTDOOR_PATHS, project_sample_path, runtime_scene
from project_config import ProjectStore, FIELDS, MACHINE_FIELDS, write_snapshot, validate_operation
from project_detection import detect_project_config
from indoor_maps import indoor_floor_files
from project_workflow import describe_build, prepare_build, required_issues, sync_executable, BUILD_FIELDS
from parameter_catalog import parse_document, build_catalog, replace_scalar

PROJECT_CONTEXT = ContextVar('project_config', default=None)

CSV_ENCODINGS = ("utf-8-sig", "gb18030", "gbk")


# ----------------------------------------------------------------------
# 环境读写（平台选择持久化回 env 文件，保持 CLI 与 GUI 单一事实）
# ----------------------------------------------------------------------

def load_env():
    return dict(PROJECT_CONTEXT.get() or ProjectStore(ENV_FILE).load(
        allow_empty=True, read_only=True))


def save_env_keys(**kwargs):
    """只写当前项目档案；legacy env 仅用作首次导入。"""
    store = ProjectStore(ENV_FILE)
    if 'PROJECT_DIR' in kwargs:
        env = store.select(kwargs.pop('PROJECT_DIR'))
        if kwargs:
            env = store.save(kwargs, project=env['PROJECT_DIR'])
    else:
        env = store.save(kwargs, project=load_env()['PROJECT_DIR'])
    if PROJECT_CONTEXT.get() is not None:
        PROJECT_CONTEXT.set(env)
    return env


# ----------------------------------------------------------------------
# 三个识别器
# ----------------------------------------------------------------------

def scan_projects():
    """仅列出明确添加的项目，以及升级前已配置的当前项目。"""
    env = load_env()
    found = []
    if os.path.isfile(PROJECTS_FILE):
        with open(PROJECTS_FILE, encoding='utf-8') as fh:
            found = json.load(fh).get('projects', [])
    current = to_slash(env.get("PROJECT_DIR", ""))
    if env.get('PROJECT_PROFILE_ID'):
        found = found + ProjectStore(ENV_FILE).paths(read_only=True)
    unique, seen = [], set()
    for path in ([current] if current else []) + found:
        key = os.path.normcase(os.path.abspath(to_native(path)))
        if key not in seen:
            seen.add(key)
            unique.append(to_slash(path))
    return unique, current


def validate_project(path):
    path = os.path.abspath(os.path.expanduser(path.strip().strip('"')))
    required = [('CMakeLists.txt', os.path.isfile), ('LiShuttle', os.path.isdir),
                ('SwanUtility/incl/LiShuttleTypes.h', os.path.isfile)]
    missing = [name for name, check in required if not check(os.path.join(path, name))]
    warnings = [f'缺少 {name}，请检查对应构建或装配配置' for name in
                ('CMakePresets.json', 'ThirdPart/Config/runtimelibrary/runtimeschema.xml')
                if not os.path.isfile(os.path.join(path, name))]
    return dict(ok=not missing, path=to_slash(path), warnings=warnings,
                error='不是可识别的 LiShuttle 项目，缺少：' + '、'.join(missing) if missing else '')


def add_project(path):
    if not path.strip():
        return dict(ok=False, error='请输入项目根目录')
    result = validate_project(path)
    if not result['ok']:
        return result
    projects, _ = scan_projects()
    if not any(os.path.normcase(os.path.abspath(p)) == os.path.normcase(result['path']) for p in projects):
        projects.append(result['path'])
    os.makedirs(os.path.dirname(PROJECTS_FILE), exist_ok=True)
    with open(PROJECTS_FILE + '.tmp', 'w', encoding='utf-8') as fh:
        json.dump({'projects': projects}, fh, ensure_ascii=False, indent=2)
    os.replace(PROJECTS_FILE + '.tmp', PROJECTS_FILE)
    return result


def thirdpart_defaults(values=None):
    """默认值源于当前项目样例；路径必须落在真实存在的配置源内。"""
    env = load_env()
    config = os.path.realpath(os.path.join(env['PROJECT_DIR'], env.get('CONFIG_SRC') or 'ThirdPart/Config'))
    indoor = runtime_scene(values or {}) == 'indoor'
    sample = project_sample_path(env, indoor=indoor)
    try:
        with open(sample, 'rb') as fh:
            document = parse_document(fh.read())
    except (OSError, ValueError):
        return {}
    if indoor and document['values'].get('MapFormat', '').strip().lower() != 'indoor':
        return {}
    path_tags = {p['name'] for p in load_spec()['params'] if p.get('type') == 'path'}
    path_tags.update(('BuildingPenetration', 'RoadsToBeRecorded', 'PredictedCells'))
    known = {'SceneSettingsPath': 'config/scenesettings.xml',
             'ClutterMatchPath': 'config/cluttermatchsettings.xml'}
    result = {}
    for tag, field in document['fields'].items():
        value = field['value']
        item = dict(available=True, value=value, source=to_slash(sample), reason='')
        if field['read_only']:
            result[tag] = dict(item, available=False, value='', reason='项目样例：' + field['read_only_reason'])
            continue
        if tag in path_tags or tag.endswith(('Path', 'Directory')):
            item.update(available=False, value='', reason='ThirdPart 中没有可确认的默认资源，请选择任务数据路径')
            candidates = [os.path.join(config, known[tag])] if tag in known else []
            if value.strip():
                native = to_native(value.strip())
                candidates += [os.path.join(os.path.dirname(sample), native), os.path.join(config, native)]
            for candidate in candidates:
                candidate = os.path.realpath(candidate)
                try:
                    inside = os.path.commonpath([config, candidate]) == config
                except ValueError:
                    inside = False
                if inside and os.path.exists(candidate):
                    item.update(available=True, value=to_slash(candidate), source=to_slash(candidate), reason='')
                    break
        result[tag] = item
    return result


def _check(paths_labels):
    return [[label, to_slash(p), os.path.isfile(p)] for label, p in paths_labels]


def scan_cities():
    """地图根的子目录 → 室外城市（heights/index.txt）/ 室内 DAS 场景。"""
    env = load_env()
    map_root = env.get("MAP_ROOT", "")
    cities = []
    if not os.path.isdir(map_root):
        return cities, to_slash(map_root)
    for name in sorted(os.listdir(map_root)):
        full = os.path.join(map_root, name)
        if not os.path.isdir(full):
            continue
        floors = indoor_floor_files(full)
        if floors:
            checks = _check([(path.name, str(path)) for path in floors])
            cities.append({"name": name, "kind": "indoor", "checks": checks})
        elif os.path.isfile(os.path.join(full, "heights", "index.txt")):
            checks = _check([
                ("投影", os.path.join(full, "heights", "projection.txt")),
                ("高程", os.path.join(full, "heights", "index.txt")),
                ("杂波", os.path.join(full, "clutter", "index.txt")),
                ("杂波菜单", os.path.join(full, "clutter", "menu.txt")),
                ("建筑", os.path.join(full, "buildings", "index.txt")),
                ("建筑矢量", os.path.join(full, "buildvector", "index.txt")),
            ])
            cities.append({"name": name, "kind": "outdoor", "checks": checks})
    return cities, to_slash(map_root)


def sniff_csv_encoding(path):
    with open(path, "rb") as fh:
        raw = fh.read(64 * 1024)
    for enc in CSV_ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "gb18030"


def detect_task_kind(folder_name, csv_files):
    """室内外识别：文件夹名约定优先，CSV 表头兜底。"""
    low = folder_name.lower()
    if "室内" in folder_name or "indoor" in low:
        return "indoor", "文件夹名"
    if "室外" in folder_name or "outdoor" in low:
        return "outdoor", "文件夹名"
    for csv_path in csv_files[:3]:
        enc = sniff_csv_encoding(csv_path)
        try:
            with open(csv_path, "r", encoding=enc, errors="replace") as fh:
                rows = []
                for _, line in zip(range(2), fh):
                    rows.append(line)
        except OSError:
            continue
        head = "".join(rows)
        if "AP ID" in head or "AP ID" in head.encode("utf-8").decode("utf-8", "ignore"):
            return "indoor", "CSV表头(AP ID)"
        if "Cell ID" in head or "小区ID" in head:
            return "outdoor", "CSV表头(Cell ID)"
    return "unknown", "未能识别"


def scan_tasks():
    """gongcan 目录 → 任务列表。子目录=一个任务；顶层散 csv 也算单文件任务。"""
    env = load_env()
    gongcan = env.get("GONGCAN_ROOT", "")
    tasks = []
    if not os.path.isdir(gongcan):
        return tasks, to_slash(gongcan)
    for name in sorted(os.listdir(gongcan)):
        if name == '.lishuttle-history':
            continue
        full = os.path.join(gongcan, name)
        if os.path.isdir(full):
            csvs, txts, xmls = [], [], []
            antenna = model = scene = ""
            antenna_dir = model_dir = ""
            for base, dirs, files in os.walk(full):
                dirs[:] = sorted(d for d in dirs if d != '.lishuttle-history')
                base_name = os.path.basename(base).lower()
                if base_name in ("antenna", "antennas") and not antenna_dir:
                    antenna_dir = base
                elif base_name == "models" and not model_dir:
                    model_dir = base
                for f in sorted(files):
                    p = os.path.join(base, f)
                    lf = f.lower()
                    if lf.endswith(".csv"):
                        csvs.append(p)
                    elif lf.endswith(".txt") and not f.startswith("build"):
                        txts.append(p)
                    elif lf.endswith(".xml"):
                        xmls.append(p)
                    if lf == "antenna.xml":
                        antenna = p
                    elif lf == "lishuttlemodel.xml":
                        model = p
                    elif lf == "scenesettings.xml":
                        scene = p
            # 有多份资源目录时，使用已识别 antenna.xml 所在的目录，避免 XML/方向图错配。
            if antenna and os.path.basename(os.path.dirname(antenna)).lower() in ('antenna', 'antennas'):
                antenna_dir = os.path.dirname(antenna)
            kind, basis = 'unknown', ''
            tasks.append({
                "name": name, "kind": kind, "detect": basis, "dir": to_slash(full),
                "csvs": [to_slash(p) for p in csvs],
                "txts": [to_slash(p) for p in txts],
                "xmls": [to_slash(p) for p in xmls],
                "antenna": to_slash(antenna) if antenna else "",
                "model": to_slash(model) if model else "",
                "scene": to_slash(scene) if scene else "",
                "antenna_dir": to_slash(antenna_dir) if antenna_dir else "",
                "model_dir": to_slash(model_dir) if model_dir else "",
            })
        elif name.lower().endswith(".csv"):
            kind, basis = 'unknown', '散文件'
            tasks.append({
                "name": name, "kind": kind, "detect": basis + "(散文件)",
                "dir": to_slash(gongcan), "csvs": [to_slash(full)],
                "txts": [], "xmls": [], "antenna": "", "model": "", "scene": "",
            })
    # A container with several independent XML packages is not one task.
    # Keep each package's CSV, antenna and model resources in its own scope.
    expanded = []
    for task in tasks:
        candidates = schema_candidates(task.get('xmls', []))
        folders = sorted({os.path.dirname(c['path']) for c in candidates})
        if len(folders) > 1 and all(folder != task['dir'] for folder in folders):
            for folder in folders:
                child = dict(task, name=task['name'] + '/' + to_slash(os.path.relpath(folder, task['dir'])), dir=folder)
                for key in ('csvs', 'txts', 'xmls'):
                    child[key] = [p for p in task[key] if os.path.commonpath([p, folder]) == os.path.normpath(folder)]
                for key, filename in (('antenna', 'antenna.xml'), ('model', 'lishuttlemodel.xml'), ('scene', 'scenesettings.xml')):
                    matches = [p for p in child['xmls'] if os.path.basename(p).lower() == filename]
                    child[key] = matches[0] if len(matches) == 1 else ''
                for key, names in (('antenna_dir', ('antenna', 'antennas')), ('model_dir', ('models',))):
                    matches = [os.path.join(base, name) for base, dirs, _ in resource_walk(folder)
                               for name in dirs if name.lower() in names]
                    child[key] = to_slash(matches[0]) if len(matches) == 1 else ''
                expanded.append(child)
        else:
            expanded.append(task)
    tasks = expanded
    for task in tasks:
        identify_engineering(task)
        task['schema_candidates'] = schema_candidates(task.get('xmls', []))
        task['has_antennas'] = bool(task.get('antenna')) or bool(task.get('antenna_dir')) and any(
            any(not f.lower().endswith('.bak') for f in files)
            for _, _, files in resource_walk(task['antenna_dir'])
        )
    return tasks, to_slash(gongcan)


# ----------------------------------------------------------------------
# 渲染（写 jobs/web-*.env 后调 render_schema.py，复用全部已验证逻辑）
# ----------------------------------------------------------------------

def pick_region(txts, csv_path):
    """从任务的 txt 里挑区域多边形：优先与工参 CSV 同名的（服务器任务包命名惯例
    task-name.csv / task-name.txt）；没有同名的就退回 csv 同目录的第一个；
    都没有则返回空。天线方向图等大量 txt 不会被误选。"""
    if not csv_path:
        return ""
    stem = os.path.splitext(os.path.basename(csv_path))[0]
    for t in txts:
        if os.path.splitext(os.path.basename(t))[0] == stem:
            return t
    csv_dir = os.path.dirname(csv_path)
    same_dir = [t for t in txts if os.path.dirname(t) == csv_dir]
    return same_dir[0] if same_dir else ""


def preview_task_schema(body, task, city_kind):
    """Validate selected local files and build the same path table used by CLI rendering."""
    requested = body.get('schema_source', '')
    candidates = task.get('schema_candidates', [])
    source = next((c['path'] for c in candidates if os.path.normcase(os.path.realpath(c['path']))
                   == os.path.normcase(os.path.realpath(requested))), None) if requested else None
    if not source:
        raise ValueError('请选择当前任务中有效的运行配置 XML，请重新扫描后选择')
    polygon = body.get('polygon_file', '')
    if polygon:
        polygon = next((p for p in task.get('txts', [])
                        if os.path.normcase(os.path.realpath(p)) == os.path.normcase(os.path.realpath(polygon))), None)
        if not polygon:
            raise ValueError('区域文件不属于当前任务，请重新选择')
    env = load_env()
    city = body.get('city', '')
    if not city:
        raise ValueError('请选择地图')
    job = dict(JOB_NAME=body['job_name'], SCHEMA_NAME=body['job_name'] + '.xml',
               SYNC_RUNTIME_NAME='1',
               FUNC=body.get('func', 'pl'), CITY=city,
               SCHEMA_SOURCE=source, SYNC_ENGINEERING='1' if body.get('sync_engineering') else '0',
               ENGINEERING_FILE=task.get('engineering_file', ''), POLYGON_FILE=polygon)
    if task.get('scene'):
        job['SCENE_SETTINGS_FILE'] = task['scene']
    overrides = path_overrides(body.get('path_overrides', {}))
    if set(overrides) & {'EngineeringFilePath', 'PolygonFilePath'}:
        raise ValueError('请通过上方工参及区域文件选择修改路径，不允许另外覆盖')
    job['PATH_OVERRIDES'] = json.dumps(overrides, ensure_ascii=False)
    if city_kind == 'indoor':
        job.update(TEMPLATE='runtimeschema-indoor.xml.tpl', MAP_PATH=env['MAP_ROOT'].rstrip('/') + '/' + city)
    table = build_table(env, job)
    preview = render_existing(table)
    destination = schema_path(job['SCHEMA_NAME'])
    if os.path.normcase(os.path.realpath(source)) == os.path.normcase(os.path.realpath(destination)):
        raise ValueError('源 XML 与目标文件相同，不能覆盖原始配置')
    task.update(schema_source=source, sync_engineering=bool(body.get('sync_engineering')), polygon_file=polygon,
                path_overrides=overrides)
    preview['destination'] = destination
    preview['token'] = hashlib.sha256((preview['token'] + '\0' + destination + '\0'
        + json.dumps(env, sort_keys=True)).encode('utf-8')).hexdigest()
    preview['warnings'] = []
    for label, path in [('场景配置', preview['scene_settings_file']), ('路测目录', preview['drivetest_dir'])]:
        native = to_native(path)
        if path and not os.path.exists(native if os.path.isabs(native) else os.path.join(os.path.dirname(os.path.dirname(destination)), native)):
            preview['warnings'].append(f'{label}路径在本机不存在：{path}；请在本地路径中修改')
    if not task['sync_engineering'] and preview['engineering_file']:
        engineering_path = preview['engineering_file'].replace('\\', '/')
        if not os.path.isabs(engineering_path):
            engineering_path = os.path.join(os.path.dirname(os.path.dirname(destination)), engineering_path)
        if not os.path.isfile(engineering_path):
            preview['warnings'].append('原 XML 的工参路径在当前运行位置不存在；可勾选“同步为当前工参”，或复制后手动调整')
    return {k: v for k, v in preview.items() if k != 'text'}


def job_env_path(job_name, env=None):
    """Stable task-sheet destination, discoverable before an assembly mutates it."""
    from runtime_cleanup import build_scope
    env = load_env() if env is None else env
    directory = os.path.join(JOBS_DIR, env.get('PROJECT_PROFILE_ID') or
                             hashlib.sha256(os.path.realpath(env['PROJECT_DIR']).encode('utf-8')).hexdigest()[:20],
                             build_scope(env))
    return os.path.join(directory, f'web-{job_name}.env')


def build_job_env(job_name, func, task_id, task, city_name, city_kind, transaction=None):
    env = load_env()
    lines = [
        f'JOB_NAME="{job_name}"',
        'SYNC_RUNTIME_NAME="1"',
        f'PLATFORM_PROJECT_DIR="{to_slash(env["PROJECT_DIR"])}"',
        f'PLATFORM_BUILD_SUBDIR="{env["BUILD_SUBDIR"]}"',
        'PLATFORM_JOB_SCOPE="build-v1"',
        f'SCHEMA_NAME="${{JOB_NAME}}.xml"',
        f'FUNC="{func}"',
        f'TASK_ID="{task_id}"',
        f'RENDER_BEFORE_RUN="1"',
        f'SERVER_BACKGROUND="0"',
    ]
    txts = task.get("txts") if task else []
    csv_file = (task.get('engineering_file', '') if task.get('schema_source') and not task.get('sync_engineering')
                else to_slash(validate_engineering(task)))
    region = pick_region([to_slash(t) for t in txts], csv_file)
    if city_kind == "indoor":
        lines += [
            f'TEMPLATE="runtimeschema-indoor.xml.tpl"',
            f'MAP_PATH="${{MAP_ROOT}}/{city_name}"',
            f'ENGINEERING_FILE="{csv_file}"',
            f'POLYGON_FILE=""',
        ]
    else:
        lines += [
            f'CITY="{city_name}"',
            f'ENGINEERING_FILE="{csv_file}"',
            f'POLYGON_FILE="{region}"',
        ]
    job_file = job_env_path(job_name, env)
    if env.get('PROJECT_PROFILE_ID'):
        lines += [f'PROJECT_PROFILE_ID="{env["PROJECT_PROFILE_ID"]}"']
    if task.get('schema_source'):
        lines += [f'SCHEMA_SOURCE="{task["schema_source"]}"',
                  f'SYNC_ENGINEERING="{1 if task.get("sync_engineering") else 0}"',
                  'PATH_OVERRIDES="' + json.dumps(task.get('path_overrides', {}), ensure_ascii=False) + '"']
        # 区域由用户明确选择，不再猜测任务包的 index/WrongSites 等 TXT。
        lines = [f'POLYGON_FILE="{task.get("polygon_file", "")}"'
                 if line.startswith('POLYGON_FILE=') else line for line in lines]
    if task.get('scene'):
        lines.append(f'SCENE_SETTINGS_FILE="{task["scene"]}"')
    data = ("# 由平台生成，可手工编辑后用脚本复跑\n" + "\n".join(lines) + "\n").encode('utf-8')
    (transaction.write if transaction else atomic_write)(job_file, data)
    return to_slash(job_file)


def run_render(job_file, transaction=None):
    """Render and verify this invocation's receipt, paths and content digests.

    必须显式给子进程 PYTHONIOENCODING=utf-8：Python 的 stdout 被管道捕获时用的是
    系统 locale 编码（中文 Windows 上是 GBK），而这里按 UTF-8 解码；
    不固定编码就会整页乱码（实测就是这个原因导致渲染输出不可读）。
    """
    child_env = dict(os.environ)
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env['LISHUTTLE_CONFIG_SNAPSHOT'] = write_snapshot(load_env())
    job = read_env_file(job_file, '任务单')
    table = build_table(load_env(), job)
    # When the API owns the transaction it owns backups too, so a later resource
    # failure can restore the previous .bak and remove new history entries.
    if transaction is not None:
        targets = [os.path.join(table['RUNTIME_SCHEMA_DIR'], name.strip())
                   for name in table['SCHEMA_NAME'].split(',') if name.strip()]
        targets.append(os.path.join(table['RUNTIME_SCHEMA_DIR'],
                                    table['SCHEMA_NAME'] + '.manifest.json'))
        for path in targets:
            if os.path.isfile(path):
                transaction.copy(path, path, backup=True)
    attempt_id = secrets.token_hex(24)
    with tempfile.TemporaryDirectory(prefix='lishuttle-render-') as directory:
        receipt_path = os.path.join(directory, 'receipt.json')
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, "render_schema.py"), job_file, "local-win",
             '--attempt-id', attempt_id, '--receipt', receipt_path]
            + (['--no-backup'] if transaction is not None else []),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=ROOT, env=child_env)
        result = dict(exit_code=proc.returncode, output=(proc.stdout or '') + (proc.stderr or ''),
                      generated=False, status='failed', attempt_id=attempt_id, outputs=[])
        try:
            with open(receipt_path, encoding='utf-8') as source:
                receipt = json.load(source)
            if not isinstance(receipt, dict):
                raise ValueError('本次生成凭据格式无效')
            expected = {os.path.normcase(os.path.abspath(os.path.join(table['RUNTIME_SCHEMA_DIR'], name.strip())))
                        for name in table['SCHEMA_NAME'].split(',') if name.strip()}
            manifest = os.path.join(table['RUNTIME_SCHEMA_DIR'], table['SCHEMA_NAME'] + '.manifest.json')
            expected.add(os.path.normcase(os.path.abspath(manifest)))
            outputs = receipt.get('outputs', [])
            actual = {os.path.normcase(os.path.abspath(item['path'])) for item in outputs}
            status = 'ready' if proc.returncode == 0 else 'missing_inputs' if proc.returncode == 1 else None
            if (receipt.get('attempt_id') != attempt_id or not receipt.get('generated')
                    or receipt.get('status') != status or status is None
                    or actual != expected or len(outputs) != len(expected)
                    or any(item['revision'] == 'missing' or file_revision(item['path']) != item['revision'] for item in outputs)):
                raise ValueError('本次生成凭据与目标文件不一致')
            with open(manifest, encoding='utf-8') as source:
                manifest_data = json.load(source)
            generation = manifest_data.get('generation') if isinstance(manifest_data, dict) else None
            if not isinstance(generation, dict) or generation.get('attempt_id') != attempt_id:
                raise ValueError('渲染记录不属于本次生成')
            result.update(generated=True, status=status, outputs=outputs,
                          missing_inputs=receipt.get('missing_inputs', []))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result['output'] += f'\n[生成未确认] {exc}'
        return result


def resource_walk(directory, **kwargs):
    """Business resources exclude immutable save history at every depth."""
    for base, directories, files in os.walk(directory, **kwargs):
        directories[:] = sorted(name for name in directories if name != '.lishuttle-history')
        yield base, directories, sorted(files)


def ensure_runtime_resources(project_env, transaction=None):
    """补齐基础运行文件；现有运行配置、任务资源及 DLL 均不覆盖。"""
    if transaction is None:
        with FileTransaction() as transaction:
            return ensure_runtime_resources(project_env, transaction=transaction)
    project = os.path.realpath(to_native(project_env['PROJECT_DIR']))
    exe_dir = os.path.realpath(os.path.join(project, to_native(project_env['BUILD_SUBDIR']), 'Bin'))
    sources = [('基础配置', project_env.get('CONFIG_SRC', 'ThirdPart/Config')),
               ('动态库', project_env.get('DLL_SRC', 'ThirdPart/Dll/Release'))]
    roots = []
    for label, relative in sources:
        if not relative:
            raise ValueError(f'{label}源目录未配置')
        source = os.path.realpath(os.path.join(project, to_native(relative)))
        if not os.path.isdir(source):
            raise ValueError(f'找不到{label}源目录：{source}')
        try:
            overlap = os.path.commonpath([source, exe_dir]) in (source, exe_dir)
        except ValueError:
            overlap = False
        if overlap:
            raise ValueError(f'{label}源目录与 Bin 不能互相包含：{source}')
        roots.append(source)

    # 与 stage_local.bat 顺序一致：Config → DLL → config/*.xml 平铺。
    # 同名文件在内存中先确定最终来源，不在磁盘上反复覆盖。
    plan = {}
    def walk_error(error):
        raise error
    for (label, _), source in zip(sources, roots):
        file_count = 0
        for base, dirs, files in resource_walk(source, onerror=walk_error):
            dirs.sort()
            for name in sorted(files):
                if name.lower().endswith(('.bak', '.tmp', '.task-bak')):
                    continue
                path = os.path.join(base, name)
                if os.path.islink(path):
                    raise ValueError(f'基础资源不支持符号链接：{path}')
                plan[os.path.relpath(path, source)] = path
                file_count += 1
        if not file_count:
            raise ValueError(f'{label}源目录没有可装配文件：{source}')
    config_dir = os.path.join(roots[0], 'config')
    if os.path.isdir(config_dir):
        for name in sorted(os.listdir(config_dir)):
            path = os.path.join(config_dir, name)
            if name.lower().endswith('.xml') and os.path.isfile(path):
                plan[name] = path
    if not plan:
        raise ValueError('基础运行资源源目录为空，未执行装配')

    pending, kept = [], 0
    for relative, source in plan.items():
        destination = os.path.join(exe_dir, relative)
        if os.path.isfile(destination):
            kept += 1
            continue
        if os.path.lexists(destination):
            raise ValueError(f'基础文件目标被目录或链接占用：{destination}')
        parent = os.path.dirname(destination)
        while parent != os.path.dirname(parent):
            if os.path.exists(parent) and not os.path.isdir(parent):
                raise ValueError(f'基础资源目标目录被文件占用：{parent}')
            parent = os.path.dirname(parent)
        pending.append((source, destination, relative))

    copied = []
    for source, destination, relative in pending:
        transaction.copy(source, destination)
        copied.append(dict(file=relative, **{'from': to_slash(source)},
                           to=to_slash(destination), backup='补齐缺失基础文件'))
    return dict(copied=copied, kept_count=kept, exe_dir=to_slash(exe_dir),
                config_source=to_slash(roots[0]), dll_source=to_slash(roots[1]))


def assemble_files(task, project_env, groups=('antenna', 'model'), transaction=None):
    """任务包共用文件 → 替换进 exe 目录（先备份）。返回动作清单。

    规则（对 antenna/models 两组一致）：
    - 任务有 <name>.xml → 复制它（原文件备份 .bak）
    - 任务有 antenna/、antennas/ 或 models/ 子文件夹 → 整夹内容同步（antenna.xml 引用的
      方向图就住在这种文件夹里，缺了会报 Load3DGainFile 错误并回退默认方向图）
    - 只有文件夹没有 xml → 同步整夹 + 恢复项目默认 xml
    - 什么都没有 → 恢复项目默认 xml（撤销上一个任务的替换——否则上一个室外
      任务的 antenna.xml 会留在 exe 里，室内任务加载到不存在的天线型号会
      直接中止，实测 0xC0000409）
    """
    if transaction is None:
        with FileTransaction() as transaction:
            return assemble_files(task, project_env, groups=groups, transaction=transaction)
    exe_dir = f"{to_slash(project_env['PROJECT_DIR'])}/{project_env['BUILD_SUBDIR']}/Bin"
    actions = []
    for key, sub in (("antenna", "antennas"), ("model", "models")):
        if key not in groups:
            continue
        src = task.get(key) if task else ""
        dst_dir = os.path.join(exe_dir, sub)
        os.makedirs(dst_dir, exist_ok=True)
        base = "antenna.xml" if key == "antenna" else "LiShuttleModel.xml"

        # 收集要复制的目标：(源绝对路径, 目标相对名)
        targets = []
        if src:
            targets.append((src, os.path.basename(src)))
        extra_dir = task.get(f"{key}_dir") if task else ""
        if extra_dir and os.path.isdir(extra_dir):
            for base_d, _, files_d in resource_walk(extra_dir):
                rel = os.path.relpath(base_d, extra_dir)
                for f in files_d:
                    if f.lower().endswith(".bak"):
                        continue
                    targets.append((os.path.join(base_d, f),
                                    f if rel == "." else os.path.join(rel, f)))

        if targets:
            seen_dst = set()
            for s, rel_name in targets:
                if not os.path.isfile(s) or rel_name in seen_dst:
                    continue
                seen_dst.add(rel_name)
                dst = os.path.join(dst_dir, rel_name)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                note = ""
                if os.path.isfile(dst):
                    note = "已备份原文件"
                transaction.copy(s, dst, backup=True)
                actions.append({"file": rel_name, "from": to_slash(s),
                                "to": to_slash(dst), "backup": note})

        # "恢复默认"必须以 SVN 检出的仓库 ThirdPart/Config 为唯一基线。
        # 不能用 .bak——它是单层的，反复切换任务包后 .bak 里存的是上一个
        # 任务的版本，恢复出来照样是错的天线库（实测导致室内 FATAL）。
        # 仅在任务没有自带 xml 时执行；带了就不动。
        if not src:
            baseline = os.path.join(to_native(project_env["PROJECT_DIR"]),
                                    to_native(project_env["CONFIG_SRC"]), sub, base)
            dst = os.path.join(dst_dir, base)
            if os.path.isfile(baseline):
                note = ""
                if os.path.isfile(dst):
                    note = "（覆盖前已备份）"
                transaction.copy(baseline, dst, backup=True)
                actions.append({"file": base, "from": to_slash(baseline),
                                "to": to_slash(dst), "backup": f"已恢复仓库基线{note}"})
            elif os.path.isfile(dst):
                # 仓库基线本来就没有这个文件（项目自带 antennas 目录不含
                # antenna.xml）→ 默认状态就是"没有"，删掉上一个任务留下的
                transaction.copy(dst, dst + '.task-bak')
                transaction.touch(dst)
                os.remove(dst)
                actions.append({"file": base, "from": "-", "to": to_slash(dst),
                                "backup": "项目默认无此文件，已移除任务残留（.task-bak）"})
    return actions


# ----------------------------------------------------------------------
# 任务 XML 参数读写（文件即唯一事实；正则定点替换保留其余内容）
# ----------------------------------------------------------------------

def schema_path(schema_name):
    from runtime_configs import resolve_runtime_config
    return str(resolve_runtime_config(load_env(), schema_name))


def read_schema(schema_name):
    path, document = read_schema_document(schema_name)
    if document is None:
        return None, {}, path
    return path, document['values'], document['name']


def read_schema_document(schema_name):
    path = schema_path(schema_name)
    if not os.path.isfile(path):
        return path, None
    with open(path, 'rb') as fh:
        raw = fh.read()
    document = parse_document(raw)
    document['revision'] = hashlib.sha256(raw).hexdigest()
    return to_slash(path), document


def schema_inputs(schema_name, document=None):
    """The selected XML, including relative paths, owns its editor inputs."""
    if document is None:
        _, document = read_schema_document(schema_name)
    if document is None:
        return {'engineering_file': '', 'reason': '运行 XML 不存在，请重新选择'}
    field = document['fields'].get('EngineeringFilePath')
    if not field or len(field['occurrences']) != 1 or not field['value'].strip():
        return {'engineering_file': '', 'reason': (field or {}).get('read_only_reason') or '当前 XML 未定义有效工参路径'}
    value = field['value'].strip().replace('\\', '/')
    if not os.path.isabs(value):
        value = os.path.join(os.path.dirname(os.path.dirname(schema_path(schema_name))), value)
    return {'engineering_file': to_slash(os.path.normpath(value)), 'reason': ''}


def load_spec():
    with open(SPEC_FILE, encoding="utf-8") as fh:
        return json.load(fh)


# 真正的 -f 运行功能（这些宏对应的才注册了引擎）。
# 不在此列的 *_SERVICE 是内部服务（material/geo/basestation 等），不能当 -f 用。
RUN_FUNC_MACROS = {
    "INNER_DEBUG_SERVICE", "PATHLOSS_CALC_SERVICE", "PATHLOSS_INDOOR_SERVICE",
    "PATHLOSS_HYBRID_SERVICE", "HYBRID_RAYS_SERVICE", "PM_CALIBRATION_SERVICE",
    "DT_ANALYZE_SERVICE", "PM_AI_SERVICE", "COVERAGE_PREDICT_SERVICE",
    "COVERAGE_PREDICT_INDOOR_SERVICE", "ACP_SERVICE", "RAYS_RECORD_SERVICE",
    "INDOOR_RAYS_RECORD_SERVICE", "PM_SCENE_CLASSIFY_SERVICE",
    "BUILDING_DEBUG_SERVICE", "COMMUNICATION_SENSING_SERVICE",
}


def scan_functions(project_dir=None):
    """从项目的 SwanUtility/incl/LiShuttleTypes.h 解析可用的 -f 值。

    这个头文件是 GB18030 编码（用普通 grep/UTF-8 读会全部漏掉），并且是
    -f 取值的权威来源——readme.txt 不全（缺 predindoor），换项目还会变
    （如部分版本多出 plhybrid/hybridrays）。所以按项目现读。
    """
    env = load_env()
    proj = project_dir or env["PROJECT_DIR"]
    header = os.path.join(to_native(proj), "SwanUtility", "incl", "LiShuttleTypes.h")
    names = []
    if os.path.isfile(header):
        with open(header, "rb") as stream:
            raw = stream.read()
        text = ""
        for enc in ("gb18030", "utf-8"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        for line in text.splitlines():
            m = re.match(r'\s*#define\s+(\w+)\s+"([^"]+)"', line)
            if m and m.group(1) in RUN_FUNC_MACROS:
                names.append(m.group(2))
    return list(dict.fromkeys(names))   # 去重、保序


def ordered_functions():
    """项目实际支持的功能，附加中文名；字典里有说明的排前面。"""
    spec = load_spec()
    labels = {f["name"]: f for f in spec.get("function_info", [])}
    avail = scan_functions()
    if not avail:                                   # 项目还没检出/解析失败
        avail = [f["name"] for f in spec.get("function_info", [])]
    out = []
    for name in avail:
        info = labels.get(name)
        out.append({"name": name,
                    "label": info["label"] if info else name,
                    "desc": info["desc"] if info else "（参数字典未收录此功能）"})
    return out


def radius_source(schema_name):
    """The running XML selects the CSV; its default radius stays a fallback."""
    path, document = read_schema_document(schema_name)
    values = document['values'] if document else {}
    result = dict(kind='engineering_csv', fallback=values.get('DefaultCalcRadius', ''),
                  path='', column='', values=[], editable=False,
                  schema_revision=document['revision'] if document else '')
    selected = values.get('EngineeringFilePath', '')
    if not path or not selected:
        return dict(result, reason='运行配置没有有效工参路径，请先选择并同步工参')
    if not os.path.isabs(selected):
        selected = os.path.join(os.path.dirname(os.path.dirname(path)), selected)
    result['path'] = to_slash(os.path.normpath(selected))
    grid = read_csv_grid(selected, bin_dir=os.path.dirname(os.path.dirname(path)),
                         indoor=values.get('MapFormat', '').lower() == 'indoor')
    if 'error' in grid:
        return dict(result, reason=grid['error'])
    result.update(revision=grid['revision'], format_revision=grid['format_revision'],
                  header_lines=grid['header_lines'])
    if not grid['editable']:
        return dict(result, reason=grid['read_only_reason'])
    index = grid['columns'].get('CalcRadius')
    if index is None:
        return dict(result, reason='工参没有 CalcRadius / 计算半径列，请在工参 CSV 中补充后再修改')
    name = next((header[index] for header in grid['header_rows'] if len(header) > index and
                 normalized(header[index]) in {normalized(alias) for alias in ALIASES['CalcRadius']}), 'CalcRadius')
    radii = list(dict.fromkeys(row[index] if len(row) > index else '' for row in grid['rows'] if any(row)))
    return dict(result, column=name, column_index=index, values=radii, editable=bool(radii),
                reason='' if radii else '工参没有小区数据')


def write_cell_radius(schema_name, value, expected_revision=None, source_revision=None,
                      format_revision=None, return_revision=False):
    try:
        radius = float(value)
    except (ValueError, TypeError):
        return False, '计算半径必须是有效的正数（米）'
    if not math.isfinite(radius) or radius <= 0:
        return False, '计算半径必须是有效的正数（米）'
    source = radius_source(schema_name)
    _, schema_document = read_schema_document(schema_name)
    if schema_document is None or schema_document['revision'] != source['schema_revision']:
        raise FileConflict('运行 XML 已变化，请重新加载后再保存')
    if expected_revision is not None and source['schema_revision'] != expected_revision:
        raise FileConflict('运行 XML 已变化，请重新加载后再保存')
    if source_revision is not None and source.get('revision') != source_revision:
        raise FileConflict('工参 CSV 已变化，请重新加载后再保存')
    if format_revision is not None and source.get('format_revision') != format_revision:
        raise FileConflict('工参格式已变化，请重新加载后再保存')
    if not source['editable']:
        return False, source['reason']
    def check_source():
        if file_revision(schema_path(schema_name)) != source['schema_revision']:
            raise FileConflict('运行 XML 已变化，请重新加载后再保存')
    result = set_csv_column(source['path'], source['column'], value,
                            expected_revision=source['revision'],
                            expected_format_revision=source['format_revision'],
                            bin_dir=os.path.dirname(os.path.dirname(schema_path(schema_name))),
                            indoor=schema_document['values'].get('MapFormat', '').lower() == 'indoor',
                            column_index=source['column_index'], return_revision=return_revision,
                            before_write=check_source)
    ok, message = result[:2]
    final = (ok, f'工参 CSV：{source["path"]}；{message}；XML 默认半径保持不变')
    return (*final, result[2], schema_document['values']) if return_revision and len(result) > 2 else final


def write_schema_param(schema_name, tag, value, expected_revision=None,
                       source_revision=None, format_revision=None, return_revision=False):
    """把 <tag>old</tag> 定点替换为新值；其余内容逐字节保留。先备份 .bak。"""
    if tag == 'DefaultCalcRadius':
        return write_cell_radius(schema_name, value, expected_revision, source_revision,
                                 format_revision, return_revision)
    path = schema_path(schema_name)
    if not os.path.isfile(path):
        return False, f"找不到运行单：{path}"
    with open(path, 'rb') as fh:
        raw = fh.read()
    read_revision = hashlib.sha256(raw).hexdigest()
    if expected_revision is not None and expected_revision != read_revision:
        raise FileConflict('运行 XML 已变化，请重新加载后再保存')
    try:
        replacement = replace_scalar(raw, tag, value)
        document = parse_document(replacement)  # Reject invalid XML characters before writing or backing up.
    except (ValueError, ET.ParseError) as exc:
        return False, str(exc)
    new_revision = atomic_write(path, replacement, backup=True, expected_revision=read_revision)
    result = (True, f"{tag} -> {value}（原文件已备份 .bak）")
    return (*result, new_revision, document['values']) if return_revision else result


# ----------------------------------------------------------------------
# 工参 CSV 读写
# ----------------------------------------------------------------------

def _csv_decoded(raw):
    for enc in ('utf-8-sig', 'gb18030'):
        try:
            return raw.decode(enc), ('utf-8' if enc == 'utf-8-sig' and not raw.startswith(b'\xef\xbb\xbf') else enc)
        except UnicodeDecodeError:
            continue
    raise ValueError('文件不是 UTF-8 或 GB18030 文本')


def csv_editor_context(path, schema_name=''):
    env = load_env()
    bin_dir = os.path.join(env.get('PROJECT_DIR', ''), env.get('BUILD_SUBDIR', ''), 'Bin')
    indoor = engineering_kind(path) == 'indoor'
    if schema_name:
        schema_file, document = read_schema_document(schema_name)
        if document is None:
            raise ValueError('运行 XML 不存在，请重新装配后加载工参')
        bin_dir = os.path.dirname(os.path.dirname(schema_file))
        indoor = indoor or document['values'].get('MapFormat', '').lower() == 'indoor'
    return dict(bin_dir=bin_dir, indoor=indoor)


def read_csv_grid(path, bin_dir=None, indoor=False):
    if not os.path.isfile(path):
        return {"error": f"找不到文件：{path}"}
    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
        text, enc = _csv_decoded(raw)
        rows = list(csv.reader(io.StringIO(text), strict=True))
    except (OSError, ValueError, csv.Error) as exc:
        return {'error': f'工参 CSV 无法安全解析，未执行编辑：{exc}'}
    layout = grid_layout(rows, bin_dir=bin_dir, indoor=indoor)
    headers = rows[:layout['header_lines']]
    return {
        "path": to_slash(path), "encoding": enc,
        "newline": '\r\n' if '\r\n' in text else '\n',
        "revision": hashlib.sha256(raw).hexdigest(),
        "format_revision": layout['revision'], "format_source": layout['source'],
        "header_lines": layout['header_lines'], "header_rows": headers,
        "header_zh": headers[0] if headers else [],
        "header_en": headers[1] if len(headers) > 1 else [],
        "rows": rows[layout['header_lines']:], "columns": layout['columns'],
        "editable": layout['editable'], "read_only_reason": layout['error'],
    }


def save_csv_grid(path, header_zh, header_en, rows, expected_revision=None,
                  expected_format_revision=None, header_rows=None, header_lines=None,
                  bin_dir=None, indoor=False, return_revision=False):
    """整表写回（前端可编辑单元格）。先备份 .bak。"""
    grid = read_csv_grid(path, bin_dir=bin_dir, indoor=indoor)
    if 'error' in grid:
        return False, grid['error']
    if expected_revision is not None and grid['revision'] != expected_revision:
        raise FileConflict('工参 CSV 已变化，请重新加载后再保存')
    if expected_format_revision is not None and grid['format_revision'] != expected_format_revision:
        raise FileConflict('工参格式已变化，请重新加载后再保存')
    if not grid['editable']:
        return False, grid['read_only_reason']
    if header_rows is None:
        header_rows = [header_zh, header_en]
    if header_lines is None:
        header_lines = len(header_rows)
    if header_lines != grid['header_lines'] or len(header_rows) != header_lines:
        return False, '表头格式已变化，请重新加载'
    if header_zh is not None and header_zh != (header_rows[0] if header_rows else []):
        return False, '表头字段不一致'
    if header_en is not None and header_en != (header_rows[1] if len(header_rows) > 1 else []):
        return False, '表头字段不一致'
    buf = io.StringIO()
    enc = grid['encoding']
    writer = csv.writer(buf, lineterminator=grid['newline'])
    writer.writerows(header_rows)
    writer.writerows(rows)
    _check_csv_format(grid, bin_dir, indoor)
    revision = atomic_write(path, buf.getvalue().encode(enc), backup=True,
                            expected_revision=grid['revision'])
    result = (True, to_slash(path))
    return (*result, revision) if return_revision else result


def _check_csv_format(grid, bin_dir, indoor):
    current = grid_layout([], bin_dir=bin_dir, indoor=indoor)['revision']
    if current != grid['format_revision']:
        raise FileConflict('工参格式已变化，请重新加载后再保存')


def set_csv_column(path, column_key, value, expected_revision=None,
                   expected_format_revision=None, bin_dir=None, indoor=False,
                   column_index=None, return_revision=False, before_write=None):
    """整列批量设置：column_key 按中英文列名匹配（大小写不敏感）。先备份。"""
    grid = read_csv_grid(path, bin_dir=bin_dir, indoor=indoor)
    if 'error' in grid:
        return False, grid['error']
    if expected_revision is not None and grid['revision'] != expected_revision:
        raise FileConflict('工参 CSV 已变化，请重新加载后再保存')
    if expected_format_revision is not None and grid['format_revision'] != expected_format_revision:
        raise FileConflict('工参格式已变化，请重新加载后再保存')
    if not grid['editable']:
        return False, grid['read_only_reason']
    enc, newline = grid['encoding'], grid['newline']
    rows = [row[:] for row in grid['header_rows'] + grid['rows']]
    col = grid['columns'].get(column_key, -1)
    key = normalized(column_key)
    if col < 0:
        matches = {i for header in grid['header_rows'] for i, name in enumerate(header)
                   if normalized(name) == key}
        if len(matches) > 1:
            return False, f'列名重复，无法确认要修改哪一列：{column_key}'
        if matches:
            col = matches.pop()
    if col < 0:
        return False, f"找不到列：{column_key}"
    if column_index is not None and column_index != col:
        return False, '列位与工参格式不一致'
    changed = 0
    for r in range(grid['header_lines'], len(rows)):
        if not any(rows[r]):
            continue
        while len(rows[r]) <= col:
            rows[r].append("")
        if rows[r][col] != value:
            rows[r][col] = value
            changed += 1
    buf = io.StringIO()
    csv.writer(buf, lineterminator=newline).writerows(rows)
    _check_csv_format(grid, bin_dir, indoor)
    if before_write is not None:
        before_write()
    revision = atomic_write(path, buf.getvalue().encode(enc), backup=True,
                            expected_revision=grid['revision'])
    result = (True, f"列[{column_key}] -> {value}，影响{changed}行（已备份）")
    return (*result, revision) if return_revision else result


# ----------------------------------------------------------------------
# 进程运行器（lishuttle / 体检 / 编译 / 装配 共用）
# ----------------------------------------------------------------------

RUNTIME = RuntimeGuard()


def build_toolchain_root(config):
    """Use the environment script actually selected by the build first."""
    vcvars = config.get('VCVARS', '')
    if vcvars:
        script = os.path.realpath(vcvars)
        if re.search(r'/VC/Auxiliary/Build/vcvars(?:64|all)\.bat$', script.replace('\\', '/'), re.I):
            return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(script))))
    return config.get('VS_ROOT') or None


def build_cleanup_diagnostic(session):
    if session.get('status') == 'done':
        return ''
    return str(getattr(session.get('tree'), 'cleanup_error', '') or session.get('cleanup_note') or '')


class Runner:
    def __init__(self, guard=None, history=None):
        self.sessions = {}
        self.lock = threading.RLock()
        # Numeric for existing clients, unique across service restarts (< JS 2**53).
        self.counter = secrets.randbits(51)
        self.guard = guard if guard is not None else RUNTIME
        self.history = history

    def start(self, cmd, cwd, label, env=None, context=None, baseline=None, finalize=None):
        context = deepcopy(context or {})
        if context.get('operation') == 'build':
            source_project = context.get('project') or (context.get('project_config') or {}).get('PROJECT_DIR')
            if source_project:
                context['source_project'] = source_project
        with self.guard.operation(label, context) as token:
            self.guard.acquire_resources(token, context)
            with self.lock:
                self.counter += 1
                sid = self.counter
            if self.history:
                record = self.history.create(sid, label, context, cmd, cwd, baseline=baseline)
                if record.get('snapshot_issues'):
                    message = '运行输入快照保存失败，未启动引擎：' + '；'.join(
                        item.get('message', '') for item in record['snapshot_issues'])
                    self.history.finish(sid, 'done', None, {'verdict': 'failed',
                        'process': {'status': 'snapshot_failed', 'exit': None}}, internal_error=message)
                    raise OSError(message)
            try:
                process_options = {}
                cleanup_note = ''
                if context.get('operation') == 'build':
                    process_options['build_toolchain_root'] = build_toolchain_root(context.get('project_config') or {})
                    if not process_options['build_toolchain_root']:
                        cleanup_note = '无法确认所选 VS 工具链位置，安全等待进程树结束；未自动回收辅助进程。请核对 VCVARS 或 VS_ROOT。'
                tree = ManagedProcess(cmd, cwd, env=env, **process_options)
            except BaseException as exc:
                if self.history:
                    try:
                        self.history.finish(sid, 'done', None, {'verdict': 'failed',
                            'process': {'status': 'spawn_failed', 'exit': None}}, internal_error=str(exc))
                    except Exception:
                        pass  # Preserve the original launch failure.
                raise
            proc = tree.proc
            try:
                with self.lock:
                    self.sessions[sid] = {"proc": proc, "tree": tree, "lines": [], "status": "running",
                                          "label": label, "exit": None, "context": context,
                                          "cancelled": False, "internal_error": '', "result": None,
                                          'cleanup_note': cleanup_note,
                                          "token": token, 'done_event': threading.Event()}
                    self.guard.bind(token, sid, context)
            except BaseException:
                tree.terminate()
                tree.wait()
                tree.close()
                raise

            def pump():
                s = self.sessions[sid]
                try:
                    for line in proc.stdout:
                        line = line.rstrip('\r\n')
                        with self.lock:
                            s['lines'].append(line)
                        if self.history:
                            self.history.append(sid, line)
                except Exception as exc:
                    with self.lock:
                        s['internal_error'] = f'日志读取失败：{exc}'
                    try:
                        tree.terminate()
                    except Exception as stop_error:
                        with self.lock:
                            s['internal_error'] += f'；终止失败：{stop_error}'
                finally:
                    try:
                        proc.stdout.close()
                    except Exception:
                        pass
                # A root process can exit while build/engine children still run.
                # Keep the lease, even on a monitoring error, until exit is confirmed.
                while True:
                    try:
                        code = tree.wait()
                        break
                    except Exception as exc:
                        with self.lock:
                            s['internal_error'] = f'等待进程树退出失败：{exc}'
                        time.sleep(.1)
                self.guard.set_phase(token, 'finalizing')
                with self.lock:
                    s.update(status='finalizing', exit=code)
                    lines, cancelled = list(s['lines']), s['cancelled']
                try:
                    if finalize:
                        result = finalize(context, baseline, lines, code, cancelled=cancelled)
                    else:
                        verdict = ('cancelled' if cancelled else 'failed' if code else
                                   'unconfirmed' if context.get('func') else 'success')
                        result = {'verdict': verdict, 'process': {'exit': code, 'status': 'done'},
                                  'artifacts': {'status': 'unconfirmed' if context.get('func') else 'not_applicable'},
                                  'business': {'status': 'unconfirmed' if context.get('func') else 'not_applicable'}}
                    if s['internal_error'] and result.get('verdict') == 'success':
                        result['verdict'] = 'unconfirmed'
                except Exception as exc:
                    with self.lock:
                        s['internal_error'] = f'结果验证失败：{exc}'
                    result = {'verdict': 'cancelled' if cancelled else 'failed' if code else 'unconfirmed',
                              'process': {'exit': code, 'status': 'done'},
                              'artifacts': {'status': 'unconfirmed'}, 'business': {'status': 'unconfirmed'},
                              'issues': [{'severity': 'error', 'code': 'VALIDATION_ERROR',
                                          'message': str(exc), 'path': context.get('out_dir', '')}]}
                finally:
                    try:
                        tree.close()
                    except Exception as exc:
                        with self.lock:
                            s['internal_error'] += f'；关闭进程句柄失败：{exc}'
                        if result.get('verdict') == 'success':
                            result['verdict'] = 'unconfirmed'
                if self.history:
                    try:
                        record = self.history.finish(sid, 'done', code, result,
                            cancelled=cancelled, internal_error=s['internal_error'])
                        s['archive'] = record.get('archive', {})
                    except Exception as exc:
                        s['internal_error'] += f'；运行记录或归档保存失败：{exc}'
                        s['archive'] = {'status': 'incomplete', 'dir': str(self.history.root / str(sid)),
                                        'issues': [{'message': str(exc)}]}
                        if result.get('verdict') == 'success':
                            result['verdict'] = 'unconfirmed'
                        result.setdefault('issues', []).append({'severity': 'error',
                            'code': 'HISTORY_SAVE_FAILED', 'message': str(exc), 'path': str(self.history.root)})
                with self.lock:
                    s.update(result=result, status='done')
                    self.guard.release(token)
                    s['done_event'].set()

            try:
                threading.Thread(target=pump, daemon=True).start()
            except BaseException as exc:
                with self.lock:
                    s = self.sessions[sid]
                    s['internal_error'] = f'无法启动进程监控：{exc}'
                    # If termination also fails, a later stop/shutdown can
                    # finish the same monitor synchronously without a new thread.
                    s['recover_pump'] = pump
                try:
                    tree.terminate()
                except Exception as stop_error:
                    with self.lock:
                        s['internal_error'] += f'；终止失败，可重试：{stop_error}'
                else:
                    with self.lock:
                        recover = s.pop('recover_pump', None)
                    if recover:
                        recover()
                raise
            return sid

    def output(self, sid, since=0, limit=None):
        with self.lock:
            s = self.sessions.get(sid)
            if s:
                diagnostic = build_cleanup_diagnostic(s)
                start = max(0, int(since))
                end = len(s['lines']) if limit is None else min(len(s['lines']), start + max(1, min(5000, int(limit))))
                return deepcopy({"lines": s["lines"][start:end], "total": len(s["lines"]),
                                 'next_since': min(end, len(s['lines'])), 'has_more': end < len(s['lines']),
                                 "status": s["status"], "exit": s["exit"], "label": s["label"],
                                 'context': s.get('context', {}), 'result': s.get('result'),
                                 'archive': s.get('archive', {}),
                                 'cancelled': s.get('cancelled', False), 'cleanup_error': diagnostic,
                                 'internal_error': '；'.join(filter(None, [s.get('internal_error', ''), diagnostic]))})
        if self.history:
            return self.history.output(sid, since=since, limit=limit)
        return {"error": "会话不存在", 'code':'SESSION_NOT_FOUND'}

    def stop(self, sid):
        with self.lock:
            s = self.sessions.get(sid)
            if not s or s['status'] in ('done', 'finalizing'):
                return False
            if s.get('cancelled'):
                return True
            s.update(cancelled=True, status='cancelling')
            self.guard.set_phase(s['token'], 'cancelling')
            try:
                s['tree'].terminate()
            except Exception as exc:
                s.update(cancelled=False, status='running', internal_error=f'停止失败，可重试：{exc}')
                self.guard.set_phase(s['token'], 'running')
                raise
            recover = s.pop('recover_pump', None)
        if recover:
            recover()
        return True

    def shutdown(self):
        with self.lock:
            active = [sid for sid, s in self.sessions.items() if s['status'] != 'done']
        for sid in active:
            # The HTTP server must not exit while daemon monitors are still
            # waiting on a killed child or validating its final products.
            event = self.sessions[sid]['done_event']
            while not event.is_set():
                try:
                    self.stop(sid)
                except Exception:
                    pass  # stop records the diagnostic and remains retryable.
                event.wait(.1)


RUNNER = Runner(history=RunHistory(os.path.join(ROOT, '.lishuttle-runs')))


def runtime_resources(env, source=False):
    project = env.get('PROJECT_DIR', '')
    resources = {'project': project,
            'bin_dir': os.path.realpath(os.path.join(project, env.get('BUILD_SUBDIR', ''), 'Bin')) if project else '',
            'out_dir': env.get('OUT_ROOT', '')}
    if source and project:
        resources['source_project'] = project
    return resources


def runtime_state(env=None):
    state = RUNTIME.snapshot()
    if state['busy']:
        return state
    try:
        return RUNTIME.external_snapshot(runtime_resources(env if env is not None else load_env(), source=True))
    except OSError as exc:
        return dict(state, check_error=f'无法检查其他平台占用：{exc}')


def sync_vs_launch(project_env, schema_name, func, task_id, city_kind, previous_schema=''):
    return sync_launch(project_env, schema_name, func, task_id, city_kind,
                       scan_functions(project_env['PROJECT_DIR']), previous_schema=previous_schema)


class PreflightRejected(ValueError):
    def __init__(self, report):
        self.report = report
        errors = [item['message'] for item in report['issues'] if item['severity'] == 'error']
        super().__init__('运行前检查未通过：' + ('；'.join(errors[:3]) or '输入无法确认'))


def check_run(schema_name, func, task_id):
    from preflight import check_run as inspect_run
    try:
        path = schema_path(schema_name)
    except (ValueError, OSError) as exc:
        return {'ok': False, 'issues': [{'severity': 'error', 'code': 'SCHEMA_NAME_INVALID',
                'message': str(exc), 'field': 'schema', 'path': schema_name}],
                'context': {}}
    report = inspect_run(load_env(), path, func, str(task_id))
    report['context']['schema_name'] = schema_name
    return report


def start_lishuttle(schema_name, func, task_id):
    """直接起 lishuttle.exe（工作目录=exe 目录），不经 bat。"""
    with RUNTIME.operation('运行 ' + func) as token:
        env = load_env()
        RUNTIME.acquire_resources(token, runtime_resources(env))
        try:
            validate_operation(env, 'run')
        except ValueError as exc:
            return None, str(exc)
        report = check_run(schema_name, func, task_id)
        if not report['ok']:
            raise PreflightRejected(report)
        from result_validation import snapshot, validate
        context = deepcopy(report['context'])
        context['project_config'] = dict(env)
        context['preflight_issues'] = report['issues']
        RUNTIME.acquire_resources(token, context)
        baseline = snapshot(context)
        exe, cwd = context['exe'], context['bin_dir']
        cmd = [exe, '-f', func, '-t', str(task_id), '-c', schema_name]
        sid = RUNNER.start(cmd, cwd, f'-f {func} -t {task_id} -c {schema_name}',
                           context=context, baseline=baseline, finalize=validate)
        return sid, to_slash(exe)


def start_toolkit(step):
    """doctor/build/stage：批处理封装。"""
    with RUNTIME.operation(step) as token:
        env = load_env()
        RUNTIME.acquire_resources(token, runtime_resources(env, source=step == 'build'))
        try:
            validate_operation(env, step)
        except ValueError as exc:
            return None, str(exc)
        bat = os.path.join(SCRIPTS, {"doctor": "doctor_local.bat", "build": "build_local.bat",
                                     "stage": "stage_local.bat"}[step])
        child_env = dict(os.environ, LISHUTTLE_CONFIG_SNAPSHOT=write_snapshot(env))
        binary = os.path.realpath(os.path.join(env['PROJECT_DIR'], env.get('BUILD_SUBDIR', ''), 'Bin'))
        sid = RUNNER.start(["cmd", "/d", "/c", bat], ROOT, step, env=child_env,
                           context={'project': env['PROJECT_DIR'], 'bin_dir': binary,
                                    'operation': step, 'project_config': dict(env)})
        return sid, to_slash(bat)


# ----------------------------------------------------------------------
# 结果查看
# ----------------------------------------------------------------------

def session_results(sid):
    runner = RUNNER
    # Only copy in-memory fields under the runner lock. Hashing historical
    # products must never block stdout collection or cancellation of a new run.
    with runner.lock:
        live = runner.sessions.get(sid)
        session = deepcopy({key: live.get(key) for key in
            ('status', 'exit', 'context', 'result', 'label', 'internal_error', 'archive')}) if live else None
        log_tail = list(live.get('lines', [])[-40:]) if live else []
        if session:
            session['internal_error'] = '；'.join(filter(None, [session.get('internal_error', ''), build_cleanup_diagnostic(live)]))
    record = runner.history.get(sid) if runner.history else None
    source = session or record
    if not source:
        return {'error': '会话不存在；目录浏览无法确认当时运行', 'code':'SESSION_NOT_FOUND'}
    context = deepcopy(source.get('context', {}))
    report = deepcopy(source.get('result'))
    if report is None:
        report = {'verdict': 'pending', 'process': {'status': source['status'], 'exit': source['exit']},
                  'artifacts': {'status': 'pending'}, 'business': {'status': 'pending'},
                  'files': [], 'log_tail': log_tail, 'errors': [], 'issues': []}
    directory = context.get('out_dir', '')
    report.update(sid=sid, associated=True, context=context, dir=directory,
                  status=source['status'], exit=source['exit'], label=source['label'],
                  internal_error=source.get('internal_error', ''), exists=bool(directory and os.path.isdir(directory)))
    report.setdefault('files', [])
    report.setdefault('log_tail', log_tail)
    report.setdefault('errors', [])
    report.setdefault('log_file', '')
    if runner.history:
        report.update(historical=True, historical_verdict=report.get('verdict', 'unconfirmed'),
                      current_files=runner.history.current(sid),
                      archive=source.get('archive') or (record or {}).get('archive', {}))
    return report


def recent_runs(project='', limit=20, offset=0):
    limit, offset = max(1, min(100, int(limit))), max(0, int(offset))
    if not RUNNER.history:
        return {'runs': [], 'total': 0, 'limit': limit, 'offset': offset}
    # The store supplies project filtering before pagination.
    records = RUNNER.history.list(project=project, limit=1000000)
    total = len(records)
    records = records[offset:offset + limit]
    with RUNNER.lock:
        for record in records:
            session = RUNNER.sessions.get(record['sid'])
            if session:
                for key in ('status', 'exit', 'label', 'result', 'internal_error', 'archive'):
                    if key in session:
                        record[key] = deepcopy(session[key])
    runs = [{key: value for key, value in record.items() if key in
             ('sid', 'label', 'created_at', 'finished_at', 'status', 'exit', 'context', 'result', 'archive')}
            for record in records]
    for run in runs:
        run['historical'] = True
        run['context'] = {key: value for key, value in run.get('context', {}).items() if key in
                          ('project', 'bin_dir', 'schema_name', 'task_name', 'func', 'task_id', 'out_dir', 'operation')}
        run['result'] = {'verdict': (run.get('result') or {}).get('verdict', 'pending')}
        run['archive'] = {key: value for key, value in run.get('archive', {}).items() if key in ('status', 'dir')}
    return {'runs': runs, 'total': total, 'limit': limit, 'offset': offset}


def results(job_name='', schema_name=''):
    env = load_env()
    out_dir = os.path.join(env.get("OUT_ROOT", '').replace("/", os.sep), job_name)
    manifest_path = schema_path(job_name + '.xml') + '.manifest.json' if job_name and not schema_name else ''
    if schema_name:
        path = schema_path(schema_name)
        out_dir = runtime_details(path, os.path.dirname(os.path.dirname(path)))['out_dir']
    elif os.path.isfile(manifest_path):
        with open(manifest_path, encoding='utf-8') as fh:
            manifest = json.load(fh)
        if manifest.get('schema_mode') == 'existing':
            out_dir = runtime_details(schema_path(job_name + '.xml'),
                                      os.path.dirname(os.path.dirname(manifest_path)))['out_dir']
    exe_dir = os.path.join(env["PROJECT_DIR"].replace("/", os.sep),
                           *env["BUILD_SUBDIR"].split("/"), "Bin")
    info = {"dir": to_slash(out_dir), "exists": os.path.isdir(out_dir),
            "files": [], "status": "", "log_tail": [], "errors": [],
            "log_file": "", 'associated': False, 'verdict': 'unconfirmed',
            'association_note': '目录浏览：未关联本次运行',
            'process': {'status': 'unassociated', 'exit': None},
            'artifacts': {'status': 'unconfirmed'}, 'business': {'status': 'unconfirmed'}}
    if not info["exists"]:
        return info
    for base, dirs, files in os.walk(out_dir):
        rel = os.path.relpath(base, out_dir)
        for f in files:
            p = os.path.join(base, f)
            info["files"].append({"rel": to_slash(os.path.normpath(os.path.join(rel, f))),
                                  "size": os.path.getsize(p)})
    info["files"].sort(key=lambda x: x["rel"])
    for f in os.listdir(out_dir):
        if f.startswith("jobstatus_"):
            info["status"] = f.replace("jobstatus_", "")
    # 引擎内部失败时程序也会写 jobstatus_end 且退出码 0（实测），
    # 所以"完成"还要看有没有真产物：只有状态文件 = 假完成
    data_files = [f for f in info["files"]
                  if not f["rel"].startswith("jobstatus_") and f["rel"] != "uplan.log"]
    info["empty_run"] = (info["status"] == "end" and len(data_files) == 0)
    # 日志来源：输出目录的 uplan.log 优先（run_local.bat 会归档到这里）；
    # 平台直接跑 exe 时日志落在 exe 目录，回退读它
    for log in (os.path.join(out_dir, "uplan.log"), os.path.join(exe_dir, "uplan.log")):
        if os.path.isfile(log):
            info["log_file"] = to_slash(log)
            with open(log, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            info["log_tail"] = [l.rstrip() for l in lines[-40:]]
            info["errors"] = [l.rstrip() for l in lines if "ERROR" in l or "FATAL" in l][-20:]
            break
    return info


def to_slash(p):
    return str(p).replace("\\", "/")


def to_native(p):
    return str(p).replace("/", os.sep)
