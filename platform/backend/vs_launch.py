"""Generate task launch entries for Visual Studio, preserving hand-written JSONC."""

import json
import os
from pathlib import Path
import re
import shutil
import tempfile


PREFIX = '[LiShuttle 平台] '
OUTDOOR_FUNCTIONS = ('pl', 'pred', 'rays', 'dt', 'cali', 'acp', 'ai', 'scene')
INDOOR_FUNCTIONS = ('plindoor', 'predindoor', 'indoorrays')


def _jsonc(text):
    """Mask comments and trailing commas without changing character offsets."""
    tokens = r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/'
    masked = re.sub(tokens, lambda m: m[0] if m[0].startswith('"') else
                    re.sub(r'[^\r\n]', ' ', m[0]), text)
    return re.sub(r'("(?:\\.|[^"\\])*")|,(?=\s*[}\]])',
                  lambda m: m[1] if m[1] is not None else ' ', masked)


def _skip(text, pos):
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'启动配置存在重复键：{key}')
        result[key] = value
    return result


def _merge(text, entries):
    masked = _jsonc(text)
    data = json.loads(masked, object_pairs_hook=_unique_object)
    if not isinstance(data, dict):
        raise ValueError('启动配置根节点必须是对象')
    configs = data.get('configurations', [])
    if not isinstance(configs, list) or any(not isinstance(c, dict) for c in configs):
        raise ValueError('configurations 必须是启动配置对象数组')
    newline = '\r\n' if '\r\n' in text else '\n'

    def format_entry(entry):
        return json.dumps(entry, ensure_ascii=False, indent=2).replace('\n', newline + '    ')

    decoder = json.JSONDecoder()
    # Locate the top-level configurations value; nested keys cannot match here.
    pos = _skip(masked, masked.index('{') + 1)
    array_start = None
    while masked[pos] != '}':
        key, end = decoder.raw_decode(masked, pos)
        pos = _skip(masked, end) + 1  # colon
        pos = _skip(masked, pos)
        _, end = decoder.raw_decode(masked, pos)
        if key == 'configurations':
            array_start = pos
            break
        pos = _skip(masked, end)
        if masked[pos] == ',':
            pos = _skip(masked, pos + 1)

    if array_start is None:
        blocks = (',' + newline + '    ').join(format_entry(e) for e in entries)
        inserted = newline + '  "configurations": [' + newline + '    ' + blocks + newline + '  ]'
        if data:
            inserted += ','
        start = masked.index('{') + 1
        return text[:start] + inserted + newline + text[start:]

    pending = {e['name']: e for e in entries}
    edits = []
    pos = _skip(masked, array_start + 1)
    while masked[pos] != ']':
        config, end = decoder.raw_decode(masked, pos)
        name = config.get('name')
        if isinstance(name, str) and name in pending:
            generated = pending.pop(name)
            if config != generated:
                edits.append((pos, end, format_entry(generated)))
        pos = _skip(masked, end)
        if masked[pos] == ',':
            pos = _skip(masked, pos + 1)
    if pending:
        blocks = (',' + newline + '    ').join(format_entry(e) for e in pending.values())
        # Insert before existing entries so existing trailing commas/comments survive.
        inserted = newline + '    ' + blocks + (',' if configs else '') + newline
        edits.append((array_start + 1, array_start + 1, inserted))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    json.loads(_jsonc(text), object_pairs_hook=_unique_object)
    return text


def sync_launch(project_env, schema_name, func, task_id, city_kind, available):
    """Merge only names reserved by the platform; atomic write with one backup."""
    project = Path(project_env['PROJECT_DIR'])
    target = project / '.vs/launch.vs.json'
    exe = project_env.get('EXE_NAME', 'lishuttle.exe')
    build = project_env['BUILD_SUBDIR'].replace('\\', '/').strip('/')
    current_dir = '${projectDir}/' + build + '/Bin'
    primary = INDOOR_FUNCTIONS if city_kind == 'indoor' else OUTDOOR_FUNCTIONS
    functions = [f for f in primary if f in available]
    if func not in functions:
        functions.append(func)
    entries = [dict(
        type='default', project='CMakeLists.txt',
        projectTarget=f'{exe} (Bin\\{exe})',
        name=f'{PREFIX}{schema_name} / {function}',
        program=f'{current_dir}/{exe}', currentDir=current_dir,
        args=['-f', function, '-t', str(task_id), '-c', schema_name],
    ) for function in functions]
    original = target.read_bytes() if target.exists() else None
    text = original.decode('utf-8-sig') if original is not None else (
        '{\n  "version": "0.2.1",\n  "defaults": {},\n  "configurations": []\n}\n')
    merged = _merge(text, entries)
    encoded = merged.encode('utf-8')
    if original is not None and original.startswith(b'\xef\xbb\xbf'):
        encoded = b'\xef\xbb\xbf' + encoded
    changed = encoded != original
    if changed:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='launch-', suffix='.tmp', dir=target.parent)
        try:
            with os.fdopen(descriptor, 'wb') as fh:
                fh.write(encoded)
            if original is not None:
                shutil.copy2(target, str(target) + '.bak')
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return dict(path=target.as_posix(), entries=[e['name'] for e in entries],
                changed=changed, backup=str(target) + '.bak' if original is not None and changed else '')
