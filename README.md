# LiShuttle 本地运行平台

在 Windows 浏览器中选择地图和任务、修改运行参数和工参 CSV、编译并运行 LiShuttle、查看结果和日志。

后端使用 Python 标准库，前端是原生 HTML/CSS/JavaScript，不需要 Node.js、npm 或额外 pip 包。本教程只介绍 Windows 本地运行。

**本仓库不包含 LiShuttle C++ 引擎源码、第三方库、地图和真实任务数据。** 使用者需要单独取得这些资源并配置本机路径，才能完成计算。配置模板中的路径只是示例。

首次 clone 后按以下顺序操作：

1. 安装 Python 和 Windows C++ 工具链，取得独立的 LiShuttle 引擎项目、完整 ThirdPart 资源及业务数据（第 1～2 节）。
2. 双击 `启动平台.bat`：首次打开会自动查找并保存本机工具链，供所有引擎项目复用；添加引擎项目后，在“项目配置”确认其预设与数据路径（第 3 节）。也可先运行自动配置命令，无需手工找工具位置。
3. 执行体检，缺少 exe 时编译（第 4 节）。
4. 启动平台，选择项目、地图、任务和功能，装配、调整参数，再运行并检查结果（第 5～6 节）。网页装配会一并补齐基础运行资源。

换电脑不需要沿用原作者的盘符或 `Lab+日期` 项目名称；但目前支持的是符合约定目录结构的 Windows 本地环境。可配置路径与需要改代码才能适配的限制见第 10 节。

## 1. 准备环境和数据

推荐 Windows 10/11（64 位）和 Python 3.13（当前开发环境版本）。其他 Python 3 版本尚未逐一验证。

| 必需内容 | 检查方式 |
| --- | --- |
| Python 3 | 安装时勾选加入 PATH；终端执行 `python --version` 显示 Python 3 的版本 |
| LiShuttle C++ 项目 | 根目录包含 `CMakeLists.txt`、`LiShuttle/`、`SwanUtility/incl/LiShuttleTypes.h`；编译还需可用的 `CMakePresets.json` |
| 第三方库 | 包含引擎所需的 `ThirdPart/Lib`、Windows DLL 等文件 |
| 运行配置 | `ThirdPart/Config` 内有运行单、场景、天线、模型、日志及签名配置 |
| 业务数据 | 与引擎版本和功能匹配的地图、工参、区域等数据 |
| 编译工具 | VS2022 或对应 Build Tools，安装“使用 C++ 的桌面开发”、项目需要的 Windows SDK、C++ CMake 工具和 Ninja |

引擎项目、第三方库和业务数据请向项目维护者获取，仓库中的示例任务单不附带实际数据。若已有可运行的 Windows 构建产物，可以跳过编译，但仍需完整的依赖和运行配置。

配置源中必须有完整样例 `CONFIG_SRC/runtimelibrary/runtimeschema.xml`，用于生成运行单和读取默认值。DLL 需要与 exe 的架构、Debug/Release 配置及引擎版本匹配。引擎自己的 CMake 预设、第三方依赖路径也必须适用于本机，平台不会自动修复引擎构建文件。

把工作目录放在自己有写入权限的位置。现有批处理使用 GBK 代码页，首次使用建议采用简单的英文路径，避免 `!`、`%` 等特殊字符。

## 2. 下载并打开仓库

在 GitHub 仓库页面点击 **Code → Download ZIP**，解压并打开包含本 README 的文件夹；也可以复制该页面的 HTTPS clone 地址，使用 `git clone` 下载。

在资源管理器中打开仓库根目录，在地址栏输入 `powershell` 并回车。以下命令都在这个终端中执行。

```text
lishuttle-workflow/
├─ README.md
├─ 启动平台.bat
├─ 停止平台.bat
├─ env/local-win.env.example
├─ jobs/example-*.env
├─ platform/backend/
├─ platform/frontend/
├─ scripts/
└─ templates/
```

## 3. 快速配置本机与项目

### 推荐：自动搜索工具，一台电脑配置一次

首次 clone 后，安装第 1 节的工具，再双击 `启动平台.bat`。网页首次加载时会查找本机工具，**将已验证且尚未配置的工具地址直接保存**；以后添加或切换引擎项目都复用，不必再填一遍。

也可以先在仓库根目录运行，无需先登记引擎项目：

```powershell
python .\scripts\project_config.py --setup-machine
python .\scripts\project_config.py --show-machine
```

第一条搜索并保存空缺项，第二条显示当前全局值。工具查找顺序是 VS Installer 的 `vswhere.exe` 注册信息、常见 VS 安装目录文件检查、系统 `PATH` 中的 CMake/Ninja；VS 安装在自定义盘符时，优先通过注册信息定位。只接纳实际存在的目录/程序，优先组合同一套 VS 内的 CMake、Ninja 和 `vcvars64.bat`，不会执行引擎 CMake 文件，也不会自动安装软件或修改系统 PATH。

| 配置范围 | 配置项 | 使用方式 |
| --- | --- | --- |
| 本机全局 | `VS_ROOT`、`CMAKE`、`NINJA`、`VCVARS` | 自动搜索后直接保存；所有引擎项目和本地脚本共用 |
| 每个引擎项目 | 构建模式/预设、`CONFIG_SRC`、`DLL_SRC` | 选择 Debug/Release 后自动派生构建/安装目录、程序名；确认资源后保存 |
| 每个项目的数据 | `MAP_ROOT`、`GONGCAN_ROOT`、`OUT_ROOT`、`DT_ROOT` | 按真实业务数据选择，可显式指向共享目录 |

这里的“全局”指**本机这份平台仓库管理的所有引擎项目**，不是 Windows 系统设置，也不跨其他 clone 自动同步。配置保存在被 Git 忽略的 `env/project-profiles.json` 中：全局工具在顶层 `machine.values`，项目配置在 `profiles.<项目ID>.values`。换电脑请重新 clone 并自动检测，不要复制另一台电脑的本机配置或快照。

