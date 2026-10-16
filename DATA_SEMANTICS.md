# Data Semantics

本文定义现役消息身份、字段和统计语义；模块职责见 [ARCHITECTURE](ARCHITECTURE.md)。来源解析、核心统计和展示消费是不同环节，不能把展示规则写成来源事实。

## 1. 消息与身份

RichMessage 保存来源提取的结构化内容和关系；ChatMessage 是它面向现有过滤／统计的单向投影，也有仅提供 ChatMessage 的本地导入路径。投影正文只包含 TextContent，不代表完整原始消息。过滤后的 Rich 事实按原投影实例关联，不按 message_id 猜测；重复、缺失 ID 不授权消息合并。

### 稳定身份与展示名

`sender_id` 是来源命名空间内的身份，不等于 `sender` 或昵称；它不是跨平台、跨账号的全局 ID。分析的 stable_sender_key 优先使用非空 sender_id，缺失时回退 sender 展示文本。因此没有稳定 ID 的旧输入仍可能按名称归属，不能宣称所有成员合并都具有稳定身份保证。

| 来源 | 现役身份合同 |
| --- | --- |
| QQ Direct DB | 发送者来自原生字段 `40033`，不是任意 uid/uin 二选一。本人上下文为 `self.namespace="qq_uin"`、`self.value`，绑定快照账号的 NapCat selfInfo.uin；Adapter 用 canonical_qq_uin 比较。命名空间不匹配或本人值不可靠时 is_self=None。sender_id 保留来源标识字符串，不附加 namespace 前缀，也不把账号值变成显示名。 |
| 微信数据库 | 发送者来自 Name2Id.user_name；本人身份使用同一 username 命名空间，不能拿目录显示名或昵称比较。 |

QQ 显示名由 remark、群名片、nickname 和安全 fallback 按会话上下文解析；名称改变不应拆分已有稳定 ID，同名不同 ID 不应合并。展示名缺失不能成为猜测账号的理由。

QQ Direct DB 私聊的零值发送者可保留消息：sender_id=None、sender=""、is_self=None，不采用偶然附带的昵称作为参与者身份。它不进入成员画像、成员词语归属或参与者计数，仍参与全局消息量、时间、文本和表达统计；不推定为系统消息、本人或对方。群聊零值维持现有行为，不能把私聊规则无条件推广。缺失／无效到无法解析的原始记录仍可能被 Adapter 跳过，不等于所有未知输入都必定保留。

### conversation_type 与 is_self

conversation_type 为 private / group / unknown。`is_self` 是三态事实：

- True：可靠确认由本人发送。
- False：本人身份与发送者均可靠，且发送者不是本人。
- None：无法可靠判断，不能当作 False 或 peer。

未知发送者与未知本人身份不同：有稳定发送者但无本人上下文时，仍可按成员统计，却不能推断 self / peer。混合 private / group 或没有可靠会话类型时，核心会话报告类型为 unknown。

依据：[qq_db_adapter.py](src/qq_chat_analyzer/qq_db_adapter.py)、[qq_db_identity.py](src/qq_chat_analyzer/qq_db_identity.py)、[analysis/identity.py](src/qq_chat_analyzer/analysis/identity.py)；守护见 [test_identity_semantics.py](tests/test_identity_semantics.py)、[test_qq_db_adapter_self_identity.py](tests/test_qq_db_adapter_self_identity.py)。

## 2. 微信 self identity canonicalization

Provider 必须先取得唯一候选账号目录；歧义时不产生本人身份。目录可能为 `<基础 username>_<hex suffix>`，只有基础 username 确实存在于 contact.username 时才去掉后缀，不能仅凭字符串形状截断。

不匹配后缀格式或无 contact 佐证时，当前实现保留完整目录候选值；这不授权再猜一个基础 username。Adapter 按传入的 conversation.self_username 与发送者 username 比较；无法可靠提供本人上下文时保持 None。

