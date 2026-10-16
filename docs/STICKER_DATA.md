# 表情包事实与原件数据通路

本轮是本地核心数据能力，不新增 UI、榜单、报告章节或数据库读取器。
自动测试只使用虚构消息及程序生成的媒体；**尚未验证真实 QQ / 微信恢复**。
原件解码支持在安装声明依赖的源码环境中使用；现有 Frozen 配置明确排除 Pillow，
本轮保持该发行边界。默认桌面分析不加载解码器，发送事实仍可用；若运行环境缺少
解码器，原件验证返回 `unsupported/decoder_unavailable`，不能标为恢复成功。

## 实际支持矩阵

| 来源 | 确认发送事实 | 素材身份 | 原件获取 |
| --- | --- | --- | --- |
| QQ Direct DB MFACE，`45002=11` 且有 `45600` | 支持，保留每个段的发送记录 | `qq-marketface:sha256:`，原始 bytes 的不透明派生值；不宣称解码了 emoji ID / MD5 | 未支持：`unsupported/original_digest_unproven`；`45812/45814` 只保存为不可信线索，不读取 |
| QQ PIC，`45002=2` | 普通图片事实，**不进入已确认表情包发送集合** | 保存 `45406` 的 16 字节 raw MD5、`45418` 原图标志及 `45403/45812` 路径线索（若有） | 本轮不获取；尚无可靠自定义表情分类证据 |
| 微信 Type 47，单一 emoji XML 且 md5 是 32 位十六进制 | 支持 | `wechat:md5:<lowercase>`；独立于旧表达展示 key | 显式指定可信根后，完整文件 MD5 相等且可验证解码才成功 |
| 微信 Type 47，缺失 / 非法 / 多义 MD5、XML 不可安全解析 | 支持 | `identity_key=None`，逐次发送独立，不按 message_id 或标签归并 | `unsupported/original_digest_unproven` |
| 微信 Type 3 | 不确认表情包 | 不猜测 | Adapter 仍按现有规则跳过；本轮未建立普通图片导入能力 |

QQ 缺少 `45600` 的 MFACE 段仍沿用 Adapter 原先的省略行为，本轮没有恢复该类发送事实。
不透明 QQ key 只说明原始身份字节相同，不保证不同字节一定代表不同视觉素材，也不保证跨版本稳定。
本地不存在、加密、未下载的微信原件不会被网络下载、缩略图或标签替代。

## 消费契约

`AnalysisApplicationService.execute(AnalysisRequestDTO(...))` 的
`result.stickers: StickerData` 提供两个不可变元组：

- `sends`：来源、会话及类型、sender_id、message_id、原始时间、统一 epoch_seconds、
  Asia/Shanghai 的 chat_date、content_index、classification_basis、identity_basis、
  identity_key、media_key、资源 MD5 和路径线索。未知发送者和时间保持未知。
- `media`：每个 media_key 一个结果，包含 status / reason；成功时包含
  verified_reference、SHA-256、实际 format、frame_count、animation_preserved、byte_count
  及完整不可变 `original_bytes`。失败时没有可供冒充原件的字节或路径。

以 `media_key` 关联两个集合。`occurrence_id` 由本次过滤后消息序号和内容段序号组成，
只在当前结果内唯一，**不是跨运行持久主键**。重复或缺失 message_id 不会合并发送。
`identity_key=None` 时禁止按素材聚合；有 QQ opaque key 时须保留 identity_basis，
不能当作已经校验的媒体哈希。成员按 source / conversation / sender_id 聚合，
日期使用 chat_date；未知 sender_id 不能用昵称猜测。发送次数始终按 sends 逐次计算。

统一链路为：ImportService 原有 Rich / 投影配对 → scope / smart / quality 过滤 →
按存活投影实例选取 Rich → `collect_sticker_sends` → 应用层原件验证 → result.stickers。
资源成功率不能决定发送是否保留。不能把 available 数量当作全部表情包数量。

此通路不裁剪发送记录、不输出到 Echo JSON / HTML，不改变 ExpressionReport 的 sticker
总量和旧 fallback key，也不把 sticker 展示文本送入词法统计。新数据及媒体字节、路径、
身份默认不进入 repr / 日志。它仍然是敏感的内存数据，调用者不得随意序列化或上传。
只有旧 ChatMessage 的来源没有本通路所需 Rich 事实，不能从文字占位符重建。

## 关联证据与失败

默认 `sticker_media_roots=()`：完全不发现或读取媒体。仅对调用者显式传入的绝对本地根
扫描，不从配置、用户名、QQ 消息路径、URL 或客户端安装位置推导搜索范围。
文件名和扩展名均不参与匹配；先计算完整文件 MD5，与 Type 47 XML 的 MD5 比较。
匹配后验证 PNG、JPEG、GIF、APNG、WebP 的真实格式和全部帧，保留原始字节、不转码。
相同字节多份路径和多次发送仅保留一份媒体；同一 MD5 下不同字节视为歧义，拒绝任选。
MD5 是来源提供的关联证据，不能提供抗恶意碰撞的密码学保证；SHA-256 用于原件完整性复验。