顶部“本机工具链（全局）”可查看当前值和下拉候选。点击“自动检测并保存本机工具链”会重新搜索并补齐空缺；已经保存的自定义值保持不变。需要改用另一套工具时，选择候选或切换“手动填写”，然后点击“保存本机工具链”，立即对所有项目生效。改变全局配置会让旧页面修订失效，其他已打开页面需要刷新；已经启动的命令继续使用启动时的配置快照。

**没有找到工具时：** 检查 Python 是否已加入 PATH；VS Installer 中确认安装了 C++ 桌面开发、MSVC x64/x86、Windows SDK、C++ CMake 工具。若某项仍为空，安装后重新检测，或指定真实文件位置：

```powershell
# 示例路径必须替换为本机实际安装位置；路径含空格时保留整段引号。
python .\scripts\project_config.py --set-machine "VS_ROOT=C:/Program Files/Microsoft Visual Studio/2022/Community" --set-machine "CMAKE=C:/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe" --set-machine "NINJA=C:/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe" --set-machine "VCVARS=C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat"
```

手动保存只做配置文本校验，请用 `Test-Path` 或“体检”确认文件存在。VS 卸载/迁移或误拷贝了旧电脑配置时，可在网页改正；也可以先清空旧工具地址，再自动查找，避免“已有值保留”阻止更新：

```powershell
python .\scripts\project_config.py --set-machine "VS_ROOT=" --set-machine "CMAKE=" --set-machine "NINJA=" --set-machine "VCVARS=" --setup-machine
```

工具配置正确后添加引擎项目。自动检测无法提供尚未取得的地图、任务包、ThirdPart 或源码，业务资源仍需自行准备。

### 本地项目档案与切换

网页、渲染器和本地 Windows 脚本共同读取 `env/project-profiles.json`，运行时合并本机全局工具链和所选项目配置。每个项目独立保存构建预设、构建/安装目录、exe 名、配置/DLL 源目录及地图、工参、路测、输出根目录；切换 A→B→A 会恢复各自项目配置，并复用同一份本机工具链。没有旧 env 时也可以在网页添加首个项目。

打开或切换项目时，网页会自动检测并填充尚未配置的项目字段：读取本项目的 `CMakePresets.json` / `CMakeUserPresets.json`（含继承和 include），优先选用已有可执行文件的 Windows x64 Ninja 预设；从项目内容识别程序名、配置源和 DLL 目录。地图、工参、输出和路测目录只列出实际存在的约定目录，包括明确标注的同级共享候选；多个业务目录需下拉选择，未找到则说明原因并允许手动填写，不会编造路径。

“项目配置”直接显示检测值和每项来源，候选可下拉选择或切换手动填写。通过上方 Debug/Release 和项目预设选择构建配置，自动派生构建/安装目录、程序名和匹配的 DLL 目录，不再手填这些构建字段。自定义 DLL 目录仍保留。已保存的项目配置和本次手动输入不会被重新检测覆盖，也不会继承其他项目档案。**项目检测结果是草稿，点击“保存当前项目配置”后生效；本机工具链自动检测则直接保存。**

升级已有配置时：旧 `env/local-win.env` 首次导入前备份为 `local-win.env.profiles.bak`；旧版项目工具链首次升级前备份整个档案为 `project-profiles.json.machine.bak`。迁移使用当前活动项目的工具配置作为全局起点，不拼接其他项目的工具值，其余项目原来的工具值可从备份查看。旧 env、原有备份及任务数据保持不变。**导入后请用网页或上述命令修改；继续编辑旧 env 不会覆盖档案。** 本机配置、备份及快照不提交 Git。配置源与 DLL 源可以是相对项目路径，也可以是本机绝对路径；构建/安装目录沿用相对项目的目录约定。

仅在需要兼容旧入口时，才从 `env/local-win.env.example` 复制 `env/local-win.env` 作为首次导入来源；新安装推荐自动配置，无需复制模板。首次导入前若 env 已存在，不要重新复制覆盖；文件使用 UTF-8、`KEY="VALUE"` 和正斜杠路径。

一次网页请求固定配置；渲染和工具子进程使用 `env/snapshots/` 中按内容摘要保存的快照。本地 `doctor/build/stage/run` 入口通过 `scripts/load_local_env.bat` 在开始时固定快照，后续网页切项目不会改变已启动命令的配置。旧页面修订号不符会被拒绝，需刷新。独立的 `server` target 未纳入此次适配。

直接使用 Python 时可明确选择已登记项目，不改变网页当前选择：

```powershell
python scripts/render_schema.py --print-env local-win --project "D:/LiShuttle/项目A"
python scripts/render_schema.py jobs/<项目ID>/web-demo.env local-win --project "D:/LiShuttle/项目A"
```

网页生成的任务单带项目标识，不能在另一个项目下直接复跑。本地批处理会明确拒绝包含 `!` 的配置/路径，避免 Windows 延迟展开吞字符；该情况下请调整路径，或使用 Python 渲染入口并直接启动引擎。中文和空格路径有独立的 Windows 批处理回归覆盖。

### 交给 AI 的提示词

自动搜索通常比让 AI 猜工具位置更快。若仍有缺项，把本仓库交给能读取本机文件并执行终端命令的 AI 编程助手，提供引擎项目、地图和任务包位置，再复制以下提示词：

