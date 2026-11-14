# QQ 独立数据源：SQLCipher 互操作与 54395 测试输入复核

日期：2026-11-14。范围仅为 `spike/qq-independent-source` 研究；不是功能适配声明。
前一轮报告及两个原型已在本地提交 `3bc07779ac82498b5d367152fb62babefba0b9d5`。
本记录补充新证据，不覆盖[前一轮报告](2026-11-14-qq-independent-source.md)的历史验证结果。
本页保留上一轮的截断缺口和实验结果；后续授权的最小拒绝修正及来源调查见
[54395 数据来源调查](2026-11-14-qq-54395-source-investigation.md)。下文“本轮”指互操作实验阶段。

## A. 离线解密技术的跨实现结论

**针对候选加密参数组合，已经取得足以支持算法互操作判断的双向跨实现证据。**
参照方是真正的 WCDB 内嵌 SQLCipher，实验方是已有的 Node 独立 codec，
不是让同一份 encode/decode 相互证明。此结论不证明 QQ 54395 使用该组合，
也不表示当前原型已经是完整、可交付的离线解密器。

发现的具体缺口：**原型只认证实际存在的页，末尾整页丢失仍会返回明文**；
该明文被标准 SQLite 完整性检查拒绝。因此逐页 HMAC 成功不能代替数据库完整性检查，
也不能代替输入快照一致性。本轮只记录并复现，不扩张为正式入口或快照工程。

### 参照来源与执行边界

- 直接复用仓库现有 `runtime/wechat/WCDB.dll` 的任务内副本，原文件未修改。
  运行前 SHA256 与发行清单固定值一致：
  `c4108e53dbe6749eb4ec2881f6d322eb160a1c5020ac959fb8ffaeac5498ecab`。
