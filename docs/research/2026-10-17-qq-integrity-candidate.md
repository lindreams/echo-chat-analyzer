# QQ integrity 现场候选 1：交付与结果使用

基线为正式 v0.2.2，分支为 `fix/qq-snapshot-integrity-v022`。保留 Header 18/19
转换、WAL 稳定性见证、只读 quick_check、凭据及明文清理保护。
本候选补齐一次本地检查的可执行交付链路；**尚未证明现场故障根因，也没有宣称连接已修复**。
前期依据见 [快照研究记录](2026-10-17-qq-snapshot-integrity.md)。本轮未扩大虚构数据库规模。

## 交付文件与一次运行

独立便携候选位于任务工作树的 `build/integrity1-final-delivery/`，不进入正式 Release，也不覆盖已安装版本。

- 文件：`Echo-0.2.2-qq-integrity1-windows-x64.zip`，108328880 字节。
- SHA256：`452f1169c6fea8dbb855e36a398c7d391281d3fe331e393773f58bb8d299e7cb`。
- 解压到新目录，关闭其他 Echo，双击 `Run-QQ-Integrity-Check.cmd`。
- 在 Echo 中按正常流程连接 QQ，等待会话列表成功或失败，然后正常关闭 Echo。
- 命令窗口显示本次 `check-...` 目录；只回传其中的 `integrity-result.json`。
  不回传整个目录、应用日志、截图、聊天数据库或运行状态。

运行入口与说明源文件保存在 `scripts/qq_integrity_candidate/`。每次启动创建唯一的检查目录，
仅为本进程设置独立 LOCALAPPDATA，隔离 Echo 配置和运行时工作目录；正常 QQ 登录继续使用
本机 QQ 资料位置。无需安装开发工具。直接运行内部 Echo.exe 不启用检查。
候选内部版本仍为 0.2.2，外层文件名及启动入口明确标识候选 1；不制作更新源或安装包。

## 实际取证边界

1. 显式开启 `ECHO_QQ_INTEGRITY_CHECK=1` 时，捕获层在内存记录选中页面的主库/WAL 来源。
   NapCat 解密完成后、Header 转换和原有加密中间文件删除前，从**同一个已捕获合并文件**逐页
   独立解密，对比 NapCat 输出。按 256 页分批读取，只累计来源页数、有效区不一致页数及
   Header 相等布尔值。SQLite reserve 48/80 与固定 48 字节加密尾部分开处理。
   前后验证副本文件状态；检查失败输出固定 unavailable/unstable，不输出异常文本。
2. 密钥仅在原有 NapCat 进程内取自既有 API，复制到本检查拥有的 Buffer，结束时清零；
   不清零借用的原 Buffer，不交给 Python，不写入 manifest、结果、环境或日志。
3. Python 在原有 quick_check 之后、清理之前，只对已验证 generation 做一次额外的 `mode=ro`
   quick_check，并将返回文本立即映射成固定类别。记录页面大小、reserve、Header 页数是否
   有效/匹配物理页数、freelist 页数、读写版本、schema format、文本编码和 auto-vacuum 布尔值。
   不输出原始 SQLite 文本、表/索引名、页内容、故障页号、账号、聊天正文、路径、密钥或数据库哈希。
4. 结果先只留内存；原有 cleanup 执行之后独占创建指定 JSON 文件。`cleanup=confirmed` 必须同时满足
   cleanup 正常返回与 generation 目录消失。失败为 not_confirmed，原有异常继续向上返回。
   文件创建失败不替代原始连接或清理结果；已有文件不覆盖。每个 Echo 进程最多输出一次。
5. 未到 SQLite 校验就关闭应用时，启动器只生成 `initial_check=not_reached`、
   `cleanup=not_observed` 的固定结果，不推断数据库状态。

原始主库及 WAL 不写入。新增检查不创建数据库或页面副本，不改变原有明文文件的清理所有权；
与原有处理一样，进程被强制终止时仍由原有启动恢复清理处理，不能把诊断文件存在视为清理证明。
manifest 中可选的计数字段与原 generation 一并删除。常规应用日志不属于可分享的诊断结果。

## 收到结果后的修复路径

