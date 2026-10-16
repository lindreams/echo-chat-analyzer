# Architecture

本文记录当前源码的架构、资源所有权及必须维持的安全合同。实现事实、已有测试与设计要求分别说明；存在测试不等于当前发行或真人验收通过。发布风险与验证状态见 [HARDENING](docs/HARDENING.md)。跨来源字段与统计定义见 [DATA_SEMANTICS](DATA_SEMANTICS.md)。

## 1. 系统目标、入口与整体结构

Echo 是隐私优先的本地聊天分析工具。桌面来源为 QQ Direct DB 与微信数据库；真实聊天数据只在本机处理，不上传、不进入诊断日志或测试资产。更新检查访问网络，不意味着聊天处理需要远端服务。

- Desktop：`echo-gui`、`python -m qq_chat_analyzer.gui` 与 frozen 入口共同进入 [desktop.py](src/qq_chat_analyzer/desktop.py)，再进入 GUI。
- CLI：`echo-chat` 经应用服务分析本地文件，支持 `qq-db-json`、`wechat-db-json`、`detailed-json`、`chatlab-jsonl`、`cli-json`。它不是 GUI 的第三种来源，不直接获取 QQ/微信数据库。
- QQ 正式链路为 NapCat 启动／登录与 Direct DB 快照。QCE、旧 QQ JSON/JSONL 和外部 miyu 实时获取已退休，不得通过 hint 或 fallback 恢复；微信 CLI 导出格式仍可本地导入。

下图表示运行时调用／数据交接，不是 Python import 许可图：

```text
Desktop → gui/app.py（组合根）→ GUI → ChatAnalyzerFacade
                                       ├─ 来源连接／获取服务 → Provider → 临时 payload
                                       ├─ AnalysisApplicationService
                                       │    → ImportService → Adapter / Parser
                                       │    → RichMessage → ChatMessage 单向投影
                                       │    → scope / 智能过滤 / 质量过滤
                                       │    → 清洗、分词、Analysis Core → AnalysisReports
                                       │    → Presentation → Echo JSON / HTML
                                       └─ Report Package 发布与 Catalog
CLI ─────────────────────────────────────→ AnalysisApplicationService
```

## 2. 模块职责、依赖方向与组合根

| 模块 | 现役职责及边界 |
| --- | --- |
| Provider | 外部 RPC、数据库只读查询、工具调用与原始导出；不做分析和应用流程编排。数据库 Provider 也处理来源 SQL／原生记录，不能概括成完全不理解来源语义。 |
| Adapter / Parser | 解析来源格式并生成消息事实；不拥有连接、取钥、过滤策略或分析。现役模块位于包根目录。 |
| ImportService | 路径与文件发现、格式识别、路由 Adapter / Parser，返回 ImportOutcome；不执行分析或报告发布。 |
| 来源服务 | 编排来源准备、会话查询和 payload 获取；由各来源自己的 owner 管理资源。 |
| AnalysisApplicationService | 导入、过滤、词法处理、调用分析器、组装结果并导出分析产物。CLI 与 GUI 共用这一分析流程。 |
| ChatAnalyzerFacade | 应用门面：来源分派、配置与错误归一、分析请求、输出所有权、报告包、shutdown 及安装交接；不实现格式解析或统计算法。 |
| Analysis Core | 消费统一消息、token 与必要的 Rich 事实，产生统计报告；不获取数据库、不依赖 GUI 或第三方工具。 |
| Presentation | 报告到视图的转换、格式化、资源装配与 JSON/HTML 输出；具体 I/O 边界见第 6 节。 |
| GUI / CLI | 输入、状态、进度与错误展示。GUI 业务动作经过 Facade；CLI 调用分析应用服务。 |

[gui/app.py](src/qq_chat_analyzer/gui/app.py) 是组合根例外：它导入应用服务并注入依赖，为 QQ 创建共享 QQRuntimeSession、ProviderFactory 和延迟 SourceBundle，为微信延迟创建连接／设置／读取服务。不能把“GUI 控件不得绕过 Facade”扩大为“gui 包只能 import facade”。GUI 还使用应用 DTO、状态和结果契约。

