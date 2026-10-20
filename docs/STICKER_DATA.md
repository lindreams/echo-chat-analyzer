# StickerData：发送事实、素材身份与媒体消费契约

## 当前能力与验收证据

表情数据复用现役 QQ Direct DB / 微信分析链，不新增聊天数据来源。
QQ 私聊／群聊点击生成报告后，先完整统计并选择成员榜、共同榜、招牌等报告所需素材，
按可靠身份去重。优先关联本流程已有的可信目录；缺图的 QQ PIC 自动复用已登录客户端的
原生通路，无网络确认框。验证后一次导出最终 HTML/JSON 并打开，失败保留统计及占位。
独立素材窗口、手动获取、网络确认和另存新报告流程已退休。
QQ 正式报告仅获取当前会话的所选目标，保留内核消息及 PIC 元素复核，不扫描未授权目录。
微信 Type 47 继续复用统一分析和报告链；明文原件只从显式授权目录关联。

成员榜默认展示 Top 3；私聊及群聊 1～9 名实际发送成员最多展开 Top 10，
群聊 10～99 名最多 Top 5，100 名及以上仅 Top 3，不显示展开按钮。
人数只统计本次分析范围内 `send_count > 0` 的成员，不使用群名义人数或未发送成员数。
全群榜、共同榜仍最多 Top 10。展示模型只保留各成员对应上限的排行项，
媒体目标与离线 HTML 复用同一模型及去重机制；完整统计、完整排名与招牌规则不变。
全部成员仍可选择，已有榜外招牌继续进入去重目标。
已有容量测量中，分散的 500 人虚构样本由 5010 个目标降至 1510 个。
该测量使用旧版 32 次获取、60 秒阶段期限及 16 MiB 内嵌预算；当前 QQ 报告已取消这些
整报告丢弃条件，按所选去重目标串行排队，具体传输和导出边界见下文。

用户本轮报告：QQ 新鲜私聊的 9 种素材中，5 种原件已验证，3 种经 QQ 内核获取为可信预览，
剩余 1 种受预算限制。这是用户在本机进行的真实验收，未向开发测试提供真实媒体；
只覆盖所验收客户端版本与样本，不能外推为全量、跨版本或全部动画恢复。
微信已有发送事实的用户验收，明文原件恢复仍待真实验收。
用户已在真实测试群验证不同素材的发送识别；此项证据不包含群聊内核映射或媒体获取。

| 来源 | 发送与身份 | 媒体能力与边界 |
| --- | --- | --- |
| QQ PIC，45002=2 且唯一 45003=1 | 确认自定义表情发送；可信 45406 raw MD5 建立 qq-pic:md5:<lowercase> 身份 | 报告自动恢复所选目标，分别返回原件或可信预览 |
| QQ PIC，普通图片、其他或重复 45003 | 保留原有图片事实，不进入已确认表情发送集合 | 不通过本功能获取，不按后缀、尺寸、动画推断表情 |
| QQ MFACE，45002=11 且含 45600 | qq-marketface:sha256:<digest>，原始身份 bytes 的不透明身份 | unsupported/original_digest_unproven；尚无可靠原件摘要映射 |
| 微信 Type 47 | 单一安全 emoji XML 中合法 MD5 建立 wechat:md5:<lowercase>；非法、多义或缺失时身份未知 | 仅支持用户授权目录内完整文件 MD5 匹配的明文原件；未实现内核或 CDN 获取 |
| 微信 Type 3 | 当前 Adapter 按既有规则跳过，不确认表情发送 | 未建立普通图片导入能力 |

QQ 的 45003=1 判据来自有限真实样本，不是所有 QQ 版本的通用协议保证。
45424 只能否决冲突，不能单独授权身份；重复字段的不同摘要使身份未知。
MFACE 缺少 45600 的段仍按原有 Adapter 省略，不能假定所有发送已覆盖。
45812/45403 等路径仅是线索，不能提供读取权限或证明原件。

## 算法侧直接消费

`AnalysisApplicationService.execute(AnalysisRequestDTO(...))` 返回
`AnalysisResultDTO.stickers: StickerData`；Facade 分析结果中路径为
`outcome.result.stickers`。模型定义在 `analysis/stickers.py`。
发送事实和私有定位信息保留在进程内；报告只序列化选定的展示统计和已验证媒体。

