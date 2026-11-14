# QQ 54395 单窗口候选密钥实验

本轮交付可运行工具，不宣称取得真实 QQ 密钥。上一轮来源与模块探测四个文件已本地提交为
`8b52c2d`；此前三个启动准入正式源码/测试修改仍独立待审，没有纳入该提交。

## 实现及复用

- `scripts/spikes/qq_key_candidate.py`：默认只输出操作计划；执行模式只读取一个明确给定的运行时窗口，
  一次进程打开、一次窗口遍历，不枚举账号、进程或虚拟地址空间。
- `qq_windows_process_probe.py`：将已有身份校验和句柄释放收敛为共享上下文；
  保留原模块探测接口，新增创建时间检查，避免把 PID 本身当成代际证据。
- `qq_key_auth.mjs`：仅经匿名 stdin 接收候选及加密页，仅返回认证计数。
  codec 新增首页面认证入口，直接复用原 `pageTag`；没有修改 encode/decode 或重新实现解密算法。
  只认证观察到的 main 首个加密页，不解密正文、不打开 SQLite、不形成快照或报告。
- 参考微信 `WeChatKeyService` 的单次生命周期、取消、截止时间、错误脱敏及唯一资源释放所有者。
  复用 Echo `windows_job.launch_owned_process` 和退出证据；QQ 目标只持只读句柄，
  绝不加入工具的 Job。取消只释放本工具的 Python/Node 进程树，不结束 QQ。
  微信 Hook、等待退出/重新登录、密钥环境变量和 stdout 传钥方式均未移植。

## 有依据的候选信号与当前缺口

已读的 MIT 项目 [qq-nt-export 固定源码](https://github.com/q957506633/qq-nt-export/blob/bec1504170f99e2752793320711c5653f3803670/scripts/ntqq_key_scan.py)
描述登录后可能残留 SQLCipher raw key 与 salt 的完整十六进制字符串。
本工具只识别完整 `x'<64 hex key><32 hex salt>'` 形状，再与指定库做 MAC 认证；
盐匹配只用于筛选，绝不作为密钥正确的结论。
上游读取全部可读区域、输出样本和明文密钥的做法没有移植，未复制其源码。
该表示曾用于旧版本，不证明 54395 会保留它，更不证明当前登录阶段仍然存在。

[qq-dump 的候选模块](https://github.com/miniyu157/qq-dump/blob/22533d048602dbf5594a1fec9b443ec54e70230b/cli/keyscan/scan.py)
另描述 HMAC 标记邻近的 16 字节可打印口令及聚簇启发式；
其[调用方](https://github.com/miniyu157/qq-dump/blob/22533d048602dbf5594a1fec9b443ec54e70230b/cli/keyscan/pc.py)
仍需读取进程的大量区域。这与 32 字节派生 key 是不同输入。
其移植来源存在许可证缺口，且当前没有 54395 实证，因此不复制、不添加邻近猜测或强扫描 fallback。

**缺少的是 54395 活动 codec 对象/凭据字符串的运行时定位依据。**
加载 wrapper.node 只证明目标模块；不知道对象的引用链、存储分配位置或确定的保留阶段，
便不能把任意堆页称为“密钥窗口”。本工具不假设固定地址，也不要求负责人提供现成地址或密钥。
当前没有可据此申请读取的真实窗口，故不提出泛化的业务内存授权请求。
需要继续获得可审阅的当前模块结构/对象引用线索，才能给出具体地址范围和单次实机申请。

## 执行合同

请求从 stdin 输入 JSON，字段为 `pid`、`executable`、`created_ticks`（Windows FILETIME 整数）、
`module`、`database` 和 `window`。路径必须为绝对本地路径。
`window` 包含运行时 `address`、`size` 和 `evidence=observed_codec_context`。
这些元数据只在内存/子进程环境传递，不含候选密钥，不写任务配置文件。
evidence 声明不是自动证明，更不是授权凭证；执行前仍须人工审阅来源与范围。

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
# 先通过 stdin 提供已审阅请求，默认只计划，不打开进程或数据库：
.venv/Scripts/python.exe scripts/spikes/qq_key_candidate.py
# 获得针对该窗口的明确批准后才可使用：
.venv/Scripts/python.exe scripts/spikes/qq_key_candidate.py --execute-approved-window --work-parent <owned-work>
```

没有 window、超限或缺少依据时，在打开目标前失败关闭。命令行开关不能替代负责人授权。

| 项目 | 硬性边界 |
| --- | --- |
| 目标 | 单个指定 PID；核对可执行路径、创建时间、当前 54395 资源及确实加载的模块 |
| 访问 | 0x0410 查询/读取权限；不提权、不注入、不写内存、不暂停、不调试启动 |
| 业务读取 | 一个已定位窗口，最多 65536 字节，最多 16 次 4096 字节 ReadProcessMemory |
| 页属性 | 仅已提交 MEM_PRIVATE、非 guard、非执行的只读/读写页；越界或部分读取失败即停 |
| 候选 | 最多 16 个完整 raw key＋salt；不猜口令、不扩区、不换进程、不自动重试 |
| 数据库读取 | main 前 5120 字节，前后各一次，合计最多 10240 字节；变化即拒绝 |
| 时间 | worker 8 秒；外层 10 秒截止，中止后的资源释放另有最多 3 秒预算 |
| 内存 | 原始读取缓冲最多 64 KiB，候选最多 16 个；解释器及 Node 自身运行时开销另计 |
| 取消 | Ctrl+C 或 cancel_event；只有 acquire 所有者释放工具 Job，并核验全树退出 |
| 输出 | 固定状态、计数和释放结果；不输出 key、salt、地址、PID、路径或原始 helper 输出 |

有限窗口仍可能包含私人字节，不能保证仅经过密钥；这一风险必须在真实读取申请中明确。
读取可能被系统或客户端拒绝，拒绝即停止，不绕过保护。失败无需恢复 QQ 文件或内存，因为不进行写入。
工具对可变缓冲做尽力清零，但 Python/JSON/Node 不可变副本、系统分页或外部转储无法作绝对清零保证。
候选不写文件、日志、命令行或环境；生命周期结束由独立工作进程退出，不保留候选缓存。
一次首页面 MAC 命中不能代替全库逐页认证、可信页数、SQLite 完整性及消息语义验收。

Win32 读取遵循官方 [VirtualQueryEx](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-virtualqueryex)
及 [ReadProcessMemory](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-readprocessmemory) 合同。

## 本轮验证与结果去向

`qq_key_candidate_check.py` 只启动本次自建 Python 子进程，随机 key/salt 经匿名管道传递，
不写密钥夹具。使用已有 encoder 生成一页虚构密文，不执行解密或报告闭环。
覆盖：缺少窗口拒绝、超限拒绝、默认只计划、跨读取块的候选捕获、错候选与同盐伪匹配拒绝、
创建时间失配拒绝、已创建 Job 后取消、硬截止退出、目标子进程仍存活、句柄与临时目录释放。
这些验证通过，不能外推为真实 QQ 取钥成功。

本轮没有真实 QQ 业务内存访问、没有真实数据库认证、没有新框架或正式链路改动。
候选工具和本文档经下一阶段明确授权审核后独立本地提交；新的来源与生命周期工作另行保留待审。
脱敏回执及虚构密文留本次忽略实验目录供审核，审核后决定处置。
不 merge、不 push，main 与微信不改，无关文件保留。
