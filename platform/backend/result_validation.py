"""Read-only, session-bound result checks for the reviewed LiShuttle products.

The caller owns run identity and supplies only its current process output.  In
particular, this module never opens the engine's shared historical log files.
An exit code, modification time or task-level completion line cannot attribute
an unchanged final product to a run.
"""

import csv
import hashlib
import io
import math
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET


_CHUNK = 1024 * 1024
_OUTDOOR = re.compile(r'^(RSRP|DLRSSINR|BESTSERVER|ECHORP|SCR)(\d*)\.dem$', re.I)
_INDOOR = re.compile(r'^(RSRP|DLRSSINR)_(-?\d+)\.dem$', re.I)
_SITE = re.compile(r'Calibration site\((.*?)\):\s*grid count=(\d+),\s*success=([YN]),\s*update=([YN]),\s*code=0x([\da-fA-F]+)\.')


def _path(value):
    return Path(value).resolve() if value else None


def _fingerprint(path):
    """Hash streams rather than allocating an entire raster or model file."""
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b''):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OSError('文件在读取期间发生变化')
    return dict(path=str(path), size=after.st_size, mtime_ns=after.st_mtime_ns,
                sha256=digest.hexdigest())


def _candidates(context):
    """Only final artifacts; do not hash potentially enormous ray/cache trees."""
    found = set()
    prefix = context.get('task_name') or ''
    reports = ('meas.anchor', 'clean_grids.csv', 'propmodel_ana.csv')
    if prefix:
        reports += (prefix + '_cell_summary.csv', prefix + '_scene_summary.csv')
    patterns = [('pred_dir', ('*.dem', 'index.txt', 'cellid.csv')),
                ('dt_dir', reports),
                ('models_dir', ('*.xml',))]
    for key, globs in patterns:
        root = _path(context.get(key))
        if not root or not root.is_dir():
            continue
        for pattern in globs:
            for path in root.rglob(pattern):
                # A linked artifact outside the selected root is not run evidence.
                if path.is_file() and path.resolve().is_relative_to(root):
                    found.add(path.resolve())
    root = _path(context.get('out_dir'))
    if root:
        path = root / 'CorrectionMeanVariance.xml'
        if path.is_file() and path.resolve().is_relative_to(root):
            found.add(path.resolve())
    return sorted(found, key=str)


def snapshot(context):
    """Capture the content baseline before launch; the return value is JSON safe."""
    files, issues = {}, []
    try:
        paths = _candidates(context)
    except (OSError, ValueError) as exc:
        paths = []
        issues.append(dict(code='BASELINE_READ', path='', message='运行前基线读取失败：' + str(exc)))
    for path in paths:
        try:
            files[str(path)] = _fingerprint(path)
        except OSError as exc:
            issues.append(dict(code='BASELINE_READ', path=str(path), message='运行前基线读取失败：' + str(exc)))
    bin_models = _path(context.get('bin_dir'))
    general_files = []
    if bin_models and (bin_models / 'models').is_dir():
        general_files = sorted(path.name for path in (bin_models / 'models').iterdir()
                               if path.is_file() and path.name.endswith('.xml'))
    records = (context.get('engineering') or {}).get('records')
    fixed_records = [dict(record) for record in records] if isinstance(records, list) and all(isinstance(record, dict) for record in records) else None
    return dict(version=1, files=files, issues=issues, general_model_files=general_files,
                engineering_records=fixed_records)


def _text(path):
    if path.stat().st_size > 16 * _CHUNK:
        raise ValueError('元数据超过 16 MiB 检查上限')
    data = path.read_bytes()
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError('无法识别元数据文本编码')


def _geometry(tokens):
    values = [float(value) for value in tokens]
    if len(values) != 5 or not all(math.isfinite(v) for v in values):
        raise ValueError('网格索引必须包含五个有限数值')
    left, right, bottom, top, resolution = values
    if resolution <= 0 or right <= left or top <= bottom:
        raise ValueError('栅格范围或分辨率无效')
    # GeoRasterRect's edges are exclusive, with its source rounding tolerance.
    columns = math.ceil((right - left) / resolution - .01)
    rows = math.ceil((top - bottom) / resolution - .01)
    if columns <= 0 or rows <= 0:
        raise ValueError('栅格行列数为空')
    return dict(bounds=values[:4], resolution=resolution, columns=columns, rows=rows,
                expected_bytes=columns * rows * 2)


class _Check:
    def __init__(self, context, baseline):
        self.context = context
        self.baseline_metadata = baseline if isinstance(baseline, dict) else {}
        self.baseline = baseline.get('files', {}) if isinstance(baseline, dict) else {}
        self.issues = []
        self.checked = []
        self.fingerprints = {}
        self.unknown = False
        if not isinstance(baseline, dict) or 'files' not in baseline or baseline.get('issues'):
            self.uncertain('BASELINE_UNKNOWN', '缺少完整的本次运行前产物基线，不能确认结果归属。')

    def issue(self, code, message, path='', severity='error', **where):
        self.issues.append(dict(code=code, message=message, path=str(path or ''),
                                severity=severity, **where))

    def uncertain(self, code, message, path='', **where):
        self.unknown = True
        self.issue(code, message, path, severity='warning', **where)

    def changed(self, path, model_kind=None):
        """Inspect freshness before deciding a historical file is applicable."""
        path = path.resolve()
        try:
            info = self.fingerprints.get(str(path))
            if info is None:
                info = _fingerprint(path)
                self.fingerprints[str(path)] = info
            previous = self.baseline.get(str(path))
            return previous is None or previous.get('sha256') != info['sha256']
        except OSError:
            if model_kind:
                # A new or observably modified required model that cannot be
                # read must flow through the attributed integrity failure path.
                # Do not promote an unchanged historical unreadable file.
                previous = self.baseline.get(str(path))
                try:
                    info = path.stat()
                    if previous and (info.st_size, info.st_mtime_ns) == (previous.get('size'), previous.get('mtime_ns')):
                        return False
                except OSError:
                    pass
                return True
            return False

    def file(self, path, current=False, **where):
        if path is None:
            self.uncertain('PATH_UNKNOWN', '无法确定所选任务的输出路径。', **where)
            return None
        path = path.resolve()
        roots = [_path(self.context.get(key)) for key in ('pred_dir', 'dt_dir', 'models_dir', 'out_dir')]
        if not any(root and path.is_relative_to(root) for root in roots):
            self.issue('ARTIFACT_OUTSIDE_ROOT', '产物解析后位于所选任务输出目录之外。', path, **where)
            return None
        entry = dict(path=str(path), changed=False, **where)
        self.checked.append(entry)
        try:
            info = self.fingerprints.get(str(path))
            if info is None:
                info = _fingerprint(path)
                self.fingerprints[str(path)] = info
            entry.update(size=info['size'], sha256=info['sha256'])
            previous = self.baseline.get(str(path))
            entry['changed'] = previous is None or previous.get('sha256') != info['sha256']
            if not info['size']:
                self.issue('EMPTY_FILE', '必需产物为空文件。', path, **where)
                return None
            if current and not entry['changed']:
                self.uncertain('NO_CURRENT_ARTIFACT', '文件内容与运行前一致，不能确认由本次运行生成。', path, **where)
            return entry
        except FileNotFoundError:
            self.issue('REQUIRED_FILE', '缺少必需的最终产物。', path, **where)
        except OSError as exc:
            self.issue('ARTIFACT_READ', '产物读取失败：' + str(exc), path, **where)
        return None