| 字段 | 契约 |
| --- | --- |
| sends: tuple[StickerSend, ...] | 每个已确认内容段一条发送，重复发送不去重；一条消息含多个表情时保留多条 |
| media: tuple[StickerMedia, ...] | 每个 media_key 一个结果；通过 key 关联 sends，不能按两个元组的位置对应 |
| message_counts: StickerMessageCounts | self_messages / other_messages / unknown_messages；只读 total_messages 为三者之和 |

sends 与分母使用同一份经过正式过滤、且仍有 Rich 事实的消息集合。
分母包含该集合内的普通文本等非表情消息；一条消息只计一次，不能用表情发送次数代替分母。
缺少 Rich 配对的旧消息不伪报为已覆盖。过滤继续走统一分析链。

每条 send 携带来源、会话与类型、发送者、is_self、消息 ID、原始时间、epoch_seconds、
Asia/Shanghai 的 chat_date、content_index、分类与身份依据、identity_key、media_key、
content_md5 和私有路径线索。未知身份、本人标记与时间保持未知。
occurrence_id 和未知身份使用的 unresolved:<occurrence_id> 只在本分析结果内有效。

可信身份归并规则：

- 仅按非空 identity_key 归并；三个来源命名空间互不归并，不按名称、视觉相似或消息 ID 合并。
- identity_key=None 的发送逐次独立，不能把全部未知身份合为一种素材。
- MFACE 相同 key 只证明原始身份 bytes 相等，不证明已解码出资源 MD5，也不保证跨版本稳定。
- is_self 直接来自来源标记，不能由昵称、频率或参与人数推断。False 在私聊中可解释为 TA，
  群聊中只表示非本人，须同时检查 conversation_type。
- MD5 是来源关联依据，不能提供抗恶意碰撞保证；SHA-256 描述实际取回字节的完整性。

算法可直接使用发送事实，媒体覆盖率应单独统计：

```python
from collections import Counter

data = outcome.result.stickers
by_media = {item.media_key: item for item in data.media}
known_sends = Counter(s.identity_key for s in data.sends if s.identity_key is not None)
originals = {key: item for key, item in by_media.items() if item.status == "available"}
previews = {key: item for key, item in by_media.items() if item.status == "preview"}
message_denominator = data.message_counts.total_messages
```

正式报告使用 `aggregate_stickers` 的成员统计和排名，不维护第二套素材目录。
成员按可靠 sender_id 区分；零值或缺失发送者保留未知身份，不借昵称归属。
群聊非本人发送是多名成员的合计，不能解释为一个 TA。

## QQ 群聊接入审计与原生获取

本轮只读取源码、公开资料和虚构样本，未读取真实 QQ 数据库、媒体或账号状态。

- 数据库 Provider 从 group_msg_table 读取 40001、40027、40030、40033、40050 和完整 40800，
  同时保留存在的 40021、40020；
  并按 40027 选择当前会话；record_id 来自 40001。Adapter 与 collect_sticker_sends 已保留
  conversation_type、conversation_id、sender_id、is_self、消息 ID、时间和素材身份，无需第二套发送模型。
- 群聊 40800 使用与私聊共享的内容 schema，现有 PIC 的唯一 45003=1 分类、45406 摘要与冲突否决规则
  可以复用；这证明实现可复用，不等于所有客户端版本的分类已真实验收。