```text
请根据 README 第 3 节配置这台 Windows 电脑上的 lishuttle-workflow。
LiShuttle C++ 项目、地图和任务包的位置由我提供；缺少位置时先问我。

1. 检查 python --version，确认 python 指向 Python 3。
2. 先运行 python scripts/project_config.py --setup-machine，再运行
   python scripts/project_config.py --show-machine。优先用程序自动搜索，
   不要先猜 VS/CMake/Ninja 路径，不要覆盖现有配置。
3. 若工具仍为空，检查 VS Installer 注册信息、安装组件和 PATH；找到后用
   Test-Path 验证，再通过 --set-machine "KEY=真实路径" 保存。
   VS_ROOT、CMAKE、NINJA、VCVARS 是全局项，只配置一次，不写入每个项目。
   不安装或下载软件；未安装时列出缺少的组件。
4. 读取我提供的项目 CMakePresets.json 及引用的预设文件，确认 Windows
   预设名、生成器、binaryDir、installDir，通过网页选择 Debug/Release 及真实预设，
   让平台派生 PRESET、BUILD_SUBDIR、INSTALL_SUBDIR，不要求手填不存在的构建目录。
   当前脚本在 PROJECT_DIR/BUILD_SUBDIR/Bin/EXE_NAME 找 exe，
   BUILD_SUBDIR 必须是项目内相对目录；预设布局不兼容时说明原因。
5. 检查 CONFIG_SRC、DLL_SRC 和第三方库，确保 DLL 与构建配置匹配。
6. 根据真实数据位置填写 MAP_ROOT、GONGCAN_ROOT、OUT_ROOT；DT_ROOT 仅路测相关功能需要。
   只有用户确认的输出/工作目录可以创建，不伪造地图、工参或第三方库。
7. 通过网页“添加项目”“项目配置”保存项目字段。若必须直接修改配置文件，
   先备份 env/project-profiles.json，使用 UTF-8 JSON，保留所有未知字段、
   项目ID和任务绑定；全局字段仅在 machine.values，项目字段在
   profiles.<项目ID>.values。不要改旧 local-win.env 期待覆盖已导入档案。
   修改全局字段时递增 machine.revision 及所有 profiles 的 revision；
   修改某项目字段时递增该项目 revision，修改后刷新网页。
8. 执行 python scripts/render_schema.py --print-env local-win 和
   scripts/doctor_local.bat，阅读完整输出。体检退出码 0 不代表所有检查通过。
9. 报告检查结果、仍缺少的资源及下一步编译和装配操作。

只配置本地模式，不设置 SSH 或服务器，不修改引擎源码或原始任务数据。
不要覆盖已有自定义值、清空构建目录、修改引擎源码或执行实际计算。
```

只能聊天的 AI 无法自动发现本机路径，需要向它提供模板、项目预设和实际目录，再自行核对生成的配置。

### 配置项对照

| 配置项 | 含义 |
| --- | --- |
| `PROJECT_DIR` | 引擎项目的绝对路径，不是平台目录；该目录及其父目录必须存在 |
| `PRESET` | 真实的 Windows CMake 预设名，示例为 `x64-release` |
| `BUILD_SUBDIR` | 自动取所选预设的 `binaryDir`，相对于引擎项目；首次编译由 CMake 创建，网页无需填写 |
| `INSTALL_SUBDIR` | 自动读取预设的安装目录；可选，默认从构建树运行，不需要安装 |
| `EXE_NAME` | 内部运行元数据，自动读取 CMake 主程序目标或 `Bin/` 下的真实产物，网页无需填写 |
| `VS_ROOT` | 本机全局：VS2022/Build Tools 实际安装根目录 |
| `CMAKE`、`NINJA`、`VCVARS` | 本机全局：工具文件的绝对路径，不是文件夹路径 |
| `CONFIG_SRC` | 相对项目目录的配置源，通常为 `ThirdPart/Config` |
| `DLL_SRC` | 相对项目目录的 DLL 源，通常为 `ThirdPart/Dll/Release`；需匹配构建配置 |
| `MAP_ROOT` | 地图根目录，每个子文件夹是一座城市或室内场景 |
| `GONGCAN_ROOT` | 本地工参任务根目录，每个子文件夹是一份任务包；CLI 任务引用包内的具体输入文件 |
| `OUT_ROOT` | 可写的结果根目录，通常按任务名存放计算产物 |
| `DT_ROOT` | 可选：仅路测、校正等相关功能需要的数据目录 |

平台不自动登记父目录中的其他引擎项目。顶部点击“添加项目”，输入项目根目录，通过验证后加入本机列表并切换。目录名称不限，以 `CMakeLists.txt`、`LiShuttle/`、`SwanUtility/incl/LiShuttleTypes.h` 组合识别；缺少构建预设或完整运行样例时给出提示。本机列表保存于 `env/projects.json`（不提交 Git），升级前已配置的当前项目会保留。切换时刷新功能、地图和任务列表，并清空旧项目的参数与运行状态；工具链复用本机全局配置，预设与数据根恢复对应项目配置。

配置后创建缺失的输出和工作目录，例如 `OUT_ROOT`。不要用空文件夹替代真实地图或依赖。

### 新项目按顺序操作

网页顶部会持续显示操作指南，点击步骤可直接定位对应位置：

1. **添加并选择本地项目**：输入引擎源码根目录。
2. **确认本机工具链**：自动搜索并保存，所有项目复用；缺少工具时先安装并重新检测。
3. **选择 Debug / Release → 编译所选配置**：下拉框列出项目实际兼容的 Windows x64 Ninja 预设；Release 包含 RelWithDebInfo/MinSizeRel。没有预设时检查项目的 CMakePresets.json。平台先保存所选预设及派生目录，再调用 MSVC、CMake、Ninja；不依赖地图或输出目录已配置。
4. **确认并保存项目资源**：CONFIG_SRC、DLL_SRC、MAP_ROOT、GONGCAN_ROOT、OUT_ROOT 必需；DT_ROOT 仅路测相关功能需要。CLI 工参目录已移除，旧值迁移前备份到 project-profiles.json.retired-fields.bak；输入文件直接来自任务包或明确文件路径。
5. **选地图、工参 CSV、已有 XML（如使用）**：确认本地路径和区域文件，可保存任务与地图对应关系。
6. **装配并渲染 → 确认预览 → 运行**：缺少必填项时，网页展开对应设置、滚动并聚焦到该项，显示缺失原因；填写后保存再重试。

