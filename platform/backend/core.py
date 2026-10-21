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
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import hashlib
import html
import xml.etree.ElementTree as ET
from engineering import identify_engineering, validate_engineering

HERE = os.path.dirname(os.path.abspath(__file__))      # platform/backend
ROOT = os.path.dirname(os.path.dirname(HERE))          # 工作流根目录
SCRIPTS = os.path.join(ROOT, "scripts")
ENV_FILE = os.path.join(ROOT, "env", "local-win.env")
PROJECTS_FILE = os.path.join(ROOT, "env", "projects.json")
JOBS_DIR = os.path.join(ROOT, "jobs")
SPEC_FILE = os.path.join(HERE, "params_spec.json")

sys.path.insert(0, SCRIPTS)
from render_schema import read_env_file, build_table  # noqa: E402
from task_schema import schema_candidates, render_existing, runtime_details

TAG_RE = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)>([^<]*)</\1>")
CSV_ENCODINGS = ("utf-8-sig", "gb18030", "gbk")


# ----------------------------------------------------------------------
# 环境读写（平台选择持久化回 env 文件，保持 CLI 与 GUI 单一事实）
# ----------------------------------------------------------------------

def load_env():
    return read_env_file(ENV_FILE, "环境文件")


def save_env_keys(**kwargs):
    """把平台的选择写回 env 文件（只改对应 KEY 行，注释原样保留）。"""
    with open(ENV_FILE, "r", encoding="utf-8") as fh:
        lines = fh.readlines()
    for key, value in kwargs.items():
        pat = re.compile(rf"^(\s*){re.escape(key)}=.*$")
        replaced = False
        for i, line in enumerate(lines):
            if pat.match(line):
                lines[i] = f"{key}=\"{value}\"\n"
                replaced = True
                break
        if not replaced:
            lines.append(f"\n{key}=\"{value}\"\n")
    with open(ENV_FILE, "w", encoding="utf-8") as fh:
        fh.writelines(lines)


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


def thirdpart_defaults():
    """默认值源于当前项目样例；路径必须落在真实存在的配置源内。"""
    env = load_env()
    config = os.path.realpath(os.path.join(env['PROJECT_DIR'], env.get('CONFIG_SRC', 'ThirdPart/Config')))
    sample = os.path.join(config, 'runtimelibrary', 'runtimeschema.xml')
    try:
        root = ET.parse(sample).getroot()
    except (OSError, ET.ParseError):
        return {}
    if root.tag != 'RuntimeSchema':
        return {}
    path_tags = {p['name'] for p in load_spec()['params'] if p.get('type') == 'path'}
    path_tags.update(('BuildingPenetration', 'RoadsToBeRecorded', 'PredictedCells'))
    known = {'SceneSettingsPath': 'config/scenesettings.xml',
             'ClutterMatchPath': 'config/cluttermatchsettings.xml'}
    result = {}
    for node in root:
        value = node.text or ''
        item = dict(available=True, value=value, source=to_slash(sample), reason='')
        if node.tag in path_tags or node.tag.endswith(('Path', 'Directory')):
            item.update(available=False, value='', reason='ThirdPart 中没有可确认的默认资源，请选择任务数据路径')
            candidates = [os.path.join(config, known[node.tag])] if node.tag in known else []
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
        result[node.tag] = item
    return result


def _check(paths_labels):
    return [[label, to_slash(p), os.path.isfile(p)] for label, p in paths_labels]


