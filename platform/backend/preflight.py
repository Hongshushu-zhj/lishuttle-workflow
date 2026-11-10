"""Read-only checks for the reviewed engine's real inputs and layer semantics.

Paths in XML are interpreted from Bin, exactly like the launched process. This
module deliberately does not stage files, create output folders or repair XML.
"""
import csv
import codecs
import hashlib
import io
import math
import os
from pathlib import Path
import re
import shlex
import struct
import sys
import xml.etree.ElementTree as ET

from engineering import engineering_kind, normalized
from engineering_format import cell_layout, header_line_count, INDOOR_COLUMNS, ALIASES as _COLUMN_LABELS

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from indoor_maps import indoor_map_entries, engine_indoor_map_entries  # noqa: E402


def _path(value, base):
    if not value:
        return ''
    return str(Path(os.path.abspath(os.path.join(str(base), str(value).replace('\\', os.sep)))))


def _text(path):
    raw = Path(path).read_bytes()
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return raw.decode(encoding)
        except UnicodeError:
            pass
    raise ValueError('文件不是 UTF-8 或 GB18030 文本')


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _bool(params, tag, default=True):
    value = str(params.get(tag, str(default))).lower()
    if value in ('false', '0'):
        return False
    if value in ('true', '1'):
        return True
    return default


def _open_text(path):
    """Choose supported text encoding without loading large data into memory."""
    with open(path, 'rb') as fh:
        sample = fh.read(65536)
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            codecs.getincrementaldecoder(encoding)().decode(sample, final=False)
            return open(path, encoding=encoding, newline='')
        except UnicodeError:
            pass
    raise ValueError('文件不是 UTF-8 或 GB18030 文本')


def _xml_fragments(path):
    text = re.sub(r'<\?xml\b.*?\?>', '', _text(path), flags=re.S)
    return ET.fromstring('<Document>' + text + '</Document>')


def _cell_columns(bin_dir, issue, layout=None):
    # The editor and preflight use exactly the same format decoding and offsets.
    # CellLoader.h defaults remain in force if the XML cannot be parsed.
    layout = cell_layout(bin_dir) if layout is None else layout
    path = str(Path(bin_dir) / 'cellformat.xml')
    if layout['error']:
        issue('warning', 'ENGINEERING_FORMAT_DEFAULT', f'未加载 Bin/cellformat.xml，使用 CellLoader.h 默认列布局：{layout["error"]}', 'EngineeringFilePath', path)
    return layout['columns'], layout['header_lines']


def _engineering(path, expected, issue, bin_dir=None):
    info = dict(path=path, kind='', rows=0, ids=[], floors=[], antennas=[], sensing_antennas=[], models=[], records=[])
    if not path or not Path(path).is_file():
        issue('error', 'ENGINEERING_MISSING', '工参 CSV 不存在', 'EngineeringFilePath', path)
        return info
    layout = cell_layout(bin_dir or Path(path).parent) if expected == 'outdoor' else None
    info['kind'] = engineering_kind(path)
    if not info['kind'] and layout and layout['explicit'] and layout['header_lines'] == 0:
        # A trusted zero-header format is the only source of layout evidence
        # for a data-only file. Its records still undergo every ordinary check.
        info['kind'] = expected
    if info['kind'] != expected:
        issue('error', 'ENGINEERING_KIND', f'工参表头需要 {expected}，实际为 {info["kind"] or "无法识别"}', 'EngineeringFilePath', path)
        return info
    try:
        if expected == 'indoor':
            columns, headers = INDOOR_COLUMNS.copy(), 2
        else:
            columns, headers = _cell_columns(bin_dir or Path(path).parent, issue, layout)
        strings = ['CellId', 'Antenna', 'PropagationModel', 'CellType'] + (['ApId'] if expected == 'indoor' else ['SiteId'])
        if columns.get('CityCode', -1) >= 0:
            strings.append('CityCode')
        numeric = ['ChannelNumber', 'EPRE', 'TxNumber', 'RxNumber', 'AntennaHeight', 'Azimuth', 'Tilt']
        numeric += ['Floor', 'x', 'y', 'ULTrafficLoad'] if expected == 'indoor' else ['Longitude', 'Latitude', 'SensePower']
        info['format'] = dict(columns=columns, header_lines=headers, source='indoor fixed offsets' if expected == 'indoor' else str(Path(bin_dir or Path(path).parent) / 'cellformat.xml'))
        ids, floors, antennas, sensing_antennas, models = set(), set(), set(), set(), set()
        with _open_text(path) as fh:
            rows = list(csv.reader(fh, strict=True))
        detected_headers = header_line_count(rows, max(2, headers))
        if detected_headers and detected_headers != headers:
            issue('error', 'ENGINEERING_HEADER_COUNT',
                  f'识别到 {detected_headers} 行工参表头，但引擎配置读取 {headers} 行；'
                  '请确认 Bin/cellformat.xml 的 HeaderLines，避免遗漏首条数据',
                  'EngineeringFilePath', path)
        # Known labels are checked against configured positions, never used to reorder data.
        for tag, aliases in _COLUMN_LABELS.items():
            if tag not in columns:
                continue
            labels = {normalized(a) for a in aliases}
            for header in rows[:headers]:
                found = [i for i, value in enumerate(header) if normalized(value) in labels]
                if found and columns[tag] not in found:
                    issue('error', 'ENGINEERING_LAYOUT', f'{tag} 表头位于列 {found[0] + 1}，引擎实际读取列 {columns[tag] + 1}', 'EngineeringFilePath', path)
        for line, row in enumerate(rows[headers:], headers + 1):
            if not any(c.strip() for c in row):
                continue
            try:
                for tag in strings:
                    if not row[columns[tag]]:
                        raise ValueError(f'{tag} 不能为空')
                cell_id = row[columns['CellId']]
                for label in numeric:
                    value = _number(row[columns[label]])
                    if value is None:
                        raise ValueError(f'{label} 不是有限数值')
                    if label in ('ChannelNumber', 'TxNumber', 'RxNumber', 'Floor') and value != int(value):
                        raise ValueError(f'{label} 必须为整数')
                    if label == 'ChannelNumber' and value < 0:
                        raise ValueError('ChannelNumber 不能为负')
                    if label == 'Longitude' and not -180 <= value <= 180:
                        raise ValueError('经度超出范围')
                    if label == 'Latitude' and not -90 <= value <= 90:
                        raise ValueError('纬度超出范围')
                    if label == 'Floor':
                        floors.add(int(value))
                ids.add(cell_id)
                antennas.add((row[columns['Antenna']], _number(row[columns['ElecTilt']]) or 0))
                if expected != 'indoor' and columns.get('SenseAntenna', -1) >= 0:
                    sense = row[columns['SenseAntenna']] or row[columns['Antenna']]
                    sensing_antennas.add((sense, _number(row[columns['SenseTilt']]) or 0))
                models.add(row[columns['PropagationModel']])
                if expected == 'outdoor':
                    # Ordinary CellLoader::createTransceiver reads siteName
                    # from SiteId and assigns name from its first cell's ID.
                    # Keep these domains explicit for calibration persistence.
                    info['records'].append(dict(cell_id=cell_id, site_name=row[columns['SiteId']],
                                                transceiver_name=cell_id))
                info['rows'] += 1
            except (IndexError, ValueError) as exc:
                issue('error', 'ENGINEERING_ROW', f'工参第 {line} 行：{exc}', 'EngineeringFilePath', path)
        info.update(ids=sorted(ids), floors=sorted(floors), antennas=[dict(name=name, tilt=tilt) for name, tilt in sorted(antennas)],
            sensing_antennas=[dict(name=name, tilt=tilt) for name, tilt in sorted(sensing_antennas)], models=sorted(models))
        if not info['rows']:
            issue('error', 'ENGINEERING_EMPTY', '工参 CSV 没有可用数据行（表头不计为数据）', 'EngineeringFilePath', path)
    except (OSError, ValueError, csv.Error, StopIteration) as exc:
        issue('error', 'ENGINEERING_INVALID', f'工参读取失败：{exc}', 'EngineeringFilePath', path)
    return info


