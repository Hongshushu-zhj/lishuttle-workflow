# P0 结果校验实现报告

实现文件：`platform/backend/result_validation.py`。测试文件：`tests/test_result_validation.py`。

## 已实现行为

- `snapshot(context)` 在启动前记录最终产物的绝对路径、字节数、纳秒修改时间和流式 SHA256；只检查预测 DEM/索引、小区映射、校正报告/锚点、模型 XML 等结果文件，不读取共享旧日志或批量扫描实测输入 CSV 内容。
- `validate(context, baseline, lines, exit_code, cancelled=False)` 分离进程状态、产物完整性、业务结果和最终判定。保留 `files/dir/exists/log_tail/errors`，提供 `process.exit` 和 `process.exit_code`，返回值可 JSON 序列化。所有检查为只读。
- `pred` 检查 RSRP、DLRSSINR、BESTSERVER；`commsensing` 检查 ECHORP、SCR 及当前格式的小区映射，不要求 BSINTF。按 UTM+文件名+边界+分辨率索引计算行列数，核对两字节小端 int16 长度，统计有效值、-32768 无效值、最小/最大值及 BESTSERVER 映射错误。
- 地面模式忽略历史高层目录。3d 使用实际 `floor(H/h)+1` 层与源代码高度目录命名规则，不生成非整倍数末层。建筑楼层按已计算区域观察其实际栈，只要求该区域已出现最高层之下的连续层；不把其他区域最高楼层机械套到未计算区域。允许建筑上层全部为无效值。
- `predindoor` 以 DAS/AP 楼层元数据检查 RSRP_<floor> 与 DLRSSINR_<floor> 配对，核对配套网格。明确区分当前文件名索引和旧版单行五数值室内索引；仅 ILS 缓存不能证明预测完成。
- 每个必需最终 DEM 都独立要求新建/内容变化；旧索引和小区映射仅可作为与当前新结果一致的辅助资料。修改时间变化、全任务 Finished 行、单个新指标不能使旧配套指标成为本次结果。
- `cali` 从调用方传入的本次 `Calibration site(...): grid count=..., success=Y/N, update=Y/N, code=0x...` 逐站日志分别统计求解成功、失败、更新、未更新和原始代码，不从旧合并 CSV 推断本次数量。根据当前逐小区报告、DT 锚点和条件模型保存证据给出 success/partial/no_update/failed/unconfirmed。
- 校正站点更新需要实际目标目录 `cells` 中内容变化的模型 XML；场景报告有结果时需要对应 `scenes/SceneModel.xml` 的保存证据。`ModelTemporaryStorage` 对应的 `models_dir` 可以是输出目录下 `models_task<id>` 或 Bin/models，验证器不会改写配置。
- 模型 XML 支持 TinyXML 的多个根节点片段。场景报告按设置检查；场景报告仅表头时不强求场景模型；CorrectionMeanVariance.xml 只在出现本次变化时检查，不因其缺失断言失败。
- 未知功能、未知索引格式、缺少实际楼层/模式/基线信息、旧文件无法归属本次、仅有地面结果而无法确认建筑楼层适用性，均不能自动判为成功。异常、取消、非零进程退出不能成为完整成功。

## 测试证据

采用测试先行：首次运行 26 个测试均因模块未实现而产生预期断言失败，再实现至通过；后续行为缺口先增加失败测试再修复。

最终聚焦命令：`python -m unittest discover -s tests -p test_result_validation.py`，39 个测试通过，退出码 0。覆盖当前/历史产物、同大小改写、mtime-only、逐指标归属、地面旧高层隔离、3d 非整倍数、建筑稀疏区域与中间层、室内两种索引、维度/哨兵/小区映射、超过 1 MiB 的流式统计、校正部分成功/未更新/失败、条件报告、两种模型保存位置、多个根 XML 和未知元数据。

## 证据依据与限制

只读参考活动源目录 `D:/workspace/LAB/Lab20261013` 中 Prediction 的 IndicatorCalcSuite/BinCalcCase/CubeCalcCase/IndoorCalcCase、Propagation 的 PMCorrectionEngine/CorrectCalculator/CellCorrectionData/PropagationModelFactory，以及 SwanUtility 的楼层目录格式和 ThirdPart 的 GeoRasterRect 行列计算。逐站日志 Y/N 及十六进制代码格式直接对应 CorrectCalculator.cpp 378–383 行。另只读观察已有旧版室内五数值索引以确认格式差异。