构建路径会在编译前显示为“尚未生成”，只有目录实际存在才显示“已生成”；程序名来自 CMake 目标和构建产物，编译结束后重新识别。目录存在不代表编译成功，请检查运行页的退出码及日志。Debug 与 Release 分别使用各自预设目录和匹配 DLL，不会清空已有构建目录。切换配置后旧运行单失效，需要重新装配。项目要求在 `<binaryDir>/Bin/` 输出主程序；无法明确识别主程序时，检查 CMake 的 add_executable / OUTPUT_NAME 或产物布局。

## 4. 检查、编译和装配

```powershell
python .\scripts\render_schema.py --print-env local-win
.\scripts\doctor_local.bat
```

第一条应输出配置键值，第二条检查工具链、项目、第三方库、配置源、数据根和构建产物。

**阅读体检输出，不能只看退出码。** 现有体检即使发现缺失也可能返回 0。首次编译前“未生成”exe 正常，渲染前“未渲染”也可能正常；工具链、项目、库、配置或真实数据缺失应先处理。体检提示的通用 `runtimeschema.xml` 不等于每个任务的专用运行单。

依赖齐全且尚无匹配的 exe 时执行：

```powershell
.\scripts\build_local.bat
```

编译成功后应有 `PROJECT_DIR/BUILD_SUBDIR/Bin/lishuttle.exe`。装配成功后 exe 旁应有 `runtimelibrary/`、配置、天线、模型、日志配置、签名文件和必要 DLL。

正常网页流程直接进入第 6 节，在“装配并渲染”时自动补齐缺失的基础配置和 DLL，保留 Bin 中已有文件。引擎按 exe 位置查找配置，与终端所在目录无关。

仅在需要命令行完整装配时执行以下可选步骤：

```powershell
.\scripts\stage_local.bat
```

**此脚本与网页的“只补缺失文件”不同：它使用目录复制，可能覆盖已有配置、DLL 等运行期文件。** 应在渲染和手工调整之前使用；已有调好的运行目录请先备份。若要更新已存在的 DLL 或基础配置，网页补齐不会自动升级这些文件，需要明确选择更新方式。

已有匹配构建产物可跳过编译，但必须让本机配置指向它并确认装配完整。默认流程不需要 `--install`。

## 5. 准备地图和任务

室外地图通常需要以下结构，索引引用的数据文件也必须齐全：

```text
MAP_ROOT/
└─ city-name/
   ├─ heights/index.txt
   ├─ heights/projection.txt
   ├─ clutter/index.txt
   ├─ clutter/menu.txt
   ├─ buildings/index.txt
   ├─ buildvector/index.txt
   └─ city-namecluttermatchsettings.xml
```

杂波匹配配置也可使用项目默认文件。室内地图通常为 `MAP_ROOT/scene-name/building.das`。

建议 Web 任务按以下结构组织：

```text
GONGCAN_ROOT/
└─ task-name/
   ├─ task-name.csv       # 工参
   ├─ task-name.txt       # 室外区域；室内可不提供
   ├─ antennas/          # 按任务需要提供
   ├─ models/            # 按任务需要提供
   └─ scenesettings.xml  # 按任务需要提供
```

平台读取 CSV 前两行，按小区/AP 标识、位置、天线和功率等字段组合识别工参，排除路测及结果汇总 CSV。任务包 XML 的 `EngineeringFilePath` 可辅助定位：旧机器路径只作线索，在当前任务包匹配本机文件并校验表头。唯一候选自动选中；多个候选无法唯一确定时，须在“功能与参数”的“工参文件”下拉框选择；没有有效候选时停止装配。页面显示识别依据和实际路径，“工参CSV”页同步使用选定文件。装配前后端重新扫描校验，文件被移动或表头变化后需重新选择。

区域文件与选定的工参 CSV 同名会优先匹配。室外区域通常每行一个 `经度,纬度` 顶点，首尾点重复，具体格式和坐标系以引擎要求为准。

工参字段必须匹配引擎版本和功能，室内 AP 工参与室外工参不能混用。没有完整业务数据，可以检查网页和配置，但无法验证计算。

## 6. 启动和运行

双击 **启动平台.bat**，或执行：

```powershell
python .\platform\backend\server.py
```

浏览器自动打开 <http://127.0.0.1:8641>。页面和项目列表正常加载才说明初始化成功。保留服务终端；关闭浏览器不会停止服务。