def scan_cities():
    """地图目录 → 室外城市（heights/index.txt）/ 室内场景（building.das）。"""
    env = load_env()
    map_root = env["MAP_ROOT"]
    cities = []
    if not os.path.isdir(map_root):
        return cities, to_slash(map_root)
    for name in sorted(os.listdir(map_root)):
        full = os.path.join(map_root, name)
        if not os.path.isdir(full):
            continue
        if os.path.isfile(os.path.join(full, "heights", "index.txt")):
            checks = _check([
                ("投影", os.path.join(full, "heights", "projection.txt")),
                ("高程", os.path.join(full, "heights", "index.txt")),
                ("杂波", os.path.join(full, "clutter", "index.txt")),
                ("杂波菜单", os.path.join(full, "clutter", "menu.txt")),
                ("建筑", os.path.join(full, "buildings", "index.txt")),
                ("建筑矢量", os.path.join(full, "buildvector", "index.txt")),
            ])
            cities.append({"name": name, "kind": "outdoor", "checks": checks})
        elif os.path.isfile(os.path.join(full, "building.das")):
            checks = _check([("building.das", os.path.join(full, "building.das"))])
            cities.append({"name": name, "kind": "indoor", "checks": checks})
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
        full = os.path.join(gongcan, name)
        if os.path.isdir(full):
            csvs, txts, xmls = [], [], []
            antenna = model = scene = ""
            antenna_dir = model_dir = ""
            for base, dirs, files in os.walk(full):
                dirs.sort()
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
    for task in tasks:
        identify_engineering(task)
        task['schema_candidates'] = schema_candidates(task.get('xmls', []))
        task['has_antennas'] = bool(task.get('antenna')) or bool(task.get('antenna_dir')) and any(
            any(not f.lower().endswith('.bak') for f in files)
            for _, _, files in os.walk(task['antenna_dir'])
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
               FUNC=body.get('func', 'pl'), CITY=city,
               SCHEMA_SOURCE=source, SYNC_ENGINEERING='1' if body.get('sync_engineering') else '0',
               ENGINEERING_FILE=task.get('engineering_file', ''), POLYGON_FILE=polygon)
    if city_kind == 'indoor':
        job.update(TEMPLATE='runtimeschema-indoor.xml.tpl', MAP_PATH=env['MAP_ROOT'].rstrip('/') + '/' + city)
    table = build_table(env, job)
    preview = render_existing(table)
    destination = schema_path(job['SCHEMA_NAME'])
    if os.path.normcase(os.path.realpath(source)) == os.path.normcase(os.path.realpath(destination)):
        raise ValueError('源 XML 与目标文件相同，不能覆盖原始配置')
    task.update(schema_source=source, sync_engineering=bool(body.get('sync_engineering')), polygon_file=polygon)
    preview['destination'] = destination
    preview['token'] = hashlib.sha256((preview['token'] + '\0' + destination).encode('utf-8')).hexdigest()
    preview['warnings'] = []
    if not task['sync_engineering'] and preview['engineering_file']:
        engineering_path = preview['engineering_file'].replace('\\', '/')
        if not os.path.isabs(engineering_path):
            engineering_path = os.path.join(os.path.dirname(os.path.dirname(destination)), engineering_path)
        if not os.path.isfile(engineering_path):
            preview['warnings'].append('原 XML 的工参路径在当前运行位置不存在；可勾选“同步为当前工参”，或复制后手动调整')
    return {k: v for k, v in preview.items() if k != 'text'}


def build_job_env(job_name, func, task_id, task, city_name, city_kind):
    env = load_env()
    lines = [
        f'JOB_NAME="{job_name}"',
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
    job_file = os.path.join(JOBS_DIR, f"web-{job_name}.env")
    if task.get('schema_source'):
        lines += [f'SCHEMA_SOURCE="{task["schema_source"]}"',
                  f'SYNC_ENGINEERING="{1 if task.get("sync_engineering") else 0}"']
        # 区域由用户明确选择，不再猜测任务包的 index/WrongSites 等 TXT。
        lines = [f'POLYGON_FILE="{task.get("polygon_file", "")}"'
                 if line.startswith('POLYGON_FILE=') else line for line in lines]
    with open(job_file, "w", encoding="utf-8") as fh:
        fh.write("# 由平台生成，可手工编辑后用脚本复跑\n" + "\n".join(lines) + "\n")
    return to_slash(job_file)


def run_render(job_file):
    """调渲染脚本，返回 (退出码, 输出文本)。

    必须显式给子进程 PYTHONIOENCODING=utf-8：Python 的 stdout 被管道捕获时用的是
    系统 locale 编码（中文 Windows 上是 GBK），而这里按 UTF-8 解码；
    不固定编码就会整页乱码（实测就是这个原因导致渲染输出不可读）。
    """
    child_env = dict(os.environ)
    child_env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "render_schema.py"), job_file, "local-win"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT, env=child_env)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def assemble_files(task, project_env, groups=('antenna', 'model')):
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
            for base_d, _, files_d in os.walk(extra_dir):
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
                    shutil.copy2(dst, dst + ".bak")
                    note = "已备份原文件"
                shutil.copy2(s, dst)
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
                    shutil.copy2(dst, dst + ".bak")
                    note = "（覆盖前已备份）"
                shutil.copy2(baseline, dst)
                actions.append({"file": base, "from": to_slash(baseline),
                                "to": to_slash(dst), "backup": f"已恢复仓库基线{note}"})
            elif os.path.isfile(dst):
                # 仓库基线本来就没有这个文件（项目自带 antennas 目录不含
                # antenna.xml）→ 默认状态就是"没有"，删掉上一个任务留下的
                shutil.copy2(dst, dst + ".task-bak")
                os.remove(dst)
                actions.append({"file": base, "from": "-", "to": to_slash(dst),
                                "backup": "项目默认无此文件，已移除任务残留（.task-bak）"})
    return actions


