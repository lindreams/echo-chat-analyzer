# A4：软件内卸载当前 Setup

## 固定上游契约

核实版本为 Velopack **1.2.161**，不是最新版文档中的推测：

- [update.rs](https://github.com/velopack/velopack/blob/1.2.161/src/bins/src/update.rs)：
  `uninstall` 及兼容别名 `--uninstall`；卸载子命令没有 `wait` / `waitPid`。
  不传 `rootDir`，由正在执行的当前安装 `Update.exe` 定位自身安装。
- [uninstall.rs](https://github.com/velopack/velopack/blob/1.2.161/src/bins/src/commands/uninstall.rs)：
  卸载会 force-stop 安装目录中的进程，删除快捷方式、安装目录内容、对应临时目录和卸载注册项；
  MSI 安装拒绝走这条链路。部分删除错误被上游忽略，所以退出码 0 仍需人工核实实际移除结果。
- [registry.rs](https://github.com/velopack/velopack/blob/1.2.161/src/bins/src/windows/registry.rs)：
  HKCU 卸载项以 manifest id 为键，注册命令为 `"<root>\Update.exe" --uninstall`。
- [locator.rs](https://github.com/velopack/velopack/blob/1.2.161/src/lib-rust/src/locator.rs)：
  Setup 使用 `current/sq.version`，Portable 标记 `.portable`，MSI 标记 `.msi-installed`。

## 实现与拒绝边界

关于页保留既有布局，仅连接原有卸载按钮。Facade 是 GUI 的业务入口。
独立卸载服务不依赖更新 feed，不更改更新核心，也不需要合入 P1。

准入要求 Windows frozen 的 `current/Echo.exe`，清单的主程序、标题和运行版本匹配，
安装 id 对应的 HKCU 卸载项与当前安装路径、版本和命令完全一致，且 `Update.exe` 的
PE 文件版本为 1.2.161。缺失文件、Portable、MSI、源码、reparse 路径以及程序目录与
标准用户数据目录相交的环境均拒绝。当前不支持 SDK 的只读安装根目录 fallback 布局。
这校验当前本地安装的一致性，不提供对抗已控制当前 Windows 用户账户的恶意修改者的发布者认证。

确认框默认取消，说明移除程序与快捷方式、保留报告和配置。确认前后检查后台任务，
确认框和交接均防重入。用户取消不会准备卸载、启动清理或启动进程。

确认后禁用操作面板，复用同一个 ShutdownProtocol。只有 Facade 自己缓存的资源清理
证据与 GUI worker 证据完整成功，才消费一次性令牌并启动隐藏的 Windows PowerShell
交接进程。当前来源生命周期存在 UNKNOWN 时拒绝卸载；使用过来源的会话可能需要先正常
退出、重新打开，再在未连接的空闲状态卸载。不会为卸载放宽 QQ／微信的退出证据。
清理失败或超时时不启动卸载器，提示关闭并重新打开，停止后的服务不会重新开放操作。

交接进程先取得 Echo 进程句柄、复验安装文件 SHA-256 和注册项，再执行 READY / GO /
ARMED 握手。Echo 收到 ARMED 才正常关闭；交接进程等到 Echo 退出码为 0 后再次复验，
两次复验均拒绝同一安装中仍在运行的其他 Echo 实例，避免上游强制停止它们的任务。
然后通过 Start-Process 显式等待当前安装的卸载器执行 `--uninstall`，读取原生退出码。
PowerShell 对 GUI exe 的直接 `&` 调用不保证等待，不能用它判断成功。
交接启动失败在 Echo 中反馈；Echo 退出后发生的复验或卸载器失败通过独立提示反馈。
整个路径不使用 `shell=True`，也不自行删除任何安装目录或本地数据。

没有删除用户数据选项，不扫描旧 ZIP、旧测试安装或其他目录。标准用户数据目录必须
独立于当前安装；卸载服务只检查这两个目录的包含关系，不遍历用户报告。

## 自动验证与人工验收

自动测试使用虚构布局、隔离的虚构 HKCU 注册项及可记录参数的原生 GUI exe 替身。
替身只写调用记录并返回可控退出码；不会执行真实 Velopack 卸载。
覆盖准入、拒绝、取消、防重入、任务运行中拒绝、安全退出、超时、文件复验、握手失败、
父进程异常退出、原生卸载器非零退出，以及报告与配置字节保持。

真实 Setup 验收清单（人工在隔离测试安装上执行）：

1. 正式安装显示可用按钮；Portable、源码、损坏身份不允许执行；页面布局无变化。
2. 取消不退出、不调用卸载器；连续点击只产生一次确认和一次交接。
3. 任务运行中拒绝；关闭或重启后的空闲会话能获得完整退出证据。
4. 记录 Echo 原生进程退出码为 0，确认清理先完成，卸载器只在 Echo 退出后运行；
   无强杀 Echo、残留交接进程或控制台窗口。同时运行同一安装的其他 Echo 实例时应拒绝卸载，
   不影响另一实例；关闭另一实例并重新打开当前 Echo 后可以重试。
5. 当前安装的程序、桌面／开始菜单快捷方式、对应卸载注册项被移除；核实延迟自删除。
6. 独立报告与配置前后哈希一致，旧 ZIP、旧测试安装和其他目录不受影响。
7. 缺失／替换卸载器、权限不足、PowerShell 不可用、清理失败和交接失败均有明确拒绝／失败反馈，
   不出现 Echo 宣称“已卸载成功”的提示。

## 人工验收结果（2026-10-14）

验收对象是本 A4 未提交代码构建的隔离测试 Setup：独立 packId `EchoUninstallAcceptance`、
channel `win-x64-a4-acceptance`、版本 0.2.0，外部 `--installto` 安装到实验目录 `installed/`，
用户数据根独立于安装目录；构建与身份证据见 `2026-10-14-a4-test-setup-build.md`。

人工报告的实际结果：

| 验收项 | 结果 |
| --- | --- |
| 安装与首次启动 | 通过：测试 Setup 安装、启动正常 |
| 桌面与开始菜单快捷方式 | 通过：创建正常，卸载时随安装移除 |
| 关于页显示与操作 | 通过：显示与操作正常，未记录布局变化 |
| 软件内卸载 | 通过：卸载成功，安装目录及相关快捷方式正常移除 |
| 本地数据保留 | 通过：本地虚构测试数据保留，卸载前后 SHA256 一致 |

以下项目本轮**没有取得直接证据**，不计为通过：

- **Echo 原生进程退出码数值**：人工报告没有记录该数值。卸载成功且安装目录与快捷方式被移除，
  间接说明交接进程观察到退出码为 0（`_BROKER` 在 `$owner.ExitCode -ne 0` 时抛错并跳过卸载器），
  但这是间接推断而非直接记录。既有正常关闭路径的原生访问冲突风险本次未做复现或修复验证。
- 取消路径、连续点击防重入、任务运行中拒绝、关闭／重启后空闲会话的完整退出证据、
  同一安装第二实例拒绝卸载、延迟自删除与卸载注册项移除的逐项核实、
  拒绝／失败路径抽样（缺失或替换卸载器、权限不足、PowerShell 不可用、清理失败、交接失败）：
  均未在本轮人工报告中单独记录或执行；这些分支只有自动化证据。

收尾审核的自动化证据：A4 定向测试 123 passed。Fast Suite
（`-m "not slow_integration and not known_failure"`）为 3899 passed / 169 failed / 10 errors，
其中 152 failed、10 FacadeError、1 个 jieba 隔离测试的失败与全部 10 errors 由共享构建环境缺少
jieba `dict.txt` 引起（既有已证明的环境问题，未重复调查）；其余 6 failed 出现在本专项新增的
GUI 卸载测试，原因是既有 `tests/test_gui.py` 遗留 GUI worker 全局状态使 `workers_idle()` 为假，
不是本专项生产代码缺陷。未运行 Full，未重新打包，未 push。
