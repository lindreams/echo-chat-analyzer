# StickerData：发送事实、素材身份与媒体消费契约

## 当前能力与验收证据

表情数据复用现役 QQ Direct DB / 微信分析链，不新增聊天数据来源。
QQ 私聊／群聊点击生成报告后，先统计并选择 Top 10、共同榜、招牌等实际展示素材，
按可靠身份去重。优先关联本流程已有的可信目录；缺图的 QQ PIC 自动复用已登录客户端的
原生通路，无网络确认框。验证后一次导出最终 HTML/JSON 并打开，失败保留统计及占位。
“查看表情素材”保留分页目录、本地原件关联与手动补救，不是正常生成的必经流程。
QQ 群聊选中素材后可查看按 sender_id 区分的逐成员次数；
原生获取复用同一操作，可在当前窗口选择一条成员发送记录，默认优先其他成员。
联网确认后先复核内核消息及 PIC 元素，通过全部检查才下载；群聊真实媒体展示仍待用户验收。
QQ 正式报告生成会获取所选素材并加载现有验证器；不扫描未授权目录，不获取无关会话素材。
微信和单独导入路径保留原有行为。高级窗口的单独获取仍使用其原有确认动作。

用户本轮报告：QQ 新鲜私聊的 9 种素材中，5 种原件已验证，3 种经 QQ 内核获取为可信预览，
剩余 1 种受预算限制。这是用户在本机进行的真实验收，未向开发测试提供真实媒体；
只覆盖所验收客户端版本与样本，不能外推为全量、跨版本或全部动画恢复。
微信已有发送事实的用户验收，明文原件恢复仍待真实验收。
用户已在真实测试群验证不同素材的发送识别；此项证据不包含群聊内核映射或媒体获取。

| 来源 | 发送与身份 | 媒体能力与边界 |
| --- | --- | --- |
| QQ PIC，45002=2 且唯一 45003=1 | 确认自定义表情发送；可信 45406 raw MD5 建立 qq-pic:md5:<lowercase> 身份 | 报告自动恢复所选目标；高级窗口支持手动补救。分别返回原件或可信预览 |
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
这是进程内的不可变数据，不进入现有 HTML / JSON 报告序列化。

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

`build_sticker_catalog(sends, source=..., conversation_type="private")` 默认保持私聊目录；
显式传入 `conversation_type="group"` 提供群聊目录。两者均复用上述身份及既有次数降序，
不是新的发送来源或算法排名口径。条目 `member_counts` 保留各 sender_id 的独立次数，
`unknown_sender_count` 只表示缺少发送者身份，不能与 is_self 未知的 `unknown_count` 混淆。
QQ Direct DB 私聊与群聊的零值发送者均按未知身份保留，不使用附带昵称归入真实成员；
发送次数与消息分母仍计入未知方，素材目录计入 `unknown_sender_count`，不进入 `member_counts`。
群聊 `other_count` 是所有非本人发送合计，不能解释为一个 TA；窗口选中素材后展示完整成员列表，
可以选择、复制。同一素材跨成员只生成一个条目；未知素材仍按 occurrence_id 逐次独立。

## QQ 群聊接入审计与原生获取

本轮只读取源码、公开资料和虚构样本，未读取真实 QQ 数据库、媒体或账号状态。

- 数据库 Provider 从 group_msg_table 读取 40001、40027、40030、40033、40050 和完整 40800，
  同时保留存在的 40021、40020；
  并按 40027 选择当前会话；record_id 来自 40001。Adapter 与 collect_sticker_sends 已保留
  conversation_type、conversation_id、sender_id、is_self、消息 ID、时间和素材身份，无需第二套发送模型。
- 群聊 40800 使用与私聊共享的内容 schema，现有 PIC 的唯一 45003=1 分类、45406 摘要与冲突否决规则
  可以复用；这证明实现可复用，不等于所有客户端版本的分类已真实验收。
- 原目录仅按 private 筛选，主窗口也只向私聊开放素材动作，窗口文案只有我／TA。
  本轮增加显式会话类型选择、QQ 群聊入口和逐成员计数；零值发送者的未知身份语义与私聊一致，见 [DATA_SEMANTICS](../DATA_SEMANTICS.md)。
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
不再取得数据库快照；高级窗口手动获取仍重新读取当前会话的入库事实。
两者均核对会话范围、群号、成员、is_self、时间及素材摘要。
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

私聊原有请求 schema 和身份语义保持不变；群聊仅增加两个固定发送者字段，未新增 RPC 方法或通用调用权限。
两者共用认证、Bearer／boot_id／runtime_id 绑定、文件安全读取、2 MiB 上限、解码预算与
available／preview 分级，不增加媒体系统、扫描器、验证窗口或持续诊断工具。