def _index(path, tag, issue, required=True, vector=False):
    """PLANET indices refer to files relative to their own directory."""
    entries = []
    if not path or not Path(path).is_file():
        issue('error' if required else 'warning', 'MAP_INDEX_MISSING', '地图索引不存在', tag, path)
        return entries
    try:
        for line, text in enumerate(_text(path).splitlines(), 1):
            if not text.strip():
                continue
            parts = text.split()
            count, start = (7, 2) if vector else (6, 1)
            bounds = [_number(v) for v in parts[start:start + 4]]
            valid = len(parts) >= count and len(bounds) == 4 and None not in bounds
            if valid:
                valid = bounds[0] < bounds[1] and bounds[2] < bounds[3]
            resolution = None if vector or len(parts) < 6 else _number(parts[5])
            if not vector:
                valid = valid and resolution is not None and resolution > 0
            if not valid:
                issue('error' if required else 'warning', 'MAP_INDEX_INVALID', f'地图索引第 {line} 行格式或范围无效', tag, path)
                continue
            references = [_path(parts[i], Path(path).parent) for i in range(2 if vector else 1)]
            missing = [p for p in references if not Path(p).is_file() or Path(p).stat().st_size == 0]
            for ref in missing:
                issue('error' if required else 'warning', 'MAP_REFERENCE_MISSING', f'地图索引第 {line} 行引用文件不存在或为空', tag, ref)
            needed = None
            if not missing and not vector:
                # GeoRasterData::InitDataBuffer quantizes resolution to 1/1024,
                # shrinks right/top by EPSILON and reads signed 16-bit samples.
                scaled = resolution * 1024 + 0.5
                if not math.isfinite(scaled):
                    issue('error' if required else 'warning', 'MAP_INDEX_INVALID', f'地图索引第 {line} 行分辨率量化超出可表示范围', tag, path)
                    continue
                step = math.floor(scaled) / 1024
                width, height = bounds[1] - bounds[0] - 1e-9, bounds[3] - bounds[2] - 1e-9
                if step <= 0 or not all(math.isfinite(v) and v > 0 and math.isfinite(v / step) for v in (width, height)):
                    issue('error' if required else 'warning', 'MAP_INDEX_INVALID', f'地图索引第 {line} 行分辨率不能构成有效栅格', tag, path)
                    continue
                needed = math.ceil(width / step) * math.ceil(height / step) * 2
                if needed <= 0 or Path(references[0]).stat().st_size < needed:
                    issue('error' if required else 'warning', 'MAP_RASTER_TRUNCATED', f'地图索引第 {line} 行栅格需要至少 {needed} 字节', tag, references[0])
                    continue
            if not missing:
                entries.append(dict(paths=references, bounds=bounds, resolution=resolution, raster_bytes=needed))
        if not entries:
            issue('error' if required else 'warning', 'MAP_INDEX_EMPTY', '地图索引没有可用的引用记录', tag, path)
    except (OSError, ValueError, OverflowError) as exc:
        issue('error' if required else 'warning', 'MAP_INDEX_INVALID', f'无法读取地图索引：{exc}', tag, path)
    return entries


