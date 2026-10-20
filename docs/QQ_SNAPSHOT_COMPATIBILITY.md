# QQ 跨机器快照兼容性专项

## 故障结论与证据边界

现场已知两次获取均返回 ready、manifest 通过，随后 quick_check 失败，清理成功。
现场未提供 SQLite 返回的完整性结果类别或错误码，因此尚不能确定是数据损坏还是打开失败。
`main_changed_during_read` 和 `wal_frame_salt_invalid` 是捕获拒绝的证据，不能据此认定
另一次已发布快照损坏；本次继续保留这些拒绝条件及有界重试。

本地确认的兼容性缺陷：main 与已提交 WAL 已被合成为一个完整文件，但 NapCat 4.18.34
解密器仍保留页 1 的 WAL 读写版本 2/2。普通 `mode=ro` 因而可能尝试访问或创建辅助文件。
可写目录上的测试掩盖了此依赖；辅助文件无法创建时，正常数据库也会在 quick_check 阶段失败。
这是现场故障的一个有复现证据的候选根因，仍需受影响电脑验收，不能称为已证实的现场唯一根因。

格式依据见 [SQLite WAL 只读数据库](https://www.sqlite.org/wal.html#read_only_databases)
及 [SQLite 文件 Header](https://www.sqlite.org/fileformat2.html#the_database_header)。

## 实际修复

- 在发布前完成单文件格式转换：先完成全部捕获 guard、等待解密返回并复验加密输入强见证，
  持有原 workspace lease，只对固定 staging 明文输出处理 Header。
- 拒绝非普通文件、硬链接、意外 WAL/SHM/journal、输出长度与捕获页数不符、错误 magic、
  页大小、读写版本或有效 Header 页数不符；失败沿原清理路径退出，不发布 generation。
- 只将 Header 的偏移 18、19 改为 1/1。保留所有页数据、48 个保留字节、计数器和数据库页数。
  不对 QQ 原库执行转换，不使用 immutable，不跳过 quick_check。
- quick_check 保持原有 ok/failed/error 接口；新增固定分类和 SQLite 数字错误码，区分
  integrity、corrupt、access、busy、io 等情况，不记录数据库路径、表名、检查结果原文或聊天内容。
- 同步 runtime 模板哈希，构建时继续验证源码、模板和打包文件一致。

## 本地复现与回归

`test_published_single_file_needs_no_wal_or_shm` 使用虚构加密 SQLite main/WAL，
经正式 acquisition 返回 ready 后，用目录占用 WAL/SHM 名称，模拟辅助文件无法创建。
修复前 quick_check 返回 error（RED）；修复后普通 mode=ro 下 quick_check 与 integrity_check
均通过（GREEN），并读到选择边界的已提交正文。测试逐字节证明只有偏移 18、19 变化，
原始加密 main 不变，WAL 仅有测试主动追加的未提交事务；该事务含不同正文且未被采用。

回归还覆盖提交边界后的追加、未提交帧、checkpoint 推进、WAL 重置/截断/替换、校验和/盐值
拒绝、较大数据库及 overflow 页、明文输出格式失败、意外 WAL 与硬链接拒绝和异常清理。
端到端用虚构 QQ 表从加密捕获、解密、发布、SQLite 校验进入 Facade，读取群聊/私聊并生成
两类报告；损坏 b-tree 的快照仍安全拒绝，成功和失败路径都清理 generation。

这里的解密测试使用与固定 NapCat codec 相同的 AES/PBKDF2 格式，未运行真实 QQ 或读取用户账号。
自动化不能证明朋友电脑的 QQ 版本、文件系统访问条件、持续写入规模或安装兼容性。

本轮 Windows 本地验证结果：

- 最终 Focused：274 passed，包含快照、lease/清理、身份/认证/RPC、Facade、runtime bootstrap、
  发行资产合同及实际候选 Frozen 的 6 项合同检查；候选目录通过测试模块局部绑定，未覆盖正式 dist。
- Fast：1364 passed、2 skipped、288 deselected；两项跳过为 Windows symlink 权限。
- 最终快照算法定向回归：71 passed；初始单文件故障有 RED → GREEN 记录。
- 独立 Frozen 重建成功；130 个项目模块来源均为本专项源码，打包依赖元数据与模板哈希一致。
  隔离用户目录中的 Frozen 副本检出主窗口、正常关闭，原生退出码 0；未启动 QQ。
- Setup 包装验证覆盖 runtime pins、feed 身份、包哈希、逐文件内容与源目录未变；
  首轮构建期间模板变化触发 pin mismatch，产物未交付，最终重建通过。
- 未运行 Full，未进行本轮 Setup 安装/升级/卸载、真实 QQ 登录或朋友电脑验收。

## 候选版现场验收

候选包仅供本专项本地验证，不发布 Release/Tag、不自动更新正式 feed。交付使用实验安装身份
`EchoQQSnapshotLab` / `win-x64-lab`，应用数据目录仍遵循 Echo 现有规则。应用版本仍为 0.2.1；
文件名或交付清单应注明专项提交，避免与正式 v0.2.1 混淆。安装和替换须由测试者操作。

1. 正常退出旧 Echo，保留原报告和配置；核对候选文件 SHA256 与交付清单。
2. 安装指定专项候选，使用 Echo 授权流程启动并登录 QQ。
3. 加载会话列表，选一个群聊和一个私聊，分别生成并打开报告；确认正文和时间范围合理。
4. QQ 持续接收消息时重新加载、再次生成报告，确认新获取能完成，未误用旧 generation。
5. 正常退出 Echo，确认自有 QQ runtime 退出，明文快照与临时 payload 清理，原报告仍可打开。
6. 如仍失败，只记录固定阶段、outcome、错误分类和数字码。access 表示仍需追查打开/访问条件；
   integrity/corrupt 表示继续追查合成/解密或来源格式。不得上传数据库、密钥、聊天、身份或原始日志。

本地候选构建、Frozen 检查和现场验收分别记录，不将任一项扩大为跨机器验收通过。
