<?xml version="1.0" encoding="utf-8"?>
<!--
  ============================================================
  运行时运行单模板（RuntimeSchema）

  这个文件本身不能直接运行，它由 scripts/render_schema.py 渲染成成品：

      python scripts/render_schema.py jobs/<任务单>.env local-win
      python3 scripts/render_schema.py jobs/<任务单>.env server

  输出位置（必须是这里，程序才会找到）：
      <exe目录>/runtimelibrary/<SCHEMA_NAME>

  为什么必须是这个位置：LiShuttle/src/main.cpp:68-94 用
  get_executable_path() 把配置目录解析为 <exe目录>/runtimelibrary/
  （常量在 LiShuttle/incl/configs.h:11），与当前工作目录无关。

  本文件里形如 ${ 大括号 } 的地方是占位符，由渲染脚本替换；
  可用占位符的完整清单见 README.md 第 3 节和 jobs/ 里任务单的注释。
  本注释块里刻意不写占位符字面量，否则会被渲染替换掉。

  路径一律用正斜杠，例如 D:/LiShuttle/map/，
  upl_access / upl_mkdir 两种平台都认，所以一份模板可以跨平台渲染。

  下面调参类字段为示例默认值，请按实际引擎版本和模型需要调整。
  ============================================================
-->
<RuntimeSchema name="${JOB_NAME}">

	<!-- ==================== 输入路径 ==================== -->

	<!-- 工参 CSV：小区/基站工程参数表 -->
	<EngineeringFilePath>${ENGINEERING_FILE}</EngineeringFilePath>

	<!-- 地图投影参数。从每张地图自己的 heights/projection.txt 读取，
	     不要硬编码城市或 UTM 分区（广州是 UTM 49N，合肥是 50N） -->
	<ProjectionFilePath>${MAP_ROOT}/${CITY}/heights/projection.txt</ProjectionFilePath>

	<!-- 地图各类索引 -->
	<HeightIndexPath>${MAP_ROOT}/${CITY}/heights/index.txt</HeightIndexPath>
	<ClutterIndexPath>${MAP_ROOT}/${CITY}/clutter/index.txt</ClutterIndexPath>
	<ClutterMenuPath>${MAP_ROOT}/${CITY}/clutter/menu.txt</ClutterMenuPath>
	<BuildingIndexPath>${MAP_ROOT}/${CITY}/buildings/index.txt</BuildingIndexPath>
	<!-- 注意：源码里这个字段名拼写就是 BulidVector（少个 d），照抄，别改 -->
	<BulidVectorIndexPath>${MAP_ROOT}/${CITY}/buildvector/index.txt</BulidVectorIndexPath>

	<!-- 杂波匹配配置 -->
	<ClutterMatchPath>${CLUTTER_MATCH_FILE}</ClutterMatchPath>

	<!-- 场景配置。留空时程序回退到 <exe目录>/config/scenesettings.xml
	     （LiShuttle/src/ServiceHelper.cpp:154-166） -->
	<SceneSettingsPath>${SCENE_SETTINGS_FILE}</SceneSettingsPath>

	<!-- 区域多边形：WGS84 经纬度，用于限定计算范围 -->
	<PolygonFilePath>${POLYGON_FILE}</PolygonFilePath>

	<!-- ==================== 输出路径 ==================== -->

	<!-- 路损结果输出根目录。
	     【注意】程序会在这个目录后面追加运行单的 name 属性
	     （LiShuttle/src/ServiceHelper.cpp:126-130），所以这里只写"根"，
	     不要带任务名，否则最终目录会变成 root/<任务名>/<任务名>。
	     最终输出目录 = <这里>/<name 属性> = ${OUT_ROOT}/${JOB_NAME}/
	     程序会检查并自动创建（ServiceHelper.cpp:132-150）。 -->
	<PathlossDirectory>${OUT_ROOT}</PathlossDirectory>

	<!-- ==================== 计算范围与精度 ==================== -->

	<DefaultCalcRadius>800</DefaultCalcRadius>
	<DefaultCalcResolution>5</DefaultCalcResolution>
	<DefaultAngleRes>1</DefaultAngleRes>
	<!-- 计算高度层数由这两个字段决定：层数 = MaxCalcHeight / DefaultFloorHeight。
	     3/3 = 只有地面以上一层（3m）。例如 100/10 表示 10m 到 100m 的多层。
	     要多层就在任务单里调整 MAX_CALC_HEIGHT 和 DEFAULT_FLOOR_HEIGHT。 -->
	<MaxCalcHeight>${MAX_CALC_HEIGHT}</MaxCalcHeight>
	<DefaultFloorHeight>${DEFAULT_FLOOR_HEIGHT}</DefaultFloorHeight>
	<DefaultUEHeight>1.5</DefaultUEHeight>
	<SpatialCalcMode>3d</SpatialCalcMode>
	<MaxHops>6</MaxHops>
	<Max_Error>0.01</Max_Error>
	<Epoch>20</Epoch>

	<!-- 强制重算：false 时会复用已有结果，调试时想重算就改成 true -->
	<IsForcedCalc>false</IsForcedCalc>

	<!-- 建筑相关 -->
	<UsingBuildingPolygon>true</UsingBuildingPolygon>
	<RoofOrGround>Ground</RoofOrGround>
	<PeneLossMode>0</PeneLossMode>
	<OnlyOutdoor>false</OnlyOutdoor>

	<!-- ==================== 业务判定阈值 ==================== -->

	<MicroThreshold>0.25</MicroThreshold>
	<MacroThreshold>0.9</MacroThreshold>
	<MicroMaxRadius>500</MicroMaxRadius>
	<MacroMinAntHeight>15</MacroMinAntHeight>
	<EdgeDistanceOfMerged>10</EdgeDistanceOfMerged>
	<DistanceOfVirtualSource>500</DistanceOfVirtualSource>
	<MaxPower>200</MaxPower>
	<MinPower>1</MinPower>
	<MaxDistance>900</MaxDistance>
	<MinDistance>1</MinDistance>

	<!-- ==================== 天线与增益 ==================== -->

	<AntGainCalced>true</AntGainCalced>
	<FourierScale>0.5</FourierScale>
	<CordPrecision>4</CordPrecision>
	<RsrpOffset>0</RsrpOffset>

	<!-- ==================== 射线追踪 ==================== -->

	<!-- 想用 -f rays / -f indoorrays 记录射线时，把 RaySpectrumSaved 改成 true -->
	<RaySpectrumSaved>false</RaySpectrumSaved>
	<RaysCache>1000</RaysCache>
	<CellPLCache>1000</CellPLCache>
	<PWaveCount>5</PWaveCount>
	<SigmaRCS>0.01</SigmaRCS>

	<!-- ==================== 传播模型校正（-f cali） ==================== -->

	<CorModelName>test</CorModelName>
	<CalNewModelName>test</CalNewModelName>
	<IsCorrect_Los_K0andKnear>true</IsCorrect_Los_K0andKnear>
	<IsCorrect_Los_Kfar>true</IsCorrect_Los_Kfar>
	<IsCorrect_nLos_K0andKnear>true</IsCorrect_nLos_K0andKnear>
	<IsCorrect_nLos_Kfar>true</IsCorrect_nLos_Kfar>
	<IsCorrectDiffraction>true</IsCorrectDiffraction>
	<IsCorrectReflection>true</IsCorrectReflection>
	<IsCorrectSceneModel>false</IsCorrectSceneModel>
	<ForceCalibaration>false</ForceCalibaration>
	<CorrectByDT>false</CorrectByDT>
	<IsFilterBackData>true</IsFilterBackData>
	<MinSamples>10</MinSamples>
	<MinDistRangeBefore15>50</MinDistRangeBefore15>
	<MinDistanceRange>80</MinDistanceRange>
	<MinCorrCoef>0.5</MinCorrCoef>
	<MaxGiniCoef>0.4</MaxGiniCoef>
	<MinAccuracyRate>0.6</MinAccuracyRate>
	<MinK0>18</MinK0>
	<MaxK0>38</MaxK0>
	<MinKnear>18</MinKnear>
	<MaxKnear>30</MaxKnear>
	<MinDeltaKfar>0</MinDeltaKfar>
	<MaxDeltaKfar>30</MaxDeltaKfar>
	<MinDiff>0.1</MinDiff>
	<MaxDiff>1</MaxDiff>
	<MinRef>0.2</MinRef>
	<MaxRef>1</MaxRef>
	<Max_MeanError>0.5</Max_MeanError>
	<Max_VarError>4</Max_VarError>
	<!-- 路测数据目录：-f dt / -f cali 需要 -->
	<DriverTestFileDictionaryPath>${DT_ROOT}</DriverTestFileDictionaryPath>

	<!-- ==================== 传播模型存储 ==================== -->

	<!-- true = 模型只临时存储，不改动 models 目录下的正式模型文件。
	     调试阶段保持 true 更安全，避免把测试模型写进共享模型库 -->
	<ModelTemporaryStorage>true</ModelTemporaryStorage>
	<RebuildSceneModel>false</RebuildSceneModel>
	<isCorrectExclusiveModel>true</isCorrectExclusiveModel>

	<!-- ==================== 自动参数优化（-f acp） ==================== -->

	<ACP_Algorithm>0</ACP_Algorithm>
	<IsOptRSRP>true</IsOptRSRP>
	<IsOptSINR>true</IsOptSINR>
	<IsOptEleTilt>true</IsOptEleTilt>
	<IsOptAzimuth>true</IsOptAzimuth>
	<IsOptRsPower>true</IsOptRsPower>
	<IsOptMecTilt>false</IsOptMecTilt>
	<IsOptOutdoor>true</IsOptOutdoor>
	<IsOptIndoor>false</IsOptIndoor>
	<RSRP_Weight>0.5</RSRP_Weight>
	<SINR_Weight>0.5</SINR_Weight>
	<RSRPThreshold>-89</RSRPThreshold>
	<SINRThreshold>5</SINRThreshold>
	<MaxEleTilt>6</MaxEleTilt>
	<MinEleTilt>0</MinEleTilt>
	<MaxAdjustableEleTilt>6</MaxAdjustableEleTilt>
	<MaxAdjustableAzimuth>20</MaxAdjustableAzimuth>
	<MaxRSPower>19.2</MaxRSPower>
	<MinRSPower>10</MinRSPower>
	<MaxAdjustableRSPower>9</MaxAdjustableRSPower>
	<MaxMecTilt>15</MaxMecTilt>
	<MinMecTilt>0</MinMecTilt>
	<MaxAdjustableMecTilt>5</MaxAdjustableMecTilt>
	<PopulationSize>5</PopulationSize>
	<SpeedRatio>0.2</SpeedRatio>
	<IntertiaFactor>0.8</IntertiaFactor>
	<SelfLearnFactor>2</SelfLearnFactor>
	<GroupLearnFactor>2</GroupLearnFactor>
	<MaxIter>10</MaxIter>
	<MinError>0</MinError>

	<!-- ==================== 室内（-f plindoor / -f indoorrays） ==================== -->
	<IndoorRxPowerSF>4</IndoorRxPowerSF>
	<IndoorSinrSF>1</IndoorSinrSF>
	<IndoorRSRPThreshold>-110</IndoorRSRPThreshold>
	<IndoorSINRThreshold>-3</IndoorSINRThreshold>
	<IndoorWeight>0.5</IndoorWeight>

	<!-- ==================== 通感一体化（-f commsensing） ==================== -->

	<RxPowerSF>4</RxPowerSF>
	<SinrSF>1</SinrSF>
	<BsInterf>true</BsInterf>
	<MultiPathInterf>false</MultiPathInterf>
	<ClutterInf>5</ClutterInf>
	<UEThermalNoiseFactor>4</UEThermalNoiseFactor>

	<!-- ==================== 季节与气象 ==================== -->

	<!-- 气象数据取自 ThirdPart/Config/UrbanMeteorologicalData.csv，stage 步骤会复制过去 -->
	<Season>1</Season>
	<RainLevel>0</RainLevel>
	<FogLevel>0</FogLevel>

</RuntimeSchema>
