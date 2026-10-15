# AGENTS.md

# Local Chat Analyzer AI Development Guide

## Project定位

这是一个隐私优先、本地运行的聊天记录分析工具。

目标： - 支持多个聊天来源； - 将不同来源转换为统一消息模型； -
提供高质量聊天分析； - 最终让普通用户无需命令行即可使用。

当前来源： - QQ Direct DB（通过 NapCat 启动 / 登录与本地解密） - 微信聊天记录。
`echo-chat` 保留为当前支持格式的本地文件分析入口；输入格式以 ARCHITECTURE.md 为准。

------------------------------------------------------------------------

## 隐私规则

禁止： - 上传真实聊天记录； - 提交真实 JSON/JSONL 数据； -
提交群号、昵称、账号信息； - 提交密码、token、API Key。

测试必须使用： - 虚构数据； - 人工构造样本。

真实聊天数据只能在用户本机处理。

------------------------------------------------------------------------

## 架构原则

核心原则：

数据来源与分析逻辑分离。

架构事实来源：

ARCHITECTURE.md（仓库根目录）是当前唯一架构事实来源；架构与分层讨论以它为准，不在本文件复制架构图。

结构：

数据来源 → Parser / Provider → ChatMessage → Application Service →
Analysis Core → Exporter / GUI

分析核心不能知道： - QQ 格式； - 微信格式； - CLI； - GUI； -
第三方工具实现。

新增来源必须先转换为统一消息模型。

------------------------------------------------------------------------

## QQ 数据入口

桌面 QQ 会话列表与分析使用正式 QQ Direct DB 链路；历史版本已完成真人 E2E 和最终 smoke。
该历史验收不覆盖当前 NapCat 升级、RPC 认证、Worker 代际隔离与显式重连变更；
当前代码、自动化、合入与最终发行 / 真人验收状态以 `docs/HARDENING.md` 为准。
具体数据流、获取与清理边界以 ARCHITECTURE.md 为准，不在本文件复制架构图。
QQChatExporter / QCE 已完全退休：runtime、CLI 服务调用、QCE JSON 与旧 QQ JSON/JSONL
兼容均不再支持；不得重新引入 QCE fallback。正式链路与统一消息模型边界见 ARCHITECTURE.md。

架构约束：

- CLI 不直接调用 Provider；
- Provider 只负责外部数据获取；
- Adapter 只负责格式转换；
- Application 层负责业务编排；
- CLI 不直接调用核心分析逻辑；
- 不复制分析逻辑。

------------------------------------------------------------------------

## 模块职责

### Parser

负责： - 读取外部数据； - 转换内部模型。

不负责： - 分析； - 过滤策略。

### Cleaner

负责： - 文本清理； - 标准化。

不负责： - 判断机器人； - 判断消息价值。

### Tokenizer

负责： - 分词； - token生成。

### Analyzer

负责： - 统计； - 用户分析； - 关系分析。

不能包含： - 文件读取； - CLI逻辑； - GUI逻辑。

### Application Service

CLI 和 GUI 的共同入口。

GUI 通过 ChatAnalyzerFacade 接入（见 GUI原则）。

禁止出现两套业务逻辑。

------------------------------------------------------------------------

## 智能过滤原则

过滤分三个层级：

### 发送者过滤

过滤整个来源。

例如： - 机器人账号； - 系统账号。

### 消息模板过滤

过滤完整重复模板。

例如： - 欢迎消息； - 签到回复； - 查询结果。

不要把模板中的词全部加入停用词。

### 停用词过滤

只影响分词结果。

自动识别需要记录： - 理由； - 类别； - 置信度。

支持人工覆盖和撤销。

------------------------------------------------------------------------

## AI开发流程

### First 5 Minutes / 首次进入仓库检查

进入仓库后先按以下顺序确认工作边界：

1. 运行 `git status --short --branch`，识别当前分支和 working tree 状态；
2. 识别并保护已有未提交修改，不覆盖、不 restore、不 checkout；
   开始新任务或阶段前运行 `git worktree list --porcelain` 和 `git branch -vv`，
   检查候选工作树的状态与使用情况，优先复用干净且合适的工作区；
