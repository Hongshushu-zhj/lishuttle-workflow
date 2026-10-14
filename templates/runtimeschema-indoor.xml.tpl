<?xml version="1.0" encoding="utf-8"?>
<!--
  ============================================================
  室内运行单模板（indoor RuntimeSchema）

  室内地图和计算参数示例；使用前按实际引擎版本核对。

  与室外模板的关键区别：
    <MapFormat>indoor</MapFormat>   ← 室内外分流开关（GeoSubSys.cpp:96-103，
                                      默认 PLANET 走室外，INDOOR 走室内）
    <MapPath>${MAP_PATH}</MapPath>  ← 室内地图目录（里面就一个 building.das），
                                      不再需要 heights/clutter/buildings 四件套索引

  渲染：
      python scripts/render_schema.py jobs/<任务单>.env local-win

  常调参数（来自 如何跑室内.md）：
    - 射线数量/反射/衍射/透射次数：结合 svn 日志定位代码错误
    - DefaultCalcResolution：默认 1，一般手动改成 0.2
    - IsForcedCalc：true = 忽略缓存强制重算
  ============================================================
-->
<RuntimeSchema name="${JOB_NAME}">

	<!-- ==================== 输入路径 ==================== -->

	<!-- 室内工参：AP 位置表（列：AP ID/Floor/x/y/天线/功率...），
	     例如 gongcan/ap-single.csv -->
	<EngineeringFilePath>${ENGINEERING_FILE}</EngineeringFilePath>

	<!-- 地图类型：indoor = 室内 -->
	<MapFormat>indoor</MapFormat>

	<!-- 室内地图数据目录（墙体、材质、楼层），目录下应有 building.das -->
	<MapPath>${MAP_PATH}</MapPath>

	<!-- 场景配置。留空时程序回退到 <exe目录>/config/scenesettings.xml -->
	<SceneSettingsPath>${SCENE_SETTINGS_FILE}</SceneSettingsPath>

	<!-- 区域多边形（WGS84 经纬度）。室内任务可以留空 -->
	<PolygonFilePath>${POLYGON_FILE}</PolygonFilePath>

	<!-- ==================== 输出路径 ==================== -->

	<!-- 输出根目录。程序会追加 name 属性（ServiceHelper.cpp:126-130），
	     最终输出 = ${OUT_ROOT}/${JOB_NAME}/ -->
	<PathlossDirectory>${OUT_ROOT}</PathlossDirectory>

	<!-- ==================== 射线追踪参数（室内核心参数） ==================== -->

	<!-- 强制重算：室内调试建议 true，忽略缓存 -->
	<IsForcedCalc>true</IsForcedCalc>

	<!-- 最小墙段长度（米），过滤极短墙段 -->
	<MinimumWallLength>0.1</MinimumWallLength>
	<!-- 每条射线最大传播分支数 -->
	<MaxRayNumber>8</MaxRayNumber>
	<!-- 最大衍射次数 -->
	<MaxDiffraction>2</MaxDiffraction>
	<!-- 最大反射次数 -->
	<MaxReflection>4</MaxReflection>
	<!-- 最大穿透次数（墙体/门窗） -->
	<MaxPenetration>2</MaxPenetration>
	<!-- 最大传播深度（反射+衍射+穿透累计） -->
	<MaxDeepth>6</MaxDeepth>

	<!-- ==================== 计算范围与精度 ==================== -->

	<!-- 室内精度一般用 0.2（默认 1 太粗，见 如何跑室内.md） -->
	<DefaultCalcRadius>800</DefaultCalcRadius>
	<DefaultCalcResolution>0.2</DefaultCalcResolution>
	<DefaultAngleRes>1</DefaultAngleRes>
	<DefaultUEHeight>1.5</DefaultUEHeight>
	<AntGainCalced>true</AntGainCalced>

	<!-- ==================== 室内接收功率/信噪比缩放因子 ==================== -->

	<IndoorRxPowerSF>10</IndoorRxPowerSF>
	<IndoorSinrSF>2</IndoorSinrSF>

	<!-- ==================== 室内外通用判定阈值 ==================== -->

	<MicroThreshold>0.25</MicroThreshold>
	<MacroThreshold>0.9</MacroThreshold>
	<MicroMaxRadius>500</MicroMaxRadius>
	<MacroMinAntHeight>15</MacroMinAntHeight>
	<EdgeDistanceOfMerged>10</EdgeDistanceOfMerged>
	<DistanceOfVirtualSource>500</DistanceOfVirtualSource>
	<PeneLossMode>0</PeneLossMode>
	<UsingBuildingPolygon>true</UsingBuildingPolygon>
	<RoofOrGround>Ground</RoofOrGround>
	<MaxPower>200</MaxPower>
	<MinPower>1</MinPower>
	<MaxDistance>900</MaxDistance>
	<MinDistance>1</MinDistance>
	<Max_Error>0.01</Max_Error>
	<Epoch>20</Epoch>
	<Distlimit>0.2</Distlimit>

	<!-- ==================== 传播模型校正（-f cali 用） ==================== -->

	<DriverTestFileDictionaryPath>${DT_ROOT}</DriverTestFileDictionaryPath>
	<CorModelName>test</CorModelName>
	<IsCorrect_Los_K0andKnear>true</IsCorrect_Los_K0andKnear>
	<IsCorrect_Los_Kfar>true</IsCorrect_Los_Kfar>
	<IsCorrect_nLos_K0andKnear>true</IsCorrect_nLos_K0andKnear>
	<IsCorrect_nLos_Kfar>true</IsCorrect_nLos_Kfar>
	<IsCorrectDiffraction>true</IsCorrectDiffraction>
	<IsCorrectReflection>true</IsCorrectReflection>

	<!-- ==================== 自动参数优化（-f acp 用） ==================== -->

	<ACP_Algorithm>0</ACP_Algorithm>
	<IsOptRSRPandSINR>true</IsOptRSRPandSINR>
	<IsOptRSRP>true</IsOptRSRP>
	<RSRP_Weight>1</RSRP_Weight>
	<RSRPThreshold>-89</RSRPThreshold>
	<IsOptSINR>false</IsOptSINR>
	<SINR_Weight>0</SINR_Weight>
	<SINRThreshold>-3</SINRThreshold>
	<IsOptEleTilt>true</IsOptEleTilt>
	<IsOptAzimuth>true</IsOptAzimuth>
	<IsOptRsPower>false</IsOptRsPower>
	<IsOptMecTilt>false</IsOptMecTilt>
	<IsOptOutdoor>true</IsOptOutdoor>
	<IsOptIndoor>false</IsOptIndoor>
	<MaxEleTilt>6</MaxEleTilt>
	<MinEleTilt>0</MinEleTilt>
	<MaxAdjustableEleTilt>6</MaxAdjustableEleTilt>
	<MaxAdjustableAzimuth>60</MaxAdjustableAzimuth>
	<MaxRSPower>15.2</MaxRSPower>
	<MinRSPower>13</MinRSPower>
	<MaxAdjustableRSPower>9</MaxAdjustableRSPower>
	<MaxMecTilt>15</MaxMecTilt>
	<MinMecTilt>0</MinMecTilt>
	<MaxAdjustableMecTilt>5</MaxAdjustableMecTilt>
	<RaysCache>1000</RaysCache>
	<CellPLCache>1000</CellPLCache>
	<PopulationSize>15</PopulationSize>
	<SpeedRatio>0.2</SpeedRatio>
	<IntertiaFactor>0.8</IntertiaFactor>
	<SelfLearnFactor>2</SelfLearnFactor>
	<GroupLearnFactor>2</GroupLearnFactor>
	<MaxIter>60</MaxIter>
	<MinError>0</MinError>

</RuntimeSchema>
