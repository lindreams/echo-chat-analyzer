# QQ 54395 可信数据来源调查与原型审核

日期：2026-11-14。分支：`spike/qq-independent-source`。
本阶段从解密算法转向输入来源；仅授权审核研究文件、最小完整性拒绝修正与公开资料调查。

## 结论与停止位置

**在本轮核对的公开证据中，尚无同时具备版本、数据来源及读取条件证明，
可按当前边界开展实际验证的 Windows QQ 9.9.37-54395 数据来源。**
这不是证明该版本不能独立读取；现有算法互操作证据也不能补上输入来源证据。
当前停止真实端到端验证，不启动账号实验，不开发或执行自动取钥，不增加虚构样本数量推进结论。

仍值得保留的方向是：来源清楚的 54395 受控加密库与合法匹配密钥，
或用户主动提供、可证明确由该 build 导出的结构化消息。
**两者目前都缺少可采用的具体输入**，不据方向合理性批准实施。

## 1. 上轮四个文件的审核与必要修正

| 文件 | 审核事实及本阶段处理 |
| --- | --- |
| `scripts/spikes/qq_independent_codec.mjs` | 独立候选 profile 编解码；上轮仅增加导出接口与 CLI 运行判断。没有发现进程、账号或配置读取。此次只增加认证后 SQLite 页数拒绝检查 |
| `scripts/spikes/qq_sqlcipher_reference.cpp` | 小型测试 SQL 执行程序，使用官方 WCDB 类型；不是 QQ 客户端 helper，没有发现取钥、注入或保护相关实现。本阶段未修改、未重编译 |
| `scripts/spikes/qq_sqlcipher_crosscheck.py` | SQLCipher 自产虚构库，双向互读与标准 SQLite 检查有效。此次改变截断预期、补充不可信页数拒绝，并要求原生负向结果是程序明确的 SQL 错误，进程崩溃或启动失败不能算认证拒绝 |
| `docs/research/2026-11-14-qq-sqlcipher-crosscheck.md` | 实验范围、参照实现、历史结果均与源码及现有 `result.json` 一致。保留原始缺口记录，增加到本报告的指引；没有将 54395 写成已支持 |

审查使用的 C++ 源码 SHA256 为
`37fe0b447cab46f08553383ded73ee94268338f95dc4a103ccb7aa456fda303f`，
已有本地编译程序为 `fe57f6f58549418dc235e1def8cd950c5f8b4aafaf4efe6c808c9a57d7d5453d`；
其旁 WCDB.dll 仍与发行清单固定 SHA256 一致。没有运行社区下载的二进制。
研究 helper 接收受控 SQL、可以写虚构数据库，不是面向用户输入的安全数据库入口。

### 截断修正的证据与边界

修正前用上一轮已有虚构加密样本复现：页头声明 10 页，文件只剩 9 页，
页头 change counter 与 version-valid-for 相等，原型仍成功返回明文。
根因是按输入长度认证剩余页，没有验证已认证页头里的数据库大小。

