# Echo 发布与维护状态

本文只维护当前发布基线、现存风险及验证证据边界。核对日期：2026-10-16。
当前实现与已发布二进制分开判断；历史研究中的“未合入／未发布”只描述记录当时。
架构与数据语义见 [ARCHITECTURE](../ARCHITECTURE.md)、
[DATA_SEMANTICS](../DATA_SEMANTICS.md)，开发操作见 [DEVELOPMENT](../DEVELOPMENT.md)；
后续安排由负责人确认并在 [ROADMAP](ROADMAP.md) 维护。

## 当前发布基线

### 已发布 v0.2.1

负责人于 2026-10-16 确认 v0.2.1 已正式发布，并在本机完成正式
v0.2.0 → v0.2.1 在线升级、QQ 会话列表加载及分析报告生成验收。
速度改善未被明显感知，不能据此声称全面提速；跨机器 QQ 连接仍待验证。
这是负责人提供的本机验收事实，本轮未重跑真实来源或正式发行验收。
只读查询 [v0.2.1 Release](https://github.com/lindreams/echo-chat-analyzer/releases/tag/v0.2.1)
确认非 Draft／Pre-release，发布时间为 2026-10-16 09:21:47 UTC。

版本元数据已更新为 0.2.1，QQ 可靠性修复与必要脱敏诊断已完成本地回归。
已重建固定 NapCat candidate，并核验全部模板进入 Frozen 与正式身份 Setup 包。
发行合同检查 52 passed；真实 0.2.0 Setup → 0.2.1 Setup 原位升级、两版 GUI
原生退出 0、安装文件校验及卸载后虚构数据保留通过，测试注册项和快捷方式已移除。
上述发布前回归未连接真实聊天来源，未验证跨机器连接或正式 GitHub 在线更新。
复用既有实验身份 A/B 包重跑本地 feed：GUI 检查、下载、确认、五项 SUCCESS、安装与
自动重启通过，A/B 原生退出 0、虚构数据保留。其更新核心与当前源码编译结果一致；
该实验不等同于当前正式身份包通过 GitHub feed 更新。

首轮产物齐备后的 Full 为 1563 passed、2 skipped、2 failed，原始失败记录保留。
`test_registry_proves_real_fictional_job_tree_exit` 在 Job 计数归零后立即观察句柄，
虚构原生实验确认 signaled 状态有短暂滞后；测试改为有界等待，保留全部句柄退出断言。
旧凭据请求的 WinError 10053 可由分开发送请求头／体稳定复现，桥接层现对有界普通请求
先丢弃接收体再结束拒绝响应，保持认证拒绝与请求大小限制；已更新 pins 并重建正式资产。
最终 Full：1565 passed、2 skipped（396.50s），跳过项均为 Windows symlink 权限；
相关 Focused 97 passed，发行／更新 Focused 87 passed。新包已重新通过真实 Setup 升级验收。
Echo.exe 与 Setup 未签名；发布及本机正式在线更新的后续验收见本节开头。

### 已发布 v0.2.0

- [v0.2.0](https://github.com/lindreams/echo-chat-analyzer/releases/tag/v0.2.0)
  于 2026-10-14 正式发布，非 Draft／Pre-release；现已由 v0.2.1 接续。
  本地与远端 tag 均指向 `fab1eb2e997ad8efc6ee5451d378f21afbc9628b`，
  不把当前工作分支等同于该发行源码。
- 五个资产已在线核对：`Echo-0.2.0-windows-x64-Setup.exe`、
  `Echo-0.2.0-windows-x64-Setup.exe.sha256`、
  `Lindreams.Echo-0.2.0-win-x64-stable-full.nupkg`、
  `releases.win-x64-stable.json`、`SHA256SUMS.txt`。
  Setup 公开 SHA256 为 `c9140b85284295c41eeec19ad26ea7f7b154b41a5d184d99f2ccda3595cd54e8`。
  本次核对 Release 元数据、校验清单及 feed 身份／大小／哈希的一致性，未重新下载二进制或复做发行验收。
- v0.2.0 交付 Windows x64 Setup 与应用内发现、下载、校验、安装和自动重启；
  正式更新身份为 `Lindreams.Echo`／`win-x64-stable`。
  [v0.1.0](https://github.com/lindreams/echo-chat-analyzer/releases/tag/v0.1.0)
  Portable Pre-release 保留，不能应用内升级到 Setup，需手动安装。
- 发行记录中的 Setup 与主程序未做 Authenticode 签名；本次未重新检查二进制签名。
  SHA256 证明文件一致性，不代替发布者签名或跨机器兼容性验证。
- 当前源码锁定 NapCat 4.18.34 与 Echo patch；资产合同见
  [runtime pins](../scripts/qq_napcat_runtime_pins.json)。
  当前源码保留本地 Echo Report 文件分享，独立纪念卡图片生成已退休；
  既有图片不迁移或删除，不据此改写 v0.2.0 已发布包的行为。

## Shutdown 与安装安全边界

普通退出可以在有界清理后离开；退出完成、窗口消失或退出码为 0，均不单独构成安装授权。
更新须经用户确认、空闲及安装身份检查、关闭任务入口、该次 shutdown 证据和包复验，
才调用官方 Velopack 交接并重启。软件内卸载同样要求可信清理与当前安装核验；
升级／卸载不得删除用户报告与配置，也不得管理用户自己的 QQ／微信进程。

[ShutdownResult](../src/qq_chat_analyzer/application/shutdown_models.py) 的安装准入要求以下五项
各出现恰好一次且全部为 SUCCESS：Direct DB 清理、保留的临时报告清理、QQ runtime 终止与凭据退役、
来源生命周期、GUI workers 静止。缺项、重复项、未知项、FAILED、TIMED_OUT 或 UNKNOWN 均拒绝；
普通汇总 status 为 SUCCESS 并不单独证明证据完整，历史缓存或调用方伪造结果不能替代本次关闭。

未使用的生产来源可通过已知无资源路径证明空闲；已使用来源缺少完整停止／drain 证明时保持 UNKNOWN。
微信 helper 进程树退出、Python reader／PIPE／句柄释放与 Node CleanupHook 完成是不同证据：
前两项成功不证明最后一项。UNKNOWN 是证据不足时正确的安全结果，不应为了让更新可用而改成 SUCCESS。

## 现存风险与验证缺口

以下按当前源码或已有记录描述，不将“存在风险”写成已发生用户损失，也不反推所有缺口均存在于发行包。

| 事项 | 已知事实与尚未证明的范围 |
| --- | --- |
| QQ 跨机器兼容性 | 已有本机及部分用户基本使用证据；另有机器因 QQ 进程冲突检测无法连接，根因未确认。保留真实兼容性问题，不称已修复，不扩大为所有 Windows／QQ 环境通过。 |
| 微信 shard 完整性 | **已确认的错误处理缺口／潜在漏读风险**：`_table_exists()` 将 WeChatDatabaseError 转为 False，故障 shard 可能被视为不存在目标表。正常多 shard 合并已有测试，不证明异常时读取完整；未确认真实数据丢失。会话计数的独立 unknown 处理也不能代替消息读取的完整性证明。 |
| 来源生命周期与 CleanupHook | **证据缺口**：已有 helper 所有权、退出与资源回收检查，但已使用 QQ／微信来源仍缺全局生命周期证明，Node CleanupHook 也无可信完成证明。相关 UNKNOWN 拒绝安装是当前预期边界，不是已确认的资源泄漏；补证前不得放宽准入。 |
| 微信断开与写回并发 | **验证不足／潜在竞态**：取钥请求有 generation 与提交锁，但 disconnect、独立配置保存与在途取钥写回的完整并发行为未充分验证。局部代际保护不等于所有取消／断开顺序安全；目前不声称已发生密钥回写或用户数据损坏。 |
| UserProfile repr | **已确认的隐私防护缺口**：默认 dataclass repr 包含 speaker、speaker_key、昵称等字段；DTO 的 repr=False 不覆盖下游全部模型。不得记录／上传这些对象；尚无由此已泄漏真实信息的证据，全面 repr 防护与回归仍待补齐。 |
| GUI 原生退出异常 | 历史出现过 `0xC0000005`；后续隔离源码与 Setup 更新实验有正常退出证据，但具体原生根因未确认。不能称所有环境已修复，也不能凭旧现象断言当前必然复现；任意 native hang 与长期稳定性仍非已验收保证。 |
| 微信 runtime 迁移边界 | 当前已有统一的 CLI／DLL 成对解析，且有[不自动混配的回归](../tests/test_wechat_environment_config.py)，不能照搬历史“逐项补路径造成混配”的缺陷结论。配置仍不能区分旧 bundled 与用户 custom：完整旧路径保留，半有效配置不自动补齐；这是保守兼容边界，不等于全部迁移场景已真人验收。 |
| 第三方图片来源与授权 | [NOTICE](../NOTICE.md) 已披露 QQ 图片来源边界：仅部分图片有明确同步记录，其余逐文件来源未核实；尚无可核实的权利人再分发／修改授权。来源披露、代码 MIT 或 Echo MPL-2.0、非商业运营均不能作为图片已获授权的证明。其他第三方材料仍受各自许可约束，不能称已全面合规审查。 |

## v0.2.1 Setup 体积基线与 LAC 候选验证

本地正式 `Lindreams.Echo-0.2.1-win-x64-stable-full.nupkg` 的 SHA256 为
`e7609384904b8db3b786a110612877f78a5a6ed7d9f4cae076bd02c6581cf10f`，
与上述 Release 的资产 digest、125,800,799 bytes 大小一致，未下载大型资产。
ZIP 中 1,425 项，解压总量 295,763,979 bytes；各项 `compress_size` 合计
125,513,161 bytes，ZIP 目录等开销 287,638 bytes。以下使用 MiB（1,048,576 bytes），
占比分母为 nupkg 文件大小；运行时内图片归其运行时，分类互斥。

| 类别 | ZIP 压缩量 MiB | 包占比 |
| --- | ---: | ---: |
| Qt／PySide6／Shiboken | 36.74 | 30.62% |
| 微信运行时 | 35.82 | 29.85% |
| Python DLL／扩展／标准库 ZIP（不含 Qt 绑定与其他依赖） | 5.60 | 4.66% |
| NapCat | 4.71 | 3.93% |
| 图片（frontend、assets、微信指引） | 7.30 | 6.08% |
| 应用、jieba、其他依赖与更新组件 | 29.54 | 24.62% |

基线中的瘦身机会如下；本轮仅实施 LAC 数据排除，其余均未修改：

- jieba `lac_small` 数据仍占 11.48 MiB；spec 已排除其代码，tokenizer 只使用
  普通 `lcut`／`load_userdict`，数据采集仍带入模型。这是最直接的候选，理论包收益约
  9.57%；另有 `analyse/idf.txt` 2.11 MiB，现役源码未见调用，须核实 hook 和运行时后再决定。
- Qt 带入 Quick／Qml／QmlModels 约 5.42 MiB、Pdf 约 2.36 MiB、翻译 1.94 MiB，
  现役源码未直接导入这些模块。需查清插件传递依赖和中文显示要求才能评估可删范围，
  上述体积不是可保证收益。`opengl32sw.dll` 单项 7.33 MiB，可能参与图形兼容，不能直接删除。
- 微信 `node.exe` 占 32.92 MiB，但当前 helper 需要 Node，不能把“最大文件”当作可删项；
  NapCat 仅 4.71 MiB，正式 ZIP 未包含匹配 linux／darwin／win32-arm64 名称的 native 文件，
  不能再以删除这些平台文件计算收益。Python 核心也未发现可安全直接删除的证据。
- QQ 表情约 4.97 MiB、微信表情 0.71 MiB、品牌图 1.59 MiB；其中报告 wordmark
  单项 1.51 MiB，可评估尺寸与编码，收益上限受这些现有体积约束，须真人核对画质与授权边界。

正式 Setup 为 133,362,527 bytes（127.18 MiB），比 nupkg 多 7.21 MiB；
差额包含封装开销，未解包归因，不视为全部可节省。

0.3.0 前收尾确认官方 PyInstaller jieba hook 使用 `collect_data_files('jieba')`，
模块 excludes 不阻止模型数据被收集。spec 现仅过滤 `jieba/lac_small` 的数据条目，
保留普通词典、用户词典加载能力和其余 jieba 资源，不改依赖、pins 或运行时。
使用既有 Windows 构建入口、全新输出目录与隔离用户目录生成 `EchoFinalLab`／
`win-x64-final-lab` 实验候选，未修改正式包、Tag、Release，也未安装或启动候选。
候选 nupkg 为 113,758,313 bytes（108.49 MiB），比基线减少 12,042,486 bytes
（11.48 MiB，9.57%）；Setup 为 121,320,041 bytes（115.70 MiB），同样减少约 11.48 MiB。
逐文件比较仅删除 22 个 LAC 文件、无新增应用文件；QQ／微信运行时逐文件一致，
其余内容变化为 Echo.exe、标准库 ZIP 与实验身份 `sq.version`，不把全部字节差归因于模型。
该候选构建于本轮 shard／repr 修复之前，仅验证瘦身，不能用作本轮最终发行验收。
分词／收集合同相关 17 passed；候选 Frozen／Setup 合同 17 passed。

## 验证证据及边界

### 发布后体验问题调查（2026-10-16，源码）

- 书写动画：`ProcessingAnimationWidget` 在 GUI 线程按 16ms 定时刷新，
  每帧重画纸张纹理、笔迹和笔；后台分析使用 Python Qt worker，仍可能竞争 GIL。
  隔离环境下用模型驱动 360 帧 800×460 的 QImage 书写渲染，单帧中位数 4.02ms、
  P95 4.44ms、最大 53.72ms；另取 60 帧 profile，纸纹 `_grain` 占累计绘制时间约一半。
  这只是合成渲染测量，不包含真实分析、窗口合成与高 DPI，孤立最大值不证明稳定根因。
  尚未可靠复现用户所见卡顿，不修改帧率、纹理或交互，待真人确认具体阶段后决定。
- 关闭浏览器报告后的残留：`show_outcome` 主动保留最近报告入口和保存提示，
  `_return_to_workspace_after_success` 明确保留；报告通过系统浏览器打开，没有关闭回调。
  首页、来源切换、本地数据页与关于页已有清除路径。关闭浏览器与在 Echo 内离开页面
  是不同事件；负责人已确认继续保留最近报告入口，本轮不监听外部浏览器关闭。
  动画及报告／导航相关定向回归 55 passed，不能代替真人流畅度和视觉验收。

| 证据 | 可以支持的结论与限制 |
| --- | --- |
| [标准更新收敛记录](research/2026-10-14-standard-update-convergence.md) | 记录隔离 A 0.2.0 → B 0.2.1 的实际安装更新、自动启动、五项 SUCCESS、A/B 原生退出 0、文件及虚构数据哈希、实验卸载保留数据。实验改用了隔离身份、本地 feed 和用户目录，不能当作全部生产来源连接后或跨机器通过。该记录结束时尚未发布，后续正式发布由上面的 Release 证明。 |
| [A2 退出合同记录](research/2026-10-12-a2-exit-contract.md) | 保存正常／兜底退出、完整证据与 UNKNOWN 拒绝的历史验证。其“首页不批准更新”和早期 helper 所有权缺口描述属于当时版本；当前已有未连接来源的完整空闲路径及 helper 资源治理，不能原样作为当前结论。 |
| [A4 卸载记录](research/2026-10-14-a4-setup-uninstall.md) | 记录隔离安装卸载与虚构数据保留；部分拒绝分支只有自动化证据，GUI 原生退出码未在该轮人工报告直接记录，不能据此补写全部卸载场景通过。 |
| 现役回归 | [shutdown](../tests/test_shutdown_results.py)、[空闲证据](../tests/test_idle_shutdown_evidence.py)、[安装交接](../tests/test_update_install_handoff.py)、[微信 helper 资源](../tests/test_wechat_key_helper_resources.py)、[shard](../tests/test_wechat_db_source.py) 分别保护其合同；测试存在或局部通过不代表发行二进制与真人场景已重新验收。 |

发行收尾提交 `ee8556a` 记录最终 Full、发行专项及封印检查通过；
标准更新研究保留了此前一次 Full 的回环连接中止失败及节点／文件重跑通过记录，
两者属于不同时间的验证，不能用重跑覆盖原失败或声称偶发根因已查明。
此前 GUI 小优化运行上述定向回归及更新相关回归（57 passed），并检查 diff 格式；
本轮审核实际 diff 后保留成果，未重复这些 GUI 回归，也未重跑正式发行验收或 Full。
更新确认框的浅色呈现、中文按钮与
默认／Esc 取消已有 Qt 自动化覆盖，Windows 原生主题、高 DPI 与焦点视觉仍待真人检查。

历史故障根因见 [BUG_JOURNAL](BUG_JOURNAL.md)；新增问题只提供虚构样本或脱敏统计，
不公开真实聊天、日志、私人路径和凭据。后续修复、签名与第三方资产的授权补证／替换／停止分发
由负责人确定范围；不在本文复制未来功能计划，也不因文档订正宣告风险关闭。
