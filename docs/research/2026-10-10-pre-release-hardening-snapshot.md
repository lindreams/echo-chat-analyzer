> **历史快照：** 以下正文保留 2026-10-10 发布前工作地图的原始内容，不再作为 v0.1.0 发布后状态。当前事实请看 [docs/HARDENING.md](../HARDENING.md)。

# Echo Hardening 工作地图

> **唯一定位**：本文是 Echo「上线前 Hardening 阶段」的唯一实时工作地图，同时承担 Active Bug Backlog。
> 不要再单独创建 `bug-backlog.md`。
> 架构事实源：`ARCHITECTURE.md`；语义事实源：`DATA_SEMANTICS.md`；
> 已解决的真实工程问题：`docs/BUG_JOURNAL.md`；QQ Direct DB 研究证据：`docs/research/`。

Echo 已过「先证明有没有人愿意用」的阶段。当前目标是修复阻塞问题、稳定 QQ / 微信主链、
保证分析可信、完成数据生命周期与分享闭环、改善关键 UX，并在真实机器 / 真实数据上验收。
默认不新增大型功能或新数据来源。

**交付层级（统一口径）**：

1. **代码实现完成**：须注明在工作树、分支提交还是 `main`；只有已进入 `main` 才称为已合入交付。
2. **自动化测试通过**：对应 focused / Fast / Full 层级通过（须注明层级与时间）。
3. **Frozen 发行包通过**：在新鲜构建的 Frozen / Portable 包上通过合同与启动验收。
4. **真实用户验收通过**：在真实机器、真实数据上完成端到端验收。
5. **正式发布完成**：对应源码、tag / Release 与最终发行资产已公开交付。

五者分别记录；低层级完成不得用于关闭更高层级待办。

校准基线：2026-10-10，`origin/main = 003a689b06992e2caade01d41b6912c52365c05e`。
当前 `integration/napcat-convergence` 包含该 main，领先 3 个提交；RPC 客户端认证、
staging 输入强见证与 G2 telemetry patch 移除已在分支提交，尚未合入 main。
Worker `boot_id` 代际隔离、显式重连、NapCat 4.18.33 升级及两个连接归属 P1 修复
已在工作树实现，尚未提交。2026-10-10 本工作树 Full 已通过（3898 passed、32 skipped、0 failed；
沿用上一轮结果，本次文档检查未重跑）；跳过项不算验收通过，Frozen / 真人与正式发布仍未完成。
（历史校准、逐次 checkpoint 与旧测试数字已移除以降低维护成本；需要时见 Git 历史与
`docs/BUG_JOURNAL.md`。）

## Release Blocker 与待验收清单

| 条目 | 状态 |
| --- | --- |
| REL-06C NapCat 升级与兼容性 | **Release Blocker：Yes**；集成工作树已适配 4.18.33、Worker 代际与显式重连，两个连接归属 P1 已修复，Full 已通过；升级与修复尚未提交 / 合入，最终 Frozen / 真人验收未完成 |
| REL-08 分析结果分享闭环 | **源码功能已合入；分享体验优化 DEFERRED**（与报告内容后续一并优化）；最终基本可用性纳入 QA-01 |
| REL-06 Windows Portable ZIP 发布 | 未完成：v0.1.0 只交付 Windows Portable ZIP（不开发 Setup 安装器）；REL-06B 已合入 main（PR #24），整合版最终发行验收未完成 |
| REL-07 GUI 最终 polish | **源码功能收尾完成**（含 `9a81d5b`、`b5413dd`、`e820579d`）；仅保留最终真实使用 / Frozen 验收，不再作为独立功能开发阻塞项 |
| QA-03 GitHub Release | 未完成：需核对 tag / 发布说明 / fresh build 资产后发布 |
| QA-04 新版本检测 | Core 与 GUI 手动检查已合入（PR #27）；待最终视觉与真实交互验收 |
| QA-06 跨机器 Direct DB RC | 待真实验收 |
| QA-01 最终真实验收 | 未完成（见下） |
| 版权 / 第三方分发合规 | **许可与 NOTICE 专项已有实施结果**（仓库已包含 MPL-2.0 `LICENSE` / `NOTICE.md`）；仍需最终发行包资产与第三方许可复核，不重复开展专项开发 |
| GUI native access violation | 既有偶发现象，尚未证明修复；纳入 QA-01 稳定性验收，出现复现证据再专项处置 |

