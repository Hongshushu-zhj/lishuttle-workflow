# LiShuttle Workflow 桌面版验收记录

## 0.1.3 装配及完整流程修复 · 2026-11-18

本轮 Python 核心完整回归 744 项、2 项跳过，其余通过（65.771 秒）；Web/桌面外壳 158 项、Vue 界面 46 项通过，类型检查通过。独立复审发现的 Windows 子进程持文件句柄边界已补回归：修复前立即模拟回滚 75/80 次被拒绝，修复后相同持锁场景 30/30 次恢复成功。

### 已复现的问题和修复边界

- 原 0.1.2 的真实桌面服务在保持控制输入读取时，合法 `/api/render` 请求超过 10 秒仍无响应；直接继承输入的渲染器 `--help` 也超时，独立空输入约 0.21 秒返回。装配与 Runner 任务使用不同入口，是前次未覆盖的缺陷。
- 新装配进程使用 `ManagedProcess` 的空输入和进程树所有权。渲染上限 120 秒，超时返回未确认生成；正常退出先停止渲染器，让 HTTP 装配请求通过原 `FileTransaction` 回滚，再完成服务关闭。现有生成凭据、哈希校验和资源保护保留。
- 退出超时后不再重复向停止读取的服务发送关闭消息；界面保持“仍在关闭”，可以继续等待或明确强停。
- Windows 当前项目历史按路径语义比较，修复正反斜杠/大小写差异造成的漏显。原始历史上下文不重写，POSIX 路径保留大小写隔离。
- 前端编辑即作废旧体检，适配模式更新工参路径，活动日志切换与结果关联均有独立回归。

### 实际服务流程

`tests/desktop_packaged_toolkit.py` 使用真实 `desktop_supervisor → desktop_entry → authenticated HTTP API`，从启动到关闭持续保留控制管道。临时安装/用户数据/项目完全隔离，路径含中文和空格，PATH 仅含 System32；使用本机真实 MSVC/CMake/Ninja 编译一次性 C++ 程序。覆盖：

1. 拒绝未鉴权请求；项目、工具链、任务、地图、偏好读取保存。
2. Debug/Release 两次实际编译及体检；对应 DLL 来源选择；每模式新建与重复装配，各次凭据独立。
3. 原任务 XML 预览、过期令牌拒绝、适配装配；参数读取保存及旧修订冲突。
4. 无效预检阻止启动，修复临时输入后通过；实际子进程参数与固定会话上下文正确。
5. 进程退出前可读日志，分页及完整导出一致；运行中拒绝并发装配；历史及会话结果一致。
6. 真实关闭和重启后，配置、参数、当前运行配置选择、偏好、日志及历史仍可恢复；原临时源数据字节保持原样。

临时程序只打印参数，不实现 LiShuttle 业务。其退出码为 0，但无业务产物，因此验收明确检查 `verdict=failed`、业务不可用、归档不完整，避免把进程成功当作业务成功。此项是结果状态表达的验收，不是业务计算验收。

最终交付及证据目录：`release/stable/0.1.3/`；`package-verification.json` 校验资源白名单及哈希，`SHA256SUMS.txt` 校验安装包，`win-unpacked/resources/build-info.json` 记录源码提交及干净状态。`smoke/packaged-toolkit.json` 保存完整流程检查、请求耗时和会话结果；`smoke/desktop-smoke.json` 保存最终桌面启动及退出证据。

```powershell
node scripts/package-verify.cjs release/stable/0.1.3/win-unpacked
node scripts/desktop-smoke.cjs --executable "release/stable/0.1.3/win-unpacked/LiShuttle Workflow.exe" --output release/stable/0.1.3/smoke
& "release/stable/0.1.3/win-unpacked/resources/python/python.exe" -B tests/desktop_packaged_toolkit.py --resources release/stable/0.1.3/win-unpacked/resources --output release/stable/0.1.3/smoke --vs-root "D:/Program Files/Visual Studio"
```

仍需用户真实项目验证室内/室外引擎功能与业务产物；本次不执行真实用户引擎，不改实际业务数据，不声称已完成覆盖安装或另一台 Windows 验收。

---

## 0.1.2 编译启动阻塞修复 · 2026-11-17