依赖约束是：分析核心不依赖 application、presentation、gui 或 providers；业务服务不依赖 GUI；界面业务代码不直接操作 Provider / Adapter / Analyzer。这不是“只有 Provider 可以 I/O”的规则：ImportService、配置、取钥、报告导出和 Catalog 都有各自明确的 I/O 所有权。

代码入口：[facade.py](src/qq_chat_analyzer/application/facade.py)、[analysis_service.py](src/qq_chat_analyzer/application/analysis_service.py)、[import_service.py](src/qq_chat_analyzer/application/import_service.py)。

## 3. 数据模型、Adapter 与统一分析链

表情包数据复用同一 Rich / 投影配对及过滤链：Adapter 在 ExpressionContent 附带
StickerIdentity，核心 `analysis/stickers.py` 提取逐次发送事实；应用层
`application/sticker_media.py` 仅在显式可信根内验证有来源摘要的原件，结果通过
`AnalysisResultDTO.stickers` 返回，不进入现有报告序列化。媒体读取不属于分析核心，
不新增数据库入口、磁盘缓存或网络获取。支持边界与本机验收见
[STICKER_DATA](docs/STICKER_DATA.md)。

### 双消息模型

[RichMessage](src/qq_chat_analyzer/rich_message.py) 保存发送者身份、内容段、表达、reply / mention 等结构化事实；[ChatMessage](src/qq_chat_analyzer/message.py) 是现有过滤和多数统计的消息输入。两者都是现役模型，ChatMessage 不是唯一跨层模型。

[legacy_projection.py](src/qq_chat_analyzer/legacy_projection.py) 单向投影 RichMessage：只拼接 TextContent 到正文，同时保留身份、会话、时间与消息属性。表达与非文本段不会伪造为正文，也不能由 ChatMessage 反推完整 RichMessage。部分本地文件导入路径只有 ChatMessage。

[ImportOutcome](src/qq_chat_analyzer/application/import_outcome.py) 同时保存消息与投影配对。过滤保留原 ChatMessage 实例；应用服务按 `id(legacy_message)` 关联仍存活的 RichMessage，而非按可能重复／缺失的 message_id 或复合字段猜测。被过滤消息不能向保留消息提供表达或非文本事实。

### 单次分析

1. 来源服务产生 payload，ImportService 选择 Adapter / Parser。
2. 最终 Analysis Scope Filter 按统一时间语义过滤；来源 SQL 时间条件仅用于减少获取量，不能替代最终过滤。
3. 智能过滤分发送者、整条消息模板、停用词三个层次；质量过滤后再进行分析。停用词只作用于词法，不应代替整条模板过滤。
4. 清洗／分词生成全局及发送者 token，核心生成 AnalysisReports，应用服务触发导出。

这是统一编排，不表示所有处理都完全来源无关：应用词法路径向 `clean_text` 传入 platform，[cleaner.py](src/qq_chat_analyzer/cleaner.py) 仍有微信特殊处理；表达资源准备也保留来源映射。应把原生字段和第三方工具隔离在来源边界，不能把这一设计方向写成整个现役分析链已无平台分支。

身份、未知归属、顺序、会话和 authored lexical text 的唯一详细定义在 [DATA_SEMANTICS](DATA_SEMANTICS.md)。

## 4. QQ 连接、授权代际与 Snapshot 所有权

### 连接动作与被动状态

```text
GUI → Facade.start_qq_auth_flow → QQAuthBridge → Echo-owned launcher → QQ / NapCat
GUI → Facade 状态接口 → ConnectionManager → QQConnectionService → NapCatQQProvider
GUI → Facade.list_sessions / analyze_session → QQDirectDatabaseImportService
```

