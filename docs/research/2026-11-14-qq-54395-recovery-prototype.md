# Windows QQ 54395 恢复专项：独立来源原型与启动拒绝

日期：2026-11-14。研究分支：`spike/qq-independent-source`。
这是来源组件施工记录，不是 QQ 恢复上线或 54395 实机通过声明。
本机续验已获授权，见末节；备用机、虚拟机和预先提供密钥不再是开发前提。

## 已完成的施工

1. `scripts/spikes/qq_windows_source.py`：独立 Windows QQ 来源原型。
   不接入正式 GUI，不调用 NapCat/SnowCat API，不启动 QQ 或访问进程。
2. `scripts/spikes/qq_windows_source_check.py`：针对新来源接口的一次小型虚构验收，
   复用既有 fixture builder、codec、QQ Provider 和 Adapter。
3. `qq_auth_bridge.py`：给现有客户端启动路径补上 54395 起的安全拒绝政策，
   并把资源检查前移至等待日常 QQ 退出和清理旧连接之前。
   调用启动器前仍复核同一份资源。

### 可以直接使用的既有部分

| 能力 | 本轮处置与证据边界 |
| --- | --- |
| 独立 codec | 直接导入 `qq_independent_codec.mjs` 的 decode；不重写 AES、KDF 或 HMAC |
| 跨实现验证 | 沿用[互操作记录](2026-11-14-qq-sqlcipher-crosscheck.md)及[截断修正记录](2026-11-14-qq-54395-source-investigation.md)：WCDB/SQLCipher 双向互读、逐页认证、错钥与参数拒绝、标准 SQLite 可读、可信页数及完整 integrity_check；本轮不重跑算法实验 |
| QQ Provider / Adapter / 分析和报告 | 保持现有实现；新来源连接直接返回 QQDatabaseProvider。虚构验收只检查新增接入到 Provider/Adapter，没有再实现分析或重跑报告闭环 |
| 现有安全快照 | 继续保留其 SHM 见证、提交边界、所有权及清理能力；本原型只接收冻结 main，不声称已经脱离 runtime 复用了活动捕获入口 |
| qq-local-interface | 固定 `587b63e880070849240dde3f2bc447d7a7e8b35a` 的 macOS 验收支持独立处理的工程可行性；不是 Windows 54395 密钥来源，不移植其 LLDB 接入或长期 Vault |

## 原型接口和实际行为

```text
doctor（可选显式 QQ.exe）
  → Windows/架构/Node 可用性；只读复用 QQ 资源元数据解析
locate（显式数据根目录）
  → 有界检查直达库、nt_db、nt_qq、nt_qq_* 及 {account}/nt_qq/nt_db 布局
  → 不透明 database_id、格式候选/缺钥/拒绝状态
connect（明确库选择，可选本地 key 文件）
  → 无 sidecar、文件身份和大小检查
  → 自有临时副本 → 已有 codec（加密候选）
  → 可信页数 + 完整 SQLite integrity_check + 必需 QQ 列
  → 现有 QQDatabaseProvider → 现有 Adapter / 分析调用者
  → 上下文结束清理临时副本
```

- 不扫描默认用户目录、不读登录库、不自动选账号；多库必须明确选择。
- 目录、消息库和 key 文件拒绝符号链接/reparse point；消息文件拒绝硬链接。
  拒绝 UNC/设备路径；不把这些检查扩大为完整 Windows 路径/ACL 安全验收。
- 识别扩展头只返回 `key_required`，不算认证成功。没有密钥时不假装空会话。
- 当前接受显式 key 文件的 `{kind: passphrase|raw, value: ...}`；raw 为 32 字节十六进制。
  密钥不进入命令行、日志、报告或持久配置；通过私有子进程 stdin 交给已有 codec。
  此接口是后续授权取钥组件的接入点，不是已经实现自动取钥。
- 子进程隔离用户目录并移除 Node 自动加载选项；不执行社区二进制。
- 来源只读，SQLite 查询只作用于临时副本。遇到 WAL/SHM/journal 一律拒绝，
  不合并、不忽略、不修改原库或页头；WAL 模式页头仍拒绝。
