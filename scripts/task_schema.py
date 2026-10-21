"""Copy an existing RuntimeSchema while changing only explicitly allowed paths."""
import hashlib
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
            'engineering_file': root.findtext('EngineeringFilePath') or '',
            'scene_settings_file': root.findtext('SceneSettingsPath') or '',
            'drivetest_dir': root.findtext('DriverTestFileDictionaryPath') or ''}


def render_existing(table):
    source = table['SCHEMA_SOURCE']
    text, root = read_runtime(source)
    schema_name = root.get('name', '')
    if not schema_name:
        raise ValueError('已有配置缺少 RuntimeSchema name，无法确定真实输出目录')
    indoor = (table.get('MAP_FORMAT', '').lower() == 'indoor'
              or table.get('TEMPLATE') == 'runtimeschema-indoor.xml.tpl')
    source_indoor = (root.findtext('MapFormat') or '').lower() == 'indoor'
    if indoor != source_indoor:
        raise ValueError('所选地图与已有 XML 的室内外类型不一致，请选择匹配的配置')
    values = {'PolygonFilePath': table.get('POLYGON_FILE', ''),
              'PathlossDirectory': table['OUT_ROOT']}
    if indoor:
        values['MapPath'] = table.get('MAP_PATH', '')
    else:
        city_dir = f"{table['MAP_ROOT'].replace(chr(92), '/')}/{table.get('CITY', '')}"
        values.update({tag: f'{city_dir}/{rel}' for tag, rel in OUTDOOR_PATHS.items()})
        values['ClutterMatchPath'] = table['CLUTTER_MATCH_FILE']
    if table.get('SYNC_ENGINEERING') == '1':
        values['EngineeringFilePath'] = table['ENGINEERING_FILE']
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
    output = table['OUT_ROOT'].replace('\\', '/').rstrip('/') + '/' + schema_name
    return {'text': rendered, 'source': source.replace('\\', '/'),
            'changes': changes, 'runtime_name': schema_name, 'out_dir': output,
            'engineering_file': (values.get('EngineeringFilePath')
                                 if table.get('SYNC_ENGINEERING') == '1' else root.findtext('EngineeringFilePath') or ''),
            'scene_settings_file': root.findtext('SceneSettingsPath') or '',
            'drivetest_dir': root.findtext('DriverTestFileDictionaryPath') or '',
            'token': hashlib.sha256((os.path.abspath(source) + '\0' + rendered).encode('utf-8')).hexdigest()}
