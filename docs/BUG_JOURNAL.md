# Echo Bug Journal

> **退休导航（2026-10-07）**：QCE 产品入口及其文件输入兼容已正式移除，不代表所有本地文件分析入口退休。
> 下文 QCE payload、旧命令与已删除测试路径仅作历史证据，不表示当前仍受支持；现役架构与状态分别见
> [ARCHITECTURE](../ARCHITECTURE.md) 和 [HARDENING](HARDENING.md)。

> **定位**：只记录「已经解决并验证」的真实工程问题。
>
> [HARDENING](HARDENING.md) 维护现存风险和验证缺口；尚未解决的问题按需要使用 Issue 跟踪。
> 各条修复方式、测试清单与真人验收描述记录当时的证据，不自动构成当前实现或发行版本的保障。

## 固定模板

每条记录按以下结构书写：

1. 现象
2. 为什么难查
3. 当时错误 / 竞争假设
4. 最终根因
5. 原代码的隐含假设
6. 为什么开发机或普通场景没有暴露
7. 哪个诊断 / 实验真正钉死根因
8. 最终修复
9. 可推广的工程经验
10. 可以反向审计仓库的规则
11. 对应 regression test

---

## Journal 001 — WeChat 多账号数据库与 Key 错配

### 1. 现象

在真实朋友机器上，微信连接 / 数据库读取失败；
机器存在非默认盘符和多个账号数据目录。

### 2. 为什么难查

Key 获取链和 `session.db` 选择链各自看起来都能成功，
失败发生在两条链组合之后。

### 3. 当时错误 / 竞争假设

包括路径发现错误、Key 提取失败、WCDB 兼容问题等。

### 4. 最终根因

Key capture 选择了一个 Weixin.exe / account，
Provider 又独立选择了另一个 `session.db`；
系统没有「Key 与数据库必须属于同一账号」的验证。

### 5. 原代码的隐含假设

「机器上只有一个可用微信账号 / 数据库候选，
任意成功 Key 可以读取任意发现的 `session.db`」。

### 6. 为什么开发机或普通场景没有暴露

现有封版记录不足以确定，本 Journal 不补充未经验证的推断。

### 7. 哪个诊断真正钉死根因

对数据库候选逐个使用捕获 Key 执行真实可读性验证，
确认只有匹配账号数据库可成功读取。

### 8. 最终修复

- 使用同一 WCDB InnerHandle prepare / step / read 路径做可读性验证；
- probe 候选数据库；
- 只有唯一 readable account 时选择；
- 持久化前再次 official verify；
- provider cache / invalidation 与 GUI directory recovery 配合。

### 9. 可推广的工程经验

任何 credential / key 与 resource / database 的自动发现都不能独立完成后直接组合；
必须验证它们属于同一 identity / domain。

### 10. 可以反向审计仓库的规则

搜索所有「独立发现 credential + 独立发现 resource + 最后组合使用」的链路，
确认是否存在 pairing verification。

### 11. 对应 regression test

当时的回归清单；前两项节点现已删除，其余四项仍存在：

- `tests/test_wechat_database_probe.py::test_probe_uses_the_same_key_for_all_unique_candidates`
- `tests/test_wechat_database_recovery.py::test_probe_result_preserves_owning_account_data_root`
- `tests/test_wechat_database_recovery.py::test_unique_readable_candidate_recovers_to_owning_account_root`
- `tests/test_wechat_database_recovery.py::test_multiple_readable_candidates_do_not_auto_recover`
- `tests/test_wechat_db_source.py::test_verify_readable_keeps_the_key_off_the_command_line`
- `tests/test_wechat_db_source.py::test_sanitize_wcdb_message_redacts_path_key_and_sql`

该修复同时新增了 probe / recovery / setup service / facade 侧的多条覆盖，
此处只列与「Key 与数据库必须同账号」这一根因边界最直接相关的条目。

### 历史状态

CLOSED / merged。

历史修复 commit：

```text
387f1fa14ce209eb5bcc36a8e10b6fbce95416c8 fix(wechat): recover database root matching captured key
c118929b73f746e1f199ed3e7e96f33f0d089c3a Merge pull request #15 from lingmeng-658/fix/wechat-wcdb-prepare
```

---

## Journal 002 — QQ structured expression fallback 污染普通文本统计

> 说明：本条第 6 项没有足够历史证据，因此明确保留未知；
> 第 9、10 项为基于已确认根因总结出的工程经验与审计规则。

### 1. 现象

QQ 私聊 / 群聊普通词频和「你常说 / TA常说」
被结构化表情的 fallback name 污染。

### 2. 为什么难查

单条 QCE payload 同时含 aggregate text 与 structured expression，
单看两者都像合法数据。