def _index(check, root, indoor):
    path = root / 'index.txt'
    if not check.file(path):
        return 'missing', {}
    try:
        lines = [line.split() for line in _text(path).splitlines() if line.strip()]
        if not lines:
            raise ValueError('索引为空')
        utm = lines[0][0] == 'UTM'
        if utm:
            if len(lines[0]) != 2 or not re.fullmatch(r'-?\d+', lines[0][1]):
                raise ValueError('UTM 索引头无效')
            lines = lines[1:]
        if indoor and not utm and len(lines) == 1 and len(lines[0]) == 5:
            return 'indoor_numeric_legacy', {'*': _geometry(lines[0])}
        if not indoor and not utm:
            raise ValueError('室外索引缺少已识别的 UTM 头')
        entries = {}
        for fields in lines:
            if len(fields) != 6:
                raise ValueError('索引行必须包含文件名和五个网格数值')
            name = fields[0]
            if '/' in name or '\\' in name or ':' in name or name in ('.', '..'):
                check.issue('UNSAFE_INDEX_PATH', '索引只能引用输出目录内的产物文件名。', path)
                return 'unsafe', {}
            matcher = _INDOOR if indoor else _OUTDOOR
            if not matcher.fullmatch(name):
                raise ValueError('未识别的索引产物名称：' + name)
            if name in entries:
                check.issue('DUPLICATE_INDEX', '产物索引存在重复条目。', path)
                return 'invalid', {}
            try:
                entries[name] = _geometry(fields[1:])
            except ValueError as exc:
                check.issue('INDEX_GEOMETRY', '索引网格参数无效：' + str(exc), path)
                return 'invalid', {}
        if not entries:
            raise ValueError('索引没有产物条目')
        if indoor and utm:
            raise ValueError('带 UTM 头的室内索引格式尚未核实')
        return 'indoor_filename' if indoor else 'outdoor_utm', entries
    except (OSError, ValueError) as exc:
        check.uncertain('INDEX_FORMAT_UNKNOWN', '索引格式无法确认：' + str(exc), path)
        return 'unknown', {}


def _mapping(check, root):
    path = root / 'cellid.csv'
    if not check.file(path):
        return set()
    ids = set()
    try:
        for row in csv.reader(io.StringIO(_text(path))):
            if not row:
                continue
            if len(row) < 2 or not row[1].strip():
                raise ValueError('小区映射行格式无效')
            value = int(row[0])
            if value < 0 or value > 32767 or value in ids:
                raise ValueError('小区映射编号重复或超出有符号 int16 范围')
            ids.add(value)
        if not ids:
            raise ValueError('小区映射没有有效编号')
    except (OSError, ValueError) as exc:
        check.issue('CELL_MAPPING', '小区映射不可读或格式有误：' + str(exc), path)
    return ids


def _raster(check, path, geometry, ids=None, allow_empty=False, **where):
    entry = check.file(path, current=True, **where)
    if not entry:
        return
    entry.update(geometry)
    if entry['size'] != geometry['expected_bytes']:
        check.issue('RASTER_SIZE', f"应为 {geometry['expected_bytes']} 字节，实际为 {entry['size']} 字节。", path, **where)
        return
    valid, invalid, minimum, maximum, unmapped = 0, 0, None, None, 0
    digest = hashlib.sha256()
    try:
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(_CHUNK), b''):
                digest.update(chunk)
                for (value,) in struct.iter_unpack('<h', chunk):
                    if value == -32768:
                        invalid += 1
                    else:
                        valid += 1
                        minimum = value if minimum is None else min(minimum, value)
                        maximum = value if maximum is None else max(maximum, value)
                        if ids is not None and (value == 0 or value not in ids):
                            unmapped += 1
        if digest.hexdigest() != entry['sha256']:
            check.issue('ARTIFACT_CHANGED', '栅格在校验期间发生变化。', path, **where)
        entry.update(valid=valid, invalid=invalid, minimum=minimum, maximum=maximum, unmapped=unmapped)
        if not valid and not allow_empty:
            check.issue('NO_VALID_CELLS', '栅格全部为 -32768 无效值，没有可用网格。', path, **where)
        if unmapped:
            check.issue('BESTSERVER_ID', f'{unmapped} 个有效网格使用了零编号或 cellid.csv 中不存在的小区编号。', path, **where)
    except (OSError, struct.error) as exc:
        check.issue('RASTER_READ', '栅格读取失败：' + str(exc), path, **where)
    return entry


