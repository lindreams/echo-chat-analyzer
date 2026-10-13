# A3 安全安装交接（2026-10-13）

## 支持与事实边界

保留既有检查、下载、GUI、Direct DB 与关闭证据成果。不扩展 QQ/微信生命周期。
0.2.0 当前安装路径仅限未建立来源连接、无分析任务的空闲会话。
连接过的会话即使已断开也先正常退出，再重新启动安装；未知资源状态仍拒绝。
默认没有正式 feed，源码/Portable/未配置 feed 保留发布页检查，不会实际应用更新。

生产使用显式、可核验 locator：当前 Frozen 程序位于可写 Setup 根目录的 `current/`，
存在 Update.exe 与 sq.version，无 .portable，安装 id/channel/version 与 SDK/配置一致。
仅这一路径启用安装；只读 Setup/MSI 根目录 fallback 缓存未获路径证明，不猜测、不放行。
注入本地 feed/SDK/缓存解析器只供虚构测试和可信 composition root 使用，不从 GUI 输入推导。

## Facade 接口

既有 `check_installable_update()`、`download_update(progress=...)`、`get_update_status()` 不变。

| 调用 | 所在线程与返回 |
| --- | --- |
| `prepare_update_install()` | worker；先只读检查空闲，再刷新可信 feed 并复验本地包；返回 `InstallHandoffResult` |
| `handoff_update_install(token, result)` | 原桌面退出入口；要求最终 ShutdownResult 及真实 Facade 关闭证据；无网络 |

`InstallHandoffResult` 为不可变对象，字段 status、target_version、token、public_message。
status：ready / denied / started / failed / busy。
token 为不透明一次性准备凭证，不是安装许可；不含磁盘路径、URL、SDK 对象或异常原文。
started 只表示 SDK 交接成功，不声称更新已经安装或新版启动。

## 时序与拒绝行为

1. 用户明确确认“安装并重启”，默认选择否；确认嵌套事件循环期间禁止重复请求。
2. worker 通过 Facade 复验可信 feed 的候选和真实 pending，确认 Full、文件名、大小、SHA256、
   新版本严格高于当前版本，ZIP 根 nuspec 的 id/version/channel 完全匹配。
3. 准备成功回调延后一轮 GUI 事件，等同一 worker relay 退场；关闭对话框使回调失效。
4. MainWindow 确认全局 workers 空闲，记录 token，通过原 closeEvent 开始同一 ShutdownProtocol。
5. 原退出入口等协议结束。最终五项 SUCCESS 缺一不可；Facade 还比较实际缓存的四项资源
   证据，拒绝仅由调用者构造的 SUCCESS。未修改必要步骤集合与 can_apply_update 契约。
6. 交接再次核对 Setup、配置、版本、pending、包路径、大小、摘要和 nuspec。没有网络或清理。
   复验使用 5 秒协作式预算，检查到超时不启动 SDK；该预算不能强行中断原生调用。
   Windows 共享读句柄禁止写入/删除，从最终复验前一直保留到
   自然退出，避免复验后替换包。SDK 出错则释放句柄、消费 token，并返回 failed。
7. 最后调用 wait_exit_then_apply_updates(asset, silent=False, restart=True)，随后自然返回退出。
   没有 apply_updates_and_restart、提前启动更新器或新的 ShutdownProtocol。

源会话已使用、分析活动或未知实现：确认前提示完成任务、断开并正常退出，再重新启动安装。
其他 worker 尚未退场：保持窗口，提示等后台任务完成再重试。
包复验失败：保持窗口可重试；关闭/迟到/重复成功回调不启动安装。
最终关闭失败、超时、UNKNOWN 或交接失败：更新不放行，原正常退出/watchdog 路径继续；退出
入口记录安全 status，不将关闭后的应用恢复为可用状态，不伪造安装成功。
原协议窗口 40 秒，watchdog 50 秒；清理全部发生在 SDK 的 60 秒等待窗口开始之前。
watchdog 在等待清理前启动，交接及正常返回后仍保持 armed，但它是 Python 线程。
固定 SDK 的安装交接不释放 GIL；若原生调用持续持有 GIL，watchdog 也无法按时执行。
因此 40 秒协议等待、5 秒复验预算和 50 秒 watchdog 不构成对这种原生阻塞的绝对超时保证。
最小诊断以虚构交接缩短 watchdog 为 50 毫秒：释放 GIL 时约 51 毫秒执行，持有 GIL 的
500 毫秒原生调用中约 513 毫秒才执行；未调用更新器，也不证明 B2 曾发生该阻塞。
本阶段接受并记录此边界，不新增原生监督进程、不修改 SDK、不重构退出架构；准入仍严格拒绝未知证据。

