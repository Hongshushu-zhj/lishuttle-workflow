"""Shared CellLoader layout and conservative CSV header recognition."""
import hashlib
from pathlib import Path
import re
import xml.etree.ElementTree as ET


DEFAULT_COLUMNS = dict(CellId=0, PCI=7, BandWidth=17, ChannelNumber=18, MaxPower=15,
    EPRE=16, SensePower=16, PropagationModel=19, CalcRadius=23, SiteId=2, Longitude=4,
    Latitude=5, TxNumber=13, RxNumber=14, Antenna=12, SenseAntenna=12,
    AntennaHeight=8, Azimuth=9, Tilt=10, ElecTilt=11, SenseTilt=11,
    CellType=34, CityCode=-1)
INDOOR_COLUMNS = dict(ApId=0, CellId=2, Floor=3, x=4, y=5, AntennaHeight=6,
    Azimuth=7, Tilt=8, ElecTilt=9, Antenna=10, TxNumber=11, RxNumber=12,
    MaxPower=13, EPRE=14, ChannelNumber=16, PropagationModel=17,
    ULTrafficLoad=20, CalcRadius=21, CellType=31)
ALIASES = {
    'CellId': ('Cell ID', 'CellId', 'ID', '小区ID', '小区'),
    'SiteId': ('Site ID', '基站ID'),
    'CalcRadius': ('CalcRadius', 'Calc Radius (m)', 'Main Calculation Radius (m)',
                   'Calculation Radius (m)', '计算半径', '计算半径(m)', '计算半径(米)',
                   '小区计算半径', '小区计算半径(m)', '小区计算半径(米)', '半径'),
    'Antenna': ('Antenna', 'Antenna Model', '天线', '天线型号'),
    'Longitude': ('Longitude', '经度'), 'Latitude': ('Latitude', '纬度'),
    'MaxPower': ('Max Power (dBm)', 'Power', 'Tx Power', '发射功率', '最大发射功率', '功率'),
    'AntennaHeight': ('Height (m)', 'Antenna Height', '天线高度', '天线高度(m)'),
    'Azimuth': ('Azimuth (°)', 'Azimuth', '方位角', '天线方位角'),
    'Tilt': ('Mechanical Downtilt (°)', '机械下倾角'),
    'ElecTilt': ('Additional Electrical Downtilt (°)', '电下倾角', '电子下倾角'),
    'EPRE': ('EPRE per antenna port', 'EPRE', '参考信号功率'),
    'ChannelNumber': ('Channel Number', '频点'),
    'PropagationModel': ('Main Propagation Model', '预测模型'),
    'TxNumber': ('Number of Transmission Antennas', '天线发射端口数量'),
    'RxNumber': ('Number of Reception Antennas', '天线接收端口数量'),
    'CellType': ('Cell Type', '小区类型'),
    'ApId': ('AP ID', 'AP编号'), 'Floor': ('Floor', '楼层'),
    'x': ('x', 'X(m)', 'x坐标'), 'y': ('y', 'Y(m)', 'y坐标'),
}


def normalized(value):
    return re.sub(r'[\s_()（）°\-]', '', value.lstrip('\ufeff').lower())


def recognized_columns(row):
    result = {}
    for index, label in enumerate(row):
        for tag, aliases in ALIASES.items():
            if normalized(label) in {normalized(alias) for alias in aliases}:
                result.setdefault(tag, index)
    return result


def _header_row(row):
    # A cell/antenna name can itself be "Antenna" or "CellId". One matching
    # value is not enough evidence to remove an entire CSV record as a header.
    return len(set(recognized_columns(row).values())) >= 2


def header_line_count(rows, limit=2):
    """Count only consecutive, recognizable header records, never data rows."""
    count = 0
    for row in rows[:limit]:
        if not _header_row(row):
            break
        count += 1
    return count


def _decode_format(raw):
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return raw.decode(encoding)
        except UnicodeError:
            pass
    raise ValueError('文件不是 UTF-8 或 GB18030 文本')


