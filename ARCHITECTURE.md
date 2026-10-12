# Architecture

本文档是 Local Chat Analyzer 的**唯一架构事实来源**。

描述范围：当前已实现并通过测试的结构；发布状态与版本治理见 `docs/HARDENING.md`。
不包含未来路线图、环境搭建步骤和用户使用说明，参见第 9 节的文档边界。

---

## 1. 设计动机

项目要同时满足四个约束：

1. **隐私优先** —— 真实聊天记录只在用户本机处理，不出网络，不进日志。
2. **多来源** —— GUI 现役来源为 QQ 与微信。现役 adapter / `wechat_parser` 与
   `ImportService` 提供当前支持格式的本地文件导入，`echo-chat` 仍使用该能力，但不构成 `LOCAL_FILE`
   GUI 产品入口或 Facade 分析入口。
3. **分析核心稳定** —— 新增来源不应该迫使分析逻辑改动。
4. **面向普通用户** —— 最终形态是桌面应用，而非命令行脚本。

这四条共同导出一个结论：**数据来源与分析逻辑必须彻底分离**。

分离的手段是引入统一领域模型 `ChatMessage`。所有来源先转换成它，
分析核心只消费它。于是来源的数量和格式差异被挡在核心之外，
核心不需要知道 QQ 与微信的任何区别。

GUI 带来第二个问题：界面若直接调用各个 Service，就会把来源判断、
配置组装、异常处理散落到控件代码里。为此引入 `ChatAnalyzerFacade`
作为应用层门面，GUI 只认识它一个入口。

---

## 2. 完整数据流

```mermaid
flowchart TD
    subgraph EXT["外部数据源（进程外）"]
        QQDB["QQ 本地数据库<br/>NapCat 解密快照"]
        NAPCAT["NapCat<br/>启动 / 登录 / 本地解密"]
        WXAPP["微信本地数据库"]
        FILE["已导出文件<br/>JSON / JSONL"]
    end

    subgraph ACQ["Provider 数据获取"]
        PQQDB["qq_database_provider"]
        PWXDB["wechat_database_provider"]
        PWXCLI["wechat_cli_provider"]
    end

    subgraph ADP["Adapter / Parser 格式转换"]
        AQQDB["qq_db_adapter"]
        AWXDB["wechat_db_adapter"]
        AWXCLI["wechat_cli_adapter"]
        PARSER["wechat_parser"]
    end

    MSG["统一消息模型<br/>RichMessage / ChatMessage"]

    subgraph APP["Application 应用层"]
        IMPORT["ImportService"]
        SCOPE["Analysis Scope Filter"]
        ORCH["QQDirectDatabaseImportService<br/>WeChatExportImportService"]
        SVC["AnalysisApplicationService"]
        FACADE["ChatAnalyzerFacade"]
        PACKAGER["Echo Report Packager<br/>staging → 正式 package"]
        CATALOG["ReportPackageCatalog<br/>metadata / ownership / usage"]
    end

    subgraph CORE["Analysis Core 分析核心"]
        CLEAN["cleaner / tokenizer"]
        LEGACY["analyzer<br/>词频 · 说话者统计"]
        V2["analysis/analyzers<br/>activity · length · profile · conversation"]
        REPORTS["AnalysisReports"]
    end

    subgraph PRES["Presentation 展示层"]
        BUILD["DashboardBuilder"]
        VIEW["DashboardView"]
    end

    subgraph UI["交互与输出"]
        GUI["PySide6 GUI"]
        CLI["CLI"]
        EXP["exporters<br/>CSV · 词云"]
    end

    NAPCAT --> QQDB --> PQQDB --> AQQDB --> MSG
    WXAPP --> PWXDB --> AWXDB --> MSG
    WXAPP --> PWXCLI --> AWXCLI --> MSG
    FILE --> PARSER --> MSG
    FILE --> AQQDB
    FILE --> AWXDB
    FILE --> AWXCLI

    ORCH --> PQQDB
    ORCH --> PWXDB
    IMPORT --> PARSER
    IMPORT --> AQQDB
    IMPORT --> AWXDB
    IMPORT --> AWXCLI
    MSG --> IMPORT --> SCOPE --> SVC
    ORCH --> IMPORT

    SVC --> CLEAN --> LEGACY
    CLEAN --> V2 --> REPORTS
    LEGACY --> EXP
    REPORTS --> BUILD --> VIEW

    FACADE --> ORCH
    FACADE --> SVC
    FACADE --> BUILD
    FACADE --> PACKAGER
    FACADE --> CATALOG
    GUI --> FACADE
    CLI --> SVC
    VIEW --> GUI
```

---

## 3. 依赖方向

箭头表示"允许依赖"，且**永不反向**。

```text
gui  ──▶  application/facade  ──▶  application/services  ──▶  analysis
                  │                        │                     │
                  │                        ├──▶ providers        ▼
                  │                        ├──▶ adapters    presentation
                  │                        └──▶ parsers          │
                  └──────────────────────────────────────────────┘
                          （facade 读取 presentation 产出）
```

两个容易被误读的事实：

- `presentation` 只依赖 `analysis` 的报告模型，不依赖任何其他层。
- `facade` 同时依赖 application 服务与 presentation，是唯一的汇聚点。
  这是刻意为之：把"调度 + 转换"的复杂度集中在一处，GUI 才能保持轻薄。

---

## 4. 各层职责

### 4.1 Provider

| | 内容 |
| --- | --- |
| 负责 | 与进程外数据源通信：HTTP 调用、token 读取、数据库定位与读取、导出任务创建与轮询；产出本地文件路径或原始记录 |
| 不负责 | 格式转换、分析、过滤、业务编排、面向用户的错误措辞 |
| 可依赖 | 标准库、HTTP 客户端、自身模块 |
| 禁止依赖 | `analysis/`、`presentation/`、`gui/`、`application/`、`ChatMessage` |

Provider 是唯一允许触碰外部世界的层。它不理解聊天语义，
只负责"把数据拿到本机"。

### 4.2 Adapter / Parser

| | 内容 |
| --- | --- |
| 负责 | 把某一种具体格式转换为 `ChatMessage` |
| 不负责 | 数据获取、分析、过滤策略、文件发现 |
| 可依赖 | `message.py`、标准库 |
| 禁止依赖 | `analysis/`、`presentation/`、`gui/`、`providers/` |

Adapter 与 Parser 属于**同一层的两种形态**：

- **Adapter** 处理 Provider 产出的外部数据格式。
- **Parser** 处理用户手上已有的导出文件。

两者输出都是 `ChatMessage`，都不得依赖分析核心。
新增来源时不要复制现有 parser，各来源使用独立模块。

### 4.3 ChatMessage

| | 内容 |
| --- | --- |
| 负责 | 作为跨层唯一领域模型，表达一条与来源无关的聊天消息 |
| 不负责 | 展示名称解析、统计、格式化、平台特有字段 |
| 可依赖 | 标准库 |
| 禁止依赖 | 其他任何业务层 |

