# Echo 架构决策：Rich Semantic Model 与渐进迁移

> 展示说明更新：下文 Dashboard 为早期设计用语；旧 Qt 页面及专属数据构建链已退休，现役展示使用 Echo Report，见 [ARCHITECTURE](../ARCHITECTURE.md)。

## 决策状态

- 阶段：Phase 9.3
- 状态：已冻结，供后续实施阶段遵循
- 范围：Echo 统一语义模型、旧 `ChatMessage` 兼容路径及 P0/P1 边界
- 本文不授权实现，不修改当前运行链路

## 背景与依据

当前已完成 Raw Source Capability Audit、`ECHO_ANALYSIS_CAPABILITY_MAP.md` 和
`ECHO_DATA_MODEL_DESIGN.md`。调查确认 QQ 与微信 Raw Source 能表达复合内容、消息关系、
行为事件、稳定身份和资源信息，而当前链路在进入 Analysis 前主动丢弃其中大部分语义。

当前实际架构仍然是：

```text
Raw Source
    ↓
Provider
    ↓
Adapter / Parser
    ↓
ChatMessage
    ↓
Analysis
```

`ARCHITECTURE.md` 是当前已实现架构的唯一事实来源。它将 `ChatMessage` 定义为冻结的唯一
跨层领域模型。本文记录的是下一阶段的目标架构决策；在实现和迁移完成前，不能用本文
宣称当前代码已经采用 Rich Semantic Model。未来启动实施时，必须同步更新架构事实文档，
不能让目标决策与实际结构长期不一致。

---

# 1. Rich Model 是否成为未来唯一事实模型

## 1.1 备选方向

本阶段考虑过三个方向：

1. 继续扩展现有 `ChatMessage`。迁移表面简单，但会让文本中心对象不断累积可选内容、
   Relation、Event 和 Identity 字段，无法形成清晰概念边界。
2. 直接用 Rich Model 一次性替换 `ChatMessage`。目标清晰，但会迫使现有 Analysis 与全部
   来源链路同时迁移，风险与回归范围过大。
3. Rich Model 成为长期事实模型，`ChatMessage` 保留为单向生成的 Legacy Projection。
   该方向兼顾长期语义完整性与现有分析稳定性。

## 1.2 最终决策

采用第三个方向：**Rich Semantic Model 是 Echo 长期唯一事实模型。**

目标数据流冻结为：

```text
Raw Source
    ↓
Provider
    ↓
Adapter / Parser
    ↓
Rich Semantic Model
    ├────────────→ Rich-aware Analysis
    ↓
Legacy Projection
    ↓
Legacy Analysis
```

“唯一事实模型”具有以下含义：

- 来源中已被 Echo 接纳的语义，只在 Rich Semantic Model 中进行规范化表达。
- 新分析能力以 Rich Semantic Model 为语义来源，不以扩展旧 `ChatMessage` 为前提。
- `ChatMessage` 不再承担保存完整聊天事实的职责，只承载旧 Analysis 所需的兼容视图。
- Legacy Projection 可以有信息损失，因为旧文本分析本来无法理解全部 Rich 语义；
  这种损失必须局限在兼容投影，不能反向改变 Rich Semantic Model。
- Rich Semantic Model 不等于完整 Raw payload。只有具有明确当前价值或明显未来分析空间
  的跨来源语义进入模型。

## 1.3 转换逻辑唯一性

**禁止 Provider 同时维护 `ChatMessage` 与 Rich Semantic Model 两套转换逻辑。**

Provider 仍只负责获取外部数据或原始记录，不负责统一领域转换。Adapter / Parser 是来源
格式进入 Rich Semantic Model 的唯一转换边界。旧 `ChatMessage` 只能由 Rich Semantic
Model 经过 Legacy Projection 产生。

该约束避免：

- 两条转换路径对同一 Raw 字段产生不同解释；
- 修复一个 Adapter 时遗漏另一条路径；
- 旧模型与新模型成为并列事实来源；
- Provider 开始承担格式转换和分析价值判断。

---

# 2. ChatMessage 生命周期决策

## 2.1 当前价值

当前 `ChatMessage` 的优点明确：

- 已稳定运行于现有 QQ、微信和本地导出链路；
- 现有词频、说话者、活跃度、长度、画像和会话分析依赖它；
- 已有广泛测试覆盖和兼容行为；
- 来源中立，现有 Analysis 无需理解 QQ 或微信字段。

