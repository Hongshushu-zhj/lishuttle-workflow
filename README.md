# LiShuttle 本地运行平台

在 Windows 浏览器中选择地图和任务、修改运行参数和工参 CSV、编译并运行 LiShuttle、查看结果和日志。

后端使用 Python 标准库，前端是原生 HTML/CSS/JavaScript，不需要 Node.js、npm 或额外 pip 包。本教程只介绍 Windows 本地运行。

**本仓库不包含 LiShuttle C++ 引擎源码、第三方库、地图和真实任务数据。** 使用者需要单独取得这些资源并配置本机路径，才能完成计算。配置模板中的路径只是示例。

## 1. 准备环境和数据

推荐 Windows 10/11（64 位）和 Python 3.13（当前开发环境版本）。其他 Python 3 版本尚未逐一验证。

| 必需内容 | 检查方式 |
| --- | --- |
| Python 3 | 安装时勾选加入 PATH；终端执行 `python --version` 显示 Python 3 的版本 |
| LiShuttle C++ 项目 | 根目录包含 `CMakeLists.txt`、`CMakePresets.json` 和 `ThirdPart/` |
| 第三方库 | 包含引擎所需的 `ThirdPart/Lib`、Windows DLL 等文件 |
| 运行配置 | `ThirdPart/Config` 内有运行单、场景、天线、模型、日志及签名配置 |
| 业务数据 | 与引擎版本和功能匹配的地图、工参、区域等数据 |
| 编译工具 | VS2022 或对应 Build Tools，安装“使用 C++ 的桌面开发”、项目需要的 Windows SDK、C++ CMake 工具和 Ninja |

引擎项目、第三方库和业务数据请向项目维护者获取，仓库中的示例任务单不附带实际数据。若已有可运行的 Windows 构建产物，可以跳过编译，但仍需完整的依赖和运行配置。

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

## 3. 创建本机配置（可以让 AI 协助）

首次执行：

```powershell
Copy-Item .\env\local-win.env.example .\env\local-win.env
notepad .\env\local-win.env
```

已有 `local-win.env` 时直接打开修改，不要重新复制覆盖。配置保存为 UTF-8，每行使用 `KEY="VALUE"`，路径使用正斜杠 `/`，带空格的路径也要保留双引号。

### 交给 AI 的提示词

把本仓库交给能读取本机文件并执行终端命令的 AI 编程助手，告诉它引擎项目、地图和任务包的位置，再复制以下提示词：

```text
请根据 README 和 env/local-win.env.example 配置 Windows 本地环境。
LiShuttle C++ 项目、地图和任务包的位置由我提供；缺少位置时先问我。

1. 检查 python --version，确认 python 指向 Python 3。
2. 如果 env/local-win.env 不存在则从示例复制；存在时保留并检查已有配置。
3. 读取我提供的项目 CMakePresets.json 及引用的预设文件，确认 Windows
   预设名、生成器、binaryDir、installDir，填写 PRESET、BUILD_SUBDIR、INSTALL_SUBDIR。
   当前脚本在 PROJECT_DIR/BUILD_SUBDIR/Bin/EXE_NAME 找 exe，
   BUILD_SUBDIR 必须是项目内相对目录；预设布局不兼容时说明原因。
4. 查找实际 VS2022/Build Tools 安装位置，验证 cmake.exe、ninja.exe、
   vcvars64.bat 文件存在，填写 VS_ROOT、CMAKE、NINJA、VCVARS，不要猜路径。
5. 检查 CONFIG_SRC、DLL_SRC 和第三方库，确保 DLL 与构建配置匹配。
6. 根据真实数据位置填写 MAP_ROOT、GONGCAN_ROOT、CASE_ROOT、OUT_ROOT、DT_ROOT。
   创建必要的输出/工作目录，不伪造地图、工参、第三方库或引擎源码。
7. 保留全部配置键，使用 UTF-8、KEY="VALUE" 和正斜杠路径保存。
8. 执行 python scripts/render_schema.py --print-env local-win 和
   scripts/doctor_local.bat，阅读完整输出。体检退出码 0 不代表所有检查通过。
9. 报告检查结果、仍缺少的资源及下一步编译和装配操作。

只配置本地模式，不设置 SSH 或服务器，不修改引擎源码或原始任务数据。
不要覆盖已有配置、清空构建目录或执行实际计算。
```

只能聊天的 AI 无法自动发现本机路径，需要向它提供模板、项目预设和实际目录，再自行核对生成的配置。

### 配置项对照

| 配置项 | 含义 |
| --- | --- |
| `PROJECT_DIR` | 引擎项目的绝对路径，不是平台目录；该目录及其父目录必须存在 |
| `PRESET` | 真实的 Windows CMake 预设名，示例为 `x64-release` |
| `BUILD_SUBDIR` | 构建目录，相对于引擎项目根目录，必须对应预设的 `binaryDir` |
| `INSTALL_SUBDIR` | 安装目录，相对于引擎项目根目录；默认从构建树运行，不需要安装 |
| `EXE_NAME` | 通常为 `lishuttle.exe`，应在构建目录的 `Bin/` 下 |
| `VS_ROOT` | VS2022/Build Tools 实际安装根目录 |
| `CMAKE`、`NINJA`、`VCVARS` | 工具文件的绝对路径，不是文件夹路径 |
| `CONFIG_SRC` | 相对项目目录的配置源，通常为 `ThirdPart/Config` |
| `DLL_SRC` | 相对项目目录的 DLL 源，通常为 `ThirdPart/Dll/Release`；需匹配构建配置 |
| `MAP_ROOT` | 地图根目录，每个子文件夹是一座城市或室内场景 |
| `GONGCAN_ROOT` | Web 平台任务根目录，每个子文件夹是一份任务包 |
| `CASE_ROOT` | 命令行示例引用的工参/区域文件目录，与 Web 任务目录作用不同 |
| `OUT_ROOT` | 可写的结果根目录，通常按任务名存放计算产物 |
| `DT_ROOT` | 路测、校正等功能的数据目录 |