`ChatMessage` 是 `frozen=True, slots=True`，**视为冻结契约**。
新增展示需求不通过扩展它来满足（见 5.4 名称注入）。

2026-08 人工批准一次向后兼容的最小扩展：`conversation_type`
（`private` / `group` / `unknown`）与 `is_self`（`True` / `False` / `None`）
作为跨平台分析所需的最小 identity semantics 进入 `ChatMessage`；
`None` 表示数据源无法可靠判断本人，展示层仍通过名称注入与
`resolved_display_name` 解析，不复制平台身份规则。
关于 `sender_id`、`conversation_type`、`is_self` 的平台映射、canonical identity
与 Unknown 语义，以根目录 `DATA_SEMANTICS.md` 为唯一事实来源；本文只定义其架构职责。

### 4.4 Application

应用层含四类组件，职责各不相同。

**ImportService** —— 路径校验、文件发现、来源识别、parser/adapter 路由。
它直接引用全部 parser 与 adapter，是格式识别的集中点。
不做分析，不做导出。

当前支持格式只有 `qq-db-json`、`wechat-db-json`、`detailed-json`、`chatlab-jsonl`
和 `cli-json`（符合微信 CLI schema 的 bare array）。`echo-chat` 是这些格式的本地文件
分析入口；已退休的 QCE JSON 与旧 QQ JSON/JSONL 不会通过显式 platform hint 恢复支持。

**来源编排服务** —— 桌面 QQ 使用 `QQDirectDatabaseImportService`，微信使用
`WeChatExportImportService`。
它们把“先获取、再导入”串起来，并提供会话列表查询。Provider 负责来源数据获取，
Adapter 负责格式转换，分析核心不读取 QQ 原生字段。

#### QQ Direct DB 当前主链

正式 QQ 产品链只有：NapCat → Direct DB → `qq_db_adapter` → 统一消息模型 → Analysis。
桌面 QQ 先通过 NapCat 启动 / 登录；会话列表和分析的正式获取路径为：

```text
QQ 本地 main+WAL+SHM → hardened committed boundary B capture
→ staging 加密合并 DB → NapCat in-process decryptDatabase → Echo snapshot generation
→ QQDatabaseProvider（只读）→ qq-db-json 临时 payload
→ qq_db_adapter → ChatMessage → ImportService / AnalysisApplicationService
→ Analysis Core → Presentation → Echo JSON / HTML Report
```

`gui/app.py` 为 QQ 构造 `QQDirectDatabaseImportService`；Facade 通过该服务获取
会话和单次分析数据。服务首次启动时先 `recover` 上次遗留 plaintext；每次获取
都使用新的 generation，执行 `acquire`、校验 manifest、只读查询并物化 payload，
随后在 `finally` 清理 generation；分析和报告不持有 plaintext DB。正常关闭时先停止新的获取，
有限等待进行中的获取并 `recover`，再终止 Echo 自有的 QQ runtime 进程树（见第 11 节）。

首次会话查询或分析触发服务启动：在有限的 readiness 窗口内等待本地 RPC bridge
与 `EchoSnapshotApi.recover` 可用，完成遗留 plaintext 清理后才进入 `ACTIVE`。
bridge/API 暂未就绪或暂时不可达时返回可重试的 `not_ready`，后续请求可重新启动；
真正的 recover 清理失败则保持关闭，不允许读取旧 generation。QQ 连接状态可先显示
已连接，不代表 Direct DB snapshot API 已完成 readiness。

每次 `acquire` 由 snapshot helper 串行执行：先清除旧 generation、staging 与历史
plaintext，清理失败则拒绝解密；再分别有限等待 DatabaseApi/passphrase 和本人身份，
获取先固定 SHM 见证的 committed boundary B，校验 WAL header/salt/checksum 和完整前缀、
main identity/stat/content 稳定性及 checkpoint witness；B 后 append 可以继续，checkpoint、
main 改变、WAL reset/truncate 或无法证明一致性均 fail closed，不回退 main-only。
复用同一个 hardened capture 模块生成 staging 加密合并文件，交给现有 NapCat 解密；
Echo 在解密前后对 staging 输入校验 `dev` / `ino`、大小与纳秒级 `mtime` / `ctime`
强见证，无效或变化的见证均 fail closed；不再依赖上游 native-read telemetry 或 G2 patch。
发布 generation 前删除加密合并文件，复核身份未改变后
写入原 schema manifest 并原子发布 generation。RPC 客户端的
acquire 超时覆盖两个顺序等待窗口。DatabaseApi namespace Proxy 的可调用 `then` 不能作为 async
函数返回值直接返回，否则 Promise 会把它当作 thenable 而永久 pending；helper
通过普通对象承载该 Proxy。应用服务校验 generation 后只读查询，清理 generation
后才让下游消费临时 payload；失败时不使用旧 generation。

RPC 客户端仅对 `snapshot_unstable` 执行 bounded retry；每次重试仍获取新的
generation，耗尽后明确失败，不绕过任何 guard。Windows/libuv 文件 identity
比较已统一使用 descriptor `fstat`，路径探测先 open 再 fstat，保留 `dev` 与 `ino`
双重保护，避免同一文件的 path stat / descriptor stat 来源差异造成误拒绝。

同一 snapshot root 的 Windows OS 独占 lease 从获取前 recover 持有到 generation 消费后
cleanup，进程内 mutating 操作仍串行。root/staging ownership marker、generation manifest 和
固定文件 allowlist 约束删除范围；未知文件、目录或 junction 拒绝清理。全部成员验证后才删除，
ownership proof 最后删除；清理失败明确返回失败并保留可恢复残留。runtime 强杀后 OS handle
释放，下一次 startup/acquire 在 lease 内恢复，不通过 PID 存活猜测接管。lease 由隐藏的
PowerShell 子进程持有，stdin EOF 释放，不需要另一套 Python 环境。

这里有两个不同的 transient 资源：`snapshot.db` 属于 runtime generation，会话列表查询
结束或所选会话的 `qq-db-json` payload 物化完成后立即调用 `cleanup(generation_id)`；
payload 属于本次分析的临时目录，在导入、分析消费结束或抛异常后清理。两者都不作为
长期 cache。启动 `recover` 和关闭时的 `recover` 处理遗留的 runtime plaintext；
cleanup 失败会作为错误上报，不能假装分析已安全完成。

QQChatExporter / QCE 的 runtime、provider/service、CLI 命令、QCE JSON 和旧 QQ JSON/JSONL
兼容均已退休，`parser.py` 与 `qq_chat_exporter_adapter.py` 已删除；不存在 QCE fallback。
DB 原生字段与 protobuf 解释留在 Provider / Adapter 边界内，不能进入分析核心。已有真人验收确认
正式 hardened main+WAL acquisition、解密、会话列表、分析、JSON / HTML 报告
和正常 shutdown 清理可用。2026-10-02 最终验收已关闭 Stage 3.5、A4、A5、A6，
Final Cleanup / Final Smoke 均 PASS；此前 main-only 损坏快照问题已关闭。
验收范围与跨机器 RC 等开放事项见 `docs/HARDENING.md`，不将本机验收扩大为
跨机器或跨 QQ 版本 schema 保证。上述 2026-10-02 验收属于历史版本，
不覆盖当前 4.18.34、RPC 认证、Worker 代际隔离与显式重连变更；最新验收状态见该工作地图。

