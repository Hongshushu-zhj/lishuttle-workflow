"""One DLL root resolver and explicit, recoverable DLL-only preparation.

Queries never create directories or backups. Sync holds the existing runtime
lease through comparison, replacement and verification; unrelated Bin files are
never in its write plan. Unknown legacy leaf sources remain explicitly usable.
"""
import hashlib
import json
import ntpath
import os
from pathlib import Path
import stat
import shutil
import tempfile

from file_safety import FileConflict, FileTransaction, file_revision


def normalize_dll_path(value):
    value = str(value or '').strip().replace('\\', '/')
    return ntpath.normpath(value).replace('\\', '/') if value else ''


def migrate_dll_values(values, project=''):
    """Return persisted root/source fields without guessing unknown leaf layouts."""
    root = normalize_dll_path(values.get('DLL_ROOT'))
    source = normalize_dll_path(values.get('DLL_SRC'))
    if not root and source:
        leaf = ntpath.basename(source).lower()
        candidate = Path(project) / source
        if leaf in ('debug', 'release'):
            root = normalize_dll_path(ntpath.dirname(source) or '.')
        elif source.lower() == 'thirdpart/dll' or any((candidate / mode).is_dir() for mode in ('Debug', 'Release')):
            root = source
    return {'DLL_ROOT': root, 'DLL_SRC': source}


def resolve_dll(env, build_type=None):
    values = migrate_dll_values(env, env.get('PROJECT_DIR', ''))
    if build_type is None and env.get('PROJECT_DIR') and env.get('PRESET'):
        from project_detection import read_presets
        build_type = read_presets(Path(env['PROJECT_DIR']), []).get(env['PRESET'], {}).get('build_type', '')
    kind = str(build_type or '').lower()
    mode = 'Debug' if kind == 'debug' else 'Release' if kind in ('release', 'relwithdebinfo', 'minsizerel') else ''
    root, source = values['DLL_ROOT'], values['DLL_SRC']
    if not root and not source and (Path(env.get('PROJECT_DIR', '')) / 'ThirdPart/Dll').is_dir():
        root = 'ThirdPart/Dll'
    compatibility = bool(source and not root)
    if root:
        source = normalize_dll_path(ntpath.join(root, mode)) if mode else ''
    exists = bool(source and (Path(env.get('PROJECT_DIR', '')) / source).is_dir())
    if compatibility:
        message = '沿用旧版直接来源目录；选择动态库根目录后，将按构建预设使用 Debug 或 Release 子目录。'
    elif root and not mode:
        message = '请选择有效构建预设，以确定动态库的 Debug 或 Release 子目录。'
    elif not exists:
        message = f'找不到当前构建需要的动态库目录：{source or "未配置"}。请选择包含 {mode or "Debug/Release"} 子目录的动态库根目录。'
    else:
        message = f'当前构建使用 {mode} 子目录。'
    return dict(root=root, source=source, mode=mode, compatibility=compatibility, exists=exists, message=message)


def _is_link(path):
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0)
                                        & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))
    except FileNotFoundError:
        return False


def _reject_links(path):
    for part in (path, *path.parents):
        if _is_link(part):
            raise ValueError(f'动态库准备不支持链接目录或文件：{part}')


def _directories(env):
    resolved = resolve_dll(env)
    if not resolved['exists']:
        raise ValueError(resolved['message'])
    if not env.get('BUILD_SUBDIR'):
        raise ValueError('请先应用构建预设并确认已有程序，再准备动态库。')
    source = Path(os.path.abspath(Path(env['PROJECT_DIR']) / resolved['source']))
    binary = Path(os.path.abspath(Path(env['PROJECT_DIR']) / env['BUILD_SUBDIR'] / 'Bin'))
    _reject_links(source)
    _reject_links(binary)
    if not binary.is_dir() or not any(path.is_file() for path in binary.glob('*.exe')):
        raise ValueError('当前构建的 Bin 目录中没有程序，请先编译或应用已有程序。')
    source_real, binary_real = os.path.realpath(source), os.path.realpath(binary)
    try:
        overlap = os.path.commonpath([source_real, binary_real]) in (source_real, binary_real)
    except ValueError:
        overlap = False
    if overlap:
        raise ValueError('动态库来源与当前 Bin 目录不能相同或互相包含。')
    return resolved, source, binary


