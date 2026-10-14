# A4 隔离测试 Setup：构建记录与人工验收入口

本文记录 A4「安装与维护」专项当前未提交代码的**测试 Setup 构建结果**，供人工安装／卸载验收使用。
完整长文报告、验收步骤全文、构建脚本与全部验证证据保存在仓库外 A4 实验目录
（`README.md`、`verification.json`、`logs/`）。

本阶段**未安装、未启动、未卸载任何本机 Echo**，未提交、未 push，工作树未修改。
软件内卸载的实现与拒绝边界仍以 `2026-10-14-a4-setup-uninstall.md` 为准；本文只补充构建与准入证据。

## 产物

| 项目 | 值 |
| --- | --- |
| Setup | 实验目录 `artifacts\EchoUninstallAcceptance-win-x64-a4-acceptance-Setup.exe` |
| 大小 | 131,324,625 字节 |
| SHA256 | `8336c911925f1c574192cfa358ce30bdc5bc9534717a58641e61f66ebd84c64f` |
| packId / channel | `EchoUninstallAcceptance` / `win-x64-a4-acceptance` |
| 版本 / packTitle / mainExe | `0.2.0` / `Echo` / `Echo.exe` |
| 完整包 | `EchoUninstallAcceptance-0.2.0-win-x64-a4-acceptance-full.nupkg`，123,762,897 字节，SHA256 `6d9f27aa803ff488d9a240c099fb8c3efd3c090de599cf63afdf094f2bb0f08c` |
| 本地数据目录 | `%LOCALAPPDATA%\EchoTestA4-20261014` |
| 窗口标题 | `余音 Echo - 0.2.0 测试版` |
| 更新 feed | 未配置（`status == unconfigured`）；产物未签名 |

## 构建来源