群成员元数据使用已验证的 `result.infos`：优先 `cardName`，缺失时回退 `nick`；
不通过好友列表假定群成员关系，也不为缺失元数据猜名称。Provider 按
`40050 ASC, 40001 ASC` 查询消息，Adapter / Import 保留该顺序。
Adapter 按段序保留多段文本与 QQ face，Unicode emoji 继续由来源中立的表达分析处理；
group reply 按可唯一匹配的序列建立 ReplyRelation，mention 保留结构化关系，
引用及 mention 元数据不混入 authored text。图片段映射为 `NonTextContent("image")`，
其他未识别段只保留 `NonTextContent("unknown")`，不猜具体媒体类型；重复段不去重。
legacy 正文只投影 TextContent，纯图片也可完成分析并生成消息统计与空词频报告。

Direct DB MarketFace（`45002=11`）以 `45600` bytes 的 SHA-256 建立独立命名空间中的
不透明 sticker 身份，不声称已解码 QQ emoji ID，也不等同于旧 QCE `type_17`。
已有表达映射与 ReplyRelation 保留是当前结构能力；完整 Sticker / 表情包语义与
Reply / 引用回复分析属于 0.2，不是 0.1 发布前置。产品状态见 `docs/HARDENING.md`。

Final Cleanup 已移除 `analysis-ordering` 专用计数/日志与闲置 `pollCount`；
保留 `analysis-timing`、DEBUG member-shape、identity coverage，以及
failure_stage / guard_code、WAL/SHM/identity/checkpoint witness、staging 输入强见证、
generation/source/snapshot/`quick_check`、cleanup/recover/shutdown 等长期诊断。
Direct DB helper 的 `QCE_LOG_FILE` 仅是保留的历史诊断变量名，不代表 QCE 能力；
保留该诊断接口，不为字符串清零强改运行逻辑。来源注释修正同步模板、pin 与部署副本。

获取范围是减少无关数据的优化边界；`Analysis Scope Filter` 才是最终 correctness
guarantee。两者必须同时保留，且时间单位按来源区分：QQ Direct DB 获取使用
epoch seconds 查询；WeChat 转换为 epoch seconds 用于 `m.create_time` SQL 条件。
QCE 的毫秒获取分支已退休，不再构成时间单位协议。

WeChat 的一个 session 的 `Msg_*` table 可分布在 0..N 个 `message_N.db` shard。
Provider 发现全部匹配 shard，对每个 shard 使用同一时间范围查询，再做全局
`create_time` 排序；显式正数 limit 在全局 merge 后应用。正常消息获取默认不限量，
`wcdb_cli` 的 no-limit/`limit=0` 表示持续 step 至 statement done，而不是默认
100000 条上限。

**来源连接服务** —— `QQConnectionService`。把 Echo bridge 的 Core.status
翻译成 `QQConnectionStatus`（runtime ready、有效 QQ 登录、独立的 Direct DB ready、
下一步操作提示）。它是应用层内 Provider 的合法调用者之一；GUI 通过 Facade
获取状态，不直接接触 Provider。

**运行时管理** —— `QQRuntimeManager`。负责检测、启动、停止外部 QQ 采集
运行环境，并把底层异常转换成用户层 `QQRuntimeStatus`。它只依赖
`runtime/` 的 `ChatRuntime` 协议，不解析外部工具输出，也不接触 Provider
的 HTTP 通信。启动立即返回进程状态；QQ 登录由连接服务后续探测，
`wait_ready()` 通过注入的 NapCat bridge readiness 探测等待就绪。

**运行时实现** —— `BundledQQRuntime` 与 `QQRuntimeConfig`。配置承载
`executable_path`、`working_directory`、bridge `base_url` 与版本；
实现负责进程启动、停止、状态与 `wait_ready()` 探测，
不复制 Provider 的业务解析。

**Windows 发布合同（De-QCE）** —— Desktop 默认 QQ runtime 位于
`runtime/qq-napcat-candidate`：官方 NapCat v4.18.34、late-passphrase
补丁、Echo plugin 白名单与 `napcat-plugin-echo`。连接和 metadata 使用
`NapCatQQProvider`；snapshot correctness 使用 Echo staging 输入强见证。Provider 与
snapshot client 绑定同一个已认证的 Worker `boot_id`，代际失效后仅显式重连可重新绑定，
新连接 recover 成功后才允许 acquire。
本机 bridge RPC 使用每次启动独立的凭据；凭据校验与 Worker 代际校验共同约束请求，
不能仅凭端口健康认领其他 runtime。此处描述当前分支 / 工作树实现，合入与发行状态见
`docs/HARDENING.md`。
`windows_runtime_manifest.json` 限定发布程序资产，build 在复制前后校验
`qq_napcat_runtime_pins.json` 的关键产物 hash。正式 portable 不携带旧 `runtime/qq`、
qce-server、QCE plugin 或 static/qce；不自动回退 QCE。
QCE Python provider/service、`qce_compat`、文件 adapter 与旧 `parser` 均不得进入 fresh
发行包或 frozen PYZ；现有 runtime forbidden checks 和 frozen package 合同共同守护。
旧 Desktop 配置只迁移 QQ 安装路径，不能恢复旧 runtime 或 API endpoint。

**AnalysisApplicationService** —— 业务流程编排：
调用 ImportService 取得消息，按本次请求应用 Analysis Scope Filter，
再 driving 清洗、分词、分析，
组装 `AnalysisResultDTO` 与 `AnalysisReports`，触发导出。

**Analysis Scope Filter** —— 应用层的单次分析时间范围过滤：
只读取 `ChatMessage.timestamp`，支持全部、最近一年、最近半年和自定义日期范围。
过滤发生在 ImportService 之后、现有智能过滤和 Analyzer 之前；Analyzer 不感知范围配置。
“全部”模式直接保留原消息，指定范围过滤为空时在进入 Analyzer 前返回应用错误。

**Desktop Bootstrap（A1 工作树实现）** —— `desktop.py:main` 是源码
`echo-gui`、`python -m qq_chat_analyzer.gui` 与 Frozen `desktop_entry.py` 的
共同入口。它先运行固定版本 Velopack 1.2.161 的 Hook 分派，显式禁用
`auto_apply_on_startup`，再导入 `gui.app._run_gui`。安装、更新与卸载 Hook
由 SDK 结束进程，不创建 GUI。`gui.app.main` 保留为兼容入口别名。
`scripts/package_windows_setup.py` 将现有 onedir 的已校验副本交给固定版本 vpk；
版本来自 `pyproject.toml`，安装目录与现有用户数据目录分离。
这里不包含软件内下载、应用更新或更新后重启编排；发行状态与实际验收见
[A1 审计](docs/research/2026-10-12-windows-setup-a1.md)。