- [群表字段说明](https://github.com/QQBackup/nt_msg_db_util/blob/master/db_docs/group_msg_table/summary.md)
  区分本地会话键 40027、群号 40030／40021、发送者 QQ 40033、发送者 NT UID 40020。
  [群消息体说明](https://github.com/QQBackup/nt_msg_db_util/blob/master/db_docs/group_msg_table/40800.md)
  明确 45001 是段级 ID，不能替代 40001。
- 固定 [NapCat 4.18.34 类型](https://github.com/NapNeko/NapCatQQ/blob/v4.18.34/packages/napcat-core/types/msg.ts)
  定义群 chatType=2，RawMessage.peerUid 在群聊为群号，senderUin／senderUid 分别表示发送者 QQ／UID，
  MessageElement.elementId 表示元素 ID。
  [getMsgsByMsgId](https://github.com/NapNeko/NapCatQQ/blob/v4.18.34/packages/napcat-core/apis/msg.ts)
  把 peer 和 msgIds 交给 QQ 内核，不证明它与数据库字段的映射。

40001 与 45001 只作为候选 msgId／elementId，不能因类型相似就认定映射成立。
Facade 仅从当前 StickerData 选择 occurrence_id 对应的发送事实。
自动报告复用本次仍受 acquisition 管理的 payload，先核对 session_type 与 internal_key，
不再取得数据库快照，并核对会话范围、群号、成员、is_self、时间及素材摘要。
不接受任意外部消息 ID，不猜邻近 ID，不尝试其他会话。

群聊固定请求使用 chatType=2、字符串群号 peerUid、必需的 expectedSenderUin，
以及存在时的 expectedSenderUid。40021 与 40030 必须相等并匹配当前会话；
40033 对应内核 senderUin，40020 存在时还必须匹配 senderUid，不从群号或 is_self 推断发送者。
本人标记已知时，还复核当前内核 selfInfo 的 UIN／可用 UID 与本人标记是否一致。
Adapter 仍只为 private 填充 QQPicMediaFact.peer_uid，群聊使用独立 group_id 与 sender 字段。

bridge 在同一已认证方法内调用 getMsgsByMsgId，只接受唯一消息，核对 msgId、chatType、
peerUid（以及返回的非空 peerUin）、发送者、消息时间，再唯一匹配 PIC 的 MD5、fileUuid 和 elementId。
群聊 UUID 和元素 ID 缺失、重复定位字段、任何冲突或多义结果均拒绝。
Provider 重算判定，Facade 再检查每项依据；失败只显示固定脱敏错误码与中文提示，指出未确认的依据。
downloadPicMedia 在 downloadMedia 之前再次定位并执行同样检查，防止查询后身份变化。
不会因首次查询通过就跳过下载前校验。

私聊原有定位 schema 和身份语义保持不变；群聊仅增加两个固定发送者字段。
两者共用认证、Bearer／boot_id／runtime_id 绑定、文件安全读取、32 MiB 上限、解码预算与
available／preview 分级。媒体传输仅新增固定分块读取／释放方法，不提供任意路径或通用调用权限。

正常报告验收：手动启动当前开发版并连接 QQ，分别选择私聊／群聊及适量时间范围，
点击生成报告。全程无需素材窗口或网络确认，检查最终报告图片、可信预览标识及对应档位的展开上限，
记录次数、种类、未知身份、资源状态与墙钟耗时，断网重开 HTML；存在 media/ 时须保留整个报告目录。

虚构回归不能证明真实群聊媒体恢复成功；Frozen／Setup 本轮未验收。

## 微信 Type 47 正式报告接线

Provider 查询和 Adapter 均按 `local_type` 低 32 位识别 Type 47，原始 source_type 保留。
明文与 WCDB zstd 压缩 XML 走同一解析器；单一安全 emoji 的合法 MD5 归一后建立身份，
非法、多义或缺失身份仍计入发送量，不参与可靠种类归并，不读取 CDN URL。

私聊和群聊均复用 Provider 导出、ImportService、Rich／投影配对与正式过滤链、
`aggregate_stickers`、报告展示模型和 HTML/JSON 包装。重复发送只合并媒体目标，
发送次数不去重；本人标记来自来源，Type 3 继续跳过。
显式授权根通过现有配置和 Provider 传入；无根时保留统计和未请求状态，
切换账号不继承其他账号的媒体权限。未新增目录扫描入口、CDN 获取或缓存解密。

定向回归使用虚构 Provider 数据，覆盖私聊 GIF、群聊 WebP 原件、压缩及带高位标记的 Type 47、
未知身份、归属、消息分母、改名明文原件匹配、完整动画字节与 HTML 导出，以及显式禁用媒体。
这证明源码接线，不代表真实微信数据库或原件恢复已验收。

## 原件、预览和不可用状态

| status | 含义与消费要求 |
| --- | --- |
| available | 完整文件 MD5 与可信消息摘要相等，且支持格式的全部帧验证通过；可作为原件消费 |
| preview | 仅来自已认证 QQ 原生获取：内核唯一确认消息、发送者和 PIC 元素，但字节 MD5 与消息摘要不符；可展示，不能算原件 |
| not_requested | 有可靠摘要但未授权本地根，不表示已尝试获取 |
| missing | 本次授权范围内无候选或无匹配；reason 区分 no_digest_name_match / digest_mismatch / no_digest_match，不表示全机不存在 |
| unsupported | 摘要无法证明、解码器缺失或容器不支持，不能猜测成功 |
| ambiguous | 同一 MD5 匹配到不同字节，拒绝任选 |
| invalid / unsafe / unreadable | 图片无效、安全检查失败或读取失败，不提供可用字节 |
| limited / cancelled | 预算不足或用户取消，不能解释为缺失 |

成功媒体包含实际格式、帧数、animation_preserved、字节数、SHA-256 和已验证内容。
历史字段名 `original_bytes` 同时承载 available 与 preview，必须先检查 status；
preview 的 reason=content_digest_mismatch，不能仅凭该字段有字节就宣称原件。
QQ 自动报告把成功字节移至私有 `stored` 临时文件，`original_bytes=None` 不表示缺图；
消费者须同时支持这两种保留方式。临时文件不暴露源路径，取消／失败释放当前所有权，
正常结果随最后一个持有者释放而关闭删除；不形成长期缓存。
支持 PNG、JPEG、GIF、APNG、WebP，保留实际取回字节，不转码、不裁成首帧。
animation_preserved 表示取回内容本身包含多帧，不证明预览与未知原件的动画相同。
verified_reference 仅是本地读取时的来源，不承诺外部缓存之后仍相同；消费已验证字节而非重新打开旧路径。

`associate_sticker_media(data, media_keys=..., roots=..., source=...)` 返回新的 StickerData，
不修改发送事实或消息分母。正式 QQ 报告将此结果与原生获取结果交给同一报告装配流程。
身份复核失败不保留图片字节，也不能转为“全局缺失”。

## 两条正式媒体路径

离线目录关联保留为正式能力：无需 QQ 在线，适用于已下载原件和微信显式明文目录。
目录发现和账号选择界面已退休；正式路径只使用已有显式授权根，不扫描安装目录。QQ 只打开摘要命名或授权范围内精确路径线索命中的候选；
微信显式目录允许改名原件。最终仍完整计算 MD5、检查歧义并解码全部帧。
不恢复无任何可靠线索的 QQ 任意命名文件、加密缓存或商店资源。

本地路径验证拒绝越界、UNC、符号链接、junction/reparse 和特殊文件。
Windows 打开后检查句柄最终路径并排除并发写入/删除；POSIX 逐级使用 O_NOFOLLOW。
读取完整性、读前后身份和元数据稳定性必须成立；未完整扫描不能发布该次范围的成功结论。

QQ 原生获取只处理当前私聊或 QQ 群聊所选的一条已确认 PIC 消息。
报告生成自动调度去重后的所需目标。
Facade 复用本次仍受 acquisition 管理的 payload，通过现有已认证桥接校验消息、时间、会话、发送者、
MD5、fileUuid 和 elementId；下载操作再次定位唯一元素后调用原生下载。
这两层身份检查均是正式安全机制，不能随诊断界面一起删除。
桥接只传有界字节，不传本地路径或内核错误；文件类型、打开身份、路径复核、读前后句柄稳定性
和完整读取检查保留。Windows 使用 BigInt ino，跨 lstat/fstat 不比较 dev，
同 API 内仍比较 dev/ino；未知文件 ID 继续拒绝。
消息身份已确认也不保证下载字节与消息摘要一致，因此必须保留原件／预览分级。
QQ 报告媒体先保留于进程拥有、关闭即删除的临时文件，正式导出才写入报告包；
不增加长期媒体缓存，QQ 自身下载可能更新其缓存。

## 产品限制：传输与解码预算

QQ 原生获取使用独立容量档，本地目录／微信的原有限制保持。
不以数量或整报告墙钟截止放弃尚未尝试目标；触及单项安全限制不代表资源不存在。

| 限制 | 当前行为与产品影响 |
| --- | --- |
| QQ 单文件 32 MiB | 桥接、Provider、字节验证器共同约束；超过仍以明确错误拒绝，不伪报缺失 |
| 分块 256 KiB，单桥接一个文件租约 | 认证及代际绑定逐次检查；不把整个文件变为 Base64 RPC。必须按偏移顺序读完，最后一块前复核文件身份、元数据与 EOF。取消／失败释放，失联租约空闲 30 秒自动关闭 |
| 单帧画布最多 4 × 1024 × 1024 像素 | GIF 在进入解码器前检查所有图像区域均处于逻辑画布内；超大画布拒绝，不能靠显示缩放绕过 |
| QQ 单素材累计 512 × 1024 × 1024 像素及工作单位 | 全部帧顺序验证，不保留全部解码帧。每帧工作量为画布像素数加 65536；没有默认帧数门槛，超限为 limited/decode_budget |
| QQ 单素材验证 10 秒协作式截止 | 在容器检查和逐帧解码之间检查，支持取消；不是原生解码硬中断 |
| 本地单素材累计 32 × 1024 × 1024 像素、64 × 1024 × 1024 工作单位、2 秒 | 微信及本地目录路径维持原值 |
| 本地整批累计 64 × 1024 × 1024 像素、128 × 1024 × 1024 工作单位 | 多素材共享，超限为 limited/total_decode_budget；显式传入的更小帧数上限仍生效 |
| 每批最多 32 个素材，本地跨批保留 128 MiB | 已验证原件复用，不按每次发送重复读取 |
| 本地单文件 16 MiB、总读取 128 MiB | 与 QQ 网络传输是不同边界，未命中的读取也消耗预算 |
| 本地扫描目录项、深度和时间 | 默认 4096 项、8 层、10 秒协作式截止；QQ 定向遍历最多 100000 项，仅打开候选；未完成搜索不能认定缺失 |
| QQ 报告无固定获取数量和阶段总时限 | 全群／共同榜优先，其后招牌与个人目标，按既有模型去重。单项失败继续其余目标；查询 8 秒、原生下载 120 秒、客户端接收下载结果 135 秒（覆盖二次查询及传输余量）、分块／释放各 10 秒。超时后仍等待底层操作结束才允许下一项，不能确认结束时可取消并等待人工重启 |
| QQ 每个桥接滚动 60 秒各 64 次身份查询和媒体获取 | 配额保留，队列等待恢复并可取消；不重置桥接、不把排队目标写为下载失败。下载含二次身份查询，该查询属于当前下载额度 |
| QQ 报告内嵌原始字节合计最多 8 MiB | 更大报告使用摘要命名的 media/ 相对资源，HTML／JSON 不内嵌大 Base64；没有 256 MiB 整报告丢图门槛，容量受可用磁盘和浏览器承载限制。必须保留完整报告目录；摘要或文件检查失败则明确导出失败 |
| 非 QQ 报告内嵌 16 MiB | 原有行为保持 |

取消后 GUI 立即返回选择页；进行中的下载 RPC 及原生解码须先返回，线程会在后续检查点释放
传输与临时文件，不再导出或打开迟到结果。保持串行原生下载，未引入超时后的并行任务。
不保证网络、内核或编解码器挂起时能在进程内强制中断。

QQ Facade 将 limited/decode_budget 单独转为固定公共错误 qq_media_decode_budget，
中文提示说明画布、累计像素、逐帧工作量或验证耗时受限；其他图片验证失败仍返回 qq_media_invalid_content。
失败结果不写回 media，也不保留未通过验证的图片字节。
本地与 QQ 获取共用同一个逐帧验证器：每帧按解码画布宽 × 高累计一次，
GIF 的局部更新矩形不等于解码画布，容器校验不重复累计帧数或像素；文件大小按原始字节计算。
媒体身份来自完整文件摘要或已确认消息的可信预览来源；完整解码属于格式与资源准入检查，
不承担发送身份或素材归并。保留完整验证可在报告展示前发现后段损坏；GIF、APNG、WebP
均逐帧验证并复用上述预算。跳过后段解码仅凭首帧发布原件不作为本次方案。

报告通过原始图片字节播放动画，保持原件／可信预览状态，不转码或裁成首帧。
虚构长 GIF/APNG/WebP 验证了超过 128 帧的正常素材可通过；后段截断、越界帧、
画布和工作量超限继续拒绝。独立窗口的 QMovie 播放器与专属生命周期测试随窗口退休。
QQ 路径验证了约 30 MiB 的 320 × 240、300 帧 GIF，以及超过旧累计预算的 512 × 512、300 帧 GIF；
后者仍超过本地目录旧档位，不能据此宣布微信容量已调整。
解码预算检查不是可强制中断原生解码调用的硬超时或进程内存硬隔离。
未读取用户真实 GIF；它值得重新验收，但若触及保留的其他安全边界仍会拒绝。

## 清理结果与尚未验收边界

已清退独立消息映射验证窗口、候选列表及展示 DTO、专属 GUI/Facade 测试和旧探针操作文档。
原有 PIC-1、Top-1 实验脚本及接线的删除继续保留；本轮继续退休独立素材窗口及其目录、信号、回调、手动获取和另存流程。
底层媒体定位事实、身份校验 RPC、本地扫描验证器及其安全回归保留。

尚未验收：微信真实原件恢复、QQ MFACE 原件、全部 QQ 版本的 PIC 分类、全部格式与大动画、
预算外素材、跨机器及本轮 Frozen/Setup 集成。历史打包或虚构解码测试不能替代这些验收。
只对用户检查过的来源版本与样本报告成功；真实 QQ 和媒体最终验证由用户手动进行。
