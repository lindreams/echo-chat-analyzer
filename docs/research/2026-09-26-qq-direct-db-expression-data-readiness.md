# QQ Direct DB 表情数据准备度调查

**日期：** 2026-09-26
**性质：** 纯调查 / 字段研究冻结，不实现代码、不下载表情资源、不输出真实聊天数据。
**目标：** 为近期 QQFace / MarketFace 表情统计确认稳定 identity 与资源来源。
**范围：** 只回答“数据是否齐备、能否归一、需要动哪里”，不落地实现。

> 后续事实修正（MFACE 整改）：本文关于 45600 内含 sticker_id/MD5 的判断未获证实，
> 不再作为当前协议依据。现役 Adapter 使用合法 80810/80903 复合资源身份，保留
> 45600-only 旧身份；80903 不是文件 MD5。当前合同见 docs/STICKER_DATA.md。

## 0. 方法与证据来源

- 现有产品代码：`src/qq_chat_analyzer/providers/qq_database_provider.py`（Provider）、
  `src/qq_chat_analyzer/qq_db_adapter.py`（Adapter v0）、
  `src/qq_chat_analyzer/qq_chat_exporter_adapter.py`（QCE 生产路径的表情处理参照）、
  `src/qq_chat_analyzer/rich_message.py`（`ExpressionContent`）、
  `src/qq_chat_analyzer/analysis/analyzers/expression_analyzer.py`（下游消费方）。
- 已有研究资料：`docs/research/2026-09-26-qq-direct-db-field-semantics-freeze.md`
  （`40001/40027/40030/40033/40050/40800` 字段冻结）。
- 社区参考工具：`references/nt_msg_db_util`（QQBackup/nt_msg_db_util），核心证据为
  `msgdb/proto/c2c_40800.proto`、`msgdb/c2c/parser.py`、`msgdb/c2c/models.py`、
  `db_docs/c2c_msg_table/40800.md`、`db_docs/group_msg_table/{40800,40011,40012,40062}.md`、
  `echo_audit_report.md`。

**前置事实（已冻结，见上一份 freeze 报告）：**
`40800` 列是 `MsgBody { repeated MsgContent content = 40800; }` 的 Protobuf BLOB，
一条消息可以含多个 `MsgContent` 段（图文/表情混排）。`45002` 是段级 `content_type`：
`1`=文本、`2`=图片、`6`=`T_QQFace`、`11`=`T_MarketFace`。
表情的全部信息都在 `40800` 内部字段，不依赖主表其它列。

---

## A. QQFace（`45002=6`）最佳 canonical identity 候选

**结论：以 `47601`（face index，小黄脸/QQ 表情编号）为主键，`47602` 为显示文本。**

| 字段 | 类型 | 角色 | 社区置信度 |
| --- | --- | --- | --- |
| `47601` | int32 | **表情 ID / face index**，区分“具体哪个 QQ 表情” | 🔍（样本支持，未全量命名） |
| `47602` | string | 表情外显文字，例如 `/汪汪`（即 faceText/name） | ✅（已验证） |
| `45101` | bytes | 文本正文；纯表情段通常为空，不作为 identity | ✅（文本语义） |
| `45815` | repeated bytes | 文本降级标记，如 `[动画表情]`；仅为占位展示 | ✅（fallback 语义） |

**逐问回答：**

1. **哪个字段能稳定区分具体 QQ 表情**：`47601`（face index）。它与 QCE 生产路径里
   `faceElement.faceIndex / id / faceId` 是同一语义（见 `qq_chat_exporter_adapter.py:524-543`
   的 `_face_expression`）。
2. **是否有 index / text / name**：有。index=`47601`；text/name=`47602`（外显文字）。
   没有独立“name”字段，name 语义由 `47602` 承担；`45815` 是降级占位。
3. **同一种表情重复发送能否稳定归一**：**能。** 用 `47601` 作为 `expression_key`
   即可把同一小黄脸跨消息稳定归一；`47602` 作为 `display_text` 用于展示与“纯表情消息”判定。

**风险：** `47601` 的语义标注是社区 🔍（非 ✅），且 face index 编号空间是否跨 QQ 版本
稳定未证明。对**单库快照内统计**足够稳定；跨版本迁移是否仍一致属于 G 节待确认项。

---

## B. MarketFace（`45002=11`）最佳 canonical identity 候选

**结论：以 `45600`（sticker bytes，内含 sticker_id + md5）为主键候选；当前最稳可用的是
`45600` 的 md5 派生值。显示文本用 `80900`。**