根因：桌面服务主线程保持读取生命周期输入管道，构建批处理中的 Python 子进程继承了相同输入，在 Windows 启动阶段阻塞。修复将非交互任务输入设为 `subprocess.DEVNULL`；服务监管协议仍使用自己的双向管道。

| 范围 | 实际结果 |
| --- | --- |
| 可重复回归 | 修复前，真实 Runner 下 Python 任务及 build/doctor/stage/run 四个批处理入口均在管道读取时超时；修复后全部通过，任务结束后运行锁释放。 |
| Python 完整回归 | 734 项，2 项跳过，其余通过；71.759 秒。 |
| Web 与桌面外壳 | 154 项通过。 |
| Vue 界面 | 38 项通过。 |
| 桌面服务实际编译 | 真实 desktop_supervisor → desktop_entry → HTTP API → Runner → 批处理；中文及空格临时路径、隔离用户数据、PATH 仅含 System32，使用本机 CMake/Ninja/MSVC 完成 Debug 和 Release 两次编译，产出程序运行输出预期标识。 |
| 实时日志与退出 | 两次编译结束前均已读到实际输出；体检全部关键项就位；预设对应 Debug/Release DLL 来源正确；服务仍能响应活动查询及正常关闭。 |

仅运行一次性 C++ 夹具；夹具 DLL/配置文件只用于体检存在性检查，不加载。没有执行真实 LiShuttle 计算或修改实际项目及业务数据。原来卡住的会话 `162495045872085` 已在 22:56:41 被取消。

最终交付目录：`release/stable/0.1.2/`。包资源及哈希结果以 `package-verification.json`、`SHA256SUMS.txt`、`win-unpacked/resources/build-info.json` 为准；最终包的桌面启动和真实编译证据存放于 `smoke/`。

```powershell
node scripts/package-verify.cjs release/stable/0.1.2/win-unpacked
node scripts/desktop-smoke.cjs --executable "release/stable/0.1.2/win-unpacked/LiShuttle Workflow.exe" --output release/stable/0.1.2/smoke
& "release/stable/0.1.2/win-unpacked/resources/python/python.exe" -B tests/desktop_packaged_toolkit.py --resources release/stable/0.1.2/win-unpacked/resources --output release/stable/0.1.2/smoke --vs-root "D:/Program Files/Visual Studio"
```

最后一条命令的 Visual Studio 目录是本次验收机参数，不写入应用默认配置。真实引擎的项目依赖和业务计算仍需在用户项目中验证。

---

## 0.1.1 改进验收 · 2026-11-17

本轮在独立桌面分支 `codex/desktop-app` 完成；原 Web 工作区、实际引擎和业务数据未改动。以下检查使用临时项目、假工具文件或一次性输出进程，不代表真实 LiShuttle 业务计算已通过。

| 范围 | 实际结果 |
| --- | --- |
| Python 后端 | 最终完整回归 732 项，2 项跳过，其余通过；117.505 秒。 |
| Web 与桌面外壳 | 154 项通过，包括大于 16 MiB 的流式导出、失败时原目标保留、必需安装包文件及版本目录隔离。 |
| Vue 界面 | 38 项通过；类型检查及生产构建通过。 |
| DLL 专项复审 | 根目录迁移、预设解析、来源复制中变化、目标外部编辑、失败回滚等问题均补回归并通过；最终独立复审通过。 |
| 日志专项复审 | 分块中文输出、重连续读、写盘失败、事件完整性、结果归档收尾和关闭等待均覆盖；最终独立复审通过。 |
| 浏览器验收 | 13 组业务/布局场景通过，页面异常为空；覆盖三路 XML、编辑、旧历史、完整导出及大样本。 |
| 真实服务连接 | 实际 API 预览并应用 `Dll/Debug`；实际子进程退出前显示已刷新的中文半行；真实完整日志下载通过。 |
| 包内体检 | 旧 0.1.0 在仅有 System32 的 PATH 下重现“找不到 python”；新包使用内置解释器、实际 doctor 和配置加载脚本，中文空格临时项目的工具、DLL、配置和数据检查全部就位。 |
| 打包桌面启动 | 实际 Electron 0.1.1 的 13 项检查通过，页面异常为空；隔离用户目录、无系统 Python/Node PATH，正常退出后自己拥有的服务和监管进程均结束。 |
| 包内容 | 46 个工作流资源、35 个 Python 运行时文件、3 个通知文件、10 个 ASAR 条目，通过白名单、必需文件及资源哈希检查。 |

