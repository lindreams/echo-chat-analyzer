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