正常报告验收：手动启动当前开发版并连接 QQ，分别选择私聊／群聊及适量时间范围，
点击生成报告。全程无需素材窗口或网络确认，检查最终报告图片、可信预览标识及 Top 10，
记录次数、种类、未知身份、资源状态与墙钟耗时，断网重开同一 HTML 验证自包含。

高级手动补救验收（可选）：在现有测试群限定分析范围，
打开“查看表情素材”，先选之前未恢复的其他成员 PIC，在发送记录下拉框确认对应成员，
点击“通过 QQ 获取所选素材”并单独确认。只有身份复核通过才下载并展示；随后选择本人发送记录复验。
同一素材可分别选择其他成员和本人记录进行验证，每次仍需单独确认并消耗原有桥接预算。
反馈是否成功、图片是否正确、原件／可信预览状态，或失败时的固定错误码与中文提示即可，
不提交真实消息、图片、账号标识或凭据。
最后检查既有私聊的目录和 QQ 获取。虚构回归不能证明真实群聊媒体恢复成功；Frozen／Setup 本轮未验收。

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

成功媒体包含实际格式、帧数、animation_preserved、字节数、SHA-256 和不可变字节。
历史字段名 `original_bytes` 同时承载 available 与 preview，必须先检查 status；
preview 的 reason=content_digest_mismatch，不能仅凭该字段有字节就宣称原件。
支持 PNG、JPEG、GIF、APNG、WebP，保留实际取回字节，不转码、不裁成首帧。
animation_preserved 表示取回内容本身包含多帧，不证明预览与未知原件的动画相同。
verified_reference 仅是本地读取时的来源，不承诺外部缓存之后仍相同；消费已验证字节而非重新打开旧路径。

`associate_sticker_media(data, media_keys=..., roots=..., source=...)` 和
`ChatAnalyzerFacade.fetch_qq_sticker_media(..., network_consent=True)` 返回新的 StickerData，
不修改发送事实或消息分母，调用方必须接住返回值。
素材窗口富化结果保存在 `StickerMediaDialog.stickers`，不会自动回写原分析 outcome；
算法需要媒体时应接收富化后的同一数据对象，不能假定旧 outcome 已被更新。
QQ 获取失败以脱敏 FacadeError 返回，旧数据保持不变；错误码不能被转换为“全局缺失”。

## 两条正式媒体路径

离线目录关联保留为正式能力：无需 QQ 在线，适用于已下载原件和微信显式明文目录。
QQ 目录发现只读取公共 INI 和有限目录元数据，候选账号及范围仍须用户确认；
不推断当前账号、不扫描安装目录。QQ 只打开摘要命名或授权范围内精确路径线索命中的候选；
微信显式目录允许改名原件。最终仍完整计算 MD5、检查歧义并解码全部帧。
不恢复无任何可靠线索的 QQ 任意命名文件、加密缓存或商店资源。

本地路径验证拒绝越界、UNC、符号链接、junction/reparse 和特殊文件。
Windows 打开后检查句柄最终路径并排除并发写入/删除；POSIX 逐级使用 O_NOFOLLOW。
读取完整性、读前后身份和元数据稳定性必须成立；未完整扫描不能发布该次范围的成功结论。

QQ 原生获取只处理当前私聊或 QQ 群聊所选的一条已确认 PIC 消息。
报告生成自动调度去重后的所需目标；高级窗口仍支持单独确认的手动补救。
Facade 复用本次 payload 或在手动补救时重新获取存储事实，通过现有已认证桥接校验消息、时间、会话、发送者、
MD5、fileUuid 和 elementId；下载操作再次定位唯一元素后调用原生下载。
这两层身份检查均是正式安全机制，不能随诊断界面一起删除。
桥接只传有界字节，不传本地路径或内核错误；文件类型、打开身份、路径复核、读前后句柄稳定性
和完整读取检查保留。Windows 使用 BigInt ino，跨 lstat/fstat 不比较 dev，
同 API 内仍比较 dev/ino；未知文件 ID 继续拒绝。
消息身份已确认也不保证下载字节与消息摘要一致，因此必须保留原件／预览分级。
媒体只在本次进程内保留，不增加 Echo 磁盘缓存；QQ 自身下载可能更新其缓存。

## 产品限制：传输与解码预算

文件、累计像素与保留字节上限保持不变；固定默认帧数门槛改为按逐帧工作量计费。
触限不代表映射错误或资源不存在。