修正不重写算法：全部现存页认证完成后，读取 SQLite 页头 offset 28 的页数；
仅当其非零且 offset 24、92 的计数相等时才信任，再与实际页数比较。
不可信计数报 `untrusted_page_count`，页数不匹配报 `page_count_mismatch`；
调用方在函数成功返回后才写文件，因此拒绝时没有明文发布。
依据是 [SQLite 数据库文件格式 §1.3.7](https://www.sqlite.org/fileformat.html#in_header_database_size)。
这里故意比通用 SQLite 严格：不对旧式/过期页头按文件长度 fallback，不修计数、不补页、不跳坏页。
它只保证本候选 main-only 读取的页数前提，不能证明没有缺失 WAL 或历史消息。

沿用原有 10 页、24 行的小实验复核：

- 完整库：两个互读方向、raw-key+salt、逐页损坏、错钥及错误参数拒绝仍成立。
- 缺最后一整页：codec 在输出前拒绝；独立截短的明文也被标准 SQLite 完整性检查拒绝。
- 认证正确但 header counter 过期：codec 拒绝，不猜测完整性。
- 完整明文仍执行 `PRAGMA integrity_check`，并逐条核对正文/BLOB；没有以页数检查替代它。

最终驱动结果：`whole_page_truncation="codec rejects before output; standard SQLite also rejects"`、
`untrusted_page_count="rejected"`、`qq_54395="not_tested"`。
没有新增 pytest 文件、依赖或通用测试工具，没有重跑 Provider → Adapter → 报告闭环。

## 2. 独立历史数据库案例：哪些证据确实与 54395 匹配

调查将三类证据分开：工具源码有能力、作者声明某版本成功、可核验的当前 build 输入与结果。
只有第一类不能推出后两类。更新日期晚于 QQ 发布也不能证明工具测试过这个 build。

| 一手材料及固定版本 | 历史数据与密钥来源 | 对 54395 的判断 |
| --- | --- | --- |
| [QQDecrypt Windows 验证记录](https://qqbackup.github.io/QQDecrypt/decrypt/extract/NTQQ%20(Windows).html)；文档提交 `4cc0912c92dcb1edcc799127e56178c60a7b7cdc` | 记录原始库/key 获取，明确确认 9.9.32-51246 | 不是 54395 成功案例 |
| [qq-nt-export README](https://github.com/q957506633/qq-nt-export/blob/bec1504170f99e2752793320711c5653f3803670/README.md) | 进程外内存扫描凭据，再解密历史库；声明实测 9.9.35 | 不是 54395 版本匹配证据；本阶段没有运行或研究绕过措施 |
| [x_key_scanner README](https://github.com/QQBackup/x_key_scanner/blob/d864bc466097666a034ee207a9808f95f7689c14/README.md) | 独立小工具，声称从已登录进程取得 raw key，可导出副本 | 未附可核验 54395 DB/key 配对、模块哈希和全库结果；固定树/API 未见 LICENSE，不能直接作为已获许可的可复用代码 |
| [qq-dump README](https://github.com/miniyu157/qq-dump/blob/22533d048602dbf5594a1fec9b443ec54e70230b/README.md)及[验证边界](https://github.com/miniyu157/qq-dump/blob/22533d048602dbf5594a1fec9b443ec54e70230b/test/README.md) | Windows/Linux 有内存扫描入口和离线 key cache；数据库历史导出，不仅是实时消息。作者说明算法流程参考 x_key_scanner，声明自身 MIT | 新的 Windows 候选资料，但未见 54395 对应运行结果与输入来源；虚构契约测试不触发真实取钥，不能当该 build 通过。上游许可及来源还需单独澄清 |
| [nt_msg_db_util README](https://github.com/QQBackup/nt_msg_db_util/blob/317024ce2c5e3482fdf9f310a5a7159ab4927e34/README.md) | 个人长期历史库的解析与导出成果，已有 key 为前提；还包含坏页跳过/精简能力 | 历史解析成果真实有价值，但不是本任务可采用的 54395 专用受控输入；容错、精简不纳入 Echo 原型 |

通过 GitHub API 对上述相关仓库定向检索 `54395`，并对 qq-win-db-key、qq-dump 检索 `9.9.37`，
没有找到补齐“当前版本＋密钥来源＋独立读库结果”的 issue。
扩展检查了 BAK、ChatLab、QQNT 导出工具的一手说明及源码树，不只复查前轮候选。
全局搜索含大量同号 issue 和无关结果；本结论仅限本轮可核验材料，不宣称穷尽所有社区或私下成果。
没有读取社区用户的数据库附件、账号配置或聊天样本。

本轮确实读到了当前 build 的故障记录：
[QCE #719](https://github.com/shuakami/qq-chat-exporter/issues/719)注明 Windows 11、54395、QCE 6.3.2 的启动失败；
[SnowCat #73](https://github.com/DandanLLab/SnowCatQQ/issues/73)报告同 build 启动失败，维护者将其登记为待复现问题。
这些只证明存在运行兼容故障反馈，**不能据此诊断数据库格式改变、密钥算法改变或独立读库不可能**。
本阶段不追踪相关注入、保护或修复方法。

## 3. 官方/用户主动导出、恢复、转换能否解除阻塞

### 官方产品入口

[QQ Windows 官方页面](https://im.qq.com/pcqq/)本轮可以抓到页面内容，但静态抽取的版本占位仍为旧值，
不能用于确认 54395 的导出格式。社区更新日志对“导出到电脑”的转述只作为找入口线索，
不是输出为 JSON/TXT 或本 build 可离线转换的证明。

腾讯发布的 [QQ 隐私保护指引 §6.1](https://private-70457.njc.vod.tencent-cloud.com/3f1b9192-8b71-11ef-a0fe-eeb9d133b947)
说明查询和复制个人信息的产品入口及反馈渠道；该材料为 2024 年版本，
没有承诺 54395 提供完整历史聊天 JSON/CSV 或数据库 key。
不能把信息查询权/产品入口写成已经取得聊天档案的技术方案。
若由用户主动向官方申请结构化导出或专用研究样本，仍需官方答复和实际格式证据；本轮未发送请求。

### 不混用不同 BAK 与导出物

| 输入/途径 | 当前可支持的判断 | 仍缺什么 |
| --- | --- | --- |
| 旧 PCQQ 官方 TXT/MHT | 可以承载既有历史消息；[ChatLab 的导出指南](https://github.com/ChatLab/ChatLab/blob/c258a139d323e0743ff06d82d915a726d1c2a733/docs/cn/usage/how-to-export.md)明确把原生 TXT 标为旧版 QQ | 不能推出 54395 可导出相同格式；不恢复 Echo 已退休的旧 QQ 导入功能 |
| 旧 PCQQ BAK → 官方导入 | 可以是用户主动恢复历史记录的操作；[qq-bak-chat-history-export 的实际流程](https://github.com/zywstudy123/qq-bak-chat-history-export/blob/5516ccb6f582c0ab87997fe3f2cdb67433b3dd0d/README.md)仍是导入 → 本地库 → 另行解密 → JSON/CSV | 未消除本地库的 key 前提；项目名字不等于存在独立 BAK 解码器 |
| 手机备份 BAK | [qqnt-chat-decrypt](https://github.com/fnyfree/qqnt-chat-decrypt/blob/a73ec7d0b576dbb67e13536d3641530d8fa640f9/README.md)描述官方恢复后再导出本地库，并指出备份 key 可能独立 | 是其他平台的社区观察，不能证明 Windows 54395 的导出包相同或可无钥读取；本轮不扩展手机开发 |
| 当前 Windows 的“导出到电脑”产物 | 可以保留为待确认的产品入口 | 缺 54395 原生导出物类型、字段、许可及虚构示例；不因扩展名叫 BAK 就套用旧格式、ZIP/MSG0 或 SQLCipher 假设 |
| 用户主动提供明文 SQLite / JSON / JSONL | 来源、授权和 schema 都清楚时可以成为离线研究输入，用户无需交出进程访问权 | 仍需生产该文件的工具/版本、原始消息清单、转换与过滤说明；“结构化”不保证完整，也不自动证明来源是 54395 |

官方恢复和客户端正常显示历史是有意义的恢复能力；它们不自动给 Echo 一个独立可读文件。
本轮没有找到一个可核验的“54395 原生导出 → 无取钥独立转换 → 完整结构化消息”案例。
不采取降级登录旧 QQ、跨端换密钥或将私人数据交给在线转换服务等替代动作。

## 4. 社区能力分类：历史导出、实时收发和旧库不能混为一谈

| 方案 | 实际类别 | 当前采用判断 |
| --- | --- | --- |
| [Tealina28/QQNT_Export](https://github.com/Tealina28/QQNT_Export/blob/766888be69685d00d088e2988c0497ef26fc7f56/README.md)，GPL-3.0 | 真正的历史数据库消费者；明确要求先解密。部分版本可输出 ChatLab JSON/JSONL | 下游转换参考，不提供当前 build 的钥匙或输入来源 |
| [star-picker/QQNT-Database-Export-Tool](https://github.com/star-picker/QQNT-Database-Export-Tool/blob/9c140c11eaafe77068103d0989433a61a7219f47/README.md)，AGPL-3.0 | 已解密历史库导出，或用外部 key 配置调用 SQLCipher。README 还引用旧的 key 计算材料 | 不能据其通用说明宣称 54395 的 key 可计算；没有运行仓库携带的 exe |
| qq-dump、nt_msg_db_util、qq-nt-export | 历史库读取/转换；获取条件不同，后两者有较早版本或长期库的成果 | 有技术价值，缺本 build 可信输入；不照搬坏页跳过或明文 key 缓存行为 |
| NapCat/SnowCat/QCE 类型的客户端框架/导出器 | **并非都只能实时收发**。SnowCat 的[群历史源码](https://github.com/DandanLLab/SnowCatQQ/blob/1c3d85fe4bcb11856d62dd963d74c5e6d7d93704/packages/snowcat-onebot/action/go-cqhttp/GetGroupMsgHistory.ts)与[私聊历史源码](https://github.com/DandanLLab/SnowCatQQ/blob/1c3d85fe4bcb11856d62dd963d74c5e6d7d93704/packages/snowcat-onebot/action/go-cqhttp/GetFriendMsgHistory.ts)确实调用客户端 MsgApi 历史接口 | 历史接口存在不证明所有历史都可追溯或 54395 完整实测；仍依赖被排除的客户端框架，不作为独立路线，不恢复 QCE |
| 只订阅事件并从启动时积累消息的机器人/桥接日志 | 实时收集；只有接入以后实际看到的消息 | 不能据收发成功声称恢复接入前的桌面本地历史 |
| [腾讯官方 botpy](https://github.com/tencent-connect/botpy/blob/e25f3e84bad7217357d8200a9d12939b58285b84/botpy/api.py) | 官方 bot/频道 API。源码存在按频道和消息 ID 取指定消息等能力，因此不绝对称所有 API 都无历史 | 未提供普通账号 54395 私聊/群聊本地数据库的全量导出入口；不是个人桌面档案来源 |
| ChatLab 分析与格式标准 | 导入/分析已有导出物；指南把 QQ 来源分成 QCE JSON/JSONL 和旧 QQ TXT | 标准便于交换，不会替生产方取得历史数据或 key |

代码许可仅决定代码是否可按相应条件使用，不给聊天数据、客户端访问或测试账号自动授权。
x_key_scanner 缺许可、QQDecrypt 自定义非商用许可，以及 GPL/AGPL 项目的复用条件均不能略过。
本轮只阅读和记录，未复制其实现进入 Echo。

## 5. 有可信输入以后，现有 Echo 距离完整验证还差什么

源码核对仍是以下边界：`scripts/qq_direct_db_snapshot/snapshot.mjs` 的获取入口依赖
`core.apis.DatabaseApi`、`selfInfo`、进程内 key revision；底层捕获和工作区安全能力可保留，
**不能把“现有安全快照存在”当成独立来源入口已经存在**。
当前独立 codec 接受候选格式的冻结 main 文件和已知 key，不拥有账号、密钥或活动快照的来源证明。

| 验证条件 | 最小需要的证据 |
| --- | --- |
| 版本与权限 | 官方 Windows 54395 的实际运行模块版本/架构/哈希，样本产生时间；提供与使用该虚构样本的授权；区分热更新后的模块与安装包标称版本 |
| 读取条件 | 原始加密字节、与同一代数据库匹配的合法 key 及获得方式；或不依赖 key 的原生结构化导出和格式证明。账号密码、包装元数据、其他数据库 key 均不能替代 |
| 输入完整性 | 冻结副本的大小、哈希与一致性依据；最小 main-only 实验要求正常关闭/检查点后没有待恢复提交。存在未合并 WAL 时不得静默丢掉它，也不在本轮新做 WAL |
| 54395 格式与消息语义 | 实际包装、加密 profile、schema/40800 与现有 Provider 的对应；已知私聊及群聊清单的 ID、时间、方向、正文/BLOB 逐条一致；正常重开后已存在的消息，证明读到历史而非仅即时事件 |
| 解密与接入 | 每页认证、可信页数、完整 SQLite `integrity_check`，再由现有 Provider/Adapter 分析；源文件不被改写，拒绝时不发布结果；不以报告生成成功代替清单一致 |

另外，现有通用 ChatLab JSONL 导入路径由微信解析器处理且标记 `platform="wechat"`；
显式 QQ hint 只接受 `qq-db-json`。因此不能承诺社区任意 ChatLab JSON/CSV/TXT
直接就是 Echo 的 QQ 数据源。若取得结构化导出，须先核对语义和现有入口，再由负责人决定是否授权转换；
本轮没有开发转换器、Adapter、GUI 或正式来源。

若将来上述条件落实，最小实验是一个仅含预定虚构私聊/群聊的小样本，包含重启前历史消息，
在不访问 QQ 进程的情况下读副本并与清单比对。若只获得明文导出，能验证的是该导出链路；
不能由此宣称加密数据库获取链路也通过。当前缺少前提，不执行该实验。

## 6. 具体缺失条件、交付和停止

目前必须补齐至少一条输入路线：

1. **数据库路线**：54395 版本可复核、仅含虚构内容的一致加密副本，加上获得方式明确且获准的匹配 key。
2. **导出路线**：54395 官方或明确授权的本地导出操作记录、结构化格式说明、完整字段及受控样本；
   如提供的是 BAK，还要有对应格式的可核验离线读取条件，不能绕回未解决的 key 前提。

两条路线都还需要历史消息清单、数据授权和本机处理边界。当前只有工具能力与旧版本/其他平台线索，
没有符合这些条件的输入；故本阶段结论为**阻塞，停止**。不把自行生成的加密库当成 54395 产生的样本。

审核与验证仅触及上述四个研究文件及本报告；对正式 `src` 和快照脚本只读。
上一阶段报告保留历史结果，当前结果在本页说明。按本次授权对研究成果显式列文件本地提交，
不合并、不 push。main 保持 `798e34b7effbd465532accbef863a1b50f655e2f`。
无关未跟踪 `Microsoft/` 原样保留。

使用现有 `.venv` 复核解释器、目标源码导入位置及依赖一致性；定向驱动、Node 语法检查和 diff 检查通过。
未补装依赖或处理 jieba，未扩张测试体系，未做 Full/Frozen/Setup/GUI 验收。
原任务忽略构建目录中的参照程序、虚构样本和本轮公开检索元数据原位保留供审核，
不提交这些资产、不进入 runtime；审核结束后由负责人决定处置。