### 3. 当时错误 / 竞争假设

tokenizer、stopwords、presentation、expression analyzer 等。

### 4. 最终根因

`qq_chat_exporter_adapter::_build_rich_contents()`
把 aggregate `content.text` 作为 `TextContent`，
同时又提取 `ExpressionContent`。

于是同一结构化表情同时进入：

- ordinary lexical text
- expression analytics

### 5. 原代码的隐含假设

QCE aggregate `content.text` 永远代表用户真正输入的普通文本。

### 6. 为什么开发机或普通场景没有暴露

封版记录未包含本项，待人工补充。

### 7. 哪个诊断真正钉死根因

构造三个最小样本：

- expression-only
- authored text + expression
- 用户真的手输 Laugh

这三个样本把「fallback text」和「真实 authored text」
的语义边界钉死。

### 8. 最终修复

结构化 QQ expression 保留在 `ExpressionContent`；
其 fallback text 不进入普通 lexical stats；
用户真实输入同名词仍正常统计。

### 9. 可推广的工程经验

（据根因补充）结构化能力与普通文本统计必须由显式的语义边界分开：
「展示用的 fallback 文本」不等于「用户 authored 的普通文本」。
两者若共用同一条进入统计的路径，就必然互相污染。

### 10. 可以反向审计仓库的规则

（据根因补充，供人工确认）检查所有「结构化内容 + 其展示 fallback 同时向后传递」的链路，
确认 fallback 文本是否也被当作普通文本进入 lexical 统计。

### 11. 对应 regression test

以下为历史回归清单；QCE adapter 测试文件及此处的旧 service 测试节点均已删除：

- `tests/test_qq_chat_exporter_adapter.py::test_structured_expression_fallback_is_not_text_content`
- `tests/test_qq_chat_exporter_adapter.py::test_mixed_expression_fallback_preserves_only_authored_text`
- `tests/test_qq_chat_exporter_adapter.py::test_plain_text_named_like_expression_is_preserved`
- `tests/test_analysis_reports_service.py::test_private_qce_expression_fallback_does_not_leak_into_voice_words`

当时保护的场景：

- expression-only
- mixed authored + expression
- literal typed word
- private profile regression

现役来源的相关语义回归见 [test_expression_lexical_boundary.py](../tests/test_expression_lexical_boundary.py)
及 `tests/test_analysis_reports_service.py::test_private_expression_tokens_do_not_reenter_language_profile`，
不表示旧 QCE 入口继续受支持或旧清单逐项保留。

### 历史状态

CLOSED / merged。

历史修复 commit：

```text
08b644df7d76975a0837e223932ca8f9431c20a0 fix(qq): keep structured expressions out of text stats
0892cd704e840ca04c30b115f3bcfb787779927c Merge pull request #16 from lingmeng-658/fix/qq-expression-text-leak
```

**特别注明**：后续观察到 Facepalm / Sob / Laugh / ThumbsUp 的截图属于 WeChat，
不能把它当作这个 QQ Bug 重新出现的证据。
QQ 与 WeChat 必须分别追根因。

---

## Journal 003 — WeChat 英文官方表情别名污染普通语言统计

### 1. 现象

真实 WeChat 会话中，英文官方表情 code（`Facepalm` / `Sob` / `Laugh` /
`ThumbsUp` 等）出现在普通语言画像里，例如「你常说 / TA常说 / 同频」词表。
表情本身在 UI 中显示为图片，但这些英文名以普通 token 的形式进入了统计。

### 2. 为什么难查

同一段 `[Facepalm]` 文本同时穿过三条链：

- expression 识别（本应命中官方表情）；
- tokenizer lexical preprocessing（负责处理 bracket 标点）；
- 普通词频 / 语言画像统计。

三条链各自看都「正常」：表情报告里有表情，词频里也有词。
污染只在两条链的**交界处**成立，单看任何一条链都不像错误。

### 3. 当时错误 / 竞争假设

- 英文 stopword 覆盖不足：应该补更多英文停用词；
- 英文词本来就不该进入中文语言画像：应该屏蔽所有英文；
- bracket 文本都是噪声：应该删除所有 `[A-Za-z]+`；
- tokenizer 或 expression analyzer 单点故障。

这些假设都被最终证据否定：污染词不是功能词，而是官方表情 code；
`[TODO]` / `[AI]` / `[Python]` 是用户真实内容；
bare `Laugh` / `Lol` 也是用户真实输入。

### 4. 最终根因

```text
official WeChat expression English alias
→ expression recognizer 未接住
→ bracket punctuation 被 lexical preprocessing 去除
→ alias body 被当成 ordinary English token
→ 泄漏进 language profile
```

