# Echo A2：退出可靠性与清理证据契约

基线 `e6e778c934371e692272208d5b47e88db2e0edc9`，独立分支
`feat/echo-a2-exit-contract`。开始时工作树干净；复用项目已有虚拟环境，
Python 3.13.9 x64、PySide6/Qt 6.11.2、Velopack 1.2.161，运行/dev/gui
依赖符合 pyproject，pip check 通过，实际源码导入指向当前工作树。
截至收口验收时，改动未提交、未推送、未创建 PR、未合并或发布，也未开始 A3。

## A2.1：已实现，源码验证通过

原实现为避免 daemon 清理在解释器收尾时丢失，在有界等待之后仍无条件调用
os._exit。此前游戏本首页关闭三轮中两轮出现 0xC0000005；轻薄本 A1 中原始
main 与 A1 源码各三轮均失败。失败栈均到 _hard_exit/os._exit。

仓库外最小实验只让清理完成后的入口返回，三轮均自然退出 0。先写回归测试，
四个有效 RED 覆盖正常完成、owner 异常、运行中的清理以及 watchdog 与超时竞争。
修复让已经返回的清理走自然退出，仍先等待有界清理，再保留 watchdog 兜底，
立即退出与 watchdog 共享一次性出口。

随后重复子进程验证发现 watchdog 中 os._exit 也会访问冲突：主线程当时位于
threading._shutdown，watchdog 位于 _hard_exit。这是额外有效 RED。
Windows 兜底改为 GetCurrentProcess pseudo-handle + TerminateProcess，其他平台
保留 os._exit；没有按名字、路径或端口杀进程。微软文档说明 TerminateProcess
不通知 DLL 终止，而 ExitProcess 会运行 DLL_PROCESS_DETACH；这支持兜底方式的
选择，**不证明本次具体 DLL、Qt TLS 或 CRT 回调就是原生根因**。
来源：[TerminateProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess)、
[ExitProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-exitprocess)。

最终真实首页通过正式 `-m qq_chat_analyzer.gui` 入口运行五轮，窗口可见后等待
五秒，发送正常 WM_CLOSE，以实际 GUI 进程句柄读取退出码，并等待本次启动树的
全部已捕获句柄。五轮均退出 0，关闭耗时分别为 0.130、0.157、0.108、0.105、
0.110 秒，无探针强杀、无存活树 PID，虚构配置哈希未变。
用户目录每轮独立，QQ/微信配置指向不存在的实验路径；没有连接真实来源。
补齐凭据核验后再次以正式入口运行三轮，均退出 0、无存活树 PID，耗时
0.114、0.148、0.131 秒，虚构配置哈希未变。此前五轮证据与最后三轮分别保留。
源码模式日志固定写到忽略目录 Echo/logs；探针仅从每轮启动前的字节 offset
读取本轮新增日志并复制到仓库外，不收集旧日志。

子进程测试每种情形重复执行：正常、清理异常、重复关闭、运行中的虚构 Qt
worker、清理超时、非 daemon 线程阻塞解释器，以及 Echo 自有虚构 Job helper。
worker 完成标记和 helper 的真实 PID 退出都被核验，不能只凭窗口消失或日志完成。
测试以短预算验证兜底行为，不把它当作生产预算性能验收。
非 daemon 任务无限等待，测试核对实际强制出口标记，不能靠任务自行结束通过。
额外仓库外实验把 Qt worker 也改为无限等待，实际在约 1.01 秒内退出 0，记录到
watchdog 强制出口标记，外部 Job 监督器没有强杀。仍不能扩大为任意 native hang
的保证；原始证据为 qt-worker-hang/result.json 与 stderr/application 日志。

## A2.2：已实现可信状态契约，更新未接入

新增 application/shutdown_models.py：不可变逐步证据与汇总结果。
FAILED 优先于 TIMED_OUT，随后 UNKNOWN；只有全部证据为 SUCCESS 才允许更新。
空证据保持 UNKNOWN。完成标志仍可用于普通退出的等待，不能当更新权限。