def cell_layout(bin_dir):
    path = Path(bin_dir) / 'cellformat.xml'
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return dict(columns=DEFAULT_COLUMNS.copy(), header_lines=2, source='CellLoader.h defaults',
                    revision='missing', explicit=False, error='cellformat.xml 不存在')
    except OSError as exc:
        return dict(columns=DEFAULT_COLUMNS.copy(), header_lines=2, source='CellLoader.h defaults',
                    revision='unreadable', explicit=False, error=f'cellformat.xml 无法读取：{exc}')
    revision = hashlib.sha256(raw).hexdigest()
    try:
        text = _decode_format(raw)
        text = re.sub(r'<\?xml\b.*?\?>', '', text, flags=re.S)
        document = ET.fromstring('<Document>' + text + '</Document>')
        columns, headers = DEFAULT_COLUMNS.copy(), 2
        parsed = {}
        for root in document.findall('TableFormat'):
            for node in root:
                value = (node.text or '').strip()
                if node.tag == 'HeaderLines':
                    headers = int(value)
                    if headers < 0:
                        raise ValueError('HeaderLines 必须非负')
                elif re.fullmatch('[A-Za-z]+', value):
                    index = 0
                    for char in value.upper():
                        index = index * 26 + ord(char) - 64
                    parsed.setdefault(node.tag, index - 1)
        if not document.findall('TableFormat'):
            raise ValueError('没有 TableFormat')
        columns.update(parsed)
        for target, fallback in (('SensePower', 'EPRE'), ('SenseAntenna', 'Antenna'), ('SenseTilt', 'ElecTilt')):
            if target not in parsed:
                columns[target] = columns[fallback]
        return dict(columns=columns, header_lines=headers, source=str(path),
                    revision=revision, explicit=True, error='')
    except (UnicodeError, ET.ParseError, ValueError) as exc:
        return dict(columns=DEFAULT_COLUMNS.copy(), header_lines=2, source='CellLoader.h defaults',
                    revision=revision, explicit=False, error=f'cellformat.xml 无法解析：{exc}')


def grid_layout(rows, bin_dir=None, indoor=False):
    if indoor:
        layout = dict(columns=INDOOR_COLUMNS.copy(), header_lines=2, source='indoor fixed offsets',
                      revision='indoor-fixed', explicit=True, error='')
    elif bin_dir is not None:
        layout = cell_layout(bin_dir)
    else:
        layout = dict(columns={}, header_lines=0, source='recognized headers', revision='missing',
                      explicit=False, error='')
    if not layout['explicit'] and layout['revision'] == 'missing':
        headers = header_line_count(rows)
        layout['header_lines'] = headers
        layout['columns'] = {}
        for row in rows[:headers]:
            layout['columns'].update(recognized_columns(row))
        layout['source'] = 'recognized headers' if headers else 'unknown'
        layout['error'] = '' if headers else '无法确认工参表头，文件只读'
    if layout['header_lines'] > len(rows):
        layout['error'] = '表头行数超过文件记录数'
    if layout['header_lines'] > 2:
        layout['error'] = '超过两行表头的编辑暂不支持'
    headers = rows[:layout['header_lines']]
    if any(_header_row(row) for row in headers) and not all(_header_row(row) for row in headers):
        layout['error'] = '配置的表头行数与 CSV 不符，可能把数据行当作表头；文件只读'
    for row in headers:
        for tag, aliases in ALIASES.items():
            labels = {normalized(alias) for alias in aliases}
            if sum(normalized(value) in labels for value in row) > 1:
                layout['error'] = f'{tag} 表头重复，无法确认列位；文件只读'
        for tag, index in recognized_columns(row).items():
            if tag in layout['columns'] and layout['columns'][tag] != index:
                layout['error'] = f'{tag} 表头列位与 cellformat.xml 冲突'
    layout['editable'] = not layout['error']
    return layout