# ----------------------------------------------------------------------
# 任务 XML 参数读写（文件即唯一事实；正则定点替换保留其余内容）
# ----------------------------------------------------------------------

def schema_path(schema_name):
    env = load_env()
    exe_dir = os.path.join(env["PROJECT_DIR"].replace("/", os.sep),
                           *env["BUILD_SUBDIR"].split("/"), "Bin", "runtimelibrary")
    return os.path.join(exe_dir, schema_name)


def read_schema(schema_name):
    path = schema_path(schema_name)
    if not os.path.isfile(path):
        return None, {}, path
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r'<RuntimeSchema\s+name="([^"]*)"', text)
    values = {}
    for tag, val in TAG_RE.findall(text):
        values.setdefault(tag, html.unescape(val))
    for tag in re.findall(r'<([A-Za-z_][A-Za-z0-9_]*)\s*/>', text):
        values.setdefault(tag, '')
    return to_slash(path), values, (m.group(1) if m else "")


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
        raw = open(header, "rb").read()
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


def write_schema_param(schema_name, tag, value):
    """把 <tag>old</tag> 定点替换为新值；其余内容逐字节保留。先备份 .bak。"""
    path = schema_path(schema_name)
    if not os.path.isfile(path):
        return False, f"找不到运行单：{path}"
    with open(path, 'rb') as fh:
        text = fh.read().decode('utf-8')
    pat = re.compile(rf"(<{re.escape(tag)}>)([^<]*)(</{re.escape(tag)}>)")
    empty_pat = re.compile(rf'<{re.escape(tag)}\s*/>')
    if not pat.search(text) and not empty_pat.search(text):
        return False, f"运行单里没有字段 <{tag}>"
    shutil.copy2(path, path + ".bak")
    escaped = html.escape(value, quote=False)
    if pat.search(text):
        new_text = pat.sub(lambda m: m.group(1) + escaped + m.group(3), text, count=1)
    else:
        new_text = empty_pat.sub(lambda m: f'<{tag}>{escaped}</{tag}>', text, count=1)
    with open(path, 'wb') as fh:
        fh.write(new_text.encode('utf-8'))
    return True, f"{tag} -> {value}（原文件已备份 .bak）"


# ----------------------------------------------------------------------
# 工参 CSV 读写
# ----------------------------------------------------------------------

def read_csv_grid(path):
    if not os.path.isfile(path):
        return {"error": f"找不到文件：{path}"}
    enc = sniff_csv_encoding(path)
    text = open(path, "r", encoding=enc, newline="").read()
    rows = list(csv.reader(io.StringIO(text)))
    return {
        "path": to_slash(path), "encoding": enc,
        "header_zh": rows[0] if rows else [],
        "header_en": rows[1] if len(rows) > 1 else [],
        "rows": rows[2:],
    }


def save_csv_grid(path, header_zh, header_en, rows):
    """整表写回（前端可编辑单元格）。先备份 .bak。"""
    enc = sniff_csv_encoding(path) if os.path.isfile(path) else "utf-8-sig"
    if os.path.isfile(path):
        shutil.copy2(path, path + ".bak")
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n" if "\r\n" in (
        open(path, encoding=enc, newline="").read(4096) if os.path.isfile(path) else "") else "\n")
    writer.writerow(header_zh)
    writer.writerow(header_en)
    writer.writerows(rows)
    open(path, "w", encoding=enc, newline="").write(buf.getvalue())
    return True, to_slash(path)