平台扫描 `PROJECT_DIR` 父目录中以 `Lab` 开头且含 `CMakePresets.json` 的项目，也保留配置指定的当前项目。其他命名的项目仍可通过本机配置使用。

配置后创建缺失的输出和工作目录，例如 `OUT_ROOT`、`CASE_ROOT`。不要用空文件夹替代真实地图或依赖。

## 4. 检查、编译和装配

```powershell
python .\scripts\render_schema.py --print-env local-win
.\scripts\doctor_local.bat
```

第一条应输出配置键值，第二条检查工具链、项目、第三方库、配置源、数据根和构建产物。

**阅读体检输出，不能只看退出码。** 现有体检即使发现缺失也可能返回 0。首次编译前“未生成”exe 正常，渲染前“未渲染”也可能正常；工具链、项目、库、配置或真实数据缺失应先处理。体检提示的通用 `runtimeschema.xml` 不等于每个任务的专用运行单。

依赖齐全后依次执行，每条完成并检查输出后再执行下一条：

```powershell
.\scripts\build_local.bat
.\scripts\stage_local.bat
```

编译成功后应有 `PROJECT_DIR/BUILD_SUBDIR/Bin/lishuttle.exe`。装配成功后 exe 旁应有 `runtimelibrary/`、配置、天线、模型、日志配置、签名文件和必要 DLL。

装配会复制配置和动态库，并把 `config/` 下的 XML 补充到 exe 旁。重复装配可能覆盖已有运行期文件，所以先装配，再渲染、修改参数。引擎按 exe 位置查找配置，与终端所在目录无关。

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

区域文件与 CSV 同名会优先匹配。首次每个任务目录只放一份目标工参和区域文件，避免误选。室外区域通常每行一个 `经度,纬度` 顶点，首尾点重复，具体格式和坐标系以引擎要求为准。

工参字段必须匹配引擎版本和功能，室内 AP 工参与室外工参不能混用。没有完整业务数据，可以检查网页和配置，但无法验证计算。

## 6. 启动和运行

双击 **启动平台.bat**，或执行：

```powershell
python .\platform\backend\server.py
```

浏览器自动打开 <http://127.0.0.1:8641>。页面和项目列表正常加载才说明初始化成功。保留服务终端；关闭浏览器不会停止服务。

1. 顶部确认项目。尚未编译/装配时，也可依次使用“体检”“编译”“装配配置”按钮，等待完成并检查输出。
2. 左侧确认地图与工参任务目录，点击对应“重新扫描”，选择城市/场景和任务。目录修改会写回本机配置。
3. 在“功能与参数”选择功能、填写任务名，建议用英文字母、数字、`-`、`_`，例如 `demo-pl`。功能列表按当前引擎项目读取，缺少某功能时先确认版本支持。
4. 点击“装配并渲染”，检查缺失文件提示，修正路径。专用运行单生成在 exe 的 `runtimelibrary/` 下，任务单生成在 `jobs/web-*.env`。运行单以当前项目 `CONFIG_SRC/runtimelibrary/runtimeschema.xml` 为完整底稿，保留全部参数、注释、顺序及样例默认值，仅替换任务名、数据路径和任务单明确指定的算高/层高；不按所选功能删减参数。室内任务另设置必需的 `MapFormat`、`MapPath`。样例缺失或无效时直接报错，不回退到精简模板。参数面板出现不表示输入数据已经齐全。
5. 检查并保存参数。需要调整 CSV 时，在“工参CSV”页加载、编辑并保存。
6. 在“运行”页点击“运行 lishuttle”，查看实时输出。
7. 完成后在“结果”页用相同任务名查询，确认有预期的数据文件并检查日志中的 `ERROR`、`FATAL`。

室外路损选 `pl`，室内路损选 `plindoor`，室外预测选 `pred`，室内预测选 `predindoor`（需要引擎支持）。任务 ID 通常保持默认 `1`，它不是结果目录名；算高、层高按真实任务填写。

勾选“替换天线/模型进exe(带备份)”会复制任务资源到构建目录。参数和 CSV 编辑直接写文件，通常生成 `.bak`，但后续保存会覆盖备份，重要原始数据请另存副本。再次渲染会按项目样例和任务单重新生成，覆盖手改的运行单。渲染输出及 `.manifest.json` 的 `schema_source` 记录本次使用的底稿路径。CLI 显式指定其他名称的 `TEMPLATE` 时，仍按自定义模板渲染。

**完成状态和退出码 0 不保证计算成功。** 引擎可能内部报错却正常退出，应同时检查结果产物和日志，平台会提示部分“假完成（无产物）”情况。

先停止或等待计算结束，再在服务终端按 `Ctrl+C` 退出。也可双击“停止平台.bat”，它按默认端口结束进程及子进程。关闭网页不能停止计算。

## 7. 可选：命令行复跑

Web 使用不要求手写任务单。脚本复跑可复制示例：

```powershell
Copy-Item .\jobs\example-pl-guangzhou.env .\jobs\my-pl.env
notepad .\jobs\my-pl.env
```

修改任务名、城市、工参和区域路径。示例不附带广州或室内数据；示例的 `CASE_ROOT` 不会自动等同于 Web 任务目录。

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
| 缺少 `local-win.env` | 按第 3 节复制模板、填写路径；模板不会自动成为配置 |
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
