"""Identify engineering CSVs by header structure, never by traversal order."""
import csv
import os
import re
import xml.etree.ElementTree as ET


def normalized(value):
    return re.sub(r'[\s_()（）°\-]', '', value.lstrip('\ufeff').lower())


def engineering_kind(path):
    """Read at most two header rows; measurements with only cellID/coordinates fail."""
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            with open(path, encoding=encoding, newline='') as fh:
                rows = []
                reader = csv.reader(fh)
                for _ in range(2):
                    rows.append(next(reader, []))
        except UnicodeError:
            continue
        except (OSError, csv.Error):
            return ''
        for row in rows:
            fields = {normalized(c) for c in row}
            def has(*names):
                return bool(fields.intersection(normalized(n) for n in names))
            antenna = has('Antenna', 'Antenna Model', '天线', '天线型号')
            power = has('Max Power (dBm)', 'Power', 'Tx Power', '发射功率', '最大发射功率', '功率')
            if not (antenna and power):
                continue
            if (has('AP ID', 'AP编号') and has('x', 'X(m)', 'X坐标')
                    and has('y', 'Y(m)', 'Y坐标') and has('Floor', '楼层')):
                return 'indoor'
            if (has('Cell ID', '小区ID') and has('Longitude', '经度')
                    and has('Latitude', '纬度') and has('Height (m)', 'Antenna Height', '天线高度', '天线高度(m)')
                    and has('Azimuth (°)', 'Azimuth', '方位角', '天线方位角')):
                return 'outdoor'
    return ''


def path_key(path):
    return os.path.normcase(os.path.realpath(path))


def identify_engineering(task):
    kinds = {p: engineering_kind(p) for p in sorted(task.get('csvs', []))}
    candidates = [p for p, kind in kinds.items() if kind]
    references = set()
    for xml in sorted(task.get('xmls', [])):
        try:
            root = ET.parse(xml).getroot()
        except (OSError, ET.ParseError, ValueError):
            continue
        for elem in root.iter('EngineeringFilePath'):
            ref = (elem.text or '').strip().replace('\\', '/')
            if not ref:
                continue
            exact = [p for p in candidates
                     if path_key(p) == path_key(os.path.join(os.path.dirname(xml), ref))]
            matches = exact or [p for p in candidates
                                if os.path.basename(p).lower() == ref.rsplit('/', 1)[-1].lower()]
            references.update(matches)
    selected = ''
    if len(references) == 1:
        selected = next(iter(references))
        reason = '任务 XML 引用，工参表头校验通过'
    elif len(candidates) == 1:
        selected = candidates[0]
        reason = '唯一工参候选，表头校验通过'
    elif candidates:
        reason = '存在多个工参候选，请手动选择'
    else:
        reason = '未发现表头符合要求的工参 CSV'
    task.update(engineering_candidates=candidates, engineering_file=selected,
                engineering_reason=reason, engineering_kinds={p: kinds[p] for p in candidates})
    task['kind'] = kinds.get(selected) or 'unknown'
    task['detect'] = reason
    return task


def validate_engineering(task, selected=None):
    selected = task.get('engineering_file', '') if selected is None else selected
    if not selected:
        raise ValueError(task.get('engineering_reason', '请选择工参 CSV'))
    matches = [p for p in task.get('engineering_candidates', []) if path_key(p) == path_key(selected)]
    if len(matches) != 1 or not engineering_kind(matches[0]):
        raise ValueError('所选文件不是当前任务中有效的工参 CSV，请重新扫描并选择')
    return matches[0]