**Update Check Core（QA-04）** —— `application/update_check_service.py` 提供
Qt 无关、聊天来源无关的 `UpdateCheckResult`、`UpdateChecker.check(manual=False)`
与默认 `UpdateCheckService`。当前版本只读取 `version.APP_VERSION`，标准库 HTTP
查询 GitHub `/repos/lingmeng-658/echo-chat-analyzer/releases/latest`，仅接受正式 Release。
严格校验 SemVer；可去掉 tag 的 `v` 前缀，build metadata 不影响优先级，远端
prerelease tag 也不接受。正式版本按 major/minor/patch 比较，同号正式版高于本地 prerelease。

GUI 的唯一入口为 `ChatAnalyzerFacade.check_for_updates(manual=False)`，由 GUI 在
worker 中异步调用并在 GUI 线程展示结果；「关于余音」对话框提供手动检查更新入口，
仅提示并打开校验后的官方 GitHub Release 页面，不自动下载、替换或静默更新。
构造时无网络/磁盘 I/O。返回状态为 `update_available`、`up_to_date`、`no_release`、
`skipped`、`unavailable`，另带当前/最新版本、校验后的 Release 页面 URL、检查时间、
安全错误代码与 `public_message`。网络或响应失败不冒充“已是最新”；异常响应正文不外泄。
请求无重试，socket timeout 为 5 秒，响应最多 256 KiB；该 timeout 不是总时限，
不得在 GUI 主线程或同步启动流程中调用。不会下载或替换程序。

自动检查使用 `<user_data_dir>/update-check.json`，只保存 Unix 时间字段
`last_check_time`，按所有检查尝试（含失败和手动检查）去重 24h；恰好 24h 可再检查。
手动检查绕过去重，但同一 service 实例的并发调用立即返回 `skipped/in_progress`。
状态缺失、损坏或时钟回拨产生的未来时间不抑制检查；原子写入失败不影响结果，
同一实例仍保留内存去重。该最小策略不承诺跨进程互斥或状态不可写时的跨重启去重。

**Report Package 生命周期（BUG-03）** —— Report Package 是 Echo 唯一持久分析对象，
也是 Local Data 历史列表的事实来源。`ReportHistoryManager`、`analysis_history.jsonl`
及其读写 API 已退休，不再维护与报告目录分离的元数据历史。

Windows 默认根目录为 `%LOCALAPPDATA%\LocalChatAnalyzer`（由 `user_data_dir()` 提供）：

```text
LocalChatAnalyzer/
├─ reports/
│  └─ Echo_Report_YYYYMMDD_HHMMSS[_N]/
│     ├─ echo-report.html
│     ├─ echo-report.json
│     ├─ metadata.json
│     └─ README.txt
└─ transient/
   └─ chat-analyzer-output-<8位十六进制>/
```

- `reports/` 的持久资产只包括正式 Report Package，不放默认分析 scratch 或 raw export。
  发布期间在同一 root 创建 `.echo-report-<uuid>` staging，四文件完整写入后 rename
  为正式 package；staging 不进入 catalog，也不计入报告存储统计。发布时创建同 root ownership
  sidecar，绑定 root、staging 和 sidecar 的文件系统身份，并持有 OS 文件锁。
  普通发布异常会尝试清理 staging；catalog list / clear_all 会恢复清理具有有效 ownership
  且未被活跃发布锁定的 staging。清理前拒绝 reparse point、身份变化和未知成员；仅有前缀
  或缺少有效 sidecar 的旧 staging 不会被删除。恢复失败只记录安全诊断，clear_all 沿用
  既有失败错误；staging 不作为正式报告或不可读报告 issue 展示。
- `package_echo_report()` 只负责发布；Facade 显式使用 Catalog 的 canonical
  `reports_root`，成功返回正式目录即作为本次结果。发布成功后不自动删除任何既有报告；
  发布失败不删除旧报告，生成的报告仍留在本次 output。
- `ReportPackageCatalog` 只读 `metadata.json` 构建 summary（包括 `conversation_kind`）；
  检查 package 完整性时不读取 report JSON 或聊天正文。损坏或不完整 package
  作为 issue 对用户可见，不因 metadata 不可读而脱离 package ownership 枚举。
- 正式报告的分析结果是 immutable historical snapshot。app upgrade 不自动 migration 或
  re-analysis；Local Data 重开使用包内原 HTML。新算法或新数据库字段需要新版重新
  acquisition / analysis，生成新包；旧报告不伪造缺失数据。既有删除与
  可选分享产物的生命周期不改变这一分析快照约束。
- `echo-report-meta.v1` 是包摘要契约，允许 additive 可选字段；reader 忽略未知字段，
  新 reader 必须继续读取旧包。新包追加 `app_version`、`report_schema_version` 和
  `analysis_revision`；旧包缺这些字段仍正常 list / reopen / 统计，不补写当前版本。
  `echo-report.v0.7` 是展示 JSON 契约，不是原始消息或可重新分析的完整中间结果；
  当前不承诺用新版 presentation 重新渲染旧 JSON。
- app release version 唯一事实源为 `pyproject.toml`；`version.py` 从安装元数据读取，
  GUI 与 metadata writer 共用。frozen build 核对安装版本与发布版本一致并携带元数据。
  `analysis/revision.py` 单独记录分析语义修订；影响结果的数据解释、identity、过滤、
  分词或统计规则变化时递增，纯 presentation 改动不递增。report schema 使用 serializer
  的既有常量，三个版本不绑定递增。
- listing、统计与 delete 共用正式 package 候选边界：reports root 的直属真实目录，
  且名称严格符合 ownership naming。合法名称的普通文件不是 Report Package，忽略并保留；
  reparse / symlink / junction 仍进入安全拒绝流程，不跟随外部目标。
- 报告发布后不按数量或空间阈值自动淘汰：既有正式报告只由用户在 Local Data 显式删除。
  删除前验证 direct child、ownership naming、canonical root、目录身份与
  整棵树的 symlink / junction / reparse 边界，不跟随外部路径。
- `ReportPackageCatalog.storage_usage()` 只使用文件元信息统计 owned package 数量与字节占用，
  包含损坏或不完整但仍属 Echo 管理范围的 package；不读取报告正文或 metadata，也不使用
  mtime / ctime 作为报告时间。无法安全统计（reparse、身份变化、文件系统错误）的 package
  仍计入数量并单独标记为 unmeasured，未知占用不得记为零。Facade 通过
  `get_report_storage_usage()` 暴露该统计，供后续 GUI 显示报告数量与总占用空间。
- 默认 scratch 位于 `transient/`，Facade 持有最近一次成功分析的 scratch，替换或 shutdown
  时清理；分析失败也清理。每个 Facade 首次创建默认 scratch 前执行一次 stale scratch
  recovery，只处理严格命名的直属自有目录，拒绝 reparse，失败记日志并继续。
  用户指定的 `output_directory` 不归该 scratch 清理流程所有；该 recovery 不处理
  Direct DB generation，后者有独立的生命周期边界。