## 官方 API 核对

基于固定 1.2.161 官方源码：
[Python manager](https://github.com/velopack/velopack/blob/1.2.161/src/lib-python/src/manager.rs)、
[Rust manager](https://github.com/velopack/velopack/blob/1.2.161/src/lib-rust/src/manager.rs)、
[locator](https://github.com/velopack/velopack/blob/1.2.161/src/lib-rust/src/locator.rs)。
Python 的 wait API 只启动等待当前 PID 的 updater，不退出 Python；立即 apply API 会退出，未使用。
SDK 已存在缓存可能跳过摘要校验，pending 不含可信摘要，因此安装必须自行重验。

## 安装交接实现阶段记录（历史）

RED：首轮交接 12 failed / 1 passed；Facade/GUI 三项新增连接行为 3 failed / 13 passed；
限时复验 1 failed / 22 passed；Windows 防替换边界 1 failed / 25 passed。均已转 GREEN。
真实 Qt 子进程使用当前 worktree 源码、虚构配置/数据和真实本地 SDK feed，只注入安装启动
边界；五项 SUCCESS、can_apply_update=True、自然退出码 0、虚构数据哈希不变。
这不是实际 Setup A→B 安装或新版重启的验收证明。

测试隔离修正：首次 Fast 在新增空闲测试的模态提示中停住，已核实并终止专用 pytest
子进程。旧 GUI 测试辅助函数会忽略已销毁 signal 的 relay，而生产准入要求完整退场；
简单排空事件仍不能证明空闲。未修改 worker SUCCESS/UNKNOWN 判定、未清空全局集合。
两项空闲断言迁入独立 Qt 子进程，与原子进程验收组成 direct / worker / entrypoint 三种
模式：不提前启动 SDK、relay 先退场、五项证据成功、重复退出只交接一次、自然退出和数据
哈希不变。它们属于 slow_integration，需在 focused 显式运行。
期间另捕获 MainWindow 直接导入业务服务 DTO 的分层回归，已改从 Facade 导入；未放宽测试。
第二个 Fast 旧收集集合在测试隔离调整后中止；最终重新收集当前源码，完整运行一次 Fast。

历史阻断：实现阶段未找到旧 A0/A1 的 vpk 1.2.161 / .NET 8.0.425 工具链，未执行真实安装。
该阻断已解除：后续经授权从官方 NuGet 恢复隔离 vpk 1.2.161，复用 .NET SDK 9.0.200 与
.NET 8 Runtime；B1 已用包含本工作树未提交成果的副本构建真实 A/B Setup、Full 包和本地 feed。

## B1/B2 最终实验验收与发行边界

B2 已通过真实安装 A 0.2.0 → GUI 检查、SDK 下载 B → 用户确认 → 原 ShutdownProtocol →
wait_exit_then_apply_updates → A 正常退出（退出码 0）→ B 0.2.1 自动启动的完整功能链路。
后续复用同一实验安装，B 正常关闭（保留原生句柄捕获退出码 0）并从安装入口再次启动；
观测时无旧 GUI/受管进程残留或重复交接，1419 个安装文件与三个虚构数据文件的哈希校验通过。
首次自动启动的 B 在取得句柄前由用户关闭，其退出码仍 UNKNOWN；后续 B 的关闭证据不能替代该历史缺项。
最终五项 SUCCESS 来自原编译调用链的严格准入及成功交接证据，不是完整 ShutdownResult DTO 的原始日志。
原始报告、校验和日志保存在仓库外隔离实验目录，不纳入提交，不携带实验绝对路径或发行身份。

B2-W1 独立验证了固定 1.2.161 的句柄权限缺陷：waitPid 仅申请 PROCESS_SYNCHRONIZE，
WaitForSingleObject 可以成功等待退出，随后 GetExitCodeProcess 因缺少查询权限返回
ERROR_ACCESS_DENIED（5 / HRESULT 0x80070005）；增加 PROCESS_QUERY_LIMITED_INFORMATION 后成功。
B2 原生警告高度可信地由此引起，不再解释为“更新器未等待 A 退出”；B2 没有逐 API 返回值实录，
不能把独立复现写成原运行的直接 API 证据，也不能仅用跨进程日志时间戳证明精确同步顺序。

另有独立发行风险：上游 operation_wait 对真正等待错误仅警告后继续，并忽略 60 秒 WaitTimeout；
Windows apply 随后尝试强制停止包进程再替换文件。B2 正常路径成功没有覆盖这些失败情形。
依据固定版本的 [等待实现](https://github.com/velopack/velopack/blob/1.2.161/src/lib-rust/src/process_win.rs)
和 [错误/超时处理](https://github.com/velopack/velopack/blob/1.2.161/src/bins/src/shared/util_common.rs)。
正式启用安装前须审核处置该风险，优先评估官方修复版本及匹配 SDK/CLI/updater；权限修复本身不解决继续安装策略。
本次不升级、不补丁第三方二进制、不另建更新框架。

正式 feed 仍未配置：还需正式 packId/channel 与已安装版本一致、可信 HTTPS 发布源与
Full 包/索引的签名和摘要验证、正式配置下的发行包验收与回归、用户确认发布。
A3 功能与 B1/B2 隔离实验验收通过，不等于 0.2.0 正式发行条件全部完成。

实现阶段验证（历史；解释器显式复用已验证 Echo 环境，PYTHONPATH 指向当前 worktree/src，导入路径已核验）：

- focused：438 passed（完整 GUI + 安装交接，含三项独立 Qt 进程），385 passed（检查/下载、
  Windows Job、退出子进程、ShutdownProtocol/Facade 等）；两个文件集合不重叠，共 823 passed。
- 最终完整 Fast：4011 passed / 5 skipped / 477 deselected，511.59 秒；使用
  `-m "not slow_integration and not known_failure"`。前两次未完成的试跑中止情况如上，未把它们
  报为通过。五项 skip 是两项 symlink 权限和三项 bundled Windows Node/微信运行时缺失，未新增或修复依赖。
- git diff --check：通过；diff 文件清单和 status 已核对，未超过本轮修改范围。
- 未运行 Full；未提交、push、创建 PR、发布 feed 或实际安装/更新本机 Echo。

## 本轮修改文件（不包含之前保留的成果）

- application/installable_update_service.py：准备凭证、复验、locator 和安全 SDK 交接。
- application/facade.py：空闲预检、准备接口、最终证据来源检查。
- application/analysis_service.py、application/source_bundle_builder.py：已有 owner 的只读状态查询。
- gui/update_dialog.py、gui/main_window.py、gui/app.py、gui/workers.py：确认、复验 worker、正常关闭意图、原退出入口交接和 worker 只读查询。
- tests/test_update_install_handoff.py：新增虚构资产/SDK、Windows 防替换和隔离 Qt 退出测试。
- tests/test_installable_update_service.py：显式 locator 工厂的隔离夹具适配。
- tests/test_gui_update_check.py：已开放安装动作后的展示/能力缺失检查，保留隐藏无效入口的约束。
- ARCHITECTURE.md、本文件、2026-10-13-a3-update-core.md：当前接口、范围和历史阶段说明。

以上文件清单与“未运行 Full、未真实安装”描述属于实现阶段历史；后续 B1/B2 实验结论以上文为准。
既有未提交成果保留；最终文档收尾与完整回归不修改生产代码、测试逻辑或第三方文件，不提交或发布。

最终收尾已核验当前 worktree 源码导入与依赖，并执行 `& $EchoPython -m pytest -q`：
完整 Full 成功结束；Frozen 构建缺失、Windows symlink 权限及原生运行时前置资产缺失项按原测试规则跳过。
保留测试中的 Pillow API 弃用警告，未为消除警告修改测试。文档纠偏与 Full 通过不代替正式发行配置和风险审批。