未运行实际引擎，未改动真实项目数据、引擎源代码或其他代理拥有的实现文件，未提交版本。文件完整性检查不能替代无线传播结果的物理准确性验收。无法由元数据推断的建筑区域层数会保守保留为 unconfirmed；结构正确但确定性重算生成完全相同内容的最终文件，也不会仅因完成日志或时间戳变化而自动归属本次。旧版室内索引只有在已有实际楼层元数据及两类最终文件可校验时才可确认。校正日志按站点统计，逐小区模型/报告属于不同统计粒度，不强行把两者数量等同。

## 审查修复追加记录（本节取代上文已修正的行为说明）

已读取 `validation-review.md`，复现其中五项 Important，并以失败回归测试覆盖后修复。测试上下文现使用实际契约：`schema_name='different-config.xml'`、`task_name='demo'`，不再以人工相同名称隐藏报告前缀差异。

1. **报告身份和基线**：报告查找与启动前基线均使用 `task_name`，不使用 XML 文件名；缺少真实任务名保留 unconfirmed。
2. **通用模型求解与保存**：分别识别 `The calibration of the general model completed!/failed!`、`No enough data for general model calibration:`，以及 common/propagation model 的保存失败。按 `CalNewModelName` 验证变化后的模型 XML 身份。保存文件名遵循 factory 的实际选择：从运行前 Bin/models 顶层 XML 候选继承文件名，无候选时为 LiShuttleModel.xml；不假定某个城市或任意固定文件。候选次序不属于稳定合同，通过当前变化文件及模型身份确认，不伪造目录枚举顺序。
3. **模型类别分别统计**：新增 `business.model_kinds.cells/general/scenes`，每类固定包含 `status/processed/succeeded/updated/skipped/failed/unit/reason/items`，items 为对象数组。cells 的单位是 site_groups，general 是 models，scenes 是 scenes；保留原有 `total/succeeded/updated/no_update/sites` 为逐站日志兼容统计。`business.counts.unit='model_kinds'`，其数量只表示具有相应结果的模型类别数，不混加站点组、模型个数和场景个数。站点没有更新但通用/场景模型确认更新时不再误报 no_update；已确认更新与其他类别明确失败并存时为 partial。若模型类别保存证据未知，仍保留 unconfirmed。单类求解成功但保存失败不能冒充另一类成功；取消和非零退出继续覆盖全局判定。
4. **建筑模式范围**：读取 `layer_cap/configured_layer_count`，必要时由配置高度和步长推导上限；实际 `layer_count=None` 不再误当矩形全栈缺失。仅本次内容变化的适用层产物可扩展该区域的要求，范围内和范围外旧高层目录均不能扩展当前栈。当前确实已出现的高层仍要求该区域连续中间层，以及逐指标本次归属。忽略的旧文件也不混入当前 files 列表。
5. **历史模型隔离**：先按适用类别、实际文件位置、变化指纹和模型身份筛选，再解析当前候选 XML。未变化、不相关的历史坏模型不会使健康的当前结果失败。当前必需模型 XML 无效仍被记录；若其他类别已有确认更新，明确模型类别失败可保留 partial，报告/清洗网格等共同必需产物损坏仍是全局失败。

附加验收也已实现：3d 先检查同一区域全部必查 base 指标，全部为 sentinel 时标记 EMPTY_REGION/unconfirmed，不要求没有参与而未懒扩的完整上层立方体；只空 BESTSERVER 而 RSRP 等有效时继续判为不一致、失败，不能绕过上层校验。明确的 `No cells have been choosed to this predication` 记录定位为无参与小区，不制造整套缺层诊断。BESTSERVER 编号 0 仍按源码视为无效。

**clean_grids.csv 能力边界**：当前已审查源的 `isUpdateDtFiles` 构造默认 true，未发现 XML 赋值开关，因此未发明 XML 开关。若调用方确有可信能力信息 `context.result_capabilities.clean_grids=true`，缺少该最终报告会明确失败。当前服务没有可信的二进制能力注册机制，不能因项目存在这份源码就认定 exe 同版；默认未知版本缺失该文件时，以完整 clean_grids.csv 路径及 CLEAN_GRIDS_CAPABILITY_UNKNOWN 记录 unconfirmed。发现已核实格式的文件时，逐行读取校验其本次内容变化、源码表头、非空数据、时间/小区编号及有限经纬度/RSRP；接受源码 sizeof(header) 在 Windows 表头中写入的 NUL 终止字符。meas.anchor 仍只是辅助中间证据，不能单独证明最终成功。