| | 内容 |
| --- | --- |
| 负责 | 流程编排、DTO 转换、应用级错误 |
| 不负责 | 具体统计算法、文件格式解析、界面措辞 |
| 可依赖 | `providers/`、adapters、parsers、`analysis/`、`message.py` |
| 禁止依赖 | `gui/` |

### 4.5 Analysis Core

| | 内容 |
| --- | --- |
| 负责 | 全部统计与分析算法，输入 `ChatMessage`，输出报告模型 |
| 不负责 | 文件读写、数据获取、格式化展示、平台判断 |
| 可依赖 | `message.py`、`rich_message.py`（P0 source-neutral 旁路输入）、标准库、算法类第三方库 |
| 禁止依赖 | `application/`、`presentation/`、`gui/`、`providers/`、adapters、parsers |

核心分两代，并存且互不干扰：

- **v1**：`cleaner.py`、`tokenizer.py`、`analyzer.py` —— 词频、说话者统计。
- **v2/v3**：`analysis/` 包 —— 活跃度、消息长度、用户画像、会话概览、
  Conversation Sessions 等结构化分析能力。

**Conversation Sessions** 位于 Analysis Core 内部，只消费统一后的
`ChatMessage.timestamp`、`conversation_type`、`is_self` 与稳定发送者身份。
Session 切分、initiator 判定和汇总统计必须在核心完成；
Presentation 与 Echo 只消费结果，不得重新计算。

**Rich 能力（Expression v1.1）** 可选消费 `rich_message.py` 中的 source-neutral
content part（如 `ExpressionContent`），作为 `ChatMessage` legacy 文本投影之外
的旁路输入。QQ face、QQ market_face、微信 type47 sticker 与微信
`local_type=1` 官方文本表情 `[名称]` 统一进入 `ExpressionContent`；
`ImportOutcome.rich_messages` 只在来源 adapter 已支持 Rich 语义时填充；
Analysis 仍不得出现平台分支。

**禁止在核心中出现平台分支。** 不得出现 QQ、微信、`wxid`、`chatroom` 之类判断。
唯一例外是 `analysis/models.py` 中对内部标识可展示性的判定，
那是展示语义规则而非来源分支（见 5.4）。

### 4.6 Presentation

| | 内容 |
| --- | --- |
| 负责 | 格式转换、标题与描述生成、排序截断、图表数据组装 |
| 不负责 | **任何统计计算**、数据获取、控件创建 |
| 可依赖 | `analysis/` 的报告模型、标准库 |
| 禁止依赖 | `gui/`、Qt、任何 GUI 框架、`providers/`、adapters |

展示层是纯函数式的转换层。它拿到的数字必须已由 analyzer 算好，
自己只做"怎么说给人听"。产出 `DashboardView`，其中包含
`MetricCard`、`UserCard`、`ConversationCard`、`ChartData`。

`DashboardView` 不暴露 `AnalysisReports` 内部结构，GUI 只面对视图模型。

### 4.7 Facade

| | 内容 |
| --- | --- |
| 负责 | 来源选择与分派、配置整理、Service 调度、异常统一、返回展示模型 |
| 不负责 | 统计、解析、控件创建、数据获取细节 |
| 可依赖 | application 各服务、`presentation/` |
| 禁止依赖 | `gui/` |

`ChatAnalyzerFacade` 是 **GUI 的唯一入口**。对外 API：

- `list_sources()` → `tuple[SourceInfo, ...]`，含可用性标记
- `list_sessions(source)` → `list[SessionInfo]`，统一 QQ 与微信差异
- `get_connection_status(source)` → `QQConnectionStatus`，返回来源连接状态
- `list_report_packages()` → `ReportPackageListing`，返回 metadata summaries 与 issues
- `get_report_package_html_path(package_name)` → `Path`，安全定位 package 内的普通 HTML 文件
- `clear_report_packages()`，删除完整自有 package，部分失败转换为公开错误
- `analyze_session(source, session_id, config)` → `AnalysisOutcome`

`ChatSource` 只有 `QQ` 与 `WECHAT` 两个现役来源；已无 `LOCAL_FILE`、
`AnalysisPage`、`Facade.analyze_file` 或 `--headless-analyze` 产品入口。
`analyze_session` 内部通过来源获取的中间 payload 把会话送入通用分析核心；QQ payload
位于本次 Echo-owned transient lease 中，消费者完成后清理。底层 parser、
`ImportService`、JSON / JSONL 与 `AnalysisApplicationService` 能力仍保留，供来源
中间文件进入统一核心使用。

两条重要约定：

1. **异常在此归一。** 底层异常统一转换为 `FacadeError`，
   携带 `code` 与 `public_message`。GUI 只展示 `public_message`，永不展示 traceback。
2. **中间文件对 GUI 不可见。** `analyze_session` 内部会产生导出文件（`payload_path`），
   但这属于实现细节，不出现在返回值与 API 语义里。

依赖注入构造（`qq_service`、`wechat_service`、`analysis_service`、
`presentation_builder`、`report_package_catalog`），测试可传入 stub 或临时 reports root。

### 4.8 GUI

| | 内容 |
| --- | --- |
| 负责 | 控件装配、事件转发、状态展示（空 / 进行中 / 成功 / 错误） |
| 不负责 | 读数据库、解析文件、调用 Provider、任何统计计算 |
| 可依赖 | `application/facade.py`、`presentation/` 的视图模型、PySide6 |
| 禁止依赖 | `providers/`、parsers、adapters、`analyzer.py`、`tokenizer.py`、`cleaner.py`、`sqlite3` |

GUI 层零业务逻辑。所有报告展示控件为只读
（`setEditTriggers(NoEditTriggers)`），但保留选中与复制能力。
分析成功后在现有状态栏展示报告保存状态。
Local Data 通过 Facade 读取真实 package catalog，支持刷新、删除选中报告、删除全部报告、轻量搜索与 reopen。
搜索仅对已加载的 summaries 做 `query.strip().casefold()` substring 匹配：会话名、来源、
会话类型、生成日期、分析范围的显示文本；空查询显示全部，issues 始终可见。
报告不做自动淘汰，列表展示当前全部已发布正式报告；不可读报告不靠搜索静默隐藏。
搜索不发起新的 Facade / Catalog 磁盘调用，refresh 后保留 query 并重新过滤。
选中行的 `Qt.UserRole` 保存 `package_name`，打开按钮和双击共用 reopen 流程：
Facade → Catalog 安全定位 `echo-report.html` → 注入的系统 opener。
GUI 不拼接任意用户路径，metadata 不存绝对路径；定位或打开失败显示安全错误并保留记录。
Reopen 使用系统默认浏览器查看已有 HTML，不重建 Dashboard 或重新分析。