Facade 每步异常不再洗成完成成功，超时保存不可变 TIMED_OUT；Direct DB recover
抛出的失败传播到结果，即使其 state 最终为 CLOSED。临时报告 cleanup 会吞掉
异常，因此额外验证原路径确已消失；runtime 清理失败或仍有注册资源报告失败。
首次 shutdown 结果缓存，重复调用不把失败、未知或超时变成成功。
credential 退休纳入 runtime 步骤的时间窗，普通退出预算不变。
退休接口或凭据查询接口缺失报告 UNKNOWN；调用后凭据仍存在报告 FAILED，
不把 retire() 返回当作凭据已经消失的证明。

保守边界：已使用的 QQ/微信来源没有完整的停止新任务、drain、helper/reader/handle
释放证明，报告 UNKNOWN；即使 registry 已清空，此前有自有进程也保持 UNKNOWN，
因为 registry 移除不是后代退出的 wait。GUI 在开始关闭时取消 worker 而不等待，
未静止的 pool、pending worker 或 relay 向结果加入 UNKNOWN。
无来源资源且 GUI 已静止的关闭可以 SUCCESS；这是关闭流程的资源快照，未来
更新必须先停止生产者并使用该次关闭结果，不能在仍可创建资源的 UI 中缓存授权。

测试覆盖无资源、实际临时报告移除、吞掉的报告失败、部分失败、recover 失败、
超时晚返回、未知来源、无 owner/无返回证据、重复关闭、运行中 worker，以及
空 Facade 证据不能被 GUI idle 成功覆盖。没有调用 Velopack 应用更新。

## 验证状态

收口前 focused 61 passed；真实桌面子进程 21 passed；桌面子进程与 Windows Job
组合 focused 34 passed。收口前 Fast：3811 passed / 2 failed / 2 skipped /
452 deselected；退出码 1。收口前 Full 运行一次：4235 passed / 2 failed / 30 skipped /
1 warning，退出码 1。两项失败均为下述独立基线对照已确认的同名用例。
跳过项为 Frozen/Portable 产物缺失、symlink 权限、NapCat 审计 archive/Node 条件
以及未设置原生 WCDB CLI；这些能力不算验收通过。警告为已有 Pillow getdata 弃用。
A2.1 Fast 的两项失败在独立 git archive 的 e6e778c 上亦
复现：已安装 distribution 的 echo-gui entrypoint 仍指向 gui.app:main，基线要求
desktop:main；NOTICE 已迁到 lindreams，许可测试仍要求 lingmeng-658。
上述是修正前的原始记录；收口修正及最终回归另列于下文。
中间 A2.2 Fast 还暴露新增 idle 测试的隔离问题：前序 GUI 测试遗留 relay，
不应假定共享进程已无任务。保持原成功预期，将 fresh-process 场景放到真实独立
子进程，原执行顺序 focused 已通过；不清空未知工作来伪造静止状态。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| Application | src/qq_chat_analyzer/application/facade.py、shutdown_models.py |
| GUI | src/qq_chat_analyzer/gui/app.py、shutdown.py、main_window.py、workers.py |
| 测试 | tests/test_desktop_exit_ownership.py、test_desktop_natural_exit.py、test_desktop_exit_subprocess.py、test_shutdown_results.py、test_shutdown_worker_results.py |
| 基线断言修正 | tests/test_windows_runtime_contract.py |
| 文档 | ARCHITECTURE.md、docs/HARDENING.md、本审计 |

原始证据保留在仓库外实验目录：各阶段测试日志、baseline-failures.log、
natural_probe.py、final-real/comparison.json、final-real-credential/comparison.json、
final-subprocess-evidence/、qt-worker-hang/、各轮 stderr/application 日志与探针。
这些包含虚构配置及本机路径，不提交到 Git。

## A2.1/A2.2 收口审计

### 两项基线失败

独立完整 git archive 的 e6e778c 同样有这两项失败，证据为 baseline-failures.log。
NOTICE 已在 PR #37 迁到 lindreams，修正 test_windows_runtime_contract.py 的旧地址断言。
入口失败来自当前仓库 .venv 的 qq_chat_analyzer-0.1.0.dist-info/entry_points.txt；
direct_url.json 指向本仓库且 editable=true，注册仍为 gui.app:main。
这是磁盘安装元数据过期：新 Python 进程也读到旧注册，清内存缓存不能解决。
仅执行本项目 `pip install --no-deps --no-build-isolation --no-index -e .` 刷新注册，
未下载、升级或安装依赖，未构建发行产物。入口已为 desktop:main，源码导入仍指向当前 src，
pip check 通过。未修改 pyproject 或生产入口来适配过期注册。

