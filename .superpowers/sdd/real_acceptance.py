"""Local acceptance on COPIED runtime/CSV/DT; original engine inputs are read only."""
from pathlib import Path
import csv
import hashlib
import io
import json
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[2]
# This scratch script lives at <repo>/.superpowers/sdd during development.
sys.path.insert(0, str(REPO / 'platform/backend'))
import core

LAB = Path('D:/workspace/LAB')
SOURCE = LAB / 'Lab20261013/out/build/x64-release/Bin'
REPORT = REPO / 'docs/p0-runtime-validation'
REPORT.mkdir(parents=True, exist_ok=True)


def digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            sha.update(chunk)
    return sha.hexdigest()


def scalar(root, key, value):
    node = root.find(key)
    if node is None:
        node = ET.SubElement(root, key)
    node.text = str(value)


def read_csv(path):
    data = path.read_bytes()
    for enc in ('utf-8-sig', 'gb18030'):
        try:
            return list(csv.reader(io.StringIO(data.decode(enc))))
        except UnicodeError:
            continue
    raise ValueError(path)


def save_csv(path, rows):
    with path.open('w', encoding='gb18030', newline='') as handle:
        csv.writer(handle).writerows(rows)


def prepare():
    work = Path(tempfile.mkdtemp(prefix='lishuttle-p0-acceptance-'))
    binary = work / 'Bin'
    shutil.copytree(SOURCE, binary, ignore=shutil.ignore_patterns('*.pdb', '*.bak', '*.log', 'uplan.log*'))
    # Each copied schema is isolated; pre-existing schemas in copied Bin are not used.
    inputs = work / 'inputs'
    inputs.mkdir()
    original_files = list((SOURCE/'models').rglob('*.xml')) + list((SOURCE/'runtimelibrary').glob('*.xml'))
    original_files += [LAB/'gongcan/zhengzhou-hybrid-109034/engineering.csv',
                       LAB/'gongcan/indoor/ap-single.csv', LAB/'gongcan/ningde-cali/CALI002600.csv',
                       LAB/'gongcan/ningde-cali/LiJobID002600.csv']
    before = {str(p):digest(p) for p in original_files}
    # The active Bin was last staged for outdoor work and lacks the AP's
    # referenced entity. Add only that official definition to the copied Bin.
    official_ant = LAB/'Lab20261013/ThirdPart/Config/antennas/antenna.xml'
    before[str(official_ant)] = digest(official_ant)
    before[str(SOURCE/'antennas/antenna.xml')] = digest(SOURCE/'antennas/antenna.xml')
    ant = ET.parse(binary/'antennas/antenna.xml')
    original_ant = ET.parse(official_ant)
    if ant.getroot().find("AntennaEntity[@name='omni11dBi']") is None:
        ant.getroot().append(original_ant.getroot().find("AntennaEntity[@name='omni11dBi']"))
        ant.write(binary/'antennas/antenna.xml', encoding='utf-8', xml_declaration=True)
    cases = []
    for func in ('pred', 'commsensing'):
        rows = read_csv(LAB/'gongcan/zhengzhou-hybrid-109034/engineering.csv')
        header = rows[1]
        for row in rows[2:]:
            row[header.index('Main Calculation Radius (m)')] = '80'
            if func == 'commsensing':
                row[header.index('SenseActive')] = '1'
                row[header.index('SensePower')] = '15'
        engineering = inputs/(func+'.csv')
        save_csv(engineering, rows)
        for mode in ('ground','floor','3d'):
            root = ET.parse(SOURCE/'runtimelibrary/zhengzhou-hybrid-109034-pred.xml').getroot()
            name = 'p0-'+func+'-'+mode
            root.set('name',name)
            for key, value in dict(EngineeringFilePath=engineering, PathlossDirectory=work/'outputs',
                SceneSettingsPath=binary/'runtimelibrary/scenesettings.xml',SpatialCalcMode=mode,
                MaxCalcHeight=6,DefaultFloorHeight=3,MaxHops=1,DefaultAngleRes=2,CpuLoad=25,
                DriverTestFileDictionaryPath='',CorrectByDT='false').items():
                scalar(root,key,value)
            filename=name+'.xml'
            ET.ElementTree(root).write(binary/'runtimelibrary'/filename,encoding='utf-8',xml_declaration=True)
            cases.append(dict(schema=filename,func=func,task_id='1'))
    indoor = ET.parse(SOURCE/'runtimelibrary/indoorruntimeschema.xml').getroot()
    # The official template has conflicting duplicate DefaultUEHeight. Preserve
    # the first (the engine's selected value) only in this acceptance copy.
    seen = set()
    for node in list(indoor):
        if node.tag in seen and not list(node):
            indoor.remove(node)
        seen.add(node.tag)
    indoor.set('name','p0-predindoor')
    shutil.copy2(LAB/'gongcan/indoor/ap-single.csv', inputs/'ap.csv')
    for key,value in dict(MapFormat='indoor',MapPath=LAB/'map/sjy',EngineeringFilePath=inputs/'ap.csv',
        SceneSettingsPath=binary/'runtimelibrary/scenesettings.xml',PathlossDirectory=work/'outputs',
        DefaultCalcResolution=.5,MaxReflection=1,MaxDiffraction=1,CpuLoad=25).items():
        scalar(indoor,key,value)
    ET.ElementTree(indoor).write(binary/'runtimelibrary/p0-predindoor.xml',encoding='utf-8',xml_declaration=True)
    cases.append(dict(schema='p0-predindoor.xml',func='predindoor',task_id='1'))
    dt=inputs/'dt'
    dt.mkdir()
    measurements=read_csv(LAB/'gongcan/ningde-cali/CALI002600.csv')
    chosen=measurements[1][1]
    selected=[row for row in measurements[1:] if row[1]==chosen][:600]
    save_csv(dt/'measured.csv',[measurements[0],*selected])
    (dt/'index.txt').write_text('measured.csv\n')
    engineering=read_csv(LAB/'gongcan/ningde-cali/LiJobID002600.csv')
    rows=[row for row in engineering[2:] if row[0]==chosen]
    if not rows:
        raise ValueError('DT cell absent from copied engineering')
    rows[0][engineering[1].index('Active')]='1'
    save_csv(inputs/'calibration.csv',[*engineering[:2],*rows])
    calibration=ET.parse(LAB/'gongcan/ningde-cali/schema_job.xml').getroot()
    calibration.set('name','p0-cali')
    for key,value in dict(EngineeringFilePath=inputs/'calibration.csv',
        SceneSettingsPath=binary/'runtimelibrary/scenesettings.xml',
        ClutterMatchPath=LAB/'map/ningde/ningdecluttermatchsettings.xml',
        PathlossDirectory=work/'outputs',DriverTestFileDictionaryPath=dt,
        ModelTemporaryStorage='true',SpatialCalcMode='3d',MaxCalcHeight=6,DefaultFloorHeight=3,
        MaxHops=1,CpuLoad=25,UsingBuildingPolygon='false').items():
        scalar(calibration,key,value)
    for tag,relative in [('ProjectionFilePath','heights/projection.txt'),('HeightIndexPath','heights/index.txt'),
        ('ClutterIndexPath','clutter/index.txt'),('ClutterMenuPath','clutter/menu.txt'),
        ('BuildingIndexPath','buildings/index.txt'),('BulidVectorIndexPath','buildvector/index.txt')]:
        scalar(calibration,tag,LAB/'map/ningde'/relative)
    ET.ElementTree(calibration).write(binary/'runtimelibrary/p0-cali.xml',encoding='utf-8',xml_declaration=True)
    cases.append(dict(schema='p0-cali.xml',func='cali',task_id='1'))
    manifest=dict(workspace=str(work),env=dict(PROJECT_DIR=str(work),BUILD_SUBDIR='.',EXE_NAME='lishuttle.exe'),
                  cases=cases,original_hashes=before,
                  fixture_changes=['Copy official omni11dBi entity into copied Bin only',
                    'Keep first duplicate indoor scalar in copied XML',
                    'Select existing PLANET raster building branch for cali copy'])
    (REPORT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(workspace=str(work),cases=len(cases)),ensure_ascii=True),flush=True)