def _height_folder(height):
    whole = math.floor(height)
    return (f'{height:.1f}' if height - whole > .09 else str(whole)) + 'm'


def _prediction(check, lines):
    context = check.context
    root = _path(context.get('pred_dir'))
    if root is None:
        check.uncertain('PATH_UNKNOWN', '无法确定预测输出目录。')
        return dict(status='unconfirmed'), 'unknown'
    if any('No cells have been choosed to this predication' in line for line in lines):
        check.uncertain('NO_PARTICIPATING_CELLS', '本次日志确认没有选中参与预测的小区；没有可归属本次的可用预测结果。', root)
        return dict(status='unconfirmed', no_participating_cells=True, regions=0, layers=0), 'not_written'
    indoor = context.get('func') == 'predindoor'
    fmt, entries = _index(check, root, indoor)
    if not entries:
        return dict(status='unconfirmed'), fmt
    if indoor:
        floors = context.get('indoor_floors') or []
        if not floors:
            check.uncertain('FLOORS_UNKNOWN', '缺少实际 DAS/AP 楼层信息，无法确认应有室内产物。', root)
            floors = sorted({int(_INDOOR.fullmatch(name)[2]) for name in entries if name != '*'})
        for floor in floors:
            pair = [entries.get(f'{product}_{floor}.dem', entries.get('*')) for product in ('RSRP', 'DLRSSINR')]
            if all(pair) and pair[0] != pair[1]:
                check.issue('INDEX_GRID_MISMATCH', '同一室内楼层的配套指标使用了不同网格。', root / 'index.txt', region=0, layer=floor)
            for product in ('RSRP', 'DLRSSINR'):
                name = f'{product}_{floor}.dem'
                geometry = entries.get(name, entries.get('*'))
                if geometry is None:
                    check.issue('INDEX_PRODUCT', '索引缺少本楼层必需的室内预测产物。', root / 'index.txt', layer=floor)
                    continue
                _raster(check, root / name, geometry, layer=floor, region=0)
        return dict(status='checked', floors=len(floors)), fmt

    ids = _mapping(check, root)
    products = ('RSRP', 'DLRSSINR', 'BESTSERVER') if context.get('func') == 'pred' else ('ECHORP', 'SCR')
    region_entries = {}
    for name, geometry in entries.items():
        match = _OUTDOOR.fullmatch(name)
        if match[1].upper() in products:
            region_entries.setdefault(int(match[2] or 0), {})[match[1].upper()] = (name, geometry)
    if not region_entries:
        check.uncertain('INDEX_PRODUCTS_UNKNOWN', '索引没有所选功能对应的已识别产物。', root / 'index.txt')
        return dict(status='unconfirmed'), fmt
    mode = context.get('mode') or {}
    effective = mode.get('effective')
    if effective not in ('ground', '3d', 'floor', 'building'):
        check.uncertain('MODE_UNKNOWN', '无法确定本任务应采用的空间计算模式。', root)
        return dict(status='unconfirmed'), fmt
    count, step = mode.get('layer_count'), mode.get('floor_height')
    cap = next((value for value in (mode.get('layer_cap'), mode.get('configured_layer_count'), count)
                if isinstance(value, int) and value > 0), None)
    if not isinstance(cap, int) and isinstance(step, (int, float)) and math.isfinite(step) and step > 0:
        height = mode.get('max_height')
        if isinstance(height, (int, float)) and math.isfinite(height) and height >= 0:
            cap = math.floor(height / step) + 1
    if effective == '3d' and not isinstance(count, int):
        count = cap
    if effective != 'ground' and (not isinstance(cap, int) or cap < 1 or not isinstance(step, (int, float)) or not math.isfinite(step) or step <= 0):
        check.uncertain('LAYERS_UNKNOWN', '无法确定本任务实际适用的输出层数。', root)
    if effective == '3d' and isinstance(count, int) and count > 10000:
        check.uncertain('LAYERS_LIMIT', '层数超过产物校验的检查上限。', root)
        return dict(status='unconfirmed'), fmt
    requested_regions = {r.get('id') for r in context.get('regions', []) if isinstance(r, dict)}
    omitted = sorted(requested_regions - set(region_entries))
    for region in omitted:
        check.uncertain('UNCOMPUTED_REGIONS', '本请求区域没有已计算的索引条目，其可用性尚不能确认。', root / 'index.txt', region=region)
    checked_layers = 0
    empty_regions = []
    for region, group in sorted(region_entries.items()):
        reference = next(iter(group.values()))[1]
        for product in products:
            if product not in group:
                check.issue('INDEX_PRODUCT', f'已计算区域缺少 {product} 索引条目。', root / 'index.txt', region=region, layer=0)
            elif group[product][1] != reference:
                check.issue('INDEX_GRID_MISMATCH', '同一区域的配套指标使用了不同网格。', root / 'index.txt', region=region, layer=0)
        # Inspect the base before imposing a 3d cube. An entirely empty region
        # never expands in the engine; one empty companion metric cannot hide
        # another metric's valid participation evidence.
        base = []
        for product in products:
            if product in group:
                name, geometry = group[product]
                base.append(_raster(check, root / name, geometry, ids if product == 'BESTSERVER' else None,
                                    allow_empty=effective == '3d', region=region, layer=0))
        checked_layers += 1
        if effective == '3d' and len(base) == len(products) and all(entry and entry.get('valid') == 0 for entry in base):
            empty_regions.append(region)
            check.uncertain('EMPTY_REGION', '本区域全部必查地面指标均无有效网格，没有参与计算证据；不要求未懒扩的完整上层立方体。', root, region=region, layer=0)
            continue
        if effective == '3d':
            for entry in base:
                if entry and entry.get('valid') == 0:
                    check.issue('NO_VALID_CELLS', '本区域其他指标已有有效值，但本配套指标全部为空，结果不可用。', entry['path'], region=region, layer=0)
        layers = []
        if effective == '3d' and isinstance(count, int) and 0 < count <= 10000 and isinstance(step, (int, float)) and step > 0:
            layers.extend((layer, root / _height_folder(layer * step)) for layer in range(1, count))
        elif effective in ('floor', 'building') and isinstance(step, (int, float)) and step > 0:
            # Floor cases expand lazily. Validate each observed region stack;
            # another region's height is not evidence that this one was computed.
            observed = []
            if root.is_dir():
                for folder in root.iterdir():
                    match = re.fullmatch(r'(\d+(?:\.\d+)?)m', folder.name)
                    if not match or not folder.is_dir():
                        continue
                    layer = round(float(match[1]) / step)
                    if layer <= 0 or (isinstance(cap, int) and layer >= cap):
                        continue
                    if _height_folder(layer * step) != folder.name:
                        continue
                    names = [name for name, _ in group.values()]
                    if any((folder / name).is_file() and check.changed(folder / name) for name in names):
                        observed.append((layer, folder))
            if observed:
                # Expansion to a high floor creates every lower case for this
                # region, but says nothing about another region's stack.
                last = max(layer for layer, _ in observed)
                if last > 10000:
                    check.uncertain('LAYERS_LIMIT', '已观察楼层数超过校验检查上限。', root, region=region)
                else:
                    layers.extend((layer, root / _height_folder(layer * step)) for layer in range(1, last + 1))
            elif isinstance(cap, int) and cap > 1:
                check.uncertain('FLOOR_OUTPUT_UNCONFIRMED', '仅存在地面产物，尚不能确认本区域建筑楼层的实际计算情况。', root, region=region)
        for layer, folder in layers:
            checked_layers += 1
            for product in products:
                if product in group:
                    name, geometry = group[product]
                    _raster(check, folder / name, geometry, ids if product == 'BESTSERVER' else None,
                            allow_empty=layer > 0 and effective in ('floor', 'building'), region=region, layer=layer)
    return dict(status='checked', regions=len(region_entries), layers=checked_layers,
                omitted_regions=omitted, empty_regions=empty_regions), fmt