- 研究原型限 64 MiB，超限拒绝，不截短；没有做大库优化。
- 输入必须由获准的正常关闭/检查点等流程冻结。文件状态检查不等于活动数据库一致性证明，
  也不能证明本地包含全部云端历史；不应用于日常 QQ 活跃目录。
- 自有临时目录不是完整 Windows ACL 隔离方案。按最新授权，在当前电脑进行只读预检；
  真实进程访问、取钥和正文读取仍分别需要明确批准。本人身份仍需来自可信输入，不从昵称或频率猜测。

从仓库根目录，使用 DEVELOPMENT 已验证的 `.venv` 和目标 `src` 导入路径：

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
# 以下目录/程序均须明确属于隔离实验；不填日常 QQ 的目录。
.venv/Scripts/python.exe scripts/spikes/qq_windows_source.py doctor --qq-executable <lab-QQ.exe>
.venv/Scripts/python.exe scripts/spikes/qq_windows_source.py locate --data-root <lab-data-root> --work-parent <separate-lab-work>
.venv/Scripts/python.exe scripts/spikes/qq_windows_source.py connect --data-root <lab-data-root> --work-parent <separate-lab-work> --database-id <selected-id>
```

加密输入无 key 时，最后一条返回 `state=refused, code=key_required`；已获准的私有 key 文件可通过
`--key-file <lab-private-key-file>` 传入。命令不打印会话名称、账号、正文或 key；
即使连接成功也明确输出 `qq_54395=not_verified`，避免把文件格式通过当成客户端版本验收。

## 正式启动路径的具体风险与修正

修正前最低 build 检查为 40768，54395 能通过；尚未做版本检查就可能先等待用户退出日常 QQ。
资源元数据不明时，部分拒绝也迟到真正调用 launcher 阶段。
本轮先用虚构 base/热更新资源复现，再修改此准入顺序。

现在：

- `build >= 54395` 返回 `qq_version_unsupported`，提示等待 Echo 兼容更新，
  不建议反复重试或改装日常 QQ。
- 不能确认当前资源的版本/入口则拒绝；已支持范围内的启动、取消、代际和资源变化复核保持原路径。
- 拒绝发生在等待日常 QQ 退出、生成 bootstrap、生成凭据和启动子进程之前。
  前置流程仍可能准备 Echo 自有工作区，不是整个操作绝对零写入。

这是对内置 launcher 的保守准入政策，不是证明 54395 及所有更高版本都存在同一故障，
也不是证明更早版本全部兼容。独立来源组件不使用这个 launcher gate 作为数据库格式判据。

源码读取还确认：Echo 自身生成的 package/bootstrap 写向自有 work_root，
没有在该 Python 路径直接覆盖 QQ 安装文件；进程冲突检测只等待，
清理由已登记 Job/自有进程 owner 执行。这些不能代替第三方 launcher 在真实 54395 的行为验收，
因此本轮没有调用它。未宣称已证明所有启动副作用都不存在。

## 上一轮隔离环境评估（不再作为开发前提）

只读查询 CIM、命令/模块可用性及系统功能状态，没有扫描账号或查询聊天文件：

| 观察 | 本轮结果 |
| --- | --- |
| 系统报告 hypervisor 存在 | true |
| CPU 的 firmware virtualization / SLAT 标志 | 返回 false；在 hypervisor 下不能据此断言 BIOS 未启用虚拟化 |
| Hyper-V 管理模块 | 未发现 |
| Windows Sandbox 可执行程序 | 未发现 |
| VirtualBox / VMware 管理命令 | PATH 未发现；不代表所有目录都不存在安装 |
| 可选功能状态 | 当前查询权限不足，未知 |

目前没有证据支持直接创建一台可用测试机。未启用系统功能、修改启动配置、下载安装 QQ/虚拟化软件，
未复用可能属于日常工作的虚拟机或 WSL。没有把“hypervisor 存在”写成实验环境已准备好。

## 下一段密钥获取施工的边界与真正所需条件

不要求负责人先提供现成密钥。按最新授权在当前电脑继续；获得具体进程访问批准后，验证普通只读接入能否在 54395 成立：

1. 用户明确批准指定本机 QQ 进程的访问范围，核对其账号用途、官方版本、实际模块和数据库归属；
   不做全机账号扫描，不把 PID/进程名本身当成授权。
2. 仅申请所需查询/读取权限；不启用 SeDebugPrivilege，不提权，不调试启动、不注入、不改签名/文件，
   不请求写入内存或创建远程线程权限。权限拒绝、身份变化或保护阻止读取即停止。
3. 在获准范围内验证候选读取条件；候选必须通过目标数据库页面认证，
   再由现有完整解密和 SQLite 检查验证。不能把匹配 salt/可打印字符串直接当成 key 成功。
4. 先仅验证专用消息库，不复制登录状态、整份进程 dump 或无关辅助库。

Windows 官方 [OpenProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess)
按目标安全描述符检查请求权限；
[ReadProcessMemory](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-readprocessmemory)
要求读取权限且拒绝不可读范围。接口存在不证明 QQ 54395 会允许访问或内存中存在可定位的匹配 key。
本轮没有实现或执行进程取钥，也没有用这些通用 API 的文档冒充 54395 实证。

前轮 Windows 旧版本扫描源码只作为后续候选方法参考，不能当作当前 build 成功。
`qq-dump` 本轮核对仍是前轮同一提交 `22533d048602dbf5594a1fec9b443ec54e70230b`，没有新增输入证据；
不继续重复搜索旧工具。macOS LLDB、完整框架、未知来源 key 包不作为替代。

上一轮提出的外部条件已由本机续验方案替代；当前需要的是分步批准：

- 先批准仅查询本机 QQ 进程元数据，用于核对程序归属；不读取命令行、内存或密钥。
- 取得进程归属证据后，再单独审阅有界只读取钥操作的目标、权限、影响及资源释放办法。
- 如需产生消息验收，由用户决定本机账号及聊天范围；未经明确批准不读取私人聊天。

当前未操作本机 QQ 进程，不能判断 54395 是否允许该访问，也不能验证真实 key 的生命周期。
本机只读预检已完成；进程访问批准是下一步操作边界。

最小实机验收：一份专用账号的小库、已知私聊/群聊清单、重开前历史消息；
原始加密字节与模块/数据库哈希留隔离本机。通过获准的读取条件接入后，
验证每页认证、可信页数、完整 SQLite 检查、消息语义和现有报告产物。
若只能提供活动 WAL，先停止 main-only 实验，再单独评估复用现有安全捕获；不得静默忽略 WAL。

## 本轮验证与交付状态

- `.venv` Python 3.13.9、目标源码导入和依赖检查通过；未安装依赖或处理 jieba。
- 启动门禁及相关 base/热更新/取消、setup、runtime wiring 和连接准入测试：101 passed，
  7 个 slow integration 未运行；没有运行需要真实客户端或归档的验收。
- 扩大验证初次在较长临时根目录下有 15 个 workspace 准备失败；缩短临时根目录后该组准备成功。
  随后暴露启动方法直接调用时的回归：提前返回跳过了原有迟到凭据回收验证。
  已恢复这一入口的 launcher 准备，并与前置准入共用同一方法；上述 101 项复验通过。
- 新来源接口验收：虚构资源 doctor、有界定位、无钥拒绝、已有 codec → Provider → Adapter、
  错钥拒绝、sidecar 拒绝、多库选择拒绝、源哈希不变、临时连接副本清理均通过。
- 新原型首轮发现 Windows Python stat/fstat 的 ctime 语义不同；已核对同一文件的返回值，
  改为跨 API 比较 file identity/大小/mtime，同时各自保留前后 ctime 检查；复验通过。
- 上一轮没有实机访问；本轮仅完成下述本机预检，没有取钥、真实报告或 Frozen/Setup 验收。

来源组件、进程探测工具及其验收脚本经下一阶段授权审核后本地提交；
此前启动准入的三个正式源码/测试修改独立待审，不纳入这次来源工具提交。不 merge 或 push。
main 及微信源码不改。无关未跟踪 `Microsoft/` 保留；自有忽略实验目录保留失败复现、
虚构样本和验收回执供审核，决定后再处置，不进入发行或正式运行时。

## 本机续验：实际安装与数据库预检

本轮只修改来源 spike、它的小型验收脚本和本文档；上一轮启动准入改动保持原状。

- 注册安装项指向的主程序 PE 为 9.9.31.49738；复用现有资源解析，确认当前启用的热更新资源为 **9.9.37-54395**。
  未把旧 PE 版本当成当前资源版本，也没有执行 QQ 或 native 模块。
- 标准文档数据根下找到一份 `{account}/nt_qq/nt_db/nt_msg.db`；消息主库为 422912 字节。
  读取固定 16 字节 magic，识别为 QQ 扩展头，大小满足候选 1024 包装头 / 4096 页对齐。
  未读取 salt、消息页、账号配置、数据库表或正文，未复制真实数据库。
- 观察时没有 WAL/SHM/journal；这不能证明冻结、完整历史、匹配密钥或该库属于当前运行的 54395 进程。
- `WindowsQQSource` 已补上上述 Windows 实际布局；扫描有界，超限拒绝。
  新 `inspect()` 只读取 16 字节（无缓冲打开，避免应用缓冲预读），sidecar 仅取文件元数据。
  预检允许报告存在 sidecar，连接路径仍严格拒绝；两者没有共享“忽略 WAL 后连接”的开关。
- 新 CLI 必须显式执行 `inventory --inspect-local-host --work-parent <owned-work-directory>`。
  只从固定 QQ 安装注册项、常见安装位置及已知用户文件夹定位；不做全盘扫描、QQ 进程枚举或框架 API 调用。
  私人路径只在本机内存中使用；输出版本、脱敏布局、文件大小、sidecar 状态和不透明库 ID。
  固定位置发现不代表覆盖自定义数据目录；未知位置需用户显式指定，不扩大扫描。
- 新接口虚构验收覆盖实际目录形状、有 sidecar 时的 16 字节读取上限、不调用连接、脱敏输出、
  输入字节不变、环境恢复与临时数据清理；另验证 UNC 在文件系统访问前拒绝。
  本机预检的脱敏回执仅留忽略实验目录，不将私人路径或真实数据写入本文档。
- 本轮复核资源解析相关定向测试：29 passed，3 个 slow integration 未运行。
  来源接口及自有 Python 子进程的模块检查均通过；没有重复执行 codec 跨实现实验或报告闭环。

随后获得两次单独批准，并完成：

1. CIM 仅查询 QQ.exe 的 PID、父 PID、创建时间和可执行路径；发现一个主进程及七个子进程，
   全部路径匹配注册安装。未请求命令行，未保存私人路径或 PID。
2. 新 `qq_windows_process_probe.py` 先在本次创建的 Python 子进程上验证模块查询、
   路径不符拒绝及句柄释放；第一次自验因系统 DLL 具有硬链接触发已有守卫，
   核实原因后改用自建子进程自身 EXE 作验证目标，没有放宽守卫。
3. 对获准 QQ 进程组申请 `PROCESS_QUERY_INFORMATION | PROCESS_VM_READ`（0x0410），
   只使用 QueryFullProcessImageNameW、K32EnumProcessModulesEx、K32GetModuleFileNameExW。
   八个进程均取得句柄；仅主进程加载了与当前 54395 资源完全相同路径的 wrapper.node。
   每个句柄均经 CloseHandle 成功释放。不调用 ReadProcessMemory，不扫描业务内存、不取钥。
   这仅证明路径匹配和句柄权限，不证明加载模块字节与当前磁盘文件完全相同，也不证明所有内存区域可读。
4. 首次执行时进程组数量前置检查拒绝，尚未打开 QQ 句柄；随后在已批准的 CIM 范围内重新核对为八个进程，
   再完成上述检查。未遇到后重试客户端访问拒绝，未提权或绕过保护。

模块查询参考 Windows 官方 [EnumProcessModulesEx](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-enumprocessmodulesex)
及 [GetModuleFileNameExW](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-getmodulefilenameexw)；
模块 API 会查询加载器元数据，不能将其描述为完全不涉及进程内部状态。

取钥及任何正文验收仍未获准或实施。下一个目标已缩小至加载该模块的主进程，
但仍需确定候选密钥读取范围、读取上限及与库的归属/认证证据，再单独申请操作批准。
不应在尚无定位方法时直接扫描整个进程并声称“只读取密钥”；宽范围扫描可能经过私人内容的内存。
不再要求准备备用机或虚拟机。
