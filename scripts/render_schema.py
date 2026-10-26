#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把运行单模板渲染成成品运行单，并输出运行参数给 shell 脚本消费。
Windows 和 Linux 用的是同一个文件。

用法：
    # 渲染运行单 + 检查输入文件是否就位
    python  scripts/render_schema.py jobs/example-pl-guangzhou.env local-win
    python3 scripts/render_schema.py jobs/example-pl-guangzhou.env server

    # 只输出运行参数（KEY=VALUE，供 run_*.bat / run_*.sh 解析）
    python  scripts/render_schema.py jobs/example-pl-guangzhou.env local-win --print-run

    # 只输出环境变量（KEY=VALUE，供 *.bat / *.sh 加载环境）
    python  scripts/render_schema.py --print-env local-win
    python3 scripts/render_schema.py --print-env server

读三个东西：
    env/<target>.env                  环境定义（路径根、预设名、工具链）
    jobs/<job>.env                    任务单（功能、城市、工参、区域）
    <PROJECT_DIR>/<CONFIG_SRC>/runtimelibrary/runtimeschema.xml    完整样例

输出：
    <PROJECT_DIR>/<BUILD_SUBDIR>/Bin/runtimelibrary/<SCHEMA_NAME>        成品运行单
    <同目录>/<SCHEMA_NAME>.manifest.json                                 渲染记录

