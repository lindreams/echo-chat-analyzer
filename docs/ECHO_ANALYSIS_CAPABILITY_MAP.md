# Echo 数据与分析能力映射

> **基线导航（2026-10-07）**：本文保留 Phase 9.2 的历史能力审计与设计判断。
> 下文 QCE 原始来源基线已退休，不代表现役输入能力；当前 Direct DB / WeChat 能力以
> [ARCHITECTURE](../ARCHITECTURE.md) 为准，发布状态见 [HARDENING](HARDENING.md)。
> 下文 Dashboard 为历史设计用语；旧 Qt 页面及专属数据构建链已退休，现役展示使用 Echo Report。

## 1. 文档目的

本文定义 Phase 9.2 对“Echo 未来应该理解什么数据”的判断。它把已经确认的
Raw Source 能力映射为 Echo 语义能力与分析价值，但不规定 Provider、Adapter、
统一模型或分析器的实现方式。

当前架构事实仍以 `ARCHITECTURE.md` 为准：

```text
Raw Source → Provider → Adapter / Parser → ChatMessage → Analysis
```

Raw Source Capability Audit 已确认，QQChatExporter 与微信本地数据库都包含
比当前链路实际使用内容更丰富的信息：

- QQ 导出保留消息 ID、复合消息元素、资源、mention、reply、recalled、system
  以及发送者元数据；NapCat/OneBot 运行态另有成员角色和通知事件。
- 微信 `message_N.db` 的 `Msg_<md5>` 表包含文本、图片、语音、视频、表情、
  AppMsg、系统消息和撤回等多种 `local_type`；引用 AppMsg 包含
  `refermsg/svrid`；联系人、群成员和资源分别存在于联系人库及资源目录。
- 当前 QQ Adapter 主要只保留 `text/reply` 的文本；当前微信数据库 Provider
  在查询阶段只读取 `local_type = 1`。因此“当前没有进入 Analysis”不能被解释为
  “源头不存在”。

本文采用三条价值判断：

1. 数据必须能支撑明确的当前产品价值，或具有明显、可说明的未来分析空间。
2. “进入 Echo 模型”不等于“立即产生统计”；关系恢复、资源定位和未来 AI 理解
   也属于保留价值。
3. Echo 只保留理解聊天所需的语义，不以复制所有平台原始字段为目标。

## 2. 能力分级

### P0：统一理解的最低闭环

P0 是回答以下问题不可缺少的信息：谁在何时发送了什么、它属于什么类型、
是否指向某人或某条消息、后来是否被撤回。

- text
- sender
- timestamp
- message_id
- message type
- reply
- mention
- recall

P0 不代表所有字段今天都已被 Analysis 使用，而是代表未来统一模型不能继续
主动丢弃这些语义。

### P1：有明确扩展空间

P1 当前可以产生可靠的基础统计或上下文占位，未来还可支持内容理解、AI 记忆、
群体结构和互动分析：

- emoji / sticker
- image metadata
- file metadata
- voice metadata
- video metadata
- forward
- group member information
- role
- system events
- join / leave / poke

### P2：暂不进入核心

P2 不是“源头无能力”，而是现阶段价值、稳定性、隐私成本或跨来源一致性不足：

- 在线状态、QQ 等级、年龄等瞬时或弱相关资料：无法稳定重建历史，对聊天理解
  的增益有限。
- 完整地理坐标、红包与转账财务细节：隐私敏感，且不是当前 Echo 核心目标。
- 平台专用展示装饰、头像挂件、群荣誉等：跨来源语义弱，容易让统一模型变成
  平台字段集合。
- 未验证的微信好友关系、群管理员历史、撤回原消息 ID 标签：在证据不足前不能
  进入稳定概念；应先完成针对性验证。
- 原始二进制正文和完整平台 payload：可由来源层按需要保留或重新读取，但不属于
  Echo 核心语义。

## 3. 总体能力映射

“当前使用”指现有 Analysis 链路，而不是 Raw Source 是否存在。