1. 在“本机工具链（全局）”确认所有项目共用的工具地址。使用“添加项目”登记引擎项目，在“项目配置”保存该项目的预设与资源路径，再用“体检”“编译”检查。任务装配统一在“功能与参数”页的“资源与装配”区域操作。
2. 左侧确认地图与工参任务目录，点击对应“重新扫描”，选择城市/场景和任务。目录修改只写当前项目档案。选择工参后可保存“当前工参与地图对应关系”，再次选择相同工参和运行 XML 时恢复当前项目的绑定。
3. 在“功能与参数”选择功能、填写任务名，建议用英文字母、数字、`-`、`_`，例如 `demo-pl`。装配后生成 `demo-pl.xml`，其 `RuntimeSchema name`、输出子目录及 VS 平台启动项同步为本次任务名；源 XML 保留原状。修改任务名或任务 ID 后需重新装配，页面会阻止继续运行旧任务。功能列表按当前引擎项目读取，缺少某功能时先确认版本支持。
4. 点击“装配并渲染”，自动先从当前项目 `CONFIG_SRC`、`DLL_SRC` 补齐 Bin 的基础资源（含目录结构和 exe 旁的 `config/*.xml`），然后生成任务配置，最后按勾选装配任务天线、模型。基础补齐只复制缺失文件，保留已有运行 XML、模型、天线和 DLL；跳过源中的 `.bak`、`.task-bak`、`.tmp` 备份。源目录缺失时停止并显示错误；装配输出展示复制来源、目标和数量。复用 XML 的预览阶段不复制，确认后才装配。专用运行单生成在 exe 的 `runtimelibrary/` 下，任务单按项目生成在 `jobs/<项目ID>/<构建标识>/web-*.env`。运行单以当前项目 `CONFIG_SRC/runtimelibrary/runtimeschema.xml` 为完整底稿，保留全部参数、注释、顺序及样例默认值，仅替换任务名、数据路径和任务单明确指定的算高/层高；不按所选功能删减参数。室内任务另设置必需的 `MapFormat`、`MapPath`。样例缺失或无效时直接报错，不回退到精简模板。参数面板出现不表示输入数据已经齐全。
5. 检查并保存参数。`cali / pred / predindoor / acp / commsensing` 默认进入“本功能可配置 + 未分类”，按本地引擎源码调用链显示功能参数及路损、地图、工参、天线依赖。“本功能当前生效参数”进一步隐藏开关未启用的条件项、仅启动读取项和未分类字段；“全部已识别参数”保留当前运行 XML 的所有实际字段。切换功能会重新计算范围，手选的显示范围和搜索词保持不变。参数旁显示触发条件及源码依据；缺失的强制读取元素和可选参数单独提示，不冒充已配置值，也不自动写入 XML。其他功能暂沿用旧字典推荐范围。
   每个可编辑参数旁提供“ThirdPart 默认”按钮：数值从当前项目完整样例读取；路径只填入当前项目配置源内确实存在的对应资源（例如场景配置、杂波匹配配置），点击即备份并写入目标 XML，不修改任务源 XML。无可靠默认资源、样例缺少字段或目标 XML 缺少字段时禁用并提示；留空不会自动覆盖。需要调整 CSV 时，在“工参CSV”页加载、编辑并保存。
6. 在“运行”页点击“运行 lishuttle”，查看实时输出。“导出运行日志”可下载当前会话的全部控制台输出（含指令、导出时间、状态和退出码），保存为 UTF-8 `.log` 文件；运行中也可导出截至当时已收集的日志。体检、编译输出同样支持导出。此功能导出平台捕获的控制台日志，不包含引擎另行写入的 `uplan.log`；服务重启、刷新页面或切换项目后不会自动恢复上一会话的导出入口，需提前保存。
7. 完成后在“结果”页用相同任务名查询，确认有预期的数据文件并检查日志中的 `ERROR`、`FATAL`。
8. 需要整理时，在“资源与装配”展开“清理平台历史配置”，先“预览可清理配置”，核对后“归档并清理以上配置”。仅处理当前项目所选构建目录中具有可核验平台渲染记录的历史 XML、`.bak`、manifest、生成任务 env 及对应平台 VS 启动项；保留当前运行单（页面无当前任务时保留最近生成的一份）、任务源 XML、被其他 XML 或手写启动项引用的配置、基础资源和结果。新任务 env 按项目和构建分别存放；旧版共享 env 无法确认构建独占时保留。来源不明的文件跳过；平台进程运行时拒绝清理，文件变化后须重新预览。文件移至本工作流已忽略的 `docs/runtime-config-archives/<时间及唯一编号>/`，不会永久删除；按 `restore.json` 将文件复制回 `source` 路径即可恢复，需要恢复启动项时参考同目录 `launch.vs.json.before` 合并，避免覆盖后来新增的启动项。此入口不清理其他 Debug/Release 构建目录，需切换对应配置再预览。

室外路损选 `pl`，室内路损选 `plindoor`，室外预测选 `pred`，室内预测选 `predindoor`（需要引擎支持）。任务 ID 通常保持默认 `1`，它不是结果目录名；最大计算高度、层高统一在装配后下方的配置参数面板中调整；顶部不再单独设置，网页生成任务单也不再写入高度覆盖值。

“装配任务天线”和“装配任务模型”分别控制资源复制。天线目录同时支持 `antenna/`、`antennas/`，其中 XML、方向图及子目录文件复制到当前项目的 `Bin/antennas/`，覆盖前备份为 `.bak`（任务包内的 `.bak` 文件不复制）。仅在所选任务识别到天线 XML 或非空的天线资源目录时显示“装配任务天线”选项；未识别到资源时隐藏、取消勾选，后端也跳过天线装配。不勾选时不复制、恢复或移除项目现有天线文件；仅有方向图目录而没有天线 XML 时，勾选后沿用恢复项目默认天线 XML 的规则。参数和 CSV 编辑直接写文件，通常生成 `.bak`，但后续保存会覆盖备份，重要原始数据请另存副本。再次渲染会按项目样例和任务单重新生成，覆盖手改的运行单。渲染输出及 `.manifest.json` 的 `schema_source` 记录本次使用的底稿路径。CLI 显式指定其他名称的 `TEMPLATE` 时，仍按自定义模板渲染。

### 在 Visual Studio 中运行和调试

网页成功完成“装配并渲染”（或确认复用已有 XML）后，会自动在**当前引擎项目**生成或合并 `.vs/launch.vs.json`。Visual Studio 使用这个文件；VS Code 的 `.vscode/launch.json` 是另一种格式，本功能不生成后者。预览阶段和渲染失败时不会写启动配置。

室外任务生成当前引擎头文件中支持的主要功能：`pl`、`pred`、`rays`、`dt`、`cali`、`acp`、`ai`、`scene`；室内任务生成 `plindoor`、`predindoor`、`indoorrays`。本次明确选择的功能也会生成。条目名称为 `[LiShuttle 平台] <任务名>.xml / <功能>`，各条目使用本次任务 XML 和任务 ID，不会误用通用的 `runtimeschema.xml`。

