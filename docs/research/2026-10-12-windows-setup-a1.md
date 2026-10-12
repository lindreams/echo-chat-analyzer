# Echo A1：Windows Setup 与 Bootstrap 验收

范围仅为 Setup 与启动 Bootstrap；本记录描述未合入工作树，不改变 v0.1.0 的发行事实。
基线：main / origin/main `1aeb19926359ab5f872c4ae8b9d23a63d0f31f8a`，独立分支
`feat/windows-setup-a1`。开始时 main 干净，既有环境未安装或升级依赖。

## 实现与文件范围

| 文件 | 改动与用途 |
| --- | --- |
| `src/qq_chat_analyzer/desktop.py` | Velopack Hook 分派先于 GUI 导入，显式禁用启动时自动应用更新 |
| `desktop_entry.py`、`gui/__main__.py`、`gui/app.py` | Frozen / 源码入口共用 Bootstrap；保留 `gui.app.main` 兼容别名，原 GUI 运行逻辑仅改名 |
| `pyproject.toml`、`LocalChatAnalyzer.spec` | 桌面 SDK 固定 1.2.161；构建核验并携带 SDK 元数据；正式版本仍为 0.1.0 |
| `scripts/package_windows_setup.py` | 使用显式 vpk、packId/channel；校验版本、运行时 pin、许可、私有状态；复制 staging 打包并验证 feed/hash/包内字节与源码未变；拒绝覆盖产物 |
| `scripts/windows_runtime_manifest.json`、`.gitattributes`、`third_party/velopack/LICENSE` | 沿用现有许可复制机制，新增未经改写的上游许可 |
| `tests/test_desktop_bootstrap.py`、`tests/test_package_windows_setup.py` | 入口顺序、禁用 auto apply、Hook 不启动 GUI；非法输入、工具版本、失败输出和源码保留 |
| `tests/test_cli.py`、`tests/test_windows_runtime_contract.py`、`tests/test_portable_runtime_copy.py` | 更新入口契约，校验 SDK 与许可，许可测试样本从共享清单生成 |
| `ARCHITECTURE.md`、`DEVELOPMENT.md`、`docs/HARDENING.md`、本报告 | 记录实际实现、操作方法和验收限制 |

没有实现 UpdateManager、GUI 下载/安装、更新退出或重启编排。既有 QQ/微信获取链路与
退出协议没有行为修改。正式 Release、Tag、项目版本及已有用户数据不属于本次改动。

## 环境与真实安装证据

专用 A1 venv：Python 3.12.10、PyInstaller 6.22.3、hooks 2026.8、Velopack SDK 1.2.161、
PySide6 6.12.0、pytest 8.4.2。复用 A0 的自定义目录 .NET SDK 8.0.425 / vpk 1.2.161；
只设置进程环境，不修改系统 PATH 或全局工具。源码导入实际指向 A1 worktree 的 `src`。

当前 checkout 缺少微信原生程序资产。从已发布 v0.1.0 ZIP 只恢复程序文件，ZIP SHA256
与已发布校验和一致：`826782306b7669898f6852ef13ec002b9190e315268fcfdf863fcb931cf240d1`；
三个原生文件分别符合当前 manifest pin。NapCat 与 Node/Koffi 通过既有官方 bootstrap
恢复和校验。它们未被用于真实聊天获取。前端回归所需 Node 使用实验目录的官方便携版本，
SHA256 对照官方清单通过，PATH 仅限测试进程。

独立 packId 为 `EchoA1.Validation20261012`，channel 为 `win-x64-a1`。
安装到实验目录 `installed/`，`LOCALAPPDATA` 指向实验目录 `install-localappdata/`。
虚构 `qq.json`、`wechat.json` 均指向不存在的实验路径，报告标记只有人工测试内容。

| 真实场景 | 实际结果 |
| --- | --- |
| 运行 Setup、首次启动 | Setup 退出 0；安装路径中的 Echo 打开“余音 Echo”窗口 |
| 安装入口再次启动 | 安装根目录入口成功启动 `current/Echo.exe` |
| 版本一致 | 启动日志、Echo 元数据、sq.version 都为 0.1.0；SDK 元数据为 1.2.161 |
| install / updated / uninstall Hook | 每个进程退出 0；未新增 GUI 启动日志，源码 Hook 亦退出 0 |
| 安装/数据隔离 | 配置、报告标记与 Frozen 日志在隔离数据根；安装目录不产生这些目录 |
| 真实卸载 | `Update.exe --uninstall --silent` 退出 0，测试注册项移除，应用目录清空 |
| 卸载后数据保留 | 虚构配置与报告标记的 SHA256 与安装前完全一致 |
| 正常关闭 | **失败：源码与 Frozen 进程均捕获到 `0xC0000005`**；窗口消失不等于干净退出 |

关闭日志表明本次空会话的既有 shutdown protocol 完成，受管 QQ PID 集为空。
启用 faulthandler 的源码对照中，绕过 Bootstrap 的 `_run_gui` 也出现相同访问冲突，
栈位于现有 `_hard_exit` / `os._exit`，并有 QThreadStorage 警告。
这证明 Bootstrap 并非复现所需条件；**根因与完整修复未验证**，不能只据栈位置断言原因。
未运行真实 QQ/微信，也未覆盖带活跃子进程的关闭场景。

### 收口退出对照：既有风险

将原始 main `1aeb199` 的 Git archive 与当前 A1 源码复制到仓库外，在同一实验路径交替运行。
两者使用同一 A1 venv（Python 3.12.10 / PySide6 6.12.0）、相同环境变量、cwd、隔离用户目录
和虚构配置。只停留首页，窗口出现后等待 5 秒，发送正常 WM_CLOSE；保留 GUI 进程句柄读取退出码。