## 2.2 当前限制

其限制同样明确：

- 以单个 `text` 为中心，难以表达一条消息中的多段复合内容；
- `message_type` 不能同时表达文本、图片、reply 与 mention 等并存语义；
- 难以表达 Reply、Mention、Forward 等独立 Relation；
- 难以表达 Recall、Join、Leave、Poke 等 Event；
- 单个 sender 展示字符串不能完整表达稳定身份、别名、群昵称和角色；
- 继续增加可选字段会使它成为扁平的平台能力集合。

## 2.3 最终决策

`ChatMessage` **不立即删除，也不继续作为新能力的扩展中心**。它进入兼容生命周期：

```text
Rich Semantic Model
    ↓
ChatMessage Projection
    ↓
Legacy Analysis
```

冻结规则：

- 旧分析能力可以继续存在并保持可运行。
- Legacy Analysis 可以继续依赖 `ChatMessage`。
- 新能力不得以“给 `ChatMessage` 继续加 Rich 字段”作为默认方案。
- `ChatMessage` 不得反向补全或重建 Rich Semantic Model。
- 不设定立即删除日期；其最终退役必须等待旧分析均有明确替代或稳定迁移路径。
- 兼容期不允许 Rich Model 与 `ChatMessage` 成为两套并列业务事实模型。

---

# 3. 数据流方向约束

## 3.1 必须遵守的方向

所有来源的长期目标链路必须是：

```text
Raw Source
    ↓
Provider
    ↓
Adapter / Parser
    ↓
Rich Semantic Model
```

仅在旧分析需要时增加：

```text
Rich Semantic Model
    ↓
Legacy Projection
    ↓
ChatMessage
    ↓
Legacy Analysis
```

Rich-aware Analysis 可以直接消费 Rich Semantic Model，但仍必须遵守 Analysis Core 的
来源中立原则。

## 3.2 层级职责保持不变

- Raw Source：保存平台或数据库实际提供的事实。
- Provider：获取原始数据，不做格式转换、分析或价值过滤。
- Adapter / Parser：把来源字段转换为来源无关的 Rich 语义。
- Rich Semantic Model：作为 Echo 接纳语义的唯一事实来源。
- Legacy Projection：只负责生成旧 Analysis 可消费的兼容视图。
- Analysis：只理解来源无关语义，不读取 Raw Source 或平台字段。

## 3.3 明确禁止

禁止以下数据流：

```text
Provider ──→ ChatMessage
        └──→ Rich Semantic Model
```

也禁止：

- Provider 或 Adapter 分别维护一套 Rich 转换和一套 Legacy 转换；
- Legacy Projection 读取 QQ/微信原始字段补充 Rich Model 已丢失的信息；
- Analysis 直接读取 `replyElement`、`refermsg`、`local_type`、`wxid`、QQ message segment
  或其他平台专用字段；
- 在 Analysis 中用平台分支解释来源类型；
- GUI、Presentation 或 Exporter 成为 Rich 到 Legacy 的业务转换位置；
- 为保持旧报告而在 Provider 阶段继续主动过滤 Rich 语义。

---

# 4. P0 实施边界

P0 是 Rich Semantic Model 的首个最小闭环。其目标是停止丢失聊天理解的基础事实，而不是
同时实现全部新统计。

## 4.1 Message Core

P0 必须能够表达：

- message identity：来源内可被 Reply 或 Recall 引用的消息身份；
- source：数据来源与必要的可追溯上下文；
- conversation：消息所属会话；
- sender：指向稳定 Identity，而非只保存昵称；
- timestamp：发生时间与必要的顺序语义；
- message type：来源无关的规范化消息类别。

P0 不在本文决定 ID 的字段类型或数据库存储方式。QQ id/msgId 与微信 server/local ID 的
唯一范围仍需在实施前以虚构样本和已有事实验证。

## 4.2 Relations

P0 必须支持：

- Reply：当前消息到目标消息的关系；目标未导入时关系仍可保留为未解析引用。
- Mention：当前消息到稳定 Identity 或会话范围目标的关系；只有昵称而无可靠 ID 时不得
  强行合并身份。

Reply 与 Mention 必须独立于 Content 和 message type，因为一条复合消息可以同时包含
文本、图片、回复和多个 mention。