### 准入修正与传播链

新增 6 项有效 RED：协议早于 finished 发布结果、未发布 builder、分析服务缺少 drain 证明、
两种未知 registry 清点、session 退役但未证明进程退出。均以 UNKNOWN 阻止准入。
另一个有效 RED 证明 runtime 异常会跳过凭据退役；改为 finally 执行，结果仍为 FAILED。
协议 finished 前返回 UNKNOWN，超时后晚完成仍 TIMED_OUT；重复关闭保留首次结果。
无资源 SUCCESS 只接受已知清点：没有 builder/来源/分析服务、没有受管 QQ PID，
默认 session 没有活跃凭据，报告目录不存在或实际移除已验证；GUI 还必须已 idle。
注入 session 或非标准 registry 缺少完整所有权证明，不以空返回伪造 SUCCESS。
生产桌面注册了来源 builder 和分析服务，所以首页关闭结果保留 UNKNOWN，不批准更新。

Direct DB recover 异常重新抛出，由 Facade bounded step 记录 FAILED；CLOSED 不覆盖失败。
recover 返回或 drain 超时后服务返回都不证明全部 reader/handle 释放，现有服务仍 UNKNOWN。
临时报告 cleanup 吞错由 lstat 的实际结果纠正；registry 吞错后留下 PID 时记录 FAILED，
PID 被删除但曾有受管资源仍 UNKNOWN。legacy shutdown_qq_runtime 的 best-effort 返回
未被状态链当作成功证据。普通退出只等待任务完成，失败/未知仍允许有界离开。

缓存是一次关闭的不可变快照，未来更新前仍须冻结生产者；它不是可跨任务复用的安装许可。
没有全局 drain 证明的外部调用、源构建、helper/CLI/reader/handle 不得推断为 SUCCESS。
未调用 Velopack apply，未增加生命周期框架或扩展 Provider。

### 真实退出证据

专项前 12 轮及去掉多余 worker 成员字段后的 3 轮，共 15 轮正式首页启动/WM_CLOSE。
每轮隔离用户目录、虚构 QQ/微信路径，窗口可见后等待 5 秒；GUI GetExitCodeProcess
全部为 0x00000000，launcher 也均退出 0。捕获的本轮启动树句柄全部 signaled，
无探针强杀、无捕获树残留、配置哈希均不变。关闭耗时 0.366–0.495 秒；
最后三轮 GUI PID 3928/33652/40524，耗时 0.414/0.430/0.420 秒。
测试同时运行可能影响耗时，不能与此前串行测量直接解释性能差异。
仓库外 closeout 证据：comparison.json、final-storage-simplification/comparison.json，
逐轮 stderr/application 日志、conditions.json、exit_probe.py。
日志只截取本轮新增字节，没有读取旧日志或真实聊天数据。
与游戏本基线 2/3 及轻薄本原 main/A1 多轮 0xC0000005 对照，当前游戏本样本改善；
Qt/CRT/DLL 的具体原生根因仍未证明，轻薄本新方案、Frozen/Setup 未复验。

### 文件必要性审查

原 14 个文件全部复核，另加用户指定的旧地址断言修正，合计 15 个文件。

| 文件 | 必要职责与审查结论 |
| --- | --- |
| application/facade.py | 既有有界步骤收集证据，保留失败/未知；无新 Provider 生命周期机制 |
| application/shutdown_models.py | 一个枚举、两个不可变结果集中汇总；无状态机框架 |
| gui/app.py | 自然返回和单次有界强制兜底，保留原 watchdog |
| gui/shutdown.py | 单次 owner 与完成/结果分离，未完成不授权 |
| gui/main_window.py | Facade 结果追加 idle 证据；删除多余成员，改为局部快照 |
| gui/workers.py | 检查现有 pending/relay/pool，不另建任务注册表 |
| test_desktop_exit_ownership.py | 原出口职责断言随有意行为变更更新 |
| test_desktop_natural_exit.py | 自然退出、watchdog/超时竞争单元回归 |
| test_desktop_exit_subprocess.py | 真实退出码、超时、后台任务与自有 helper 的独立进程证据 |
| test_shutdown_results.py | 异常、超时、未知/无资源、重复关闭与发布边界 |
| test_shutdown_worker_results.py | GUI workers 与 Facade 结合；idle 使用新进程隔离 |
| test_windows_runtime_contract.py | 仅修正已迁移的公开源码地址 |
| ARCHITECTURE.md | 唯一架构事实源同步出口/结果契约 |
| docs/HARDENING.md | 未合入/未发布及验收边界 |
| 本报告 | 基线、RED/GREEN、进程证据和限制供审核 |

