# 回复关系：0.4.0 接续记录

2026-10-29 负责人决定将 QQ／微信回复关系延期到 **0.4.0**，当前转向 0.3.0 收尾。
源码初版已保存为可恢复补丁，并从当前运行路径撤下；不是删除成果，也不是 0.3.0 已交付能力。
现役报告在后续 01–04 收尾后使用 `echo-report.v0.17`／`echo-analysis.v15`；
这个 v0.17 用于撤下独立偏好词及句长／连续发送投影，与已保存回复原型当时的 v0.17 内容不同。

## 保存物与恢复

- [完整源码补丁](deferred/reply-relations-0.4.0.patch)：22 个文件的来源、模型、应用、展示、测试及两份合同文档变更；含五个新增文件。
- [恢复校验清单](deferred/reply-relations-0.4.0.manifest.json)：原型基线 HEAD、补丁 SHA256，以及恢复后每个文件统一 LF 的 SHA256。
- 保存时已验证反向应用、正向 `git apply --check`，并在独立源码目录实际恢复全部文件、逐文件比较清单。
  补丁不包含 CNB 分发、卸载清理或其他任务的修改，不包含真实聊天、配置、账号和密钥。

继续开发时先按 DEVELOPMENT 核验工作区和解释器，在获准的工作分支中检查：

```powershell
git apply --check docs/deferred/reply-relations-0.4.0.patch
```

**检查通过后再应用** `git apply docs/deferred/reply-relations-0.4.0.patch`。
0.3.0 后续排版等变更可能使上下文失效；失败时按下表在各 owning layer 手工重接，
不要强制覆盖当前文件或整文件恢复旧模板。清单证明保存时的完整性，不要求未来源码回到旧哈希。
恢复后的 schema／分析修订需根据当时基线重新分配，不能机械回退版本号。
尤其不要恢复已在 0.3.0 撤下的偏好词／句长小字和关联原话；先核对当前语言投影，
只恢复回复关系需要的共享原话构建能力。

本机另保留 `build/previews/reply-relations/` 的虚构 QQ／微信离线预览与宽窄屏截图；
这些是可重新生成的本地产物，不是补丁恢复的前提。此前含回复功能的本地候选包属于原型，
不能作为撤下回复关系后 0.3.0 源码的构建验收证据。

## 已打通的路径

| 层 | 文件／入口 | 恢复要点 |
| --- | --- | --- |
| QQ 来源 | 既有 QQ Adapter → `ReplyRelation` | 沿用核实的同群序号关联，不新增实时采集或旧运行时 fallback。 |
| 微信读取 | `providers/wechat_database_provider.py` | 仅群聊白名单加入完整 `local_type=244813135921`；消息读取、日期边界使用同一白名单，私聊不扩大。 |
| 微信解析 | `wechat_db_adapter.py` | appmsg/type=57；正文只取作者的 title。svrid 对应目标 server_id，fromusr 是群、chatusr 是目标作者。无合法 server_id 用 `local:` 命名空间，引用方无合法 ID 不授予关系。 |
| 关系模型 | `rich_message.py` | `ReplyRelation.target_sender_id` 仅存在于本地，供核对来源声称的目标作者。 |
| 分析 | `analysis/group_replies.py` → `AnalysisReports.group_replies` | 对同次保留 Rich／普通投影配对计数；仅唯一 ID、可靠双方、同群、严格更早的目标。自引与无法定位独立计数，拒绝同秒、逆序、重复和作者不符。 |
| 应用 | `application/analysis_service.py` | 质量过滤与范围选择后构建；保留序号同时用于词语原话与引用原话，不能以未过滤源行号代替。 |
| 安全投影 | `presentation/group_replies.py`、`language_sources.py`、`models.py` | 只输出称呼、次数、报告内序号及已保留原话；不输出源 ID、XML 快照、原始证据对象。 |
| 离线展示 | `echo_replies.py`、`echo_language.py`、模板与 serializer | 第六章有向组合；点击复用只读原话面板，先目标、后本次回复；预览三组、完整每批十组，选择复制及关闭恢复焦点／阅读位置。 |
| 回归 | `test_group_replies.py`、`test_wechat_group_replies.py` 等补丁内测试 | 虚构 QQ／微信正式导入 → 过滤 → 分析 → JSON／HTML；时间过滤、来源拒绝、私聊隔离、纯文本安全及浏览器分页。恢复时同时补回 conftest 域注册。 |

## 已有证据与下一步

本机受控微信样本的四条引用、两个方向各两条，已通过正式 Provider／Adapter／质量过滤在内存中核对；
覆盖连续引用、重复目标、表情包目标。真实数据没有进入自动化样本或补丁。
完整来源与当时验证见 [审查记录第 7 节](LANGUAGE_ORIGINALS_AND_REPLY_AUDIT.md#7-qq微信群聊明确引用初版2026-10-29)。

恢复时重新执行来源、分析、应用、展示与离线浏览器定向回归，并复核当前过滤、序号及 schema 接口。
此前的本地 Frozen／Setup 构建和虚构原生 WCDB 回归只证明保存时的初版；
仍需恢复后真实 GUI 新报告审核、最终候选安装升级／卸载及跨机器验收。
未实现群聊 @／拍戳、私聊引用、完整引用链或关系评分，不因恢复补丁自动扩大范围。