def run():
    manifest=json.loads((REPORT/'manifest.json').read_text(encoding='utf-8'))
    token=core.PROJECT_CONTEXT.set(manifest['env'])
    reports=[]
    try:
        for case in manifest['cases']:
            preview=core.check_run(case['schema'],case['func'],case['task_id'])
            if not preview['ok']:
                result=dict(case=case,stage='preflight',report=preview)
            else:
                import result_validation
                original_snapshot = result_validation.snapshot
                captured = {}
                def capture(context):
                    baseline = original_snapshot(context)
                    captured['baseline'] = baseline
                    return baseline
                result_validation.snapshot = capture
                try:
                    sid,_=core.start_lishuttle(case['schema'],case['func'],case['task_id'])
                finally:
                    result_validation.snapshot = original_snapshot
                deadline=time.monotonic()+180
                while core.RUNNER.output(sid,0)['status']!='done':
                    if time.monotonic()>deadline:
                        core.RUNNER.stop(sid)
                    time.sleep(.1)
                result=dict(case=case,stage='run',report=core.session_results(sid),
                    baseline=captured['baseline'],console_lines=core.RUNNER.output(sid,0)['lines'])
            reports.append(result)
            (REPORT/(Path(case['schema']).stem+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(dict(case=case,stage=result['stage'],verdict=result['report'].get('verdict'),
                exit=result['report'].get('exit'),issues=[i.get('code') for i in result['report'].get('issues',[])]),ensure_ascii=True),flush=True)
    finally:
        core.PROJECT_CONTEXT.reset(token)
    unchanged=all(Path(p).is_file() and digest(Path(p))==sha for p,sha in manifest['original_hashes'].items())
    (REPORT/'summary.json').write_text(json.dumps(dict(originals_unchanged=unchanged,runs=reports),ensure_ascii=False,indent=2),encoding='utf-8')
    print('originals_unchanged='+str(unchanged),flush=True)


if __name__=='__main__':
    prepare() if '--prepare' in sys.argv else run()