def _xml(check, path, current=False, model_kind=None):
    where = {'model_kind': model_kind} if model_kind else {}
    entry = check.file(path, current=current, **where)
    if not entry:
        if model_kind:
            # Empty and unreadable current models are definite failures of the
            # selected model kind, just like a truncated XML fragment.
            return dict(path=str(path.resolve()), invalid=True, model_names=[], model_kind=model_kind)
        return None
    try:
        # TinyXML writes sibling roots (version + propagation categories).
        text = re.sub(r'<\?xml\s.*?\?>', '', _text(path), flags=re.S)
        root = ET.fromstring('<artifact>' + text + '</artifact>')
        if not list(root):
            raise ValueError('XML 模型片段没有元素')
    except (OSError, ValueError, ET.ParseError) as exc:
        entry['invalid'] = True
        check.issue('MODEL_XML', '模型 XML 片段解析失败：' + str(exc), path, **where)
        return entry
    if not model_kind:
        # CorrectionMeanVariance is a diagnostic with a different schema.
        entry['model_names'] = [node.text for node in root.iter('ModelName') if node.text and node.text.strip()]
        return entry
    entry['model_names'] = []
    versions = root.findall('ModelVersion')
    categories = [category for category in root.findall('PropagationCategory') if category.get('name') == 'LiShuttleModel']
    if not versions or not categories:
        entry['unconfirmed'] = True
        check.uncertain('MODEL_FORMAT_UNKNOWN', 'XML 缺少已核实的 ModelVersion 与 LiShuttleModel 类别结构，不能作为模型保存证据。', path, **where)
        return entry
    try:
        if len(versions) != 1 or not re.fullmatch(r'[+-]?\d+', (versions[0].text or '').strip()):
            raise ValueError('ModelVersion 必须是唯一整数元素')
        version = int(versions[0].text)
        expected = 1 if model_kind == 'scenes' else 0
        if version != expected:
            entry['unconfirmed'] = True
            check.uncertain('MODEL_VERSION_UNKNOWN', f'当前模型版本 {version} 不在本类别已核实版本 {expected} 的范围内。', path, **where)
            return entry
        identifiers, names = set(), set()
        models = [model for category in categories for model in category.findall('Model')]
        if not models:
            raise ValueError('已核实类别中没有 Model 元素')
        for model in models:
            identifier = model.get('ID', '')
            if not re.fullmatch(r'[+-]?\d+', identifier) or not 0 <= int(identifier) <= 2147483647:
                raise ValueError('Model ID 缺失或不是有效非负 int32 整数')
            identifier = int(identifier)
            name = model.findtext('ModelName')
            if not name or not name.strip():
                raise ValueError('ModelName 为空')
            if identifier in identifiers:
                raise ValueError('Model ID 重复，模型身份不唯一')
            # SaveCommonModel appends with overwrite=false and a fresh ID;
            # historical general models may legitimately share ModelName.
            if model_kind != 'general' and name in names:
                raise ValueError('ModelName 重复，模型身份不唯一')
            identifiers.add(identifier)
            names.add(name)
            for field in ('K0', 'Knear', 'Kfar', 'K0_nlos', 'Knear_nlos', 'Kfar_nlos'):
                value = model.findtext(field)
                if value is None or not math.isfinite(float(value)) or abs(float(value)) > 3.4028235e38:
                    raise ValueError(f'{name} 缺少有效有限系数 {field}')
            if model_kind == 'scenes':
                for field in ('Frequency', 'City', 'Features'):
                    if not (model.findtext(field) or '').strip():
                        raise ValueError(f'场景模型 {name} 缺少 {field}')
                # The loader permits absent training groups, but any present
                # group must carry the reviewed writer's usable finite data.
                for group_name in ('TRAING_LOS', 'TRAING_NLOS'):
                    group = model.find(group_name)
                    if group is None:
                        continue
                    count = group.findtext('dataSize') or ''
                    if not re.fullmatch(r'\d+', count.strip()):
                        raise ValueError(f'{name}/{group_name} 的 dataSize 无效')
                    for field, length in (('sumY', 1), ('squareY', 1), ('sumX', 4), ('squareX', 4), ('sumProduct', 10)):
                        values = (group.findtext(field) or '').split(',')
                        if len(values) != length or not all(math.isfinite(float(value)) for value in values):
                            raise ValueError(f'{name}/{group_name}/{field} 的统计量无效')
            entry['model_names'].append(name)
        entry.update(model_version=version, model_format='LiShuttleModel', model_ids=sorted(identifiers))
    except (ValueError, OverflowError) as exc:
        entry['invalid'] = True
        check.issue('MODEL_STRUCTURE', '已核实的模型结构或必要参数无效：' + str(exc), path, **where)
    return entry