- 匹配头文件来自官方 [Tencent/wcdb v2.1.15 对应提交](https://github.com/Tencent/wcdb/tree/a62d7f12191843e1f095e3c37f46785ed04ebde8)，
  通过 GitHub codeload 下载该提交源码，仅在忽略的任务构建目录取用头文件。
  归档 SHA256：`8f12be1742c725753406636129ce8dd901492424d33ce552a5902156f616093c`。
  这是本次下载的复核指纹，不是额外发布的官方签名。
- 仓库构建脚本固定的 SQLCipher 子模块为
  `f049bed66ca26741f09a6e4f0603ed3af195ac96`。本次实际回读 `cipher_version`
  为 **`4.1.0 community`**。这是 WCDB 集成的 SQLCipher 实现，未另跑 Zetetic 原版 CLI。
- 新增的[小型 C++ 参照程序](../../scripts/spikes/qq_sqlcipher_reference.cpp)由本机现有 MSVC x64 编译。
  使用官方类型布局和 DLL 导出生成的 import library；没有手写 ABI、访问 QQ 进程或安装目录。
  不下载、安装或运行 SQLCipher wheel、其他 QQ 工具或未经核验的二进制。
- [实验驱动](../../scripts/spikes/qq_sqlcipher_crosscheck.py)只生成虚构表，
  使用已有 Node v24.16.0、显式 Echo `.venv` Python 3.13.9、标准 SQLite 3.50.4。
  子进程 HOME、USERPROFILE、APPDATA、LOCALAPPDATA、TEMP、TMP 指向任务目录。
  不导入 Echo 业务链路，不重复 Provider → Adapter → 报告实验，也不依赖 jieba。

### 参数与方法

| 项目 | 本次验证范围 |
| --- | --- |
| 加密算法 | AES-256-CBC，无 PKCS padding；由双向互读验证兼容 |
| 页大小 / reserved bytes | SQLCipher 回读 4096；解密后 SQLite 页头 reserved bytes 为 48 |
| passphrase KDF | PBKDF2-HMAC-SHA512，4000 次；回读配置并双向读取 |
| 页认证 | HMAC-SHA1，认证 ciphertext、IV、页号；原型使用 LE 页号，HMAC 子密钥 PBKDF2-SHA512/2、salt XOR 0x3a，互读成立 |
| key 形态 | 已知虚构 passphrase；另验证 SQLCipher raw 32-byte key + 16-byte salt 读取 Node 输出 |
| QQ 外层头 | 人工加上的 1024 字节包装；不声称验证真实 QQ 的包装结构或元数据 |
| 数据 | SQLCipher 自行生成 10 页、24 行，含中文、emoji、BLOB，无 QQ schema 或真实消息 |

WCDB 在获取主库句柄时会先执行自身配置，因此本实验在独立控制库中，
先设置 `cipher_default_*`，再 `ATTACH ... KEY ...` 创建/读取目标加密库。
创建后从 `fixture` schema 回读实际参数，再执行结构和全表检查；没有把默认设置成功
或 `PRAGMA key` 不报错当成解密成功。相关 API 含义参见 [SQLCipher 官方说明](https://www.zetetic.net/sqlcipher/sqlcipher-api/)。

第一次构建时，生成 `.def` 给符号加的引号被 import library 保留，导致链接不到实际符号；
通过比对导出表及 `dumpbin /linkermember` 确认后去掉符号引号，构建成功。
第一次负向实验还发现该运行库对 `cipher_integrity_check` 不返回有效损坏诊断，
不能将空结果算作认证成功。最终驱动采用实际 SQLCipher 读取、`integrity_check`、
全部正文/BLOB 比对，以及逐页损坏实验，不依赖该 PRAGMA 的空输出。

### 实际结果

| 验证 | 结果与含义 |
| --- | --- |
| SQLCipher 加密 → Node 解密 → 标准 SQLite | `integrity_check=ok`，全部 24 行的 id、UTF-8 正文、BLOB 与预设值一致 |
| Node 加密 → SQLCipher | SQLCipher 完整性检查为 ok；全表内容一致 |
| raw key + salt | SQLCipher 用该形态读取 Node 输出，内容一致；不等于取得 QQ 密钥 |
| 逐页破坏 | 分别破坏第 1 至第 10 页 ciphertext；Node 每次拒绝且不发布输出；参照方打开或完整性检查每次拒绝 |
| 错误密钥 | 两个实现实际访问数据库均拒绝，不以 key 设置语句成功算通过 |
| 参数不匹配 | SQLCipher KDF 改成 4001 后实际读取失败；Node 错误 HMAC profile 拒绝 |
| 截掉 1 字节 | Node 拒绝，不发布明文 |
| 截掉最后 4096 字节 | Node 接受剩余页；标准 SQLite 拒绝该不完整数据库，作为已知缺口保留 |

HMAC 不是整个文件的签名：QQ 外层包装、reserved 区末尾对齐填充、文件是否完整及是否同一代
不是本次逐页认证单独保证的属性。本轮没有实现整页截断加固、WAL、并发快照或大库能力。

### 复核方式

参照程序构建输入只需上述官方源码的 `src/common`、`src/cpp` 头文件及核验过的 DLL 副本：

1. 用 PE 导出表生成 `LIBRARY WCDB.dll` / `EXPORTS` 的 `.def`，符号原样逐行写入，不加引号。
2. 在 MSVC x64 开发环境执行 `lib /def:WCDB.def /machine:x64 /out:WCDB.lib`。
3. 将两个源码子树的全部头文件目录加入 include，使用
   `cl /std:c++17 /EHsc /utf-8 /MD /DWCDB_DLL` 编译参照源码并链接该 import library；
   将核验过的 DLL 副本放到生成程序旁。全部输出放在本任务拥有的忽略目录，不能覆盖正式 runtime。
4. 先隔离用户环境目录，再从仓库根目录执行以下命令；最后一个参数必须是尚不存在的目录。

```powershell
.venv/Scripts/python.exe scripts/spikes/qq_sqlcipher_crosscheck.py <reference.exe> <new-owned-output-directory>
```

驱动生成 `result.json` 和全套虚构输入/输出，不写入账号数据；重跑使用新的目录。
本轮最终输出包含：`pages=10`、`records=24`、两个互读方向 passed、raw_key_plus_salt passed、
all_pages_corruption_rejected_by_both true，`qq_54395=not_tested`。

## B. QQ 9.9.37-54395 测试输入与密钥来源

**本轮未取得符合条件的当前 Windows build 数据库及匹配密钥；尚不能确认有现成合法可信的输入可直接采用。**
阻塞是测试输入和密钥来源，不是已经证实该版本改了 cipher，也不是已经证实该版本无法离线解密。
本轮没有运行 QQ、登录账号、扫描或调试进程、修改安全保护，未联系项目维护者。

### 公开证据能证明到哪里

| 一手资料（本轮核对） | 可支持 / 不可支持的判断 |
| --- | --- |
| [QQDecrypt Windows 教程](https://qqbackup.github.io/QQDecrypt/decrypt/extract/NTQQ%20(Windows).html)，仓库提交 `4cc0912c92dcb1edcc799127e56178c60a7b7cdc` | 明确确认版本是 9.9.32-51246，日期 2026-07-19；流程涉及取钥。不是 54395 的 DB/key 实测证明 |
| [qq-nt-export 固定版 README](https://github.com/q957506633/qq-nt-export/blob/bec1504170f99e2752793320711c5653f3803670/README.md) | 标注实测 9.9.35，使用外部内存扫描获取凭据；参数可供假设与互操作验证，不能将其取钥成功外推到 54395 |
| [SnowCatQQ 固定版 README](https://github.com/DandanLLab/SnowCatQQ/blob/1c3d85fe4bcb11856d62dd963d74c5e6d7d93704/README.md) | 声称 54395 主进程运行时适配，描述 V8 注入通道；它不是独立离线 DB/key fixture，也不能证明无框架取钥可行 |
| [QQDecrypt 统一解密](https://qqbackup.github.io/QQDecrypt/decrypt/decrypt_db.html) | 前提就是已有原始库及 key，不提供官方 key 导出授权或 54395 配对输入 |

另通过 GitHub API 核对上述三个固定提交的完整文件树，分别 162、13、1384 个条目，均未截断；
未发现命名为 fixture/testdata/sample/54395 或扩展名为 db/sqlite/sqlite3/bak 的文件。
这只是限定仓库和文件名的调查，不证明互联网不存在样本，也不排除嵌入数据或其他分支。
精确 build 与密钥/数据库/fixture 组合检索未补到可核验的配对证据。
前轮涉及的 NapCat issue 2163 仍不能直接读取，不能将搜索摘要升级为验证结果。
Linux 版本中相同的 54395 数字也不能充当 Windows 证据。

没有找到可信的官方文档证明此 build 提供消息库密钥导出；官网页面本轮访问失败，
因此不能据此断言这种机制绝对不存在。官方 BAK 也不能未经验证就当成明文 SQLite 或配对密钥来源；
目前不具备用 BAK 消除本阻塞的证据。

### 可接受的输入取得条件（本轮不执行）

最小可行候选是腾讯/有明确授权的研究维护者提供的 **54395 专用虚构样本与匹配测试密钥**，
或负责人另行批准的隔离环境内，由全新专用测试账号产生的样本。
后者仍须先落实一个经过审查且获准的具体密钥获得机制；“账号属于本人”不能代替该条件。
若方法要求修改客户端、关闭保护或超出本任务约束，即停止；不能借专用账号自动放宽边界。

输入至少应满足：

1. **版本可信**：Windows、架构、9.9.37-54395 的来源、客户端/实际加载模块版本与哈希，
   以及样本生成记录；区分安装包标称版本与热更新后的运行模块。不以旧版本库迁移后改标签充数。
2. **数据有权使用**：专用参与方明确同意，只产生预定虚构消息；数据库、测试密钥的提供和研究使用
   均有明确授权/许可。代码开源许可不能替代聊天数据授权或客户端相关授权。
3. **密钥可溯源**：记录获得方式与授权，区分 passphrase、raw key+salt、登录密码、其他库的固定 key；
   盐相同只证明候选关联，必须实际验证所有页和数据库内容。不接受来历不明的论坛 DB/key 包。
4. **冻结输入可信**：提供与密钥同代、由正常关闭/检查点等方式获得的一致副本，附哈希和已知消息清单。
   本轮不处理活动 WAL。保留当前客户端实际产生的原始加密字节；把明文脱敏后再自行加密不能证明 54395。
   原始账号状态和样本留本机，不提交到仓库或上传。

条件满足后，下一步只需**一个**受控样本：检查包装/参数/全页认证，标准 SQLite 完整性检查，
按清单核对 schema、全部私聊/群聊消息的 ID、时间、方向和正文，再经过已有 Provider/Adapter。
有现存密钥时可先证明该 build 的离线读取；它仍不能证明普通用户可自动取得密钥。

**停止条件已触发：当前没有经授权且可复核的 54395 匹配密钥来源。**
不继续自动取钥，不用更多虚构库代替当前 build 的真实来源证据，等待负责人决定取得条件是否值得推进。

## 交付及未覆盖范围

只改动研究文档和 `scripts/spikes`。前轮三个文件已按授权单独本地提交；
本轮新增验证记录、两份参照/驱动源码，以及 codec 的最小导出接口修改原位待审。
未合并、未 push、未改正式 Echo/微信/QQ 链路，也未扩大 pytest 体系。
未运行 Full、Frozen、Setup 或 GUI 验收；本轮不涉及其发布变更，不能宣称产品验收通过。
此前默认 jieba 词典环境失败不影响此实验，未修依赖。

任务构建目录中的源码归档、官方头文件、核验后的 DLL 副本、本地编译程序和虚构数据库均未提交，
原位保留供本轮复核，复核结束后由负责人决定处置；不将该目录引入正式运行时。
无关未跟踪 `Microsoft/` 保持原样，main 保持原 HEAD。研究到此停止，等待下一步决策。