当前 GUI 结构由 `MainWindow` 承载 `HomePage`、`QQWorkspace`、
`WeChatWorkspace`、处理页、`DashboardPage`、`LocalDataPage`。
QQ 与微信来源分别由 `QQWorkspace` / `WeChatWorkspace` 负责连接与生命周期，
会话列表、搜索、排序、时间范围与分析按钮由两者共享的
`SessionAnalysisPanel` 承担。

分析中的共享页面由 `ProcessingPage` 承载 `ProcessingAnimationWidget`；其确定性
`processing_animation_model.py`、`processing_geometry.py` 和
`processing_animation.py` 只负责原生 Qt 动画状态、几何和绘制，不读取聊天数据，
也不推断分析进度。独立预览入口 `processing_animation_preview.py` 供无真实聊天记录的视觉验收使用。

Facade 通过 `analyze_session(..., on_phase=...)` 在真实业务边界发布
`application/analysis_phase.py` 定义的 `READING` 与
`ANALYZING_REPORT` 结构化阶段（按顺序、同一阶段每次任务最多一次）。
QQ / 微信 Workspace 将事件转发给 `MainWindow` 与同一 `ProcessingPage`；
不根据中文进度文本、预估耗时或动画循环推测实际处理进度。
任务取消、成功、失败和页面离开时停止动画；旧任务的迟到阶段事件
不得改变新任务的页面。后台取消仍采用协作式机制，不保证立即终止阻塞中的数据获取。

### 4.9 CLI

| | 内容 |
| --- | --- |
| 负责 | 命令参数解析、用户交互、结果显示、退出码 |
| 不负责 | 分析流程、Provider 构造、格式解析 |
| 可依赖 | `application/` |
| 禁止依赖 | `providers/`、核心分析模块 |

CLI 与 GUI 是同层的两个交互适配器，共享同一套应用服务，
**不允许存在两套业务逻辑**。

### 4.10 Exporter

| | 内容 |
| --- | --- |
| 负责 | 生成本地产物：词频 CSV、词-说话者 CSV、词云图、Top 说话者图 |
| 不负责 | 统计计算、数据获取 |
| 可依赖 | 分析结果、绘图与字体库 |
| 禁止依赖 | `gui/`、`providers/`、`application/` |

---

## 5. 核心设计原则

每条给出原则、理由与违例信号，便于在 review 中实际检查。

### 5.1 单向依赖

依赖只能由外层指向内层，核心永不感知外层。

理由：核心稳定性是多来源支持的前提。

违例信号：`analysis/` 中出现 `from ..application import ...`。

### 5.2 ChatMessage 是唯一跨层领域模型

所有来源统一转换为它，核心只消费它。

理由：把来源差异挡在核心之外，新增来源不改核心。

违例信号：平台专用模型进入 `analysis/`；为了展示需求去改 `ChatMessage` 字段。

Rich 能力阶段允许 `ImportOutcome` 额外携带 `rich_messages` 作为旁路通道，
供 Analysis Core 可选消费；`ChatMessage` 仍是 legacy text projection 的稳定入口，
禁止用 Rich 数据反向补全 `ChatMessage`，也禁止平台字段进入 `analysis/`。

### 5.3 来源与分析隔离

分析核心不知道 QQ、微信、本地文件的存在。

理由：来源会持续增加，分析算法不应随之膨胀。

违例信号：`analyzer.py` / `tokenizer.py` / `cleaner.py` / `analysis/` 中出现平台判断。

### 5.4 展示名称由调用方注入

这是 v0.7.0 阶段的关键决策（该版本号后来已统一为 `0.1.0`），单列说明。

问题：分析结果里的 `sender` 可能是 `wxid_xxx`，`conversation_id` 可能是
`xxx@chatroom`，用户无法理解。但 `ChatMessage` 不可改，
分析核心又不允许认识微信。

解法：名称映射由**调用方经 DTO 注入**。
`AnalysisRequestDTO` 提供 `speaker_names` 与 `conversation_names`
（`Mapping[str, str]`，默认空），`AnalysisApplicationService` 透传给
`UserProfileAnalyzer` 与 `ConversationAnalyzer`。

报告模型提供 `display_name` 字段与 `resolved_display_name` 属性，
展示层只读后者。三级 fallback：

```text
display_name 非空            →  display_name
conversation_id 可展示       →  conversation_id
否则                         →  UNKNOWN_CONVERSATION_NAME（未知会话）
```

不可展示的内部标识：含 `@chatroom`，或以 `wxid_` 开头。

**未注入映射时，行为与注入机制引入前完全一致**（回退到原始 key），
因此该机制对既有调用方无侵入。

两个隐私约束：`speaker_names` / `conversation_names` 在 DTO 中标记
`repr=False`，避免真实昵称随 repr 泄露到日志。

### 5.5 GUI 无业务逻辑

GUI 只装配控件、转发事件、展示状态。

理由：业务逻辑一旦进入控件，就无法被测试，也无法被 CLI 复用。

违例信号：`gui/` 中出现 `sqlite3`、Provider 导入、循环求和统计。

### 5.6 异常在 Facade 归一

底层异常不穿透到界面，统一转为 `FacadeError`。

理由：用户看 traceback 没有意义；界面也不应该认识每种底层异常。

违例信号：GUI 中 `except` 捕获 Provider 或 Service 的具体异常类型。

### 5.7 隐私优先贯穿各层

原始聊天内容只在本机处理，不出网络。DTO 对敏感字段使用 `repr=False`，
摘要模型不保存正文与消息列表，测试只用虚构数据。

违例信号：日志或终端输出完整正文；测试引入真实导出文件。

---

## 6. 模块映射

以下为当前代码的真实结构。