def compare_dlls(env):
    """Describe only DLL byte differences; never modify sources or Bin."""
    resolved, source, binary = _directories(env)
    files = []
    counts = dict(same=0, different=0, missing=0)
    for base, directories, names in os.walk(source, followlinks=False):
        directories[:] = sorted(name for name in directories if name != '.lishuttle-history')
        for directory in directories:
            _reject_links(Path(base) / directory)
        for name in sorted(names):
            if not name.lower().endswith('.dll'):
                continue
            original = Path(base) / name
            relative = original.relative_to(source)
            target = binary / relative
            _reject_links(original)
            _reject_links(target)
            if target.exists() and not target.is_file():
                raise ValueError(f'动态库目标不是文件：{target}')
            source_revision, target_revision = file_revision(original), file_revision(target)
            if source_revision == 'missing':
                raise ValueError(f'动态库来源已变化，请重新比较：{original}')
            status = 'missing' if target_revision == 'missing' else 'same' if source_revision == target_revision else 'different'
            counts[status] += 1
            files.append(dict(path=relative.as_posix(), status=status,
                              source_revision=source_revision, target_revision=target_revision))
    if not files:
        raise ValueError(f'当前动态库来源中没有 DLL 文件：{source}')
    revision = hashlib.sha256(json.dumps([str(source), str(binary), files], sort_keys=True).encode('utf-8')).hexdigest()
    return dict(**resolved, source_directory=source.as_posix(), bin_directory=binary.as_posix(),
                counts=counts, files=files, revision=revision, pending=counts['different'] + counts['missing'])


def sync_dlls(env, runtime, resources, revision=None):
    """Explicit sync under existing process/resource locks, with complete rollback.

    Pass the revision from compare_dlls to reject stale user previews. A caller
    already using runtime.operation can safely nest this operation (RuntimeGuard
    retains the outer owner); ordinary callers need no separate runtime wrapper.
    """
    with runtime.operation('准备动态库') as token:
        # Compute the actual Bin ourselves rather than trusting a caller's hint.
        binary = Path(env.get('PROJECT_DIR', '')) / env.get('BUILD_SUBDIR', '') / 'Bin'
        runtime.acquire_resources(token, dict(resources, bin_dir=os.path.realpath(binary)))
        before = compare_dlls(env)
        if revision is not None and revision != before['revision']:
            raise ValueError('动态库来源或 Bin 已变化，请重新比较后再准备。')
        source, binary = Path(before['source_directory']), Path(before['bin_directory'])
        updated = 0
        with FileTransaction() as transaction:
            written = {}
            try:
                for entry in before['files']:
                    if entry['status'] == 'same':
                        continue
                    original, target = source / entry['path'], binary / entry['path']
                    _reject_links(original)
                    _reject_links(target)
                    _reject_links(Path(str(target) + '.bak'))
                    _reject_links(target.parent / '.lishuttle-history')
                    if (file_revision(original) != entry['source_revision']
                            or file_revision(target) != entry['target_revision']):
                        raise ValueError('动态库文件已变化，请重新比较后再准备。')
                    # Publish only the exact bytes the user compared. A live
                    # source may change while it is being read; verify a private
                    # streamed snapshot before it can reach the destination.
                    with tempfile.TemporaryDirectory(prefix='lishuttle-dll-source-') as temporary:
                        snapshot = Path(temporary) / original.name
                        shutil.copy2(original, snapshot)
                        if file_revision(snapshot) != entry['source_revision']:
                            raise ValueError('动态库来源在读取期间发生变化，请重新比较后再准备。')
                        transaction.copy(snapshot, target, backup=True,
                                         expected_revision=entry['target_revision'])
                    written[target] = entry['source_revision']
                    if file_revision(target) != entry['source_revision']:
                        raise ValueError(f'动态库校验未通过：{entry["path"]}')
                    updated += 1
                after = compare_dlls(env)
                if after['pending'] or [f['path'] for f in after['files']] != [f['path'] for f in before['files']]:
                    raise ValueError('动态库来源在准备期间发生变化，已撤回本次更新；请重新比较。')
            except BaseException as error:
                external = []
                for target, published_revision in written.items():
                    if file_revision(target) != published_revision:
                        transaction.discard_snapshot(target, preserve=True)
                        external.append(str(target))
                if external:
                    raise FileConflict('动态库被外部修改，已保留外部内容并撤回其他更新：' + '、'.join(external),
                                       transaction.recovery_dir) from error
                raise
        return dict(after, updated=updated)