| 字段 | 类型 | 角色 | 社区置信度 |
| --- | --- | --- | --- |
| `45600` | bytes | **sticker 数据（嵌套结构：sticker_id + md5）**，资源/身份载体 | 🔍（内层 id 未解码） |
| `80900` | string | 商城表情显示文本 | ✅（已验证） |
| `45815` | repeated bytes | 文本降级标记 | ✅（fallback 语义） |
| `45802` / `45803` / `45804` | string/bytes | 缩略图 / 预览图 / 原图 CDN URL | ✅ |
| `45812` | bytes | 本地缓存路径 | ✅ |
| `45814` | string | NTOS 路径 | ✅（结构） |

**逐问回答：**

1. **哪个字段能稳定区分具体贴图**：候选是 `45600`（sticker bytes）。它对应 QCE 生产
   路径里 `marketFaceElement.emojiId / key`（`qq_chat_exporter_adapter.py:546-565`）。
   `45600` 是嵌套 Protobuf，内含 `sticker_id`（int）与 `md5`；但社区参考工具当前把
   `sticker_id` 硬编码为 `0`、仅把整段 bytes 转 hex 当 `md5` 用
   （`msgdb/c2c/parser.py:126-134` `_parse_sticker`）。因此**内层 expression id 尚未可靠解码**。
2. **display text / expression id / resource id 分别在哪里**：
   - display text → `80900`（✅）；降级 → `45815`；
   - expression id → 理论上在 `45600` 内层 `sticker_id`（**尚未解码**）；当前可用的稳定
     替代是 `45600` 整段 bytes 或其 md5 hex；
   - resource id / 图片 → CDN URL `45802/45803/45804`、本地路径 `45812`、NTOS `45814`。
3. **45802 / 45803 / 45804 / 45815 / 80900 等字段实际承担什么角色**：
   - `45802`=缩略图 CDN URL、`45803`=预览图 CDN URL、`45804`=原图 CDN URL（三者是同一
     资源的三种尺寸访问地址，不是三种不同贴图）；
   - `45815`=repeated bytes 文本降级标记（例如 `[动画表情]`），不是 identity；
   - `80900`=商城表情显示文本（✅），但在 proto 中被命名为 `sys_content`、在系统消息
     （`45002=8`/`40011=17`）场景又被复用为系统内容，**属多态字段，需按 `45002` 上下文区分**。

**风险（关键）：** MarketFace 的 `sticker_id`/`emojiId` 内层字段在现有研究中**尚未解码**。
若只做“计数归一”，用 `45600` 的 md5 派生值可工作（内容派生、稳定）；但要拿到与 QCE
`emojiId` 语义对齐的“数字表情 ID”，需要先对 `45600` 内层再做一次小范围 wire 采样解码。

---

## C. 可用 display text

| 表情类型 | display text 来源 | 置信度 |
| --- | --- | --- |
| QQFace（`45002=6`） | `47602`（如 `/汪汪`） | ✅ |
| QQFace 降级 | `45815`（如 `[动画表情]`） | ✅ |
| MarketFace（`45002=11`） | `80900`（商城表情显示文本） | ✅ |
| MarketFace 降级 | `45815` | ✅ |

结论：两类表情都有可用 display text，且降级文本 `45815` 兜底。下游 `ExpressionAnalyzer`
已支持 `display_text=None → "[表情]"` 兜底（`expression_analyzer.py:170`），因此即便
display text 缺失也不会破坏统计，只会让展示不够友好。

---

## D. 图片 / 资源来源

- **是否存在本地文件**：存在。`45812`（本地缓存路径）、`45814`（NTOS 路径）指向本地缓存。
  但这是“运行时缓存”，并非每条消息都有、也可能已被清理，**不能作为稳定资源契约**。
- **是否只有 CDN URL**：不是。`45802/45803/45804` 是 CDN URL，`45812/45814` 是本地路径，
  二者并存；CDN URL 受 `45505`（过期时间）、`45515-45519`（TTL）约束会过期。
- **是否根本不需要图片资源即可完成统计**：**是。** 表情统计（出现次数、Top 表情、成员
  表情习惯、组合、邻近词）只依赖 `expression_key` + `display_text`，**完全不需要**图片
  二进制或可访问的 URL。图片仅在“渲染表情图”的 UI 层才需要。
- 小黄脸（QQFace）更是客户端内置资源，靠 `47601` 编号即可映射，无独立资源文件。

**结论：** 统计不需要图片资源；图片路径/URL 是未来 UI 渲染的可选项，且都已在 `40800`
内部保留（`45802/45803/45804/45812/45814`），不构成阻塞。

---

## E. 当前 Provider 是否已保留全部必要数据

**是。** 当前 `qq_database_provider.py` 的 `_raw_record` / `_session_record` 把整段
`40800` BLOB 以 base64 原样写入 payload 的 `message_blob`（`qq_database_provider.py:266-306`），
没有丢弃任何内部字段。因此 `47601/47602/45600/80900/45802-45804/45815` 全部随 `40800`
被保留在 payload 里。