| 目录 / 模块 | 架构层 |
| --- | --- |
| `providers/qq_database_provider.py` / `providers/napcat_qq_provider.py` | QQ Direct DB 获取 / NapCat readiness 与 metadata |
| `providers/wechat_database_provider.py` | Provider |
| `providers/wechat_cli_provider.py` | Provider |
| `qq_db_adapter.py` | QQ Direct DB Adapter |
| `wechat_db_adapter.py` | Adapter |
| `wechat_cli_adapter.py` | Adapter |
| `wechat_parser.py` | Parser（微信导出文件） |
| `message.py` | 领域模型 ChatMessage |
| `application/import_service.py` | 导入编排 |
| `application/import_request.py` / `import_outcome.py` / `import_result.py` | 导入契约 |
| `application/qq/qq_direct_database_import_service.py` | 桌面 QQ Direct DB 获取与生命周期编排 |
| `application/qq/qq_connection_service.py` | QQ 连接状态 |
| `application/qq/qq_connection_manager.py` / `application/qq/qq_auth_bridge.py` | QQ 连接流程与登录授权 |
| `application/qq/qq_setup_service.py` / `application/qq/qq_environment_config.py` | QQ 连接设置与配置 |
| `application/qq/qq_provider_factory.py` | QQ Provider 装配与缓存 |
| `application/qq/qq_runtime_manager.py` / `application/qq/qq_process_registry.py` | QQ runtime 管理与自有进程记录 |
| `application/connection_models.py` | 来源无关的连接状态契约 |
| `application/qq_connection_service.py` | 保留的公共旧模块路径，仅重导出连接服务实现对象 |
| `application/connection/__init__.py` / `application/runtime/__init__.py` / `application/runtime/qq_runtime_manager.py` | 保留的连接与 runtime 公共兼容出口，无业务实现 |
| `application/wechat/wechat_export_import_service.py` | 来源编排（微信） |
| `application/wechat/wechat_connection_service.py` | 微信连接状态 |
| `application/wechat/wechat_connection_progress.py` | 微信连接进度 |
| `application/wechat/wechat_setup_service.py` | 微信连接设置 |
| `application/wechat/wechat_environment_config.py` | 微信环境配置 |
| `application/wechat/wechat_provider_factory.py` | 微信 Provider 装配与缓存 |
| `application/wechat/wechat_data_detector.py` | 微信数据位置检测 |
| `application/wechat/wechat_key_service.py` | 微信读取授权 |
| `application/wechat_connection_service.py` / `application/wechat_environment_config.py` | 保留的公共旧模块路径，仅重导出微信实现对象 |
| `application/analysis_service.py` | 应用服务 |
| `application/update_check_service.py` | 正式 Release 更新检查、来源无关结果契约与最小本地去重 |
| `application/scope_filter.py` | 单次分析时间范围过滤 |
| `application/echo_report_export.py` | 四文件 Report Package staging 与正式发布 |
| `application/report_staging.py` | Report staging ownership、发布锁与安全恢复清理 |
| `application/report_package_metadata.py` | Report Package metadata 构建 |
| `application/report_package_catalog.py` | metadata catalog、安全定位、完整 package 删除与报告存储统计 |
| `application/dto.py` / `errors.py` / `task.py` / `export_config.py` | 应用契约 |
| `application/facade.py` | Facade |
| `runtime/` | 外部运行时契约（ChatRuntime）与捆绑运行时实现（BundledQQRuntime） |
| `cleaner.py` / `tokenizer.py` / `analyzer.py` | Analysis Core v1 |
| `analysis/models.py` | 报告模型（v2/v3） |
| `analysis/analyzers/*.py` | 独立分析器 |
| `analysis/conversation_sessions.py` | Conversation Sessions 切分与汇总分析 |
| `analysis/identity.py` | 稳定发送者 identity 辅助 |
| `analysis/peaks.py` / `timestamps.py` | 分析辅助 |
| `presentation/models.py` | 视图模型 |
| `presentation/builders.py` / `formatters.py` | 视图构建与格式化 |
| `gui/main_window.py` / `dashboard_page.py` | GUI 界面 |
| `gui/app.py` / `__main__.py` / `workers.py` | GUI 启动与执行 |
| `cli.py` | 交互适配（CLI） |
| `exporters.py` | 输出适配 |
| `detectors/*.py` / `smart_profile.py` / `filter_pipeline.py` / `filter_decisions.py` / `candidates.py` / `decision_engine.py` | 智能过滤子系统 |

两处需要如实说明的结构现状：

1. **三个 Adapter 位于包根目录，没有 `adapters/` 子包**，
   与 `providers/` 的组织方式不一致。属历史结构差异，不影响依赖方向。
2. **Facade 位于 `application/` 而非独立顶层包**，
   因其本质是应用层的门面，而不是新的一层业务。

---

## 7. 扩展指南

### 7.1 新增聊天来源

1. 先阅读真实导出样例，确认字段结构；只支持第一种格式，不预先支持所有变体。
2. 若需进程外获取，在 `providers/` 新增 provider 模块。
3. 新增独立 adapter 或 parser，输出 `ChatMessage`；**不要复制现有 parser**。
4. 在 `ImportService` 注册识别与路由。
5. 若需"先导出再导入"，新增 `XxxExportImportService`。
6. 在 `ChatSource` 枚举与 Facade 分派中登记。
7. 先写虚构数据测试，再实现。

**不许修改**：`analyzer.py`、`tokenizer.py`、`cleaner.py`、`analysis/`、
`presentation/`、`gui/`、`message.py`。

验收标准：分析核心的代码与测试零改动，全量测试通过。

### 7.2 新增分析能力

1. 在 `analysis/models.py` 新增 frozen dataclass 报告模型。
2. 在 `analysis/analyzers/` 新增独立 analyzer，入参为 `ChatMessage` 序列。
3. 在 `AnalysisReports` 新增字段，给默认值以保证向后兼容。
4. 在 `AnalysisApplicationService._build_reports()` 接线。
5. 若需展示，再到 `presentation/` 增加对应视图模型与构建逻辑。

需要 Rich 语义的新分析器（如 Expression v1.1）可额外接收 `ImportOutcome.rich_messages`
中的 source-neutral `RichMessage`；该通道默认空元组，旧分析器不感知。

**不许**把新统计塞进 `analyzer.py`；
**不许**在 analyzer 内读文件、分词或访问网络。

### 7.3 新增展示方式

1. 在 `presentation/models.py` 新增视图模型，在 `builders.py` 做转换。
2. **不许在展示层重新计算统计** —— 需要的数字应先在 analyzer 中产出。
3. 新界面（Web、报告导出等）作为 Facade 的新调用者接入，
   不绕过 Facade 直接调用 Service。

---

## 8. 架构不变量

以下规则可被机械检查，新增层时应同步补守护测试。

```text
1. analysis/     不 import application | presentation | gui | providers | adapters | parsers
2. presentation/ 不 import gui | PySide6 | providers | adapters
3. gui/          不 import providers | parser | wechat_parser | analyzer
                 | tokenizer | cleaner | sqlite3
4. gui/          除 facade 外不 import application 的其他模块
5. 核心分析模块  不出现 wxid / chatroom / qq / wechat 平台分支
6. 报告与 DTO    敏感字段不进入 repr
7. 测试          不读取真实聊天数据
```

其中若干条已由现有测试守护（如 GUI 不导入 provider、
展示层不依赖 Qt、DTO 敏感字段不泄露）。

---

## 9. 文档边界

本文档只讲架构。其他内容各有归属：

| 内容 | 归属文档 |
| --- | --- |
| 当前 Hardening / Active Bug 工作地图 | `docs/HARDENING.md` |
| 环境搭建、测试命令、Git 流程 | `DEVELOPMENT.md` |
| AI 协作规范 | `AGENTS.md` |
| 项目简介与快速上手 | `README.md` |
| 跨平台字段、identity 与分析语义 | `DATA_SEMANTICS.md` |
| 已解决且验证的真实工程问题 | `docs/BUG_JOURNAL.md` |
| 历史设计记录 | `docs/design/`、`docs/superpowers/specs/` |

当架构描述与其他文档冲突时，**以本文档为准**。

---

## 10. Connection Layer

记录 Phase 10 新增的连接层。它回答一个问题：
“这个来源现在能不能用”。