- Auth Bridge 负责工作区准备、实例身份校验、授权启动、QR freshness、取消与断开；新授权只接受本 session 更新过的 QR。
- 自有旧 runtime 清理失败时保留 registry 所有权并拒绝新启动；凭据退休阻止旧客户端继续使用，但不构成进程已退出的证据。
- ConnectionManager 映射被动连接／授权等待状态，不拥有另一套 connect 动作。QQConnectionService 把认证 RPC 状态转换为应用状态。
- QQSetupService 保留配置读写、路径准备和被动 runtime 查询。QQRuntimeManager / BundledQQRuntime 仍有底层生命周期能力与测试，但正式 GUI 启动由 Auth Bridge 发起。
- 有效登录可使 `available` / CONNECTED 成立；`direct_db_ready` 还要求数据库、passphrase、Snapshot API 等能力。获取服务完成 startup recover 后才进入 ACTIVE。三者都不证明清理或退出完成。

### 四种代际标识

| 标识 | 约束对象 |
| --- | --- |
| 启动凭据 | QQRuntimeSession 为每次启动生成本地 RPC 凭据，通过子进程环境交给 bridge；不从普通配置恢复，也不写入报告或日志。 |
| Worker boot_id | bridge 实例启动时生成；Provider 与 snapshot client 绑定同一个已认证 Worker，不能只凭固定端口健康接管。 |
| 连接 epoch | 应用服务请求准入代次；请求在 readiness 前捕获 epoch，在正式准入时复验，防止旧请求进入新连接。 |
| Snapshot generation | 单次快照身份及其 manifest / 数据库；不是 Worker 或连接身份。 |

[Facade](src/qq_chat_analyzer/application/facade.py) 显式连接时，在同一 reconnect guard 内重置 Direct DB epoch 和 ProviderFactory 连接绑定，随后才执行授权 I/O。活动 startup / acquisition 阻止重连。普通配置 `invalidate()` 只清缓存，不更换当前连接 owner。

[NapCatQQProvider](src/qq_chat_analyzer/providers/napcat_qq_provider.py) 与 [snapshot client](src/qq_chat_analyzer/providers/qq_direct_snapshot_runtime.py) 是本地认证 RPC 客户端，不创建 Worker。旧 client 不得升级为新启动凭据或新 boot_id；Worker 变化锁定为需要显式重连，旧 acquire、metadata、cleanup、recover 不重放到新 Worker。[bridge.mjs](scripts/qq_napcat_plugin/bridge.mjs) 在调用允许的方法前校验认证与绑定；[plugin](scripts/qq_napcat_plugin/index.mjs) 在 Worker 内注册 Snapshot API。

### 获取与一致性合同

[QQDirectDatabaseImportService](src/qq_chat_analyzer/application/qq/qq_direct_database_import_service.py) 负责 startup、准入、payload 与 drain；[snapshot helper](scripts/qq_direct_db_snapshot/snapshot.mjs) 负责串行快照操作：

1. startup recover 成功才准入；短暂 API 未就绪可重试，真正恢复失败保持关闭。
2. acquire 前清理旧 generation / staging / 自有遗留明文；清理失败拒绝解密。
3. main+WAL+SHM 获取固定 SHM 见证的 committed boundary B，验证 WAL header / salt / checksum、完整前缀、main identity/stat/content 稳定性和 checkpoint witness。允许 B 后 append；checkpoint、main 改变、reset/truncate 或无法证明一致性均失败关闭，不回退 main-only。
4. staging 加密合并文件交给 NapCat 进程内解密；解密前后校验 dev / ino、大小、纳秒级 mtime / ctime 强见证，使用 descriptor fstat 保持文件身份比较一致。输入变化、无效见证或本人身份变化禁止发布。
5. 删除 staging 加密输入后，写入 manifest 并原子发布 generation。客户端只对 snapshot_unstable 在共享总预算内有限重试，每次仍经过全部 guard。
6. 应用校验 generation / manifest / 数据库 / self identity，只读查询；同一 generation 内选择会话并物化 payload。失败不读取旧 generation。

一致性实现见 [main_wal.mjs](scripts/qq_direct_db_snapshot/main_wal.mjs)。这里记录必须维持的拒绝条件，不将历史真人验收扩大为跨 QQ 版本保证。

### lease、清理与资源边界

[workspace.mjs](scripts/qq_direct_db_snapshot/workspace.mjs) 以 Windows OS 独占文件 lease 覆盖获取前 recover、发布、消费直至 cleanup；进程内变更另行串行。lease 由隐藏 PowerShell 子进程持有，stdin EOF／进程结束释放，不以 PID 存活猜测接管。

