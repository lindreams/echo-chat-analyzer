# Echo 源码许可与获取方式

Echo 自有且有权授权的源代码采用 Mozilla Public License 2.0（MPL-2.0）。
完整、未经修改的 Mozilla 官方许可证见同目录 `LICENSE`，原文来源：
https://www.mozilla.org/media/MPL/2.0/index.txt

本声明适用于仓库中 Echo 自有的源码，包括 `src/`、`tests/` 和 `scripts/` 中 Echo 自有部分。
以下标准声明集中放置在仓库及发行包根目录；不批量改写源码文件。
这一放置方式依据 MPL Exhibit A 与 Mozilla 官方 FAQ：
https://www.mozilla.org/en-US/MPL/2.0/FAQ/

> This Source Code Form is subject to the terms of the Mozilla Public
> License, v. 2.0. If a copy of the MPL was not distributed with this
> file, You can obtain one at https://mozilla.org/MPL/2.0/.

此声明不对 NapCat、第三方源码、依赖包、字体及其他第三方资产重新授权，
包括 `runtime/`、`third_party/` 内第三方材料及脚本内保留的上游代码。
它们仍受各自许可证和版权声明约束；NapCat 材料见 `third_party/napcat/NOTICE.md`。
官方 Echo 免费、非商业运营；MPL 2.0 本身允许商业使用。
Echo 的运营方式不限制 MPL 覆盖源码的商业使用权，也不替代第三方许可条件。

## 获取 MPL 覆盖的源码

公开仓库：https://github.com/lindreams/echo-chat-analyzer

发行版本与源码下载：https://github.com/lindreams/echo-chat-analyzer/releases

接收 Windows Portable 的用户可在上述公开仓库获取 MPL 覆盖的源码；
请选择与所收发行包版本对应的 Git tag / Release，并使用该页面的 Source code 下载。
源码以 MPL 2.0 提供，无需支付获取费用。
发行者须在发布 Portable 时同步公开该版本对应的完整 MPL 覆盖源码，
包含用于构建该版本的未提交修改；仅提供不同版本的 main 分支不能代替对应源码。

## QQ 表情图片：来源与授权待确认事项

核实日期：2026-10-16。`frontend/echo_report/qq-emojis/` 当前包含 327 张 PNG。
2026-10-10 的同步记录仅明确记载其中 77 张（id 为 55、418、433–507）取自
[QFace](https://github.com/koishijs/QFace)；不能据此认定此前 250 张的逐文件来源已核实。

- 资源索引：[QQ emoji v2](https://koishi.js.org/QFace/assets/qq_emoji/_index.v2.json)，
  当时记录的 `syncedAt` 为 `2026-09-28T03:43:28.805Z`；本次在线核对该值相同。
- 下载来源：`https://koishi.js.org/QFace/` 加索引中的 `assets[].path`。
  此来源记录不代表本地图片与 CDN 原文件逐字节一致。
- 本地处理：上述 77 张统一为 128×128 RGBA PNG；449、466、468、469 提取 APNG 首帧；
  485、486、487、501、502 选用 `<id>_0.png` 首帧并居中裁方、重采样。

上游证据固定于提交 `c96fa14ff894147ac0442dda0fce6a4523e5fcbd`：
[README](https://github.com/koishijs/QFace/blob/c96fa14ff894147ac0442dda0fce6a4523e5fcbd/README.md)
将表情素材标为腾讯版权，并声明限学习交流、非商业用途；
[LICENSE](https://github.com/koishijs/QFace/blob/c96fa14ff894147ac0442dda0fce6a4523e5fcbd/LICENSE)
为代码的 MIT 许可（署名 Shigma，2020-present），要求在软件副本或实质部分中保留版权和许可声明。
代码的 MIT 许可不能自动作为 QQ 表情图片的再分发授权，Echo 的 MPL-2.0 也不覆盖这些图片。

本次检查的上游 README、LICENSE 及本仓库声明未提供可核实的腾讯权利人授权，
不能确认图片随 Echo 分发及裁剪、重采样等处理的许可范围；非商业运营和本地使用均不能替代授权证据。
后续需补足图片权利人的再分发及修改授权依据，或另行决定替换／停止分发；本声明不表示已完成合规审查。
