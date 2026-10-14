# 余音 Echo Development Guide

## 1. Project Overview

余音 Echo is a privacy-first local chat analysis tool.

Current GUI / ChatSource product sources:
- QQ Direct DB for desktop session discovery and analysis; bundled QQ / NapCat runtime for connection
- WeChat local database (data directory detection, key acquisition, session analysis)

Current-format JSON / JSONL import capabilities remain in the lower-level pipeline
and the echo-chat local-file CLI, including WeChat detailed JSON / chatlab JSONL.
They are not the removed `LOCAL_FILE` GUI product entry point.

The project is designed to:
- run locally;
- keep chat data on the user's machine;
- separate analysis core from user interfaces;
- convert each source into ChatMessage;
- support future additional chat sources without changing the analysis core.

------------------------------------------------------------------------

## 2. Development Environment

Requirements: - Windows (primary development platform) - Python - Git

For QQ development, use Python 3.11+; the fresh-clone acceptance on
2026-10-14 verified Python 3.13.9 at public main commit
`6ee8828a4574bcbab81903da2442a8690ba6f6fc`.
The existing `pyproject.toml` declaration remains `requires-python = ">=3.10"`,
but QQ workspace validation in
`src/qq_chat_analyzer/application/qq/qq_runtime_workspace.py` uses
`hashlib.file_digest`, which is available only in Python 3.11+.
This is a known inconsistency; Python 3.10 was not verified by that acceptance,
and this documentation update does not change the project's global minimum.

Some JavaScript focused tests require a system Node.js executable on `PATH`.
Node.js is not a separate prerequisite for the NapCat bootstrap or the GUI
initialization verified in that acceptance. Install it when running tests that
execute the JavaScript helpers; the `dev` Python extra does not install it.

The project uses a Python virtual environment:

    .venv/

The virtual environment is local only and should not be committed.

------------------------------------------------------------------------

## 3. Initial Setup

### 3.1 Human Initial Setup (new clone)

After cloning the repository, a human developer may create the project
virtual environment:

``` powershell
python -m venv .venv
```

Install the complete development environment from `pyproject.toml`:

``` powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,gui]"
```

All project commands after creation should use the explicit `.venv` interpreter;
shell activation is not required.

For QQ development, rebuild the runtime from the repository root after installing
the dependencies:

``` powershell
$EchoPython = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $EchoPython scripts/bootstrap_qq_napcat_runtime.py
```

Use the fixed official **NapCat 4.18.34** `NapCat.Shell.zip` from
`NapNeko/NapCatQQ`, as pinned in `scripts/qq_napcat_runtime_pins.json`.
The bootstrap downloads the official archive, verifies its size and SHA256 and
the pinned key files, applies and verifies the Echo NapCat patch, and installs
the hash-verified Echo plugin templates and plugin enable configuration.
It checks `scripts/qq_napcat_runtime_manifest.json` before publishing
`runtime/qq-napcat-candidate`. It does not start QQ or log in to an account.
Do not substitute another NapCat version or copy a runtime from an existing
development checkout.

If GitHub downloads are restricted, download the exact official archive using
a browser or download tool with network access, then pass it to the bootstrap.
For example, save it as `NapCat.Shell.zip` in the repository root:

``` powershell
curl.exe --location --fail --output .\NapCat.Shell.zip https://github.com/NapNeko/NapCatQQ/releases/download/v4.18.34/NapCat.Shell.zip
& $EchoPython scripts/bootstrap_qq_napcat_runtime.py --archive .\NapCat.Shell.zip
```

The `--archive` option retains all size, SHA256, patch and plugin checks; do not
use an unofficial repack or disable validation. Configure any required network
proxy locally for the downloader you use: Git's proxy configuration does not
automatically configure Python's downloader. Keep proxy addresses, credentials
and downloaded archives out of commits.

Public terminal entrypoints are `echo-chat` (CLI) and `echo-gui` (Desktop).
After installation, developers can launch them without activating the shell:

``` powershell
.\.venv\Scripts\echo-chat.exe --help
.\.venv\Scripts\echo-gui.exe
```

Successful GUI initialization, including opening the QQ page, does not establish
that real QQ login, database snapshot acquisition or analysis works. The
fresh-clone acceptance used temporary user-data directories and fictional
configuration without connecting QQ or reading chat databases. Real QQ
acceptance is a separate step requiring a local QQ installation, human login
and explicit verification of the snapshot and analysis flow.