def _building_height(entries, vector=False):
    """Return one usable height as evidence; never scan a whole large raster."""
    for entry in entries:
        try:
            if vector:
                # PLANET attribute: id, quoted name, building height, clutter.
                with _open_text(entry['paths'][1]) as attributes:
                    for line in attributes:
                        fields = shlex.split(line, posix=True)
                        height = _number(fields[2]) if len(fields) >= 4 else None
                        if height is None or height <= 0:
                            continue
                        building_id = int(fields[0])
                        # Require geometry for the same positive-height building.
                        with _open_text(entry['paths'][0]) as geometry:
                            for line in geometry:
                                header = line.split()
                                if len(header) < 3:
                                    continue
                                try:
                                    identifier, count = int(header[0]), int(header[-1])
                                except ValueError:
                                    continue
                                if count < 3:
                                    continue
                                valid = True
                                for _ in range(count):
                                    point = next(geometry, '').split()
                                    if len(point) < 2 or any(_number(v) is None for v in point[:2]):
                                        valid = False
                                if identifier == building_id and valid:
                                    return height
            else:
                with open(entry['paths'][0], 'rb') as raster:
                    remaining = entry['raster_bytes']
                    while remaining:
                        block = raster.read(min(65536, remaining))
                        if not block or len(block) % 2:
                            break
                        remaining -= len(block)
                        for (height,) in struct.iter_unpack('>h', block):
                            if 0 < height <= 20000:  # GIS_MAX_ALTITUDE; larger samples become invalid.
                                return height
        except (OSError, ValueError):
            continue
    return None


def _projection(path, issue):
    try:
        with _open_text(path) as fh:
            lines = [next(fh, '').split() for _ in range(4)]
        if any(not line for line in lines) or not re.fullmatch(r'[+-]?\d+', lines[1][0]) or len(lines[3]) < 4 or any(_number(v) is None for v in lines[3][:4]):
            raise ValueError('至少需要4行，第二行为整数分区，第四行含4个有限投影数值')
    except (OSError, ValueError) as exc:
        issue('error', 'MAP_PROJECTION_INVALID', f'PLANET 投影布局无效：{exc}', 'ProjectionFilePath', path)


def _output_access(path, issue, field='PathlossDirectory'):
    """Check existing parents without write probes or creating directories."""
    if not path:
        return
    target = Path(path)
    current = target
    while not current.exists() and current.parent != current:
        current = current.parent
    if current.exists() and not current.is_dir():
        issue('error', 'OUTPUT_NOT_DIRECTORY', '输出路径或父路径与现有文件冲突', field, current)
    elif not current.exists() or not os.access(current, os.W_OK | os.X_OK):
        issue('error', 'OUTPUT_NOT_ACCESSIBLE', '输出目录或最近存在的父目录不可写/不可访问', field, current)


def _gain_valid(path, three_dimensional=False):
    """Validate just the numeric shape read by AntennaLoader, using bounded memory."""
    try:
        with _open_text(path) as fh:
            lines = (line.split() for line in fh if line.strip())
            if three_dimensional:
                next(lines, None)  # Loader skips exactly one header.
                for _ in range(64800):
                    values = next(lines, [])
                    if len(values) < 3:
                        return False
                    phi, theta, gain = (_number(v) for v in values[:3])
                    if phi is None or theta is None or gain is None or not -179 <= phi <= 180 or not -90 <= theta <= 90:
                        return False
            else:
                for marker in ('HORIZONTAL', 'VERTICAL'):
                    if not any(values and values[0] == marker for values in lines):
                        return False
                    for _ in range(360):
                        values = next(lines, [])
                        if len(values) < 2 or _number(values[1]) is None:
                            return False
        return True
    except (OSError, ValueError):
        return False