def _csv_report(check, path, current=False):
    entry = check.file(path, current=current)
    if not entry:
        return
    try:
        rows = csv.reader(io.StringIO(_text(path)))
        header = next(rows, [])
        if len(header) < 2:
            raise ValueError('报告缺少已识别的 CSV 表头')
        entry['columns'] = [value.strip() for value in header]
        data = [row for row in rows if any(row)]
        entry['rows'] = len(data)
        entry['ids'] = [row[0].strip() for row in data if row]
        selected = [(column, index) for index, column in enumerate(entry['columns']) if column in ('cell', 'update', 'model_id')]
        entry['records'] = [{column: row[index] if index < len(row) else '' for column, index in selected} for row in data]
    except (OSError, ValueError, csv.Error) as exc:
        check.issue('REPORT_CSV', '校正报告读取失败：' + str(exc), path)
    return entry


def _clean_grids(check, dt):
    """The reviewed engine always writes this final report; legacy is explicit."""
    path = dt / 'clean_grids.csv'
    capability = (check.context.get('result_capabilities') or {}).get('clean_grids')
    if capability is not True and not path.is_file():
        check.uncertain('CLEAN_GRIDS_CAPABILITY_UNKNOWN', '未发现本次清洗网格报告，且当前引擎是否支持该最终产物尚未确认。', path)
        return
    entry = check.file(path, current=True)
    if not entry:
        return
    # This can be a large report. CSV rows are read incrementally rather than
    # treating clean grids as a small metadata file. Source sizeof(header)
    # writes a terminating NUL in both the base and Windows addition headers.
    error = None
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            with path.open('r', encoding=encoding, newline='') as handle:
                rows = csv.reader(handle, strict=True)
                header = [value.replace('\0', '').strip() for value in next(rows, [])]
                if header[:5] != ['PCTime', 'cellID', 'Lon', 'Lat', 'RSRP']:
                    raise ValueError('表头与源代码 PCTime,cellID,Lon,Lat,RSRP 不匹配')
                count = 0
                for line, row in enumerate(rows, 2):
                    if not any(row):
                        continue
                    if len(row) < 5 or not row[1].strip() or not re.fullmatch(r'\d{1,2}:\d{1,2}:\d{1,2}', row[0].strip()):
                        raise ValueError(f'第 {line} 行缺少时间、小区编号或实测数值')
                    longitude, latitude, rsrp = map(float, row[2:5])
                    if not all(math.isfinite(value) for value in (longitude, latitude, rsrp)) or not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
                        raise ValueError(f'第 {line} 行经纬度或 RSRP 不是可用有限数值')
                    count += 1
                entry.update(rows=count, columns=header)
                if not count:
                    check.issue('CLEAN_GRIDS_EMPTY', '本次清洗网格报告没有可用实测网格。', path)
            return
        except UnicodeDecodeError as exc:
            error = exc
        except (OSError, ValueError, csv.Error) as exc:
            error = exc
            break
    check.issue('CLEAN_GRIDS_FORMAT', '清洗网格报告格式或内容无效：' + str(error), path)


def _model_kind(unit):
    return dict(status='unconfirmed', processed=0, succeeded=0, updated=0,
                skipped=0, failed=0, unit=unit, reason='', items=[])


def _kind_status(kind):
    if kind.get('uncertain'):
        kind['status'] = 'unconfirmed'
    elif kind['failed']:
        kind['status'] = 'partial' if kind['updated'] or (kind['succeeded'] and kind['failed'] < kind['processed']) else 'failed'
    elif kind['updated']:
        kind['status'] = 'success'
    elif kind['succeeded']:
        kind['status'] = 'no_update'
    elif kind['skipped']:
        kind['status'] = 'skipped'
    else:
        kind['status'] = 'unconfirmed'
    kind.pop('uncertain', None)


def _current_model_entries(check, models, kind, names=None):
    if models is None:
        return []
    if kind == 'cells':
        folder = models / 'cells'
        paths = sorted(folder.rglob('*.xml')) if folder.is_dir() else []
    elif kind == 'scenes':
        paths = [models / 'scenes/SceneModel.xml']
    else:
        # Factory reads the first existing top-level Bin/models XML and keeps
        # its basename when saving to temporary storage. Enumeration order is
        # not a stable contract: inspect the eligible basenames and named model.
        eligible = check.baseline_metadata.get('general_model_files')
        if eligible is None:
            bin_dir = _path(check.context.get('bin_dir'))
            source = bin_dir / 'models' if bin_dir else None
            eligible = [path.name for path in source.iterdir() if path.is_file() and path.name.endswith('.xml')] if source and source.is_dir() else []
        paths = [models / name for name in (eligible or ['LiShuttleModel.xml'])]
    entries = []
    for path in paths:
        if not path.is_file() or not path.resolve().is_relative_to(models) or not check.changed(path, model_kind=kind):
            continue
        entry = _xml(check, path, model_kind=kind)
        if entry:
            if names is None or entry.get('invalid') or entry.get('unconfirmed') or set(entry.get('model_names', [])) & set(names):
                entries.append(entry)
    return entries