即：官方表情的英文 bracket alias 不在 expression 识别表的覆盖范围内，
识别失败后文本没有被标记为「未知表达式」，
而是被当作普通文本继续走 lexical 预处理，最终成为普通 token。

### 5. 原代码的隐含假设

「WeChat 官方 expression bracket code 只有中文 canonical name 一种书写形式。」
以及由此导出的：「expression 识别未命中时，bracket 内容不会成为普通语言 token。」

### 6. 为什么开发机或普通场景没有暴露

已确认的部分：既有样本与测试使用的中文 canonical name（`[捂脸]` 等）
一直能正常识别，链路不会出错；
只有出现英文 alias 输入时，才进入「未命中 → 降级为普通文本」路径。
封版记录未包含本项的完整暴露条件，未经验证的推断不补写。

### 7. 哪个诊断 / 实验真正钉死根因

用虚构样本做最小对照，同时观察 expression 识别与 tokenize 输出：

- `[Facepalm]`（英文 alias）→ 未命中 expression，本体进入 lexical token；
- `[捂脸]`（中文 canonical）→ 正常识别为同一表情，不进入 lexical token；
- `[TODO]`（普通 bracket text）→ 本来就应该保留为普通 token。

后续在 alias 全量核对时，`[Pooh-pooh]` 暴露了第二个缺陷：
hyphenated ASCII protection 比 expression masking 先执行，
把带连字符的 alias 提前替换成占位符，expression 识别再也看不到它。
这钉死了「preprocessing order 也是契约」这一结论。

### 8. 最终修复

- 建立 official alias -> canonical expression normalization：
  `[Facepalm]` 与 `[捂脸]` 归一到同一 canonical expression；
- 110 个官方英文 aliases 全部纳入 mapping / tokenizer / adapter 三层契约；
- alias 匹配大小写不敏感；`[LetDown]` 与 `[Let Down]` 归一到同一表情；
- 不做泛化规则：不把任意 `[A-Za-z]+` 当表达式，
  `[TODO]` / `[AI]` / `[Python]` 保留为普通文本；
- bare `Laugh` / `Lol` 等无 bracket 的用户真实输入保留；
- 调整 preprocessing order：expression masking 必须先于
  hyphenated ASCII protection，保证 `[Pooh-pooh]` 这类 alias 能被识别。

### 9. 可推广的工程经验

- 「格式识别」的覆盖单位应是官方 source representation 全集，
  而不是最常见的书写形式；官方同时接受中文名与英文 code，
  识别器就必须同时覆盖两者。
- 识别失败时的**静默降级**是污染的真正入口：本应报「未知表达式」的文本
  被降级成普通文本，错误不会消失，只会流入下游统计。
- placeholder / 保护性正则的**执行顺序是契约的一部分**：
  两个各自正确的步骤按错误顺序执行，会产生错误结果。

### 10. 可以反向审计仓库的规则

- 搜索所有「识别 → 未命中 → 降级为普通文本」的链路，
  确认未命中不会静默进入统计；
- 搜索所有 placeholder / protection 正则链，
  确认 masking 步骤先于 protection 步骤；
- 对照 vendored 官方 code 表，确认 alias 全集（含带空格、带连字符、
  大小写变体）都有对应条目。

### 11. 对应 regression test

以下保留修复当时的测试名称；mapping 测试文件已删除，所列 tokenizer / adapter 节点也已删除，
不能作为现役测试清单：

`tests/test_wechat_official_emojis.py`（mapping 契约）：

- `test_alias_map_only_normalizes_to_official_names`
- `test_alias_lookup_is_case_insensitive_and_rejects_unknown_codes`
- `test_previously_missing_english_alias_normalizes_to_canonical_name`
- `test_english_alias_keys_never_shadow_a_canonical_name`
- `test_spaced_let_down_and_joined_let_down_both_map_to_disappointment`
- `test_awesome_normalizes_to_the_numeric_canonical_666`
- `test_legacy_english_aliases_are_preserved`
- `test_every_current_client_code_is_recognized`
- `test_every_alias_resolves_to_declared_canonical`
- `test_alias_keys_do_not_collide_after_case_folding`

`tests/test_tokenizer.py`（tokenizer 契约）：

- `test_official_wechat_english_alias_is_not_a_language_token`
- `test_standalone_official_wechat_english_aliases_are_not_tokens`
- `test_bracketed_plain_english_words_are_not_expressions`
- `test_literal_english_words_without_brackets_are_preserved`
- `test_every_alias_bracket_is_masked_as_an_expression`
  （对 110 个 alias 全量参数化，`[Pooh-pooh]` 的 preprocessing order
  缺陷当时由它锁定）
