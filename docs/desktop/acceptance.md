# LiShuttle Workflow 桌面版验收记录

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
