# A3：空闲关闭的真实证据

本轮仅收敛 source_lifecycle / qq_runtime_termination；保留此前检查、下载、GUI、
Direct DB 及未提交成果。没有安装按钮、Velopack 更新执行、feed 修改或实际 QQ/微信访问。

## 可成功的边界

| 场景 | source_lifecycle | qq_runtime_termination |
| --- | --- | --- |
| 真正启动 GUI、仅停留主页/关于、未连接，关闭时无 worker | SUCCESS | SUCCESS |
| 自有分析服务已完成 execute，无来源资源和外部 legacy writer | SUCCESS | 取决于 runtime 证据 |
| 正在分析或 factory 在飞/已调用未发布 | UNKNOWN | 独立清点，不能弥补来源 UNKNOWN |
| 已建立 QQ/微信来源，即使界面正常断开 | UNKNOWN | 普通 close/PID 删除为 UNKNOWN；有原生整树证据才 SUCCESS |
| 自有原生 Job 在关闭前查询整树为零，并释放资源；session 无在飞 launch | 取决于来源证据 | SUCCESS |
| 未知进程、Job 已关闭未查询、PID 历史证据丢失 | 独立清点 | UNKNOWN |
| kill/资源关闭失败且仍持有资源 | 独立清点 | FAILED |

已存在可验证的正常用户关闭准入路径：隔离 Qt 子进程使用真实 build_facade、MainWindow
和正常 close，取得五项 SUCCESS、can_apply_update=True。未手工替换 GUI 证据，不创建
来源，不启用安装；原先“只构造 Facade”不足以验证这一实际路径。

## 最小所有权修改

- SourceBundleBuilder 只用于 composition root 已知惰性 factory；从未调用的 factory
  可证明尚无来源资源，并在关闭时封闭构造入口。已调用的 factory 不因未发布而成功；
  任意注入 callable 仍为 UNKNOWN，不推测其捕获对象是否持有资源。
- GUI 首页原先通过 get_wechat_setup_status 提前构造完整微信 bundle。现在在尚未创建
  来源时，以同步、与关闭互斥的只读 reader 复用 WeChatSetupService.check_setup，
  不构造 provider/key helper。已有或显式注入的 setup 仍使用原路径，连接流程不改。
- AnalysisApplicationService 用一个锁和活动 execute 计数封闭新任务；活动任务不会等到
  稍后完成再把该次 Facade 关闭结果洗成成功。未知实现和外部 legacy writer 保守拒绝。
- QQRuntimeSession 保留绑定进程历史、在飞 launch 及封闭入口。credential 查询/retire
  仍按原规则清空秘密，但不删除安装所需的进程历史。未绑定或迟到的 launch 不自证为空。
- QQProcessRegistry 在其拥有的资源上收集证据；Facade 只消费状态，不扫描进程，
  不把未知 registry 的空清单或成功返回视为可信。PID 清空/discard/无查询的 close
  记录缺证历史，重复清理不能把它变回成功。
- WindowsJobProcess.close_with_exit_evidence 仅用于可查询的 QQ Job：保留现有所有权，
  请求终止后等待 ActiveProcesses=0，再调用既有关闭逻辑。exit_verified 还要求
  native handles、PIPE 和内部 reader 已释放；普通 close 和 helper 外部 reader 不追补证明。
  不改 Job 创建/继承/纳管机制，不建立新的进程管理框架。

ActiveProcesses 的含义已核对 [Microsoft 官方文档](https://learn.microsoft.com/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information)。
终止请求不等于退出证明；本轮真实 Windows 测试还核验虚构父/子/孙进程的独立句柄均已终止。
关闭步骤依然受现有 Facade/ShutdownProtocol 时间窗约束，超时不能成为更新权限。

## 保留的阻断

已构造 QQ/微信来源目前仍没有完整的停止新任务、helper/reader/handle 与 Node
CleanupHook 生命周期证明。没有为了“连接后允许安装”继续扩张这些来源的状态框架。
普通生产断开沿旧 close 路径可能先丢失 Job 查询能力，不能事后补证。
本轮新增 API 验证的“先取得整树证明，再断开/retire”可使 runtime 步骤成功，但
不代表所有生产断开入口已经改用该 API，更不代表已使用来源的总安装准入成功。

因此 0.2.0 可验证准入路径目前限于未使用来源资源的空闲应用；连接/分析进行中不支持
安装；无法确认状态仍拒绝。ShutdownResult 必要步骤集合及 UNKNOWN/FAILED/TIMED_OUT
拒绝规则不变。安装包复验、用户确认、更新交接与 A→B 仍待后续阶段。

## 验证

核心行为先 RED（6 failed / 3 passed），另有未释放 PIPE 和真实 GUI 惰性配置查询的
独立 regression RED。测试使用虚构进程/配置和隔离用户目录，来源 factory 禁止真实访问。
Focused 包含原生 Windows Job、多代虚构进程、桌面自然/有界退出、真实 Qt 空闲准入，
以及活动分析、普通断开、退出失败、缺证历史及重复关闭。另有被替换在飞 launch 的
regression RED→GREEN，防止更新一代的成功树证明覆盖缺证的旧一代。

收口准入/Facade setup focused：121 passed，其中新增证据用例 19 项均通过。
此前扩大 Windows/退出/Direct DB focused 组合 229 passed、GUI/Facade 组合
455 passed；这些组合有重叠，不相加为总数。
一次 Fast：3988 passed、5 skipped、474 deselected。跳过项是 Windows symlink
权限以及微信 Node/koffi/wx_key.dll 条件缺失，不记作通过。
源码导入路径核验来自当前 worktree；`git diff --check` 通过。
不运行 Full，不 commit/push，不执行 Velopack 更新。

本轮文件范围：application/source_bundle_builder.py、analysis_service.py、facade.py，
application/qq 的 qq_process_registry.py / qq_runtime_session.py，runtime/windows_job.py，
GUI composition root app.py；tests/test_idle_shutdown_evidence.py 及上一轮生产空闲
测试的契约更新；ARCHITECTURE.md 和本轮/上一轮调查文档。update_dialog.py、更新核心、
Direct DB 清理代码、GUI 候选工作树及 feed/发布脚本未在本轮改动。
