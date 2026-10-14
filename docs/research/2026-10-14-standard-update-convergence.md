# Echo 0.2.0 标准自动更新收敛

基于最新 main `7e45e81` 的独立分支，保留 PR #45 及其分支作为历史实验，不合并其协议、
Broker、IPC 或启动准入。采用既有 A2 安全退出和 A3 官方 Velopack 1.2.161 交接，本轮
不修改 QQ/微信分析业务，不访问真实聊天数据，不发布 Release。

## 当前功能

`application/update_channel.py` 提供 P1 固定仓库源、`Lindreams.Echo` packId 和
`win-x64-stable` channel，桌面显式注入现有 A3 服务。构造不执行 SDK/网络 IO；不从环境
或 GUI 输入选取更新源。Source/Portable 仍由原支持性检查拒绝应用内安装。
Setup 打包命令默认使用同一身份常量，隔离测试可以显式覆盖。

下载与安装前的 SHA256、大小、pending、包内 id/version/channel、安装身份及只读包句柄
保护保持原样。用户确认提示明确说明 Echo 将关闭、安装更新并自动重启；仍只允许空闲
会话提出更新意图，随后等待原 ShutdownProtocol。五项资源清理及 GUI worker 证据必须
全部 SUCCESS；失败、超时、UNKNOWN 不调用安装。通过后调用原
`wait_exit_then_apply_updates(..., silent=False, restart=True)` 并自然退出。
本轮不引入第二套退出/跨进程互斥机制，也不要求 PR #45 的实验先完成。

## packId 实际根因与修复

旧实验失败的身份是含日期数字片段的 `Echo.UserTest020.20261013.7f3c9a21`，其
Post-process 将 `20261013.7f3c9a21-0.2.0-…` 当版本解析。固定版本的
[ReleaseEntryName 解析器](https://github.com/velopack/velopack/blob/1.2.161/src/vpk/Velopack.Core/ReleaseEntry.cs#L40)
寻找文件名中第一个版本形状的数字对，可能误取 ID 内的片段。

本轮真实 vpk 使用新目录成功打包 `Lindreams.Echo`（退出码 0）；因此“所有带点 ID 均
不支持”的历史概括被实测纠正，不改 P1 正式身份。打包器仅提前拒绝会被该解析器误取
的数字版本片段，同时将长度上限对齐现有 feed 验证；不放宽包完整性校验。
回归先复现三类歧义身份抵达 vpk，再增加最小 preflight；普通点号 ID 的既有测试保留。

## 环境与验证

按本轮明确授权，仅对选定 Echo 环境原版本 `jieba==0.42.1` 做无依赖重装，修复缺失的
`dict.txt`。人工虚构文本分词成功、pip check 通过；未升级其他依赖或改分析代码。
所有源码测试显式选择解释器并将 PYTHONPATH 指向目标 worktree，Frozen 构建则选择
对应隔离副本及独立 dist-info 元数据，未改共享 Echo 发行元数据。
真实 A、B Frozen 包契约测试各 18 passed，包含 jieba 字典/model 数据及现有 runtime 合同。

正式源注入、确认提示和歧义 packId 均先 RED 后 GREEN。focused 最终 94 passed。
Fast 4086 passed、5 skipped（Windows symlink 权限/工作树原生资产缺失），随后最终
packId 细化另跑 focused。最终 Full 为 4545 passed、38 skipped、1 failed，未全绿。
唯一失败为 `test_qq_runtime_wiring.py::test_python_and_js_plugin_share_snapshot_root_and_refuse_old_clients`：
旧凭据请求遭 Windows 连接中止（WinError 10053），转换为 RuntimeUnavailable，测试预期
RuntimeUnauthorized；客户端仍拒绝请求。该节点单独重跑 1 passed，整个文件随后 29 passed；根因尚未确定，不能
以重跑替代 Full 失败记录，也未为此修改 QQ 代码或预期。其余 skipped 涉及工作树未带
Frozen/native/audit 资产及 symlink 权限；Frozen 合同另由上述 A/B 构建各 18 passed 覆盖。

## 真实隔离 Setup A → B

从本分支复制源码到新建实验目录，逐文件记录哈希。A 为 0.2.0，B 为 0.2.1；只在副本
替换实验 packId/channel、本地 feed、数据目录、版本/窗口标识、安装显示名与无快捷方式，
并记录五项退出结果。上述偏差及构建导入路径均记录在仓库外实验报告。
这两个构建先于最后的歧义 packId preflight 细化；实验身份明确覆盖，编译后的更新交接
路径不受该打包前拒绝规则影响。最终源码另由 focused/Full 验证。
复用固定 PyInstaller 6.22.3、hooks 2026.8、vpk/SDK 1.2.161；只复制经当前 pins、白名单
及隐私检查通过的程序 runtime，未复制账号、数据库、输出或配置状态。

真实 Setup 安装 A，GUI 检查并由实际 SDK 下载 B，缓存 SHA256 匹配；GUI 确认后实际
五项 SUCCESS，A 原生退出 0；官方更新器实际安装并自动启动 B，安装清单与 GUI 为
0.2.1，B 正常关闭的保留原生句柄观察到退出 0。1423 个安装文件及三个虚构数据文件
哈希通过。最初观察脚本误把安装根的 execution stub 当作 current 内文件；核对实际
布局后同时校验根 stub、Update.exe 和 current 内的全部包文件，没有跳过或放宽包验证。

最后用核验注册 InstallLocation 后的隔离 Update.exe 正常卸载该实验安装，退出 0；
实验注册项移除，虚构数据哈希不变。原始日志、数据、源码偏差及测试包保存在仓库外供
联合验收，真实安装、既有实验安装与用户数据均未修改。

## 验收范围

正常官方更新路径已验证，提交供 0.2.0 联合验收；实验包未签名，未发布正式 feed。
跨设备 GUI/Setup 与签名发行仍需人工联合验收。固定 SDK 的上游等待/目录强杀行为没有
改写，本轮按用户确定的标准机制范围验收，不承诺极端进程竞争互斥或将其作为架构依赖。
