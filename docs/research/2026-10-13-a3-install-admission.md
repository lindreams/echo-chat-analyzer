# A3 安装准入调查：生产证据阻断，尚未进入安装验收

本文件记录上一轮调查与 Direct DB 修复。后续两项关闭证据收敛已改变“未连接”的结论；
当前场景边界见 [空闲关闭证据收敛](2026-10-13-a3-idle-shutdown.md)，安装交接仍未实现。

工作树 `feat/a3-update-core`，基线 a94eeec。保留已有检查、下载、GUI 及未提交成果。
本轮没有完成安装/重启交接，不能将此前检查/下载闭环或本轮测试通过视作 A→B 验收。

## 官方 API 与调用顺序

核对固定版本 [Python UpdateManager 1.2.161](https://github.com/velopack/velopack/blob/1.2.161/src/lib-python/src/manager.rs)
及 [Rust 实现](https://github.com/velopack/velopack/blob/1.2.161/src/lib-rust/src/manager.rs)：
`wait_exit_then_apply_updates(update, silent=False, restart=True, restart_args=None)`
启动更新器等待当前 PID 正常退出，不自行退出 Python；等待窗口为 60 秒。
`apply_updates_and_restart` 则会立即退出，不用于替代正常关闭。

未来必须先禁止生产者、完成有界清理、获得该次完整 `ShutdownResult.can_apply_update`
证据，再作最终包复验并启动等待更新器，然后正常退出。不能在清理开始前启动更新器，
把清理消耗计入 60 秒窗口；不能借用兜底强制退出证明更新可安全应用。

SDK pending 的 SHA1/SHA256 为空；已有缓存文件会跳过 download 校验。
因此 `downloaded`、pending 存在、正常 download 返回均不是安装权限。
进入安装交接前仍必须将实际缓存字节/尺寸/哈希、manifest 身份/版本/channel
与可信源中的目标及当前 Setup 安装身份重新对应。正式源不存在，不硬编码地址。
本轮未添加安装复验或 apply Facade API，不宣称已解决这项缺口。

## 真实生产阻断

使用真正 `gui.app.build_facade()` 构造后立即 shutdown，不打开任何来源或真实用户目录。
测试将 QQ/微信 bundle factory 和用户存储访问替换为禁止访问断言。得到：

| 证据 | 状态 |
| --- | --- |
| direct_db_cleanup | SUCCESS（未构造来源） |
| retained_output_cleanup | SUCCESS（无持有临时报告） |
| qq_runtime_termination | UNKNOWN |
| source_lifecycle | UNKNOWN |

此为 Facade 四项结果；GUI 即使提供第五项 SUCCESS，已有 UNKNOWN 仍不可放行。
生产总结果不是 SUCCESS，不允许合成成功证据来启动安装。

原因沿真实调用链确认：

- `source_lifecycle`：生产注册来源 builder、注入分析服务；这些对象没有完整的停止
  新任务、构造中对象归属、drain 及资源释放证据。QQ 的 bundle 发布也尚未与关闭共用
  微信现有的发布互斥边界。不能把“未发布 bundle”或“取消 GUI worker”当作资源为空。
- `qq_runtime_termination`：生产注入 QQRuntimeSession，retire 清空 credential 和 process
  引用，没有对应的进程退出证明；registry 清空/Job close 也不等价于所有后代退出的 wait。
- 使用过 QQ/微信时存在更多资源证据缺口；微信 key owner 的有界结果不证明所有来源
  helper/reader/handle 与 Node CleanupHook 均完成。现有架构对此明确保留 UNKNOWN。
- GUI 对 worker/pool/relay 的清点是即时静止证明；活动任务仍 UNKNOWN，不在本轮放宽。

这些是实际缺少的所有权证明，不是可把常量改为 SUCCESS 的错误。
依照本轮“真实生产安全证据阻断不得绕过后继续安装”的约束，在此停止安装交接。
未添加能执行安装的按钮，未运行隔离 Setup A→B，也未触碰用户使用中的 Echo。

## 本轮最小修复

`QQDirectDatabaseImportService.shutdown() -> ShutdownStatus` 现在把已经执行的有界
drain/recover 结果交给 Facade，不改变原有 recover 错误抛出及正常退出预算：

- 从未启动且无 client/startup/acquisition：可证明为空，SUCCESS；不构造 client。
- 禁止新 acquisition，drain 成功且 recover 成功：SUCCESS。
- drain 超时，即使 recover 成功或旧任务后来完成：仍 TIMED_OUT。
- recover 异常：保留 FAILED 并抛出原公共异常，重复调用不洗成成功。
- 清理进行中重复调用：UNKNOWN；结束后重复调用返回已记录结果，不重复 recover。
- startup 失败即使 state 为 CLOSED，已有 client 仍须 recover，不能冒充空资源。

Facade 只接收具体自有实现的 ShutdownStatus；未知注入服务不能靠返回 SUCCESS
获得所有权证明。`source_lifecycle` 与 runtime 的保守规则完全保留。
本轮范围是上述服务、Facade 的该证据消费、新增虚构证据测试及文档；未改更新 GUI。

## 验证与进入下一阶段的条件

新证据测试先 RED：6 failed / 1 passed；可重试 startup 分支另有有效 regression RED。
GREEN 包含实际服务/Facade、活动 acquisition、迟到完成、重复调用、失败，以及生产
composition 的阻断验证。全部使用虚构 client，不请求 generation、数据库或真实凭据。
最终 focused 两组分别 169 passed 和 43 passed，共 212 passed，包含真实 SDK 虚构
本地 feed、GUI worker 和隔离桌面子进程；新增准入证据测试 8 passed。
一次 Fast：3975 passed、5 skipped、468 deselected。跳过项是 Windows symlink 权限
以及微信 Node/koffi/wx_key.dll 条件缺失，不能记作通过。`git diff --check` 通过。
测试源码导入已核验来自当前 worktree；不运行 Full，不 commit/push/发布。

必须先补齐来源、runtime 及 GUI 的真实完整关闭证据，保持 UNKNOWN/FAILED/TIMED_OUT
拒绝规则；随后实现包复验和显式用户确认，才可尝试隔离 Setup A→B，验证 A 正常退出、
B 实际启动、虚构数据保留。完成这些验证后才具备接通正式 feed 的安全依据。
正式 feed 还缺经确认的 packId/channel/版本策略、发布端点、发布身份与签名/信任策略、
完整 release 元数据和对应包；可准备这些配置方案，但当前不能启用生产安装。