| status | 含义 |
| --- | --- |
| available | 完整扫描内唯一内容匹配，原件通过格式与帧验证 |
| not_requested | 有可靠 MD5，但未指定可信根，未尝试获取 |
| unsupported | 无可靠原件摘要，或缺少解码器；reason 区分，不猜测成功 |
| missing | 在完整、成功的指定范围扫描内没有摘要匹配；不代表全机不存在 |
| ambiguous | 同一 MD5 对应不同文件内容 |
| invalid | 匹配字节不可验证为支持的图像格式 |
| unsafe | 路径、reparse / symlink、特殊文件或文件稳定性检查失败 |
| unreadable | 读取失败或目录不可读，不能认定缺失 |
| limited | 文件、总读取量、目录项、深度、时间或解码预算耗尽，不能认定缺失 |

默认上限：16 个根、4096 个目录项、8 层子目录、单文件 16 MiB、总读取 128 MiB；
每个原件最多 128 帧、所有帧累计 32 Mi 像素；扫描使用 10 秒协作式截止时间。
时间检查发生在目录项及原件解码之间，**不是可中断原生解码调用的硬超时**。
内存保留受总读取预算约束的命中原件；解码还有额外像素缓冲。未命中文件同样计入预算。
目录过大时应由用户选择更小的目录，不能绕过安全检查。

所有祖先及文件拒绝链接 / junction / reparse，拒绝相对根、`..`、UNC 根和特殊文件。
Windows 在读字节前检查打开句柄的最终路径，持有禁止并发写入 / 删除的句柄，
比较路径与句柄文件身份及读前读后元数据；POSIX 使用逐级 `O_NOFOLLOW` 目录描述符。
扫描中断或不安全时，整个本次可解析媒体范围返回明确失败，不发布部分扫描的成功。
不把获准根之外的相似文件、猜测文件或来源路径作为 fallback。

verified_reference 仅是读取时来源证明；外部缓存随后可变动。消费原件时使用
`original_bytes` 和 SHA-256，不把旧路径的存在当作持续有效的原件证明。
不建立磁盘缓存、不跨分析保存媒体；本次结果随调用方释放，既有 payload 清理合同不变。

## 研究证据与缺口

- 仓库历史研究：[QQ 表情准备度](research/2026-09-26-qq-direct-db-expression-data-readiness.md)。
  该文提及的本地 reference 目录当前不存在；本轮没有寻找或读取私人研究资产。
- 公开 [QQBackup schema](https://github.com/QQBackup/nt_msg_db_util/blob/317024ce2c5e3482fdf9f310a5a7159ab4927e34/msgdb/proto/c2c_40800.proto)
  及 [字段说明](https://github.com/QQBackup/nt_msg_db_util/blob/317024ce2c5e3482fdf9f310a5a7159ab4927e34/db_docs/c2c_msg_table/40800.md)
  支持 PIC 的 MD5 / 原图标志 / 路径语义、MFACE 类型和资源路径线索；没有给出可靠的
  PIC 自定义表情判据，`45600` 仍是 bytes。通用媒体字段的说明不足以证明商城表情原件。
- 公开 [微信 Type 47 / MD5 说明](https://github.com/spacelan/wechat-emoticon/blob/0b9401cffe1d15b4c91df4f850b9132c3e9f3c17/README.md)
  及 [MD5 消费源码](https://github.com/spacelan/wechat-emoticon/blob/0b9401cffe1d15b4c91df4f850b9132c3e9f3c17/index.js)
  是历史协议佐证，不证明当前 Windows 微信缓存布局。本轮不声称已发现任何版本的
  自动缓存定位规则；采用显式根与实际内容摘要验证，仍需用户进行真实原件验收。

后续 QQ 原件支持需要证明 `45600` 中资源摘要的编码，或其他经过验证的原件摘要映射；
仅有 local_path 不能证明文件是原图。PIC 分类需要 Direct DB 本身的可靠标记，
不能用文件后缀、尺寸、动画或常用图片猜测。

## 用户本机验收（本轮没有执行）

使用已验证解释器及当前源码 PYTHONPATH。用户自行取得正式来源通路产生的本地
`qq-db-json` / `wechat-db-json` payload，并显式挑选允许扫描的小目录。不要上传数据。
可在本地 Python 中运行以下核心 API（替换为自己的路径，不将路径写进仓库）：

```python
from collections import Counter
from pathlib import Path
from qq_chat_analyzer.application import AnalysisRequestDTO
from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService

result = AnalysisApplicationService().execute(AnalysisRequestDTO(
    input_path=Path("<本地来源导出文件>"),
    output_directory=Path("<本次独立分析输出目录>"),
    stopwords_path=Path("<本地停用词文件>"),
    sticker_media_roots=(Path("<明确允许读取的绝对本地媒体目录>"),),
))
print("保留发送", len(result.stickers.sends))
print("素材结果", dict(Counter(m.status for m in result.stickers.media)))
```

按发送者、会话、时间对照客户端中少量已知发送；重复发送应保留多条 send，但共用 media_key。
对 available，用户在本机复算 `original_bytes` 的 MD5 与 send.content_md5、SHA-256 与
media.sha256，并用本地图片工具逐帧检查原始动图。缺文件、改内容、缩略图、非法路径应
明确失败，发送事实仍在；无 MD5 不能归并。QQ MFACE 当前应显示 unsupported，PIC / Type 3
不得进入已确认集合。验收只适用于用户实际检查的来源版本、目录与样本，不能扩大为全量恢复。