## 4.3 Events

P0 只处理 **已有证据支持的 Recall state/event**：

- 已知某条消息被撤回时，可以表达消息的 recall state。
- 来源明确提供撤回时间、操作者或目标消息时，可以表达 Recall Event。
- 来源只提供部分事实时，只保存已证实部分，不推断缺失字段。
- 微信 type 10002/revokemsg 已确认，但撤回原消息 ID 标签尚未确认；在验证前不能假设
  能完整连接原消息。

## 4.4 P0 明确不包含

- OCR；
- 图片视觉理解；
- 语音转写；
- 视频分析；
- AI 摘要、情绪判断、关系推断或自动记忆；
- P1 资源内容处理；
- 跨平台身份合并；
- 全量 Event 体系实现。

这些能力不得被作为 P0 数据接入的隐性前置条件。

---

# 5. P1 扩展边界

P1 记录具有明确未来分析价值、但不要求在首个 Rich Model 阶段全部实现的能力：

- emoji / sticker；
- image metadata；
- file metadata；
- voice metadata；
- video metadata；
- forward；
- group membership；
- role；
- system events。

这些数据进入模型的理由不是“Raw Source 有什么就全部保存”，也不是要求它们立即生成
Dashboard 统计，而是它们能支持明确的渐进能力：

- 非文本消息数量、时序和互动方式；
- OCR、视觉理解和图像记忆；
- 文件分享和协作上下文；
- 语音时长、未来本地转写和语义检索；
- 视频元数据、关键帧和多模态理解；
- 信息传播与转发关系；
- 群成员基数、成员生命周期和群体结构；
- owner/admin/member 等会话范围角色分析；
- join、leave、poke、拍一拍及其他系统互动时间线。

P1 接入仍需逐项满足两个条件：来源事实已经验证；跨来源语义边界已经明确。未验证字段
不得为了填满模型而补全。

---

# 6. Event 设计原则

## 6.1 Event 不是普通 Message

Event 描述状态变化或行为事实，Message 描述通信记录及其内容。两者可以发生在同一会话
时间线上，但语义职责不同。

Event 包括但不限于：

- recall；
- join；
- leave / kick；
- poke / 拍一拍；
- system interaction。

## 6.2 来源存储形式不决定 Echo 语义

平台可能把 join、leave、recall 或拍一拍保存成系统消息行，也可能通过 OneBot notice 等
运行态事件提供。Echo 不能因为来源把它存成“消息”就把状态变化当作普通用户文本。

语义层必须区分：

- **消息内容**：参与者发送或分享了什么；
- **状态变化**：谁在何时对消息、成员或会话做了什么。

来源记录若同时含可读系统摘要与结构化事件，可以支持二者，但后续实现必须有明确去重
规则，防止同一事实同时计入 Message 和 Event 统计。

## 6.3 证据与完整性

- 运行态可见不等于历史导出可恢复。
- 事件只有部分字段时允许表达部分事实。
- 不用可读系统文案猜测未提供的操作者、目标或事件类型。
- Event 的未知值保持未知，不使用平台默认值伪装确定事实。

---

# 7. Identity 设计原则

Identity 必须区分以下概念：

- stable id：来源内稳定识别参与者的身份；
- display name：当前面向用户展示的名称；
- alias：昵称、备注、微信号等来源已验证的其他名称；
- group nickname：某个 Identity 在特定 Conversation 中的群名片或群昵称；
- role：某个 Identity 在特定 Conversation、必要时特定时间范围内的 owner/admin/member
  等角色。

冻结规则：

- **禁止使用 nickname 或 display name 作为唯一身份。** 名称可能重复或变化。
- **禁止自动跨平台真人合并。** QQ 与微信中显示名相同的用户不能据此认定为同一人。
- group nickname 和 role 是会话上下文，不是全局用户属性。
- 只有来源已验证的身份、群昵称和角色才进入模型；缺失信息保持未知。
- Analysis 以 stable identity 聚合，以 display name 展示；旧数据没有稳定 ID 时可以降级，
  但必须承认其身份可靠性较低。

Group Membership 是 Identity 与 Conversation 的关系，不复制到每条 Message。成员快照与
Join/Leave Event 分别表达当前集合和历史变化，不能互相冒充完整历史。

---

# 8. 资源原则