| 数据 | 来源证据 | 为什么有价值 | 当前价值与使用情况 | 未来发展空间 | 是否进入 Echo 模型 | 级别 |
| --- | --- | --- | --- | --- | --- | --- |
| Text | QQ `content.text`；微信 type 1 `message_content` | 是聊天语义的直接载体 | 已用于清理、分词、词频、长度、画像和会话分析 | 主题、摘要、语义检索、AI 记忆 | 是 | P0 |
| Sender | QQ sender uid/uin/name；微信 `real_sender_id → Name2Id` | 没有稳定发送者就无法形成个人行为与关系 | 当前使用展示名进行说话者统计；部分稳定 ID 已保存但未用于分析 | 跨改名身份连续性、参与角色、关系网络 | 是，以稳定身份为主 | P0 |
| Timestamp | QQ timestamp；微信 `create_time` | 负责重建顺序、节奏和共同活动 | 已用于活跃度、峰值与会话切分 | 回复延迟、互动节奏、群体生命周期 | 是 | P0 |
| Message ID | QQ id/msgId；微信 `server_id/local_id` | 是 reply、recall、forward 和资源关联的基础 | 当前部分进入 ChatMessage，但 Analysis 不使用 | 消息图、因果链、去重和增量导入 | 是；保留来源内稳定标识语义 | P0 |
| Message type | QQ type/elements；微信 `local_type` base/subtype | 避免把非文本交流误判为无交流 | 当前主要只分析 text/reply；微信非文本在 Provider 前置丢弃 | 多模态构成、内容偏好、互动方式分析 | 是 | P0 |
| Reply | QQ reply element 的目标 ID/摘要；微信 AppMsg type 57 的 `refermsg/svrid` | 明确“这句话是在回应哪句话”，是对话理解的关键边 | 当前只保留部分回复文本，不保留稳定关系 | 回复网络、响应时间、问题—回答、线程恢复 | 是，作为关系 | P0 |
| Mention | QQ mentions/at element；微信正文或系统结构中的定向提及需按来源验证 | 明确“对谁说”，区别广播与定向互动 | 当前未结构化使用 | 互动网络、被关注度、任务指派、@全体影响 | 是，作为关系；仅纳入已验证来源 | P0 |
| Recall | QQ recalled 与运行态 recall notice；微信 type 10002/revokemsg | 撤回改变消息状态，本身也是强互动信号 | QQ 仅保留 boolean 且 Analysis 不使用；微信当前不读取 | 撤回率、撤回上下文、内容可见性与关系分析 | 是，区分状态与事件 | P0 |
| Image | QQ image element/resources；微信 type 3 与图片资源 | 即使不看图，也应知道一次图片交流发生了 | 当前不进入分析；可先统计数量和时间线占位 | OCR、视觉理解、相册式记忆、图文关联 | 是，先保留元数据与资源引用 | P1 |
| Emoji / Sticker | QQ face/market_face；微信 type 47 XML 的 MD5/CDN | 表情是情绪与回应的一部分，不能等同空消息 | 当前不使用 | 表情习惯、情绪回应、表情语义聚类 | 是，保留种类/标识/资源引用 | P1 |
| File | QQ file/resources；微信 AppMsg type 6 与文件资源 | 文件名、大小和发送关系常表示协作与交付 | 当前不使用 | 文件分享统计、任务上下文、文档内容理解 | 是，保留元数据，不默认读取文件正文 | P1 |
| Voice | QQ audio/PTT；微信 type 34、时长和语音资源 | 语音可能承载完整对话，忽略会扭曲活跃度 | 当前不使用 | 时长统计、转写、语义理解、语音记忆 | 是，保留时长/资源/可选转写状态 | P1 |
| Video | QQ video element/resources；微信 type 43 与视频资源 | 表示实际发生的内容分享 | 当前不使用 | 时长统计、关键帧/OCR、视觉理解 | 是，保留元数据与资源引用 | P1 |
| Forward | QQ forward element/records；微信 AppMsg 转发结构 | 转发表示信息传播，不只是新写文本 | 当前不使用 | 传播路径、来源摘要、内容复用分析 | 是，但第一阶段只需关系和摘要，不要求完整嵌套树 | P1 |
| System message | QQ system/includeSystemMessages；微信 type 10000 XML | 包含拍一拍、群变化和其他真实互动 | QQ 只有部分标志进入模型；微信被 Provider 排除 | 系统交互统计、可读事件恢复、群体变化时间线 | 是；可解释部分进入 Event，不明部分保留可读摘要 | P1 |
| Join | OneBot `group_increase`；微信系统消息或群数据 | 改变群体边界，影响参与度和成员基数解释 | 当前不使用；历史可恢复性因来源而异 | 新成员融入、欢迎响应、群增长分析 | 是，在来源有可靠事件时 | P1 |
| Leave / Kick | OneBot `group_decrease`；微信系统消息 | 解释群体收缩和成员行为终止 | 当前不使用 | 留存、退出前互动、群生命周期分析 | 是，在来源有可靠事件时 | P1 |
| Poke / 拍一拍 | OneBot poke notice；微信 type 10000 XML title/template | 属于轻量但明确的人际互动 | 当前不使用 | 非文本互动频率、关系亲密度辅助信号 | 是，作为 system interaction | P1 |
| Nickname | QQ sender name；微信 `contact.nick_name` | 提供人类可读名称 | 当前 sender 常是折叠后的展示名 | 名称历史、可读报告、身份解析 | 是，作为身份展示属性，不作为唯一身份键 | P0/P1 |
| Group nickname | QQ group card；微信群内专属昵称字段尚待验证 | 同一成员在不同群可能有不同呈现身份 | QQ 原始层有证据但当前折叠丢失；微信需进一步验证 | 群内身份、改名历史、成员识别 | 概念进入；仅采纳来源已验证值 | P1 |
| Role | QCE 运行态 owner/admin/member；微信群主已验证、管理员未验证 | 角色影响发言权、管理事件和群体结构 | 当前不使用 | 管理者参与度、角色变化、结构性互动 | 是，作为会话范围身份上下文 | P1 |
| Group members | QCE runtime member list；微信 `chatroom_member` | 给消息参与者提供群体上下文和基数 | 当前未进入 Analysis | 活跃/沉默成员、加入后参与、群体结构 | 是，但与消息流分开表达 | P1 |