依据：[wechat_database_provider.py](src/qq_chat_analyzer/providers/wechat_database_provider.py)、[wechat_db_adapter.py](src/qq_chat_analyzer/wechat_db_adapter.py)；守护见 [test_wechat_db_source.py](tests/test_wechat_db_source.py) 的 self username 用例。

## 3. 顺序、时间与 Conversation Sessions

Adapter / Import 与单向投影保留输入顺序，不统一重排所有来源。QQ Provider 按 `40050 ASC, 40001 ASC` 查询；微信 Provider 将匹配 shard 按 create_time 全局排序。会话分析按收到的消息顺序遍历，不自行按时间排序。

共享时间转换支持秒、毫秒及可解析文本；无时区文本按 Asia/Shanghai（UTC+8）解释。数值时间中的零、负值、布尔值、非有限数，以及无法解析的时间为未知，不伪造有效时刻。

默认会话阈值为 1800 秒：当前有效时间与上一条有效时间的差 **大于** 1800 才开始新会话，恰好 1800 仍在同一会话。无效时间消息留在当前会话、不更新上一有效时间；输入时间倒退不会触发正向 gap 边界。时长使用本会话有效时间的 min/max，无有效时间时起止未知、时长为零；消息数量仍包含无效时间消息。

发起者取会话输入顺序的第一条消息，不跳过未知身份寻找后续“已知发起者”：

| 会话 | 发起者归属 |
| --- | --- |
| private | 首条 is_self=True → self；False → peer；None → unknown。unknown 单独计数，不摊给任一方。 |
| group | 使用首条 stable_sender_key（稳定 ID 优先，缺失回退名称），不据昵称猜本人。 |
| unknown | 不推断私聊双方或群聊身份。 |

私聊会话只要有一条 is_self=None，该会话 self_message_count / peer_message_count 就保持 None，不能用不完整身份给出完整双方计数。参与者计数独立采用可归属成员身份。

会话划分、时长、发起者及聚合统计由核心计算；AnalysisApplicationService 调用核心，Presentation / Echo Report 消费结果，不重新计算另一套 session statistics。

依据：[conversation_sessions.py](src/qq_chat_analyzer/analysis/conversation_sessions.py)、[timestamps.py](src/qq_chat_analyzer/analysis/timestamps.py)；边界与三态守护见 [test_conversation_sessions.py](tests/test_conversation_sessions.py)。

## 4. QQ authored lexical text

ReplyRelation、MentionRelation 是结构化关系，不等于用户当前输入的正文。reply 自动附带的 mention、引用片段和结构化 mention 的 display name 不应作为正文重复计入词法；用户实际输入的普通 TextContent 必须保留。

QQ Adapter 按段序保留文本与 face，关系单独保存；图片为 NonTextContent("image")，未识别非文本为 "unknown"，不猜媒体类型或去重重复段。ChatMessage 正文只投影 TextContent；没有正文的消息仍可参与消息和表达统计。

结构化表情与 Unicode emoji 有独立表达通道；表达展示文本不能污染词频、独特词或语言画像。MarketFace 由原始 bytes 的 SHA-256 建立独立命名空间的不透明 sticker 身份，不等于已解码 QQ emoji ID。

依据：[legacy_projection.py](src/qq_chat_analyzer/legacy_projection.py)；守护见 [test_qq_db_rich_contents.py](tests/test_qq_db_rich_contents.py)、[test_expression_lexical_boundary.py](tests/test_expression_lexical_boundary.py)、[test_rich_filtering_association.py](tests/test_rich_filtering_association.py)。

## 5. 表达数据流向与消费契约

以下是源码核实的现役行为；测试证据单列，不代表本次运行过测试，也不承诺完整 Unicode 覆盖。

