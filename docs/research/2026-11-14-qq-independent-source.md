# QQ 独立本地来源：可行性研究与虚构数据原型

研究日期：2026-11-14。目标版本：Windows QQ **9.9.37-54395**。
研究分支：`spike/qq-independent-source`，起点为本轮开始时的 main
`798e34b7effbd465532accbef863a1b50f655e2f`。
本文是研究交付，不是正式来源合同、版本兼容声明或施工授权。

## 1. 技术判断

**QQ 可以建立不依赖 NapCat／SnowCat API 的本地数据库读取链路；
但本轮仅证明候选格式和 Echo 下游接入可行，没有证明 54395 上的完整获取链路可用。**

证据最充分的是“已取得正确读取条件之后”的部分：社区已有 Windows QQNT
离线解密、消息字段解析及导出的源码；Echo 自己已经拥有明文 QQ Provider、
Adapter、统一分析和报告。本轮虚构数据库也通过了这些现役消费者。

**当前最大的前置障碍是：在授权边界内，可靠取得与 54395 目标账号、
目标数据库及其盐匹配的读取密钥，并证明其在该 build 上仍有效。**
普通用户能否完成这一步，比重新实现消息解析更影响方案是否值得产品化。
拿不到密钥时，知道 SQLCipher 参数并不能解开数据库。
这不是已经诊断出“54395 改了密钥算法”：本轮没有该版本的客户端实验，
不能给具体故障归因。

第二个门槛是**结果完整性**：main／WAL 一致性、大库锁页布局及身份元数据。
能打开 sqlite_master、导出少量文本、甚至明文 integrity_check 成功，
均不能单独证明读取的是完整、正确账号、正确时间边界的数据。

建议先研究“官方 QQ 正常运行、明确授权的进程外只读取钥、独立离线读取副本”。
先用已知测试密钥检验读取器，再决定是否授权取钥实验。
不建议现在建立新的客户端框架，也不建议先做 GUI 或改造现有 QQ 生命周期。

## 2. Echo 微信实现：可迁移的是职责与验证方法

本轮核对了实际源码，而非只根据架构图推断：

| 环节 | 微信现役实现 | QQ 可迁移／不可直接照搬之处 |
| --- | --- | --- |
| 找库 | `application/wechat/wechat_data_detector.py` 检查默认文档目录、客户端保存位置及注册表；按 session.db／message_*.db 布局提出候选 | 复用“发现不等于可读、多个账号不猜测”的方法；路径和账号目录规则需按 Windows QQ 实现 |
| 获得读取条件 | `wechat_setup_service.py` 编排位置、取钥与读前验证；`wechat_key_service.py` 经 Node／koffi 调用 wx_key.dll 的 Hook API，并拥有 helper 进程树和清理 | **微信也不是无取钥步骤的纯文件读取。** 不能把微信 Hook 当作 QQ 的授权或技术依据，DLL、函数签名与密钥语义均不通用 |
| 本地读取 | `providers/wechat_database_provider.py` 以子进程调用 wcdb_cli，用进程环境传递 WX_DB_KEY，实际验证数据库后查询 | 可复用本地 helper 的职责边界、结构化错误和不暴露密钥的原则；不应拿 QQ 密钥直接填入 WX_DB_KEY |
| 原生依赖 | `native/wcdb_cli/main.cpp` 通过 WCDB v2.1.15 API 设密钥、页大小、cipher version，只读打开；任意 SQL prepare 仍涉及内部 core handle | 当前 helper 没有 QQ 外层偏移、独立 HMAC／KDF 配置和 QQ 大库布局接口，**不是现成 QQ 读取器**；WCDB 内含 SQLCipher 不等于这个 CLI 可直接读 QQ |
| 消息转换 | Provider 输出原生行，`wechat_db_adapter.py` 生成 RichMessage，再单向投影 ChatMessage；来源服务把 payload 交给 ImportService／AnalysisApplicationService | 完整保留这条分层；QQ 使用自己的既有 Adapter，不复制微信 SQL 或消息字段 |
| 完整性与身份 | 微信消息 shard 全量发现、全局时间合并、末端 limit；本人身份按已证明的命名空间映射 | 思路可迁移，QQ 实际表、分区和本人身份来源必须另证；不能据微信流程宣布 QQ 安全可读 |