- `test_newly_added_english_aliases_are_masked_as_expressions`
- `test_newly_added_english_alias_never_leaks_into_language_tokens`
- `test_undocumented_bracketed_english_stays_a_plain_word`
- `test_all_current_official_codes_are_masked_as_expressions`

`tests/test_wechat_db_source.py`（adapter 契约）：

- `test_text_row_keeps_unknown_bracket_text_as_plain_text`
- `test_english_alias_is_normalized_to_the_chinese_official_expression`
- `test_english_alias_and_chinese_name_share_one_expression`
- `test_new_english_alias_normalizes_to_canonical_expression`
- `test_spaced_and_joined_let_down_share_one_expression`
- `test_awesome_and_chinese_666_share_one_expression`
- `test_every_current_official_code_is_recognized_in_one_text_row`
- `test_every_alias_bracket_becomes_canonical_expression`
- `test_plain_bracketed_english_stays_plain_text`

现役表情与普通词统计隔离的相关覆盖见
[test_expression_lexical_boundary.py](../tests/test_expression_lexical_boundary.py)
及 `tests/test_analysis_reports_service.py::test_private_expression_tokens_do_not_reenter_language_profile`；
这些断言不等同于上述历史 alias 全量契约逐项仍有覆盖。

真实验收：

当时在朋友机器 / 真实 WeChat 数据上使用修复版本复验通过：
原先的英文 expression names 不再进入语言画像，使用过程中未发现新 Bug。

### 历史状态

CLOSED / merged。

历史修复 commit：

```text
8cf051889664e37ae76dcd61a29de8404a00151b fix: support WeChat English expression aliases
1d2942d9dc0642da288479d30e0f8e38be6095b4 Merge branch 'fix/wechat-english-expression-aliases'
```

---

## Journal 004 — QQ reply / mention display text 污染 authored content

### 1. 现象

QQ 的 reply 自动附带 `@`，普通 structured mention 也带有供展示的名称；这些展示文本被重复算入 authored lexical content。

### 2. 为什么难查

同一条 payload 同时承载 reply / mention relation 和可供文本分析的内容，显示正常时很难发现统计边界已被污染。

### 3. 当时错误 / 竞争假设

曾需区分是 tokenizer、mention rendering，还是 adapter 在组装 authored text 时重复保留了结构化展示内容。

### 4. 最终根因

reply 自动 mention 与 structured mention display text 被当作普通正文投影；它们实际属于关系元数据，而不是用户 authored lexical text。

### 5. 原代码的隐含假设

任何出现在 QQ message display representation 中的文本都等同于用户亲自输入的正文。

### 6. 为什么开发机或普通场景没暴露

现有证据不足，Journal 不补写未经验证的暴露条件。

### 7. 哪个诊断 / 实验真正钉死根因

最小 QQ reply 和 mention payload 对照，分别断言 relation 仍可表达、display text 不进入 authored text、用户在 mention 后实际输入的 text 仍保留。

### 8. 最终修复

把 reply relation / mention semantics 与 authored text 分离：reply 自动 mention 和 structured mention display text 不进入 lexical content，真正输入的普通 text 保留。

### 9. 可推广的工程经验

展示用文本、结构化关系与 authored text 必须显式建模为不同语义；不能因为它们同处一个 source payload 就共用 lexical 投影。

### 10. 可以反向审计仓库的规则

检查所有 adapter：凡是 relation、reply、mention 或展示 fallback 与正文同时存在的地方，都要确认结构化 display data 不会重复进入词频和语言画像。

### 11. 对应 regression test

- `tests/test_qq_chat_exporter_adapter.py::test_reply_message_excludes_auto_mention_from_authored_text`
- `tests/test_qq_chat_exporter_adapter.py::test_plain_at_text_does_not_count_mention_display_emoji_as_authored_text`
- `tests/test_qq_chat_exporter_adapter.py::test_plain_at_text_preserves_emoji_authored_after_mention`

以上为历史证据，所属 QCE adapter 测试文件已随旧入口退休，不是当前回归入口。

历史状态：CLOSED / merged。覆盖 commit：`d4d68f3`、`a9afca1`。

---

## Journal 005 — QQ 长期 Snapshot 使重新分析可能读取旧数据

### 1. 现象

新消息出现后重新全量分析可能复用旧 raw `ChatDataSnapshot`，而不是重新获取 QQ 数据。

### 2. 为什么难查

分析、报告和历史都能成功完成；错误在 acquisition resource ownership 与生命周期，而非分析算法。

### 3. 当时错误 / 竞争假设

需要区分 QCE 是否未导出新数据、导入是否遗漏，还是 stale snapshot 在重新分析前被复用。

### 4. 最终根因

生产设计允许长期 raw `ChatDataSnapshot`，使后续分析拥有读取旧 acquisition payload 的路径。

### 5. 原代码的隐含假设