```text
QQ / 微信 DB payload → Adapter → RichMessage
                                ├─ TextContent → ChatMessage 单向投影
                                └─ ExpressionContent / NonTextContent 留在 Rich
ImportService 保存 (ChatMessage 实例, RichMessage) 配对
  → scope → Smart Profile（发送者 / 整条模板）→ 质量过滤 → kept_messages
  → 按存活投影实例关联 rich_by_instance
      ├─ 正文 → clean_text → tokenize + 停用词 → 全局词频
      │       + _expression_tokens → sender_tokens → 去除 expression: token
      │         → 成员常用词 / 特色词 / 私聊语言画像 / CLI 词语产物
      └─ 原正文 + Rich 表达 → ExpressionAnalyzer（预检一次，报告复用）
          → prepare_expression_report → AnalysisReports.expression
          → Echo builders → EchoReportView → JSON / 内嵌同一 JSON 的 HTML
```

### 来源识别与投影边界

**现役实现已满足／已核实**（[QQ Adapter](src/qq_chat_analyzer/qq_db_adapter.py)、[微信 Adapter](src/qq_chat_analyzer/wechat_db_adapter.py)、[投影](src/qq_chat_analyzer/legacy_projection.py)）：

- Unicode Emoji 在 Adapter 中仍是 TextContent；首次识别发生在分析阶段的 `iter_emoji_clusters()`，不是来源层。QQ 内置 face 在 `_content_from_segment()` 按 type 6 / `47601` 首次识别；MarketFace 按 type 11 / `45600` 原始 bytes 的 SHA-256 识别为 sticker，标签不参与身份判定。
- 微信 type 1 的已知官方方括号表情在 `_extract_official_text_expressions()` 首次识别，英文别名归一为官方名称，同时保留原 TextContent；type 47 在 `_sticker_expression()` 识别为 sticker，key 优先 XML md5，否则 message_id，再否则 `unknown`。降级 key 不能证明相同素材身份。此 Adapter 只接收 type 1 / 47，其他类型被跳过，不能声称微信普通图片已有完整通路。
- QQ type 2 为 `NonTextContent("image")`，其他未识别段为 `"unknown"`；缺少必需 face / sticker 身份的段可能不产生内容。未知图片不推断为 sticker。通用文字占位符（如 `[表情]`、`[贴图]`）在分析时被当作 platform_face 占位事实，不证明原消息确有可识别素材。
- 投影保留身份及名称字段、时间、来源／原生类型、会话、消息 ID、系统标记、is_self 与 recalled 布尔值；正文仅拼接 TextContent。表达、非文本段、段位置／上下文、reply / mention、recall event 及“召回状态未知”不进入 ChatMessage；完整事实依赖原 Rich 配对，不能从投影重建。

### 过滤、隔离与统计消费者

**现役实现已满足／已核实**（[analysis_service.py](src/qq_chat_analyzer/application/analysis_service.py)、[ExpressionAnalyzer](src/qq_chat_analyzer/analysis/analyzers/expression_analyzer.py)、[tokenizer.py](src/qq_chat_analyzer/tokenizer.py)）：