源码事实与限制：微信取钥的局部 generation、helper 所有权和 shutdown 证据
并不证明所有断开并发或 native CleanupHook 场景均已验收。
本研究不修补或扩展微信功能，也不将其实现当作 QQ 的完整安全模板。

## 3. 社区调查：哪些能力已经存在

以下区分“读过实现”和“上游自述”；所有第三方代码均只读，没有运行，
没有安装第三方包、下载可执行资产、修改 QQ 或读取私人配置。
固定 revision 便于复核，不表示该 revision 已经通过 Echo 准入。

| 项目／固定 revision | 读到的实现或明确边界 | 复用判断 |
| --- | --- | --- |
| [QQBackup/QQDecrypt](https://github.com/QQBackup/QQDecrypt/tree/4cc0912c92dcb1edcc799127e56178c60a7b7cdc) | 格式、表字段与平台教程；说明页明确确认 Windows 9.9.32-51246（2026-07-19），没有据此证明 54395 | 有价值的技术线索；根 LICENSE 为自定义非商用条款，不能当作宽松许可代码包 |
| [QQBackup/qq-win-db-key](https://github.com/QQBackup/qq-win-db-key/tree/5c643c39bdc65a7ce3ecc414052fdfd93d5f9107) | `scripts/windows/ntqq/windows_ntqq_get_key.ps1` 默认静态定位 wrapper.node 的取钥函数，再以调试器启动 QQ；不是普通进程外只读扫描器 | 不能因文件名含 Windows／get_key 就执行；调试启动路径不作为本轮实验；自定义非商用许可 |
| [QQBackup/x_key_scanner](https://github.com/QQBackup/x_key_scanner/tree/d864bc466097666a034ee207a9808f95f7689c14) | Rust 进程外读取、候选验证及 main／WAL 解密；README 声称支持 Windows／Linux／macOS。`src/crypto/decrypt.rs` 解密路径明确不逐页要求 HMAC，通过候选验证与完整解密是两回事 | 方向有价值；查询时树中未见 LICENSE，GitHub license 字段为空，不可直接引入。自述“低检测风险”不是 Echo 的安全证据 |
| [miniyu157/qq-dump](https://github.com/miniyu157/qq-dump/tree/22533d048602dbf5594a1fec9b443ec54e70230b) | Python 跨平台取钥；`cli/decrypt_db.py` 调 SQLCipher、处理 WAL，并针对约 1 GiB 锁页错位做有条件页迁移；README 明确要求停止写入才能获得一致副本 | 根 MIT，有局部参考价值；取钥移植来源涉及无许可证项目的说明，复制前仍须核对来源。明文密钥缓存和 HMAC 参数探测策略不能原样搬入 Echo |
| [q957506633/qq-nt-export](https://github.com/q957506633/qq-nt-export/tree/bec1504170f99e2752793320711c5653f3803670) | `ntqq_key_scan.py` 用只读 Win32 进程权限查找 raw key＋salt；`ntqq_decrypt.py` 用 SQLCipher 验证、导出；公开实测声明是 **9.9.35** | MIT；Windows 路线最直接的候选之一。匹配盐只排除部分错配，仍须 HMAC／实际查询。顺序 copy main／WAL、可选忽略 WAL、密钥写 config 均不满足 Echo 现有合同 |
| [QQBackup/nt_msg_db_util](https://github.com/QQBackup/nt_msg_db_util/tree/317024ce2c5e3482fdf9f310a5a7159ab4927e34) | `1.decrypt.py` 去头、设置 cipher 参数、逐表读取，另有丰富字段／protobuf 研究；导出会缩小批次、跳过坏行，索引错误也可被忽略 | GPL-3.0；字段研究可参考，恢复性导出不能冒充 Echo 的完整分析输入。不能直接复制后仍假定只有 MPL 义务 |
| [Tealina28/QQNT_Export](https://github.com/Tealina28/QQNT_Export/tree/766888be69685d00d088e2988c0497ef26fc7f56) | README 明确入口为**已解密**数据库，负责 SQL／protobuf 解析与文本／JSON 导出 | GPL-3.0；不解决 Windows 取钥；Echo 已有对应解析职责，不引入第二套导出器 |
| [star-picker/QQNT-Database-Export-Tool](https://github.com/star-picker/QQNT-Database-Export-Tool) | 仓库元数据定位为已解密数据库的导出工具，未深入审计实现 | AGPL-3.0；不是获取链路的替代，不列入可直接复用成果 |
| [zywstudy123/qq-bak-chat-history-export](https://github.com/zywstudy123/qq-bak-chat-history-export/tree/5516ccb6f582c0ab87997fe3f2cdb67433b3dd0d) | README 的真实 BAK 流程实际是“官方导入 → NTQQ 本地库 → 另行解密 → 解析”；源码树没有独立 BAK 解密器 | MIT；**名字不能证明能直接读 BAK**，这条流程仍回到密钥问题 |
| [fnyfree/qqnt-chat-decrypt](https://github.com/fnyfree/qqnt-chat-decrypt/tree/a73ec7d0b576dbb67e13536d3641530d8fa640f9) | macOS 调试／堆扫描、SQLCipher 参数和 schema 资料；Windows 部分指向 QQBackup；说明 BAK 有独立读取条件 | MIT；格式交叉线索，macOS 的操作和兼容结论不能迁到 Windows |
| [Znger1/muse-qq-connect](https://github.com/Znger1/muse-qq-connect) | README 声明 Linux QQ 3.2.34 的只读取钥／解密／protobuf 链路；本轮只读 README，未固定 revision 或审计实现 | GitHub 元数据为 MIT；只能作为另一平台的可行性线索，不引入其 SSH／远端助手工作流 |
| [fangtimmy/ntqq-db-decrypt](https://github.com/fangtimmy/ntqq-db-decrypt) | README 描述 Linux 只读内存扫描和同类 cipher 参数；未固定 revision 或审计全实现 | 查询时无明确根许可；Linux 代码不等于 Windows 支持 |
| [DaizeDong/qq-history-recovery](https://github.com/DaizeDong/qq-history-recovery) | README 与 `tools/qqnt_decrypt.py` 描述逐页 AES／HMAC 离线读取；实现默认容忍 2 个 HMAC 不匹配，与 README 的严格完整性描述有差别；未固定 revision | 元数据 MIT；不能照搬默认容错或据 README 宣称完整。只作交叉线索 |
| [shuakami/qq-chat-exporter](https://github.com/shuakami/qq-chat-exporter/tree/07113d8ebb2be829db9b9c58865a43629cad1a57) | 仓库树包含 NapCat 集成／插件，元数据 GPL-3.0；本轮未重新审计完整旧框架 | 不作为独立本地来源，不重新引入退休 QCE 功能 |
| [xCipHanD/qqnt_backup](https://github.com/xCipHanD/qqnt_backup) | README 明确适用 Android NTQQ 数据库；本轮未审计实现与许可 | 不能将 Android 文件头推导密钥经验移植为 Windows 已有能力；不新增移动端工作 |

许可结论针对组件选择，不构成整个产品的法律合规结论：
SQLCipher Community 的 BSD 风格许可允许开源和商业软件使用，须保留声明与依赖许可，
见[官方 Community 许可说明](https://www.zetetic.net/sqlcipher/community/)。
MIT 候选仍须保留版权及核对文件来源；GPL／AGPL 不等于完全不能使用，
但分发／组合义务需要先确定，不能静默复制进 MPL 文件。
无许可证、非商用限制均不是“开源所以可随便复用”。本轮没有复制第三方源码。

## 4. 数据格式、密钥、54395 兼容必须分别判断

### 4.1 已有证据支持的 QQNT 候选格式

社区多个实现一致使用外层 1024 字节 QQ wrapper，之后为 SQLCipher 页流；
真实盐候选位于文件偏移 1024 起的 16 字节，不能把外层头或账号目录当作密钥。
常见候选参数是 4096 字节页、AES-256-CBC、PBKDF2-HMAC-SHA512／4000 次、
页 HMAC-SHA1／48 reserved bytes。这**不是 SQLCipher 4 默认配置**；
官方默认页 HMAC 为 SHA512、KDF 次数为 256000，见[官方设计](https://www.zetetic.net/sqlcipher/design/)。
其他库或变体出现 SHA512／80 reserved bytes 时，必须作为独立 profile 验证，不能静默猜测。

passphrase、32 字节派生 key、带盐的 SQLCipher raw-key 表达式是不同输入。
对已派生 key 再跑 passphrase KDF 会失败；盐公开可读不等于 key 公开可得。
同账号不同库／不同设备／换代能否复用密钥，需要逐库证明。
Android 头部推导方案、login.db 固定读取条件，都不能证明 nt_msg.db 可据此解密。

SQLCipher 的 key／cipher 参数须在第一次实际读取前按所选 API 和版本设置；
PRAGMA 成功返回不证明已用正确 codec 打开，普通 SQLite 甚至可能忽略未知 PRAGMA。
应同时确认 cipher_version 和真实 schema／数据查询，见[官方 API](https://www.zetetic.net/sqlcipher/sqlcipher-api/)。

### 4.2 大库与 WAL

QQ 的外层偏移使其约 1 GiB 处的保留锁页位置与标准 SQLite 差一页。
按 4096 页计算，QQ 布局跳过 262144，标准 SQLite 跳过 262145。
粗暴剥头后交给标准 SQLite／SQLCipher 导出，可能出现损坏或遗漏。
Echo 已有 `providers/qq_sqlite_reader.py`，在受控 Windows 子进程调整 pending byte，
且只允许明确 SQLite 版本（当前源码 3.50.4／3.54.1）。这部分不应重写。
若采用 SQLCipher 导出，必须先证明它能正确遍历大库；不能指望下游 reader
恢复上游已经遗漏的数据。社区页迁移仅支持部分引用形态，不是全格式解法。
SQLite 锁页与 WAL 基础规则见[官方文件格式](https://www.sqlite.org/fileformat.html)。

有 WAL 时顺序复制文件不保证同一个 committed boundary；
关闭写入也仍需识别遗留 committed WAL，不能仅看 QQ 窗口是否消失。
现有 Echo `main_wal.mjs`／source guard 能提供更强的一致性证据，
应保留其 main／WAL／SHM 边界、checksum、文件身份与发布验证。
不能把社区的“忽略 WAL”“允许部分损坏”“尾部无效就使用前缀”作为默认成功策略。

还须区分现有 `main_wal.mjs` 的两种用途：正式链路使用加密合并，
随后调用 NapCat DatabaseApi 解密；模块里的 `createSnapshot`／`encryptFixture`
是研究用路径，后者生成的是人为构造的 SHA512 截断标签，前者不校验真实逐页 HMAC。
**已有 PoC 通过不代表已有可直接启用的完整 QQ 解密器。** 本轮没有修改它们。

### 4.3 54395 的证据矩阵

| 问题 | 本轮证据 | 判断 |
| --- | --- | --- |
| 54395 是否仍是上述 wrapper／页格式 | 没有该 build 的授权样本或实机实验 | 未证实，不能写成已改变或已兼容 |
| 登录后是否仍有可读 raw-key／passphrase 候选 | 有 9.9.32／9.9.35 上游声明和相应源码，没有 54395 的直接验证 | 最优先验证的前置条件；取钥失败不自动证明加密算法变更 |
| NapCat／其他辅助程序能否启动 | 搜索命中过 NapCatQQ issue #2163 的 54395 故障摘要，但页面抓取 404，GitHub API 返回 410，仓库定向搜索无结果 | 排除为已确认证据；无法据摘要诊断 launcher／Worker 根因 |
| 新版辅助程序启动失败是否证明数据库读不了 | 没有这种因果证据 | 启动／ABI／注入、取钥、数据库解密、消息字段必须分别实验 |
| 私聊／群聊列与 40800 protobuf 能否完整复用 | Echo 当前 schema 消费者与本轮虚构样本通过 | 只证明接入边界；仍须 54395 控制样本核对列含义、未知类型与身份 |

截至本轮调查，没有取得可复核的“Windows 9.9.37-54395，独立获取密钥、
完整离线读取、与受控消息清单一致”的端到端公开证据。
这表示尚未证明，不表示社区绝对没有实现。
GitHub 匿名 API 后续触发限流，补充调查使用官方 raw 源文件；
部分候选只达到 README／元数据级，表中明确标出，不据此认证实现。

## 5. Echo 的复用边界

```text
未来独立获取条件（尚未证明）＋已有一致加密快照
    → 独立、版本明确、逐页验证的本地读取／解密（尚未正式实现）
    → 同代际、身份有证据的明文 snapshot
    → QQDatabaseProvider → qq-db-json → QQ DB Adapter
    → RichMessage／ChatMessage → AnalysisApplicationService → 原有报告
```

| 已有能力 | 复用程度／剩余工作 |
| --- | --- |
| 加密 main＋committed WAL 捕获、路径所有权、lease、staging／manifest 原子发布 | 优先保留底层实现；`snapshot.mjs` 当前仍引用 core、DatabaseApi、selfInfo，不能不改接口就称为脱离 NapCat |
| QQDatabaseProvider／qq_sqlite_reader | 现有明文消费接口可直接复用；本轮已走通小库，不能扩大为大库新解密器通过 |
| QQ DB Adapter 与 protobuf／reply／mention／表情语义 | 保留，不引入第二套通用 protobuf 猜测或第三方 JSON 再转换 |
| Analysis Core／过滤／Presentation／报告 | 保留，无需为独立来源复制统计或报告模板 |
| 昵称、本人身份、UID↔UIN、私聊戳一戳上下文、群成员和素材 | 当前部分来自已认证 QQ RPC；须从同一授权数据集的 profile_info／group_info 等验证，不能承诺零改动功能等价 |
| 认证 Worker／boot_id／账号回调／列表快照复用 | 与现役 NapCat 绑定，未来独立获取需有自己的真实身份和代际证据；不能虚构 boot_id 或删掉校验绕过 |

离线历史只能覆盖本机实际存在的数据。独立读库不自动补全云端历史、
旧客户端未迁移记录或缺失媒体，也不自动保留现有 QQ 网络素材补全能力。
这些是功能等价评估的留项，不在本轮扩展实现。

## 6. 最有希望的路线与取舍

| 路线 | 可行性与用户流程 | 风险／维护成本 | 本轮判断 |
| --- | --- | --- | --- |
| A. 正常官方 QQ＋明确授权的进程外只读取钥＋独立副本读取 | 社区已有 Windows 实现；无需第三方客户端 API、无需改安装目录；后续分析可完全离线 | **中到高**：54395 密钥驻留形态／权限、账号绑定尚未证实；仍有版本适配和授权问题。只读不等于无风险或无需授权 | 最值得投入一次最小验证；本轮未运行扫描、未实现真实取钥 |
| B. 用户主动提供官方导出／备份，Echo 纯离线解析 | 对用户授权、客户端完整性与运行资源的边界最清晰；若有稳定明文导出则最易维护 | 明文导出是低运行成本但有手工步骤；**原始 BAK 是高不确定性**：容器、密钥和版本差异未解决，54395 官方导出入口也未实测 | 值得并行保留的非侵入替代。先确认实际导出物，再决定是否研究 BAK；不要把“导入 BAK 后再取钥”当独立突破 |
| C. Echo 自有小型客户端原生读取／取钥 helper | 理论上可复用客户端已有解密能力，省去部分 codec 兼容；不依赖完整框架 API | **高**：私有 ABI、加载条件、版本耦合、进程／Hook 清理和完整性边界。若要求补丁、绕过保护即不满足本任务 | 不优先；只是备选研究假设。当前没有已验证、无需绕过保护的 54395 加载方案，不据此开始注入开发 |

“用户已有匹配密钥，直接离线读取”是 A 的最小实验入口，
有助于先区分 codec 和取钥问题，但不算另一条已解决普通用户体验的产品路线。
不存在为了凑齐三条而将同一解密器包装为三个独立方案的必要。

## 7. 本轮独立原型及实际验证

新增的研究文件只有本文与：

- `scripts/spikes/qq_independent_source.py`：Windows 虚构 SQLite 驱动，复用现有
  `qq_db_test_data.synthetic_text_message_blob` 和既有 reserve fixture；
  调用未修改的 Provider、ImportService、AnalysisApplicationService。
- `scripts/spikes/qq_independent_codec.mjs`：用现有 Node crypto 实现候选页格式的
  虚构加密／逐页 HMAC 验证／解密闭环；只含公开的固定虚构 passphrase，
  不枚举进程、不发现 QQ 数据、不获取密钥，不是正式解密 API。

运行方式（先遵循 DEVELOPMENT 的环境与目标源码验证）：

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
& .venv/Scripts/python.exe scripts/spikes/qq_independent_source.py
```

驱动先隔离用户目录、配置与临时目录，生成 3 页、48 reserve bytes 的小 SQLite，
由 Node 包装为候选 QQNT cipher 布局，再还原明文，要求逐字节相等、
QQDatabaseProvider.quick_check 为 ok。它分别生成虚构私聊、群聊 payload，
核对消息文本和本人方向，并走统一分析与 HTML／JSON 报告。
所有数据库和报告位于本次自有临时根，完成后已删除。

实际结果：

| 检查 | 结果／限制 |
| --- | --- |
| 显式环境／源码来源 | 本 worktree 的 .venv，Python 3.13.9；目标 src 实际导入通过；pip check 通过，声明 runtime／dev 包版本范围符合；现有 Node v24.16.0 |
| 虚构 codec 往返 | 通过；3 页字节一致；同时覆盖 passphrase 派生与同一已知 raw-key 输入，不证明真实客户端的 key 分发语义 |
| 拒绝检查 | 错钥、错盐、错 HMAC profile、页截断及第二页损坏均拒绝；无坏页容忍 |
| 现役消费链 | 私聊／群聊各 1，会话均 2 条消息，身份与正文断言通过，共生成 4 个 HTML／JSON 文件 |
| 初次报告实验 | 因现有 .venv 缺少 jieba/dict.txt 失败；根因已核对，未安装／升级依赖或修改共享环境 |
| 隔离报告实验 | 显式使用 5 个虚构词条的临时 jieba 字典后通过；仍使用实际分词器和生产分析路径。不是默认中文词典或完整语言画像验收 |
| 既有 Focused | `test_qq_db_import_integration.py`、`test_qq_db_adapter_self_identity.py`、`test_qq_db_reply_mentions.py`：20 passed，1 failed；失败项 `test_mention_display_emoji_does_not_enter_expression_report` 同样缺默认词典，未弱化预期或改测试 |
| SQLCipher 库互操作 | **未验证**；环境没有 sqlcipher3／pysqlcipher3，未补装。自写 encode／decode 同源往返只能支持候选格式自洽，不能证明能读真实 QQ |
| 54395 实机、真实取钥、真实 BAK、活动 WAL、新解密器大库 | **均未执行／未覆盖**；没有接触真实账号、聊天、安装目录或保护机制 |
| Full／Frozen／Setup／GUI 人工验收 | 未执行；本轮未修改正式功能、打包或客户端，不能宣称发行通过 |

没有扩大 pytest 体系，没有修改 src、现役脚本、依赖清单、主架构合同或 main。

## 8. 下一步最小实验与停损条件（等待负责人决定）

建议按信息收益顺序只做下列小实验，暂不开始正式集成：

1. **独立交叉验证 codec。** 用来源／许可已核验的 SQLCipher Community
   构建产生一份已知测试密钥、候选 QQ 参数的合成库，与本轮读取器双向比对，
   不能让同一份 encode／decode 互相证明。要求真实 cipher_version、
   全表内容及正文 BLOB 一致、逐页认证和完整性检查通过；错钥／损坏必须拒绝。
   有标准库输出也不证明 QQ wrapper 的实际版本语义。
2. **54395 控制样本先分清格式与密钥。** 后续须单独获得负责人对
   隔离环境、专门测试账号、人工构造消息及具体密钥获取方式的授权。
   当前不执行。先在未经修改的官方客户端产生有清单的私聊／群聊样本，
   人工提供合法取得的匹配测试密钥，检验冻结副本的 wrapper、盐、HMAC、
   schema、全部消息及本人方向。这样能先回答“该 build 的数据库能不能读”，
   而不把取钥失败误作 cipher 失败。样本留本机，不提交账号或数据库。
3. **再验证 A 的获取入口。** 在相同隔离测试条件和明确授权下，
   审核或自行实现一个最小只读扫描器，限定目标进程和账号，只在内存保留候选。
   要求候选与目标库的页 HMAC／实际查询匹配；盐匹配本身不算成功。
   两次正常重启／登录后仍可重新绑定；普通权限失败须如实拒绝，
   不自动提权、补丁、Hook、关闭保护或扫描其他账号。

若只能再做**一个**与产品决策直接相关的实验，选择第 2 项：
**54395 控制库＋合法已知测试密钥＋独立读取器＋消息清单逐条比对**。
本轮原型与社区源码已足够支持先做它；第 1 项可用于降低实验定位歧义。
实验设计里的测试账号和客户端操作不属于本轮已授权动作。

成功证据至少包括：精确 build／架构、来源版本与可复核的源码版本、
输入快照一致性证据、密钥形态但不含密钥值、逐页认证／完整性结果、
私聊和群聊按受控清单的 ID／时间／方向／消息类型一致、经原 Provider／Adapter
生成报告；只保存脱敏结论，不发布测试账号状态或原始库。
这能证明**该 build 在已知读取条件下的离线链路**，
第 3 项通过才能进一步证明独立自动获取入口；
活动 WAL、超过锁页边界的大库及辅助身份库仍需后续定向验证，不能扩大结论。

若第 2 项正确密钥仍无法验证首页，应先核对偏移、密钥形态与明确 profile，
停止扩展解析器；若第 3 项在合法只读权限下不可取得匹配密钥，
且继续推进必须绕过完整性保护，则 A 在当前约束下停止，转向 B 或等待新证据。
若官方 BAK 仍需未知密钥而没有可复核解码器，不开始制作 BAK 导入 GUI。

上一轮结束时，研究成果在研究分支工作区原位保留，未执行 Git commit。
本轮负责人已明确授权整理并本地提交上述研究文件；不合并 main、不 push、
不创建 PR，不清理其他任务资产。后续跨实现验证另行记录，不改写上一轮验证结论。