raw acquisition snapshot 可以安全地作为长期 cache / asset 被重新使用。

### 6. 为什么开发机或普通场景没暴露

现有证据仅证明新增消息后的真实全量重新分析消息数准确增长；不足以补写更广泛的暴露条件。

### 7. 哪个诊断 / 实验真正钉死根因

真实验收在新增消息后重新全量分析，消息数按预期增长；配合生产 snapshot removal 与 transient lifecycle 回归测试确认不再复用长期 raw payload。

### 8. 最终修复

删除生产 `ChatDataSnapshot`；QQ raw acquisition 改为 Echo-owned transient lease，正常 consumer 完成或抛异常后 cleanup，重新分析重新 acquisition。

### 9. 可推广的工程经验

数据正确性不仅由 parser 决定；raw payload 的 ownership、retention 和 cleanup 也是 correctness contract 的一部分。

### 10. 可以反向审计仓库的规则

检查所有“重新执行”路径：若保存 raw input，必须明确其 owner、失效条件、正常与异常 cleanup，以及是否会绕过新的 acquisition。

### 11. 对应 regression test

- `tests/test_snapshot_removal.py::test_qq_full_analysis_always_calls_provider`
- `tests/test_snapshot_removal.py::test_qq_full_analysis_does_not_create_persistent_snapshot`
- `tests/test_full_session_transient.py::test_full_session_run_cleanup_after_consumer`
- `tests/test_full_session_transient.py::test_full_session_exception_still_cleans_up`

以上为历史证据，两个测试文件均已删除，不作为当前生命周期覆盖清单。

历史状态：CLOSED / merged。覆盖 commit：`69eb42b`、`2194bba`。异常终止后的 orphan run directory 回收不在本项已完成范围内。

---

## Journal 006 — WeChat acquisition 时间单位错配

### 1. 现象

有限时间范围的 WeChat acquisition 全部返回 0；ALL 模式因使用 `None` / `None` 不加时间条件而正常。

### 2. 为什么难查

同一 calendar scope 对 QQ/QCE 有效，导致非空 bounds 看起来像已正确下推；真正的 contract 是来源特有时间单位。

### 3. 当时错误 / 竞争假设

不能只断言 scope bounds 非空，还需排除 SQL、session discovery 和应用层 scope filter 的影响。

### 4. 最终根因

毫秒 QCE helper 被复用于 WeChat `m.create_time` SQL；后者使用 epoch seconds。

### 5. 原代码的隐含假设

所有 source acquisition bounds 可使用同一 epoch 单位。

### 6. 为什么开发机或普通场景没暴露

ALL 模式不传 bounds，因而没有触发单位错配；除此之外的历史暴露条件证据不足。

### 7. 哪个诊断 / 实验真正钉死根因

针对有限 scope 的 RED 锁定 seconds contract，而非仅验证 values 非 `None`；ALL 仍保留无过滤行为。

### 8. 最终修复

以 source-specific seconds helper 生成 WeChat SQL bounds；analysis scope filter 继续作为最终 correctness guarantee。

### 9. 可推广的工程经验

同名的“timestamp”或“range”不是跨来源协议；单位、包含边界和空值语义都必须在 source boundary 明确测试。

### 10. 可以反向审计仓库的规则

检查所有跨 source 共用的时间 helper，逐一确认下游 API / SQL 字段的单位与 sentinel 语义，而不是只检查参数存在。

### 11. 对应 regression test

- `tests/test_facade.py::test_wechat_export_scope_uses_seconds_not_milliseconds`
- `tests/test_facade.py::test_wechat_export_keeps_none_when_scope_is_all`
- `tests/test_facade.py::test_wechat_export_pushes_scope_time_window_to_provider`

以上为历史证据，三个测试节点现已删除；不据此宣称当前仍有相同的端到端回归覆盖。

历史状态：CLOSED / merged。覆盖 commit：`e9c2367`。

---

## Journal 007 — WeChat shard rollover 的 cardinality 建模错误

### 1. 现象

一个真实 WeChat session 的新数据位于后续 `message_N.db` shard，但 Provider 只读到第一个 shard 的旧数据。

### 2. 为什么难查

`Msg_*` table 在每个单独 shard 中都可读，单 shard query 正常；DB 与 Provider 的 divergence 只在跨 shard 的真实会话中出现。

### 3. 当时错误 / 竞争假设

需要区分配置 DB 是否更新、直接 DB 是否可读、时间范围是否错误，以及是否为 Provider 的 shard discovery 过早返回。

### 4. 最终根因

代码将 session/table 到 message DB 的关系隐含建模为 1:1，并在第一个 `_table_exists` 命中后返回。

### 5. 原代码的隐含假设