1. 在 Visual Studio 中通过“打开文件夹”打开**引擎项目根目录**，不要打开本平台目录或仅打开单个 XML。
2. 选择与平台 `PRESET` 对应的 CMake 配置，等待 CMake 目标加载。平台启动项的程序和工作目录指向本机环境配置中的 `BUILD_SUBDIR/Bin`，更改构建路径后重新装配以同步。
3. 在启动项下拉框选择对应条目，例如 `[LiShuttle 平台] ningde-cali-pl.xml / cali`，再运行或调试。若列表未刷新，重新加载项目文件夹。

重复装配更新当前任务的平台条目；同一页面将已装配任务改名后重新装配，会替换上一次任务名对应的平台启动项。其他独立任务及手工启动项、注释和其他配置保留；历史配置清理会同步移除归档任务对应的平台条目。修改前备份到 `.vs/launch.vs.json.bak`（仅保留上一份）；文件无效时不覆盖，装配输出会显示同步失败原因。`[LiShuttle 平台]` 名称用于平台维护，需要长期自定义的条目请复制并改名。该功能不自动启动 VS 或计算。

同组启动项共用一份 XML；切换功能前仍须检查所需输入，例如 `dt/cali` 的路测数据、`ai` 的 Python 运行依赖。生成启动项只提供正确的启动参数，不代表数据已满足所有功能。网页参数面板修改的是同一份目标 XML，VS 下次启动即可读取。

### cali 校正功能

当前通过通用功能选择和 XML 参数面板配置 `cali`，没有独立的路测配置向导。先确认当前引擎支持该功能，准备匹配版本的工参、地图、路测数据及模型资源；按需配置 `DT_ROOT`，并检查目标 XML 中的 `DriverTestFileDictionaryPath` 等实际输入路径。复用已有 XML 时，路测目录自动使用当前项目的 `DT_ROOT`，也可在“修改本地资源路径”中调整；数据根目录不代替具体文件就绪检查。

不同引擎版本的校正参数可能不同，请以当前引擎实现和对应运行说明为准；平台不会自动转换旧版校正配置。运行后检查日志和引擎实际生成的校正产物，当前没有专门的校正结果汇总界面。

### 使用任务包里已有的运行配置

选择任务后，平台按根节点 `RuntimeSchema` 识别 UTF-8 运行配置 XML，文件名不限于 `runtimeschema.xml`。勾选“使用任务已有运行配置”，选择 XML（一份时预选，多份时手动选择），再选择区域文件；“不使用区域”会把 `PolygonFilePath` 设为空。室内外类型须与所选地图匹配。

点击“预览路径修改”，查看源文件、目标文件、逐项原/新路径及真实输出目录，再点击“确认装配此配置”。目标为当前项目的 `Bin/runtimelibrary/<任务名>.xml`，已有目标先备份到 `.bak`；原任务 XML 保持不动。

此模式按所选地图替换常规地图路径、区域路径和 `PathlossDirectory`；网页生成副本的 `RuntimeSchema name` 同步为任务设置中的任务名；计算参数、注释、顺序和换行保留，任务源 XML 不变。工参路径默认保留，勾选“将 XML 工参路径改为上方所选 CSV”才替换 `EngineeringFilePath`。展开“修改本地资源路径”会自动显示当前项目、地图及任务解析出的场景、输出根、地图索引、杂波和路测路径，同时保留原值供核对；更换地图、工参或 XML 后重新识别。任务自带 `scenesettings.xml` 优先，否则使用项目运行目录的场景配置。自动值不会作为手填覆盖保存；手动修改项进入预览及生成任务单。区域文件仅在上方选择，不再提供重复覆盖入口。旧自定义地图索引仅在所选地图内存在同名专用文件时自动定位，否则要求明确填写，不静默换成普通索引。模型复制操作在此模式下停用；天线装配由独立复选框控制。缺少必需字段时直接提示，不补字段或回退到项目样例。

小区计算半径以实际运行 XML 的 `EngineeringFilePath` 所指工参 CSV 为准，支持 `Main Calculation Radius (m)`、`CalcRadius` 及中文“小区计算半径”等列名。参数面板优先显示 CSV 各小区的值；数值不一致时明确提示，填写新值会统一修改 CSV 半径列并备份 `.bak`。逐小区设置请使用“工参CSV”编辑。XML 的 `DefaultCalcRadius` 单独显示为默认值，半径编辑不再修改它，也不提供“ThirdPart 默认”覆盖。工参或半径列缺失时停止修改并提示，不能退回写 XML。修改前请确认 XML 已同步为所选 CSV。

参数读取使用 XML 解析，忽略顶层注释中的示例，支持带属性、CDATA 和自闭合空字段。唯一的顶层标量字段可编辑；重复字段会列出各项原值，结构化子节点、内部注释、带命名空间的字段及非 UTF-8 文件完整展示并说明只读原因，避免猜测改哪一项或破坏 XML。保存会验证 XML、备份 `.bak` 并只替换目标值，随后重新读取面板，切换筛选不会恢复旧值。CPU 负载、工参误差、模型校正、预测小区筛选及 ACP 灵敏度等说明补入 `platform/backend/params_spec.json`，每项记录参考源码位置；版本独有且尚未确认用途的字段保留原名归入“未分类”。

路径识别允许项目配置尚未填齐：地图等已知路径仍会自动显示，不会因为缺少 `BUILD_SUBDIR`、`EXE_NAME` 或 `OUT_ROOT` 整块返回空白。未配置构建目录时，场景配置可从当前项目实际存在的 `CONFIG_SRC`（未填时检查本项目传统 `ThirdPart/Config`）中识别；不会借用其他项目的路径。无法确定的输出根或路测根保留为空，并在该字段旁持续显示 `OUT_ROOT` / `DT_ROOT` 的配置提示。实际装配、渲染及运行仍要求填写必要的项目配置。