本次字体采用 Windows 中文界面字体优先；正文和控件 15px、辅助文字至少 13px、日志 14px，字段标签字重 600。1366×768、1093×614、911×512、683×384 逻辑尺寸的布局与操作位置检查通过；小窗采用重排和滚动。它不等同于物理多屏完整验收。

规模夹具为 10,000×30 CSV、100,000 行日志、500 条历史；观察 CSV 加载 0.374 秒、旧日志分页补读 23.89 秒。实时事件显示另以真实服务验收；以上均为本机样本，不是业务性能承诺。

0.1.1 交付目录为 `release/stable/0.1.1/`，保留原 `release/stable/` 下 0.1.0 应用。安装包名为 `LiShuttle-Workflow-Setup-0.1.1-x64.exe`；最终构建摘要、SHA-256、源码提交及干净状态分别以该目录中的 `package-verification.json`、`SHA256SUMS.txt` 和 `win-unpacked/resources/build-info.json` 为准。打包启动与体检证据保存在 `smoke/`。

```powershell
node scripts/package-verify.cjs release/stable/0.1.1/win-unpacked
node scripts/desktop-smoke.cjs --executable "release/stable/0.1.1/win-unpacked/LiShuttle Workflow.exe" --output release/stable/0.1.1/smoke
& "release/stable/0.1.1/win-unpacked/resources/python/python.exe" -B tests/desktop_packaged_doctor.py --resources release/stable/0.1.1/win-unpacked/resources --output release/stable/0.1.1/smoke
python -B tests/desktop_live_acceptance.py
```

仍需用合法真实引擎及代表数据验证实际 MSVC 编译、DLL 依赖与业务计算，以及另一台 Windows 的断网安装和升级。安装包未配置发布者签名；本轮未执行覆盖安装。原批处理的 GBK、特殊符号与长路径边界继续适用。下方保留 0.1.0 的历史记录。

---

## 0.1.0 初版验收

日期：2026-11-16。版本：0.1.0，正式渠道构建。目标为 Windows 10/11 x64；本次验证机为 Windows build 26200 x64、Intel Core i7-11800H、16 GiB 内存。Windows 10 与其他电脑的实际安装兼容性仍需单独验收。

## 已执行的自动验证

| 范围 | 实际结果 |
| --- | --- |
| 原有 Python 与桌面后端完整回归 | 678 项，2 项跳过，其余通过；77.399 秒。覆盖原有业务事务、编辑、预检、结果、锁及新增路径/服务/监管/发现/迁移。 |
| 最后网络路径修复的覆盖检查 | 迁移 25 项、桌面 API 5 项通过；包含不可访问旧 UNC 前缀的重新定位及已知文件前缀拒绝。 |
| 原有 Web JavaScript | 127 项通过。 |
| 原有 Web 浏览器 | 32 个隔离场景通过，页面异常为空。 |
| 桌面窗口/协议/打包单元检查 | 20 项通过。 |
| Vue 状态与实际控制器 | 26 项通过；类型检查与生产构建通过。 |
| 桌面实际应用启动检查 | 开发态及打包态已启动；打包态 13 项通过，PATH 仅含 Windows System32，不含系统 Python/Node。 |
| 包内容审核 | 白名单、完整性哈希、固定 Python 版本、许可文件与 ASAR 内容检查通过。包含 43 个工作流资源、35 个 Python 运行时文件、3 个第三方通知文件、9 个 ASAR 条目。 |
| 独立审查 | 后端与全桌面源码分别审查；进程监管失败清理、偏好恢复、缺失归档证据、网络路径、CSV 未知写入恢复、装配恢复报告、结果 SID、预览复用、小屏与日志跟随等发现已修复并复查。 |

打包启动检查使用真实 Electron、预加载桥接及嵌入式 Python 服务，验证随机端口、鉴权、受限原生操作、沙盒与隔离、UTF-8 导出、草稿关闭保护、模拟忙态关闭保护、外部导航阻止、单实例、正常退出及自己拥有的监管器/服务进程确已消失。忙态由测试注入，不代表执行了真实引擎。