一个 `Msg_*` table 只会存在于一个 message shard。

### 6. 为什么开发机或普通场景没暴露

现有证据不足，不能把单 shard 数据、较短历史或其他未经验证条件写成确定原因。

### 7. 哪个诊断 / 实验真正钉死根因

真实目标 session 的同一 table 在多个 shard 中被确认；direct DB 能读近期数据，Provider 只读第一 shard，形成明确 divergence。

### 8. 最终修复

发现所有 matching shards，对每个 shard 用同一范围查询，merge 后按 `create_time` 全局排序，并在全局结果上应用 explicit positive limit。

### 9. 可推广的工程经验

底层可能存在 partition、shard、rollover 或 migration 时，资源发现的 cardinality 是 correctness contract，不是实现细节。

### 10. 可以反向审计仓库的规则

凡 `_find_xxx()` 返回单个 resource 的链路，若底层可能分区或滚动，审计 1:1 cardinality 假设是否真实成立。

### 11. 对应 regression test

- `tests/test_wechat_db_source.py::test_read_session_rows_queries_all_shards_with_matching_table`
- `tests/test_wechat_db_source.py::test_read_session_rows_respects_global_limit_across_shards`
- `tests/test_wechat_db_source.py::test_read_session_rows_respects_time_scope_across_shards`

历史状态：CLOSED / merged。覆盖 commit：`87b4bae` 的 multi-shard 部分。

---

## Journal 008 — wcdb_cli 的 unlimited sentinel 跨层错配导致 100000 静默截断

### 1. 现象

超过 100000 行的 WeChat acquisition 可被静默截断，且 `truncated` 仍可能为 `false`。

### 2. 为什么难查

Python Provider 的 `_query(limit=0)` 意图是“不设 limit”，而 native helper 对 no-limit / `0` 的 fallback 是另一套行为；单独测试任一层都难以发现错配。

### 3. 当时错误 / 竞争假设

需区分 Provider 是否传参错误、native CLI 是否截断，或结果 metadata 是否错误报告。

### 4. 最终根因

native `wcdb_cli` 将 no-limit / `limit=0` 回退到 100000，和 Provider 的 unlimited sentinel 语义不一致。

### 5. 原代码的隐含假设

跨语言 / 跨进程边界两端对 `0` 的含义天然一致。

### 6. 为什么开发机或普通场景没暴露

需要超过 100000 行才触发；其余历史暴露条件证据不足。

### 7. 哪个诊断 / 实验真正钉死根因

synthetic SQLite 100001 rows 对旧 binary 的端到端 RED 返回 100000；rebuild 后 GREEN 返回 100001 且 `truncated=false`。

### 8. 最终修复

native CLI 将 no-limit / `limit=0` 解释为持续 step 到 statement done；Provider 正常 message acquisition 保持 unlimited 默认。

### 9. 可推广的工程经验

`0`、`None`、`-1` 和 empty 等 sentinel 必须在跨语言 / 跨进程边界以端到端 contract test 固化，不能只分别测试各层。

### 10. 可以反向审计仓库的规则

搜索所有跨层 limit、timeout、offset 和 optional parameter 的 sentinel；验证 caller、transport、native helper 和 result metadata 的语义一致。

### 11. 对应 regression test

- `tests/test_wcdb_cli_unlimited.py::test_native_cli_without_positive_limit_returns_more_than_100000_rows`
- `tests/test_wechat_db_source.py::test_read_session_rows_default_limit_is_unlimited`

以上两项仍存在。历史节点 `tests/test_wechat_db_source.py::test_export_session_json_default_limit_is_unlimited`
现已删除，不计作当前回归覆盖。

历史状态：CLOSED / merged。覆盖 commit：`87b4bae` 的 unlimited 部分。

---

## Journal 009 — QQ Direct DB acquire 因 Proxy thenable 永久 pending

### 1. 现象

Direct DB 的 acquire 在已拿到 DatabaseApi/passphrase 后仍永久 pending。

### 2. 为什么难查

底层对象已就绪，卡住的位置却是 JavaScript async 返回值的 Promise 解析。

### 3. 当时错误 / 竞争假设

需区分 passphrase 尚未到达、RPC 等待超时和 Proxy 返回值自身无法完成。

### 4. 最终根因

QCE API adapter 是 Proxy，其未知方法 fallback 暴露可调用的 `then`；async 函数直接
返回该 Proxy 时，Promise 将它作为 thenable 处理，但 fallback 不调用 resolve/reject。

### 5. 原代码的隐含假设

已就绪的 DatabaseApi Proxy 可直接作为 async 函数返回值。

### 6. 为什么开发机或普通场景没有暴露

该行为依赖真实 QCE Proxy；普通对象替身没有同样的 `then` fallback。