### 最终回归

Focused 483 passed，含 21 项真实桌面子进程及受影响 Windows Job、更新检查、Facade/CLI。
Fast：3820 passed / 2 skipped / 452 deselected，436.37 秒，进程退出码 0。
Full：4244 passed / 30 skipped / 1 warning，480.32 秒，进程退出码 0。
本轮仅运行一次 Full；跳过条件同前轮，警告仍为既有 Pillow getdata 弃用。
最终 git diff --check 通过（包含未跟踪新文件）；当时真实 Git index 保持未暂存。
收口验收阶段未继续 A2.3/A3，未提交、推送、建 PR、合并或发布。

## 前轮已完成的 A2.3 只读预审（本轮不继续）

| 优先级 | 当前证据与最小任务 | 建议文件 | 最小测试 |
| --- | --- | --- | --- |
| P0 | 微信 key helper 使用普通 Popen，句柄仅为局部变量；GUI cancel 仅抑制回调，无法中断 wait。给 Echo 创建的 helper 增加明确 owner、关闭获取入口、取消、有限等待与退出核验；不得管理用户的 Weixin。 | application/wechat/wechat_key_service.py、wechat_setup_service.py、facade.py；复用 runtime/windows_job.py，必要时 helper 脚本 | 无 DLL 的虚构 helper 等待/卡住/派生后代；取消与退出竞态、重复关闭；外部虚构进程不受影响 |
| P0 | Python helper finally 仅 join reader 1 秒，没有确认 reader 结束或显式关闭 PIPE；_terminate 吞掉 kill/wait 失败。JS finally 调用 CleanupHook，但其 false/异常只记日志，强杀不保证 finally。增加可核验进程/reader/PIPE/cleanup 结果，无法确认就 UNKNOWN。 | wechat_key_service.py、runtime/wechat/wx_key_helper.cjs | 双 PIPE 大量虚构输出、EOF 不到达、kill/wait 失败、cleanup false/异常；确认 reader 不残留、句柄释放 |
| P0 | WCDB CLI 经 subprocess.run 执行，Facade 没有全局取消/drain 所有权证明；已有 QQ 也只有 recover 返回、CLOSED 和 registry 移除。未来更新前停止新 acquisition/analysis/helper/CLI，等待实际退出、明文清理和句柄释放；任一缺口禁止更新。 | facade.py、application/qq/qq_direct_database_import_service.py、wechat_key_service.py；WCDB runner 边界将来单独讨论 | 在虚构文件与子进程上覆盖晚完成、超时、清理失败；真实进程退出 + 文件可删除/重命名；验证 UNKNOWN 永不调用 apply |
| P1 | 微信配置只有绝对 CLI/DLL 路径，没有 managed/custom provenance。load_or_default 与 _apply_default_runtime 会分别保留仍存在的旧路径、替换缺失路径；Portable 升级可能留在旧版本或混合两套二进制。先明确配置来源和 CLI/DLL 配对策略，再做可回滚迁移。 | application/wechat/wechat_environment_config.py、wechat_setup_service.py、wechat_provider_factory.py、resources.py | 虚构 old Portable/current Setup 目录；managed 成对重绑定、custom 原样保留、未知不擅自认领、旧路径失效/混合版本/损坏配置；data_root/key 字节保持，写入失败不覆盖 |
| P1 | 更新前安全准入仍需生产者隔离、实际资源清理与可信 feed/签名/版本通道策略。当前 can_apply_update 仅提供关闭证据，不是完整安装授权。 | 后续 Facade/Application 更新编排与桌面入口；本轮不创建框架 | 禁用新任务后获取本次结果；FAILED/TIMED_OUT/UNKNOWN/空证据均不 apply、不启动 updater；资源复活或版本代际不符拒绝 |

剩余限制：轻薄本新方案、Frozen/Setup、真实聊天场景和任意 native 卡死均未验收。
Python watchdog 依赖线程仍能执行，不能承诺突破长期占住 GIL 的任意 native hang；
若真实验收出现该情况，应单独定位，而不是用日志完成掩盖。
