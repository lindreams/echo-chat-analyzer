# Stage 3.5I2：hardened PoC 准入验证

范围：独立真人验收 harness、虚构生命周期测试及本文；未修改 main/WAL 算法、
正式 snapshot helper、Provider、GUI、A4/A5 或旧 fail-closed 保护。
真人测试只通过本机 loopback RPC 获取目录、调用现有进程内解密，未获取密钥。
完整路径、原始 RPC envelope、payload、salt、内容 hash 和聊天字段均不输出或记录。

## 真人结果

在持续运行的 QQ/NapCat 下，hardened PoC 连续生成五次加密合并快照，调用进程内
DatabaseApi 解密，并以只读 immutable 连接执行 quick_check、完整 integrity_check、
schema 表数量和固定消息表的 count 查询。五次全部通过，且每次消费后 staging
均已删除。未将任何真实数据库或消息记录放入仓库。

| 次序 | 选定 B | 最终 index committed frame | 检查结果 | staging 清理 |
| --- | --- | --- | --- | --- |
| 1 | 17 | 17 | 全部通过 | 完成 |
| 2 | 40 | 41 | 全部通过，固定 B=40 | 完成 |
| 3 | 41 | 41 | 全部通过 | 完成 |
| 4 | 97 | 97 | 全部通过 | 完成 |
| 5 | 97 | 97 | 全部通过 | 完成 |

每次 main identity/content/stat、WAL generation/完整选定前缀及 SHM witness
校验均成立。每次 backfill/attempted 前后均为零。
第二次读窗口内 index 从 40 推进到 41，是实际 append-after-B 成功的证据；
产物仍绑定明确的 40。整个验收期间观测到源文件活动变化，结束后
DatabaseApi.hasPassphrase 仍返回 ready。未重启、停止或向 QQ 发送消息。

此次真人窗口未出现不兼容 checkpoint/reset，因此不声称真人触发了这些故障。
这些 fail-closed 条件由 Stage 3.5I 虚构并发测试覆盖；本轮重跑，未增加降级、
retry、checkpoint-lock 或 main-only fallback。

## 生命周期规则

`main_wal_acceptance.py` 曾是独立 Windows PoC harness，正式链路不 import 它。
该 harness 及其 Python workspace 已在 A3 退休；下述规则保留为历史验收记录。

### A3 安全证明迁移（2026-10-15）

生命周期验证改为直接导入正式 `workspace.mjs`，不再维护第二套 workspace。
`tests/test_qq_direct_snapshot_workspace.py` 使用虚构文件与真实 Node / Windows OS lease，覆盖：

- 强杀后恢复、活跃 owner 的跨进程互斥，以及虚构源文件保持不变。
- root、祖先路径、staging 和其成员 junction 拒绝；源目录与 workspace 三种重叠关系拒绝。
- root / staging 损坏、旧 PoC 类型或错误版本的 owner marker 拒绝，拒绝时保留数据。
- 无 marker、未知文件、未知子目录、旧 PoC 的 main/WAL 副本拒绝；删除前验证全部成员。
- 全部正式 staging 文件与 SQLite sidecar 清理、mkdir 后尚未写 marker 的空 staging 恢复。
- OS 拒绝删除时保留 marker 并阻止新 staging；解除占用后恢复。
- marker 写入异常只移除本次部分产物，并可重新获取 lease；generation 删除中断后恢复。

正式调用方的成功发布、解密返回失败或抛异常后的清理，继续由
`test_qq_direct_db_snapshot_runtime.py` 覆盖；消费异常清理由 `test_qq_direct_snapshot_lease.py` 覆盖。
正式策略允许根目录中无关文件存在，但不会删除它们；这与旧 PoC 拒绝整个根目录的策略不同。
额外只读诊断发现：Windows 下同一物理源目录仅改变路径大小写，正式 `assertSourceSeparate`
会放行，而相同大小写会返回 `workspace_invalid`。该既有缺口未修改，本轮不宣称两套源隔离
语义完全等价；后续须明确正式路径规范化契约并补大小写别名回归，不能以当前测试通过替代。
旧 PoC owner 不会被正式实现接管；本轮未扫描或处理仓库外旧工作区及真实数据。
`main_wal_poc.mjs` capture CLI、共享 capture 实现及其虚构数据测试保留；正式安全策略未修改。

### 历史 PoC 规则

- 根目录固定在仓库外的本机临时区域，须有固定版本的 PoC ownership marker。
  根目录不能与源 QQ 数据目录重叠；根路径和清理项不能经过 symlink/junction。
- acquisition/startup 先获得 OS byte-range 独占 lease，持有到消费和清理完成。
  其他活跃进程拿不到 lease，不能清理正在使用的 staging。
- kernel 在进程强制终止时释放 lease。下一次 acquisition 在 lease 内先 recover，
  无需 finally、PID 存活推测或可重用 PID 来判断遗留文件。
- staging 有自己的 owner marker，且只允许固定的 main/WAL/merged/plaintext
  和 SQLite sidecar 文件名。先验证全部成员，再删除任何成员；未知文件、
  不匹配 marker、reparse point 或子目录一律失败，不递归清理用户数据。
- marker 最后删除。删 plaintext 失败时 marker 和残留可安全识别，错误传播，
  后续 acquisition 必须先成功清理，才能生成新产物。
- kill 在 mkdir 与 marker 之间留下的空 staging 可安全移除；非空无 marker
  staging 拒绝处理。当前调用的 marker 写入异常会清除其刚创建的空 staging。
- 正常消费完成、普通异常和可捕获中断均走清理。强杀依靠下一次 recover。
  本轮不复制源 main/WAL；如果后续加入这些副本，也必须使用相同 staging
  allowlist。真实源文件只读，永远不作为删除目标。
- 输出独占创建，碰撞不能覆盖或误删已有输出。已属于本轮 staging 的文件
  在本轮消费窗口结束后统一清理；未知来源文件不能仅因名字相同就删除。

## 与正式 staging/generation 的映射

已审计既有 `snapshot.mjs`：acquire 在解密前 cleanSlate；recover 在 startup
清理旧 staging/generation；cleanup 删除消费完的 generation；所有 mutating
操作串行。对 staging 的整体回收也涵盖未来新增的加密合并文件和 sidecars。
本轮以原有 runtime/lease 测试回归这些行为，没有改变原 helper。

3.5J 接入时仍须落实这些已经确定的接口规则：同一受控 snapshot root 只有一个
活跃 owner；hardened 合并和解密只写 staging；加密副本在发布前删除；
发布后由既有 generation lease 在消费结束清理；startup/下一次 acquire 先 recover；
清理失败不能返回成功或使用旧 generation。正式 helper 的 best-effort
discardStaging 不能被解释为“清理已成功”，其遗留必须由 fail-closed recover
处理。本轮未将独立 harness 直接接入或改写正式 generation API。

## 测试与准入判断

虚构 RED → GREEN 覆盖正常/异常清理、真实 subprocess 强杀后重取、OS lease
跨进程竞争、未知根/未知 staging、源目录重叠、输出碰撞、cleanup 失败后阻断
及恢复、root/staging junction 和 marker 写入失败。测试不使用真实 QQ 数据。
重跑 main/WAL focused integration、runtime/lease focused 与 Fast Suite；
diff-check 同时覆盖 tracked 和本轮 untracked 文件。

两个遗留准入问题已得到本轮证据支持：真实 QQ 的 SHM/prefix/boundary guard
成立，受控 staging 的正常及强杀生命周期可验证。因此具备进入 3.5J 正式接入
开发的条件。此结论不等于正式链路已上线或接入后免于新的回归/真人验收。