### 7. 哪个诊断 / 实验真正钉死根因

针对带可调用 `then` 的虚构 Proxy 回归复现 pending；修复后该回归与真人 acquire 均通过。

### 8. 最终修复

`waitForDatabaseApi` 返回普通对象包装 `{ databaseApi: api }`，避免 Promise 同化 Proxy。

### 9. 可推广的工程经验

跨 async 边界返回第三方 Proxy 时，需确认它是否意外具有 thenable 形状。

### 10. 可以反向审计仓库的规则

检查 async 函数直接返回第三方 Proxy 的位置；必要时以普通对象承载。

### 11. 对应 regression test

- `tests/test_qq_direct_db_snapshot_runtime.py::test_acquire_does_not_assimilate_database_api_adapter_as_a_thenable`

上述节点为历史证据，现已删除。

历史状态：CLOSED / 当时真人验收通过；修复已提交于 `c739434`，已进入当前分支历史。

---

## Journal 010 — 桌面关闭后 Echo 自有 QQ 进程树残留

### 1. 现象

窗口关闭后，Echo 启动的 QQ/NapCat/qce-server 进程仍可残留。

### 2. 为什么难查

窗口已消失，但 daemon 清理线程尚未完成；解释器退出与进程终止是两个时间点。

### 3. 当时错误 / 竞争假设

需区分未记录 launcher PID、终止失败与退出过程未等待清理完成。

### 4. 最终根因

仅在窗口关闭时启动 daemon 清理不足以保证完成；解释器结束会中断未完成的清理。

### 5. 原代码的隐含假设

窗口关闭后启动的后台清理可以自然完成，无需桌面入口点持有退出权。

### 6. 为什么开发机或普通场景没有暴露

现有证据不足以补写更广泛的暴露条件。

### 7. 哪个诊断 / 实验真正钉死根因

退出协议与进程所有权回归固定先清理 plaintext、再终止已记录 PID 的顺序；
真人验收确认 shutdown 后 QQ/NapCat/qce-server 和 `snapshot.db` 均无残留。

### 8. 最终修复

窗口只启动单次 shutdown protocol；桌面入口点在 Qt event loop 返回后有限等待，
Facade 按顺序清理 Direct DB 与 Echo 自有进程树，超时后有强制退出兜底。

### 9. 可推广的工程经验

资源清理需要明确的 owner 和退出等待边界，不能仅依赖 daemon 线程启动。

### 10. 可以反向审计仓库的规则

检查每条应用退出路径是否等待同一个清理协议，以及终止目标是否仅来自自有 PID 记录。

### 11. 对应 regression test

- `tests/test_gui_shutdown_protocol.py`
- `tests/test_desktop_exit_ownership.py`
- `tests/test_shutdown_ownership.py`
- `tests/test_gui.py::test_main_window_close_owns_shutdown_without_waiting`

历史状态：CLOSED / 当时真人验收通过；修复已提交于 `c739434`，已进入当前分支历史。
上述测试文件与节点仍存在；当前 shutdown 安装准入及验证缺口以 [HARDENING](HARDENING.md) 为准。

---

## Journal 011 — BUG-03 Report Package 生命周期与测试用户目录隔离

### 1. 现象

Local Data 的历史记录与实际报告文件生命周期缺少统一的持久对象边界。
曾观察到点击删除后 GUI 列表为空，但真实 `reports/` 中 package 仍在；该观察后来未复现，
根因未确定，不能写成已证实的 deletion 缺陷原因。

独立确认的问题是自动测试污染真实 `%LOCALAPPDATA%\LocalChatAnalyzer\reports`：
一次相关 / Fast 测试前后 production candidates 从 120 增至 130，新增 10 个测试 package。

### 2. 为什么难查

GUI 列表、独立元数据历史、正式 package、默认 scratch 和来源 acquisition 临时资源
原本是不同观察面；仅看到列表变化不足以证明磁盘 package 被删除。
测试又能走默认用户数据路径，使真人验收环境混入自动生成的报告。

### 3. 当时错误 / 竞争假设

曾考虑 composition 注入了另一个 root、旧 compatibility API、缓存列表清空或安全校验
拒绝删除等可能性。它们没有被确认为上述未复现观察的根因；确认测试污染也不等于证明
“GUI 空但磁盘未空”由测试污染导致。

### 4. 最终根因

已确认并修复的边界缺口是：独立 JSONL history 只表示元数据记录，不能作为报告文件
是否存在或已删除的事实源；测试隔离只覆盖部分 helper / monkeypatch 调用，未覆盖所有
使用默认 `user_data_dir()` 的 packaging / composition 入口，因而可写入真实用户目录。
未复现的删除观察仍保留“原因未知”，不据此补写路径错误或 stub 根因。

