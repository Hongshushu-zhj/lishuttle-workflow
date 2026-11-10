"""Conservatively enable the known indoor building.txt source export block.

This changes source only. An enabled source guard never proves that an existing
executable contains this feature; rebuilding and checking the produced output
remain necessary. Source bytes, encoding and line endings are preserved.
"""

import hashlib
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from file_safety import atomic_write, file_revision, FileConflict  # noqa: E402


SOURCE = Path('Propagation/Frame/src/PathLossofIndoorEngine.cpp')
_DIRECTIVE = re.compile(r'^[\ufeff \t]*#[ \t]*(if|ifdef|ifndef|elif|else|endif)\b([^\r\n]*)', re.M)
_EXPORT = re.compile(
    r'std\s*::\s*string\s+filePath\s*=\s*m_calcParams\s*\.\s*pathlossDirectory\s*\+\s*'
    r'"/building\.txt"\s*;\s*'
    r'pBuilding\s*->\s*Export\s*\(\s*filePath\s*\.\s*c_str\s*\(\s*\)\s*\)\s*;')


def _source_path(env):
    project = (env or {}).get('PROJECT_DIR')
    if not isinstance(project, str) or not project.strip():
        raise ValueError('请先选择当前项目')
    root = Path(project).expanduser().resolve()
    path = root / SOURCE
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('室内源码路径通过链接超出了当前项目，拒绝修改')
    return resolved


def _decode(raw):
    for encoding in ('utf-8', 'gb18030'):
        try:
            text = raw.decode(encoding)
            if text.encode(encoding) == raw:
                return text, encoding
        except UnicodeError:
            pass
    raise ValueError('室内源码编码暂不支持，保留原文件')


def _without_comments(text):
    """Mask comments while retaining character positions and quoted literals."""
    characters = list(text)
    index, state = 0, 'code'
    while index < len(text):
        char = text[index]
        following = text[index:index + 2]
        if state == 'line':
            if char in '\r\n':
                previous = index - 2 if char == '\n' and index > 0 and text[index - 1] == '\r' else index - 1
                if previous < 0 or text[previous] != '\\':
                    state = 'code'
            else:
                characters[index] = ' '
        elif state == 'block':
            if following == '*/':
                characters[index:index + 2] = [' ', ' ']
                index += 2
                state = 'code'
                continue
            if char not in '\r\n':
                characters[index] = ' '
        elif state in ('"', "'"):
            if char == '\\':
                index += 2
                continue
            if char == state:
                state = 'code'
        elif following == 'R"':
            opening = re.match(r'R"([^\s()\\]{0,16})\(', text[index:])
            if opening is None:
                raise ValueError('室内源码包含无法识别的原始字符串')
            closing = ')' + opening.group(1) + '"'
            end = text.find(closing, index + opening.end())
            if end < 0:
                raise ValueError('室内源码包含未闭合原始字符串')
            end += len(closing)
            for position in range(index, end):
                if text[position] not in '\r\n':
                    characters[position] = ' '
            index = end
            continue
        elif following in ('//', '/*'):
            characters[index:index + 2] = [' ', ' ']
            state = 'line' if following == '//' else 'block'
            index += 2
            continue
        elif char in ('"', "'"):
            state = char
        index += 1
    if state in ('block', '"', "'"):
        raise ValueError('室内源码包含未闭合注释或字符串，无法安全识别导出块')
    return ''.join(characters)


def _guard_span(text):
    cleaned = _without_comments(text)
    if len(re.findall(r'"/building\.txt"', cleaned)) != 1:
        raise ValueError('需要唯一的 building.txt 导出块；未找到或存在重复代码')
    exports = list(_EXPORT.finditer(cleaned))
    if len(exports) != 1:
        raise ValueError('building.txt 导出语句与已知格式不一致，拒绝自动修改')
    export = exports[0]
    stack, frames = [], []
    for directive in _DIRECTIVE.finditer(cleaned):
        keyword, condition = directive.group(1), directive.group(2)
        if keyword in ('if', 'ifdef', 'ifndef'):
            frame = {'directive': directive, 'keyword': keyword, 'condition': condition, 'branches': False}
            stack.append(frame)
            frames.append(frame)
        elif keyword in ('elif', 'else'):
            if not stack:
                raise ValueError('条件编译结构无法安全识别')
            stack[-1]['branches'] = True
        else:
            if not stack:
                raise ValueError('条件编译结构无法安全识别')
            stack.pop()['end'] = directive.start()
    if stack:
        raise ValueError('条件编译结构未闭合，拒绝修改')
    containing = [frame for frame in frames if frame['directive'].end() <= export.start()
                  and frame['end'] >= export.end()]
    if not containing:
        raise ValueError('building.txt 导出块缺少对应的 #if false / #if true 开关')
    frame = max(containing, key=lambda item: item['directive'].start())
    condition = re.fullmatch(r'\s*(false|true)\s*', frame['condition'])
    if frame['keyword'] != 'if' or condition is None or frame['branches']:
        raise ValueError('building.txt 最近的条件开关不是独立的 #if false / #if true 块')
    content = cleaned[frame['directive'].end():frame['end']].strip()
    if content != export.group(0).strip():
        raise ValueError('building.txt 条件块包含其他代码，拒绝修改其编译行为')
    start = frame['directive'].start(2) + condition.start(1)
    end = frame['directive'].start(2) + condition.end(1)
    return start, end, condition.group(1) == 'true'


def _inspect(env):
    state = {'path': '', 'revision': 'missing', 'enabled': None,
             'supported': False, 'reason': '', 'requires_rebuild': False}
    raw, span, encoding = None, None, None
    try:
        path = _source_path(env)
        state['path'] = str(path)
        raw = path.read_bytes()
        state['revision'] = hashlib.sha256(raw).hexdigest()
        text, encoding = _decode(raw)
        start, end, enabled = _guard_span(text)
        span = (len(text[:start].encode(encoding)), len(text[:end].encode(encoding)))
        state.update(enabled=enabled, supported=True, requires_rebuild=True)
    except (OSError, ValueError, RuntimeError) as error:
        state['reason'] = str(error)
    return state, raw, span


def inspect(env):
    """Read source status without modifying source, backups or configuration."""
    return _inspect(env)[0]


def enable(env, expected_revision):
    """Enable only the recognized guard, backing up the prior source atomically."""
    if not isinstance(expected_revision, str) or not expected_revision:
        raise ValueError('缺少源码内容版本，请重新检查后开启')
    state, raw, span = _inspect(env)
    if not state['supported']:
        raise ValueError(state['reason'] or '当前室内源码暂不支持自动开启')
    if state['revision'] != expected_revision:
        raise FileConflict('室内源码已被其他程序修改，请重新检查后开启')
    path = _source_path(env)
    if str(path) != state['path']:
        raise ValueError('室内源码路径已变化，请重新检查')
    if state['enabled']:
        if file_revision(path) != expected_revision:
            raise FileConflict('室内源码已被其他程序修改，请重新检查')
        return dict(state, changed=False)
    start, end = span
    revision = atomic_write(path, raw[:start] + b'true' + raw[end:],
                            backup=True, expected_revision=expected_revision)
    return dict(state, enabled=True, revision=revision, changed=True)