def _resources(context, engineering, indoor, issue):
    params, bin_dir = context['params'], context['bin_dir']
    scene = _path(params.get('SceneSettingsPath') or 'runtimelibrary/scenesettings.xml', bin_dir)
    resources = dict(scene_settings=scene, antenna_settings='', model_files=[])
    resources['dynamic_runtime'] = 'unconfirmed'
    resources['log_config'] = str(Path(bin_dir) / 'log4cpp.conf')
    resources['log_config_exists'] = Path(resources['log_config']).is_file()
    issue('warning', 'RUNTIME_RESOURCES_UNCONFIRMED', '未运行 ShuttleInit；动态链接库、授权和日志初始化尚未确认，不能据此保证程序可启动', 'BIN_DIR', bin_dir)
    if not Path(scene).is_file():
        issue('error', 'SCENE_SETTINGS_MISSING', '场景配置不存在（空值回退 Bin/runtimelibrary/scenesettings.xml）', 'SceneSettingsPath', scene)
    else:
        try:
            _xml_fragments(scene)
        except (OSError, ValueError, ET.ParseError) as exc:
            issue('error', 'SCENE_SETTINGS_INVALID', f'场景配置 XML 无法解析：{exc}', 'SceneSettingsPath', scene)
    # The indoor chain constructs its own physical model; its CSV model label is
    # required by AP parsing but does not request a Bin/models propagation model.
    if not indoor:
        available = {('LiShuttleAuto', 0), ('LiShuttleSceneModel', 0), ('LiShuttleCellModel', 0)}
        model_dir = Path(bin_dir) / 'models'
        required_numbers = ('K0', 'Knear', 'Kfar', 'K0_nlos', 'Knear_nlos', 'Kfar_nlos')
        for path in sorted(model_dir.glob('*.xml')):
            try:
                doc = _xml_fragments(path)
                resources['model_files'].append(str(path))
                for category in doc.findall('PropagationCategory'):
                    name = category.get('name', '')
                    if name != 'LiShuttleModel':
                        continue  # This reviewed subsystem registers this creator only.
                    for model in category.findall('Model'):
                        try:
                            identifier = int(model.get('ID', ''))
                        except ValueError:
                            continue
                        if all(_number(model.findtext(tag)) is not None for tag in required_numbers):
                            available.add((name, identifier))
            except (OSError, ValueError, ET.ParseError) as exc:
                issue('warning', 'MODEL_FILE_INVALID', f'模型文件无法解析：{exc}', 'EngineeringFilePath', path)
        for reference in engineering['models']:
            category, sep, identifier_text = reference.rpartition('_')
            if not sep:
                category, identifier = reference, 0
            else:
                match = re.match(r'[+-]?\d+', identifier_text)
                identifier = int(match[0]) if match else 0  # upl_atoi semantics.
            if (category, identifier) not in available:
                issue('error', 'MODEL_REFERENCE_MISSING', f'工参传播模型 {reference} 在 Bin/models 中没有可加载定义', 'EngineeringFilePath', model_dir)
    antennas = engineering['antennas'] + (engineering['sensing_antennas'] if context['func'] == 'commsensing' else [])
    if antennas and (not indoor or _bool(params, 'AntGainCalced')):
        ant_file = str(Path(bin_dir) / 'antennas/antenna.xml')
        resources['antenna_settings'] = ant_file
        try:
            document = _xml_fragments(ant_file)
            entities = {node.get('name', ''): node for settings in document.findall('AntennaSettings') for node in settings.findall('AntennaEntity')}
            checked = {}
            for antenna in antennas:
                name, tilt = antenna['name'], antenna['tilt']
                entity = entities.get(name)
                exact_tilt = None
                if entity is None:
                    # A pre-suffixed name can directly reference a loaded beam.
                    base, sep, suffix = name.rpartition('_')
                    if sep and re.fullmatch(r'[+-]?\d+', suffix) and base in entities:
                        entity, exact_tilt = entities[base], int(suffix)
                if entity is None:
                    issue('error', 'ANTENNA_REFERENCE_MISSING', f'工参天线 {name} 在 Bin/antennas/antenna.xml 中不存在', 'EngineeringFilePath', ant_file)
                    continue
                if _number(entity.findtext('MaxGain')) is None:
                    issue('error', 'ANTENNA_GAIN_INVALID', f'天线 {name} 缺少有效 MaxGain', 'EngineeringFilePath', ant_file)
                    continue
                candidates = []
                for beam in entity.findall('Broadcast_Beam_FILE'):
                    try:
                        beam_tilt = int(beam.get('electilt', '0'))
                    except ValueError:
                        beam_tilt = 0
                    beam_path = _path((beam.text or '').lstrip(' \t'), Path(ant_file).parent)
                    three_dimensional = (entity.findtext('GainMode') or '').lower() == '3d'
                    key = (beam_path, three_dimensional)
                    if key not in checked:
                        checked[key] = bool(beam_path) and _gain_valid(beam_path, three_dimensional)
                    if checked[key]:
                        candidates.append((beam_tilt, beam_path))
                if exact_tilt is not None:
                    candidates = [item for item in candidates if item[0] == exact_tilt and exact_tilt != 0]
                    if not candidates:
                        issue('error', 'ANTENNA_REFERENCE_MISSING', f'工参天线 {name} 没有同名已加载波束；带后缀名称不使用邻近倾角替代', 'EngineeringFilePath', ant_file)
                        continue
                elif any(item[0] != 0 for item in candidates):
                    candidates = [item for item in candidates if item[0] != 0]
                if not candidates:
                    issue('error', 'ANTENNA_GAIN_INVALID', f'天线 {name} 没有可加载的增益文件（2D 需双360行；3D 需64800点）', 'EngineeringFilePath', ant_file)
                else:
                    selected = min(candidates, key=lambda item: abs(item[0] - tilt))
                    resources.setdefault('antenna_gains', []).append(dict(name=name, tilt=selected[0], path=selected[1]))
        except (OSError, ValueError, ET.ParseError) as exc:
            issue('error', 'ANTENNA_SETTINGS_INVALID', f'天线配置无法读取：{exc}', 'EngineeringFilePath', ant_file)
    context['resources'] = resources


def _conditional_inputs(context, issue):
    params, bin_dir, func = context['params'], context['bin_dir'], context['func']
    if func in ('pred', 'commsensing') and params.get('PredictedCells'):
        path = _path(params['PredictedCells'], bin_dir)
        try:
            with open(path, 'rb') as stream:
                if not stream.read(1):
                    raise ValueError('文件为空')
            context['resources']['predicted_cells'] = path
        except (OSError, ValueError) as exc:
            issue('error', 'PREDICTED_CELLS_REQUIRED', f'已指定预测小区列表，但文件不可用：{exc}；引擎否则可能回退到全部小区', 'PredictedCells', path)
    if func in ('pred', 'commsensing', 'cali', 'pl', 'acp') and _bool(params, 'CorrectByDT', False):
        folder = context.get('dt_dir')
        path = str(Path(folder) / 'meas.anchor') if folder else ''
        try:
            with open(path, 'rb') as stream:
                if not stream.read(1):
                    raise ValueError('文件为空')
            context['resources']['dt_anchor'] = path
            issue('warning', 'DT_ANCHOR_FORMAT_UNCONFIRMED', '路测修正锚点存在；其二进制缓存版本与适用范围仍由引擎确认，不要求原始 DT 索引代替锚点', 'CorrectByDT', path)
        except (OSError, ValueError) as exc:
            issue('error', 'DT_ANCHOR_REQUIRED', f'CorrectByDT 已启用，需要路测目录中的非空 meas.anchor：{exc}', 'DriverTestFileDictionaryPath', path or context['schema_path'])