def _aggregate_model_kinds(kinds):
    values = list(kinds.values())
    counts = dict(unit='model_kinds', processed=sum(item['processed'] > 0 for item in values),
                  succeeded=sum(item['succeeded'] > 0 for item in values),
                  updated=sum(item['updated'] > 0 for item in values),
                  skipped=sum(item['status'] == 'skipped' for item in values),
                  failed=sum(item['failed'] > 0 for item in values),
                  unconfirmed=sum(item['status'] == 'unconfirmed' for item in values))
    if counts['unconfirmed']:
        status = 'unconfirmed'
    elif any(item['status'] == 'partial' for item in values) or (counts['failed'] and counts['succeeded']):
        # A solver success followed by its own save failure is not a successful
        # second category. Count usable outcomes across distinct kinds.
        healthy = any(item['status'] in ('success', 'no_update') for item in values)
        status = 'partial' if healthy or any(item['status'] == 'partial' for item in values) else 'failed'
    elif counts['failed']:
        status = 'failed'
    elif counts['updated']:
        status = 'success'
    elif counts['succeeded']:
        status = 'no_update'
    else:
        status = 'unconfirmed'
    return status, counts


def _cell_identity_evidence(check, cells, sites, entries, report, models, definite_failure=False):
    """Join three source identities using only the captured pre-run mapping."""
    records = check.baseline_metadata.get('engineering_records')
    current = (check.context.get('engineering') or {}).get('records')
    updated_sites = [site for site in sites if site['update']]
    if not isinstance(records, list) or not records or not all(isinstance(record, dict) and
            all(isinstance(record.get(field), str) and record[field] for field in ('site_name', 'transceiver_name', 'cell_id')) for record in records):
        if not definite_failure:
            cells.update(uncertain=True, reason='运行前缺少已核实的 site_name → transceiver_name → cell_id 固定映射，不能用报告或任意模型名补造。')
            check.uncertain('CELL_IDENTITY_MAPPING_UNKNOWN', cells['reason'], models, model_kind='cells')
        return 0
    if current is not None and current != records:
        if not definite_failure:
            cells.update(uncertain=True, reason='校验上下文的工参身份映射与启动前基线不一致，继续使用固定基线但不能确认完整归属。')
            check.uncertain('CELL_IDENTITY_CONTEXT_CHANGED', cells['reason'], models, model_kind='cells')
    # The source has one saved model for the first cell of each transceiver.
    # Ambiguous/duplicated mappings cannot identify a persisted update reliably.
    identities = [(record['site_name'], record['transceiver_name'], record['cell_id']) for record in records]
    if len(set(identities)) != len(identities) or len({record['transceiver_name'] for record in records}) != len(records) or len({record['cell_id'] for record in records}) != len(records):
        if not definite_failure:
            cells.update(uncertain=True, reason='工参固定身份映射存在重复或歧义，不能确认逐对象模型更新。')
            check.uncertain('CELL_IDENTITY_MAPPING_UNKNOWN', cells['reason'], models, model_kind='cells')
        return 0
    present = {name for entry in entries if not entry.get('invalid') and not entry.get('unconfirmed') for name in entry.get('model_names', [])}
    reports = report.get('records', []) if report else []
    verified_sites = set()
    cells['verified_objects'] = []
    cells['expected_objects'] = 0
    for site in updated_sites:
        objects = [record for record in records if record['site_name'] == site['site']]
        cells['expected_objects'] += len(objects)
        missing = []
        if not objects:
            missing.append('固定工参中没有该站点')
        for record in objects:
            matching = [row for row in reports if row.get('cell') == record['transceiver_name']]
            summary_updated = bool(report and report.get('changed')) and len(matching) == 1 and matching[0].get('update', '').strip().lower() == 'yes'
            if summary_updated and record['cell_id'] in present:
                cells['verified_objects'].append(dict(site=site['site'], transceiver_name=record['transceiver_name'], cell_id=record['cell_id']))
            else:
                missing.append(f"{record['transceiver_name']} → {record['cell_id']} 缺少唯一 update=yes 本次报告或匹配的已验证模型")
        item = next((item for item in cells['items'] if item['site'] == site['site']), None)
        if not missing:
            verified_sites.add(site['site'])
            if item:
                item.update(status='success', reason='本次逐站更新、逐收发信机报告与全部固定小区模型身份均匹配。')
        else:
            if item:
                item.update(status='failed' if definite_failure else 'unconfirmed', reason='；'.join(missing))
            if not definite_failure:
                cells.update(uncertain=True, reason='部分声称更新的站点尚未验证全部固定对象；仅保留已验证的站点子集数量。')
                check.uncertain('NO_CURRENT_MODEL', '；'.join(missing), models, model_kind='cells', site=site['site'])
    return len(verified_sites)