- scope、发送者 ignore、模板 ignore、质量过滤均删除整条分析输入；活动、会话、成员、词法和表达统计统一消费 kept_messages，其 Rich 事实也随之排除。过滤器保留实例和顺序，不改正文；模板和质量规则看投影文本，不检查 sticker 资源。导入／范围诊断计数有自己的阶段口径，不能与最终统计混用。
- 停用词只影响 `tokenize()` 的普通词法结果，不删消息、不删表达，也不影响 ExpressionAnalyzer 的邻近词；后者另用内置停用词和噪声规则。结构化表达展示名从不拼入正文；tokenizer 屏蔽已知官方方括号表情及通用占位符，普通词再按有效字符等规则筛选。这不等于已证明所有 Unicode 序列都不会产生词法残片。
- `_expression_tokens()` 与 ExpressionAnalyzer 重复遍历表达，但共用 `iter_emoji_clusters()` 和 `iter_expression_placeholders()`，并分别读取同一 Rich 的 ExpressionContent。前者扫描投影正文，后者有 Rich 时扫描其 TextContent 拼接；正常投影配对下正文相同，当前未见由两套 Unicode 规则造成的结果分叉。只有 ChatMessage 的输入仍可识别 Unicode／通用占位符，不能恢复来源内置表情事实。
- `expression:` token 随 sender_tokens 暂存，现役 `_build_reports()` 在传给成员常用词、特色词、私聊语言画像前统一去除；CLI 词语归属也用去除后的 token。该临时表达通道当前不直接生成 Echo 词榜。ExpressionAnalyzer 独立生成表达全局／成员统计，再供 Echo 表达文化消费。
- 表达出现次数逐次累计；带表达／纯表达消息按消息计数，每个 key 的伴随文字／纯表达次数也按消息去重。纯表达判定只看正文与表达，未将同消息的 NonTextContent 纳入判定。sticker 计入全局与成员总量、种类和纯表达统计，但不进入邻近词及组合统计；组合为同消息不同非 sticker key 的无序对，超过 64 个不同 key 时整条消息跳过组合，其他总量保留。
- 邻近词来自整条正文的清理分词，不使用 ExpressionContent 的位置／前后片段；同一消息的邻近词会附到其中每个非 sticker 表达。无法归属成员的消息仍进入全局表达，成员占比的分母含这些全局出现次数，因此成员占比之和不保证 100%。

### 统计结果与展示边界

**现役实现已满足／已核实**（[builders.py](src/qq_chat_analyzer/presentation/builders.py)、[echo_serializer.py](src/qq_chat_analyzer/presentation/echo_serializer.py)、[expression_assets.py](src/qq_chat_analyzer/presentation/expression_assets.py)、[HTML 模板](src/qq_chat_analyzer/presentation/echo_report_template.py)）：

- Analyzer 保留完整排序候选；`prepare_expression_report()` 保留原始前缀（全局 10、成员 3、组合 3）及展示选中项，返回裁剪后的不可变报告，原报告与聚合总量不变。应用返回的候选列表已不完整，不能对列表求和重算总量。
- `_display_expression_items()` 有意只展示 count ≥ 2 的非 sticker，最多全局 5／成员 3；先筛选再限额，可补入较低排名。组合展示 count ≥ 2、最多 3；常用者另按次数、占比和可展示成员筛选。以上都不回写基础统计。sticker-only 报告可有非零总量和空榜单，这不是表达在投影中丢失。
- 资源按显式 QQ／微信来源解析，不按数字 key 猜平台；无图片资源时保留文字 fallback，不以资源缺失删除组合。JSON 直接序列化已选视图，不重算表达总量、不再按 sticker 筛选；不输出 expression_key，输出 display_text、count、kind、asset_key 等展示字段，不能用来重建完整表达事实。serializer 的 `_word_to_display()` 另有较窄 Unicode 范围判断，但现役词榜已排除 expression token，不能将此辅助路径误报为表达文化章节的当前识别分叉。
- HTML 按 `expression_culture.available` 显隐章节；该值由是否有表达成员决定，因此仅有无法归属成员的全局表达可在 JSON 保留而整章隐藏。前端逐项渲染已选榜单；“常用表达”显示榜单长度，不显示全局 unique_expression_count，文案已注明展示口径。缺资源显示文字；已有图片加载失败则隐藏图片，次数仍在。上述显隐不改变统计，不能将页面可见项视为完整事实。

### 已有回归保护与后续补足

**现有测试已覆盖**（本轮仅审阅）：

