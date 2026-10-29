"""Reviewed service dependency scopes, not guesses based on parameter labels.

Evidence and SHA256 baselines are recorded in function_profile_sources.json.
These rules describe the reviewed local engine; differing source versions are
reported explicitly. They never change a RuntimeSchema or run an engine.
"""
import hashlib
import json
import math
from pathlib import Path


SOURCES = {
    'common': 'LiShuttle/src/ServiceHelper.cpp:86-163',
    'scene': 'LiShuttle/src/SceneInfoCollection.cpp:133-189',
    'geo': 'GIS/Data/src/GeoSubSys.cpp:7-83,181-234',
    'cell': 'NetEntity/src/CellLoader.cpp:478-539',
    'ap': 'NetEntity/src/IndoorAPLoader.cpp:63-68',
    'antenna': 'Antenna/src/AntSubSys.cpp:42-73',
    'pl': 'Propagation/Interface/src/PathLossCalcParams.cpp:55-108',
    'indoor': 'Propagation/Interface/src/PathLossCalcParams.cpp:239-267',
    'cali': 'Propagation/PMCorrectionPlugins/src/CalibrationParams.cpp:31-87',
    'pred': 'Prediction/src/PredParams.cpp:43-109; Prediction/src/PredictionEngine.cpp:228-248',
    'predindoor': 'Prediction/src/PredParams.cpp:113-126; Prediction/src/IndoorPredictionEngine.cpp:35-83',
    'sensing': 'Prediction/src/PredictionEngine.cpp:251-301; Prediction/src/EchoCalculator.cpp:12-180; Prediction/src/ScrCalculator.cpp:78-99',
    'acp': 'ACP/Common/src/ACPCommonParams.cpp:307-510',
    'pso': 'ACP/Pso/src/ParticleBase.cpp:9-25; ACP/Frame/src/ACPEngine.cpp:300-329',
}
FUNCTIONS = {
    'cali': ('传播模型校正', 'outdoor', '路测数据筛选、LOS/NLOS 系数约束、场景/专属模型校正；同时调用室外路损引擎。'),
    'pred': ('室外覆盖预测', 'outdoor', '计算 RSRP、下行 SINR 和最佳服务小区；同时调用室外路损引擎，不启用感知回波计算器。'),
    'predindoor': ('室内覆盖预测', 'indoor', '先运行室内路损，再计算室内 RSRP/SINR；使用 AP 工参、室内地图和室内射线参数。'),
    'acp': ('自动参数优化', 'outdoor', '覆盖指标驱动的射频优化：优化开关、调整边界、目标权重、监控区域和 PSO；当前引擎不支持 SpatialCalcMode=3d。'),
    'commsensing': ('通感一体化预测', 'outdoor', '运行感知回波与 SCR 计算器，可选基站干扰和多径干扰；感知功率、带宽及噪声系数来自工参 CSV。'),
}


def _enabled(values, tag, default=False):
    value = str(values.get(tag, str(default))).strip().lower()
    if value in ('true', '1'):
        return True
    if value in ('false', '0'):
        return False
    return default  # TinyXML QueryBoolText default behaviour for invalid values.


def _positive(values, tag, default=0):
    try:
        return float(values.get(tag, default)) > 0.000001
    except (TypeError, ValueError):
        return default > 0.000001