**追加只读源码依据**：CorrectCalculator.cpp 的 general 校正（412–451）、scene 完成/失败及无足够数据（194–288）；PMCorrectionEngine.cpp 的 SaveCommonModel（300–324）及清洗网格保存（190–195）；PropagationModelFactory.cpp 的输入顶层 XML 选择及输出文件名继承（184–246）；LiShuttleSceneModel.cpp 的条件保存与失败日志（699–749）；CalibrationParams.h 的 clean_grids 表头/格式及 isUpdateDtFiles=true 初始化；PMCorrectionData.cpp 的清洗网格序列化（218–235）；IndicatorCalcSuite.cpp 的分区域交集、层数上限与延迟扩层调用（409 起）；Prediction/src/BestServer.cpp 的编号 0 转无效 sentinel（40 起）。均未修改或执行引擎。

**追加验证证据**：初始新回归使 60 项测试中的 30 项出现预期失败（包含修正真实上下文后暴露的旧测试）；分批修复后，新增派生 3d 上限、过期 files 列表、稳定类别字段的回归再得到 3 项预期失败；随后 65 项聚焦测试通过。最终命令及结果：

- `python -m unittest discover -s tests -p test_result_validation.py`：65 tests，OK，退出码 0。
- `python -m unittest discover -s tests -p test_runtime_lifecycle.py`：9 tests，OK，退出码 0。
- `python -m unittest discover -s tests -p test_preflight.py`：61 tests，OK，退出码 0。
- `python -m py_compile platform/backend/result_validation.py tests/test_result_validation.py`：退出码 0。

本轮只改结果验证模块、其测试及本报告，未提交、未运行引擎、未改变真实项目数据。求解日志数量与持久化模型类别数量明确分开；未能从当前证据建立身份或归属的项目仍不宣称更新成功。

## 最终审查 F1–F3 修复追加记录

已按 `validation-final-review.md` 的三项 Important 增加失败回归，并完成以下修复：

1. **F1，逐对象保存归属**：`snapshot()` 将可信预检提供的 `engineering.records` 固定为基线中的 `engineering_records`，分别保留 `site_name/transceiver_name/cell_id`。验证仅使用该启动前映射，按站点日志 → 当前变化 summary 中 `cell=transceiver_name` 且 `update=yes` 的唯一记录 → 当前有效 cells XML 中 `ModelName=cell_id` 建立证据链。某站点全部预期对象均已保存才增加该类的 `updated`，同时返回 `verified_objects/expected_objects` 和已核实子集；原始日志计数独立保留。缺映射、映射歧义、启动后上下文漂移、summary 未变化或对象保存不全均不能确认所有更新。不同物理站点组可重用文字站名，故逐条保存原始事件、暴露 `duplicate_site_names`，遇到这种歧义保持 unconfirmed。旧基线缺少身份映射时不能用执行后上下文追补，声称 cells 更新仍保持 unconfirmed。
2. **F2，真实模型格式**：cells/general/scenes 的正例已换为源码兼容的最小多根 XML，验证兄弟根 `ModelVersion`、`PropagationCategory name="LiShuttleModel"`、非负 int32 `Model ID`、唯一 ID/模型名及六个必需有限系数 `K0/Knear/Kfar/K0_nlos/Knear_nlos/Kfar_nlos`，并限制为有限 float32 范围。cells/general 识别版本 0，scenes 识别版本 1，场景还检查非空 Frequency/City/Features。可选训练组出现时，校验 dataSize、有限标量及长度为 4/4/10 的向量；源码允许其缺省，不额外强制生成。已知格式损坏记录 MODEL_STRUCTURE 并归属模型类别；不支持的结构/版本分别保持 MODEL_FORMAT_UNKNOWN/MODEL_VERSION_UNKNOWN 和 unconfirmed。多根 XML 及非模型诊断 XML 的通用解析仍保留，只有 ModelName 的任意 XML 不再成为模型成功证据。
3. **F3，类别完整性错误**：模型的空文件、读取失败和 XML 损坏均保留 `model_kind` 并返回无效候选。新建或可观察修改的不可读模型进入相同错误路径，未变化的历史不可读文件仍被隔离。这样 cells 失败而 general 已确认更新，或 general 为空而 cells 已确认保存时，最终保留 partial；共同必需的报告/清洗网格损坏仍按全局失败处理。