| 对照 | 正常启动 | 关闭退出码 | 探针强制终止 |
| --- | --- | --- | --- |
| 原始 main 源码 | 3/3 | 3/3 为 `3221225477 / 0xC0000005` | 否 |
| A1 当前源码 | 3/3 | 3/3 为 `3221225477 / 0xC0000005` | 否 |

两者均在既有 `_finish_process_exit → _hard_exit → os._exit` 路径产生访问冲突。
移除 A1 新增入口别名并恢复 GUI 函数名后，`gui/app.py` 全文与 main 一致；
退出辅助函数 AST、ShutdownProtocol、MainWindow 和 Facade 的实现一致。
因此归类为**当前 A1 环境中原始 main 已存在的风险，未发现 A1 新增退出回归**；
**原生根因仍未明、正常退出仍未通过**。这不覆盖原始 main 的历史环境或旧 Frozen 包，
也不证明活跃聊天子进程的退出可靠性；本次没有进行修复。

证据保存于仓库外实验目录 `exit-attribution/` 的 `comparison.json`、`conditions.json`、
`static-comparison.json`、六轮 stderr/应用日志和 `verification.json`。
第一次探针仅寻找 venv launcher PID，漏检实际子进程中的 GUI；该强制终止轮次不计入对照。
修正为本次启动的进程树后得到上述六轮结果，仓库与虚构配置前后哈希一致。

## 自动化与构建

Bootstrap 有效 RED 为 7 failed，GREEN 为 29 passed；Setup 初始 RED 为 1 failed / 9 errors
（待实现模块缺失），首次组合 focused 为 113 passed。许可新增 RED 为 1 failed，
最终入口/打包/许可 focused 为 118 passed。完整 onedir 构建与 vpk 打包实测成功。

最终 Fast：3792 passed / 430 deselected（372.22 秒）；相关 Frozen/packaging focused integration：
178 passed（88.66 秒）；阶段 Full：4216 passed / 6 skipped / 1 warning（410.49 秒）。
日志分别为实验目录的 `logs/fast-complete.log`、`logs/focused-packaging-reviewed.log` 与
`logs/full-reviewed.log`。六个跳过项为四个需要额外 NapCat 审计 archive 环境变量的测试、
两个需要显式原生 WCDB CLI 路径的测试；这些能力不能计为已验收。警告为既有 Pillow
`Image.getdata` 弃用警告。自动化通过不抵消上述真实关闭失败。
无效或中间检查不冒充验收：首次 Fast 因缺 Node 与旧入口预期失败；补许可后的
RuntimeOnly 复制未刷新 `_internal` 清单，Frozen 哈希检查拒绝旧产物，随后完整重建。
添加许可及重建产物期间的 Full 被主动终止；这些中途运行不是最终 Full 证据。

真实命令、原始日志、feed、Setup、完整包与 JSON 证据保存在仓库外 A1 实验目录。
实际 vpk 调用记录包括 `--skip-updates --delta None --shortcuts None`，版本来自项目元数据。
打包流程可重复执行到新目录；**未验证产物逐字节可重现**。vpk 生成的 Portable ZIP
仅作为实验产物保留，没有发布任何新资产。

最终安装产物在实验目录 `setup-reviewed/`，构建清单为 `setup-build.json`；Setup SHA256 为
`33bdce7bdabbbaec80078d9142423461c1678dc204e895b682b3453101153517`。
真实安装、Hook、退出、卸载及数据校验见 `logs/reviewed-install.json`、`logs/reviewed-hooks.json`、
`logs/reviewed-exit.json`、`logs/reviewed-uninstall.json` 与 `logs/verification-reviewed.json`；
完整执行命令见实验目录 `COMMANDS.md`。

## A2 的具体阻断与未验证项

1. 既有正常退出原生访问冲突须独立定位和修复，再验收带虚构受管进程的有界关闭与重启。
   本次不能把“进程退出了”当作“可靠退出”通过。
2. 当前 About 更新检查仍只读 GitHub 正式 releases/latest，不能发现预发布或下载更新。
   A2 需明确 production packId、channel/feed 与版本策略，再接入 Application/Facade 的
   UpdateManager 状态和后台下载；GUI 不直接承担更新业务。
3. 本实验包**未签名**；SHA256/包内一致性不证明发布者身份。正式签名与可信 feed 的
   发布方式、验证边界需要确定。
4. 本次没有 Echo A→B 更新、下载取消、包损坏、失败回退或迁移验收；A0 的虚构程序结果
   不代替 Echo 的更新与 QQ/微信进程验收。旧 Portable 数据已使用相同数据根，但未验证
   所有历史配置、可移动路径、报告兼容与非标准数据目录迁移。
   禁用 auto apply 的参数调用已单测确认；真实缓存新包时的启动行为未实测。
5. 默认安装位置、多账户、干净机器、跨 Windows 版本、SmartScreen、签名分发以及
   正式快捷方式均未验收。本机外部 `--installto` 的通过不能覆盖这些场景。

收口只补充退出对照与风险事实，生产代码和测试代码保持最终测试时的内容，复用上述证据，
不重复运行 Full。A1 收口文件范围为上表 19 个文件（13 个原有文件、6 个新增文件）；
按人工授权提交 `feat/windows-setup-a1` 并创建 PR 供审阅。原 main 工作树保持干净，
不自动合并，不发布发行资产，不进入 A2。