- source 与 workspace 必须隔离：Windows 路径比较归一大小写，拒绝同目录及相互嵌套；symlink / junction / reparse 防护不能因字符串路径看似安全而省略。
- root / staging owner、generation manifest、固定文件 allowlist 共同限定删除范围；先验证全部候选，再删除，所有权证明最后移除。未知成员或无效所有权不能被递归清除。
- 不相关 generation 的 cleanup 不释放当前消费者 lease。清理／恢复失败阻止正常返回；清理错误不能被先前的获取／解密错误掩盖，保留可恢复残留，不包装为成功。
- 已准入任务捕获原 client，读取、metadata 和 cleanup 都维持原代际；cleanup 本身仍算活动获取，不能被重连挤出。
- generation 中的 plaintext DB 在会话查询完成或 payload 物化后 cleanup，早于下游分析；临时 qq-db-json 仍含明文，由 acquisition 上下文在消费结束／异常后清理。二者均不作长期 cache。

GUI 取消会话结果只使请求失效，不中断底层 acquisition / cleanup。授权取消绑定具体 Event，迟到取消不能关闭新授权；迟到 launcher 返回的自有资源必须关闭。

`disconnect_qq()` 结束授权／运行会话，不执行完整 Direct DB drain / recover，也不提供全部资源释放证明。正常 shutdown 另见第 7 节；Worker 异常丢失时的失败关闭不代表残留已经清除，须由后续合法 recover 处理。

## 5. 微信连接、取钥与数据库读取

### 服务与读取链

GUI 经 Facade 调用微信 setup、连接状态与导出服务。延迟 SourceBundle 共享 ProviderFactory，状态查询与读取使用同一配置。主页只读 setup 检查不提前构造取钥 helper。

- [WeChatDataDetector](src/qq_chat_analyzer/application/wechat/wechat_data_detector.py) 发现候选数据位置，不证明当前账号可读。
- [WeChatSetupService](src/qq_chat_analyzer/application/wechat/wechat_setup_service.py) 协调位置、取钥、保存配置、Provider 失效和读前验证。
- [WeChatConnectionService](src/qq_chat_analyzer/application/wechat/wechat_connection_service.py) 区分数据位置、密钥与 runtime 探测；available 不是 session.db 已读通或 helper 已清理的证明。
- [WeChatDatabaseProvider](src/qq_chat_analyzer/providers/wechat_database_provider.py) 通过 wcdb_cli 读取；连接准备验证实际数据库可读。错误密钥／账号位置不能降级为普通空会话。仅在唯一可读候选且再次验证成功时自动恢复位置，歧义不猜测。
- [WeChatExportImportService](src/qq_chat_analyzer/application/wechat/wechat_export_import_service.py) 编排会话查询、时间范围与 export_only；Facade 将导出写入本次 scratch，交给统一分析服务。独立 execute 接口也可直接接 ImportService，不拥有取钥或 SQL。

### helper 唯一 owner

[WeChatKeyService](src/qq_chat_analyzer/application/wechat/wechat_key_service.py) 的 acquire 请求独占 helper 生命周期；取消只发信号，不表示资源已释放。排队前已取消的请求不能启动 helper，旧 owner 未完成／仍有失败资源时不能启动第二个 helper。

Windows helper 创建即进入 Echo 自有 Job，只管理 helper 后代，不纳管或终止用户的 Weixin.exe。清理在后台 owner 执行：整树退出、reader join、PIPE、process / Job 句柄共用一次 deadline。失败保留资源及所有权，后续连接 worker 可在同一准入机制下 retry_cleanup；不得由 GUI 与旧 owner 并发回收。

Setup 的请求 generation 与提交锁保护取钥请求之间的代际提交顺序，并检查请求是否已取消；不能将这些局部隔离保证扩大为所有断开、取消、写回场景均安全。disconnect()、独立配置保存与在途请求之间的完整并发行为尚未得到充分验证。断开清除保存的密钥及进程内 key 状态，保留数据位置／runtime 配置，不删除聊天数据，也不证明 helper 或来源完整退出。