桌面浏览器验收使用生产构建和内存业务夹具，覆盖原 XML 加载、字节保持的 XML 自动保存、CSV 手动保存/格式版本/草稿、未知写入后明确读取核对且不重试、预检、固定 SID、终态日志补读、历史与当前文件匹配、偏好、发现候选只填草稿、外部 XML 原字节导入、路径适配与可恢复错误复用预览、首次空状态。

## 视觉与大数据验证

1366×900 与 1920×1080 工作空间、首次空状态、结果/日志界面已截图查看。另以 1366×768、1093×614、911×512、683×384 逻辑视口检查窄屏布局、关键操作按钮和输入滚动位置，近似覆盖 1366×768 屏幕的 100/125/150/200% 可用逻辑尺寸。它验证页面布局，不等同于另一块物理高 DPI 屏幕上完整的原生窗口/系统对话框验收。

隔离规模样本为 10,000 行×30 列 CSV、100,000 行日志、500 条历史。CSV 按可见范围渲染，日志内存显示上限为 3,000 行，历史按每页 20 条加载；完整日志导出包含首尾全部内容。一次本机观察：CSV 加载约 0.37 秒，十万行日志分页补读约 19.34 秒。数字包含测试浏览器和模拟服务开销，仅作为本次样本记录，不是对真实计算性能的承诺。

## 构建与证据

构建固定 Electron 45.3.3、Python 3.13.17，应用为 0.1.0。嵌入式 Python 下载采用固定 SHA-256，隔离搜索路径；安装后不需要在线下载依赖。NSIS 为当前用户安装、可选目录，卸载保留用户数据；正式/开发应用标识与数据目录分开。

交付目录：`release/stable/`。

- `LiShuttle-Workflow-Setup-0.1.0-x64.exe`：离线安装包。
- `win-unpacked/LiShuttle Workflow.exe`：用于直接检查的已打包目录应用。
- `SHA256SUMS.txt`：安装包及交付文件校验值，以最终构建生成文件为准。
- `package-verification.json`：最终资源审核摘要。
- `smoke/desktop-smoke.json` 和截图：最终打包启动证据。
- `win-unpacked/resources/build-info.json`：源提交、是否有未提交修改及资源哈希，最终交付应对应干净源码。

本机详细测试日志、审查报告、浏览器截图保存在 `.superpowers/`，属于本机工作证据，不随安装包分发。可复现的测试源码、锁文件和构建工具已纳入 Git。

复现主要检查：

```powershell
python -m unittest discover -s tests -p "test_*.py"
node --test (Get-ChildItem tests -Filter "test_*.cjs").FullName
npm run test:desktop
npm --prefix desktop-ui test
npm --prefix desktop-ui run typecheck
npm --prefix desktop-ui run build
python tests/workflow_browser_check.py
python tests/desktop_browser_check.py
npm run desktop:dist
node scripts/package-verify.cjs release/stable/win-unpacked
node scripts/desktop-smoke.cjs --executable "release/stable/win-unpacked/LiShuttle Workflow.exe" --output release/stable/smoke
```

浏览器测试额外需要构建机的 Playwright 和已安装 Chrome/Edge，不会自行下载浏览器。运行程序不需要这些开发测试依赖。启动检查参数及结果以脚本帮助/源代码约定为准。

## 尚未验证的发布事项

- 另一台普通权限 Windows 10/11 电脑上的断网安装、覆盖升级、卸载后数据保留、杀毒软件与发布者签名体验。
- 合法真实 LiShuttle 引擎、MSVC 编译、匹配的 DLL、地图与业务数据的代表功能计算和完整取消验收。
- 原生物理多屏/高 DPI 矩阵、冷启动性能目标、所有异常断电/磁盘满组合、所有外部路径编码和长路径组合。

安装包尚未配置发布者代码签名。旧批处理仍有 GBK 和特殊符号限制，对不能安全传递的工具路径会明确拒绝；这不是对任意 Unicode/特殊符号/长路径的已验证承诺。无真实引擎/业务数据被执行、清理或迁移。