def function_profile(func, values):
    if func not in FUNCTIONS:
        return {}, dict(reviewed=False)
    label, scene, description = FUNCTIONS[func]
    rules = {}

    def add(tags, key, kind='function', required=False, condition='', active=True, note=''):
        for tag in tags.split():
            rules[tag] = dict(kind=kind, source=SOURCES[key], required=required,
                              condition=condition, active=active, note=note)

    add('MapFormat CityCode CpuLoad DefaultCalcResolution PathlossDirectory SceneSettingsPath', 'common', 'common')
    rules['PathlossDirectory']['required'] = True
    add('DefaultFloorHeight DefaultFloorLoss', 'scene', 'common')
    try:
        scales_valid = all(math.isfinite(float(values[tag])) for tag in ('FourierScale', 'VertFourierScale'))
    except (KeyError, TypeError, ValueError):
        scales_valid = False
    add('FourierScale VertFourierScale', 'antenna', 'dependency',
        condition='FourierScale 与 VertFourierScale 同时为有效数值；AntGainCalced=true 时用于天线增益',
        active=scales_valid and _enabled(values, 'AntGainCalced', True))
    add('EngineeringFilePath ForcedFreq', 'ap' if scene == 'indoor' else 'cell', 'dependency')
    rules['EngineeringFilePath']['required'] = True
    if scene == 'indoor':
        add('MapPath MinimumWallLength', 'geo', 'dependency')
        rules['MapPath']['required'] = True
        add('DefaultLengthError', 'common', 'dependency')
        add('MaxRayNumber MaxDiffraction MaxReflection MaxPenetration MaxDeepth DefaultCalcRadius DefaultUEHeight AntGainCalced IsForcedCalc', 'indoor', 'dependency')
        add('IndoorRxPowerSF IndoorSinrSF UEThermalNoiseFactor', 'predindoor')
        add('SpatialCalcMode MaxCalcHeight MacroMinAntHeight CordPrecision UsingBuildingPolygon', 'common', 'startup',
            note='公共解析器读取，但独立室内预测链未使用这些室外控制项。')
        add('CityCode DefaultFloorHeight DefaultFloorLoss', 'common', 'startup',
            note='公共解析器读取；室内链从 .das 读取实际楼层，采用物理材料损耗，不使用室外场景楼层默认值。')
        for tag in ('CityCode', 'DefaultFloorHeight', 'DefaultFloorLoss'):
            rules[tag]['source'] += '; GIS/Data/src/IndoorGeoInfo.cpp:48-75; Propagation/Frame/src/PathLossofIndoorEngine.cpp:71-77'
    else:
        add('UsingBuildingPolygon MacroMinAntHeight CordPrecision SpatialCalcMode', 'common', 'common')
        add('MaxCalcHeight', 'common', 'dependency', condition='SpatialCalcMode != ground',
            active=str(values.get('SpatialCalcMode', 'ground')).strip().lower() in ('floor', 'building', '3d'))
        add('ProjectionFilePath HeightIndexPath ClutterIndexPath ClutterMenuPath BuildingIndexPath BulidVectorIndexPath', 'geo', 'dependency',
            condition='XML 不存在 MapPath 元素时使用逐项地图路径', active='MapPath' not in values)
        for tag in ('ProjectionFilePath', 'HeightIndexPath', 'ClutterIndexPath'):
            rules[tag]['required'] = True
        add('MapPath', 'geo', 'dependency', condition='存在 MapPath 元素时使用地图目录（空元素也会进入此分支）')
        add('BuildingPenetration ClutterMatchPath', 'geo', 'dependency')
        add('AntPosAdjustRadius AdjustAntMount Season RainLevel FogLevel IndoorDistFilePath', 'cell', 'dependency')
        add('EngineeringDistanceError EngineeringHeightErrorRatio', 'cell', 'dependency',
            condition='AdjustAntMount=true', active=_enabled(values, 'AdjustAntMount'))
        add('ClutterMatchName MaxHops DefaultAngleRes IsForcedCalc DefaultCalcRadius MicroThreshold MacroThreshold EdgeDistanceOfMerged DistanceOfVirtualSource DefaultUEHeight MicroMaxRadius AntGainCalced NoCheckRay NoCheckPathLoss CorrectByDT', 'pl', 'dependency')
        add('DriverTestFileDictionaryPath', 'pl', 'dependency', condition='CorrectByDT=true（路测锚点修正）', active=_enabled(values, 'CorrectByDT'))
        add('RaySpectrumSaved RoadsToBeRecorded BuildingsDebuged', 'pl', 'startup',
            note='路损参数解析器读取；这些任务调用 Init/按需计算，而非道路记录或建筑调试 Run 分支。')
    if func == 'cali':
        add('MaxPower MinPower MinK0 MinKnear MinDiff MinRef MaxK0 MaxKnear MaxDiff MaxRef CalNewModelName DriverTestFileDictionaryPath', 'cali', required=True)
        add('MinDeltaKfar MaxDeltaKfar AveErrorTolerance MaxMeanJitter MaxVarJitter Epoch Distlimit MinSamples AllowedErrorOfGrid MinDistanceRange MinDistRangeBefore15 RsrpOffset MinCorrCoef MaxGiniCoef MinAccuracyRate IsFilterBackData IsLosCalibrated IsNLosCalibrated IsCorrectExclusiveModel IsCorrectSceneModel ModelTemporaryStorage RebuildSceneModel ForceCalibaration AntGainCalced', 'cali')
    elif func in ('pred', 'commsensing'):
        add('RxPowerSF SinrSF PredictedCells FocusedARFCN PolygonFilePath', 'pred')
        rules['PolygonFilePath']['required'] = True
        if func == 'pred':
            add('UEThermalNoiseFactor', 'pred')
            add('SigmaRCS PWaveCount UavType BsInterf MultiPathInterf ClutterInf', 'pred', 'startup',
                note='共用预测解析器读取；覆盖预测仅创建 RSRP/SINR/BestServer，不创建感知计算器。')
        else:
            add('SigmaRCS PWaveCount UavType BsInterf MultiPathInterf ClutterInf AntGainCalced', 'sensing')
            add('UEThermalNoiseFactor', 'pred', 'startup',
                note='共用解析器读取；SCR 噪声使用工参 CSV 的 senseNF，不使用此 UE 噪声参数。')
            add('DefaultUEHeight', 'pl', 'startup', note='通感功能在路损参数解析后强制将 UE 离地高度设为 0。')
    elif func == 'acp':
        add('ACP_Algorithm RxPowerSF SinrSF UEThermalNoiseFactor FocusedCells FocusedARFCN CellPLCache IndoorWeight MonitorWeight MonitorGridFilePath MonitorPolygonFilePath RSRPandSINR_Weight RSRP_Weight SINR_Weight RSRPThreshold SINRThreshold IndoorRSRPThreshold IndoorSINRThreshold IsOptOutdoor IsOptIndoor', 'acp')
        add('PolygonFilePath IsOptEleTilt IsOptAzimuth IsOptRsPower IsOptMecTilt', 'acp', required=True)
        for switch, tags in (
                ('IsOptEleTilt', 'MinEleTilt MaxEleTilt MaxAdjustableEleTilt'),
                ('IsOptRsPower', 'MinRSPower MaxRSPower MaxAdjustableRSPower'),
                ('IsOptMecTilt', 'MinMecTilt MaxMecTilt MaxAdjustableMecTilt'),
                ('IsOptAzimuth', 'MaxAdjustableAzimuth')):
            add(tags, 'acp', required=True, condition=switch + '=true', active=_enabled(values, switch))
        add('EleTiltSensitivity AzimuthSensitivity RSPowerSensitivity MecTiltSensitivity', 'acp',
            note='优化开关控制变量是否调整；结果导出仍无条件用各灵敏度比较原工参。')
        for tag in ('EleTiltSensitivity', 'AzimuthSensitivity', 'RSPowerSensitivity', 'MecTiltSensitivity'):
            rules[tag]['source'] += '; ACP/Pso/src/ACPPsoCalculator.cpp:149-164'
        for weight, target, default in (('RSRPandSINR_Weight', 'RSRPandSINRUnCovRate', 1),
                ('RSRP_Weight', 'RSRPUnCovRate', 0), ('SINR_Weight', 'SINRUnCovRate', 0)):
            add(target, 'acp', condition=weight + '>0', active=_positive(values, weight, default))
        add('Azimuth_Diff_Weight AzimuthDiffThreshold', 'acp', condition='IsOptAzimuth=true', active=_enabled(values, 'IsOptAzimuth'))
        add('AzimuthSmallRate', 'acp', condition='IsOptAzimuth=true 且 Azimuth_Diff_Weight>0',
            active=_enabled(values, 'IsOptAzimuth') and _positive(values, 'Azimuth_Diff_Weight'))
        add('PopulationSize SpeedRatio IntertiaFactor SelfLearnFactor GroupLearnFactor MaxIter', 'pso', required=True)
        add('SigmaRCS UavType', 'acp', 'startup', note='ACP 共用指标参数结构读取；本版本 ACP 使用覆盖指标，不创建回波/SCR 计算器。')
        for tag in ('IndoorWeight', 'IndoorRSRPThreshold', 'IndoorSINRThreshold'):
            rules[tag].update(condition='IsOptIndoor=true', active=_enabled(values, 'IsOptIndoor'))
        rules['MonitorWeight'].update(condition='配置 MonitorGridFilePath 或 MonitorPolygonFilePath',
            active=bool(values.get('MonitorGridFilePath', '').strip() or values.get('MonitorPolygonFilePath', '').strip()))
        rules['MonitorPolygonFilePath'].update(condition='MonitorGridFilePath 为空时使用', active=not values.get('MonitorGridFilePath', '').strip())
    missing_required = [tag for tag, rule in rules.items() if rule['kind'] != 'startup' and rule['active'] and rule['required'] and tag not in values]
    missing_optional = [tag for tag, rule in rules.items() if rule['kind'] != 'startup' and not rule['required'] and tag not in values]
    actual_scene = str(values.get('MapFormat', 'PLANET')).strip().lower()
    scene_warning = ''
    if (actual_scene == 'indoor') != (scene == 'indoor'):
        scene_warning = f'{label}需要{scene}地图，当前 MapFormat={values.get("MapFormat", "PLANET（引擎默认）")}；切换功能不会自动修改 XML。'
    return rules, dict(reviewed=True, label=label, scene=scene, description=description,
        scene_warning=scene_warning, missing_required=missing_required, missing_optional=missing_optional,
        notes=['范围包含所调用的路损、地图、工参和天线依赖；必需表示源码强制读取元素，不代表所有项都要手动填写。',
               '条件不满足时仍可在本功能可配置中查看；当前生效视图隐藏已确认未启用的条件项及仅启动读取项。'])


def source_review(func, project_dir):
    """Check the chosen project's source; never claim a different fork was reviewed."""
    if func not in FUNCTIONS:
        return dict(status='unreviewed', files=[])
    baseline = json.loads(Path(__file__).with_name('function_profile_sources.json').read_text(encoding='utf-8'))
    files = baseline['functions'][func]
    missing, changed = [], []
    for relative in files:
        path = Path(project_dir) / relative
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            missing.append(relative)
            continue
        if digest not in baseline['sha256'][relative]:
            changed.append(relative)
    status = 'changed' if changed else 'missing' if missing else 'matched'
    return dict(status=status, files=files, missing=missing, changed=changed,
                reference=baseline['reference'])