“保存当前工参与地图对应关系”按项目、任务目录、工参和源 XML 保存地图选择、本地路径、区域和工参同步选项，不修改原 XML。保存关系不代表所有文件已就绪；渲染仍重新校验路径。一个父目录包含多份独立运行配置包时，平台分别列出子任务，避免混选资源。本轮只做本机项目和本地路径配置，不解析服务器挂载关系或自动转换服务器任务。

引擎会把 XML 的 `name` 追加到路损输出根目录。网页任务名为 `ningde-cali` 时，副本为 `ningde-cali.xml`、`name="ningde-cali"`，实际输出为 `OUT_ROOT/ningde-cali`；预览、运行提示和结果页显示真实目录。复制完成后可继续在参数面板调整目标 XML；原 XML 引用的其他路径仍须在当前运行环境可用。CLI 直接复用 XML 时仍默认保留原 name；需要与 JOB_NAME 同步时，在任务 env 中明确配置 `SYNC_RUNTIME_NAME="1"`。

生成的 `jobs/web-*.env` 记录 `SCHEMA_SOURCE`、`SYNC_ENGINEERING` 和所选区域路径，脚本重新渲染时沿用相同复制规则。再次装配会重新读取任务包 XML；若需保留目标文件的手工调整，直接在网页运行，或使用命令行的 `--no-render`。

**完成状态和退出码 0 不保证计算成功。** 引擎可能内部报错却正常退出，应同时检查结果产物和日志，平台会提示部分“假完成（无产物）”情况。

先停止或等待计算结束，再在服务终端按 `Ctrl+C` 退出。也可双击“停止平台.bat”，它按默认端口结束进程及子进程。关闭网页不能停止计算。

## 7. 可选：命令行复跑

Web 使用不要求手写任务单。脚本复跑可复制示例：

```powershell
Copy-Item .\jobs\example-pl-guangzhou.env .\jobs\my-pl.env
notepad .\jobs\my-pl.env
```

修改任务名、城市、工参和区域路径。示例不附带广州或室内数据；本地示例使用 `GONGCAN_ROOT/<实际任务包目录>/<实际文件>`，须替换占位符或直接填写绝对路径，不按任务名猜测文件名。

```powershell
python .\scripts\render_schema.py .\jobs\my-pl.env local-win
```

确认没有必需输入缺失，再运行：

```powershell
.\scripts\run_local.bat .\jobs\my-pl.env
```

默认会再次渲染。若渲染后修改过运行单，保留修改用：

```powershell
.\scripts\run_local.bat .\jobs\my-pl.env --no-render
```

## 8. 常见问题

| 现象 | 解决方法 |
| --- | --- |
| 找不到 Python 或跳到应用商店 | 安装 Python 3 并加入 PATH，必要时关闭 Windows Python 应用执行别名，重新打开终端 |
| 缺少 `local-win.env` | 新安装无需此文件；按第 3 节自动配置工具并在网页添加项目，旧 env 仅作首次导入来源 |
| 网页打开但列表加载失败 | 检查配置、项目和父目录是否存在，查看服务终端报错 |
| 地图/任务为空 | 检查两个根目录及第 5 节结构，准备数据并重新扫描 |
| 找不到编译工具 | 补装 VS C++ 组件，填写真实的 CMake、Ninja、vcvars 文件路径 |
| 预设或 exe 找不到 | 对照实际预设和产物核对 `PRESET`、`BUILD_SUBDIR`、`EXE_NAME` |
| DLL 缺失或程序立即退出 | 检查依赖架构与构建配置，重新装配；按引擎要求安装匹配的 MSVC 运行库 |
| 配置、天线、模型、签名文件缺失 | 获取完整 `ThirdPart/Config` 并装配，确认任务资源匹配引擎 |
| CSV 解析失败 | 核对功能、引擎版本、字段、编码和必填值 |
| 完成却无结果 | 检查结果页日志和 exe 旁的 `uplan.log`，先处理首条实际错误 |
| 端口被占用 | 检查已有平台，或执行 `python platform/backend/server.py --port 9000`，访问对应端口；用终端 `Ctrl+C` 退出，默认停止脚本仍查找 8641 |

可以把报错、配置和目录结构交给 AI。优先要求核对文件是否存在、预设是否匹配、第一条日志错误；不要直接清空构建目录或修改原始数据。

## 9. GitHub 文件说明

提交平台源码、前端、脚本、模板、参数说明、示例任务、本 README 和 `env/local-win.env.example`。

`.gitignore` 排除本机配置、实际任务单、`docs/` 调整文档、缓存、业务数据目录、运行结果、日志、构建产物、凭据文件和本地压缩包。任务目录仅放行上面两份指定示例；新增公开示例需要先脱敏并显式加入放行规则。每位使用者自行准备本机配置和数据。

保留的远程脚本属于历史工作流，本教程不依赖它们，也不需要 `server.env` 或 SSH。

## 10. 换电脑使用与固定路径检查

### 可通过配置迁移的内容

本次检查仓库已跟踪的代码、脚本和模板，未发现执行流程必须使用原作者的 `D:/workspace/LAB`、个人用户目录或 `Lab20261020` 项目名。示例中的 `D:/LiShuttle/...` 和 VS 安装路径是可编辑的配置示例，不要求其他电脑存在相同盘符。