3. 优先检查 `Test-Path .\.venv\Scripts\python.exe`；当前 worktree 缺少 `.venv` 是正常现象，按 `DEVELOPMENT.md` 的 AI Existing Workspace 流程，从 `git worktree list --porcelain` 和已知 Echo 项目环境中寻找已有且验证通过的虚拟环境；
4. 用选定环境的显式 Python 路径验证解释器、当前 `pyproject.toml` 要求的依赖和测试工具；显式将源码导入路径设为目标 worktree 的 `src`，核验 `qq_chat_analyzer.__file__` 实际位于该目录，不能导入环境所属的旧工作树。仅在没有可用环境、依赖不符或无法保证源码隔离时停止；
5. 明确当前任务允许修改的文件范围；
6. 阅读与任务直接相关的事实来源；
7. 先运行与当前任务直接相关的 focused tests，不要无条件先跑 full suite。

修改代码前：

1. 阅读相关代码；
2. 理解当前设计；
3. 说明方案；
4. 确认影响范围。

开始修改前必须确认：

- 当前已有未提交修改；
- 当前任务允许修改的文件；
- 不覆盖其他任务产生的修改。

状态检查的目标是确认修改边界，不是重新审计整个仓库。

如果发现 git 状态与文件内容存在差异：
- 记录现象；
- 保留当前工作；
- 继续当前任务；
- 只有影响当前任务时才深入调查。

禁止：
- 未确认执行 git restore；
- 未确认执行 git checkout；
- 覆盖未知来源修改。

不要：
- 大规模重构；
- 为未确定需求提前设计复杂框架；
- 修改无关文件。

### Git 安全规则

- Echo 阶段成果经人工审核后，默认直接合入 main 并正常推送；除非用户明确要求，否则不创建 PR。
- 禁止使用 `git add .`；
- 提交时显式列出文件；
- 不覆盖未知来源的 working tree 修改；
- 不为当前任务顺手清理无关变化。

### 工作树与成果生命周期

- 阶段结束必须处置工作树、分支、stash 和临时资产，不能只记录“仍有修改”后永久保留。
- 对尚未合并的成果明确选择：继续合并、最小保存或放弃；未提交修改和历史备份本身不构成长期保留理由。
- 不再使用的工作树默认及时释放。待集成提交可先推送并核验远端 SHA，再移除干净工作树；不自动删除未合并分支。
- PR 合并后核验最新 main、独有成果、未跟踪与忽略资产及其他任务占用，再清理已合并分支和工作树；不能根据目录名称判断。
- 最小保存必须覆盖必要的未跟踪文件，检查敏感信息并验证完整性和恢复方法；不为过期代码另建永久档案。
- 放弃修改须已有明确授权且精确核对文件范围；新出现或来源不明的成果保留，继续处理其他已确认对象。
- 保护用户数据、虚拟环境、本地运行时与配置；禁止 `git worktree remove --force`、`git clean -fdx`、`git reset --hard` 或递归删除未知目录。
- 收尾报告记录分支、HEAD、PR/合并状态、成果保存位置、工作树状态及实际处置；剩余对象必须注明保留原因和明确结束条件。
- Windows PowerShell 的执行与核验流程见 `DEVELOPMENT.md` 第 6 节；本机路径、用户名和实验资产不写入仓库。

### Bug 修复流程

Bug 修复按以下顺序进行：

现象/复现 → 调用链 → 竞争假设 → 最小诊断 → 根因 → regression RED →
minimal GREEN → focused verification → Fast / 必要时 Full → real acceptance。

- 看到异常后不得直接 patch，必须先完成最小诊断并确认根因；
- 不得为了让测试变绿而修改测试预期；
- 环境失败先分类和报告，不得顺手修改无关业务代码。

### 测试分层与 slow integration 边界

- **Focused**：与当前修改直接相关的测试文件或测试节点；
- **Fast**：日常开发回归，运行 `slow_integration` 和 `known_failure` 之外的测试；
- **Full**：阶段完成或提交前的完整回归。

Fast Suite 命令必须与 `pyproject.toml` 中的 marker 定义一致；先按下文 Python / pytest
执行环境规则设置并验证 `$EchoPython` 和目标 worktree 的源码导入路径：

```powershell
& $EchoPython -m pytest -m "not slow_integration and not known_failure" -q
```

如果当前修改触及 `slow_integration` 覆盖的能力，必须显式运行相关的 focused
integration tests。适用范围包括 packaging、Chromium renderer、CLI subprocess、
PowerShell helper、Windows runtime integration 和特定 WeChat integration；Fast
通过不能替代这些测试。不要把当前测试数量或耗时硬编码进文档。

