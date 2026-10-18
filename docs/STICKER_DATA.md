# StickerData：发送事实、素材身份与媒体消费契约

## 当前能力与验收证据

表情数据复用现役 QQ Direct DB / 微信分析链，不新增聊天数据来源。
正常私聊分析后的“查看表情素材”提供分页目录、本地原件关联和单独授权的 QQ 原生获取。
默认分析不联网、不扫描未授权目录、不加载图片解码器。

用户本轮报告：QQ 新鲜私聊的 9 种素材中，5 种原件已验证，3 种经 QQ 内核获取为可信预览，
剩余 1 种受预算限制。这是用户在本机进行的真实验收，未向开发测试提供真实媒体；
只覆盖所验收客户端版本与样本，不能外推为全量、跨版本或全部动画恢复。
微信已有发送事实的用户验收，明文原件恢复仍待真实验收。

| 来源 | 发送与身份 | 媒体能力与边界 |
| --- | --- | --- |
| QQ PIC，45002=2 且唯一 45003=1 | 确认自定义表情发送；可信 45406 raw MD5 建立 qq-pic:md5:<lowercase> 身份 | 支持授权目录离线原件关联、单独确认后的 QQ 内核获取；分别返回原件或可信预览 |
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

`build_sticker_catalog(sends, source=...)` 提供私聊素材的我／TA／未知次数及降序目录，
复用上述身份，不是新的发送来源或算法排名口径。

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

QQ 原生获取是单独确认后的正式网络路径，只处理当前私聊所选的一条已确认 PIC 消息。
Facade 重新获取该消息的存储事实，通过现有已认证桥接校验消息、时间、会话、发送者、
MD5、fileUuid 和 elementId；下载操作再次定位唯一元素后调用原生下载。
这两层身份检查均是正式安全机制，不能随诊断界面一起删除。
桥接只传有界字节，不传本地路径或内核错误；文件类型、打开身份、路径复核、读前后句柄稳定性
和完整读取检查保留。Windows 使用 BigInt ino，跨 lstat/fstat 不比较 dev，
同 API 内仍比较 dev/ino；未知文件 ID 继续拒绝。
消息身份已确认也不保证下载字节与消息摘要一致，因此必须保留原件／预览分级。
媒体只在本次进程内保留，不增加 Echo 磁盘缓存；QQ 自身下载可能更新其缓存。

## 产品限制：传输与解码预算

这些预算本轮保持不变，触限不代表映射错误或资源不存在。

| 限制 | 当前行为与产品影响 |
| --- | --- |
| QQ 单次传输 2 MiB | 桥接、Provider、字节验证器共同约束，超限不展示；这是传输上限，不是像素或动画复杂度上限 |
| 单素材累计 32 × 1024 × 1024 像素、128 帧 | 全部帧解码，超限为 limited/decode_budget；小于 2 MiB 的高度压缩动图仍可能触限 |
| 本地整批累计 64 × 1024 × 1024 像素、512 帧 | 多素材共享，超限为 limited/total_decode_budget |
| 每页最多 32 个素材，本地跨页保留 128 MiB | 已验证原件复用，不按每次发送重复读取 |
| 本地单文件 16 MiB、总读取 128 MiB | 与 QQ 网络传输 2 MiB 是不同边界，未命中的读取也消耗预算 |
| 本地扫描目录项、深度和时间 | 默认 4096 项、8 层、10 秒协作式截止；QQ 定向遍历最多 100000 项，仅打开候选；未完成搜索不能认定缺失 |
| QQ 每个桥接生命周期各 8 次身份查询和媒体获取 | 查询与获取分别有预算，不能据第九次失败判断资源不支持 |

QQ Facade 当前把图片验证失败（包括 decode_budget）转为 qq_media_invalid_content 公共错误，
不会将失败结果写回 media。因此该 UI 错误本身不能区分损坏与解码预算不足；
若需要精确产品提示，须另行确认错误契约，不在本轮扩大修改。
解码预算检查不是可强制中断原生解码调用的硬超时；提高帧数或像素会增加内存和耗时，
不能为通过一个样本直接放宽。9 种素材中剩余 1 种只按用户报告记为受预算限制，不补作根因推断。

## 清理结果与尚未验收边界

已清退独立消息映射验证窗口、候选列表及展示 DTO、专属 GUI/Facade 测试和旧探针操作文档。
原有 PIC-1、Top-1 实验脚本及接线的删除继续保留；产品只保留正常分页素材窗口。
底层媒体定位事实、身份校验 RPC、本地扫描验证器及其安全回归保留。

尚未验收：微信真实原件恢复、QQ MFACE 原件、全部 QQ 版本的 PIC 分类、全部格式与大动画、
预算外素材、跨机器及本轮 Frozen/Setup 集成。历史打包或虚构解码测试不能替代这些验收。
只对用户检查过的来源版本与样本报告成功；真实 QQ 和媒体最终验证由用户手动进行。