The Python package remains `qq_chat_analyzer`; the distribution name used by
`pip show` remains `qq-chat-analyzer`. No `qqchat` / `qqchat-gui` aliases are registered.

Release version is defined only in `pyproject.toml`. Runtime consumers read the
installed distribution metadata through `qq_chat_analyzer.version`; after a version
change, refresh the editable installation using the setup command above. The
Windows PyInstaller build requires Python 3.11+ to read TOML, rejects stale installed
version metadata, and copies the verified metadata into the frozen application.
It does not require the source checkout to read its version at runtime.

### 3.1.1 Windows Release Build Toolchain

The Windows release build needs the pinned build toolchain, which is not part of
the runtime dependencies. Install it from the same `pyproject.toml` extras:

``` powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,gui,build]"
```

`scripts/build_windows_exe.ps1` runs `<project>\.venv\Scripts\pyinstaller.exe` and
fails closed when it is missing. The versions pinned in the `build` extra are the
toolchain the released frozen artifact is built with, so a release must not be
produced with a different interpreter or an unpinned PyInstaller.

### 3.2 AI Existing Workspace

New-clone initialization in section 3.1 is a human setup workflow. A new Git
worktree normally has no `.venv`; this alone is not an environment failure and
does not authorize initialization. An AI agent must prefer the current worktree's
environment, then look for an existing, previously verified Echo environment
using `git worktree list --porcelain` and known local Echo checkouts. Revalidate
each candidate against the target worktree's `pyproject.toml`; prior successful
tests or builds do not guarantee compatibility with the current requirements.

Run commands from the target worktree. Select the explicit interpreter locally
(when reusing an environment, set `$EchoPython` to its verified path instead):

``` powershell
Test-Path .\.venv\Scripts\python.exe
$EchoPython = (Resolve-Path .\.venv\Scripts\python.exe).Path
$EchoSource = (Resolve-Path .\src).Path
$env:PYTHONPATH = $EchoSource
& $EchoPython -c "import sys; print(sys.executable); print(sys.version); assert sys.prefix != sys.base_prefix"
& $EchoPython -m pip --version
& $EchoPython -m pip check
& $EchoPython -m pytest --version
& $EchoPython -c "from pathlib import Path; import os, qq_chat_analyzer; actual = Path(qq_chat_analyzer.__file__).resolve(); expected = Path(os.environ['PYTHONPATH']).resolve() / 'qq_chat_analyzer' / '__init__.py'; print(actual); assert actual == expected, (actual, expected)"
```

Compare installed dependency versions with the target `pyproject.toml` (runtime,
`dev`, and task-required extras such as `gui` or `build`), and verify their imports.
`pip check` verifies installed dependency consistency; it does not by itself
verify the target checkout's requirements. Tests default to the verified
interpreter and explicit target source path, for example:

``` powershell
& $EchoPython -m pytest tests/test_facade.py -q
& $EchoPython -m pytest -m "not slow_integration and not known_failure" -q
```

Keep this source path in the command session and inherited subprocess environment;
recheck it in new sessions. Shared `echo-chat.exe` / `echo-gui.exe` entrypoints or
editable-install metadata may still refer to the environment's original checkout.
Use the verified Python and target source path for source execution, and verify
subprocesses that override import paths also use the target worktree.
The `.venv` commands in sections 4 and 5 are local-environment examples; when
reusing an environment, use `& $EchoPython` with the same explicit source path.

Stop only when no usable Echo environment exists, dependencies do not match, or
target-source isolation cannot be guaranteed. Do not automatically install or
upgrade dependencies, create a virtual environment, fall back to system Python,
or alter another worktree's virtual environment (including editable reinstallation).
Report missing or incompatible requirements for human resolution.

For a Windows release build, `scripts/build_windows_exe.ps1` requires the target
project's `.venv\Scripts\pyinstaller.exe`. After verifying reuse is safe, a local
`.venv` junction may point to the existing environment. Before creating it,
resolve and verify the environment directory and interpreter, and inspect the
destination `.venv` with `Get-Item -LiteralPath .\.venv -Force` and a parent-directory
listing (including reparse points or dangling links). Create a junction only when
the destination is absent; never overwrite or remove a real directory or existing
link. Use `New-Item -ItemType Junction` with the checked destination and target,
without `-Force`, then inspect the link target and revalidate the interpreter and
source import. The junction is local only; neither `.venv` nor machine-specific
absolute paths may be committed to Git.