图片、视频、语音和文件在第一阶段只要求保存其**内容语义和资源引用**：

- 该消息包含何种内容；
- 来源提供的必要元数据；
- 可用时指向本地或远端资源的引用；
- 资源当前是否可定位或可访问。

冻结规则：

- 不默认把大量二进制复制进 Rich Semantic Model。
- 不以资源下载、解密、OCR、转写或视觉分析成功作为消息成立条件。
- 资源文件缺失、CDN 失效或关联失败，不能导致 Message 被删除或改变消息类型。
- 资源引用是“可定位但不保证可用”的关系。
- 派生结果不得覆盖原始事实；未来 OCR、转写和视觉描述必须能区分其来源和状态。
- 文件正文、语音内容和图像内容的进一步读取必须继续遵守本地处理与用户授权边界。

---

# 9. 后续实现约束

未来任何 Rich Semantic Model 实施必须遵守以下约束：

1. **小阶段实现。** 先完成最小 P0 概念和单一来源的可验证闭环，再逐项扩展；不得把
   P0、P1、全部来源和全部 Analyzer 合并成一次改造。
2. **保持旧 Analysis 可运行。** 每个迁移阶段都要维持现有文本分析、报告和用户流程，
   直到有明确批准的替代路径。
3. **先测试再迁移。** 所有测试使用虚构数据；先验证 Rich 语义、Projection 和兼容行为，
   再切换生产链路。
4. **不一次性重写全部链路。** 不同时重写 Provider、Adapter、Application、Analysis 和
   Presentation；每阶段只改变必要边界。
5. **保持来源与分析隔离。** 新模型不能成为平台字段进入 Analysis 的通道。
6. **保持单向转换。** Raw → Rich → Legacy Projection；不做 Legacy → Rich 回填。
7. **不复制业务逻辑。** Provider、Adapter、Projection 和 Analysis 各自只承担一层职责。
8. **保留证据范围。** 对运行态事件、历史导出、资源可用性和未解析关系明确区分完整性，
   不把缺失信息默认为否或空事实。
9. **先更新架构事实。** 任何实际切换 Rich Model 为跨层事实来源的变更，必须同步修订
   `ARCHITECTURE.md` 的数据流、层职责、扩展指南和架构不变量。

本文冻结的是方向和边界，不是实现顺序、类结构、数据库结构或字段类型。

---

# 尚未解决的问题

以下问题保留到独立实施设计或验证任务，不影响本次方向冻结：

1. Rich Semantic Model 的具体概念载体、模块位置和版本策略。
2. `ChatMessage` Legacy Projection 的准确文本投影规则，尤其是纯图片、语音、系统事件
   和混合消息如何进入旧分析而不误导统计。
3. QQ message ID 与微信 server/local ID 的稳定范围、冲突边界和未解析引用表示。
4. 历史 Event 与 OneBot 等运行态 Event 的导入、去重和证据标记方式。
5. 同一来源记录同时生成系统摘要与 Event 时的统计去重规则。
6. Identity 名称历史与当前 DTO 名称注入机制的衔接方式。
7. Group Membership 快照与 Join/Leave Event 的时间一致性。
8. 资源引用的可用性状态、生命周期、权限和启发式匹配可信度。
9. OCR、转写、视觉描述等派生内容的来源、版本和失败状态如何表达。
10. 旧 `ChatMessage` 的最终退役条件；当前不设日期，也不承诺永久保留。

这些未决问题不得被实现者自行用平台经验补全。需要进一步证据或架构选择时，应建立
独立调查、设计和测试阶段。

---

# 10. GUI 连接体验补充决策

QQ 与微信连接体验采用来源隔离的展示状态，但不引入新的连接领域模型或状态机：

- GUI 继续只消费 Facade 提供的连接状态；
- 只有来源达到 READY，GUI 才展示真实会话列表；其余阶段展示未连接、连接中或读取中占位；
- 切换来源与“返回数据源选择”会清理上一来源的纯展示状态，并忽略迟到的异步结果；
- 返回入口不表达登出、断开或刷新，也不负责关闭外部客户端；
- QQ 权限说明和微信登录图片均属于本地 GUI 引导，不改变 Provider、Key 获取或数据读取流程。

该决策只约束交互适配层，不改变本文冻结的 Rich Model、`ChatMessage` 生命周期或
Raw → Rich → Legacy Projection 方向。