| 固定结果 | 下一步生产修复依据 |
| --- | --- |
| `page_verification.status=verified` 且某来源 mismatch 非零或 Header 不同 | 优先定位解密输出兼容性及该来源页面处理；保留原检查，按实际差异制作虚构 RED 样本后修复。 |
| 页数/布局不匹配 | 对应捕获页数、提交 Header、输出转换链路，修复已证实不一致的边界。 |
| 页面逐字节一致，`category=btree/cell_layout/overflow/freelist/page_reference` | 解密输出符合当前参考算法；不能据此证明主库/WAL 全局视图正确。优先调查快照视图一致性，使用已研究的 QQ 进程内只读事务/原生备份方案核对可行性，避免继续扩规模。 |
| 页面一致，`category=constraint` | 优先定位约束/SQLite 数据语义兼容性，区分结构错误与数据约束失败；不能忽略检查或直接放行。 |
| `unknown/check_error/probe_error`、验证 unavailable/unstable 或 not_reached | 明确指出哪项证据缺失；只补该项本地验证，不宣称根因，不重新开展无边界覆盖研究。 |

`repeat_matches` 只表示两次检查的通过/失败一致，不表示错误文本或故障原因相同。
页比较是当前参考解密算法与 NapCat 的比较，不能排除二者共有的算法缺陷。
结果也不包含故障页定位，不能从一个 mismatch 计数猜测具体页面内容。
未收到朋友结果前，没有证据支持修改生产捕获/解密算法。

## 构建与验证证据

复用已验证工具链，不安装或升级共享环境。为本工作树生成独立 setuptools dist-info 并通过
构建进程的 PYTHONPATH 使用它，确认源码导入和版本均来自本工作树；不改其他开发线的 editable
安装。PyInstaller 6.22.3、hooks 2026.8、Velopack 1.2.161。
NapCat 从哈希固定的官方 4.18.34 ZIP 重建，更新后的插件模板哈希同时进入源码 pins、程序目录及
Frozen 内置 pins。微信程序资产通过既有构建合同核验。

使用 `build_windows_exe.ps1` 的独立 dist/work 输出，随后用现有 `package_windows_portable.py`
验证便携程序树，在外层附加三个固定启动/说明文件。逐项验证 ZIP 原便携内容不变、附加文件匹配
源码、没有重复 ZIP 条目，再计算候选 SHA256。未安装或发布候选。

- 历史服务代码运行同一现场输出测试：两项 RED，均因缺少 JSON 文件；当前实现通过。
  这证明诊断链路补齐，**不是现场故障修复的 RED → GREEN**。
- 虚构 SQLite 的真实 NOT NULL、freelist、b-tree 损坏分类，以及固定文本分类、关闭选项、
  清理失败、恶意 manifest 附加字段、独占输出、一次性输出和启动器隔离测试通过。
- 故意改变主库/WAL 来源的解密输出，准确累计对应来源的不一致页面；借用密钥 Buffer 保持不变。
- 原有复杂虚构样本继续使用既定规模和固定 NapCat 解密函数，同时启用新页比较；无额外场景扩张。
- 226 项快照捕获、运行时、租约、校验、清理与 Facade 回归通过，包含正常群聊/私聊各自分析到
  报告，以及损坏快照拒绝；另 48 项凭据、worker 代际、分析范围与单 generation 回归通过。
- 对实际 EXE 的 PYZ 提取代码对象，核对诊断模块及服务模块与本工作树编译结果一致；
  提取出的诊断代码执行 23 项测试通过。31 项 Frozen/Windows/NapCat 构建合同检查通过。
- 实际 EXE 在隔离用户目录下启动，窗口出现后发送正常关闭消息，退出码 0；程序树前后逐文件
  哈希不变，未触发 QQ 登录或生成快照。此项只证明程序启动/关闭，不证明真实 QQ 连接。
- 最终启动器使用 Normal 显示需要交互的 Echo 窗口；实际启动器与真实 EXE 联动验证窗口可见、
  正常关闭退出码 0，并输出固定 not_reached JSON。该验证未请求 QQ 登录，不把它当作连接成功。

日志、构建元数据、程序目录、验证摘要和候选 ZIP 仅保留在本工作树忽略的 `build/` 下，供本任务
人工转交和复验；本分支保留到朋友结果驱动的生产修复完成及审核后再决定去向。未合入 main，
未操作 0.3.0 工作树，未读取真实聊天数据或用户配置。
`integrity1-delivery/` 中的早期外层包装仅作构建记录，已被 `integrity1-final-delivery/` 替代；
转交朋友时只使用上文最终 SHA256 对应的 ZIP。