已合入 main、非阻塞（**源码功能完成**，不代表发行 / 真人验收）：报告历史浏览与批量删除
（PR #26、`b9c42de`、`fec51e9`）、微信会话排序修复（`f264ae0`）。
算法质量 v5（`347d298`）、QQ 表情资源与文字兜底（`b9f39d6`）、群语言画像双列布局
（`479246c`）已随 `003a689` 合入 main，当前分支也包含这些成果。
测试生命周期与 editable metadata 兼容修复（`4ffbe19`、`3a7e335`、`8b3b546`）同样已合入。
`fe4e07a` 的集成验收记录保留其当时的环境失败事实，不代表当前工作树 Full 仍失败；
测试修复与本轮通过也不能证明 GUI native access violation 或最终发行验收已关闭。
NapCat RPC 客户端认证与 REL-06C 升级已在集成工作树实施，两者尚未计入 `main` 交付。

## Active Bugs

### GUI native access violation（待定位风险）

微信 GUI worker 曾出现 native access violation；重跑通过，根因未确认。
状态为待定位风险，不得声称已修复；纳入 QA-01 最终稳定性验收。

## 未完成交付条目

### REL-06 Windows 普通用户发布（Portable ZIP）

- **REL-06B Portable ZIP / 运行目录分离**：已合入 main（PR #24）。
  `scripts/package_windows_portable.py` 提供 ZIP + SHA-256 包装（包裹已有 build，不执行 fresh build）；
  QQ managed runtime 区分程序目录 / 用户运行目录 / Direct DB transient 目录，安装目录只读。
  **独立工作树 Frozen 实机验收已通过；最新 main 整合版的最终发行验收未完成。**
- **REL-06C NapCat 升级与兼容性**：Blocker：Yes。工作树已升级正式来源与 pin 至 4.18.33，
  自动化 Full 已通过，尚未提交 / 合入 main；最终验收仍须覆盖 Echo patch / plugin、
  启动登录、QR freshness、会话读取、main + WAL snapshot / decrypt、
  分析、退出清理与异常恢复，并在最终 Frozen / ZIP 包上验收。
- **v0.1.0 交付形态**：首次发布**只提供 Windows Portable ZIP**，不开发 Setup 安装器；
  Setup 安装器与原地覆盖更新机制一并延期，后续作为**同一独立专题**统一设计。

仍需（必须在**整合版**上）：正式 fresh Frozen build、Portable ZIP 解压运行、
只读安装目录与发行目录不承载运行状态的验证、完整退出生命周期、异常恢复与清理验收。
不得用源码环境通过或虚构恢复测试关闭上述待办。

### REL-07 GUI 上线前最终 polish

只处理明显影响体验的视觉 / 交互问题，不重新设计 GUI。
已合入 main：Home、QQ / 微信引导、会话工作台与琴键回响、Processing 原生书本动画（PR #21）、
「关于余音」更新入口（PR #27）。
GUI 收尾提交包括 `9a81d5b`（整体 / Local Data polish）、`b5413dd`（QQ 二维码等待与取消）、
`e820579d`（QQ / 微信连接交互）。不再将旧版视觉待办默认视为未开发；
仅保留最终 fresh Frozen / Portable、真人视觉与稳定性验收。
微信消息数量排序的高效可信计数来源留作后续优化。

状态：**源码功能收尾完成；最终发行验收待做**。

### REL-08 分析结果导出 / 分享闭环（后续体验优化 DEFERRED）

需要验收整条用户链：

```text
分析完成 → 用户发现分享入口 → 生成 → 明确生成状态
→ 找到结果 → 可以发送 → 接收方无需安装 Echo 即可理解结果
```

`d67f51e` 已合入 main：有结果时显示 / 启用分享按钮，经 Facade 生成图片并展示状态、尝试打开图片。
用户决定现有分享能力先保持当前状态，分享效果及内容随报告优化后续处理，**不再将体验完善列为 0.1 独立 Release Blocker**。
正式交付时的基本分享可用性仍纳入 QA-01 验收，不宣称完整真人闭环已通过。

### 版权 / 第三方分发合规

专项已实施 Echo 自有源码 MPL-2.0 许可文本、`NOTICE.md` 和发行复制契约；
`third_party/napcat/NOTICE.md` 保留 NapCat 第三方边界。**不再把已完成的许可补齐工作列作待开发事项**。
NapCat #2096 答复的历史上下文是 4.18.18 集成方案，不能自动扩大为 4.18.33 或第三方组件的
全面授权结论；MoeHoo、napi2native、`ffmpeg.dll` 与 PTY prebuilt 精确构建来源等证据缺口仍保留。
最终生成发行包后仍须核对实际随包资产、第三方许可与声明（含 NapCat、微信 native、字体 / 图形及官方表情资源排除情况）。
仓库声明或 hash 校验不能单独代替最终发行分发合规结论；不作法律结论。

### QA-03 版本号 / GitHub Release

统一版本权威（见 GOV-04），核对最终版本、tag、发布说明与 fresh build 资产后完成 GitHub Release。
历史 portable 验收不等于正式 Release。**未完成，发布前必做。**

### QA-04 新版本检测与下载页

