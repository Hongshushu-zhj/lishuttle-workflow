"""Inventory actual RuntimeSchema fields; help metadata must never hide XML data."""
from collections import OrderedDict
import html
import re
import xml.etree.ElementTree as ET
from xml.parsers import expat
from function_profiles import function_profile


def parse_document(raw):
    try:
        root = ET.fromstring(raw, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    except ET.ParseError as exc:
        raise ValueError(f'运行配置 XML 解析失败：{exc}') from exc
    if root.tag != 'RuntimeSchema':
        raise ValueError('运行配置 XML 根节点必须是 RuntimeSchema')
    encoding_reason = ''
    try:
        text = raw.decode('utf-8-sig')
        declaration = re.match(r'\s*<\?xml\b.*?encoding=["\']([^"\']+)', text, re.I | re.S)
        if declaration and declaration[1].lower().replace('-', '') != 'utf8':
            encoding_reason = '当前 XML 声明非 UTF-8 编码，仅展示；请先保留备份并转换为 UTF-8 后编辑'
    except UnicodeDecodeError:
        encoding_reason = '当前 XML 不是 UTF-8 编码，仅展示；请先保留备份并转换为 UTF-8 后编辑'
    fields = OrderedDict()
    for element in root:
        name = element.tag
        if not isinstance(name, str):
            continue  # XML comments and processing instructions are not parameters.
        structured = bool(len(element))
        has_elements = any(isinstance(child.tag, str) for child in element)
        display = ET.tostring(element, encoding='unicode') if structured else element.text or ''
        value = display if has_elements else (element.text or '') + ''.join(child.tail or '' for child in element)
        field = fields.setdefault(name, dict(value=value, occurrences=[], displays=[], structured=False))
        field['occurrences'].append(value)
        field['displays'].append(display)
        field['structured'] = field['structured'] or structured
    for name, field in fields.items():
        repeated = len(field['occurrences']) > 1
        namespace_reason = '字段带有 XML 命名空间，仅展示；请在 XML 中编辑' if name.startswith('{') else ''
        field['read_only_reason'] = (encoding_reason or namespace_reason or
            ('同名字段重复，已列出各项原值；请在 XML 中明确配置，平台不猜测修改哪一项' if repeated else
             '结构化 XML 配置（含子节点或内部注释），仅展示；请在 XML 中编辑' if field['structured'] else ''))
        field['read_only'] = bool(field['read_only_reason'])
        field['display_value'] = '\n'.join(f'[{i+1}] {v}' for i,v in enumerate(field['displays'])) if repeated else field['displays'][0]
    return dict(name=root.get('name', ''), values={key:f['value'] for key,f in fields.items()}, fields=fields)


def build_catalog(document, spec, func, show_all=True):
    known = {p['name']:p for p in spec['params']}
    values = document['values']
    format_name = values.get('MapFormat', '').strip().lower()
    scene = 'indoor' if format_name == 'indoor' or (not format_name and values.get('MapPath', '').strip()) else 'outdoor'
    hybrid = func in ('plhybrid', 'hybridrays')
    rules, profile = function_profile(func, values)
    groups = OrderedDict((name, []) for name in spec['groups'])
    counts = dict(total=len(values), recommended=0, other=0, unclassified=0, read_only=0)
    for name, field in document['fields'].items():
        if name in known:
            row = dict(known[name])
            funcs = [f.strip() for f in row.get('func', '').split(',') if f.strip()]
            applies = row.get('applies', 'both')
            recommended = (not funcs or not func or func in funcs) and (hybrid or applies in ('both', scene))
            classification = 'recommended' if recommended else 'other'
            if profile.get('reviewed'):
                usage = rules.get(name, dict(kind='unverified', source='', active=False, required=False,
                    condition='', note='本功能审阅链中未确认使用；可能是其他功能或旧版本字段，请在全部视图核对。'))
                row['usage'] = usage
                recommended = name in rules and usage['kind'] != 'startup'
                classification = 'recommended' if recommended else 'other'
        else:
            row = dict(name=name, label=name, group='未分类（XML 已识别）', type='text', applies='both',
                       desc='此字段来自当前运行 XML，参数字典未收录；保留原名和原值，尚未确认适用功能。')
            recommended, classification = True, 'unclassified'
        counts[classification] += 1
        counts['read_only'] += int(field['read_only'])
        row.update(classification=classification, recommended=recommended, present=True,
                   read_only=field['read_only'], read_only_reason=field['read_only_reason'],
                   display_value=field['display_value'], occurrences=len(field['occurrences']))
        if show_all or recommended:
            groups.setdefault(row['group'], []).append(row)
    return dict(groups=[dict(group=name, rows=rows) for name,rows in groups.items() if rows],
                counts=counts, scene='hybrid' if hybrid else scene, function=func, profile=profile)


def replace_scalar(raw, tag, value):
    """Find an actual direct XML element by parser byte offsets, preserving all other bytes."""
    document = parse_document(raw)
    field = document['fields'].get(tag)
    if field is None:
        raise ValueError(f'运行单里没有可编辑的顶层字段 <{tag}>')
    if field['read_only']:
        raise ValueError(field['read_only_reason'])
    parser = expat.ParserCreate()
    depth, positions = 0, {}

    def start(name, attrs):
        nonlocal depth
        depth += 1
        if depth != 2 or name != tag:
            return
        index = parser.CurrentByteIndex
        end, quote = index, None
        while end < len(raw):
            char = raw[end]
            if quote:
                if char == quote:
                    quote = None
            elif char in (34, 39):
                quote = char
            elif char == 62:
                break
            end += 1
        positions.update(start=index, open_end=end, empty=raw[index:end].rstrip().endswith(b'/'))

    def end(name):
        nonlocal depth
        if depth == 2 and name == tag:
            positions['close_start'] = parser.CurrentByteIndex
        depth -= 1

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.Parse(raw, True)
    escaped = html.escape(str(value), quote=False).encode('utf-8')
    if positions['empty']:
        opening = raw[positions['start']:positions['open_end']].rstrip()[:-1] + b'>'
        return raw[:positions['start']] + opening + escaped + f'</{tag}>'.encode('utf-8') + raw[positions['open_end']+1:]
    return raw[:positions['open_end']+1] + escaped + raw[positions['close_start']:]