后台 shutdown 封闭取钥准入、有界等待 owner，并传播失败／超时。Job 整树为空、Python 资源释放、Node CleanupHook 完成是三种证据；已使用 helper 即使前两项成功，仍缺少最后一项及完整来源退出证明，当前保持 UNKNOWN，不能授予更新安装。

### 分片与身份

同一 session 的 Msg_* 表可分布于多个 message_N.db。Provider 查询全部匹配 shard，每个应用相同的包含端点的 epoch-second 时间条件，再全局按 create_time 排序，最后应用显式正数 limit；正常消息读取默认不限量。wcdb_cli 的 no-limit / limit=0 必须持续 step 到 statement done，不能隐含截断。

self identity 只按已证明的命名空间映射；目录后缀不能无证据截断，详见 [DATA_SEMANTICS](DATA_SEMANTICS.md)。

## 6. Analysis、Presentation 与 Echo Report

### 统计与展示

应用服务驱动 cleaner / tokenizer、基础 analyzer 和 analysis/analyzers，组装 [AnalysisReports](src/qq_chat_analyzer/analysis/models.py)。Conversation Sessions 在核心计算；Presentation 消费其结果，不另建统计口径。表达 token 与正文词法排名分离，不能让表情展示名、reply 引用或自动 mention 污染语言画像。

CLI 仍通过向 AnalysisApplicationService 注入 legacy writer，按条件生成 CSV、词云等附加产物。

发送者／会话名称映射由调用方经请求 DTO 注入，应用服务转交分析器；已有稳定 sender ID 时不得用展示名覆盖，缺失稳定 ID 时，现役 stable_sender_key() 允许回退到 sender 文本，但这种回退不具备可靠的稳定身份保证。DTO 的名称映射使用 repr=False，不代表下游所有报告模型同样受到保护，见第 8 节。

[presentation/builders.py](src/qq_chat_analyzer/presentation/builders.py) 负责报告到视图的选择、格式化与名称解析；其职责不等于重新分析原始消息。Presentation 不只是“只依赖报告模型的纯函数”：builders 使用共享 identity_names 与表达资产模块，[expression_assets.py](src/qq_chat_analyzer/presentation/expression_assets.py) 读取资源，[echo_serializer.py](src/qq_chat_analyzer/presentation/echo_serializer.py) 装配前端／图片资源并写 JSON / HTML。它不读取来源数据库、不拥有连接，也不依赖 Qt。

### 报告包与历史所有权

[package_echo_report](src/qq_chat_analyzer/application/echo_report_export.py) 发布四文件包：echo-report.html、echo-report.json、metadata.json、README.txt。Report Package 是持久分析历史的事实来源；不存在另一套 analysis_history.jsonl 历史索引。

- 发布在 canonical reports_root 的 `.echo-report-<uuid>` staging 完成；同 root sidecar 绑定 root / staging / sidecar 文件身份，并持有 OS 发布锁。完整写入后 rename 为正式包，staging 不参与历史列表或存储统计。
- [report_staging.py](src/qq_chat_analyzer/application/report_staging.py) 只恢复有效自有且未被活跃发布锁定的 staging，拒绝 reparse、身份变化和未知成员；仅名称前缀不构成删除授权。恢复失败保留安全诊断，不能把残留伪装成正式报告。
- 发布成功不自动淘汰旧包；发布失败不删除旧报告，已生成产物留在当前 output，受该 output 自己的生命周期管理。
- [ReportPackageCatalog](src/qq_chat_analyzer/application/report_package_catalog.py) 从 metadata.json 建 summary，不读取聊天正文。损坏／不完整包仍可作为 issue 展示和纳入自有包清点；storage_usage 只读文件元信息，无法测量的包标为 unmeasured，不把未知字节数当零。
- 列表、统计、删除共用直属正式包候选边界。删除必须验证 direct child、ownership naming、canonical root、目录身份及整树 symlink / junction / reparse，不能跟随外部目标。既有正式包只由用户显式删除，不按数量／空间自动淘汰。
- 默认分析 scratch 在 transient 下，Facade 持有最近一次成功结果，替换／shutdown 清理，分析失败也清理；首次使用前仅恢复严格命名、无 reparse 的自有旧 scratch。用户指定 output_directory 不归该自动清理 owner；QQ generation 另行管理。