**不需要新增 DB 列读取。** 表情 identity / display text / 资源引用都在 `40800` 内部，
不在主表其它列。Provider 当前 SELECT 的 `40001/40027/40030/40033/40050/40800` 对表情统计
已经足够（`40011`/`40012`/`40020` 等是给 sender 显示名、外层类型判定用的，与本统计无关，
且 `45002` 已能表达“这是表情段”）。

**唯一注意点：** payload 层仍是“opaque blob”，`45002/47601/47602/45600/80900` 目前只在
Adapter 的 protobuf 解析阶段才能读到。这符合架构边界（Provider 不解释语义），不构成缺失。

---

## F. 后续是否只需要扩 Adapter / ExpressionContent

**基本是，改动面集中在 Adapter。**

1. `rich_message.ExpressionContent` 已经存在，且 `EXPRESSION_KIND_PLATFORM_FACE` 与
   `EXPRESSION_KIND_STICKER` 常量已定义（`rich_message.py:8-10`）。
2. 下游 `ExpressionAnalyzer.analyze()` 已消费 `ExpressionContent` 做频次 / Top / 成员 /
   组合 / 邻近词统计（`expression_analyzer.py:120-352`），**不需要改 Analysis Core**。
3. QCE 生产路径 `_face_expression` / `_market_face_expression` 已经是现成的映射范式
   （`qq_chat_exporter_adapter.py:524-565`），可直接对照。

**需要改的只有 `qq_db_adapter.py`：**
- `_text_from_segment` 目前只接受 `45002==1`（文本）并返回 `TextContent`，对
  `45002==6` / `45002==11` 直接跳过（返回 None，整条表情消息被丢弃）。
- 扩展方向：在段级解析里新增 `45002==6 → ExpressionContent(platform_face, key=47601,
  display_text=47602)` 与 `45002==11 → ExpressionContent(sticker, key=<45600 派生>,
  display_text=80900 or 45815)`，并把表情段并入该 `RichMessage.contents`（与文本段并列，
  保持段顺序）。

**结论：** 不动 Provider、不动 Analysis Core、不动 `RichMessage` 模型；只需扩 Adapter
的 protobuf 段解析，产出 `ExpressionContent`。唯一的前置阻塞是 MarketFace 的
`45600` 内层 id 尚未解码（B 节风险），若接受“md5 派生 key”则无阻塞。

---

## G. 仍需人工或强模型判断的问题

1. **QQFace `47601` 的稳定性与编号空间**：社区为 🔍，未证明 face index 是否跨 QQ 版本 /
   账号迁移稳定。单库快照内统计没问题，跨版本对齐需要人工抽样确认或选择“index + display
   text 联合”作为兜底归一策略。
2. **MarketFace `45600` 内层 `sticker_id` 的解码**：这是本调查唯一真正的“数据缺口”。
   需要一次小范围 wire 采样，确认 `45600` 内层的字段布局（sticker_id、md5 的字段号），
   才能得到与 QCE `emojiId` 对齐的稳定数字 ID。在此之前只能用 md5 派生 key。
3. **`80900` 的多态性**：它既是商城表情显示文本，又是系统消息内容（proto 名 `sys_content`）。
   Adapter 必须按 `45002` 上下文区分，不能无脑把 `80900` 当表情文本；需人工确认边界规则。
4. **“纯表情消息”与“图文混排表情段”的归一**：`ExpressionContent.position / text_before /
   text_after` 目前由 QCE 路径在 `_ordered_content_parts` 填充（`qq_chat_exporter_adapter.py:461-476`）；
   Direct DB 是否需要同样填充，取决于表情统计的“纯表情消息率 / 邻近词”指标是否要求
   精确位置。需人工决定 Direct DB v0 表情是否复刻这套顺序重建。
5. **降级文本 vs 权威文本的取舍**：`47602`、`80900`、`45815` 三者可能同时存在且文案不同，
   谁是“展示优先”需人工拍板（建议 `47602`/`80900` 优先、`45815` 兜底）。
6. **跨版本稳定性总前提**：以上全部基于单一 DB 快照的社区实证，非腾讯官方稳定协议；
   进入实现前应把“只在单快照内保证稳定”写进 acceptance criteria，避免把它当成跨版本契约。

---

## 一句话结论

**数据已齐备**：`40800` 原始 blob 已被 Provider 完整保留，QQFace 用 `47601`(id)+`47602`(text)
即可稳定归一；MarketFace 用 `45600` 的 md5 派生值可稳定归一、`80900` 提供显示文本；
统计完全不需要图片资源。**改动面只在 `qq_db_adapter.py`**（产出 `ExpressionContent`），
唯一需补的研究是 `45600` 内层 `sticker_id` 的解码，用于拿到与 QCE `emojiId` 对齐的数字 ID。