### 5. 原代码的隐含假设

元数据历史可以代表持久分析结果；给部分测试 helper 传 `tmp_path` 或 patch packager
就足以隔离整个测试集的默认路径。两者都缺少覆盖真实 package / 默认 composition 的边界保证。

### 6. 为什么开发机或普通场景没有暴露

部分测试已有局部隔离，不能证明其余默认路径安全；更早未暴露的具体条件证据不足。
不把某次未复现观察归因于开发机环境、用户操作或未经验证的配置。

### 7. 哪个诊断 / 实验真正钉死根因

不读取真实报告正文，记录 production candidate count，确认测试运行新增了 10 个 package。
随后用 fake 用户目录与禁止未隔离访问的 sentinel regression 验证默认 packager、
`build_facade()`、环境变量缺失时的 home fallback 都落入测试临时目录。
隔离修复后的 focused / Fast / Full 前后 count 与真实用户目录属性快照保持不变。
后续真人验收通过批量删除及真实分析 → 保存正式 package → 删除链路。

### 8. 最终修复

- Report Package 成为唯一持久分析对象；四文件 staging 完整写入后 rename 发布，
  `metadata.json` 驱动 Catalog，损坏 package 作为 issue 可见。JSONL history 与 manager 已退休。
- 默认 scratch 移至 `transient/`；首次创建默认 scratch 前回收严格命名的 stale 自有目录，
  正常替换、失败与 shutdown 清理；用户自定义输出、未知目录及外部 reparse target 不归其所有。
- Local Data 删除完整 owned package；reopen 经 Facade / Catalog 安全定位 HTML，
  搜索只过滤内存 summaries，不读取报告正文，不隐藏 issues。
- 当时新 package 发布成功后执行固定 max-50 retention，publisher 与 Catalog 共用 root；
  时间未知 package 计数且优先淘汰，删除失败只继续原定淘汰集合，新报告仍成功并显示 warning。
  此策略已在 `4c8c10f` 退休：当前保留报告，由用户主动管理和删除，不因数量超过 50 自动淘汰。
- `tests/conftest.py` 的 autouse fixture 为每个测试设置 fake `LOCALAPPDATA`、`APPDATA`、
  home / XDG 目录并 patch `Path.home()`；测试 helper 显式注入临时 Catalog root，
  sentinel regression 覆盖默认 composition 和 packaging，禁止再碰真实用户数据。

### 9. 可推广的工程经验

持久对象的列表、打开、删除，以及当时的 retention 应共享磁盘 ownership 边界；
GUI 视觉清空不能替代 filesystem 验证。测试隔离必须覆盖默认路径、composition 和 fallback，
不能只依赖单个 helper；环境污染与产品缺陷需要分别取证。

### 10. 可以反向审计仓库的规则

检查所有默认用户数据写入入口是否被 suite fixture 隔离、目录 ownership / reparse 校验是否复用。
当时自动淘汰链路还需验证发布成功后才清理旧资产、清理失败附带 warning；这不是当前报告发布后的自动清理要求。
对未复现现象保留事实与未知，不把竞争假设写成最终根因。

### 11. 对应 regression test

- `tests/test_gui_report_package_deletion.py::test_desktop_checked_delete_changes_disk_and_preserves_unlisted_packages`：勾选删除作用于磁盘，保留未列出的 package。
- `tests/test_report_package_catalog.py`：metadata listing、损坏 package、ownership / reparse、reopen 与报告保留；其中旧名带 retention 的测试实际断言 51 份报告均保留、旧 metadata 不改写。
- `tests/test_facade.py::test_recovery_deletes_only_strict_owned_direct_children_and_continues`：严格限定自有 scratch 回收范围。
- `tests/test_facade.py::test_retention_after_successful_publication_uses_injected_root_and_preserves_new`
- `tests/test_facade.py::test_retention_publication_failure_never_calls_cleanup`
- `tests/test_test_user_data_isolation.py::test_user_data_isolation`
- `tests/test_gui.py::test_local_data_search_reopen_keeps_identity_and_invalidates_selection`：Local Data 搜索、重开身份与选择失效。

上列两个 Facade retention 测试名称沿用旧名：成功发布断言保留 50 份旧报告及新报告且不尝试删除；
发布失败断言不清理旧报告，不代表仍执行 max-50。
历史节点 `tests/test_gui_report_package_deletion.py::test_desktop_delete_all_changes_disk_and_refreshes_remaining_packages`
与 `tests/test_facade.py::test_recovery_runs_once_before_first_default_scratch` 已删除，以上列出现役相关覆盖代替。

历史状态：CLOSED / 当时真人验收通过；修复已提交于 `ec766f2`，已进入当前分支历史。
