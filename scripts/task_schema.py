"""Copy an existing RuntimeSchema while changing only explicitly allowed paths."""
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape


OUTDOOR_PATHS = {
    'ProjectionFilePath': 'heights/projection.txt',
    'HeightIndexPath': 'heights/index.txt',
    'ClutterIndexPath': 'clutter/index.txt',
    'ClutterMenuPath': 'clutter/menu.txt',
    'BuildingIndexPath': 'buildings/index.txt',
    'BulidVectorIndexPath': 'buildvector/index.txt',
}
LOCAL_PATHS = set(OUTDOOR_PATHS) | {
    'EngineeringFilePath', 'PolygonFilePath', 'PathlossDirectory', 'MapPath',
    'ClutterMatchPath', 'SceneSettingsPath', 'DriverTestFileDictionaryPath',
}


def path_overrides(value):
    if isinstance(value, str):
        try:
            value = json.loads(value or '{}')
        except json.JSONDecodeError as exc:
            raise ValueError('本地路径配置不是有效 JSON') from exc
    if not isinstance(value, dict) or set(value) - LOCAL_PATHS:
        raise ValueError('只允许修改明确支持的本地路径字段')
    if any(not isinstance(v, str) or any(c in v for c in '\r\n\0') for v in value.values()):
        raise ValueError('本地路径必须为单行文本')
    return value


def read_runtime(path):
    try:
        with open(path, 'r', encoding='utf-8', newline='') as fh:
            text = fh.read()
        root = ET.fromstring(text)
    except (OSError, UnicodeError, ET.ParseError, ValueError) as exc:
        raise ValueError(f'无法读取有效的 UTF-8 运行配置 XML：{path}：{exc}') from exc
    if root.tag != 'RuntimeSchema':
        raise ValueError(f'不是 RuntimeSchema 运行配置：{path}')
    return text, root


def schema_candidates(paths):
    candidates = []
    for path in sorted(paths):
        try:
            _, root = read_runtime(path)
        except ValueError:
            continue
        candidates.append({'path': path, 'name': root.get('name', ''),
                           'path_values': {tag: root.findtext(tag) or '' for tag in sorted(LOCAL_PATHS) if root.find(tag) is not None},
                           'kind': 'indoor' if (root.findtext('MapFormat') or '').lower() == 'indoor' else 'outdoor'})
    return candidates


def runtime_details(path, exe_dir):
    """Metadata of the actual copied configuration; independent of its source."""
    _, root = read_runtime(path)
    name = root.get('name', '')
    output_root = root.findtext('PathlossDirectory') or ''
    if not name or not output_root:
        raise ValueError('运行配置缺少 name 或 PathlossDirectory，无法确定真实输出目录')
    if not os.path.isabs(output_root):
        output_root = os.path.join(exe_dir, output_root)
    return {'out_dir': os.path.join(output_root, name).replace('\\', '/'),
            'paths': {tag: root.findtext(tag) or '' for tag in LOCAL_PATHS if root.find(tag) is not None},
            'engineering_file': root.findtext('EngineeringFilePath') or '',
            'scene_settings_file': root.findtext('SceneSettingsPath') or '',
            'drivetest_dir': root.findtext('DriverTestFileDictionaryPath') or ''}