def _map_directory(folder):
    """Use the filename alternatives and priority in PlanetMapInfo."""
    def choose(base, names, directory=False):
        for name in names:
            path = Path(base) / name
            if path.is_dir() if directory else path.is_file():
                return str(path)
        return str(Path(base) / names[0])

    heights = choose(folder, ('heights', 'Heights', 'height', 'Height'), True)
    clutter = choose(folder, ('clutter', 'Clutter', 'clutters', 'Clutters'), True)
    buildings = choose(folder, ('buildings', 'Buildings', 'building', 'Building'), True)
    vectors = choose(folder, ('buildvector', 'buildingvector', 'buildVector', 'buildingVector', 'Buildvector', 'Buildingvector', 'BuildVector', 'BuildingVector'), True)
    indexes = ('index', 'index.txt', 'Index', 'Index.txt')
    return dict(ProjectionFilePath=choose(heights, ('projection', 'projection.txt', 'Projection', 'Projection.txt')),
        HeightIndexPath=choose(heights, indexes), ClutterIndexPath=choose(clutter, indexes),
        ClutterMenuPath=choose(clutter, ('menu', 'menu.txt', 'Menu', 'Menu.txt')),
        BuildingIndexPath=choose(buildings, indexes), BulidVectorIndexPath=choose(vectors, indexes))


def _floor_caches(out_dir, mode, issue):
    """Inspect actual engine floor cache headers, without asserting C++ hash parity.

    The internal hash also depends on converted antennas, model serialization and
    geometry digests. A matching step/header alone cannot establish compatibility.
    """
    details = []
    if not out_dir or not Path(out_dir).is_dir():
        return details
    for path in Path(out_dir).rglob('*.loss3d.csv'):
        try:
            with path.open('rb') as fh:
                head = fh.read(1024)
            step, version = None, None
            if head.startswith(b'PATHLOSS3D') and len(head) >= 66:
                version, decimeters = struct.unpack_from('<II', head, 10)
                step = decimeters / 10
                file_format = 'PATHLOSS3D'
            elif head.startswith(b'version:'):
                fields = next(csv.reader([head.splitlines()[0].decode('ascii')]))
                version = int(fields[0].split(':')[1])
                step = _number(fields[2])
                file_format = 'floor_csv'
            else:
                file_format = 'unknown'
            details.append(dict(path=str(path), format=file_format, version=version, floor_height=step, compatibility='unconfirmed'))
            if version != 1 or step is None:
                issue('warning', 'CACHE_FORMAT_UNCONFIRMED', '楼层缓存格式/版本无法确认，不能用来证明当前楼层输入可用', 'SpatialCalcMode', path)
            elif mode['floor_height'] is not None and not math.isclose(step, mode['floor_height'], rel_tol=0, abs_tol=1e-6):
                issue('warning', 'CACHE_LAYER_MISMATCH', f'旧楼层缓存步长 {step} 与当前 {mode["floor_height"]} 不同；未删除或重算缓存', 'DefaultFloorHeight', path)
            else:
                issue('warning', 'CACHE_COMPATIBILITY_UNCONFIRMED', '旧楼层缓存步长相同，但尚不能核对模型、天线及地图摘要；不能据此跳过建筑输入检查', 'SpatialCalcMode', path)
        except (OSError, ValueError, IndexError, UnicodeError, csv.Error, struct.error) as exc:
            issue('warning', 'CACHE_FORMAT_UNCONFIRMED', f'楼层缓存无法读取：{exc}', 'SpatialCalcMode', path)
    return details


def _indoor(map_dir, engineering, issue):
    floors = []
    paths = indoor_map_entries(map_dir)
    engine_paths = set(engine_indoor_map_entries(map_dir))
    if not paths:
        issue('error', 'INDOOR_MAP_MISSING',
              '室内地图目录没有 .das 楼层文件（扩展名不区分大小写）',
              'MapPath', map_dir)
    for path in sorted(engine_paths - set(paths)):
        issue('error', 'INDOOR_MAP_UNEXPECTED_ENTRY',
              '当前引擎还会尝试读取这个非 .das 条目；请移出场景目录，或确认是地图后改为 .das 扩展名再检查',
              'MapPath', str(path))
    for path in paths:
        if path not in engine_paths:
            issue('error', 'INDOOR_MAP_FILENAME_UNSUPPORTED',
                  '已识别为室内 DAS 地图，但当前引擎会跳过该名称；请使用小写 .das 扩展名，且文件名超过 5 字节（如 floor1.das）',
                  'MapPath', str(path))
        try:
            lines = _text(path).splitlines()
            floor = int(lines[0].split()[1])
            altitude = _number(lines[1].split()[1])
            counts = [int(c) for c in lines[2].split()[:4]]
            if not -100 <= floor <= 1000 or altitude is None or not -500 <= altitude <= 3000 or len(counts) != 4 or min(counts) < 0:
                raise ValueError('楼层、高程或墙体数量无效')
            if len(lines) < 3 + sum(counts):
                raise ValueError('墙体/窗/柱数据被截断')
            if sum(counts) == 0:
                raise ValueError('楼层没有可用墙体或柱')
            for line in lines[3:3 + counts[0]]:
                fields = line.split()
                if len(fields) < 14 or any(_number(v) is None for v in fields[:14]):
                    raise ValueError('墙体坐标或材料无效')
            if floor in floors:
                raise ValueError(f'重复楼层 ID {floor}')
            floors.append(floor)
        except (OSError, ValueError, IndexError) as exc:
            issue('error', 'INDOOR_MAP_INVALID', f'室内 DAS 地图无效：{exc}', 'MapPath', str(path))
    for floor in engineering['floors']:
        if floor not in floors:
            issue('error', 'AP_FLOOR_MISSING', f'AP 工参楼层 {floor} 在 DAS 地图中不存在', 'EngineeringFilePath', engineering['path'])
    return sorted(floors)


