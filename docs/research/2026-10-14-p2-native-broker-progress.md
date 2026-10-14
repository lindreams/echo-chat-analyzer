# P2 原生 Broker 进展与可复现安装阻塞

基于 `d5d120b` 的既有协议继续开发，未重新实现协议核心。
仅处理更新协议、P1 composition、Windows 原生原语及相关测试和文档；没有合并 QQ 修复、
访问真实聊天数据、安装依赖、修改发行版本、发布 feed/Release 或开放生产安装。

## 实际实现

- 状态提交与拒绝共用短临界区，防止 READY/GO/ARMED 覆盖并发拒绝；apply 预约前检查
  终态。授权撤销与 apply 预约共享授权锁，防止最后一次 permission 检查后的撤销被遗漏。
  预约是副作用的线性化点；预约后的拒绝不能撤销已经开始的操作，但不能恢复成功或重试。
- ProcessIdentity、InstallationIdentity、PackageIdentity 的观察字段验证准确类型，拒绝
  与整数相等的浮点数字段；无效 authorization 安全拒绝，不在拒绝路径抛出属性错误。
  升级目标拒绝 prerelease，沿用已有版本解析器，不新建另一套 SemVer 算法。
- 从 P1/A5 提交 `ef3b0f5` 保留更新源模块和测试，桌面显式注入固定源及关闭的交接门。
  门仅认 `is True`，不接受整数、字符串等 truthy 值。未改 P1 packId 或审批开关。
- Windows ProcessHandle 申请 `SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION`，用同一
  native handle 读取创建时间/镜像、等待、查询退出码；捕获时绑定 PID/创建时间/镜像。
  截止时间为绝对 monotonic 时间，超时、句柄失效、查询失败、非零退出均不能成为 apply。
- Windows FileGuard 用保留只读句柄禁止写/删共享；最后路径分量用 OPEN_REPARSE_POINT
  并核验句柄属性。MaintenanceLease 用无共享的安装所属文件句柄排斥竞争 Broker。
  二者是原语，尚不提供完整的目录生命周期证明或生产者准入协议。

## 原生测试与阻塞证据

`tests/test_windows_update_broker.py` 属于 slow_integration，真实启动虚构 Python/C#
子进程及调用 Windows API，未启动安装器、实际 Echo GUI、QQ 或微信。

15 项原生测试通过，包括：

- 保留句柄观测真实退出 0/7；超时不成功；身份创建时间/镜像/类型不匹配拒绝。
- 同步-only 真实句柄可等待，但退出码查询权限不足，协议终态拒绝且 recorder 无调用。
  增加有限查询权限后真实正常退出才允许 fictional recorder。
- 已关闭句柄与非零退出拒绝，重复 approve 不重新调用 recorder。
- 包文件真实写入、删除、替换被共享模式拒绝；关闭 guard 后恢复正常写入。
- 两个 Broker 预约互斥；同时验证该互斥不等于禁止包生产者进入。

具体阻塞测试为
`test_exclusive_broker_reservation_does_not_prevent_new_package_process`：
先持有安装所属维护文件的排他句柄，再启动该虚构安装 `current/Echo.exe` 的受控 C#
记录器；通过 native image 查询确认它确实运行在同一安装目录，且仍在运行。
因此“最后一次进程检查为空 + Broker 文件排他”不能阻止检查后的新包实例。
当前桌面入口与第三方 helper 没有消费该维护预约，不能将其签发为 `LeaseStatus.HELD`。

固定 Velopack 1.2.161 的
[等待处理](https://github.com/velopack/velopack/blob/1.2.161/src/bins/src/shared/util_common.rs)
在等待错误后继续；其
[Windows apply](https://github.com/velopack/velopack/blob/1.2.161/src/bins/src/commands/apply_windows_impl.rs)
还会强制停止安装根目录内的包进程。只修句柄权限不消除误杀新实例的风险。
本轮依照用户“遇到实际安全阻塞则给出证据后停止”要求停止安装侧开发，没有拼接一个
最终枚举之后仍可抢入的新安装器路径，也没有把 fictional evidence 当作 OS 证明。

继续安装交接的前置条件：实现并实测覆盖全部受管启动入口的持续维护准入，证明
Broker/更新器/Hook/新版重启的准入生命周期；然后实现独立宿主、私有 IPC、完整
Windows WitnessSource 和安全 apply 边界。不能仅凭 native primitives 宣告这些已完成。
这是仍待实现的具体依赖，不是本轮设计或验收已交付。

另有发行身份待核验：P1 固定 packId 为 `Lindreams.Echo`，
[A4 构建记录](2026-10-14-a4-test-setup-build.md) 记录固定工具链下含点号 packId 的
Post-process 失败。该历史冲突未在本轮重建或修复；未擅自改名、迁移已有安装或升级 SDK。

## 验证

已验证复用 Echo 虚拟环境满足当前基础/dev/gui 依赖，显式设置 PYTHONPATH 到目标
worktree/src，实际导入路径属于本 worktree，未修改共享环境。

- 开始前 focused：173 passed。
- 协议新增回归先复现状态覆盖、拒绝后 apply、字段类型绕过、末次检查后授权撤销与无效
  authorization；GREEN 后协议测试 134 passed。
- 原生测试首轮 5 failed，身份绑定新增 8 failed，分别实现后 GREEN；最终原生 15 passed。
- 最终 focused（协议、原生、P1、SDK 本地虚构 feed、A3、GUI 及退出子进程）：276 passed。
- Full 已尝试，但未完成/未通过：共享环境的 `jieba/dict.txt` 缺失，分析相关测试大批
  失败；单独复现 `tests/test_analysis_reports_service.py` 首项得到同一 FileNotFoundError。
  对应分析/tokenizer 文件未修改，该失败不是更新代码的 RED。依赖版本元数据满足约束
  并不代表包资源完整；更新 focused 不依赖该资源，故其结果仍有效。
  在确认环境损坏且已检查其他 worktree/已知 Echo 环境无可用解释器后，主动停止 Full，
  退出码 1；不把它写成完成的回归或统计通过总数。未自动安装/修复共享环境。
- `git diff --check` 通过，变更限于本记录列出的更新源码、测试和架构/状态文档。

当前功能不满足“等待 0.2.0 联合验收”：Windows 原语和协议修复可以审查，完整 Broker 与
A3 安全安装交接尚未完成；P1 生产门始终关闭。
