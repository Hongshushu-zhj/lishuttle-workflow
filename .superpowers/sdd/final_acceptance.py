"""Recheck recorded real evidence, then repeat an unchanged copied sensing case."""
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'platform/backend'))
import core
import result_validation

REPORT = ROOT / 'docs/p0-runtime-validation'
manifest = json.loads((REPORT / 'manifest.json').read_text(encoding='utf-8'))


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def save(name, value):
    (REPORT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


rechecked = []
for case in manifest['cases']:
    stored = json.loads((REPORT / (Path(case['schema']).stem + '.json')).read_text(encoding='utf-8'))
    old = stored['report']
    mismatches = [entry['path'] for entry in old['artifacts']['checked']
                  if entry.get('sha256') and (not Path(entry['path']).is_file() or digest(entry['path']) != entry['sha256'])]
    if mismatches:
        item = dict(case=case, stage='evidence_changed', paths=mismatches, original_verdict=old['verdict'])
    else:
        report = result_validation.validate(old['context'], stored['baseline'], stored['console_lines'], old['process']['exit_code'])
        item = dict(case=case, stage='revalidated', report=report, original_verdict=old['verdict'])
    rechecked.append(item)
    print(json.dumps(dict(case=case, stage=item['stage'], verdict=item.get('report', {}).get('verdict')), ensure_ascii=True), flush=True)
save('final-revalidation.json', rechecked)

case = next(case for case in manifest['cases'] if case['schema'] == 'p0-commsensing-ground.xml')
token = core.PROJECT_CONTEXT.set(manifest['env'])
try:
    original_snapshot = result_validation.snapshot
    captured = {}

    def capture(context):
        baseline = original_snapshot(context)
        captured['baseline'] = baseline
        return baseline

    result_validation.snapshot = capture
    try:
        sid, _ = core.start_lishuttle(case['schema'], case['func'], case['task_id'])
    finally:
        result_validation.snapshot = original_snapshot
    deadline = time.monotonic() + 180
    while core.RUNNER.output(sid, 0)['status'] != 'done':
        if time.monotonic() > deadline:
            core.RUNNER.stop(sid)
        time.sleep(.1)
    result = dict(case=case, stage='repeat', report=core.session_results(sid),
                  baseline=captured['baseline'], console_lines=core.RUNNER.output(sid, 0)['lines'])
    save('p0-commsensing-ground-repeat.json', result)
    print(json.dumps(dict(repeat_verdict=result['report']['verdict'], process=result['report']['process'],
                          issue_codes=sorted({i['code'] for i in result['report']['issues']})), ensure_ascii=True), flush=True)
finally:
    core.PROJECT_CONTEXT.reset(token)

unchanged = all(Path(path).is_file() and digest(path) == sha for path, sha in manifest['original_hashes'].items())
save('final-integrity.json', dict(originals_unchanged=unchanged, checked_files=len(manifest['original_hashes']),
                                  runtime_state=core.RUNTIME.snapshot()))
print('originals_unchanged=' + str(unchanged), flush=True)
