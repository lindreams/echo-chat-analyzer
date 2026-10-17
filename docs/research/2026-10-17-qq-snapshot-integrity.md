# v0.2.2 QQ 快照 integrity 故障：未解决

本轮基线为正式 `v0.2.2`，保留 Header 18/19 转换。朋友电脑的
`result=failed category=integrity` 是负责人提供的现场证据；本轮没有读取真实
QQ 数据、凭据或用户配置，也没有重新执行真人连接。

**没有证实导致现场故障的产品缺陷，没有实际连接修复，也没有产品 RED → GREEN。**
以下实验不能作为故障已解决或可以发布的证据。

## 已追踪的链路

- `main_wal.mjs`：SHM 双 Header/checksum → 固定 mxFrame → WAL salt、逐帧滚动
  checksum 和 commit → 事务内最后页面覆盖 → commit 页数收缩时删除超界页面 →
  WAL 页面优先、主库补页 → 复验主库 identity/stat/全内容、WAL 完整选定前缀、
  checkpoint attempted/backfill 和代际。
- `snapshot.mjs`：租约和清理 → 加密合并输出 → 输入强见证 → 进程内
  `DatabaseApi.decryptDatabase` → 输入复验 → 独立输出格式/页数校验和 Header
  18/19 转换 → 删除加密中间文件 → manifest 和 generation 原子发布。
- `qq_direct_database_import_service.py` / `qq_database_provider.py`：generation
  校验 → `mode=ro` → `PRAGMA quick_check(1)` → 会话查询和物化 → 清理。

现有捕获层拒绝观察到的主库改变、checkpoint 进度改变、WAL reset/truncate、
文件替换和前缀变化。此次没有证据支持关闭这些 guard，或把失败快照作为可读数据使用。

## 新的虚构数据库实验

回归在 `tests/test_qq_direct_main_wal_acquisition.py` 中，复用正式获取、发布和清理
路径；构造超过 20 MiB 的数据库，包含多层表/索引 b-tree、复合索引、WITHOUT ROWID
表、大文本和 BLOB overflow、删除和 DROP 后的 freelist、增长及多次提交。

旧 reader 固定较早的 WAL 提交；后续写入后执行真实 PASSIVE checkpoint，断言
回填帧数大于零且小于 WAL 总帧数。加密虚构数据后保留真实 backfill/attempted
计数。再开启明确的未提交事务，缩小 cache 并产生 cache spill，断言物理 WAL
帧数超过已公布的提交边界。快照必须排除这段未提交 schema 和数据。

分别验证 SQLite 每页 reserve 为 48 和 80 的布局。**SQLite 布局 reserve 与加密
尾部长度不是同一个参数**；80 字节布局的实验仍采用固定格式的 48 字节加密尾部。
NapCat 上游也说明存在这样的 NTQQ 布局差异；这不是现场数据库参数的证明。
参见 [NapCat 解密源码](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-database/src/decrypt.ts)。

除了原有解密替身，还可通过进程环境 `ECHO_TEST_NAPCAT_BUNDLE` 显式选择一个本地
`napcat.mjs`。测试先核对项目 pins 中固定的上游或已打补丁 SHA256，只提取该版纯
解密函数及其常量；不执行 NapCat 入口、不启动 QQ、不读取配置或账户状态。
未提供 bundle 时仅对应的真实解密集成项跳过，不下载或接受任意版本代码。

判定依据不仅是 Header：

- 输出 `quick_check(1)` 和完整 `integrity_check` 均须为 `ok`。
- 按主键核对全部表内容；未提交表不得出现。
- 与写入连接在选定提交时 `serialize()` 的独立参考图像逐页比对全部有效字节，
  包含 Header 元数据、b-tree、overflow、freelist；只允许 Header 18/19 转换，
  并排除布局明确指定的页尾保留区。
- 原有会话、报告、凭据保护、代际和快照清理回归保持不变。

上述实验通过；不能外推到真实 QQ 的所有版本、加密格式或数据库状态。虚构加密
fixture 的认证尾部并非真实 QQ 认证实现，实验不证明真实 HMAC 兼容性。测试编写时
遇到的 SHM 锁区读取和 Python DDL 自动提交问题均属测试设置错误，不是产品根因。

## 替代捕获方案的可行条件

1. **在 QQ 的原生加密连接上开启读事务并执行 SQLite backup。** 这让 SQLite
   自身固定 pager/WAL 视图，比独立解释文件更直接。现役 NapCat API 提供的是文件
   解密加普通 SQLite reader，没有已确认的 QQ 加密连接 backup 入口。不能拿普通
   `node:sqlite` 打开带私有前缀的加密源，也不能把进程内密钥导出到外部工具。
   若采用此方案，先取得可验证的原生 API 和连接/线程所有权证据，再实现最小桥接。
   参见 [SQLite Online Backup API](https://sqlite.org/backup.html)。
2. **Windows 卷级一致性副本。** 同时固定 main/WAL/SHM 后离线选取提交，能避免
   捕获窗口内发生 checkpoint，但需要 VSS 权限、卷和资源释放合同；仍不能修复
   已存在的源损坏或解密格式错误。此次没有修改系统服务、创建卷影或引入管理员要求。
   机制参考 [Microsoft VSS 文档](https://learn.microsoft.com/en-us/windows/win32/vss/volume-shadow-copy-service-portal)。
3. **在已有合并图像上执行普通 SQLite backup / VACUUM。** 不能倒推或恢复已经
   丢失的页面，也不能证明原捕获视图一致；不作为完整性失败的自动 fallback。

SQLite 的 reader end mark 和 checkpoint 约束见
[WAL 文档](https://sqlite.org/wal.html)。当前实验没有证明捕获竞争是现场故障根因，
因此没有凭猜测替换捕获机制。

## 最少一次现场验证设计（尚未实施、尚无候选包）

确实需要的下一项证据是失败结果的**固定结构分类**，而不是原始 SQLite 文本或
数据库文件。单次连接尝试即可，在现有 quick_check 失败后、现有清理前完成：

- 本地将首个返回结果分类为 freelist、overflow、cell/freeblock、page reference、
  constraint、other/unknown；仅输出固定枚举。原始文本可能含表名或数据，不输出、
  不保存，也不采用“脱敏后原文”方式。
- 在同一个只读连接上核对 Header 页大小、布局 reserve、物理页数与 Header 页数
  是否匹配，只输出数值参数和匹配布尔值；不输出路径、schema、账号、内容或文件哈希。
- 若分类含可靠的故障页号，仅在进程内定位该页，并与捕获选择的加密页做独立解密
  比对；只输出 `decoder_bytes_equal` 和 `origin=main|wal|unknown`。做不到可靠定位
  就输出 unknown，不猜测。需要在 lease 覆盖的生产路径接线，不能在清理后另存明文。
- 任一步失败维持获取失败，执行原有清理；不延长明文生命周期、不上传任何数据。

此设计的目的，是区分页面选择、解密输出、Header 布局和数据约束几个不同原因，
为对应虚构复现提供明确条件。它本身不构成修复；实施前仍需合成故障与隐私回归。
当前故障继续保持未解决状态。
