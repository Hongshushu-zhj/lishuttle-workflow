"""Preview and recoverably archive platform-owned runtime configurations."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET

from vs_launch import PREFIX, _jsonc, prune_text
from project_config import read_legacy


def canonical(path):
    return os.path.normcase(os.path.realpath(path))


def inside(path, parent):
    return Path(canonical(path)).is_relative_to(Path(canonical(parent)))


def build_scope(env):
    identity = canonical(Path(env['PROJECT_DIR']) / env['BUILD_SUBDIR'])
    return 'build-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]


def cleanup_plan(env, jobs_dir, workflow_root, keep_schema=''):
    project = Path(env['PROJECT_DIR']).resolve()
    runtime = project / env['BUILD_SUBDIR'] / 'Bin/runtimelibrary'
    jobs_dir, workflow_root = Path(jobs_dir).resolve(), Path(workflow_root).resolve()
    if not inside(runtime, project) or not env['BUILD_SUBDIR']:
        raise ValueError('构建目录必须位于当前项目内')
    if keep_schema and (Path(keep_schema).name != keep_schema or not keep_schema.endswith('.xml')):
        raise ValueError('保留的运行配置文件名无效')
    if keep_schema and not (runtime / keep_schema).is_file():
        raise ValueError('当前运行配置已不存在，请重新装配或刷新页面后再清理')
    records, protected, skipped, fingerprints = [], set(), [], {}

    def fingerprint(path):
        data = path.read_bytes()
        fingerprints[str(path)] = hashlib.sha256(data).hexdigest()
        return data

    manifests = sorted(runtime.glob('*.xml.manifest.json'))
    for mp in manifests:
        if not inside(mp, runtime) or mp.is_symlink():
            continue
        try:
            data = json.loads(fingerprint(mp).decode('utf-8-sig'))
            source = data.get('schema_source', '')
            if source:
                source = Path(source)
                if not source.is_absolute():
                    source = workflow_root / source
                protected.add(canonical(source))
            xml = Path(str(mp)[:-len('.manifest.json')])
            job = Path(data.get('job_file', ''))
            if not job.is_absolute():
                job = workflow_root / job
            # Old manifests are accepted only with the exact platform job header,
            # current project identity, expected name and bounded real file paths.
            if (canonical(data.get('project_config', {}).get('PROJECT_DIR', '')) != canonical(project)
                    or not xml.is_file() or not inside(xml, runtime) or xml.is_symlink()
                    or not inside(job, jobs_dir) or job.is_symlink() or not job.is_file()
                    or job.name != f'web-{data.get("job_name", "")}.env'
                    or xml.name != str(data.get('job_name', '')) + '.xml'
                    or data.get('run', {}).get('schema_names') != [xml.name]
                    or canonical(data.get('run', {}).get('exe_dir', '')) != canonical(runtime.parent)):
                skipped.append(mp.name)
                continue
            job_text = fingerprint(job).decode('utf-8-sig')
            if not job_text.startswith('# 由平台生成，可手工编辑后用脚本复跑\n'):
                # read_bytes preserves Windows CRLF; normalize only for checking.
                if not job_text.replace('\r\n', '\n').startswith('# 由平台生成，可手工编辑后用脚本复跑\n'):
                    skipped.append(mp.name)
                    continue
            fingerprint(xml)
            metadata = read_legacy(job)
            archive_job = (metadata.get('JOB_NAME') == data['job_name']
                           and metadata.get('SCHEMA_NAME') in ('${JOB_NAME}.xml', xml.name)
                           and canonical(metadata.get('PLATFORM_PROJECT_DIR', '')) == canonical(project)
                           and metadata.get('PLATFORM_BUILD_SUBDIR', '').replace('\\', '/').rstrip('/')
                           == env['BUILD_SUBDIR'].replace('\\', '/').rstrip('/')
                           and metadata.get('PLATFORM_JOB_SCOPE') == 'build-v1'
                           and job.parent.name == build_scope(env))
            records.append(dict(xml=xml, manifest=mp, job=job, archive_job=archive_job))
        except (ValueError, OSError, TypeError, AttributeError):
            skipped.append(mp.name)

    launch = project / '.vs/launch.vs.json'
    if launch.exists() and (not inside(launch, project) or launch.is_symlink()):
        raise ValueError('启动配置链接指向项目外，未执行清理')
    original = fingerprint(launch) if launch.is_file() else None
    launch_text = original.decode('utf-8-sig') if original is not None else None
    manual_entries = []
    if launch_text is not None:
        data = json.loads(_jsonc(launch_text))
        if not isinstance(data, dict):
            raise ValueError('VS 启动配置根节点必须为对象')
        entries = data.get('configurations', [])
        if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
            raise ValueError('VS 启动配置格式不正确，请先修复再清理')
        manual_entries = [e for e in entries if not str(e.get('name', '')).startswith(PREFIX)]
        # Validate duplicate keys / structure before any file can move.
        prune_text(launch_text, set())
    if records and not keep_schema:
        keep_schema = max(records, key=lambda r: r['manifest'].stat().st_mtime_ns)['xml'].name
    if keep_schema:
        protected.add(canonical(runtime / keep_schema))
    protected.update(canonical(runtime / name) for name in ('runtimeschema.xml', 'runtimeschema-indoor.xml'))
    for r in records:
        if any(r['xml'].name in json.dumps(e, ensure_ascii=False) for e in manual_entries):
            protected.add(canonical(r['xml']))
    # Protect XML resources referenced by any runtime XML (including hand-written
    # configurations); configurations not provably owned are never candidates.
    for xml in runtime.glob('*.xml'):
        if not inside(xml, runtime) or xml.is_symlink():
            continue
        try:
            root = ET.fromstring(fingerprint(xml).decode('utf-8-sig'))
        except (OSError, ValueError, ET.ParseError):
            # A broken handwritten file could still reference a generated file.
            for r in records:
                protected.add(canonical(r['xml']))
            continue
        for node in root.iter():
            value = (node.text or '').strip()
            if value.lower().endswith('.xml'):
                path = Path(value)
                if path.is_absolute():
                    protected.add(canonical(path))
                else:
                    protected.add(canonical(runtime.parent / path))
                    protected.add(canonical(runtime / path))
    history = [r for r in records if canonical(r['xml']) not in protected]
    keep_jobs = {canonical(r['job']) for r in records if r not in history}
    files = {}
    for r in history:
        paths = [r['xml'], r['manifest'], Path(str(r['xml']) + '.bak')]
        if r['archive_job'] and canonical(r['job']) not in keep_jobs:
            paths.append(r['job'])
        for path in paths:
            if not path.is_file() or path.is_symlink():
                continue
            parent, category = (jobs_dir, 'jobs') if path == r['job'] else (project, 'project')
            if not inside(path, parent):
                continue
            fingerprint(path)
            relative = path.resolve().relative_to(parent)
            files[str(path)] = dict(path=path.as_posix(), archived_as=(Path(category) / relative).as_posix())
    schemas = {r['xml'].name for r in history}
    current_dir = '${projectDir}/' + env['BUILD_SUBDIR'].replace('\\', '/').strip('/') + '/Bin'
    merged = prune_text(launch_text, schemas, current_dir=current_dir) if launch_text is not None else None
    if merged == launch_text:
        merged = None
    token_data = dict(project=str(project), runtime=str(runtime), keep=keep_schema,
                      files=sorted(files), hashes=fingerprints)
    token = hashlib.sha256(json.dumps(token_data, sort_keys=True).encode('utf-8')).hexdigest()
    return dict(files=sorted(files.values(), key=lambda f: f['path']), schemas=sorted(schemas),
                keep_schema=keep_schema, skipped=skipped, token=token,
                kept_jobs=sorted({r['job'].as_posix() for r in history if not r['archive_job']}),
                launch_path=launch.as_posix(), launch_changed=merged is not None,
                _launch_text=merged, _launch_original=original)


def apply_cleanup(plan, archive_root):
    """Move exact previewed files; roll back all changes if any step fails."""
    if not plan['files']:
        return dict(ok=True, archive='', moved=[], message='没有可清理的历史平台配置')
    archive_root = Path(archive_root)
    archive_root.mkdir(parents=True, exist_ok=True)
    archive = Path(tempfile.mkdtemp(prefix=datetime.now().strftime('%Y%m%d-%H%M%S-'), dir=archive_root))
    moved = []
    launch = Path(plan['launch_path'])
    try:
        mapping = [dict(source=f['path'], archived_as=f['archived_as']) for f in plan['files']]
        (archive / 'restore.json').write_text(json.dumps(dict(files=mapping, project_launch=str(launch)), ensure_ascii=False, indent=2), encoding='utf-8')
        if plan['_launch_text'] is not None:
            (archive / 'launch.vs.json.before').write_bytes(plan['_launch_original'])
        for f in plan['files']:
            source, destination = Path(f['path']), archive / f['archived_as']
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            moved.append((source, destination))
        if plan['_launch_text'] is not None:
            encoded = plan['_launch_text'].encode('utf-8')
            if plan['_launch_original'].startswith(b'\xef\xbb\xbf'):
                encoded = b'\xef\xbb\xbf' + encoded
            # copy to a sibling first for atomic replacement across drives.
            descriptor, sibling = tempfile.mkstemp(prefix='cleanup-', suffix='.tmp', dir=launch.parent)
            try:
                with os.fdopen(descriptor, 'wb') as fh:
                    fh.write(encoded)
                os.replace(sibling, launch)
            finally:
                if os.path.exists(sibling):
                    os.unlink(sibling)
    except Exception:
        for source, destination in reversed(moved):
            shutil.move(str(destination), str(source))
        raise
    return dict(ok=True, archive=archive.as_posix(), moved=[str(s) for s, _ in moved],
                message=f'已归档 {len(moved)} 个历史配置文件；当前任务及原始数据保留')