def set_csv_column(path, column_key, value):
    """整列批量设置：column_key 按中英文列名匹配（大小写不敏感）。先备份。"""
    enc = sniff_csv_encoding(path)
    text = open(path, "r", encoding=enc, newline="").read()
    newline = "\r\n" if "\r\n" in text else "\n"
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 3:
        return False, "表结构不符合（少于3行）"
    col = -1
    key = column_key.strip().lower()
    for r in (0, 1):
        for i, name in enumerate(rows[r]):
            if name.strip().lower() == key:
                col = i
                break
        if col >= 0:
            break
    if col < 0:
        return False, f"找不到列：{column_key}"
    shutil.copy2(path, path + ".bak")
    changed = 0
    for r in range(2, len(rows)):
        while len(rows[r]) <= col:
            rows[r].append("")
        if rows[r][col] != value:
            rows[r][col] = value
            changed += 1
    buf = io.StringIO()
    csv.writer(buf, lineterminator=newline).writerows(rows)
    open(path, "w", encoding=enc, newline="").write(buf.getvalue())
    return True, f"列[{column_key}] -> {value}，影响{changed}行（已备份）"


# ----------------------------------------------------------------------
# 进程运行器（lishuttle / 体检 / 编译 / 装配 共用）
# ----------------------------------------------------------------------

class Runner:
    def __init__(self):
        self.sessions = {}
        self.lock = threading.Lock()
        self.counter = 0

    def start(self, cmd, cwd, label):
        with self.lock:
            self.counter += 1
            sid = self.counter
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="gbk", errors="replace", shell=False)
        self.sessions[sid] = {"proc": proc, "lines": [], "status": "running",
                              "label": label, "exit": None}

        def pump():
            for line in proc.stdout:
                with self.lock:
                    self.sessions[sid]["lines"].append(line.rstrip("\r\n"))
            proc.wait()
            with self.lock:
                self.sessions[sid]["status"] = "done"
                self.sessions[sid]["exit"] = proc.returncode

        threading.Thread(target=pump, daemon=True).start()
        return sid

    def output(self, sid, since):
        with self.lock:
            s = self.sessions.get(sid)
            if not s:
                return {"error": "会话不存在"}
            return {"lines": s["lines"][since:], "total": len(s["lines"]),
                    "status": s["status"], "exit": s["exit"], "label": s["label"]}

    def stop(self, sid):
        with self.lock:
            s = self.sessions.get(sid)
        if s and s["status"] == "running":
            s["proc"].terminate()
            return True
        return False


RUNNER = Runner()


def start_lishuttle(schema_name, func, task_id):
    """直接起 lishuttle.exe（工作目录=exe 目录），不经 bat。"""
    env = load_env()
    exe = os.path.join(env["PROJECT_DIR"].replace("/", os.sep),
                       *env["BUILD_SUBDIR"].split("/"), "Bin", env["EXE_NAME"])
    if not os.path.isfile(exe):
        return None, f"找不到 {exe}，先编译"
    cmd = [exe, "-f", func, "-t", str(task_id), "-c", schema_name]
    cwd = os.path.dirname(exe)
    return RUNNER.start(cmd, cwd, f"-f {func} -t {task_id} -c {schema_name}"), to_slash(exe)


def start_toolkit(step):
    """doctor/build/stage：批处理封装。"""
    env = load_env()
    bat = os.path.join(SCRIPTS, {"doctor": "doctor_local.bat", "build": "build_local.bat",
                                 "stage": "stage_local.bat"}[step])
    sid = RUNNER.start(["cmd", "/c", bat], ROOT, step)
    return sid, to_slash(bat)


# ----------------------------------------------------------------------
# 结果查看
# ----------------------------------------------------------------------

def results(job_name):
    env = load_env()
    out_dir = os.path.join(env["OUT_ROOT"].replace("/", os.sep), job_name)
    manifest_path = schema_path(job_name + '.xml') + '.manifest.json'
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding='utf-8') as fh:
            manifest = json.load(fh)
        if manifest.get('schema_mode') == 'existing':
            out_dir = runtime_details(schema_path(job_name + '.xml'),
                                      os.path.dirname(os.path.dirname(manifest_path)))['out_dir']
    exe_dir = os.path.join(env["PROJECT_DIR"].replace("/", os.sep),
                           *env["BUILD_SUBDIR"].split("/"), "Bin")
    info = {"dir": to_slash(out_dir), "exists": os.path.isdir(out_dir),
            "files": [], "status": "", "log_tail": [], "errors": [],
            "log_file": ""}
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