为什么必须写到 <exe目录>/runtimelibrary/：程序是用 get_executable_path()
拼配置路径的（LiShuttle/src/main.cpp:68-94），和当前工作目录无关。
"""

import glob
import json
import os
import re
import sys
import shutil
from project_config import load_local, validate_operation
from task_schema import render_existing, runtime_details, LOCAL_PATHS
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


# ----------------------------------------------------------------------
# 配置读取与占位符解析
# ----------------------------------------------------------------------

def read_env_file(path, label):
    """读 KEY="VALUE" 格式的配置文件，返回 dict。

    约定值一律带双引号，这样 bash 能直接 source，batch 用 %%~b 去掉引号，
    这里统一剥掉。路径里有空格的（如 Program Files）靠这个约定才能安全传递。
    """
    if not os.path.isfile(path):
        sys.exit(f"[错误] 找不到{label}：{path}")

    data = {}
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                # 走 stderr：stdout 是给 shell 脚本消费的干净 KEY=VALUE 流
                print(f"[警告] {label} 第 {lineno} 行不是 KEY=VALUE，已跳过：{line}",
                      file=sys.stderr)
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            data[key] = value
    return data


def expand(text, table, where):
    """严格展开：未定义的占位符直接报错。

    绝不让 ${...} 漏进成品——否则运行时会变成一个莫名其妙的路径错误，
    比在这里失败难查得多。
    """
    missing = []

    def repl(match):
        name = match.group(1)
        if name not in table:
            missing.append(name)
            return match.group(0)
        return table[name]

    result = PLACEHOLDER.sub(repl, text)
    if missing:
        names = ", ".join(sorted(set(missing)))
        sys.exit(f"[错误] {where} 里用到了未定义的占位符：{names}\n"
                 f"        请在 env/ 或 jobs/ 的对应文件里补上这些键。")
    return result


def expand_all(text, table):
    """宽松展开：能替换的替换掉，暂时找不到的原样留着。用于迭代解析互相引用的键。"""
    return PLACEHOLDER.sub(lambda m: table.get(m.group(1), m.group(0)), text)


def resolve_job(job, env):
    """解析任务单里的值。

    任务单里的值可能同时引用环境变量和任务单里的其他键，例如
        CITY="guangzhou"
        ENGINEERING_FILE="${MAP_ROOT}/${CITY}/guangzhougongcan.csv"
    前者在环境里、后者在任务单里，且不保证依赖写在前面，
    所以用迭代展开直到收敛。
    """
    table = dict(env)
    table.update(job)
    for _ in range(16):
        changed = False
        for key, value in job.items():
            new_value = expand_all(value, table)
            if new_value != table[key]:
                table[key] = new_value
                changed = True
        if not changed:
            break
    else:
        sys.exit("[错误] 任务单里的占位符互相引用成了死循环，16 轮仍未收敛。")
    return table


def to_slash(path):
    return path.replace("\\", "/")


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------

def build_table(env, job):
    """把环境变量和任务单合成最终的变量表，并补上派生变量。"""
    for key in ('PROJECT_DIR', 'PRESET', 'BUILD_SUBDIR', 'INSTALL_SUBDIR', 'EXE_NAME',
                'VS_ROOT', 'CMAKE', 'NINJA', 'VCVARS', 'CONFIG_SRC', 'DLL_SRC',
                'PROJECT_PROFILE_ID', 'PROJECT_PROFILE_REVISION'):
        if key in job and job[key] != env.get(key):
            raise ValueError(f'任务单不能覆盖项目配置 {key}，请选择对应项目后重试')
    if env.get('PROJECT_PROFILE_ID'):
        required = ['PROJECT_DIR', 'BUILD_SUBDIR', 'EXE_NAME', 'OUT_ROOT']
        if job.get('CITY'):
            required.append('MAP_ROOT')
        missing = [key for key in required if not env.get(key)]
        if missing:
            raise ValueError('当前项目配置未完成，请先填写：' + '、'.join(missing))
    table = resolve_job(job, env)

    for key, value in table.items():
        leftover = PLACEHOLDER.findall(value)
        if leftover:
            sys.exit(f"[错误] {key} 用到了未定义的占位符："
                     f"{', '.join(sorted(set(leftover)))}\n"
                     f"        请在 env/ 或 jobs/ 的对应文件里补上这些键。")

    # ---- 派生变量 ----
    build_dir = f"{to_slash(env['PROJECT_DIR'])}/{env['BUILD_SUBDIR']}"
    exe_dir = f"{build_dir}/Bin"
    runtime_schema_dir = f"{exe_dir}/runtimelibrary"

    table["BUILD_DIR"] = build_dir
    table["EXE_DIR"] = exe_dir
    table["RUNTIME_SCHEMA_DIR"] = runtime_schema_dir
    table["EXE_PATH"] = f"{exe_dir}/{env['EXE_NAME']}"

    # 留空的可选项填默认值
    # 室内任务没有 CITY/杂波匹配这些概念，跳过室外专用的默认值推导
    if table.get("CITY") and not table.get("CLUTTER_MATCH_FILE"):
        table["CLUTTER_MATCH_FILE"] = derive_clutter_match(table, env)
    if not table.get("CLUTTER_MATCH_FILE"):
        table["CLUTTER_MATCH_FILE"] = ""
    if not table.get("SCENE_SETTINGS_FILE"):
        table["SCENE_SETTINGS_FILE"] = f"{runtime_schema_dir}/scenesettings.xml"
    if not table.get("DRIVETEST_DIR"):
        table["DRIVETEST_DIR"] = to_slash(env.get("DT_ROOT", ""))
    table["DT_ROOT"] = table["DRIVETEST_DIR"]
    # 高度分层：不填就是 3m 单层（与服务器任务单默认一致）
    if not table.get("MAX_CALC_HEIGHT"):
        table["MAX_CALC_HEIGHT"] = "3"
    if not table.get("DEFAULT_FLOOR_HEIGHT"):
        table["DEFAULT_FLOOR_HEIGHT"] = "3"

    return table


def derive_clutter_match(table, env):
    """找杂波匹配文件，按可靠性依次尝试：

    1. ${MAP_ROOT}/${CITY}/${CITY}cluttermatchsettings.xml —— 常规城市名（如 guangzhou）
    2. 城市目录里通配 *cluttermatchsettings.xml —— 目录名不规整时
       （实测 "zhengzhou - test" 这种带空格/后缀的名字，规则 1 会拼出不存在的
         "zhengzhou - testcluttermatchsettings.xml"）
    3. 项目自带的 ThirdPart/Config/config/cluttermatchsettings.xml —— 兜底默认。
       程序本身在字段为空时也会回退到 <exe>/config/ 下这份，所以指到它与
       程序行为一致；对没有专门校准过杂波的城市这是预期做法。

    一个都找不到时返回空，让渲染检查如实报缺失。
    """
    map_root, city = to_slash(env["MAP_ROOT"]), table["CITY"]
    city_dir = f"{map_root}/{city}"
    candidate = f"{city_dir}/{city}cluttermatchsettings.xml"
    if os.path.isfile(candidate):
        return candidate
    try:
        hits = sorted(glob.glob(f"{city_dir}/*cluttermatchsettings.xml"))
    except OSError:
        hits = []
    if hits:
        return to_slash(hits[0])
    default = (f"{to_slash(env['PROJECT_DIR'])}/"
               f"{env.get('CONFIG_SRC', 'ThirdPart/Config')}/config/cluttermatchsettings.xml")
    if os.path.isfile(default):
        return default
    return candidate


def manifest_path_for(table):
    return f"{table['RUNTIME_SCHEMA_DIR']}/{table['SCHEMA_NAME']}.manifest.json"


def apply_xml_paths(table, paths):
    for tag, key in {'EngineeringFilePath': 'ENGINEERING_FILE', 'MapPath': 'MAP_PATH',
                     'SceneSettingsPath': 'SCENE_SETTINGS_FILE', 'PolygonFilePath': 'POLYGON_FILE',
                     'ClutterMatchPath': 'CLUTTER_MATCH_FILE', 'DriverTestFileDictionaryPath': 'DT_ROOT'}.items():
        if tag in paths:
            table[key] = paths[tag]


def validate_batch_values(values):
    if any('!' in str(value) for value in values.values()):
        raise ValueError('本地批处理不支持路径或配置中的 ! 字符；请调整路径，或使用 Python 入口。未加载配置或启动引擎。')


def do_print_env(target, env_path, project=None, batch=False, operation=None):
    """输出环境文件里的全部键值，供 .bat / .sh 加载。

    为什么不让批处理自己逐行解析环境文件：环境文件是 UTF-8（带中文注释），
    而 cmd 用当前代码页（中文 Windows 是 GBK）解码，中文注释的字节序列
    会把行结构解析乱掉，导致前半段键被整个跳过——这个坑很难查。
    交给 Python 读就没有编码问题。
    """
    env = load_local(env_path, project=project) if target == 'local-win' else read_env_file(env_path, "环境文件")
    if operation:
        validate_operation(env, operation)
    if batch:
        validate_batch_values(env)
        for key in ('CONFIG', 'DLL'):
            source = env.get(key + '_SRC', '')
            env[key + '_SOURCE_DIR'] = to_slash(os.path.join(env['PROJECT_DIR'], source)) if source else ''
    for key, value in env.items():
        print(f"{key}={value}")
    return 0


def do_print_run(table, prepare_render=False, batch=False):
    """输出运行参数，供 run_*.bat / run_*.sh 解析。

    和渲染走的是同一个 build_table()，所以"渲染时用的路径"和
    "运行时用的路径"必然一致，不会出现两套拼接逻辑跑偏。
    """
    schema_names = [n.strip() for n in table["SCHEMA_NAME"].split(",") if n.strip()]
    if not schema_names:
        sys.exit("[错误] 任务单里的 SCHEMA_NAME 是空的")

    out_dir = f"{to_slash(table['OUT_ROOT'])}/{table['JOB_NAME']}"
    if table.get('SCHEMA_SOURCE'):
        destination = os.path.join(table['RUNTIME_SCHEMA_DIR'], schema_names[0])
        out_dir = (runtime_details(destination, table['EXE_DIR'])['out_dir'] if os.path.isfile(destination) and not prepare_render
                   else render_existing(table)['out_dir'])
    values = {
        "FUNC": table["FUNC"],
        "TASK_ID": table.get("TASK_ID") or "0",
        "SCHEMA_ARGS": ",".join(schema_names),
        "EXE_DIR": to_slash(table["EXE_DIR"]),
        "EXE_PATH": to_slash(table["EXE_PATH"]),
        "OUT_DIR": out_dir,
        "JOB_NAME": table["JOB_NAME"],
        "SERVER_BACKGROUND": table.get("SERVER_BACKGROUND", "0"),
        "RENDER_BEFORE_RUN": table.get("RENDER_BEFORE_RUN", "1"),
    }
    if batch:
        validate_batch_values(values)
    for key, value in values.items():
        print(f"{key}={value}")
    return 0


def render_project_sample(table, job):
    """复制当前引擎的完整样例，只定点替换任务值，不重排 XML 或注释。"""
    sample = os.path.join(table['PROJECT_DIR'], table.get('CONFIG_SRC', 'ThirdPart/Config'),
                          'runtimelibrary', 'runtimeschema.xml')
    if not os.path.isfile(sample):
        sys.exit(f'[错误] 找不到完整运行单样例：{to_slash(sample)}')
    with open(sample, 'r', encoding='utf-8-sig', newline='') as fh:
        text = fh.read()
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        sys.exit(f'[错误] 运行单样例 XML 无效：{sample}：{exc}')
    if root.tag != 'RuntimeSchema':
        sys.exit(f'[错误] 运行单样例根节点必须是 RuntimeSchema：{sample}')

    values = {
        'EngineeringFilePath': table['ENGINEERING_FILE'],
        'PolygonFilePath': table.get('POLYGON_FILE', ''),
        'SceneSettingsPath': table['SCENE_SETTINGS_FILE'],
        'PathlossDirectory': table['OUT_ROOT'],
    }
    for key, tag in (('MAX_CALC_HEIGHT', 'MaxCalcHeight'),
                     ('DEFAULT_FLOOR_HEIGHT', 'DefaultFloorHeight')):
        if job.get(key):
            values[tag] = table[key]
    if table.get('DRIVETEST_DIR') or table.get('DT_ROOT'):
        values['DriverTestFileDictionaryPath'] = table['DT_ROOT']
    indoor = (table.get('MAP_FORMAT', '').lower() == 'indoor'
              or table.get('TEMPLATE') == 'runtimeschema-indoor.xml.tpl')
    if indoor:
        values.update(MapFormat='indoor', MapPath=table.get('MAP_PATH', ''))
    else:
        city_dir = f"{to_slash(table['MAP_ROOT'])}/{table.get('CITY', '')}"
        for tag, rel in (
            ('ProjectionFilePath', 'heights/projection.txt'),
            ('HeightIndexPath', 'heights/index.txt'),
            ('ClutterIndexPath', 'clutter/index.txt'),
            ('ClutterMenuPath', 'clutter/menu.txt'),
            ('BuildingIndexPath', 'buildings/index.txt'),
            ('BulidVectorIndexPath', 'buildvector/index.txt'),
        ):
            values[tag] = f'{city_dir}/{rel}'
        values['ClutterMatchPath'] = table['CLUTTER_MATCH_FILE']

    # 注释单独保留：其中即使出现标签或 ${...} 也不能被替换。
    parts = re.split(r'(<!--.*?-->)', text, flags=re.S)
    found = set()
    for i in range(0, len(parts), 2):
        part = parts[i]
        def rename(match):
            opening = match.group(0)
            attr = re.compile(r'\bname\s*=\s*([\'"]).*?\1', re.S)
            name = 'name=' + quoteattr(table['JOB_NAME'])
            if attr.search(opening):
                return attr.sub(lambda _: name, opening, count=1)
            return opening[:-1] + ' ' + name + '>'
        part = re.sub(r'<RuntimeSchema\b[^>]*>', rename, part, count=1)
        for tag, value in values.items():
            pattern = rf'(<{tag}\b[^>]*>)[^<]*(</{tag}\s*>)|<{tag}\b[^>]*/>'
            def replace(match):
                found.add(tag)
                if match.group(1):
                    return match.group(1) + escape(str(value)) + match.group(2)
                return match.group(0)[:-2] + '>' + escape(str(value)) + f'</{tag}>'
            part = re.sub(pattern, replace, part)
        parts[i] = part
    rendered = ''.join(parts)
    # 室内分流所必需的字段在室外样例中可能不存在；其余字段一律不增删。
    if indoor:
        newline = '\r\n' if '\r\n' in text else '\n'
        extra = ''.join(f'  <{tag}>{escape(values[tag])}</{tag}>{newline}'
                        for tag in ('MapFormat', 'MapPath') if tag not in found)
        rendered = rendered.replace('</RuntimeSchema>', extra + '</RuntimeSchema>')
    ET.fromstring(rendered)  # 写盘前确认任务值没有破坏 XML。
    return rendered, to_slash(sample)


def do_render(env, job, target, job_path, env_path, write_output=True):
    table = build_table(env, job)

    schema_names = [n.strip() for n in table["SCHEMA_NAME"].split(",") if n.strip()]
    if not schema_names:
        sys.exit("[错误] 任务单里的 SCHEMA_NAME 是空的")

    # 输出目录 = PathlossDirectory + 运行单的 name 属性。
    # 程序在 ServiceHelper.cpp:126-130 会把 name 追加到 PathlossDirectory 后面，
    # 而 name 就是模板里的 ${JOB_NAME}，所以最终目录是 OUT_ROOT/JOB_NAME。
    out_dir = f"{to_slash(table['OUT_ROOT'])}/{table['JOB_NAME']}"
    written = []
    actual_paths = {}

    if write_output:
        # 默认室内外入口均从当前项目完整样例复制。显式指定其他模板仍兼容。
        tpl_name = table.get("TEMPLATE") or "runtimeschema.xml.tpl"
        existing = None
        if table.get('SCHEMA_SOURCE'):
            try:
                existing = render_existing(table)
            except ValueError as exc:
                sys.exit(f'[错误] {exc}')
            rendered, source = existing['text'], existing['source']
            out_dir = existing['out_dir']
            table['ENGINEERING_FILE'] = existing['engineering_file']
            table['SCENE_SETTINGS_FILE'] = existing['scene_settings_file']
            table['DT_ROOT'] = existing['drivetest_dir']
        elif tpl_name in ('runtimeschema.xml.tpl', 'runtimeschema-indoor.xml.tpl'):
            rendered, source = render_project_sample(table, job)
        else:
            tpl_path = os.path.join(ROOT, "templates", tpl_name)
            if not os.path.isfile(tpl_path):
                sys.exit(f"[错误] 找不到模板：{to_slash(tpl_path)}")
            with open(tpl_path, "r", encoding="utf-8") as fh:
                rendered = expand(fh.read(), table, "模板")
            source = to_slash(tpl_path)

        actual = ET.fromstring(rendered)
        actual_paths = {tag: actual.findtext(tag) or '' for tag in LOCAL_PATHS if actual.find(tag) is not None}
        apply_xml_paths(table, actual_paths)
        os.makedirs(table["RUNTIME_SCHEMA_DIR"], exist_ok=True)
        if existing:
            for name in schema_names:
                destination = os.path.join(table['RUNTIME_SCHEMA_DIR'], name)
                if os.path.normcase(os.path.realpath(destination)) == os.path.normcase(os.path.realpath(source)):
                    sys.exit('[错误] 源 XML 与目标文件相同，不能覆盖原始配置')
        for name in schema_names:
            out_file = os.path.join(table["RUNTIME_SCHEMA_DIR"], name)
            if existing and os.path.isfile(out_file):
                shutil.copy2(out_file, out_file + '.bak')
            with open(out_file, "w", encoding="utf-8", newline="") as fh:
                fh.write(rendered)
            written.append(to_slash(out_file))

        manifest = {
            "job_name": table["JOB_NAME"],
            "schema_source": source,
            "schema_mode": 'existing' if existing else 'sample',
            "path_changes": existing['changes'] if existing else [],
            "project_config": dict(env),
            "target": target,
            "env_file": to_slash(os.path.relpath(env_path, ROOT)),
            "job_file": to_slash(os.path.relpath(job_path, ROOT)),
            "run": {
                "func": table["FUNC"],
                "task_id": table.get("TASK_ID") or "0",
                "schema_names": schema_names,
                # 直接拼好给 -c 用，逗号分隔支持多运行单顺序执行
                "schema_args": ",".join(schema_names),
                "exe_dir": to_slash(table["EXE_DIR"]),
                "exe_path": to_slash(table["EXE_PATH"]),
                "out_dir": out_dir,
                "job_name": table["JOB_NAME"],
                "server_background": table.get("SERVER_BACKGROUND", "0"),
            },
            "resolved_paths": {
                "xml_paths": actual_paths,
                "engineering_file": to_slash(table["ENGINEERING_FILE"]),
                "polygon_file": to_slash(table.get("POLYGON_FILE", "")),
                "map_root": to_slash(table.get("MAP_ROOT", "")),
                "city": table.get("CITY", ""),
                "map_path": to_slash(table.get("MAP_PATH", "")),
                "clutter_match_file": to_slash(table.get("CLUTTER_MATCH_FILE", "")),
                "scene_settings_file": to_slash(table["SCENE_SETTINGS_FILE"]),
                "out_dir": out_dir,
                "drivetest_dir": to_slash(table["DT_ROOT"]),
            },
        }
        mpath = manifest_path_for(table)
        with open(mpath, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)

    elif table.get('SCHEMA_SOURCE'):
        details = runtime_details(os.path.join(table['RUNTIME_SCHEMA_DIR'], schema_names[0]), table['EXE_DIR'])
        out_dir = details['out_dir']
        table['ENGINEERING_FILE'] = details['engineering_file']
        table['SCENE_SETTINGS_FILE'] = details['scene_settings_file']
        actual_paths = details['paths']
        apply_xml_paths(table, actual_paths)

    # 已有 XML 的相对路径由引擎相对 exe 工作目录解释；只改变检查位置，不改 XML。
    if table.get('SCHEMA_SOURCE'):
        for key in ('ENGINEERING_FILE', 'SCENE_SETTINGS_FILE', 'MAP_PATH', 'POLYGON_FILE', 'CLUTTER_MATCH_FILE'):
            path = table.get(key, '').replace('\\', '/')
            if path and not os.path.isabs(path):
                table[key] = os.path.join(table['EXE_DIR'], path)

    # ---- 检查输入文件 ----
    # 室外任务检查地图四件套索引；室内任务（MapFormat=indoor）只需
    # MapPath 目录下的 building.das（室内地图就是这一个文件）
    map_root = to_slash(table.get("MAP_ROOT", ""))
    city = table.get("CITY", "")
    is_indoor = (table.get("MAP_FORMAT", "").strip().lower() == "indoor"
                 or "indoor" in (table.get("TEMPLATE") or "").lower())
    def input_path(tag, default):
        value = actual_paths.get(tag, default).replace('\\', '/')
        return os.path.join(table['EXE_DIR'], value) if value and not os.path.isabs(value) else value
    if is_indoor:
        map_path = table.get("MAP_PATH", "")
        checks = [
            ("工参 CSV", table["ENGINEERING_FILE"], True),
            ("室内地图 building.das",
             f"{map_path}/building.das" if map_path else "", True),
            ("场景配置", table["SCENE_SETTINGS_FILE"], False),
        ]
    else:
        checks = [
            ("工参 CSV", table["ENGINEERING_FILE"], True),
            ("区域多边形", table["POLYGON_FILE"], True),
            ("地图投影", input_path('ProjectionFilePath', f"{map_root}/{city}/heights/projection.txt"), True),
            ("高程索引", input_path('HeightIndexPath', f"{map_root}/{city}/heights/index.txt"), True),
            ("杂波索引", input_path('ClutterIndexPath', f"{map_root}/{city}/clutter/index.txt"), True),
            ("杂波菜单", input_path('ClutterMenuPath', f"{map_root}/{city}/clutter/menu.txt"), True),
            ("建筑索引", input_path('BuildingIndexPath', f"{map_root}/{city}/buildings/index.txt"), True),
            ("建筑矢量索引", input_path('BulidVectorIndexPath', f"{map_root}/{city}/buildvector/index.txt"), True),
            ("杂波匹配配置", table["CLUTTER_MATCH_FILE"], True),
            ("场景配置", table["SCENE_SETTINGS_FILE"], False),
        ]

    print(f"任务单    : {table['JOB_NAME']}")
    print(f"目标环境  : {target}")
    print(f"运行参数  : -f {table['FUNC']} -t {table.get('TASK_ID') or '0'}"
          f" -c {table['SCHEMA_NAME']}")
    print(f"运行目录  : {out_dir}")
    print()

    if written:
        print(f"运行单底稿：{source}")
        print("已生成运行单：")
        for path in written:
            print(f"  {path}")
        print(f"  {to_slash(manifest_path_for(table))}   （渲染记录）")
        if len(schema_names) > 1:
            print(f"  [提示] SCHEMA_NAME 有 {len(schema_names)} 项，"
                  f"渲染出的是内容相同的运行单。")
        print()
    else:
        print("（--no-render：未重写运行单，沿用已有文件）")
        print()

    print("输入文件检查：")
    missing_required = []
    for label, path, required in checks:
        ok = os.path.isfile(path)
        mark = "OK  " if ok else ("缺失" if required else "可选缺失")
        print(f"  [{mark}] {label:<12} {to_slash(path)}")
        if not ok and required:
            missing_required.append(label)
    print()

    if missing_required:
        print(f"[注意] {len(missing_required)} 个必需文件不存在："
              f"{'、'.join(missing_required)}")
        print("       运行单已生成，但直接跑会失败。请把文件放到上面的路径，")
        print("       或改任务单里的路径后重新渲染。")
        return 1

    print("[完成] 必需文件已就位，可以运行了。")
    return 0


def main():
    raw = list(sys.argv[1:])
    project = None
    if '--project' in raw:
        index = raw.index('--project')
        if index + 1 >= len(raw):
            raise ValueError('--project 需要本地项目目录')
        project = raw[index + 1]
        del raw[index:index + 2]
    args = [a for a in raw if not a.startswith("--")]
    flags = {a for a in raw if a.startswith("--")}

    # --print-env 只需要目标环境名，不需要任务单
    if "--print-env" in flags:
        if len(args) != 1:
            sys.exit("用法：render_schema.py --print-env <目标环境>")
        target = args[0]
        operation = next((op for op in ('doctor', 'build', 'stage', 'run') if '--check-' + op in flags), None)
        return do_print_env(target, os.path.join(ROOT, "env", f"{target}.env"), project, '--batch' in flags, operation)

    if len(args) != 2:
        print(__doc__)
        sys.exit("用法：render_schema.py <任务单> <目标环境> "
                 "[--print-run] [--no-render]\n"
                 "      render_schema.py --print-env <目标环境>")

    job_arg, target = args
    job_path = job_arg if os.path.isabs(job_arg) else os.path.join(ROOT, job_arg)
    env_path = os.path.join(ROOT, "env", f"{target}.env")

    env = load_local(env_path, project=project) if target == 'local-win' else read_env_file(env_path, "环境文件")
    job = read_env_file(job_path, "任务单")

    if "--print-run" in flags:
        table = build_table(env, job)
        if '--batch' in flags:
            validate_batch_values(table)
        prepare = ('--prepare-render' in flags and '--no-render' not in flags
                   and table.get('RENDER_BEFORE_RUN', '1') != '0')
        return do_print_run(table, prepare_render=prepare, batch='--batch' in flags)

    return do_render(env, job, target, job_path, env_path,
                     write_output="--no-render" not in flags)


if __name__ == "__main__":
    sys.exit(main())