| 限制 | 当前行为与产品影响 |
| --- | --- |
| QQ 单次传输 2 MiB | 桥接、Provider、字节验证器共同约束，超限不展示；这是传输上限，不是像素或动画复杂度上限 |
| 单帧画布最多 4 × 1024 × 1024 像素 | GIF 在进入解码器前检查所有图像区域均处于逻辑画布内；超大画布拒绝，不能靠显示缩放绕过 |
| 单素材累计 32 × 1024 × 1024 像素 | 全部帧顺序验证，只保留原始字节，不保留全部已解码帧；超限为 limited/decode_budget |
| 单素材工作量最多 64 × 1024 × 1024 单位 | 每帧收取画布像素数加 65536 单位固定开销，限制小帧洪泛和解码总工作量；不再默认超过 128 帧即拒绝 |
| 单素材验证 2 秒协作式截止 | 在容器检查和逐帧解码之间检查；触限仍为 limited/decode_budget |
| 本地整批累计 64 × 1024 × 1024 像素、128 × 1024 × 1024 工作单位 | 多素材共享，超限为 limited/total_decode_budget；显式传入的更小帧数上限仍生效 |
| 每页最多 32 个素材，本地跨页保留 128 MiB | 已验证原件复用，不按每次发送重复读取 |
| 本地单文件 16 MiB、总读取 128 MiB | 与 QQ 网络传输 2 MiB 是不同边界，未命中的读取也消耗预算 |
| 本地扫描目录项、深度和时间 | 默认 4096 项、8 层、10 秒协作式截止；QQ 定向遍历最多 100000 项，仅打开候选；未完成搜索不能认定缺失 |
| QQ 单次报告最多 32 个缺图 PIC 目标，串行、不重试；素材阶段 60 秒 | 全群／共同榜优先，其后招牌与按名次轮转的个人目标；不再因剩余不足 35 秒提前整批跳过。查询最多 8 秒、客户端传输最多 25 秒，并按批次实际剩余时间缩短；验证仍受 2 秒协作式限制。截止后不开始新请求，不保留迟到结果。客户端传输超时或返回 busy 时不能证明远端已结束，后续标记 report_media_inflight_unknown，不继续冲击桥接。取消立即返回选择页，进行中的有界 RPC／原生解码先返回；素材阶段取消后不再导出报告，迟到结果不会打开。此处不是原生调用与 socket 读取的进程级硬超时 |
| QQ 每个桥接滚动 60 秒各 64 次身份查询和媒体获取 | 与单报告上限叠加；超限立即降级、不排队重试、不重启或重置桥接。额度随窗口恢复；保留单媒体在途限制和 2 MiB 文件上限 |

QQ Facade 将 limited/decode_budget 单独转为固定公共错误 qq_media_decode_budget，
中文提示说明画布、累计像素、逐帧工作量或验证耗时受限；其他图片验证失败仍返回 qq_media_invalid_content。
失败结果不写回 media，也不保留未通过验证的图片字节。
本地与 QQ 获取共用同一个逐帧验证器：每帧按解码画布宽 × 高累计一次，
GIF 的局部更新矩形不等于解码画布，容器校验不重复累计帧数或像素；文件大小按原始字节计算。
媒体身份来自完整文件摘要或已确认消息的可信预览来源；完整解码属于格式与资源准入检查，
不承担发送身份或素材归并。保留完整验证可在 GUI 播放前发现后段损坏；GIF、APNG、WebP
均逐帧验证并复用上述预算。跳过后段解码仅凭首帧发布原件不作为本次方案。

GUI 仍复用 QMovie 和可回绕的 QBuffer，明确设置 CacheNone，按需播放当前帧，
不缓存整段动画；显示缩放不改变原始字节、摘要、available/preview 或统计。
过短帧延迟通过暂停和单次定时恢复，限制到每秒最多约 25 次刷新；异常播放固定提示并释放播放器，
切换素材、关闭窗口也停止恢复定时器。Qt 编解码器是否支持对应格式仍以当前发行环境为准。

虚构长 GIF/APNG/WebP 验证了超过 128 帧的正常素材可通过；GUI 回归用真实 QMovie
定时播放超过第 128 帧并检查画面变化、无全帧缓存与关闭释放；后段截断、越界帧、画布和工作量超限继续拒绝。
例如 256 × 256 的 300 帧动画在像素和工作量预算内，512 × 512 的 200 帧动画仍会超过累计像素预算。
解码预算检查不是可强制中断原生解码调用的硬超时或进程内存硬隔离。
未读取用户真实 GIF；它值得重新验收，但若触及保留的其他安全边界仍会拒绝。

## 清理结果与尚未验收边界

已清退独立消息映射验证窗口、候选列表及展示 DTO、专属 GUI/Facade 测试和旧探针操作文档。
原有 PIC-1、Top-1 实验脚本及接线的删除继续保留；产品只保留正常分页素材窗口。
底层媒体定位事实、身份校验 RPC、本地扫描验证器及其安全回归保留。

尚未验收：微信真实原件恢复、QQ MFACE 原件、全部 QQ 版本的 PIC 分类、全部格式与大动画、
预算外素材、跨机器及本轮 Frozen/Setup 集成。历史打包或虚构解码测试不能替代这些验收。
只对用户检查过的来源版本与样本报告成功；真实 QQ 和媒体最终验证由用户手动进行。
