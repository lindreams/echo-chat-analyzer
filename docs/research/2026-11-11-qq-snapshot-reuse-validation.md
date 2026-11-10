# QQ 已验证快照复用：实现与验收

基线：main `c20bab3`。本次仅改变 Direct DB 快照的持有、消费和清理；
不修改 Main/WAL 捕获、解密算法、manifest 准入、quick_check 参数、会话 SQL、
消息统计或媒体恢复语义。成果供独立分支审核，不作为发行验收。

## 租约策略与安全证据

- 每次列表刷新仍创建新 generation，执行原有 manifest 验证和完整 quick_check。
  验证前先固定 snapshot.db 和 manifest.json，成功查询、补齐名称后才允许保留。
- 进程内最多保留一个 generation，列表完成后最多等待 120 秒，限下一次群聊分析消费一次。
  消息物化后立即清理，再进入原有报告链路。连续第二次分析、私聊分析和刷新均重新获取。
- 复用绑定原 client、启动凭据、runtime_id、boot_id、应用连接 epoch、账号和 generation。
  认证 lease RPC 检查原工作区独占 lease、原生登录连接证据、在线账号和文件保护。
  登录连接、断线、退出、SelfOffline、KickedOffLine 回调均使旧连接证据失效；
  即使当前 UIN 与 online 已恢复也不能复用。无法注册原生观察者时仅走新获取流程。
- 隐藏 PowerShell helper 以 Windows FileShare.Read 持续持有两个文件，拒绝写入、删除和替换；
  对照句柄文件 ID 与路径文件 ID，拒绝多链接、reparse 和 SQLite 辅助文件。
  所有权和连接证据在消费前、物化后复核。TTL、文件大小、mtime 均不作有效性证明。
- 应用串行化列表与分析的消费生命周期；后台到期与前台请求共享准入锁。
  显式断开／重连先封闭新任务准入、释放旧租约，再执行连接 I/O。
  原 Worker 失效后旧 client 不得向新 Worker 发送复用或清理请求，须显式重连后 recover。
- runtime 对 pin、待选、消费阶段分别设置 900、120、650 秒上限；文件 helper 自身也有
  900 秒上限，父 Worker 退出的 stdin EOF 会释放句柄。到期或保护丢失拒绝复用。
  正常到期、取消、异常、断开和退出执行 cleanup；清理失败保持错误，不能伪装成功。
  系统强杀或清理失败留下的明文仍依赖下一次合法 recover，不保证崩溃时磁盘残留立即消失。
- 无效租约先释放，再走原有安全获取；新的获取失败时直接失败，绝不回退旧 generation。

主要施工位置：
[应用生命周期](../../src/qq_chat_analyzer/application/qq/qq_direct_database_import_service.py)、
[runtime 生命周期](../../scripts/qq_direct_db_snapshot/snapshot.mjs)、
[文件保护](../../scripts/qq_direct_db_snapshot/snapshot_guard.mjs)、
[Windows 句柄](../../scripts/qq_direct_db_snapshot/snapshot_guard.ps1)。
Facade／GUI 仅传递取消信号，并在显式连接操作前释放租约；新 helper 纳入现有 runtime manifest 与 hash pins。

## 同 generation 对照方法

[test_qq_direct_snapshot_reuse.py](../../tests/test_qq_direct_snapshot_reuse.py)
使用人工构造的两个群、同秒消息和 PIC 样本，经真实 HTTP bridge、真实 Windows 工作区 lease、
真实 Main/WAL 捕获与 generation 发布、真实 quick_check 和 SQLite 查询、原有 Facade 报告链路运行。
没有启动 QQ／NapCat，也没有读取真实聊天数据库、账号或用户配置。

这是实际磁盘 generation 的对照，不是仅断言 mock 调用：列表后记住实际 generation 名称和文件，
分析期间捕获 provider 打开的路径；第一次分析必须使用同一名称，随后文件必须被清理。
第二次强制新获取必须使用不同名称。比较两次完整 payload 与报告视图，覆盖消息数量、
稳定顺序、发送者身份、统计和内嵌图片字节；预期消息 ID 顺序明确为人工样本的 201、202、203。

边界：原生 DatabaseApi 解密入口沿用现有测试 seam，输出人工选定的明文；
测试没有运行真实 QQ 原生解密器。测试证明 generation／租约／报告行为，不证明 6.7 GB
数据库的实际节省时间、真实账号连接表现或所有 Windows 安全软件环境下的可用性。

## 结果记录