def _calibration(check, lines):
    context = check.context
    # The source groups physical sites, but their textual siteName need not be
    # unique. Preserve every observed outcome and flag ambiguous group joins.
    values, seen, duplicate_sites = [], set(), set()
    for line in lines:
        match = _SITE.search(line)
        if match:
            if match[1] in seen:
                duplicate_sites.add(match[1])
            seen.add(match[1])
            values.append(dict(site=match[1], grids=int(match[2]), success=match[3] == 'Y',
                               update=match[4] == 'Y', code=int(match[5], 16)))
    succeeded = sum(site['success'] for site in values)
    updated = sum(site['update'] for site in values)
    business = dict(status='unconfirmed', total=len(values), succeeded=succeeded,
                    failed=len(values) - succeeded, updated=updated,
                    no_update=len(values) - updated, sites=values, duplicate_site_names=sorted(duplicate_sites))
    kinds = dict(cells=_model_kind('site_groups'), general=_model_kind('models'), scenes=_model_kind('scenes'))
    business['model_kinds'] = kinds
    business['status'], business['counts'] = _aggregate_model_kinds(kinds)
    dt = _path(context.get('dt_dir'))
    name = context.get('task_name')
    if dt is None or not name:
        check.uncertain('CALIBRATION_CONTEXT_UNKNOWN', '无法确定 DT 目录或任务报告前缀。')
        return business
    check.file(dt / 'meas.anchor')
    _clean_grids(check, dt)
    cell_report_path = dt / (name + '_cell_summary.csv')
    cell_report = _csv_report(check, cell_report_path, current=True)
    if cell_report:
        if not {'cell', 'update'}.issubset(set(cell_report.get('columns', []))):
            check.issue('REPORT_CSV', '逐小区报告缺少 cell 或 update 字段。', cell_report_path)
        if not cell_report.get('rows'):
            check.issue('EMPTY_REPORT', '逐小区报告没有结果记录。', cell_report_path)
    params = context.get('params') or {}
    scene = str(params.get('IsCorrectSceneModel', 'true')).lower()
    scene_report = None
    if scene in ('true', '1'):
        scene_report = _csv_report(check, dt / (name + '_scene_summary.csv'), current=True)
    elif scene not in ('false', '0'):
        check.uncertain('CALIBRATION_SETTING_UNKNOWN', '无法确定场景模型报告是否适用。')
    models = _path(context.get('models_dir'))
    cells = kinds['cells']
    cells.update(processed=len(values), succeeded=succeeded, failed=len(values) - succeeded,
                 items=[dict(**site, status='success' if site['success'] else 'failed',
                             reason=f"逐站日志：success={'Y' if site['success'] else 'N'}，update={'Y' if site['update'] else 'N'}，code=0x{site['code']:x}；保存结果见模型类别状态。") for site in values])
    if updated:
        entries = _current_model_entries(check, models, 'cells')
        invalid = any(entry.get('invalid') for entry in entries)
        save_failed = any('Failed to save cell models!' in line for line in lines)
        verified = _cell_identity_evidence(check, cells, values, entries, cell_report, models,
                                           definite_failure=invalid or save_failed)
        cells['updated'] = verified if not save_failed else 0
        if invalid or save_failed:
            cells.update(failed=max(cells['failed'], updated - cells['updated'], 1), reason='本次站点模型 XML 无效或日志确认保存失败；其他已验证对象单独保留。')
            check.issue('CELL_MODEL_SAVE_FAILED', cells['reason'], models, severity='warning', model_kind='cells')
    if not values:
        cells.update(uncertain=True, reason='没有捕获本次逐站结果，不能从历史合并报告推断。')
        check.uncertain('CALIBRATION_COUNTS_UNKNOWN', cells['reason'], dt, model_kind='cells')
    elif any(site['grids'] == 0 for site in values):
        cells.update(uncertain=True, reason='逐站结果包含零个实测网格，业务有效性未确认。')
        check.uncertain('CALIBRATION_GRIDS_UNKNOWN', cells['reason'], dt, model_kind='cells')
    if duplicate_sites:
        cells.update(updated=0, uncertain=True, reason='本次多个站点组使用同一日志站点名称，现有固定映射不能唯一对应物理分组。')
        for site in sorted(duplicate_sites):
            check.uncertain('CELL_SITE_GROUP_AMBIGUOUS', cells['reason'], dt, model_kind='cells', site=site)
            for item in cells['items']:
                if item['site'] == site:
                    item.update(status='unconfirmed', reason=cells['reason'])
    _kind_status(cells)

    general = kinds['general']
    outcome = None
    for line in lines:
        match = re.search(r'The calibration of the general model (completed|failed)!', line)
        if match:
            outcome = match[1]
        elif 'No enough data for general model calibration:' in line:
            outcome = 'skipped'
    general_name = params.get('CalNewModelName')
    general_save_failed = any('Failed to save the common model!' in line or
        ('Failed to save propagation model(' in line and (not general_name or f'model({general_name})' in line)) for line in lines)
    if general_save_failed:
        general.update(processed=1, succeeded=int(outcome == 'completed'), failed=1, reason='通用模型求解后保存失败，不能判为更新成功。')
        check.issue('GENERAL_MODEL_SAVE_FAILED', general['reason'], models, severity='warning', model_kind='general')
    elif outcome == 'skipped':
        general.update(skipped=1, reason='本次没有足够有效数据，源码跳过通用模型校正。')
    elif outcome == 'failed':
        general.update(processed=1, failed=1, reason='本次通用模型校正未被接受。')
        check.issue('GENERAL_MODEL_FAILED', general['reason'], models, severity='warning', model_kind='general')
    elif outcome == 'completed':
        general.update(processed=1, succeeded=1)
        if not general_name:
            general.update(uncertain=True, reason='缺少 CalNewModelName，无法确认实际保存模型身份。')
            check.uncertain('GENERAL_MODEL_NAME_UNKNOWN', general['reason'], models, model_kind='general')
        else:
            entries = _current_model_entries(check, models, 'general', [general_name])
            general['items'] = []
            for entry in entries:
                if entry.get('invalid'):
                    status, reason = 'failed', 'XML 无效。'
                elif entry.get('unconfirmed') or general_name not in entry.get('model_names', []):
                    status, reason = 'unconfirmed', '无法确认当前模型格式、版本或 CalNewModelName 对应保存身份。'
                else:
                    status, reason = 'success', '当前变化的模型文件包含 CalNewModelName 对应身份。'
                general['items'].append(dict(name=general_name, path=entry['path'], status=status, reason=reason))
            if any(entry.get('invalid') for entry in entries):
                general.update(failed=1, reason='本次通用模型 XML 无效。')
            elif any(general_name in entry.get('model_names', []) for entry in entries):
                general['updated'] = 1
            else:
                general.update(uncertain=True, reason='通用模型日志完成，但实际模型文件中缺少本次变化且名称匹配的保存结果。')
                check.uncertain('NO_CURRENT_GENERAL_MODEL', general['reason'], models, model_kind='general')
    else:
        general.update(uncertain=True, reason='没有捕获本次通用模型的完成、失败或无足够数据记录。')
        check.uncertain('GENERAL_OUTCOME_UNKNOWN', general['reason'], models, model_kind='general')
    _kind_status(general)

    scenes = kinds['scenes']
    scene_events = {}
    for line in lines:
        match = re.search(r'The calibration of scene (.*?) (completed\.|failed!!)', line)
        if match:
            scene_events[match[1]] = match[2] == 'completed.'
    scenes['items'] = [dict(name=name, success=success,
                           status='unconfirmed' if success else 'failed',
                           reason='源码日志记录校正完成，等待保存证据。' if success else '源码日志记录场景校正失败。') for name, success in scene_events.items()]
    scenes.update(processed=len(scene_events), succeeded=sum(scene_events.values()), failed=sum(not value for value in scene_events.values()))
    if scene in ('false', '0'):
        scenes.update(skipped=1, reason='本任务未启用场景模型校正。')
    elif scene_events:
        accepted = {name for name, success in scene_events.items() if success}
        if accepted:
            entries = _current_model_entries(check, models, 'scenes')
            present = {name for entry in entries for name in entry.get('model_names', [])}
            report_names = set(scene_report.get('ids', [])) if scene_report else set()
            if any(entry.get('invalid') for entry in entries) or any('Failed to save scene model!' in line for line in lines):
                scenes.update(failed=scenes['failed'] + len(accepted), reason='本次场景模型保存失败或 XML 无效。')
                check.issue('SCENE_MODEL_SAVE_FAILED', scenes['reason'], models, severity='warning', model_kind='scenes')
                for item in scenes['items']:
                    if item['success']:
                        item.update(status='failed', reason='本次场景模型保存失败或 XML 无效。')
            elif accepted <= present and accepted <= report_names:
                scenes['updated'] = len(accepted)
                for item in scenes['items']:
                    if item['success']:
                        item.update(status='success', reason='本次场景报告与变化后的模型 XML 均包含匹配身份。')
            else:
                scenes.update(uncertain=True, reason='本次完成的场景模型在报告或变化后的 SceneModel.xml 中缺少匹配身份。')
                check.uncertain('NO_CURRENT_SCENE_MODEL', scenes['reason'], models / 'scenes/SceneModel.xml' if models else '', model_kind='scenes')
        if scenes['failed']:
            check.issue('SCENE_MODEL_FAILED', '本次部分场景模型校正或保存失败。', models, severity='warning', model_kind='scenes')
    elif any("No enough data for scenes' calibration!" in line for line in lines) and not (scene_report and scene_report.get('rows')):
        scenes.update(skipped=1, reason='本次没有足够有效数据，源码跳过场景模型校正。')
    else:
        scenes.update(uncertain=True, reason='场景校正已启用，但没有完整的本次逐场景结果记录。')
        check.uncertain('SCENE_OUTCOME_UNKNOWN', scenes['reason'], models, model_kind='scenes')
    _kind_status(scenes)
    out = _path(context.get('out_dir'))
    # This diagnostic is written only when both general and exclusive models
    # exist. Its absence is not a mandatory-product failure.
    if out and (out / 'CorrectionMeanVariance.xml').is_file():
        path = out / 'CorrectionMeanVariance.xml'
        try:
            current = _fingerprint(path)
            previous = check.baseline.get(str(path))
            if previous is None or previous.get('sha256') != current['sha256']:
                _xml(check, path)
        except OSError as exc:
            check.issue('ARTIFACT_READ', '产物读取失败：' + str(exc), path)
    business['status'], business['counts'] = _aggregate_model_kinds(kinds)
    return business