旧报告是不可变分析快照：升级不自动迁移或重新分析，历史重开使用原 HTML；展示 JSON 不是可完整重分析的原始消息。metadata 允许 additive 字段，旧包缺版本字段不能补写成当前版本。

GUI 的 Local Data 经 Facade 的 list_report_packages、get_report_package_html_path 与删除接口访问 Catalog，以 package_name 定位；不拼接任意用户路径。重开由系统浏览器展示已验证的包内 HTML，失败保留记录并显示安全错误。

应用版本来自 pyproject.toml／安装元数据；report schema 来自 serializer；[analysis/revision.py](src/qq_chat_analyzer/analysis/revision.py) 标记数据解释、身份、过滤、分词、统计的语义修订，纯展示改动不递增分析修订。三者不绑定递增。

## 7. Desktop、Shutdown、Setup、Update、Uninstall

### Bootstrap 与普通退出

Desktop 先执行固定 Velopack SDK Hook 分派，再导入 GUI；安装／更新／卸载 Hook 不创建窗口，禁用 auto_apply_on_startup。Setup 与 Portable 共享分析能力，安装布局与用户数据目录分离；构建流程归 DEVELOPMENT。

发行资产由 [Windows runtime manifest](scripts/windows_runtime_manifest.json) 与 [QQ runtime pins](scripts/qq_napcat_runtime_pins.json) 限定，构建复制前后校验关键产物 hash。正式包不得重新携带 QCE runtime／兼容模块或本机私有数据；旧配置迁移不能恢复退休 endpoint。

MainWindow.closeEvent 只触发同一个幂等 [ShutdownProtocol](src/qq_chat_analyzer/gui/shutdown.py)，不在 GUI 线程等待。app.exec 返回后，入口有界等待该 protocol，优先自然退出，异常／超时进入 fallback。

Facade 封闭来源构造和分析执行入口，依次尝试来源生命周期关闭、Direct DB 禁止新获取并 bounded drain / recover、retained output 清理、自有 runtime 终止与凭据退休。步骤独立计时，失败仍尝试后续步骤；recover 需要旧凭据，不能先退休凭据或重新绑定 client。

Windows [windows_job.py](src/qq_chat_analyzer/runtime/windows_job.py) 以 PROC_THREAD_ATTRIBUTE_JOB_LIST 将正式 QQ launcher 和微信 helper 原子创建到不可继承、未命名、kill-on-close Job；纳管失败不回退无托管启动。QQProcessRegistry 持有 Job，日志线程／launcher 结束不释放所有权。兼容 PID 清理不用于 Job 对应 PID，不按进程名、路径或端口接管用户 QQ/微信或旧孤儿进程。

协议 finished / wait 仅表示 owner 调用结束。普通退出允许失败后的有限 fallback，不等于安装更新获准。watchdog 在正常返回后仍保持 armed，保护解释器收尾；Windows 强退针对当前 Echo pseudo-handle，不扩大到外部进程。

### 更新安装准入

[shutdown_models.py](src/qq_chat_analyzer/application/shutdown_models.py) 要求以下五项各出现恰好一次且全部 SUCCESS：

1. direct_db_cleanup
2. retained_output_cleanup
3. qq_runtime_termination
4. source_lifecycle
5. gui_workers

缺项、重复、未知项、空证据、UNKNOWN、FAILED、TIMED_OUT 均拒绝安装，不能用空登记表、CLOSED、取消完成或 worker 回调成功补足证据。

- Direct DB 仅在 drain 成功、无活动 startup / acquisition 且 recover 成功时 SUCCESS；超时即使稍后完成仍 TIMED_OUT，recover 异常仍 FAILED。重复调用缓存首次结果，进行中为 UNKNOWN；已创建 client 不能凭 CLOSED 跳过 recover。
- QQRuntimeSession 封闭新 launch 并保留进程历史；retire 不抹除退出证据。pending launch、未知进程或缺少证明仍 UNKNOWN。
- Registry 在释放 Job 前有界确认 ActiveProcesses 为零，再释放句柄／PIPE／reader；普通 close、PID 清理、clear / discard 不能追补整树退出证据，失败保留所有权。
- 未调用 factory 且已封闭的自有 SourceBundleBuilder 可证明为空；已使用 QQ/微信、在途 factory 或未知注入对象不能自证成功。AnalysisApplicationService 要求已封闭且静止，GUI worker / pool / relay 也必须静止。

