# A3 自动更新核心与 GUI 交接

基线为 `a94eeec`，分支 `feat/a3-update-core`。这是检查/下载核心，未提交、未发布。
核心首轮未修改 GUI。本工作树随后集成 `feat/a3-update-ui` 的对话框与测试成果；
GUI 候选工作树保持只读，Bootstrap、ShutdownResult 和发布脚本仍未修改。

## 官方 API 核对

核对已安装 Python 包 `velopack==1.2.161` 的运行时签名，以及
[官方 Python 入门](https://docs.velopack.io/getting-started/python)、
[1.2.161 Python 封装](https://github.com/velopack/velopack/blob/1.2.161/src/lib-python/src/manager.rs)、
[1.2.161 更新管理实现](https://github.com/velopack/velopack/blob/1.2.161/src/lib-rust/src/manager.rs)。
在线生成参考页标注 1.2.0，不将它当作锁定版本的唯一证据。

本阶段仅使用 `UpdateManager(source, options=...)`、`get_is_portable()`、
`get_app_id()`、`get_current_version()`、`check_for_updates()`、
`download_updates(update_info, progress_callback=...)`、`get_update_pending_restart()`。
显式 `UpdateOptions(False, -1, channel)` 禁止降级、使用 full 包并指定 channel。
不省略 source：SDK 省略时会选择 Velopack Flow，这不是 Echo 已批准的源。
Python 将空 feed 和没有较新更新都返回 None，契约因此使用 `no_update`，
不能区分“feed 空”与“已是最新”。

GitHub `/releases/latest` 返回 tag 和发布页面；Velopack 的目录/HTTPS feed 读取
`releases.<channel>.json` 的 `Assets` 和 nupkg。二者是不同的元数据协议。
旧 `UpdateCheckService`、其 24h 去重与发布页面校验完全保留，结果不进入下载核心。

SDK 的下载负责传输、校验和与包缓存。真实文件源测试还验证其更新器文件提取行为，
仅写入临时目录中的不可执行虚构占位文件，未启动更新器。
`get_update_pending_restart()` 从本地包 nuspec 生成资产，hash 字段为空；
不能用远端 SHA256 字段要求校验本地 pending 对象。

## GUI 可调用契约

类型从 `application.installable_update_service` 导入，业务调用只通过
`ChatAnalyzerFacade`。注入参数为 `installable_update_service: InstallableUpdater | None`。
默认服务没有生产 feed，构造无网络/磁盘 I/O。

| Facade 方法 | 结果与调用要求 |
| --- | --- |
| `check_for_updates(manual=False)` | 原有 `UpdateCheckResult`，在 worker 检查发布页，适用于源码/Portable/Setup |
| `check_installable_update()` | `InstallableUpdateResult`，在 worker 检查 Velopack feed，先恢复 SDK pending 状态 |
| `download_update(progress=None)` | 同一 service 上先检查，再在 worker 下载保留的候选；回调接收整数百分比 |
| `get_update_status()` | 内存快照，无 I/O，可在 GUI 线程读取；不探测安装环境或恢复磁盘状态 |

`InstallableUpdateResult` 是 frozen dataclass，字段为 `status`、`current_version`、
`target_version`、`progress`（默认 0）、`error_code`、`public_message`。
版本来自 SDK 安装 manifest/包元数据，不以共享 editable 环境版本代替。
无 SDK 对象、路径、feed URL、异常正文或可执行下载链接。

| status | 含义/GUI 动作 |
| --- | --- |
| `idle` | 已配置但尚未检查；不代表已确认 Setup |
| `unconfigured` | 未配置可信 feed；保留旧发布页入口 |
| `unsupported` | 非 Windows Frozen、Portable 或安装 packId 不匹配；保留发布页入口 |
| `checking` | 检查正在进行，内存可观察 |
| `no_update` | SDK 未返回可安装候选（包括空 feed）；不是旧 GitHub 检查结果 |
| `available` | 存在可下载候选，显示 target_version |
| `downloading` | 下载正在进行；回调/内存快照可观察进度 |
| `downloaded` | SDK 已报告待安装包；本阶段只展示，不调用安装或重启 |
| `failed` | 操作失败，显示 public_message；按 error_code 决定重查或重试 |
| `busy` | 并发/重入请求立即返回，不改变活动操作状态 |

error_code：`check_failed`、`download_failed`、`check_required`、`in_progress`。
无有效候选时下载返回 `failed/check_required`。下载失败保留候选，显式再次下载可重试；
重新检查失败清除旧候选。成功下载后重复检查/下载读取 SDK pending，不重复传输。
同一实例只允许一个活动操作；跨进程下载锁由 SDK 负责。
SDK 构造/安装定位失败返回失败，不能冒充“没有更新”。

回调从调用线程/SDK 回调上下文执行，必须转发为 Qt signal/queued invocation，
不能直接操作控件。进度从 0 开始、单调且限制在 0–100，重复/倒退被忽略；
SDK 的 100 暂限为 99，直到下载完成并确认 pending 的 packId/version/filename/size
与候选相符后才发出 100。消费者回调异常被隔离，不导致已成功下载误报失败。
`get_update_status()` 可在回调中调用；回调中再次检查/下载会返回 busy。
目前没有取消、超时总预算或跨启动检查去重；网络操作不得在 GUI 主线程/同步启动执行。
同一实例需保留到下载完成，不允许每次调用临时新建 Facade。

## 源配置与生产缺口

`UpdateFeedConfig(source, package_id, channel)` 是由受信任 composition root 提供的配置，
不是给用户输入任意 URL 的功能。source 可为 HTTPS URL 或用于测试的绝对 `Path`。
拒绝 HTTP、凭据、query、fragment 与相对路径；配置格式校验本身不证明发布者可信。
不读取环境变量，不自动猜地址，不调用旧 GitHub Release API 选择包。
配置的 package_id 必须与真实 Setup manifest 和 feed Assets 一致，channel 与发行策略一致。
本阶段没有硬编码 packId、channel 或生产 URL，也没有启用生产下载。

生产尚需：人工批准并控制的 HTTPS feed 托管位置；确定 packId/channel/架构；
持续发布 `releases.<channel>.json` 与 full nupkg；原子发布及保留/回退策略；
publisher/代码签名及 feed 信任策略；在 composition root 注入已批准配置。
SDK 校验和只能证明传输与元数据一致，不能代替发布者身份信任。

`downloaded` 是缓存存在状态，不是安装完整性证据。SDK 恢复 pending 不重新验证 hash，
且下载遇到已存在的目标缓存可跳过传输校验。因此后续安装交接必须按受信任元数据
重新验证缓存的身份/大小/完整性，不能仅凭 `downloaded` 直接应用。

## 验证与边界

使用已验证的 Echo 虚拟环境，显式 PYTHONPATH 指向本 worktree 的 src。
TDD 首轮 RED 因 A3 服务缺失；首轮 GREEN 后，真实本地 feed 测试复现 hash 空字段差异，
修正本地 pending 校验后 GREEN。另有 pending 读取失败残留 100% 进度的 RED→GREEN。
测试只使用虚构 SDK DTO、人工 manifest、临时本地 JSON feed 和 ZIP/nupkg，
覆盖无更新、候选、下载成功、校验失败、进度、回调异常、重复/并发请求、非 Setup、
foreign packId、异常元数据、安装定位失败、候选失效与 Facade 异常归一。
focused 显式包含 `slow_integration` 的真实 SDK 文件源测试；运行一次 Fast 与 diff 检查。
未运行 Full，未访问聊天数据/密钥，未实际安装或更新本机 Echo，未 commit/push。
这不是 Frozen/Setup 真人验收，也不是生产 HTTPS feed 验收。

## 进入安装交接阶段的条件

1. 确定上述发行信任和生产 feed 配置，完成隔离 Setup/Frozen 与生产源验证。
2. GUI 集成 worker/进度与异常展示，并将检查/下载 worker 纳入停止、排空、退出证据。
3. 停止所有生产者后收集新的完整 ShutdownResult；仅 `can_apply_update=True` 才准入。
   direct_db_cleanup、retained_output_cleanup、qq_runtime_termination、source_lifecycle、
   gui_workers 恰好各一次且 SUCCESS；空、缺项、重复、未知、失败、超时全部拒绝。
   不缓存可继续创建资源时的成功快照作为安装授权；完成 A2 生命周期缺口与验收。
4. 重新验证待安装缓存，并由下一阶段显式设计安装/退出/重启编排及失败恢复。

A3 不调用任何 apply/wait_exit/restart 方法，不更改准入，不将下载成功当作 Shutdown SUCCESS。

## 检查/下载界面集成

`UpdateDialog(facade, parent=None, executor=None)` 只接收 Facade 和 worker executor，
不再有 `updater=` 参数或 `UpdateProgress(phase, percent)` 模拟协议。
保留候选分支的按钮、进度条、纯展示映射、发布页 URL 安全校验和弱引用回调保护。
`UpdatePhase` 只描述展示，不持有更新候选、包缓存或业务更新状态机；
`_core_result` 是最后展示的不可变快照，不作为独立持久事实来源。

检查按钮在 worker 中先调用 `check_installable_update()`；只有 `unconfigured` 或
`unsupported` 时回退 `check_for_updates(manual=True)`。SDK 失败不会冒充没有更新。
`no_update` 显示“暂未发现可安装更新”，不声称空 feed 表示已是最新。
发布页回退结果不会生成下载入口，且立即刷新内存状态，避免旧可下载能力残留。
可信 Setup 候选 `available` 提供下载按钮；`failed/download_failed` 且存在目标版本
允许下载重试。核心仍保留候选和 SDK cache 的唯一所有权。

下载提交使用 `lambda report: facade.download_update(progress=report)`，
与现有 worker 的位置参数 reporter 兼容，不改变 worker 的公共契约。
既有 QObject relay 将进度、结果、FacadeError.public_message 投递回 GUI 线程。
进度只接收整数，展示不倒退，未收到终态结果前最多 99%；未知结果和正常返回的失败
均不能伪造下载成功。结果回调后退役整代回调，旧 progress/success/error 不改变终态；
新尝试也不接受上一代回调。按钮在活动期间禁止重复提交。

打开/重新打开关于窗口只调用 `get_update_status()`，不做网络/磁盘检查；
窗口在 GUI 线程用 150ms QTimer 读取同一 Facade 的内存快照，观察其他窗口已提交的
检查/下载及终态。本窗口自己的活动请求由 relay 交付，避免轮询抢先覆盖结果。
关闭停止观察并退役本窗口回调，不取消服务操作；重开可以继续观察并恢复待安装状态。
应用重启后的磁盘 pending 恢复仍需用户点击检查，在 worker 中执行 SDK I/O。

本节记录检查/下载阶段：当时完成只显示等待安装，没有安装/重启按钮，
不承诺重启自动安装。已有 desktop Bootstrap 禁用 auto_apply_on_startup 的规则保留。
使用现有全局 `submit`，下载 worker 自然进入 `_PENDING` / pool / relay 的退出清点；
关闭关于窗口不等于 worker 已退出，更不等于完整 ShutdownResult SUCCESS。

验证在当前 worktree 源码上进行：整合前原 GUI focused、候选代码搬入后的 focused、
新增真实 Facade/服务连接 RED→GREEN，以及发布页回退清除旧下载入口的 regression RED→GREEN。
虚构 UpdateManager 测试覆盖检查/下载、乱序进度、未知结果、失败重试、关窗与重开；
另有真实 SDK 临时本地 feed 通过真实 Qt worker 下载、损坏包拒绝、修复后重试，
并验证渲染发生在 GUI 线程。focused 包含该 slow integration，随后运行一次 Fast。
所有样本、manifest、nupkg 和 Update.exe 占位文件均为虚构、临时且不可执行；
未启动安装器、未访问聊天记录或凭据、未运行 Full、未 commit/push/main 合入。

现已形成可用虚构配置演示的检查→下载→进度→失败/重试→完成→关窗重开闭环。
生产默认仍没有正式 feed，因此只展示既有发布页能力。真正安装更新仍依赖上文的
生产发行信任配置、缓存重新验证、完整新鲜 ShutdownResult SUCCESS 及显式安装编排。

安装交接调查发现生产关闭证据仍阻断安装；本轮只补齐 Direct DB 的真实有界清理结果，
未接入安装按钮、未调用更新应用 API、未执行真实 A→B。具体证据、测试及下一步条件见
[安装准入调查](2026-10-13-a3-install-admission.md)。

后续已实现用户确认与安全安装交接，当前接口/支持布局/验收阻断以
[A3 安装交接](2026-10-13-a3-install-handoff.md) 为准；上述历史测试数量不是本轮验收结果。