- **GUI 不管理 runtime 生命周期。**
  界面不再启动运行环境、不做健康检查、不检查 token，
  只负责展示状态、触发连接动作、展示错误。
- **Facade 提供连接状态。**
  GUI 仍然只认识 `ChatAnalyzerFacade` 一个入口，
  通过 `get_qq_connection_snapshot()` 和 `connect_qq()` 获取结果。
- **Connection Manager 管理连接流程。**
  位于 `application/qq/qq_connection_manager.py`，负责编排准备、启动与授权检查，
  并把底层结果解释成用户可理解的状态。
- **ConnectionSnapshot 是只读状态模型。**
  定义位于 `application/connection_models.py`。
  不可变，跨层传递，GUI 只读取不重新推导。
  状态取值：`DISCONNECTED`、`INITIALIZING`、`STARTING`、
  `WAITING_AUTH`、`CONNECTED`、`ERROR`。
- **当前仅 QQ 使用该结构。**
  未来微信可以复用同一套抽象，但**不提前实现**；
  微信仍走原有连接状态路径。
- **每个 QQ auth session 都要求 QR freshness。** 新 auth flow 在启动 runtime 前记录
  当前 QR cache 基线；只有本 session 启动后发生变化的 QR 才可展示或接受。断开或开始
  新会话会终止旧 runtime session 并 reset 对应的 auth/QR 状态，避免复用旧 runtime 的
  QR 状态。

调用链：

```text
GUI
 ↓
Facade
 ↓
Connection Manager
 ↓
QQ Connection Service / Runtime
```

### 10.1 GUI 连接体验状态

连接页只把 Facade 已有状态映射为展示状态，不新增 Provider 状态，也不在 GUI
重新判断连接是否成功：

| 展示状态 | 会话区域 | 可用操作 |
| --- | --- | --- |
| 未连接 | “暂无会话；连接数据源后，这里会显示聊天记录” | 连接当前来源、返回数据源选择 |
| 连接中 / 等待登录 | “正在连接数据源...” | 取消当前连接任务、返回数据源选择 |
| 数据读取中 | “正在读取聊天数据...” | 返回数据源选择 |
| READY | Facade 返回的真实会话列表 | 选择会话、返回数据源选择 |

QQ 与微信的页面状态互相隔离。切换来源或返回数据源选择时，GUI 清空上一来源的
状态文字、会话缓存、搜索条件和引导控件；迟到的异步回调不得更新当前来源页面。
“返回数据源选择”只放弃当前 GUI 流程，不代表登出、断开或关闭 QQ/微信客户端。
分析中的取消仍沿用原分析取消流程。

---

## 11. 退出与 shutdown ownership

关闭窗口与停止 Echo 自有的运行时进程是两件独立的事，归属明确分开。

- **GUI 只触发，不等待。** `MainWindow.closeEvent` 关闭窗口后立即返回，
  主窗口消失；用户不需要盯着一个“正在关闭”窗口。
- **shutdown protocol 只有一个。** 窗口持有 `ShutdownProtocol`
  （`gui/shutdown.py`），`begin()` 只允许启动一次，重复 close 不会产生第二个
  互相竞争的清理流程。
- **入口点拥有结束权。** `gui/app.py` 在 `app.exec()` 返回后，先调用
  `window.begin_shutdown()`（幂等），再以有限时长等待同一个 protocol。
  清理调用返回后优先自然退出；等待超时或异常才立即强制退出。
  原因：CPython 不会 join daemon 线程，解释器收尾会冻结清理线程，
  因此“只启动不等待”的清理会丢失，Echo 启动的进程树会残留。
- **清理顺序由 Facade 拥有。** `ChatAnalyzerFacade.shutdown()` 按
  “停止接受新的 Direct DB acquisition → bounded drain / recover plaintext →
  终止 Echo 自有的 QQ runtime 进程树”执行。每一步都有独立时间窗，
  某一步失败或卡死都不会跳过后续步骤，也不会让退出无限挂住。
- **Windows 托管进程在创建时获得所有权。** 两条 QQ 启动入口通过
  `runtime/windows_job.py` 的 `PROC_THREAD_ATTRIBUTE_JOB_LIST` 原子创建到
  不可继承、未命名的 kill-on-close Job 中。`QQProcessRegistry` 持有会话资源，
  launcher 或日志线程结束不释放 Job；正常 shutdown 关闭 Job，Echo 异常退出
  则由 Windows 关闭句柄并终止受管后代。纳管失败不退回无托管启动。
  旧 PID 记录仅保留兼容清理；Job 对应 PID 不再执行 taskkill。
  不按端口、进程名或路径扫描认领，不接管外部健康服务或旧版本孤儿进程，
  不触碰用户自己启动的 QQ。
- **超时有明确 fallback。** 超过 bounded 窗口后强制退出；跨步骤总预算与
  last-resort watchdog 都是有限值。watchdog 在正常返回后仍保持 armed，
  用于解释器收尾被后台线程拖住的情况；与立即强制退出共享一次性出口。
  Windows 兜底只对当前 Echo 进程的 pseudo-handle 调用 `TerminateProcess`，
  不走本机 Qt 子进程中已复现访问冲突的 `os._exit` 路径；其他平台保留 `os._exit`。
- **结束与成功分别表达。** `ShutdownProtocol.finished` / `wait()` 只表示
  owner 调用已结束；`result` 传播 Facade 的不可变 `ShutdownResult`，逐步记录
  `SUCCESS`、`FAILED`、`TIMED_OUT`、`UNKNOWN`。`status=SUCCESS` 只汇总已有证据；
  更新准入还要求 `direct_db_cleanup`、`retained_output_cleanup`、
  `qq_runtime_termination`、`source_lifecycle`、`gui_workers` 各出现恰好一次且全部成功。
  缺项、重复项、未识别项、空证据、异常、超时和未知均不允许更新，普通退出仍保持有界。
  Facade 验证临时报告实际移除，保留异常与步骤超时，缓存首次结果避免重复清理
  把失败洗成成功。协议尚未 finished 时不发布成功结果。
  已使用 QQ/微信来源、注册但未发布的 builder、注入的分析服务/runtime session
  尚无完整生命周期证明，保持 `UNKNOWN`；
  注册 PID 被移除也不代表所有后代已退出。GUI 将未静止的 worker/pool/relay
  状态作为未知证据加入结果。本阶段没有调用 Velopack 应用更新。
  无资源成功只适用于已知清点为空的关闭快照；未来更新编排还必须停止生产者，
  不得在可继续创建资源的界面缓存这个结果作为安装授权。

守护测试：`tests/test_gui_shutdown_protocol.py`、
`tests/test_desktop_exit_ownership.py`、`tests/test_shutdown_ownership.py`，
`tests/test_shutdown_results.py`、`tests/test_shutdown_worker_results.py`、
`tests/test_desktop_natural_exit.py`、`tests/test_desktop_exit_subprocess.py`，
以及 `tests/test_gui.py` 的 close 用例。