| 内容 | 换电脑后的处理 |
| --- | --- |
| 工具链 | 顶部“本机工具链（全局）”或 `project_config.py --setup-machine`，一次配置、所有项目复用 |
| 引擎、构建产物、配置源和数据根 | 在顶部“项目配置”修改当前档案；旧 env 只用于首次导入，完整说明见第 3 节 |
| 手动添加的项目列表 | `env/projects.json` 是本机文件，不进入 Git；在新电脑重新添加即可，不按项目名称识别 |
| 本机任务单和运行记录 | `jobs/web-*.env` 内含绝对路径，不进入 Git；在新电脑重新装配生成 |
| 任务包中已有 XML 的旧路径 | 按第 6 节预览后替换地图、区域和输出路径；工参路径需勾选同步；其余路径须手动核对 |
| 完整运行样例内的路径默认值 | 样例来自外部引擎项目，不代表在新电脑可用；检查生成 XML，必要时编辑或使用可用的“ThirdPart 默认”按钮 |
| 测试中的旧路径、模板注释中的示例路径 | 用于测试或说明，不是本机目录要求 |

本机环境、项目列表、实际任务单、结果和凭据由 [`.gitignore`](.gitignore) 排除。`git clone` 不会带来作者机器上的这些文件，也不会自动取得外部引擎和业务数据。

### 代码固定约定：不兼容时需要适配

以下内容不是个人盘符绑定，但也不能全部通过修改环境变量解决：

| 固定约定 | 影响及处理 | 代码位置 |
| --- | --- | --- |
| 网页及本地脚本读取同一项目档案 | 当前网页只适配本地 Windows；旧 env 首次导入，子进程使用固定配置快照；服务器环境保持独立 | [project_config.py](scripts/project_config.py)、[core.py](platform/backend/core.py) |
| 工具按钮调用 `cmd /c` 和 Windows `.bat`；打开文件夹使用 `os.startfile`，引擎输出按 GBK 解码 | macOS/Linux 不能仅改路径直接复用网页完整流程，需要适配启动、编译、文件夹打开和编码处理 | [core.py](platform/backend/core.py)：`start_toolkit`、`Runner`；[server.py](platform/backend/server.py)：`open_folder` |
| exe 固定在 `PROJECT_DIR/BUILD_SUBDIR/Bin/EXE_NAME`，运行单固定在其 `runtimelibrary/` 下 | `BUILD_SUBDIR` 从预设派生、`EXE_NAME` 自动识别，`Bin`、`runtimelibrary` 是代码中的目录约定；引擎产物布局不同需调整构建布局或平台代码 | [core.py](platform/backend/core.py)：`schema_path`、`start_lishuttle`；[render_schema.py](scripts/render_schema.py) |
| 项目内容校验及功能定义文件位置固定 | 项目须包含 `CMakeLists.txt`、`LiShuttle/`、`SwanUtility/incl/LiShuttleTypes.h`；改名或改内部布局需适配识别逻辑。项目校验的样例警告仍检查传统 `ThirdPart/Config` 位置，未随自定义 `CONFIG_SRC` 改变 | [core.py](platform/backend/core.py)：`validate_project`、`scan_functions` |
| 完整样例固定在 `CONFIG_SRC/runtimelibrary/runtimeschema.xml`，参数名和 XML 结构有约定 | 可以修改配置源根目录，但不能任意改样例文件名、节点或参数名；不同引擎版本需核对兼容性。已有任务 XML 要使用 UTF-8 | [render_schema.py](scripts/render_schema.py)、[task_schema.py](scripts/task_schema.py)、[core.py](platform/backend/core.py)：`thirdpart_defaults` |
| 地图按根目录下的直接子目录识别，以 `heights/index.txt` 或 `building.das` 判定室外/室内 | 根目录可改；地图内部命名和层级不同不会自动识别，需整理数据或修改扫描及路径映射 | [core.py](platform/backend/core.py)：`scan_cities`；[task_schema.py](scripts/task_schema.py) |
| 任务按任务根目录的子目录组织；天线、模型等资源使用约定名称 | 支持 `antenna/`、`antennas/`、`models/` 等约定，不会自动理解任意资源名称；XML 和 CSV 则按内容识别 | [core.py](platform/backend/core.py)：`scan_tasks`、`assemble_files` |
| 体检固定检查 `ThirdPart/Lib`、`uplancommon.lib`、`lishuttlectl.lib` 等 | 没有独立的 `LIB_SRC` 配置；依赖库布局或名称不同需要调整体检脚本，并同步核对引擎 CMake | [doctor_local.bat](scripts/doctor_local.bat) |
| 每个项目独立保存配置和任务地图绑定 | 新项目自动检测空白配置并显示候选，需明确保存；可显式引用共享数据目录，运行目录的生命周期互斥另行实现 | [project_config.py](scripts/project_config.py)、[project_detection.py](scripts/project_detection.py)、[server.py](platform/backend/server.py) |
| 服务只监听 `127.0.0.1`；启动/停止脚本针对默认端口 8641 | CLI 可用 `--port` 修改服务端口，但停止脚本仍针对默认端口；目前是本机网页，不是开箱即用的局域网多人部署 | [server.py](platform/backend/server.py)、[启动平台.bat](启动平台.bat)、[停止平台.bat](停止平台.bat) |

**结论：兼容目录结构的其他 Windows 电脑可通过本机配置复用；其他操作系统或不同引擎内部布局，仍存在需要改代码的适配项。** 项目档案与本地任务绑定有自动化回归覆盖；尚未在全新电脑上验证安装或运行真实引擎计算。

### 外部引擎与远程运行边界

LiShuttle 引擎不在本仓库中，其 `CMakeLists.txt`、预设及 ThirdPart 依赖需要另行检查。例如所检查的外部引擎 Linux 构建配置包含固定的 `/home/lishuttle-thirdpart/Lib`、`/home/lishuttle-preinstall`，以及 `/usr/local`、`/usr/lib64` 等约定；这些不是平台环境变量能统一替换的路径。请核对实际取得的引擎版本，必要时修改引擎构建配置。

仓库保留远程运行脚本，但没有提供可直接使用的 `env/server.env` 或对应示例；SSH 主机、账号、密钥、远程项目及数据目录均需单独配置。它们不代表当前 Windows 网页已经支持 Linux 后端部署。
