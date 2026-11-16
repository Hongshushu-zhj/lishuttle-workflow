"""Bounded, cancellable, read-only discovery of local workflow resources."""
from collections import deque
from copy import deepcopy
import csv
import io
import os
from pathlib import Path
import threading
import uuid
import xml.etree.ElementTree as ET

from engineering import normalized

SKIP_NAMES = frozenset({'.git', 'node_modules', '__pycache__', '$recycle.bin',
    'system volume information', 'windows', 'programdata', '.venv'})


def _link(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _csv_kind(path):
    with path.open('rb') as stream:
        raw = stream.read(131072)
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            text = raw.decode(encoding)
            rows = csv.reader(io.StringIO(text))
            for _, row in zip(range(2), rows):
                fields = {normalized(value) for value in row}
                def has(*names):
                    return bool(fields.intersection(normalized(n) for n in names))
                if not (has('Antenna', 'Antenna Model', '天线', '天线型号') and
                        has('Max Power (dBm)', 'Power', 'Tx Power', '发射功率', '最大发射功率', '功率')):
                    continue
                if has('AP ID', 'AP编号') and has('X', 'X(m)', 'X坐标') and has('Y', 'Y(m)', 'Y坐标') and has('Floor', '楼层'):
                    return 'indoor'
                if (has('Cell ID', '小区ID') and has('Longitude', '经度') and has('Latitude', '纬度')
                    and has('Height (m)', 'Antenna Height', '天线高度', '天线高度(m)') and has('Azimuth', 'Azimuth (°)', '方位角', '天线方位角')):
                    return 'outdoor'
        except (UnicodeError, csv.Error):
            continue
    return ''


def scan_resources(roots, max_depth=4, max_entries=20000, cancel=None, progress=None):
    """Budgets count directory entries; no candidate program or project is executed."""
    if not isinstance(roots, list) or not 1 <= len(roots) <= 16:
        raise ValueError('请选择 1 到 16 个扫描目录')
    if any(not isinstance(r, str) or not r.strip() or '\0' in r or not Path(r).is_absolute() for r in roots):
        raise ValueError('扫描目录必须是完整路径')
    if type(max_depth) is not int or not 0 <= max_depth <= 12:
        raise ValueError('扫描深度必须为 0 到 12')
    if type(max_entries) is not int or not 1 <= max_entries <= 100000:
        raise ValueError('扫描条目上限必须为 1 到 100000')
    cancel = cancel or threading.Event()
    snapshot = dict(status='running', visited=0, results=[], skipped=[], limited=False)
    seen, candidates = set(), set()
    pending = deque((Path(r), 0) for r in roots)

    def skip(path, reason):
        if len(snapshot['skipped']) < 100:
            snapshot['skipped'].append(dict(path=str(path).replace('\\', '/'), reason=reason))

    def add(kind, path, evidence, values=None):
        key = (kind, os.path.normcase(str(path)))
        if key in candidates:
            return
        if len(snapshot['results']) >= 500:
            snapshot['limited'] = True
            return
        candidates.add(key)
        item = dict(kind=kind, path=path.as_posix(), label=path.name or path.as_posix(), evidence=evidence)
        if values:
            item['values'] = values
        snapshot['results'].append(item)

    while pending and not cancel.is_set() and not snapshot['limited']:
        directory, depth = pending.popleft()
        try:
            if _link(directory):
                skip(directory, '跳过链接或重解析点')
                continue
            key = os.path.normcase(str(directory.resolve()))
            if key in seen:
                continue
            seen.add(key)
            if not directory.is_dir():
                skip(directory, '目录不存在或不可访问')
                continue
            if depth >= max_depth:
                continue
            files, subdirs = {}, {}
            with os.scandir(directory) as entries:
                for entry in entries:
                    if cancel.is_set():
                        break
                    if snapshot['visited'] >= max_entries:
                        snapshot['limited'] = True
                        break
                    snapshot['visited'] += 1
                    path = Path(entry.path)
                    try:
                        if _link(path):
                            skip(path, '跳过链接或重解析点')
                        elif entry.is_dir(follow_symlinks=False):
                            if entry.name.lower() in SKIP_NAMES:
                                skip(path, '跳过系统或依赖目录')
                            else:
                                subdirs[entry.name.lower()] = path
                        elif entry.is_file(follow_symlinks=False):
                            files[entry.name.lower()] = path
                    except OSError as exc:
                        skip(path, str(exc))
            if cancel.is_set():
                break
            if ('cmakelists.txt' in files and 'lishuttle' in subdirs and
                (directory / 'SwanUtility/incl/LiShuttleTypes.h').is_file()):
                add('engine', directory, ['CMakeLists.txt', 'LiShuttle/', 'SwanUtility/incl/LiShuttleTypes.h'])
            if any(name.endswith('.das') for name in files) or ('index.txt' in files and directory.name.lower() == 'heights'):
                leaf = directory.parent if directory.name.lower() == 'heights' and 'index.txt' in files else directory
                indoor = leaf == directory
                add('map', leaf, ['.das 场景文件' if indoor else 'heights/index.txt'], {'MAP_ROOT': leaf.parent.as_posix()})
                add('map-root', leaf.parent, ['包含已识别地图'], {'MAP_ROOT': leaf.parent.as_posix()})
            if any(name.endswith('.dll') for name in files):
                add('dll', directory, ['包含 DLL（架构与版本须运行前核对）'], {'DLL_SRC': directory.as_posix()})
            task_evidence = []
            for name, path in files.items():
                if cancel.is_set():
                    break
                try:
                    if name.endswith('.csv'):
                        kind = _csv_kind(path)
                        if kind:
                            task_evidence.append('工参表头：' + path.name + ' · ' + kind)
                    elif name.endswith('.xml') and path.stat().st_size <= 2097152:
                        root = ET.fromstring(path.read_bytes())
                        if root.tag == 'RuntimeSchema':
                            add('runtime', path, ['RuntimeSchema 根节点', 'name=' + root.get('name', '')])
                            task_evidence.append('运行 XML：' + path.name)
                            if directory.name.lower() == 'runtimelibrary':
                                add('config', directory.parent, ['runtimelibrary/RuntimeSchema'], {'CONFIG_SRC': directory.parent.as_posix()})
                except (OSError, ValueError, ET.ParseError) as exc:
                    skip(path, '无法识别：' + str(exc))
            if task_evidence and directory.name.lower() != 'runtimelibrary':
                add('task', directory, task_evidence, {'GONGCAN_ROOT': directory.parent.as_posix()})
                add('task-root', directory.parent, ['包含已识别任务'], {'GONGCAN_ROOT': directory.parent.as_posix()})
            pending.extend((path, depth + 1) for path in subdirs.values())
            if progress:
                progress(deepcopy(snapshot))
        except OSError as exc:
            skip(directory, str(exc))
    snapshot['status'] = 'cancelled' if cancel.is_set() else 'done'
    if progress:
        progress(deepcopy(snapshot))
    return snapshot


class DiscoveryManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._tasks = {}

    def start(self, roots, max_depth=4, max_entries=20000):
        # Validate synchronously so malformed requests never look like running scans.
        checked = threading.Event()
        checked.set()
        scan_resources(roots, max_depth, max_entries, checked)
        with self._lock:
            for task in self._tasks.values():
                task['cancel'].set()
            while len(self._tasks) >= 8:
                self._tasks.pop(next(iter(self._tasks)))
            identity = uuid.uuid4().hex
            task = dict(cancel=threading.Event(), snapshot=dict(id=identity, status='running',
                visited=0, results=[], skipped=[], limited=False))
            self._tasks[identity] = task
            def update(value):
                with self._lock:
                    task['snapshot'] = dict(value, id=identity)
            def run():
                try:
                    scan_resources(roots, max_depth, max_entries, task['cancel'], update)
                except Exception as exc:
                    update(dict(task['snapshot'], status='failed', error=str(exc)))
            task['thread'] = threading.Thread(target=run, name='resource-discovery', daemon=True)
            task['thread'].start()
            return identity

    def status(self, identity):
        with self._lock:
            if identity not in self._tasks:
                raise ValueError('扫描记录不存在，请重新扫描')
            return deepcopy(self._tasks[identity]['snapshot'])

    def cancel(self, identity):
        with self._lock:
            if identity not in self._tasks:
                raise ValueError('扫描记录不存在，请重新扫描')
            self._tasks[identity]['cancel'].set()
        return self.status(identity)

    def close(self):
        with self._lock:
            tasks = list(self._tasks.values())
            for task in tasks:
                task['cancel'].set()
        for task in tasks:
            task['thread'].join(timeout=2)