**只读源码依据**：`CellLoader.cpp:1017/1138` 分别读取 siteName 和设置普通 CSV 分支的 transceiver.name，`1153` 起按物理位置建站，允许文字站名复用；`CorrectCalculator.cpp:307–308/341–351` 分别取日志站名和保存模型 cellID；`CellCorrectionData.cpp:175–184` 的 summary 首列来自 transceiver.name，model_id 不能代替这三个身份域。`PropagationModel.cpp:56–66` 规定整数模型 ID；`LiShuttlePropagationModel.cpp:170–210/283–304` 规定类别与六系数；`LiShuttleCellModel.cpp:234–253/279–295` 规定保存类别与版本 0；`LiShuttleSceneModel.cpp:12/666–729` 规定版本 1 与保存格式；`LiShuttleSceneSubModel.cpp:183–220` 规定场景字段和训练组；`CalibrationParams.h:179/224–295` 规定四维变量及训练统计布局。以上均来自活动源目录 `D:/workspace/LAB/Lab20261013`，未修改或执行。

**测试先行证据**：替换真实正例并新增 15 项回归后，80 项测试出现 13 项预期失败；修复后 80 项通过。再增加未变化 summary、重复站名、空 general 三项回归，83 项中出现 2 项预期失败；补齐后 83 项通过。覆盖三种身份互不相同、保存子集、旧基线、执行后映射变化、结构/版本/ID/有限系数、场景字段、空与不可读模型以及跨类别 partial。

**本次完成前重新验证**：

- `python -m unittest discover -s tests -p test_result_validation.py`：83 tests，OK，退出码 0。
- `python -m unittest discover -s tests -p test_runtime_lifecycle.py`：10 tests，OK，退出码 0。
- `python -m py_compile platform/backend/result_validation.py tests/test_result_validation.py`：退出码 0。
- 前一轮预检为 70 tests，OK；共享工作区随后新增测试，本次重跑 `test_preflight.py` 为 72 tests、2 failures，退出码 1。失败分别为 `test_dt_correction_anchor_is_conditional_and_does_not_require_raw_dt_index` 缺 DT_ANCHOR_REQUIRED、`test_prediction_selection_file_is_checked_only_when_requested` 缺 PREDICTED_CELLS_REQUIRED，实际均仅有 RUNTIME_RESOURCES_UNCONFIRMED。已告知主任务处理，未改动其负责的预检实现或测试。

本轮修改范围仍仅为结果验证模块、其测试及本报告；未运行真实引擎，未改动真实项目数据，未提交。

## 通用模型历史集合兼容性追加修复

最终复核发现上节 F2 的“唯一模型名”约束对 general 过严：`Propagation/Frame/src/PMCorrectionEngine.cpp:315–317` 以 `overwrite=false` 保存通用模型，`LiShuttlePropagationModel.cpp:307–347` 只在 overwrite 且 ID 相同时替换，否则分配 max ID + 1 后追加，并未按 ModelName 去重；factory 也按类别和 ID 建立模型索引。因此同名但不同 ID 的历史 general 模型集合是合法保存结果。

已先增加回归：真实格式、同名 general、ID 1/2 的模型集合被误判 partial，86 项中 1 项出现预期失败。随后仅放宽 general 的 ModelName 重复约束，所有类别仍拒绝重复 ID，并保留完整结构、版本与有限系数校验。另增加不同名重复 ID 的 general 负例，以及 cells/scenes 同名对象不能绕过身份检查的回归；后两类没有独立核实的合法同名保存依据，未随 general 一并放宽。已与复核代理确认源码结论。

修复后 `python -m unittest discover -s tests -p test_result_validation.py`：86 tests，OK，退出码 0；`python -m py_compile platform/backend/result_validation.py tests/test_result_validation.py`：退出码 0。仅修改验证器、其测试和本报告，未运行引擎、改真实数据或提交。

**通用模型明细状态一致性**：复核指出不支持的 XML 格式/版本虽然使类别和全局保持 unconfirmed，general.items 却仍显示 success。先在任意具名 XML 与未知版本回归中增加明细断言，86 项中出现 2 项预期失败；再使明细按无效→failed、格式/版本或名称身份未确认→unconfirmed、已确认名称匹配→success 赋值，同时为未确认项提供准确原因。聚合逻辑未改变。修复后聚焦 86 tests，OK；py_compile 退出码 0。