因此当前空闲、未使用来源的会话可取得完整证据；普通连接后断开不自动恢复完整安装准入。Direct DB SUCCESS 不代表 source_lifecycle 或进程树成功。

### 检查、下载与最终交接

[update_check_service.py](src/qq_chat_analyzer/application/update_check_service.py) 只查询正式 GitHub Release 并提供经校验的发布页提示；不提供安装包授权。网络失败不冒充最新版本，必须在 worker 中调用。

[installable_update_service.py](src/qq_chat_analyzer/application/installable_update_service.py) 经组合根注入 [固定更新源与 channel](src/qq_chat_analyzer/application/update_channel.py)，使用 Velopack 检查／下载。源码、Portable 或未经核验的安装布局不具备应用内安装能力；不从 GUI、环境变量或发布页推导 feed。SDK 本地 pending 的 downloaded 不证明包可信，百分比 100 或 worker 正常返回也不是安装授权。

用户确认后 prepare_update_install 刷新可信 feed，复验 pending、SHA256、大小、包内 id/version/channel，返回一次性 token；准备不启动安装器。GUI worker relay 退出后才提出正常关闭意图；最终入口只接受 Facade 实际缓存的关闭证据与完整五项 SUCCESS。handoff 再复验安装／包状态，以 Windows 只读共享句柄阻止包被写入／删除，随后调用 wait_exit_then_apply_updates，保留自然退出和有限 watchdog。失败、超时或 UNKNOWN 不调用安装交接。

能力边界：协作式复验预算、协议等待和 Python watchdog 都不能绝对中断持续持有 GIL 的原生 SDK 调用；固定 SDK 自己的等待失败／超时后继续 apply、目录式强杀和极端新进程竞争，也不能被应用描述成已解决。这些限制不放宽退出前清理与包复验要求，实际发行验证见 HARDENING。

### 卸载交接

[SetupUninstallService](src/qq_chat_analyzer/application/setup_uninstall_service.py) 独立验证当前 Setup 安装身份与卸载器；用户确认产生一次性 token，完整关闭证据后再次验证，再交给等待 Echo 退出的 broker。准备、broker started 与卸载实际完成是不同状态；失败不得声称卸载成功。普通退出不隐含卸载，卸载也不授权删除用户聊天数据。

## 8. 关键不变量、测试证据与限制

下表指向已有守护范围，不声明本次文档修订运行过这些测试，也不替代发行／真人验收。