### 完成前检查

完成前运行：

```powershell
git diff --check
git diff --name-only
git status --short
```

并确认实际修改文件没有超出当前任务允许的范围。

### Python / pytest 执行环境

优先使用当前 worktree 的 `.venv`；缺失时可复用已有且验证通过的 Echo 项目虚拟环境。
环境选择、依赖验证与构建复用检查见 `DEVELOPMENT.md` 的 AI Existing Workspace。
在 Windows / PowerShell 下，必须用 `$EchoPython` 保存选定解释器的显式路径，并将
`$env:PYTHONPATH` 显式设为当前目标 worktree 的 `src`，核验实际导入路径后再运行命令；
不依赖 shell 激活或共享环境里指向旧 worktree 的 editable 安装。
以下命令均以完成这一步验证、且工作目录为目标 worktree 为前提。

测试命令统一使用：

```powershell
& $EchoPython -m pytest
```

例如：

```powershell
& $EchoPython -m pytest tests/test_facade.py
& $EchoPython -m pytest tests/test_facade.py -q
```

日常开发 / RED-GREEN 使用 Fast Suite（排除 `slow_integration` 和 `known_failure`），普通测试默认属于 Fast：

```powershell
& $EchoPython -m pytest -m "not slow_integration and not known_failure" -q
```

阶段完成 / 提交前运行完整回归（命令不变）：

```powershell
& $EchoPython -m pytest -q
```

执行 Python 脚本时使用：

```powershell
& $EchoPython <script>
```

除非已经明确验证命令解析到选定的 Echo 项目虚拟环境、且导入当前目标 worktree 的源码，否则不要直接使用：

```powershell
pytest
python -m pytest
py -m pytest
```

当前 `.venv` 缺失时先查找可复用环境；只有不存在可用环境、依赖不符或源码隔离无法保证时，才停止并报告环境问题。

未经明确要求，不要：

- 自动安装或升级依赖；
- 新建另一套虚拟环境；
- 回退到系统 Python；
- 因环境错误修改测试或生产代码。

复用时不得修改其他 worktree 的虚拟环境（包括重新 editable 安装）；不得将 `.venv`、
本地 junction 或本机绝对路径提交到 Git。环境复用不放宽 Windows Frozen / Portable 构建验证。

遇到以下错误时：

- `No module named pytest`
- `ModuleNotFoundError`
- 依赖包缺失

首先确认实际使用的 Python 是否为选定且验证通过的 Echo 项目虚拟环境，并核验源码导入路径，而不是将其直接判断为测试 RED 或代码失败。

**使用错误 Python 解释器得到的测试结果，不属于有效的 RED / GREEN 证据。**

新功能：

设计 → RED测试 → 实现 → GREEN测试 → 完整测试 → 检查diff

------------------------------------------------------------------------

## 第三方工具集成

第三方工具只是数据来源。

例如： - NapCat； - CipherTalk CLI。

推荐：

第三方工具 → Provider / Adapter → ChatMessage → 分析系统

不要： - 将第三方代码复制进核心； - 让核心依赖具体工具。

------------------------------------------------------------------------

## GUI原则

GUI只负责展示和交互。

不能包含： - 数据解析； - 分析算法； - 过滤规则。

正确：

GUI → ChatAnalyzerFacade → Application Service → Core

约束：

- GUI 必须通过 ChatAnalyzerFacade 调用业务能力，不得绕过 Facade；
- GUI 不得直接调用 Provider / Parser / Adapter / Analysis Core；
- 禁止跨层依赖：GUI 不 import 业务层以外的内部模块；
- 错误统一使用 FacadeError.public_message，不展示 traceback。

------------------------------------------------------------------------

## 当前产品阶段

Echo 当前处于上线前 Hardening 阶段。

优先：

1. 修复真实用户遇到的阻塞和明显 Bug；
2. 保证数据获取、分析结果和本地数据生命周期可信；
3. 完善结果导出 / 分享和关键用户体验；
4. 降低诊断和维护成本。

当前阶段默认不新增大型功能或新数据来源。
新增能力需先由人工确认。

------------------------------------------------------------------------

## AI Agent定位

AI是开发助手，不是项目决策者。

AI负责： - 编码； - 调查； - 测试； - 提供方案。

项目方向由人工决定。

重大架构变化： 先讨论，再实施。