2026-11-11，Windows x64，Python 3.13.9、Node 24.16.0；显式使用项目虚拟环境，
核对源码导入位置及已安装依赖后执行。以下仅为约 12 KB 人工样本的一次实测，不能外推大库速度。

| 指标 | 实测 |
| --- | ---: |
| 列表总耗时 | 1.656 秒 |
| 复用分析：选群至报告准备 | 0.524 秒 |
| 新获取分析：选群至报告准备 | 1.658 秒 |
| 复用分析：选群至报告完成 | 1.933 秒 |
| generation 的数据库与 manifest 合计 | 12,529 字节 |
| acquire RPC 返回至 cleanup 完成 | 0.999 秒 |
| 列表租约授予至 cleanup 完成 | 0.418 秒 |

“报告准备”以 ANALYZING_REPORT 回调为边界，包含查询、物化、清理和身份补齐；
不包含后续报告分析。保留时长以可观察的 RPC／应用边界计量，非源数据库捕获起点。

| 累计调用次数 | snapshot_acquire | quick_check |
| --- | ---: | ---: |
| 列表完成 | 1 | 1 |
| 首次同 generation 报告完成 | 1 | 1 |
| 后续新 generation 报告完成 | 2 | 2 |

- 复用、连接代际及 runtime wiring 定向回归：58 passed。
- 连接准入最终补充回归（取消／异常／退出／重连、Facade）：47 passed。
- 独立卸载 broker 回归：17 passed。
- 最终同 generation 完整报告对照：1 passed，包含上述指标。
- 最终源码 Frozen 构建 native exit code 0；对照嵌入归档确认全部修改的 Python 模块与源码一致，
  并逐项核对源码、candidate、Frozen 的模板 hash pins。
- 最新 Frozen、Windows runtime、Setup 打包合同：38 passed。
- Full：2456 passed、11 skipped，819.49 秒，无失败。
  跳过项为 Windows 符号链接权限 4 项、固定默认 dist 路径的 Portable 二进制检查 1 项、
  未提供固定 NapCat 审计 ZIP／验证 Node 的检查 4 项、未提供原生 WCDB CLI 的检查 2 项。
  Frozen 检查通过环境变量指向本轮新产物，包含在本次 Full 中；上述 38 项另对最终产物复验。
- 最终 Frozen 在独立用户目录、副本中启动，经精确 PID 与主窗口标题正常关闭，native exit code 0；
  包内 snapshot_guard 完成 pin／check／release，退出后未见残留 Echo 进程。
  未启动 QQ／NapCat，未启动既有发行目录中的程序。

回归运行中的问题均保留记录：首轮 Full 的 helper 依赖 fixture 缺漏与旧测试预期已修正；
同轮卸载 broker 因并行 Frozen 冒烟中的 Echo 进程而按设计拒绝，分开重跑后通过。
Frozen 自动关闭脚本曾选错隐藏窗口，改为仅关闭本次启动进程的精确主窗口标题；
失败尝试已回收本次 Popen，未操作用户进程。没有据此修改无关业务代码。

可复现的核心命令：

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
& .\.venv\Scripts\python.exe -m pytest tests/test_qq_direct_snapshot_reuse.py -q
& .\.venv\Scripts\python.exe -m pytest -q
```

Full 和定向运行的原始日志、JUnit 指标及最终 Frozen 产物在本地保留待审核，不纳入 Git。

## 人工验收留项

在用户本机由人工用同一账号、同一时间范围、同一筛选条件对照新旧流程：

1. 记录列表总耗时及 snapshot_acquire、quick_check、group_query 分项。
   列表完成后立即分析，累计 acquire 与 quick_check 应仍各为 1；第二次分析应各增至 2。
2. 记录选中群到消息物化／报告准备和最终报告完成的额外等待，不能把文本分析时间归入快照收益。
   预期消除现场后续分析约 313 秒中的再次获取与校验，具体收益尚未实测。
3. 记录 generation 发布、列表返回、选群、cleanup 的时间及数据库／manifest 磁盘字节，
   验证仅一个待选 generation、120 秒到期清理、消费后清理和没有永久明文缓存。
   同时记录应用、Worker、保护 helper 的峰值工作集及私有内存；本轮没有大库内存实测。
4. 比较消息数量、ID 顺序、身份、统计及图片结果；记录账号切换、短暂断线重连、Worker 更换、
   列表与分析并发、各阶段取消和应用退出后的文件、句柄、子进程与清理状态。
5. Setup 安装、更新、跨机器与真实 QQ 会话的人工验收不属于本轮已验证结果。
