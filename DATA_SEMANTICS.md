# Data Semantics

表情包原件数据能力另见 [STICKER_DATA](docs/STICKER_DATA.md)：新通路保留来源确认的
发送记录及独立媒体结果，经现有过滤后的 Rich 实例关联，不改变本页 ExpressionReport
的旧 sticker 总量、候选裁剪或 fallback key。微信只有通过校验且无歧义的 XML MD5
可在新通路归并素材；降级身份逐次独立。QQ MFACE 保留 opaque 身份，原件关联未证实；
QQ PIC 不据动画或路径推断表情包，微信 Type 3 仍不进入已确认集合。

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

QQ Direct DB 私聊与群聊的零值发送者均保留为未知身份：sender_id=None、sender=""、is_self=None，不采用偶然附带的昵称作为参与者身份。它不进入成员画像、成员词语或表达归属、参与者计数及表情素材的逐成员计数，仍参与全局消息量、时间、文本和表达统计；不推定为系统消息、本人或对方。缺失／无效到无法解析的原始记录仍可能被 Adapter 跳过，不等于所有未知输入都必定保留。

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

以下是源码核实的现役行为；测试证据单列，不将定向回归扩大为完整平台或发行验收。

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

- Unicode Emoji 在 Adapter 中仍是 TextContent；首次识别发生在分析阶段共享的 `iter_emoji_clusters()`，不是来源层。识别固定为 Unicode / Emoji 18.0（[UTS #51 revision 31](https://www.unicode.org/reports/tr51/tr51-31.html)）：使用官方 `emoji-test.txt` 的 fully-qualified、minimally-qualified、unqualified 序列及有效 Emoji 呈现变体，最长匹配，不凭区块推断。聊天兼容口径保留裸 `❤`、`♥` 等官方未限定形式，VS16 保留为 Emoji，VS15 明确指定文本时不计该元素；不同合法拼写仍是不同 key。支持官方 RGI 国旗、tag 旗帜、肤色和 ZWJ，单独数字、`#`、`*` 与独立 component 不计，未知组合不推定为新的整体表情。数据随 Python 包离线携带，来源 URL、SHA-256 和 Unicode License V3 见 [_unicode_emoji_data.py](src/qq_chat_analyzer/_unicode_emoji_data.py)，[生成脚本](scripts/generate_unicode_emoji.py) 从固定版本本地文件重建，无运行时网络或新依赖。
- QQ 内置 face 在 `_content_from_segment()` 按 type 6 / `47601` 首次识别；MarketFace 按 type 11 / `45600` 原始 bytes 的 SHA-256 识别为 sticker，标签不参与身份判定。
- 微信 type 1 的已知官方方括号表情在 `_extract_official_text_expressions()` 首次识别，英文别名归一为官方名称，同时保留原 TextContent；type 47 在 `_sticker_expression()` 识别为 sticker，key 优先 XML md5，否则 message_id，再否则 `unknown`。降级 key 不能证明相同素材身份。群聊中他人发送的内容以 `<username>:\n` 开头，Adapter 仅在内容不以 `<` 开头且前缀精确等于该行已确认发送者时剥离，再解析 XML；其他前缀不剥离，仍按未解析身份处理。`cdnurl` 只是未受信获取线索，不参与身份，且必须先通过消息 MD5 校验。此 Adapter 与 Provider 查询均按 `local_type` 的低 32 位识别 type 1 / 47，保留原始 source_type；其他类型被跳过，不能声称微信普通图片已有完整通路。
- QQ type 2 为 `NonTextContent("image")`，其他未识别段为 `"unknown"`；缺少必需 face / sticker 身份的段可能不产生内容。未知图片不推断为 sticker。通用文字占位符（如 `[表情]`、`[贴图]`）在分析时被当作 platform_face 占位事实，不证明原消息确有可识别素材。
- 投影保留身份及名称字段、时间、来源／原生类型、会话、消息 ID、系统标记、is_self 与 recalled 布尔值；正文仅拼接 TextContent。表达、非文本段、段位置／上下文、reply / mention、recall event 及“召回状态未知”不进入 ChatMessage；完整事实依赖原 Rich 配对，不能从投影重建。

### 过滤、隔离与统计消费者

**现役实现已满足／已核实**（[analysis_service.py](src/qq_chat_analyzer/application/analysis_service.py)、[ExpressionAnalyzer](src/qq_chat_analyzer/analysis/analyzers/expression_analyzer.py)、[tokenizer.py](src/qq_chat_analyzer/tokenizer.py)）：

- scope、发送者 ignore、模板 ignore、质量过滤均删除整条分析输入；活动、会话、成员、词法和表达统计统一消费 kept_messages，其 Rich 事实也随之排除。过滤器保留实例和顺序，不改正文；模板和质量规则看投影文本，不检查 sticker 资源。导入／范围诊断计数有自己的阶段口径，不能与最终统计混用。
- 停用词只影响 `tokenize()` 的普通词法结果，不删消息、不删表达，也不影响 ExpressionAnalyzer 的邻近词；后者另用内置停用词和噪声规则。结构化表达展示名从不拼入正文；tokenizer 使用同一 Unicode 匹配器将 Emoji 替换为空格，避免 keycap 的 ASCII 部分粘入词语，并屏蔽已知官方方括号表情及通用占位符；普通词再按有效字符等规则筛选。
- `_expression_tokens()` 与 ExpressionAnalyzer 重复遍历表达，但共用 `iter_emoji_clusters()` 和 `iter_expression_placeholders()`，并分别读取同一 Rich 的 ExpressionContent。前者扫描投影正文，后者有 Rich 时扫描其 TextContent 拼接；正常投影配对下正文相同，当前未见由两套 Unicode 规则造成的结果分叉。只有 ChatMessage 的输入仍可识别 Unicode／通用占位符，不能恢复来源内置表情事实。
- `expression:` token 随 sender_tokens 暂存，现役 `_build_reports()` 在传给成员常用词、特色词、私聊语言画像前统一去除；CLI 词语归属也用去除后的 token。该临时表达通道当前不直接生成 Echo 词榜。ExpressionAnalyzer 独立生成表达全局／成员统计，再供 Echo 表达文化消费。
- 表达出现次数逐次累计；带表达／纯表达消息按消息计数，每个 key 的伴随文字／纯表达次数也按消息去重。纯表达判定只看正文与表达，未将同消息的 NonTextContent 纳入判定。sticker 计入全局与成员总量、种类和纯表达统计，但不进入邻近词及组合统计；组合为同消息不同非 sticker key 的无序对，超过 64 个不同 key 时整条消息跳过组合，其他总量保留。
- 邻近词来自整条正文的清理分词，不使用 ExpressionContent 的位置／前后片段；同一消息的邻近词会附到其中每个非 sticker 表达，沿用逐次表达出现的权重。全局条目的次数和上下文来自全部保留消息；成员 top_expressions 的 count、with_text_message_count、text_only_message_count、nearby_words 均只来自该成员的消息，消息级字段仍按每个 key 每条消息去重。无法归属成员的消息仍进入全局表达，成员占比的分母含这些全局出现次数，因此成员占比之和不保证 100%。

### 统计结果与展示边界

**现役实现已满足／已核实**（[builders.py](src/qq_chat_analyzer/presentation/builders.py)、[echo_serializer.py](src/qq_chat_analyzer/presentation/echo_serializer.py)、[expression_assets.py](src/qq_chat_analyzer/presentation/expression_assets.py)、[HTML 模板](src/qq_chat_analyzer/presentation/echo_report_template.py)）：

- Analyzer 保留完整排序候选；`prepare_expression_report()` 保留原始前缀（全局 10、成员 3、组合 3）及展示选中项，返回裁剪后的不可变报告，原报告与聚合总量不变。应用返回的候选列表已不完整，不能对列表求和重算总量。
- `_display_expression_items()` 有意只展示 count ≥ 2 的非 sticker，最多全局 5／成员 3；先筛选再限额，可补入较低排名。组合展示 count ≥ 2、最多 3；常用者另按次数、占比和可展示成员筛选。以上都不回写基础统计。sticker-only 报告可有非零总量和空榜单，这不是表达在投影中丢失。
- 资源按显式 QQ／微信来源解析，不按数字 key 猜平台；无图片资源时保留文字 fallback，不以资源缺失删除组合。JSON 直接序列化已选视图，不重算表达总量、不再按 sticker 筛选；不输出 expression_key，输出 display_text、count、kind、asset_key 等展示字段，不能用来重建完整表达事实。serializer 的 `_word_to_display()` 辅助表达 token 路径也使用共享识别器，只有完整单个合法序列才作 Unicode fallback；现役词榜仍排除 expression token。
- HTML 按 `expression_culture.available` 显隐章节；该值由是否有表达成员决定，因此仅有无法归属成员的全局表达可在 JSON 保留而整章隐藏。前端逐项渲染已选榜单；“常用表达”显示榜单长度，不显示全局 unique_expression_count，文案已注明展示口径。缺资源显示文字；已有图片加载失败则隐藏图片，次数仍在。上述显隐不改变统计，不能将页面可见项视为完整事实。

### 已有回归保护与后续补足

**现有测试已覆盖**：

| 契约 | 具体测试位置与边界 |
| --- | --- |
| QQ 多段正文、重复表达、face / sticker 身份隔离、来源至分析链 | [test_qq_db_rich_contents.py](tests/test_qq_db_rich_contents.py)：`test_all_text_segments_and_second_segment_unicode_survive`、`test_repeated_faces_and_stickers_are_occurrences_with_stable_distinct_keys`、`test_provider_import_legacy_and_expression_report_chain`；微信 type 47 见 [test_wechat_db_source.py](tests/test_wechat_db_source.py)：`test_sticker_row_becomes_rich_expression_and_legacy_message`。 |
| 四类消息过滤后 Rich 不串线，重复／缺失 ID 与临时表达 token 一致 | [test_rich_filtering_association.py](tests/test_rich_filtering_association.py)：`test_filtered_duplicate_id_cannot_supply_rich_facts`、`test_missing_id_preserves_structured_expression`；scope / quality / sender / template 均覆盖 QQ / 微信，发送者／模板用例验证实际 ignore 决策。`test_unicode_projection_tokens_and_expression_report_agree` 另保护 Unicode 正反例、投影、token 与报告的一致性。 |
| Unicode 18.0、呈现策略、成员归属、消息计数去重、组合预算 | [test_expression_analyzer.py](tests/test_expression_analyzer.py)：`test_unicode_18_sequences_and_chat_presentation_policy`、`test_decorations_do_not_change_expression_totals_or_expression_only_classification`、`test_unicode_emoji_clusters_are_counted_and_attributed`、`test_expression_message_counts_deduplicate_repeated_occurrences`、`test_over_budget_message_does_not_count_a_biased_prefix_of_pairs`。 |
| 成员上下文隔离，全局保留未知发送者表达 | [test_expression_analyzer.py](tests/test_expression_analyzer.py)：`test_member_expression_context_is_local_while_unknown_sender_stays_global` 用两个成员与未知发送者共用同一表情，保护重复出现计数、消息计数去重、不同邻近词及成员 JSON。 |
| 表达不污染词频／特色词／语言画像 | [test_expression_lexical_boundary.py](tests/test_expression_lexical_boundary.py)：`test_unicode_and_structured_expressions_preserve_lexical_consumers` 覆盖 QQ / 微信群聊与私聊；[test_analysis_reports_service.py](tests/test_analysis_reports_service.py)：`test_private_expression_tokens_do_not_reenter_language_profile`；[test_tokenizer.py](tests/test_tokenizer.py) 另保护 keycap 与词语相邻的边界。 |
| 候选裁剪不改聚合／当前视图，sticker-only 仍导出且榜单为空 | [test_analysis_reports_service.py](tests/test_analysis_reports_service.py)：`test_report_boundary_does_not_retain_full_expression_candidates`、`test_sticker_only_chat_returns_expression_only_with_echo_artifacts`、`test_sticker_rank_prefix_does_not_starve_official_expression_display`（QQ / 微信 sticker 榜首补位及裁剪后总量、成员总量与 JSON）。[关联测试](tests/test_rich_filtering_association.py) 的 `test_single_content_kind_keeps_report_status_contract` 覆盖 Unicode、官方表情、sticker、普通词和装饰符号的报告状态。 |
| 自包含资源、HTML fallback 与显隐 | [test_echo_report_serializer.py](tests/test_echo_report_serializer.py)：`test_echo_report_html_inlines_expression_assets_without_local_paths`、`test_expression_token_fallback_uses_the_same_unicode_contract`；[test_echo_conversation_sessions_frontend.py](tests/test_echo_conversation_sessions_frontend.py) 中浏览器断言覆盖缺失资源文字与损坏图片隐藏，`test_expression_chapter_uses_display_count_and_member_availability` 执行前端脚本保护榜单长度与无成员时的章节显隐。 |

**收敛状态与剩余边界**：

1. **Unicode 识别与贯通验证已完成**：官方序列替代区间启发式，定向回归贯通表达与词法消费者；新报告 metadata 的分析修订号为 `echo-analysis.v6`（[revision.py](src/qq_chat_analyzer/analysis/revision.py)）。`test_new_report_metadata_records_corrected_expression_semantics` 保护新报告标记；[Catalog 测试](tests/test_report_package_catalog.py) 保护旧版本快照重开不改内容或修改时间。
2. **原跨模块回归缺口已补足**：四类过滤、词法隔离、sticker 补位、聚合不变、当前 JSON / HTML 显隐及内容单一时的状态均有上述定向用例；未扩展表情包分类或布局。
3. **成员上下文作用域已修复**：成员条目的消息级次数和邻近词均按成员累计，全局统计保留原口径；定向测试贯通 Analyzer、报告构建与 JSON。未改变邻近词的同消息定义、出现权重或 sticker 展示策略。本次修复同属 `echo-analysis.v6`，不迁移或重写历史报告。

**已确定但尚未实现的产品边界**：未来「表情」统计只包括 Unicode Emoji 和 QQ／微信官方内置表情；「表情包」作为独立章节，统计能够可靠识别的商城、自定义贴图。未知图片及无法证实身份的文字占位符不得冒充具体表情。当前 ExpressionReport 仍混合部分表情与 Sticker 统计，后续拆分须同步检查全局／成员口径、报告消费者及分析语义修订号。
