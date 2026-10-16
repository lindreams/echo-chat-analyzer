# NapCat 与第三方版权声明

材料核实日期：2026-10-10。

本目录的 `LICENSE` 是 NapCat 原版许可证，适用于 NapCat，并非 Echo 自身的许可证。
各第三方组件保留其自己的版权及许可证；本声明不为它们重新授权，也不宣称整个发行包已经完全合规。

## NapCat 来源与版权

- 原项目：NapNeko/NapCatQQ，版本 v4.18.34。
- 原作者：Mlikiowa（上游许可证署名）；GitHub 账号 MliKiowa，以及 NapCat 项目贡献者。
- 项目：https://github.com/NapNeko/NapCatQQ
- 版本源码：https://github.com/NapNeko/NapCatQQ/tree/v4.18.34
- 标签提交：[`83c1d1d`](https://github.com/NapNeko/NapCatQQ/commit/83c1d1d)。
- 官方发行来源：https://github.com/NapNeko/NapCatQQ/releases/download/v4.18.34/NapCat.Shell.zip
- 上游许可证：https://github.com/NapNeko/NapCatQQ/blob/v4.18.34/LICENSE
- 版权：Copyright © 2024 Mlikiowa。
- 许可证名称：Limited Redistribution License for NapCat。完整文本保存在本目录 `LICENSE`，未改写。
- 原版 LICENSE SHA-256：`2bbc0dba0c62fcde4adfe38ebadad0b7d4e23b06b88d9551904bbe07769dc46f`。

官方 archive 和程序资产的来源摘要保存在 Echo 的 `scripts/qq_napcat_runtime_pins.json`。
完整来源 runtime 与 Windows Portable 的精确裁剪清单是不同的契约。
下文保留原核实日期的来源、Portable 裁剪与版权证据，不将历史 Portable 清单作为当前 Setup 资产清单。
当前发行状态及验证边界见 [HARDENING](../../docs/HARDENING.md)；本声明中的授权证据缺口仍须保留。

## Echo 的修改及集成

Echo 使用官方 Shell runtime，通过已有 QQ 安装启动和登录 NapCat，并使用本地 Direct DB 快照生成聊天分析报告。
Echo 的 `scripts/bootstrap_qq_napcat_runtime.py` 根据官方 pins 校验来源后，对 `napcat.mjs` 应用四处文本替换（G1 三处、插件白名单一处）：

1. 保留数据库凭据监听与后续 core 的关联；凭据延迟到达时更新 `core.dbPassphrase`，已有凭据也在 core 初始化时传入。
2. 将 `napcat-plugin-echo` 加入插件白名单，不放宽其他插件授权。

数据库解密一致性由 Echo 自己的 staging 输入强见证保证，不修改上游 native-read 实现。

Echo 自己的插件提供本机回环地址的状态、元数据和 snapshot acquire/cleanup/recover 接口，复用 NapCat DatabaseApi 进行解密。
相关程序来源：`scripts/qq_napcat_plugin/` 与 `scripts/qq_direct_db_snapshot/`。
Echo 的两条 QQ 启动路径仅在子进程环境设置 `NAPCAT_DISABLE_FFMPEG_DOWNLOAD=1`。
当时核实的 Windows x64 Portable 裁剪合同排除四个平台 FFmpeg Addon、九个非 Windows x64 native 文件和 AaCute.woff；
精确清单见 `scripts/windows_runtime_manifest.json` 的 `portableExcludedFiles`。
完整 NapCat 来源、官方 pins 和 bootstrap 来源校验保留不变。

## 上游对 Echo 集成方式的明确答复

- 授权咨询：https://github.com/NapNeko/NapCatQQ/issues/2096
- 原始答复：https://github.com/NapNeko/NapCatQQ/issues/2096#issuecomment-6050192807
- 答复者：MliKiowa。
- 答复时间：2026-10-08 01:19:38 UTC。
- 原文：**“没有问题”**。

该 Issue 说明 Echo 是免费、开源、非商业的本地工具，使用 NapCat v4.18.18 官方 Shell 包、少量 Direct DB/snapshot patch 和自有插件，
并保留 NapCat 许可证、版权和来源。询问事项是修改后的 runtime 随 Echo GitHub Release 分发，以及仓库保留 patch/bootstrap 脚本。
以上答复记录在该具体上下文中，不解释为对商业用途或未询问用途的无限授权，也不能代替第三方组件权利人的许可。
当前来源已升级为 4.18.34；保留上述 4.18.18 咨询事实，不将历史答复改写成针对 4.18.34 的新答复。

## 实际分发且有可核实授权材料的组件

下表记录原核实日期按 Windows x64 Portable 保留规则核对的组件，不构成当前 Setup 的完整资产清单。
所有 runtime 路径均相对 `runtime/qq-napcat-candidate/`。

| 组件 | 实际分发路径 | 可核实许可证与版权材料 |
| --- | --- | --- |
| DPAPI | `native/dpapi/win32-x64/@primno+dpapi.node` | 上游 v4.18.34 的 napcat-dpapi 包附 MIT；Copyright (c) 2023 Xavier Monin。全文见 `DPAPI-LICENSE.txt`。 |
| node-pty / prebuilt fork | `native/pty/win32.x64/conpty.node`、`conpty_console_list.node`、`pty.node` | NapCat v4.18.34 的 napcat-pty/package.json 声明 `@homebridge/node-pty-prebuilt-multiarch: ^0.12.0`；该项目 v0.12.0 的 LICENSE 为 MIT，包含 Christopher Jeffrey、Daniel Imms 与 Microsoft 的版权声明。全文见 `PTY-LICENSE.txt`。 |
| winpty | `native/pty/win32.x64/winpty.dll`、`winpty-agent.exe` | winpty 原项目 LICENSE 为 MIT；Copyright (c) 2011-2016 Ryan Prichard。全文见 `WINPTY-LICENSE.txt`。 |
| npm runtime 依赖 | `node_modules/` | 官方来源中按当时 Portable 保留规则核对共 69 个包实例：64 个声明 MIT、4 个 ISC、1 个 BSD-3-Clause。每个实例的名称、版本、路径、完整许可证及版权文本见 `NPM-LICENSES.txt`；原包内许可证也继续随包保留。 |
| JetBrains Mono | `static/fonts/JetBrainsMono.ttf`、`JetBrainsMono-Italic.ttf` | 两文件内嵌元数据标识 Version 2.304、SIL Open Font License 1.1；Copyright 2020 The JetBrains Mono Project Authors。全文见 `JETBRAINS-MONO-OFL.txt`。 |

npm 的 ISC 声明对应 inherits、once、setprototypeof、wrappy；BSD-3-Clause 对应 qs。
包实例包含 body-parser、type-is 与 negotiator 目录内各自的 content-type，因此不是 69 个不同包名。
这个 npm 清单以实际 node_modules 为范围，不是压缩 JavaScript 或原生二进制内全部嵌入依赖的清单。
PTY/winpty 的上游许可证已保存，但 prebuilt 二进制的精确源码提交/构建版本没有由本材料补足；
`^0.12.0` 是依赖范围，不是对本地二进制版本的认定。

授权文本来源（按原文保存）：

- DPAPI：https://raw.githubusercontent.com/NapNeko/NapCatQQ/v4.18.34/packages/napcat-dpapi/LICENSE
- PTY：https://raw.githubusercontent.com/homebridge/node-pty-prebuilt-multiarch/v0.12.0/LICENSE
- winpty：https://raw.githubusercontent.com/rprichard/winpty/master/LICENSE
- JetBrains Mono：https://raw.githubusercontent.com/JetBrains/JetBrainsMono/v2.304/OFL.txt
- 字体项目：https://github.com/JetBrains/JetBrainsMono
- npm：当时核对的每个 node_modules 包自身的 package.json 与许可证文件；原始仓库链接随各条目记录。

## 原生组件的已知来源与证据边界

以下组件仍在分发清单中。当前只确认它们来自官方 NapCat v4.18.34 的对应程序资产，
没有足以单独确定其完整第三方组成、适用许可证或再分发权利范围的材料：

- `native/packet/MoeHoo.win32.x64.node`
- `native/napi2native/napi2native.win32.x64.node`
- `native/napi2native/ffmpeg.dll`

来源目录：https://github.com/NapNeko/NapCatQQ/tree/v4.18.34/packages/napcat-native
各文件 SHA-256 见 Echo 官方来源 pins；保留文件仍由 Windows 构建校验。
不因为它们位于 NapCat 包内，就推断所有内嵌代码只适用 NapCat 许可证。
尤其不凭 `ffmpeg.dll` 文件名认定其是 FFmpeg 库、认定 LGPL 或宣称相关义务已经完成。
上游启动器 NapCatWinBootMain.exe / NapCatWinBootHook.dll 同样按 NapCat 官方包来源记录，本材料不提供其内嵌依赖的额外授权结论。

上述 Windows x64 Portable 裁剪合同排除的 FFmpeg Addon 和 AaCute.woff 不属于当时核实的实际分发文件。
排除它们不意味着剩余组件的证据缺口消失；本声明保留这些未确认事项供发布审核。