内置权威版本 → 检查 GitHub 最新正式 Release → 提示新版 → 打开官方下载页，由用户自行下载；
**不做自动下载、替换或静默更新**。Update Check Core 与 GUI「关于余音」手动检查均已合入 main（PR #27）。
更新服务支持**非手动检查的 24 小时去重**；但 v0.1.0 GUI 只提供手动检查，
**启动或打开关于对话框时不自动联网**。**待最终视觉与真实交互验收。**

### QA-06 跨机器 Direct DB RC

在其他 Windows 机器验证 NapCat 启动 / 登录、Direct DB snapshot / decrypt、分析报告与退出清理；
本机通过的 checkpoint 不替代此项。**待真实验收**，并纳入 QA-01。

### QA-01 最终真实验收

上线前完成一次独立 Final Acceptance，覆盖：QQ 主链、WeChat 主链、private / group、
小数据 / 普通数据 / 大数据、Echo Report、History / local data、export / share、portable build、
陌生 Windows 机器、真人实际使用。

完成条件：不存在已知 P0 / P1 恶性问题；连续一轮真实验收不再出现新的 Release Blocker。
流程：

```text
Feature Freeze → Bugfix Only → Final Build → Release
```

## Deferred / 非阻塞

### 0.2 Backlog（已确认范围）

- Sticker / 表情包完整语义：现役 QQ Direct DB / WeChat 的完整身份、资源与语义支持；
  已有基础映射保留。已退休的 BUG-02 / QCE `type_17` 不属于后续兼容待办。
- Reply / 引用回复分析：已有 ReplyRelation 与 authored text 隔离不等于完整回复分析已交付。
- 快捷登录 / 统一 UX 优化：现有授权闭环不等于快捷登录完成，不阻塞 0.1。

### Setup 安装器与 Windows 原地覆盖更新（统一延期）

v0.1.0 **不开发 Setup 安装器**，也**不实现** Windows 原地更新器；首次发布只提供 Portable ZIP。
两者作为**同一独立专题**在后续统一设计，且必须满足：

- **固定有效安装位置**（不依赖运行目录漂移）；
- **原地替换**：在原安装位置完成替换，不产生第二套并行可运行的安装；
- **单套有效安装**：替换后旧版本不可再被启动；
- **完整组件替换**（可执行文件、运行时资产、依赖），不允许部分更新留下混装；
- **保护用户数据**：更新不得删除或破坏用户报告与本地数据；
- **升级失败可恢复**：失败可回到更新前的可用状态，不留下不可用安装。

自动下载、安装或覆盖在 v0.1.0 亦明确不支持（见 QA-04）。

### 非阻塞后续优化

- **CAP-01**：更完整的图片 / 语音 / 视频 / system message 分析。
- **CAP-02**：Rich Model 最终迁移、逐步减少 legacy projection。
- 分享图片/入口体验与报告内容一并优化；不在 0.1 前单独重做 REL-08。
- 其余方向：AI 内部梗、语言趋同、表达变化趋势、更复杂关系推断、新数据来源、大型智能过滤框架升级。
- **REL-05 大型数据容量与 UX**：先按 QA-01 验收，有新证据再决定是否专项优化。DEFERRED，Blocker：No。
- **REL-09 语言画像语义 / 代表词算法分工**：`top_words` 更接近「常说什么」，
  `DistinctiveWordAnalyzer` 的 log-odds 更接近「哪些词更像 TA」，后续优化优先复用；
  数据不足时允许不展示特色词。DEFERRED，Blocker：No。

## 关键约束与长期事实

- **QQ 正式链**：NapCat → Direct DB → `qq_db_adapter` → 统一消息模型 → Analysis。
  QQChatExporter / QCE 的 runtime、provider/service、CLI 命令、QCE JSON 与旧 QQ JSON/JSONL 兼容
  均已退休，**不存在 QCE fallback**；保留 retirement / forbidden 检查以阻止能力复活。
  `echo-chat` 仍是当前支持格式的本地文件分析入口。
- **报告生命周期 / 本地数据语义**：Report Package 是唯一持久分析对象（四文件，`metadata.json`
  驱动 catalog）；独立 JSONL history（`ReportHistoryManager` / `analysis_history.jsonl`）已退休。
  报告**不自动淘汰**，只由用户在 Local Data 显式删除（删除所选 / 保留所选删除其余 / 删除全部）；
  删除目标仅为完整自有 package，不触碰 QQ / 微信原始数据或用户另存文件；
  无法安全统计的 package 标记为 unmeasured，未知占用不得记为零。
  QQ raw acquisition 是一次性 transient lease，正常 / 异常结束后清理。
  细节以 `ARCHITECTURE.md`「Report Package 生命周期」与 `DATA_SEMANTICS.md` 为准。