源码为当前 worktree `feat/a4-setup-install-branding`（HEAD `6ee8828`）**加 A4 未提交改动**，
只读复制到实验目录的 `source\`（892 个文件，逐文件哈希已记录），工作树在构建前后完全一致
（`git status` 未变，`git diff --check` 通过）。

工具链沿用既有已验证环境，未安装或升级依赖：vpk 1.2.161、PyInstaller 6.22.3、
`pyinstaller-hooks-contrib 2026.8`、Velopack SDK 1.2.161、Python 3.13.9；
构建环境通过 junction 复用既有虚拟环境，未修改该环境。

副本内仅 3 处测试元数据偏差：`pyproject.toml` 版本 `0.2.0`、
`resources.py` 的 `APP_DATA_DIR_NAME` 改为 `EchoTestA4-20261014`、
`main_window.py` 窗口标题追加测试标识。

**安装器显示名（packTitle）刻意保持 `Echo`**：`SetupUninstallService._inspect` 要求安装清单 `title`
与注册表 `DisplayName` 严格等于 `Echo`，否则关于页「卸载 Echo」按钮恒为禁用。
因此旧 `EchoPreviewLab` 式改名预览包在当前代码下无法执行软件内卸载。

## 身份隔离

| 维度 | 本构建 | 旧 EchoPreviewLab | 正式 Lindreams.Echo |
| --- | --- | --- | --- |
| packId | `EchoUninstallAcceptance` | `EchoPreviewLab` | `Lindreams.Echo` |
| channel | `win-x64-a4-acceptance` | `win-x64-user-test-020` | 正式 channel |
| 数据目录 | `%LOCALAPPDATA%\EchoTestA4-20261014` | `%LOCALAPPDATA%\EchoTest020-20261013-7f3c9a21` | `%LOCALAPPDATA%\LocalChatAnalyzer` |

packId 必须为纯字母：Velopack 1.2.161 会把含点号的 packId 当作版本前缀，
在 Post-process 阶段以 `is not a valid semantic version` 失败。

已核实本 packId 当前无 HKCU 卸载注册项，桌面与开始菜单也无 Echo 快捷方式，
因此本轮安装不会覆盖既有安装或快捷方式。本机既有 `EchoPreviewLab` 与
`EchoA3.B1Lab20261013`（后者注册项指向已不存在的 `Update.exe`，属旧损坏现场）均未被触碰。

## 自动验证结果

`verify_delivery.py` 全通过，`verification.json` 记录明细。要点：

- **身份准入**：nuspec 与包内 `lib/app/sq.version` 均为
  `id=EchoUninstallAcceptance / title=Echo / version=0.2.0 / channel=win-x64-a4-acceptance / mainExe=Echo.exe`，
  `shortcutLocations=Desktop,StartMenuRoot`。安装后布局为
  `<root>\Echo.exe`（启动器）、`<root>\Update.exe`（PE 1.2.161，卸载服务只接受该版本）、
  `<root>\current\Echo.exe`、`<root>\current\sq.version`。
- **版本**：Frozen 元数据与 `APP_VERSION` 均为 `0.2.0`，与 `sq.version` 一致。
- **哈希**：Setup／完整包与 `setup-build.json`、`RELEASES-*`、`releases.*.json` 三方一致；
  包内 `lib/app/**` 1413 个文件与 `dist/Echo` 逐字节一致；包内 `Echo.exe` 与 frozen `Echo.exe` 哈希相同。
- **许可文件**：10 个 `releaseCopyrightFiles` 在副本、Frozen 树、工作树三处逐字节一致。
- **私有数据排除**：14 项 `portableExcludedFiles`、QCE 相关 `forbiddenPaths`、
  NapCat `cache`/`logs`/`config/*`、`loadNapCat.js`、`qqnt.echo.json`、`logs/`、
  `scripts/wcdb-diagnostic.txt`、状态文件均不在包内。
- **卸载 broker 完整性**：Frozen PYZ 含卸载服务、更新服务、shutdown 模型、Facade 与两个 GUI 模块；
  `_BROKER` 交接脚本在 Frozen 与**包内** `Echo.exe` 中与源码逐字节一致（2,739 字节），
  `READY/GO/ARMED` 握手、`--uninstall`、文件与注册项复验、`.portable`/`.msi-installed` 拒绝、
  第二实例防护、`System.Windows.Forms` 失败提示全部在内；Facade 三个入口
  `can_uninstall_setup` / `prepare_setup_uninstall` / `handoff_setup_uninstall` 均在 Frozen 内；
  broker 依赖的系统 PowerShell 与 `System.Windows.Forms` 实测可用。
- **图标与快捷方式**：`branding/Echo.ico` 与包内 `setup.ico` 逐字节一致；
  5 个图标位图同时存在于 Setup、frozen `Echo.exe`、启动器与 `Update.exe` 中。
- **隔离事实**：数据目录不存在、无本 packId 注册项、无安装目录。

## 人工验收入口（详见实验目录 README 第 6 节）

安装前记录 Setup SHA256、确认无同名注册项／快捷方式、记录数据目录不存在与既有安装基线；
建议用外部 `--installto` 安装到实验目录下的 `installed/`。

1. **静态检查**：`Update.exe` 为 1.2.161；`current\sq.version` 身份一致；
   HKCU 卸载项 `DisplayName=Echo`、`DisplayVersion=0.2.0`、
   `DisplayIcon=<root>\current\Echo.exe`、`UninstallString="<root>\Update.exe" --uninstall`；
   桌面与开始菜单各一个 Echo 图标快捷方式；程序目录无私有状态。
2. **启动**：桌面快捷方式启动，窗口标题含测试标识；关于页「卸载 Echo」应可用；只开程序目录／数据目录，
   **不连接真实 QQ／微信**。用 `current\Echo.exe` 单独启动并正常关闭，记录原生退出码（broker 只接受 0）。
3. **取消与防重入**：确认框默认取消，取消后不退出、不准备卸载、不启动交接、无残留 PowerShell。
4. **主卸载流程**：未连接来源的空闲会话确认卸载；核对清理先完成、交接进程在 Echo 退出后才执行
   `Update.exe --uninstall`、无强杀、无残留交接进程与控制台、失败提示不谎称成功；
   卸载后校验快捷方式与注册项移除、程序目录内容清除、`%LOCALAPPDATA%\EchoTestA4-20261014`
   与卸载前逐字节一致、其他目录不受影响。
5. **第二实例**（若应用允许）：另一实例运行时拒绝卸载且不影响该实例；关闭后可重试。
   若应用只允许单实例，记为未覆盖。
6. **拒绝／失败路径**（抽样）：缺失或替换 `Update.exe`、身份不符、权限不足、PowerShell 不可用等
   均应明确拒绝，不出现「已卸载成功」。

## 未覆盖与风险

- 构建未签名：SHA256 与包内一致性不构成发布者身份认证。
- 本轮**未做**真实安装／启动／卸载；干净机器、跨 Windows 版本、SmartScreen、多账户、
  默认安装位置与共存安装均未验收。
- Velopack 根目录 `Echo.exe` 只是启动代理（不等待子进程），
  不能用它的退出码判断应用退出；核验退出码必须用 `current\Echo.exe`。
- A1/A3 实验共用的仓库外运行时资产树（`source-A-verified/runtime`）中的
  `wechat\node.exe` 在 2026-10-13 预览构建之后从磁盘消失。本轮未修改任何既有目录，
  改为在实验目录内重建 pin 校验通过的资产根，并从上一轮已交付、已校验的完整包中取出该
  `node.exe`（SHA256 与 `scripts/wechat_runtime_pins.json` 完全一致）。
  其他构建机若仍依赖那棵树，需用 `scripts/bootstrap_wechat_runtime.ps1` 重新引导。
- PowerShell 5.1 下构建必须以进程级重定向调用 `build.ps1`；在 PowerShell 内部用 `*>`／`2>`
  重定向语句会把 PyInstaller 的 stderr 变成 `NativeCommandError`，在 `$ErrorActionPreference=Stop`
  下中断构建（实验目录保留了该中断尝试的日志）。