def validate(context, baseline, lines, exit_code, cancelled=False):
    """Separate process completion, artifact integrity and business usability."""
    lines = str(lines).splitlines() if isinstance(lines, str) else [str(line) for line in (lines or [])]
    check = _Check(context, baseline)
    func = context.get('func')
    fmt = None
    business = dict(status='unconfirmed')
    try:
        if func in ('pred', 'commsensing', 'predindoor'):
            business, fmt = _prediction(check, lines)
        elif func == 'cali':
            business = _calibration(check, lines)
        else:
            check.uncertain('FUNCTION_UNREVIEWED', '该功能尚无经过核实的结果校验规则，不能自动判为成功。')
    except (OSError, ValueError, TypeError) as exc:
        check.uncertain('VALIDATION_INCOMPLETE', '结果校验未能完成：' + str(exc))
    hard_errors = [issue for issue in check.issues if issue['severity'] == 'error']
    if hard_errors and business.get('status') == 'partial' and all(issue.get('model_kind') for issue in hard_errors):
        verdict = 'partial'
    elif hard_errors:
        verdict = 'failed'
    elif check.unknown:
        verdict = 'unconfirmed'
    elif business['status'] in ('failed', 'partial', 'no_update'):
        verdict = business['status']
    else:
        verdict = 'success'
    if not cancelled and exit_code is None:
        verdict = 'unconfirmed'
    elif exit_code not in (0, None):
        verdict = 'failed'
    if cancelled:
        verdict = 'cancelled'
    if func in ('pred', 'commsensing', 'predindoor'):
        business['status'] = 'unusable' if hard_errors else 'unconfirmed' if check.unknown else 'usable'
        business['valid_cells'] = sum(entry.get('valid', 0) for entry in check.checked)
    process = dict(exit=exit_code, exit_code=exit_code, status='cancelled' if cancelled else 'running' if exit_code is None else 'exited' if exit_code == 0 else 'failed', cancelled=bool(cancelled))
    directory = context.get('pred_dir' if func in ('pred', 'commsensing', 'predindoor') else 'out_dir', '')
    root = _path(directory)
    files = []
    checked_paths = {entry['path'] for entry in check.checked}
    for path, info in sorted(check.fingerprints.items()):
        if path not in checked_paths:
            continue
        file_path = Path(path)
        rel = str(file_path.relative_to(root)).replace('\\', '/') if root and file_path.is_relative_to(root) else file_path.name
        files.append(dict(rel=rel, size=info['size'], path=path))
    errors = [line for line in lines if re.search(r'\b(?:ERROR|FATAL)\b', line, re.I)]
    return dict(process=process, artifacts=dict(status='invalid' if hard_errors else 'unconfirmed' if check.unknown else 'valid',
                checked=check.checked, index_format=fmt), business=business, verdict=verdict,
                issues=check.issues, files=files, dir=str(directory or ''), exists=bool(root and root.is_dir()),
                log_tail=lines[-80:], errors=errors[-30:])