| 契约 | 具体测试位置与边界 |
| --- | --- |
| QQ 多段正文、重复表达、face / sticker 身份隔离、来源至分析链 | [test_qq_db_rich_contents.py](tests/test_qq_db_rich_contents.py)：`test_all_text_segments_and_second_segment_unicode_survive`、`test_repeated_faces_and_stickers_are_occurrences_with_stable_distinct_keys`、`test_provider_import_legacy_and_expression_report_chain`；微信 type 47 见 [test_wechat_db_source.py](tests/test_wechat_db_source.py)：`test_sticker_row_becomes_rich_expression_and_legacy_message`。 |
| scope／质量过滤后 Rich 不串线，重复／缺失 ID 与临时表达 token 一致 | [test_rich_filtering_association.py](tests/test_rich_filtering_association.py)：`test_filtered_duplicate_id_cannot_supply_rich_facts`、`test_missing_id_preserves_structured_expression`；当前参数只有 scope / quality，没有发送者／模板端到端表达断言。 |
| 常见 Unicode 聚簇、成员归属、消息计数去重、组合预算 | [test_expression_analyzer.py](tests/test_expression_analyzer.py)：`test_unicode_emoji_clusters_are_counted_and_attributed`、`test_expression_message_counts_deduplicate_repeated_occurrences`、`test_over_budget_message_does_not_count_a_biased_prefix_of_pairs`。 |
| 结构化表达不污染词频／特色词，私聊语言画像排除表达 token | [test_expression_lexical_boundary.py](tests/test_expression_lexical_boundary.py)；[test_analysis_reports_service.py](tests/test_analysis_reports_service.py)：`test_private_expression_tokens_do_not_reenter_language_profile`。前者精确来源计数用例明确未加入 Unicode，不能扩大为所有 Unicode 的词法隔离证明。 |
| 候选裁剪不改聚合／当前视图，sticker-only 仍导出且榜单为空 | [test_analysis_reports_service.py](tests/test_analysis_reports_service.py)：`test_report_boundary_does_not_retain_full_expression_candidates`、`test_sticker_only_chat_returns_expression_only_with_echo_artifacts`；前者候选是 Unicode，不覆盖 sticker 占据榜首后的补位。 |
| 自包含资源与 HTML fallback | [test_echo_report_serializer.py](tests/test_echo_report_serializer.py)：`test_echo_report_html_inlines_expression_assets_without_local_paths`；[test_echo_conversation_sessions_frontend.py](tests/test_echo_conversation_sessions_frontend.py) 中浏览器断言覆盖缺失资源文字与损坏图片隐藏，不证明全部表达显隐语义。 |

**需要后续补足**（本轮不修复、不新增测试，按优先级）：

1. **Unicode 识别与贯通验证**：现役算法是区间启发式，并非完整 Emoji 属性／序列规则；如 keycap `1️⃣` 的字符均不能命中当前 base 区间。需后续修复并核对全局／成员、纯表达、组合、邻近词、空文本状态与 Echo JSON / HTML；同时验证词法隔离及两处扫描的一致性。识别／统计结果变化属于 [analysis/revision.py](src/qq_chat_analyzer/analysis/revision.py) 的语义修订范围，不能仅按展示变更处理。
2. **跨模块回归缺口**：发送者／模板过滤已有 [Smart Profile 测试](tests/test_smart_profile.py)，但尚缺与 Rich 表达联合的端到端断言；展示还需定向保护 sticker 榜首补位、裁剪前后总量不变及无成员时的章节显隐。它们是验证不足，不是已证明的表达泄漏或误删。
3. **已核实的成员字段语义缺口**：ExpressionAnalyzer 的成员 top_expressions 仅 count 为成员口径，`with_text_message_count`、`text_only_message_count`、`nearby_words` 复用全局同 key 数据，并进入 JSON；不能解释为该成员自己的上下文。目前 HTML 未展示前两项，但会展示邻近词。需后续明确消费合同并加不同成员使用同一表达的回归；不得将其描述成已正确按成员隔离。

**已确定但尚未实现的产品边界**：未来「表情」统计只包括 Unicode Emoji 和 QQ／微信官方内置表情；「表情包」作为独立章节，统计能够可靠识别的商城、自定义贴图。未知图片及无法证实身份的文字占位符不得冒充具体表情。当前 ExpressionReport 仍混合部分表情与 Sticker 统计，后续拆分须同步检查全局／成员口径、报告消费者及分析语义修订号。