| 合同 | 现有测试入口 |
| --- | --- |
| Rich 事实按投影实例关联，重复／缺失 ID 不串线 | [test_rich_filtering_association.py](tests/test_rich_filtering_association.py) |
| 身份、零值未知、会话边界与 authored text | [test_identity_semantics.py](tests/test_identity_semantics.py)、[test_conversation_sessions.py](tests/test_conversation_sessions.py)、[test_qq_db_adapter_self_identity.py](tests/test_qq_db_adapter_self_identity.py)、[test_expression_lexical_boundary.py](tests/test_expression_lexical_boundary.py) |
| QQ 凭据、Worker 绑定、epoch 准入、旧 cleanup 不操作新 Worker | [test_qq_bridge_credential.py](tests/test_qq_bridge_credential.py)、[test_qq_worker_generation.py](tests/test_qq_worker_generation.py)、[test_qq_connection_admission.py](tests/test_qq_connection_admission.py) |
| Snapshot 一致性、generation cleanup 与 lease／路径隔离 | [test_qq_direct_db_snapshot_runtime.py](tests/test_qq_direct_db_snapshot_runtime.py)、[test_qq_direct_snapshot_lease.py](tests/test_qq_direct_snapshot_lease.py)、[test_qq_direct_snapshot_workspace.py](tests/test_qq_direct_snapshot_workspace.py) |
| 微信 shard 全局合并、limit、self canonicalization | [test_wechat_db_source.py](tests/test_wechat_db_source.py) |
| 微信 helper 独占、取消、清理失败保留、树退出与资源证据分离 | [test_wechat_key_service.py](tests/test_wechat_key_service.py)、[test_wechat_key_helper_resources.py](tests/test_wechat_key_helper_resources.py)、[test_wechat_key_helper_tree.py](tests/test_wechat_key_helper_tree.py) |
| 报告发布／失败保留、staging 恢复与历史所有权 | [test_echo_report_export.py](tests/test_echo_report_export.py)、[test_report_staging_recovery.py](tests/test_report_staging_recovery.py)、[test_report_package_catalog.py](tests/test_report_package_catalog.py) |
| Job owner 不接管外部进程，失败保留；关闭与成功分开 | [test_qq_job_wiring.py](tests/test_qq_job_wiring.py)、[test_shutdown_ownership.py](tests/test_shutdown_ownership.py)、[test_idle_shutdown_evidence.py](tests/test_idle_shutdown_evidence.py) |
| 五项准入、超时／失败不可洗白、安装／卸载复验 | [test_shutdown_results.py](tests/test_shutdown_results.py)、[test_update_shutdown_admission.py](tests/test_update_shutdown_admission.py)、[test_update_install_handoff.py](tests/test_update_install_handoff.py)、[test_setup_uninstall.py](tests/test_setup_uninstall.py) |

隐私是必须维持的约束：真实聊天数据、账号、昵称、密钥、token 不进入日志、提交和测试；测试只用虚构样本，公开错误使用 FacadeError.public_message，不展示 traceback 或原始异常载荷。报告本身含用户分析结果，必须按本地用户资产管理，不能因字段不进 repr 就认定可公开。

现有缺口必须保留：

- WeChatDatabaseProvider._table_exists() 只将成功查询的空结果视为目标表不存在；查询失败向上传递，使消息读取与时间范围查询中止，不返回部分 shard 结果。会话计数的 unknown 合同独立保留；这不等于全部异常读取场景已真人验收。
- [UserProfile](src/qq_chat_analyzer/analysis/models.py)、同文件中的身份／词语字段及直接嵌套的会话发起者字段已使用 repr=False，字段访问和序列化保持原样。Presentation 的展示模型仍携带身份且不保证 repr 脱敏；不得记录／上传这些对象，不能声称所有报告与 DTO 均已全面防护。
- 已使用来源的完整生命周期证明、微信 Node CleanupHook 完成证据仍不足，保持 UNKNOWN；不能删掉安全要求以使更新可用。
- 旧请求隔离依赖当前协议与绑定检查，不代表已验证上游所有 Worker 重启路径、所有 QQ schema 或全部机器环境。
- QQ 断开／异常退出不等于所有明文已立即清除；合法后续 recover 和普通退出 fallback 有明确能力边界。

## 9. 文档职责与索引

| 文件 | 唯一维护的主题 |
| --- | --- |
| 本文 | 当前架构、调用链、职责、资源所有权与安全不变量；实际实现以源码为依据。 |
| [DATA_SEMANTICS.md](DATA_SEMANTICS.md) | 跨来源身份、字段、未知值和统计语义。 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | 搭建、测试、调试、构建与 Git 工作流程。 |
| [AGENTS.md](AGENTS.md) | AI 开发者必须遵守的操作规则。 |
| [docs/HARDENING.md](docs/HARDENING.md) | 当前未解决风险、发布与验证边界。 |
| [docs/BUG_JOURNAL.md](docs/BUG_JOURNAL.md) | 有验证证据的历史故障。 |
| docs/research/ | 无法由上述文件替代的专题技术证据，不作为现役架构默认事实来源。 |
| [NOTICE.md](NOTICE.md) | 第三方来源与权利声明。 |

不在多个文件重复维护阶段测试数字、历史工作树路径或同一架构说明。实现与文档冲突时先核对源码和测试，设计要求未落实则显式记录缺口，不让实现迎合旧叙述。