def local_path_values(table, root, strict=True):
    """Resolve local defaults once for the form, preview and CLI copy."""
    overrides = path_overrides(table.get('PATH_OVERRIDES', '{}'))
    indoor = (table.get('MAP_FORMAT', '').lower() == 'indoor'
              or table.get('TEMPLATE') == 'runtimeschema-indoor.xml.tpl')
    source_indoor = (root.findtext('MapFormat') or '').lower() == 'indoor'
    if indoor != source_indoor:
        raise ValueError('所选地图与已有 XML 的室内外类型不一致，请选择匹配的配置')
    values = {'PolygonFilePath': table.get('POLYGON_FILE', ''),
              'PathlossDirectory': table['OUT_ROOT']}
    for tag, key in (('SceneSettingsPath', 'SCENE_SETTINGS_FILE'),
                     ('DriverTestFileDictionaryPath', 'DT_ROOT')):
        if root.find(tag) is not None:
            values[tag] = table.get(key, '')
    if indoor:
        values['MapPath'] = table.get('MAP_PATH', '')
    else:
        city_dir = f"{table['MAP_ROOT'].replace(chr(92), '/')}/{table.get('CITY', '')}"
        values.update({tag: f'{city_dir}/{rel}' for tag, rel in OUTDOOR_PATHS.items()})
        # Preserve a task's special local index if it belongs to this selected map.
        for tag in OUTDOOR_PATHS:
            original = (root.findtext(tag) or '').replace('\\', '/')
            try:
                inside = os.path.commonpath([os.path.realpath(original), os.path.realpath(city_dir)]) == os.path.realpath(city_dir)
            except ValueError:
                inside = False
            if inside and os.path.isfile(original):
                values[tag] = original
            elif original and os.path.basename(original).lower() != os.path.basename(OUTDOOR_PATHS[tag]).lower():
                relocated = f'{city_dir}/{os.path.dirname(OUTDOOR_PATHS[tag])}/{os.path.basename(original)}'
                if os.path.isfile(relocated):
                    values[tag] = relocated
                elif tag not in overrides:
                    if strict:
                        raise ValueError(f'自定义地图路径 {tag} 无法确认：{original}；请在“修改本地资源路径”中明确填写，避免替换成普通索引')
                    values[tag] = ''
        values['ClutterMatchPath'] = table['CLUTTER_MATCH_FILE']
    if table.get('SYNC_ENGINEERING') == '1':
        values['EngineeringFilePath'] = table['ENGINEERING_FILE']
    values.update(overrides)
    return values


def render_existing(table):
    source = table['SCHEMA_SOURCE']
    text, root = read_runtime(source)
    schema_name = root.get('name', '')
    if not schema_name:
        raise ValueError('已有配置缺少 RuntimeSchema name，无法确定真实输出目录')
    values = local_path_values(table, root)
    parts = re.split(r'(<!--.*?-->)', text, flags=re.S)
    changes = []
    for tag, value in values.items():
        nodes = root.findall(tag)
        if len(nodes) != 1 or list(nodes[0]):
            raise ValueError(f'已有配置需要且只能包含一个简单字段 {tag}；未复制或补写任何配置')
        old = nodes[0].text or ''
        if old == value:
            continue
        replacements = 0
        pattern = rf'(<{tag}\b[^>]*>)[^<]*(</{tag}\s*>)|<{tag}\b[^>]*/>'
        def replace(match):
            nonlocal replacements
            replacements += 1
            if match.group(1):
                return match.group(1) + escape(value) + match.group(2)
            return match.group(0)[:-2] + '>' + escape(value) + f'</{tag}>'
        for i in range(0, len(parts), 2):
            parts[i] = re.sub(pattern, replace, parts[i])
        if replacements != 1:
            raise ValueError(f'字段 {tag} 的格式不支持定点替换，请先调整源配置')
        changes.append({'tag': tag, 'old': old, 'new': value})
    rendered = ''.join(parts)
    ET.fromstring(rendered)
    output_root = values['PathlossDirectory'].replace('\\', '/')
    if not os.path.isabs(output_root):
        output_root = os.path.join(table['EXE_DIR'], output_root)
    output = os.path.join(output_root, schema_name).replace('\\', '/')
    return {'text': rendered, 'source': source.replace('\\', '/'),
            'changes': changes, 'runtime_name': schema_name, 'out_dir': output,
            'engineering_file': values.get('EngineeringFilePath', root.findtext('EngineeringFilePath') or ''),
            'scene_settings_file': values.get('SceneSettingsPath', root.findtext('SceneSettingsPath') or ''),
            'drivetest_dir': values.get('DriverTestFileDictionaryPath', root.findtext('DriverTestFileDictionaryPath') or ''),
            'token': hashlib.sha256((os.path.abspath(source) + '\0' + rendered).encode('utf-8')).hexdigest()}