Before building with a reused environment, verify Python meets the build's 3.11+
requirement and PyInstaller and pyinstaller-hooks-contrib match the exact `build`
extra pins in the target `pyproject.toml`. Use the same interpreter to inspect
`pip show qq-chat-analyzer` and `importlib.metadata.distribution('qq-chat-analyzer')`
(version, requirements, metadata location and `direct_url.json` when present).
Record how that installation relates to the target worktree: an editable install
may point to an older checkout. Matching versions alone do not prove source identity;
the metadata copied into the build must also match the target project's dependency
and entrypoint declarations. Do not repair mismatches by modifying the shared
environment.

Run the build from the target project and verify `LocalChatAnalyzer.spec` belongs
to it: the spec resolves `project_root` from `SPEC`, sets `pathex` to that project's
`src`, rejects mismatched installed release versions, and copies installed metadata.
Inspect PyInstaller's analysis output to confirm packaged `qq_chat_analyzer`
modules originate from the target `src`, rather than the environment's old checkout.
A successful source import check does not replace this packaging check. Reuse does
not relax any Windows Frozen / Portable build, runtime, privacy, smoke or acceptance
checks; Fast tests do not replace the required focused integration validation.

------------------------------------------------------------------------

## 4. Verify Environment

Verify the actual interpreter and pip selected for project commands:

``` powershell
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable); print(sys.version)"
.\.venv\Scripts\python.exe -m pip --version
```

If package metadata is needed, query it through the same interpreter:

``` powershell
.\.venv\Scripts\python.exe -m pip show qq-chat-analyzer
```

------------------------------------------------------------------------

## 5. Running Tests

Tests are run in three layers:

- **Focused**: the test file or node directly related to the change;
- **Fast**: daily development regression, excluding `slow_integration` and
  `known_failure`;
- **Full**: complete regression at a phase boundary or before submission.

Run the relevant focused tests first, for example:

``` powershell
.\.venv\Scripts\python.exe -m pytest tests/test_facade.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_facade.py::test_name -q
```

The marker names are defined in `pyproject.toml`; do not replace them with
ad-hoc exclusions. The standard Fast Suite is:

``` powershell
.\.venv\Scripts\python.exe -m pytest -m "not slow_integration and not known_failure" -q
```

The Full Suite is:

``` powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Fast does not replace focused integration tests covered by `slow_integration`.
When a change touches packaging, Chromium rendering, CLI subprocesses,
PowerShell helpers, Windows runtime integration, or a specific WeChat
integration, run the relevant focused integration tests explicitly.

If Windows temporary-directory permission problems appear, pass a local base
directory to the same explicit interpreter:

``` powershell
.\.venv\Scripts\python.exe -m pytest --basetemp=.pytest-temp
```

Do not commit temporary test directories, test counts, or timing snapshots.

------------------------------------------------------------------------

## 6. Git Workflow

Use feature branches. Before editing, run:

``` powershell
git status --short --branch
```

Identify and preserve existing working-tree changes. Do not use `git restore`,
`git checkout`, or broad cleanup to remove changes whose source is unknown.

Workflow:

    Create branch
        ↓
    Implement small change
        ↓
    Run tests
        ↓
    git diff --check
        ↓
    Commit
        ↓
    Push branch
        ↓
    Create Pull Request
        ↓
    Review
        ↓
    Squash merge

Do not use `git add .`; stage only explicitly named files. Run
`git diff --check` before completion and confirm the changed-file list stays
within the allowed task scope.

Do not commit: - real chat data; - generated outputs; - local
configuration; - virtual environments.

------------------------------------------------------------------------

## 7. Architecture Rules

完整架构设计见 ARCHITECTURE.md（唯一架构事实来源）。本文档只保留与开发流程相关的规则，不再复制架构图。

CLI handles:
- command arguments;
- user interaction;
- displaying results;
- exit codes.

CLI should not contain analysis workflow.

Application Service handles:
- analysis workflow;
- calling core modules;
- DTO conversion;
- application-level errors.

ImportService handles:
- file discovery and source recognition;
- routing each input file to its source parser;
- returning ChatMessage, ImportResult, and raw message count.

Source parsers:
- QQ Direct DB adapter converts the transient qq-db-json payload into source-neutral rich messages and ChatMessage;
- WeChat parser converts WeChat detailed JSON/JSONL into ChatMessage;
- parsers must not depend on analysis core or UI layers.

Future API/Desktop interfaces should call Application Service instead of
core modules directly.

Core modules should implement analysis logic and avoid depending on
CLI/Application layers or source-specific types.

## 7.1 Multi-source Input Design Principles

- Use an independent adapter/parser for each supported source format.
- Every parser returns ChatMessage.
- ImportService recognizes the source and routes the file.
- AnalysisApplicationService calls ImportService and keeps the analysis workflow.
- ImportService must reuse existing parsers and must not duplicate parsing logic.
- Core analysis modules only consume ChatMessage.
- Do not duplicate source parsing when adding a new source.
- Do not introduce platform branches in analyzer.py, tokenizer.py, or cleaner.py.
- Confirm real sample fields before choosing the first supported format.

------------------------------------------------------------------------

## 7.2 Current Local Import Pipeline

- ImportRequest describes the input path and optional platform hint.
- ImportOutcome carries ImportResult, ChatMessage, RichMessage and processed_message_count.
- ImportService owns path validation, file discovery, source recognition and adapter/parser routing.
- AnalysisApplicationService obtains messages through ImportService, then applies the final analysis scope.
- Supported formats: qq-db-json, wechat-db-json, detailed-json, chatlab-jsonl,
  and cli-json (a bare array conforming to the WeChat CLI schema).
- echo-chat remains the local-file analysis entry point for these formats. It
  does not provide qce list / qce analyze or import retired QQ file formats.

QQChatExporter / QCE runtime, provider/service, QCE JSON and old QQ JSON/JSONL
compatibility are retired. parser.py and qq_chat_exporter_adapter.py are absent.
Retirement tests and release forbidden checks must remain.

------------------------------------------------------------------------

## 7.3 Current QQ / WeChat Source Integration

The only official QQ product chain is:

```text
NapCat -> Direct DB -> qq_db_adapter -> unified message model -> Analysis
```

- NapCat owns startup/login and local decryption; QQDirectDatabaseImportService
  orchestrates session acquisition and transient cleanup through acquired_session().
- QQDatabaseProvider reads the validated snapshot and materializes qq-db-json;
  qq_db_adapter interprets it into source-neutral RichMessage / ChatMessage.
- QQ acquisition uses epoch seconds. The application scope filter remains the
  final correctness boundary. No QCE export fallback exists.
- WeChat acquisition remains unchanged: epoch-second SQL bounds, all matching
  message shards, global ordering and unlimited acquisition by default.
- CLI delegates local-file analysis to Application services; GUI uses
  ChatAnalyzerFacade. Analysis does not know source formats or runtime tools.

Current architecture and acceptance boundaries are in ARCHITECTURE.md and
docs/HARDENING.md. The main branch released Echo v0.1.0 as a Windows Portable
ZIP (Pre-release). The pinned QQ runtime is NapCat 4.18.34 with Echo patches,
per-launch RPC credentials, Worker boot_id isolation, explicit reconnection,
and staging-input witnesses rather than native-read telemetry patches.
Check scripts/qq_napcat_runtime_pins.json and the runtime bootstrap contract
before packaging; a source checkout alone does not guarantee a current local
runtime directory. The published build does not establish compatibility on
every Windows machine; see docs/HARDENING.md for known follow-ups.
Earlier Direct DB / QCE E2E records describe historical versions and are not
current runtime interfaces. They remain in docs/BUG_JOURNAL.md,
docs/research/ and docs/superpowers/ for engineering context.

## 7.4 GUI / Facade / Presentation 开发规则

GUI 开发规则：

- GUI 只能通过 ChatAnalyzerFacade 调用业务能力；
- GUI 不得直接调用 Provider、Parser、Adapter 或 Analysis Core；
- GUI 不包含数据解析、分析算法与过滤规则；
- 报告展示控件保持只读（setEditTriggers(NoEditTriggers)），但保留选中与复制。

Facade 规则：

- ChatAnalyzerFacade 是 GUI 的唯一业务入口（application/facade.py）；
- Facade 负责来源分派、配置整理、Service 调度与异常归一（FacadeError）；
- GUI 只展示 FacadeError.public_message，不展示 traceback；
- Facade 通过依赖注入构造，测试可传入 stub。

Presentation 规则：

- Presentation 只负责展示模型转换与格式化，不重新计算分析结果；
- 需要的统计数字必须由 Analysis Core 的 analyzer 产出；
- 展示名称通过 AnalysisRequestDTO.speaker_names / conversation_names 注入，
  不在展示层做来源判断。

------------------------------------------------------------------------

## 8. Privacy Rules

Never commit:
- real QQ/WeChat chat JSON/JSONL files;
- QQ group numbers;
- usernames/nicknames;
- API keys;
- tokens;
- local paths.

Tests must use fictional data only.

------------------------------------------------------------------------

## 9. Adding a New Chat Source

1. Read the real export sample and confirm its field structure.
2. Choose only the first supported format; do not support all variants in advance.
3. Add an independent parser module that returns ChatMessage.
4. Write fictional-data tests before implementation.
5. Route the new parser through AnalysisApplicationService.
6. Run the full test suite.
7. Do not modify analyzer.py, tokenizer.py, or cleaner.py.


## Source Structure

src/qq_chat_analyzer/
    application/       # application contracts and services
    application/facade.py  # ChatAnalyzerFacade: GUI 唯一业务入口
    analysis/          # Analysis Core v2/v3: reports and analyzers
    presentation/      # view models, formatters, builders
    gui/               # PySide6 GUI MVP
    providers/         # QQ / WeChat data providers
    message.py         # source-neutral ChatMessage model
    wechat_parser.py   # WeChat detailed JSON parsing
    qq_db_adapter.py   # QQ Direct DB payload conversion
    wechat_db_adapter.py         # WeChat DB adapter
    wechat_cli_adapter.py        # WeChat CLI adapter
    smart_profile.py   # Smart Profile orchestration
    detectors/         # robot/template/interactive bot detectors
    cleaner.py         # text cleaning
    tokenizer.py       # tokenization
    analyzer.py        # analysis algorithms
    exporters.py       # local artifact generation
    cli.py             # command line adapter

## Windows Setup: A1 integration

The desktop extra requires `velopack==1.2.161`. `echo-gui`, the package GUI
module and the frozen entry dispatch Velopack before importing the GUI, with
pending-update auto apply disabled. This does not implement in-app updates.

Build the existing onedir release with `scripts/build_windows_exe.ps1` first.
Its runtime pins, app-local MSVC checks, copyright files and private-state
exclusions still apply. The Velopack [1.2.161 upstream license](https://github.com/velopack/velopack/blob/1.2.161/LICENSE)
is included through the same copyright manifest.

Use an explicitly selected vpk 1.2.161 and local .NET 8 SDK. Do not install
global tools or change system PATH. With the approved `$EchoPython`, source
isolation and process-local `DOTNET_ROOT` already verified:

```powershell
& $EchoPython scripts/package_windows_setup.py `
    --source dist/Echo --output <new-external-artifact-directory> `
    --vpk <local-tool-directory>/vpk.exe `
    --pack-id EchoA1.Fictional --channel win-x64-a1
```

The wrapper checks frozen Echo/SDK versions, runtime hashes, licenses and
private-state exclusions before invoking vpk. It packages a staging copy,
checks feed identity and package integrity, verifies every application file
and source immutability, then publishes the new directory. Existing output
directories are refused. vpk self-update and delta generation are disabled.
The project version supplies packVersion; there is no independent installer
version override. The test packId/channel are explicit; production identity,
feed policy and signing are separate release decisions.

The Setup creates a desktop shortcut and a Start Menu shortcut
(`--shortcuts Desktop,StartMenuRoot`), and it reuses `branding/Echo.ico` for the
Setup executable and those shortcuts, so an installation looks like the
`Echo.exe` it installs. Install-time branding and progress come from Velopack's
native progress dialog, which is titled through `--packTitle`; no custom splash
image is shipped.

For real acceptance, use a lab-only packId, external `--installto`, isolated
process-local `LOCALAPPDATA` and fictional configuration. Check install and
user-data paths independently. Use the test installation's registered
`Update.exe --uninstall --silent` command, and verify data hashes afterward.
Never infer a clean exit from disappearance of the window: record the native
process exit code. See the [A1 audit](docs/research/2026-10-12-windows-setup-a1.md)
for actual results and remaining gates.