def _regions(path, issue):
    if not path:
        issue('warning', 'REGION_MAP_FALLBACK', '未指定多边形，引擎使用地图范围', 'PolygonFilePath', '')
        return []
    if not Path(path).is_file():
        issue('error', 'REGION_MISSING', '指定的区域文件不存在', 'PolygonFilePath', path)
        return []
    try:
        text = _text(path)
        if Path(path).suffix.lower() == '.kml':
            root = ET.fromstring(text)
            coordinates = [''.join(node.itertext()) for node in root.iter() if node.tag.rsplit('}', 1)[-1] == 'coordinates']
        else:
            coordinates = [text]
        regions = []
        for coordinates_text in coordinates:
            points = []
            for line in coordinates_text.splitlines():
                # TXT accepts lon,lat lines; KML accepts space-delimited triples.
                chunks = line.split() if Path(path).suffix.lower() == '.kml' else [line]
                for chunk in chunks:
                    fields = re.split(r'[,;\s]+', chunk.strip())
                    if len(fields) >= 2:
                        lon, lat = _number(fields[0]), _number(fields[1])
                        if lon is not None and lat is not None and -180 <= lon <= 180 and -90 <= lat <= 90:
                            points.append([lon, lat])
            if len({tuple(p) for p in points}) >= 3:
                regions.append(dict(id=len(regions), source=path, points=points))
        if not regions:
            issue('warning', 'REGION_MAP_FALLBACK', '区域文件没有有效多边形，引擎将回退到地图范围', 'PolygonFilePath', path)
        return regions
    except (OSError, ValueError, ET.ParseError) as exc:
        issue('error', 'REGION_INVALID', f'区域文件无法读取：{exc}', 'PolygonFilePath', path)
        return []


def _dt(folder, cell_ids, issue):
    index = Path(folder) / 'index.txt' if folder else None
    if not index or not index.is_file():
        issue('error', 'DT_INDEX_REQUIRED', '路测目录需要 index.txt 列出输入文件；不会将目录内任意 CSV 当作路测', 'DriverTestFileDictionaryPath', str(index or ''))
        return []
    files, usable = [], 0
    try:
        names = [line.rstrip('\r\n') for line in _text(index).splitlines() if line]
        for name in names:
            path = _path(name, folder)
            files.append(path)
            if not Path(path).is_file():
                issue('error', 'DT_REFERENCE_MISSING', '路测 index.txt 引用文件不存在', 'DriverTestFileDictionaryPath', path)
                continue
            rows = list(csv.reader(io.StringIO(_text(path)), strict=True))
            if not rows or len(rows[0]) < 5 or [normalized(c) for c in rows[0][:5]] != ['pctime', 'cellid', 'lon', 'lat', 'rsrp']:
                issue('warning', 'DT_HEADER', '路测表头非标准名称；引擎跳过首行并按前5列读取时间、小区ID、经度、纬度、RSRP', 'DriverTestFileDictionaryPath', path)
            for row in rows[1:]:
                if len(row) < 5:
                    continue
                lon, lat, rsrp = (_number(row[i]) for i in (2, 3, 4))
                if row[1] in cell_ids and lon is not None and lat is not None and rsrp is not None and -180 <= lon <= 180 and -90 <= lat <= 90:
                    usable += 1
        if not usable:
            issue('error', 'DT_NO_USABLE_ROWS', '路测索引中没有坐标/RSRP 有效且匹配工参 Cell ID 的数据行', 'DriverTestFileDictionaryPath', str(index))
    except (OSError, ValueError, csv.Error) as exc:
        issue('error', 'DT_INVALID', f'路测输入无法读取：{exc}', 'DriverTestFileDictionaryPath', str(index))
    return files


def _calibration(params, issue):
    for low, high in (('MinPower', 'MaxPower'), ('MinK0', 'MaxK0'), ('MinKnear', 'MaxKnear'), ('MinDiff', 'MaxDiff'), ('MinRef', 'MaxRef')):
        lower, upper = _number(params.get(low)), _number(params.get(high))
        if lower is None or upper is None or lower > upper:
            issue('error', 'CALIBRATION_RANGE', f'{low}/{high} 必须是有限数值且最小值不大于最大值', low, '')
    if any(tag in params for tag in ('MinDeltaKfar', 'MaxDeltaKfar')):
        lower, upper = _number(params.get('MinDeltaKfar', '0')), _number(params.get('MaxDeltaKfar', '30'))
        if lower is None or upper is None or lower > upper:
            issue('error', 'CALIBRATION_RANGE', 'MinDeltaKfar/MaxDeltaKfar 范围无效', 'MinDeltaKfar', '')
    for tag in ('MinSamples', 'Epoch'):
        if tag in params:
            value = _number(params[tag])
            if value is None or value <= 0 or value != int(value):
                issue('error', 'CALIBRATION_PARAMETER', f'{tag} 必须为正整数', tag, '')
    if not params.get('CalNewModelName'):
        issue('error', 'CALIBRATION_MODEL_NAME', '缺少校正模型名 CalNewModelName', 'CalNewModelName', '')
    if not (_bool(params, 'IsLosCalibrated') or _bool(params, 'IsNLosCalibrated')):
        issue('warning', 'CALIBRATION_DISABLED', 'LOS 与 NLOS 校正均关闭，可能没有模型更新', 'IsLosCalibrated', '')