## 4. 从数据到 Echo 能力

### 4.1 消息内容能力

Echo 的内容理解应分两步演进：

1. **先承认内容存在。** 图片、语音或视频即使暂时不能解析，也必须能在时间线、
   消息类型和发送统计中出现。
2. **再增加内容解释。** OCR、语音转写、视觉理解、文件文本抽取属于未来派生能力，
   不应成为保留基础元数据的前置条件。

这避免了当前“只有可分词文本才算消息”的偏差，也避免为了未来 AI 功能立即保存
所有原始二进制数据。

### 4.2 消息关系能力

Reply、Mention、Forward 共同回答“对谁说、承接什么、信息从哪里来”。关系不是
文本标签：删除引用摘要中的文字后，reply 目标仍然成立；同一条消息可以同时包含
文本、图片、mention 和 reply。Echo 因此应把关系作为独立语义，而不是塞进文本或
用 message type 代替。

关系数据可以支撑：

- 消息级对话图与线程；
- 用户间定向互动网络；
- 回复率、响应时间和未获回应问题；
- 转发传播和信息来源；
- 后续 AI 在检索时带回被回复消息，而不是只读当前一句。

### 4.3 行为与群体事件能力

Recall、Join、Leave、Poke 和系统交互描述的是“发生了什么”，不一定是某人发送的
普通内容。将它们强行伪装成文本消息会丢失操作者、目标和状态变化；完全过滤又会
破坏群体时间线。

Echo 当前可以只使用它们构成事件计数和时间线，未来再支持成员生命周期、欢迎互动、
群体留存和管理行为分析。运行态事件与历史导出必须标记来源证据：OneBot 能实时收到
事件，不代表 QCE 历史 JSON 必然保存同一事件。

### 4.4 身份能力

身份必须把“稳定识别”与“人类可读显示”分开：

- platform/source ID 用于把改名前后的同一个人连起来；
- nickname、remark、group nickname 和 alias 用于展示和名称历史；
- role 属于某个会话或某段时间的上下文，不能当作用户永久属性；
- 群成员集合是会话上下文，不应复制到每一条消息。

当前以 `sender` 字符串进行分析会在改名、同名和不同群名片场景下产生身份分裂或合并。
P0 因此要求稳定 sender 身份；P1 再补充会话范围名称和角色。

## 5. 当前能力与未来能力的边界

进入 Echo 模型后，不要求每项立刻进入词频或 Dashboard：

| 阶段 | 允许的最小价值 | 不要求立即实现 |
| --- | --- | --- |
| P0 接入 | 不丢失身份、时间、类型、消息 ID、reply/mention/recall 语义 | 完整关系图 UI、复杂网络算法 |
| P1 内容接入 | 类型计数、时间线占位、元数据和资源引用 | OCR、转写、视觉模型、文件全文解析 |
| P1 事件接入 | 事件时间线、操作者与目标存在性 | 群体留存模型、管理者评分 |
| P1 身份接入 | 稳定身份与上下文名称/角色分离 | 跨平台自动合并同一真人 |

## 6. 不变量与验收判断

未来能力设计必须继续遵守现有架构：

- Provider 只获取原始数据，不判断分析价值。
- Adapter/Parser 负责来源语义到 Echo 统一语义的转换，不做统计。
- Analysis 不出现 QQ、微信、`wxid`、`chatroom` 等平台分支。
- 原始内容、资源和身份信息只在本机处理；报告与日志不默认泄露正文或内部 ID。
- 未验证的来源字段标记为未知，不用经验补全。
- 新数据是否值得进入统一模型，以能否回答 Echo 的“谁、何时、说了什么、对谁、
  如何互动、形成什么关系、群体如何变化”为判断标准。

本能力图不授权任何实现修改。具体模型迁移与兼容策略应在独立实施计划中决定。