- **版本权威（GOV-04，CLOSED）**：`pyproject.toml` 的 `0.1.0` 是唯一发布版本事实源；
  `version.py` 读取安装元数据，GUI 与报告 metadata 共用；frozen build 校验并携带安装元数据。
- **构建可复现（GOV-05，CLOSED）**：`scripts/build_windows_exe.ps1` 使用项目 `.venv` 的 PyInstaller，
  缺失时 fail closed；toolchain 在 `pyproject.toml` 的 `build` extra 精确 pin
  （`pyinstaller==6.22.3`、`pyinstaller-hooks-contrib==2026.8`），新 clone 见 `DEVELOPMENT.md` §3.1.1。
- **发布树防护（QA-02，CLOSED）**：`scripts/windows_runtime_manifest.json` 的
  `releaseTreePrivatePaths` 断言发布树无 logs / 诊断残留；WeChat native 资产
  （`WCDB.dll` / `wcdb_cli.exe` / `wx_key.dll`）SHA256 pin 在 source 与 portable 两阶段校验；
  NapCat 关键产物 hash 前后校验。最终候选包仍需重核。
- **Frozen provenance（GOV-05.2，未实施 provenance framework）**：Final Release / packaging acceptance
  必须先执行正式完整 fresh build，**不得用历史 `dist/Echo` 代表当前源码**。
- **0.1 → 0.2 兼容（QA-05，CLOSED）**：`echo-report-meta.v1` 只允许 additive 可选字段，
  旧包缺字段仍可 list / reopen / 统计且不补写；历史分析快照不随 app upgrade 自动迁移或重算；
  新算法 / 数据库字段由新版重新 acquisition / analysis 生成新包。
- **确认不在 0.1 范围**（人工确认）：dependency lockfile、CI/CD、bit-for-bit reproducibility、
  code signing、EXE VersionInfo、commit marker / provenance framework。

### 已关闭 Bug 的根因索引

- BUG-03 本地数据 / 报告生命周期 → `docs/BUG_JOURNAL.md` Journal 011。
- BUG-05 WeChat 英文官方表情别名污染语言画像 → Journal 003。
- BUG-06 WeChat shard rollover + unlimited sentinel 截断 → Journal 007 / 008。
- BUG-07 Direct DB 偶发 `database disk image is malformed`（历史 main-only 路径未含 committed WAL；
  正式链路已改为 hardened main+WAL acquisition，在固定 SHM committed boundary 内校验、合并、再解密，
  无法证明一致性时 fail closed）→ `docs/research/2026-09-29-qq-direct-db-malformed-root-cause-and-a4-audit.md`。
- BUG-08 微信会话读取失败仍停留 loading →
  regression `tests/test_gui.py::test_wechat_session_load_failure_exits_reading_state_and_allows_restart`。
- BUG-01 / BUG-02 → RETIRED（旧 QCE 路径；退休不等于根因已被修复或确认）。

## 已完成治理（仅结论）

- GOV-04、GOV-05、GOV-05.1、GOV-06（Architecture & Complexity Audit v1）、QA-02、QA-05、
  REL-02、REL-03、REL-04（用户安全错误提示）、DOC-01、DOC-02、GOV-01、GOV-02、GOV-03、
  QCE Final Retirement：**均 CLOSED / COMPLETE**。
- GOV-06 已完成 Desktop QCE → NapCat + Direct DB 主链收敛、GUI ownership / lifecycle 审计、
  RichMessage / message 一致性、QQ / WeChat source topology 与模块归组、可读性整理；
  0.1 不再重复开展泛化全仓架构审计，发布前定点核验归 QA-02 / GOV-05。
- 报告历史浏览 / 批量删除（PR #26、`b9c42de`、`fec51e9`）与微信会话排序修复（`f264ae0`）已合入 main。
- **QQ 启动前退出引导**已实现并完成实际验收；该验收不等同于最终 Frozen ZIP 全链路验收。
- 测试治理 v1 的详细历史见 `docs/engineering/TEST_GOVERNANCE_V1.md`。

## 状态词

统一使用：

- 未审计 / 审计中 / 已审计 / Ready for RED / 实现中 / 待真实验收 / CLOSED / DEFERRED /
  RETIRED（旧条目退出当前追踪，不声称根因已修复）

同时允许：候选 Bug；Release Blocker：Yes / No / TBD。

## 工作规则

每个 Bug / Improvement：

```text
现象与证据 → 调用链学习 → 只读调查 → 竞争假设 → 最小诊断 → 根因 / 设计判断
→ RED → minimal GREEN → focused → Fast → 必要的 focused integration / Full
→ 真实验收 → CLOSED
```

原则：一项一个分支；不在已完成分支继续无关工作；真实 Bug regression 优先永久保留；
不为测试变绿篡改需求；不上传真实聊天记录；每解决一个重要问题，同时形成一次「项目链路学习」。