def check_run(env, schema_path, func, task_id):
    """Return a JSON-safe report; never write or launch any process."""
    issues = []

    def issue(severity, code, message, field='', path=''):
        issues.append(dict(severity=severity, code=code, message=message, field=field, path=str(path or '')))

    project = _path(env.get('PROJECT_DIR', ''), os.getcwd())
    bin_dir = _path(env.get('BIN_DIR') or env.get('EXE_DIR') or os.path.join(env.get('BUILD_SUBDIR', ''), 'Bin'), project or os.getcwd())
    exe = _path(env.get('EXE_NAME', 'lishuttle.exe'), bin_dir)
    schema_path = _path(schema_path, bin_dir)
    context = dict(project=project, bin_dir=bin_dir, exe=exe, schema_path=schema_path,
        schema_name='', schema_digest='', schema_text='', func=str(func), task_id=str(task_id), task_name='',
        out_dir='', pred_dir='', dt_dir='', models_dir='', params={}, mode=dict(requested=None,
        parsed='', effective='', applies=False, max_height=None, floor_height=None, layer_count=None),
        regions=[], indoor_floors=[])
    if not project or not Path(project).is_dir():
        issue('error', 'PROJECT_MISSING', '项目目录不存在', 'PROJECT_DIR', project)
    if not Path(exe).is_file():
        issue('error', 'EXE_MISSING', '程序文件不存在，请先编译和装配', 'EXE_NAME', exe)
    if os.path.normcase(os.path.realpath(Path(exe).parent)) != os.path.normcase(os.path.realpath(bin_dir)):
        issue('error', 'EXE_LOCATION_MISMATCH', '程序必须位于当前 Bin；引擎按实际程序目录读取运行 XML 和资源，请修正 EXE_NAME/BUILD_SUBDIR', 'EXE_NAME', exe)
    try:
        raw = Path(schema_path).read_bytes()
        context['schema_digest'] = hashlib.sha256(raw).hexdigest()
        context['schema_text'] = raw.decode('utf-8-sig')
        root = ET.fromstring(raw)
        if root.tag != 'RuntimeSchema':
            raise ValueError('根节点不是 RuntimeSchema')
    except (OSError, ValueError, UnicodeError, ET.ParseError) as exc:
        issue('error', 'SCHEMA_INVALID', f'运行配置无法读取：{exc}', 'schema_path', schema_path)
        return dict(ok=False, issues=issues, context=context)
    params = {}
    for node in root:
        if node.tag in params:
            same = not list(node) and (node.text or '') == params[node.tag]
            issue('warning' if same else 'error', 'SCHEMA_DUPLICATE_FIELD', f'重复字段 {node.tag}；引擎读取首项' + ('，值相同' if same else '，值不同需先消除歧义'), node.tag, schema_path)
        elif not list(node):
            params[node.tag] = node.text or ''
    context['params'] = params
    name = root.get('name', '')
    context.update(schema_name=Path(schema_path).name, task_name=name)
    if not name or next(iter(root.attrib), '') != 'name':
        issue('error', 'SCHEMA_NAME', '引擎按根节点首属性读取任务名；name 必须存在且为首属性', 'RuntimeSchema@name', schema_path)
    for value, field in ((name, 'RuntimeSchema@name'), (str(task_id), 'task_id')):
        if not value or value in ('.', '..') or any(c in value for c in '/\\\0<>:"|?*'):
            issue('error', 'INVALID_TASK_NAME', '任务名/编号不能为空或包含 Windows 非法路径字符', field, schema_path)
    output = _path(params.get('PathlossDirectory'), bin_dir)
    if output and name:
        context['out_dir'] = _path(name, output)
        context['pred_dir'] = _path('pred/' + str(task_id), context['out_dir'])
        context['models_dir'] = _path('models_task' + str(task_id), context['out_dir']) if _bool(params, 'ModelTemporaryStorage') else _path('models', bin_dir)
        _output_access(context['out_dir'], issue)
        if not Path(output).exists() and not Path(output).parent.is_dir():
            issue('error', 'OUTPUT_PARENT_MISSING', '引擎只创建 PathlossDirectory 及任务目录；PathlossDirectory 的父目录必须已存在', 'PathlossDirectory', Path(output).parent)
    else:
        issue('error', 'OUTPUT_REQUIRED', '缺少 PathlossDirectory 或任务名', 'PathlossDirectory', schema_path)
    context['dt_dir'] = _path(params.get('DriverTestFileDictionaryPath'), bin_dir)
    indoor_family = func in ('predindoor', 'plindoor', 'indoorrays')
    reviewed = func in ('pred', 'commsensing', 'predindoor', 'cali', 'acp')
    context['function_contract'] = 'reviewed' if reviewed else 'unconfirmed'
    if not reviewed:
        issue('warning', 'FUNCTION_UNREVIEWED', '该功能的完整输入与结果契约尚未审查，预检通过不能自动判为业务成功', 'func', '')
        if not indoor_family:
            return dict(ok=not any(i['severity'] == 'error' for i in issues), issues=issues, context=context)
    applies = func in ('pred', 'commsensing', 'acp')
    requested = params.get('SpatialCalcMode')
    parsed = (requested if requested is not None else 'ground').lower()
    effective = 'floor' if parsed == 'building' else parsed if parsed in ('ground', 'floor', '3d') else 'ground'
    mode = context['mode']
    mode.update(requested=requested, parsed=parsed, effective=effective if applies else 'indoor' if indoor_family else 'ground', applies=applies,
        max_height=_number(params.get('MaxCalcHeight', '0')), configured_max_height=_number(params.get('MaxCalcHeight', '0')),
        floor_height=_number(params.get('DefaultFloorHeight', '3')))
    if applies and parsed not in ('ground', 'floor', 'building', '3d'):
        issue('error', 'INVALID_SPATIAL_MODE', 'SpatialCalcMode 只接受 ground、floor/building、3d；引擎不会去除首尾空格', 'SpatialCalcMode', schema_path)
    if not applies and (indoor_family or func == 'cali'):
        issue('warning', 'SPATIAL_MODE_IGNORED', '室内预测使用 DAS 楼层；校正使用地面实测射线，室外空间模式不决定其层数', 'SpatialCalcMode', schema_path)
    if mode['effective'] == 'ground':
        mode.update(max_height=0, layer_count=1, heights=[0])
    if applies and effective in ('3d', 'floor'):
        height, step = mode['max_height'], mode['floor_height']
        if height is None or height < 0 or step is None or step <= 0 or not math.isfinite(height / step) or height / step >= 2 ** 32:
            issue('error', 'INVALID_LAYER_GEOMETRY', '分层计算要求 MaxCalcHeight>=0 且 DefaultFloorHeight>0，二者须为有限数值', 'MaxCalcHeight', schema_path)
        elif effective == '3d':
            mode['layer_count'] = math.floor(height / step) + 1
            mode['configured_layer_count'] = mode['layer_count']
            # Avoid allocating an enormous array merely to describe a bad request.
            mode['heights'] = [i * step for i in range(mode['layer_count'])] if mode['layer_count'] <= 10000 else []
    expected = 'indoor' if indoor_family else 'outdoor'
    resolution = _number(params.get('DefaultCalcResolution', '5'))
    if resolution is None or resolution <= 0:
        issue('error', 'INVALID_RESOLUTION', 'DefaultCalcResolution 必须为有限正数', 'DefaultCalcResolution', schema_path)
    engineering = _engineering(_path(params.get('EngineeringFilePath'), bin_dir), expected, issue, bin_dir)
    context['engineering'] = engineering
    _resources(context, engineering, expected == 'indoor', issue)
    _conditional_inputs(context, issue)
    actual_map = params.get('MapFormat', 'PLANET').lower()
    if actual_map not in ('planet', 'plannet', 'indoor'):
        issue('error', 'MAP_FORMAT_UNSUPPORTED', '地图格式须为 PLANET/PLANNET 或 indoor；引擎不去除空格', 'MapFormat', schema_path)
    if (actual_map == 'indoor') != (expected == 'indoor'):
        issue('error', 'MAP_KIND', f'{func} 与 MapFormat={params.get("MapFormat", "PLANET")} 不匹配', 'MapFormat', schema_path)
    if expected == 'indoor':
        floors = _indoor(_path(params.get('MapPath'), bin_dir), engineering, issue)
        context['indoor_floors'] = floors
        mode['layer_count'] = len(floors)
    else:
        defaults = dict(ProjectionFilePath='heights/projection.txt', HeightIndexPath='heights/index.txt', ClutterIndexPath='clutter/index.txt', ClutterMenuPath='clutter/menu.txt', BuildingIndexPath='buildings/index.txt', BulidVectorIndexPath='buildvector/index.txt')
        maps = _map_directory(_path(params['MapPath'], bin_dir)) if params.get('MapPath') else {tag: _path(params.get(tag), bin_dir) for tag in defaults}
        if 'MapPath' in params and not params['MapPath']:
            issue('error', 'MAP_DIRECTORY_EMPTY', 'MapPath 元素存在但为空；引擎不会回退到逐项地图路径', 'MapPath', schema_path)
        projection = maps['ProjectionFilePath']
        if not projection or not Path(projection).is_file() or Path(projection).stat().st_size == 0:
            issue('error', 'MAP_PROJECTION_MISSING', '地图投影文件不存在或为空', 'ProjectionFilePath', projection)
        else:
            _projection(projection, issue)
        for tag in ('HeightIndexPath', 'ClutterIndexPath'):
            _index(maps[tag], tag, issue)
        context['map_paths'] = maps
        if not maps['ClutterMenuPath'] or not Path(maps['ClutterMenuPath']).is_file():
            issue('error', 'MAP_MENU_MISSING', 'PLANET 地图需要杂波菜单文件（MapPath 分支从杂波目录寻找 menu/menu.txt）', 'ClutterMenuPath', maps['ClutterMenuPath'])
        vector = _bool(params, 'UsingBuildingPolygon')
        building_tag = 'BulidVectorIndexPath' if vector else 'BuildingIndexPath'
        building_path = maps[building_tag]
        building_entries = []
        if not vector or (building_path and Path(building_path).is_file()):
            building_entries = _index(building_path, building_tag, issue, vector=vector)
        if applies and effective != 'ground':
            context['floor_caches'] = _floor_caches(context['out_dir'], mode, issue)
        if applies and effective == 'floor':
            if mode['max_height'] is not None and mode['max_height'] >= 0 and mode['floor_height'] is not None and mode['floor_height'] > 0 and math.isfinite(mode['max_height'] / mode['floor_height']) and mode['max_height'] / mode['floor_height'] < 2 ** 32:
                mode['layer_cap'] = math.floor(mode['max_height'] / mode['floor_height']) + 1
                mode['configured_layer_count'] = mode['layer_cap']
            tag = building_tag
            height = _building_height(building_entries, vector)
            mode['building_source'] = tag
            if height is None:
                issue('error', 'FLOOR_DATA_REQUIRED', f'floor/building 模式缺少 UsingBuildingPolygon 所选 {tag} 中可用建筑；未使用另一路或旧高层目录替代', tag, maps[tag])
            elif mode['floor_height'] and mode['floor_height'] > 0 and mode['max_height'] is not None and mode['max_height'] >= 0:
                mode['building_sample_height'] = height
                # GeoBuildingPolygon computes Floors from each scene's FloorHeight.
                # Global default step supplies only the prediction cap and labels.
                mode['layer_count'] = None
        if func in ('pred', 'commsensing', 'acp'):
            if 'PolygonFilePath' not in params:
                issue('error', 'REGION_ELEMENT_REQUIRED', '预测解析器要求存在 PolygonFilePath 元素；允许显式空值使用地图范围', 'PolygonFilePath', schema_path)
            else:
                context['regions'] = _regions(_path(params.get('PolygonFilePath'), bin_dir), issue)
    if func == 'cali':
        _calibration(params, issue)
        context['dt_files'] = _dt(context['dt_dir'], engineering['ids'], issue)
        _output_access(context['dt_dir'], issue, 'DriverTestFileDictionaryPath')
        _output_access(context['models_dir'], issue, 'ModelTemporaryStorage')
    return dict(ok=not any(i['severity'] == 'error' for i in issues), issues=issues, context=context)
