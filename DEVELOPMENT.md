# 余音 Echo Development Guide

## 1. Scope and references

This guide owns executable development workflows. Follow [AGENTS.md](AGENTS.md)
for task scope, privacy, safety and authorization. Architecture and supported
inputs belong to [ARCHITECTURE.md](ARCHITECTURE.md); data contracts belong to
[DATA_SEMANTICS.md](DATA_SEMANTICS.md). Release status, unresolved risks and
acceptance boundaries belong to [HARDENING.md](docs/HARDENING.md).
Source and tests establish implementation and coverage; historical records do
not override current code or prove that a required contract is satisfied.

## 2. Development Environment

Use Windows (the primary development platform), Python and Git.

Use Python 3.11+ for QQ development and Windows builds. The current
`pyproject.toml` still declares `requires-python = ">=3.10"`, while
`src/qq_chat_analyzer/application/qq/qq_runtime_workspace.py` uses
`hashlib.file_digest` (Python 3.11+) and `LocalChatAnalyzer.spec` imports `tomllib`
(Python 3.11+). This is an unresolved declaration/runtime mismatch, not a promise
of complete Python 3.10 compatibility. Changing the declared minimum or adding
compatibility code requires a separate decision and implementation.

Some JavaScript focused tests require a system Node.js executable on `PATH`.
The `dev` Python extra does not install Node.js; provision it when the selected
tests execute JavaScript helpers. Do not infer full GUI or QQ acceptance from
the availability of Node.js or Python dependencies.

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

Install the recommended complete Windows development environment from `pyproject.toml`:

``` powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,gui,build]"
```

The `build` extra is for developers running build-contract tests and producing
Windows releases; ordinary application users do not need these tools.

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

GUI initialization does not establish real QQ login, snapshot acquisition or
analysis correctness. Automated checks use isolated user directories and fictional
configuration; real QQ acceptance requires human login and explicit local
verification of acquisition, analysis and cleanup under the authorized scope.

The Python package remains `qq_chat_analyzer`; the distribution name used by
`pip show` remains `qq-chat-analyzer`. No `qqchat` / `qqchat-gui` aliases are registered.

Release version is defined only in `pyproject.toml`. Runtime consumers read the
installed distribution metadata through `qq_chat_analyzer.version`; after a version
change, refresh the editable installation using the setup command above. The
Windows PyInstaller build requires Python 3.11+ to read TOML, rejects stale installed
version metadata, and copies the verified metadata into the frozen application.
It does not require the source checkout to read its version at runtime.

### 3.2 AI Existing Workspace

Use this workflow when executing Python, tests or builds; a documentation-only
edit does not require provisioning dependencies or running Python tests.
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

For the authorized Windows development environment, repair a missing build
toolchain before rerunning build-contract tests or reporting the same failure:
verify the selected interpreter and source path, inspect the installation plan,
then install the existing pinned extra without upgrading satisfied dependencies:

``` powershell
& $EchoPython -m pip install --dry-run --upgrade-strategy only-if-needed -e ".[build]"
& $EchoPython -m pip install --upgrade-strategy only-if-needed -e ".[build]"
& $EchoPython -c "from importlib.metadata import version; print(version('pyinstaller')); print(version('pyinstaller-hooks-contrib'))"
& $EchoPython -m pip check
```

Compare the actual versions with `pyproject.toml`; keep its pins and unrelated
installed versions unchanged. This authorization covers missing build dependencies
in the authorized current development environment, not general dependency upgrades
or changes to another worktree's environment. A task that forbids environment
changes takes precedence. Stop only when no usable environment exists,
authorized repair cannot satisfy the requirements, or source isolation cannot be
guaranteed. Do not create an unnecessary environment, fall back to system Python,
or alter another worktree's virtual environment (including editable reinstallation).

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

## 4. Windows build and validation

### 4.1 Frozen onedir build

Frozen Windows x64 uses the official SQLite **3.54.1** DLL independently of the
builder's Python SQLite. Provision it with the verified interpreter before the
first build:

```powershell
& $EchoPython scripts/bootstrap_sqlite_runtime.py
# Or reuse the exact official ZIP without downloading again:
& $EchoPython scripts/bootstrap_sqlite_runtime.py --archive <official-sqlite-zip>
```

`scripts/sqlite_runtime_pins.json` records the official URL, release source ID,
archive size/SHA3-256 and extracted DLL SHA256. The bootstrap verifies the flat
archive and AMD64 PE image and writes only `runtime/sqlite/sqlite3.dll`; it never
changes Python or a virtual environment and refuses to overwrite a different
existing DLL. The spec explicitly supplies this DLL to PyInstaller, verifies the
collected binary table, and ships the pins. The Windows wrapper verifies the
output DLL even for `-RuntimeOnly`; missing/mismatched SQLite fails the build.
The original Python `_sqlite3.pyd` stays paired with its Python interpreter.
After a Python or SQLite upgrade, revalidate that pair's API operations in an
isolated process and confirm a Frozen launch's `sqlite_version` startup field
and loaded DLL path/hash. Ordinary source tests still use Python's own SQLite
unless an isolated test process explicitly selects the new DLL.

Use the validated environment from section 3.2, the target project's `.venv`
PyInstaller and exact `build` extra pins. Do not build with an unpinned toolchain.
The build consumes `LocalChatAnalyzer.spec` and
`scripts/windows_runtime_manifest.json`; the manifest owns required native assets,
WeChat binary hashes, copyright files and private-state exclusions. Provision
those assets through the approved workflow; missing or mismatched assets must
fail validation, not be bypassed. QQ pins/bootstrap are described in section 3.1.

From the target repository root, after confirming that generated `build` / `dist`
outputs may be replaced:

```powershell
& .\scripts\build_windows_exe.ps1
```

This produces `dist/Echo/Echo.exe`, copies validated runtime assets and app-local
MSVC dependencies (minimum 14.43), and checks that private runtime state does not
ship. `-RuntimeOnly` refreshes runtime assets in an existing onedir tree; it does
not rebuild Python code and cannot substitute for a full release build. Do not
launch the release tree before packaging; test a separate copy with isolated data.
The spec checks the installed project version and Velopack version and copies
metadata; review the dependency/entrypoint metadata and source provenance as in
section 3.2 rather than treating a version match as complete proof.

When changing frozen/runtime/Setup packaging, select the affected build-contract
tests explicitly, including relevant slow integrations. For example:

```powershell
& $EchoPython -m pytest tests/test_frozen_desktop_package_contract.py tests/test_windows_runtime_contract.py tests/test_package_windows_setup.py -q
```

These tests do not replace a real Windows build, packaged launch/exit checks or
human acceptance. If changing Portable packaging, also run
`tests/test_package_windows_portable.py` and verify the relevant artifact; keeping
that script does not establish a new product distribution decision.

### 4.2 Setup packaging and acceptance

The `gui` extra pins `velopack==1.2.161`. `echo-gui`, the package GUI
module and the frozen entry dispatch Velopack before importing the GUI, with
pending-update auto apply disabled. In-app updates require explicit user
confirmation, complete successful cleanup evidence and package revalidation,
then use the official wait-exit/apply/restart API.

Build the existing onedir release with `scripts/build_windows_exe.ps1` first.
Its runtime pins, app-local MSVC checks, copyright files and private-state
exclusions still apply. The required copyright files are listed in
`scripts/windows_runtime_manifest.json`.

Use an explicitly selected vpk 1.2.161 and local .NET 8 SDK. Do not install
global tools or change system PATH. With the approved `$EchoPython`, source
isolation and process-local `DOTNET_ROOT` already verified:

```powershell
& $EchoPython scripts/package_windows_setup.py `
    --source dist/Echo --output <new-external-artifact-directory> `
    --dotnet <local-dotnet8-directory>/dotnet.exe `
    --vpk <local-tool-directory>/tools/net8.0/any/vpk.dll `
    --pack-id EchoLabFictional --channel win-x64-lab
```

The wrapper checks frozen Echo/SDK versions, runtime hashes, licenses and
private-state exclusions before invoking vpk. It packages a staging copy,
checks feed identity and package integrity, verifies every application file
and source immutability, then publishes the new directory. Existing output
directories are refused. vpk self-update and delta generation are disabled.
The project version supplies packVersion; there is no independent installer
version override. Omit pack-id/channel for the fixed production identity
`Lindreams.Echo` / `win-x64-stable`; isolated tests must override both.
IDs containing a numeric version-like pair (such as `Echo.Lab.20261013.7abc`)
are rejected before vpk:
its legacy RELEASES filename parser mistakes that pair for the package version.
Ordinary dotted IDs remain supported.
The desktop consumes the same identity constants and fixed official CNB feed
defined in `application/update_channel.py`. Release-page checks use the public
`echo-update.json` asset; the pinned SDK consumes `releases.win-x64-stable.json`
and full nupkgs from the persistent `updates` release. No CNB token is shipped.
Signing and publication remain separate release decisions.

The Setup creates a desktop shortcut and a Start Menu shortcut
(`--shortcuts Desktop,StartMenuRoot`), and it reuses `branding/Echo.ico` for the
Setup executable and those shortcuts, so an installation looks like the
`Echo.exe` it installs. Install-time branding and progress come from Velopack's
native progress dialog, which is titled through `--packTitle`; no custom splash
image is shipped.

For real acceptance, use a lab-only packId, external `--installto`, isolated
process-local `LOCALAPPDATA` and fictional configuration. Check install and
user-data paths independently. Use the test installation's registered
`Echo.exe --echo-uninstall` entry and the in-app entry, checking both explicit
choices and cancellation. Retain report/ordinary-setting hashes in keep mode;
verify saved keys, owned runtime state, logs and update records are gone in
both modes. Purge must remove owned reports only after explicit confirmation.
Check Windows registration after both install and upgrade, including a silent
install before first GUI launch. Never substitute raw `Update.exe --uninstall`
for this acceptance: it bypasses Echo's confirmation and shutdown evidence.
Never infer a clean exit from disappearance of the window: record the native
process exit code. For update acceptance, verify isolated A-to-B installation,
cleanup evidence, automatic restart and data retention. Keep source, Frozen,
Setup and cross-machine results separate; required Full and release checks are
not replaced by a successful package build. Record remaining gates in
[HARDENING.md](docs/HARDENING.md).

------------------------------------------------------------------------

### 4.3 Quick local candidate Setup

After the environment checks in section 3.2, use one fixed entry:

```powershell
& .\.venv\Scripts\python.exe scripts/build_candidate_setup.py
```

Once per machine, write ignored `build/setup-tools.json` with three absolute
local paths: `dotnet` (the verified local .NET 8 `dotnet.exe`), `vpk` (vpk
1.2.161's `tools/net8.0/any/vpk.dll`), and `napcat_archive` (the cached official
NapCat ZIP from section 3.1). JSON paths may use forward slashes. No system PATH
or global tool installation is required. Keep these paths out of Git.
An SDK-installed `vpk.exe` can bind to .NET 9 even when DOTNET_ROOT selects 8;
the explicit host/DLL pair avoids that mismatch. Preflight verifies the net8
runtime configuration, CLI version, build pins, source and project version.

Each run creates a new `build/candidates/<unique-run>` with `dist/Echo`, `work`,
`frozen.log`, `setup`, and measured `timings.json`. `--output <new-directory>`
selects an external location; existing directories are refused. The existing
`dist/Echo` and release assets are preserved. Concurrent candidate builds are
refused by `build/candidate-setup.lock`; after an interrupted process, verify it
has exited before manually removing its stale lock.

The cached official archive is size/hash checked, patched and bootstrapped on
every run; existing private NapCat state causes refusal before replacement.
Frozen is rebuilt with `--clean` from current code and dependencies, rather than
reusing a tree based on incomplete timestamps. This deliberately limits caching
to the verified upstream download. Runtime, privacy, MSVC, license, feed and
every-file package checks still run through the existing build/Setup scripts.
There is no arbitrary version override or automatic installation/publication.

The result uses `Lindreams.Echo` / `win-x64-stable` for local trial installation;
it is **not release acceptance**. Building it does not run Full, prove real QQ
connectivity, or replace the Frozen/Setup lifecycle, update and privacy acceptance
in section 4.2. Formal releases still require the selected regression and complete
release safety checks. Do not publish a local candidate without that review.

------------------------------------------------------------------------

### 4.4 Prepare a CNB publication

After the release gates in section 4.2, prepare only public artifacts:

```powershell
& $EchoPython scripts/prepare_cnb_release.py --source <validated-setup-directory> --output <new-public-directory>
```

This checks the production identity, tool versions, full-package feed and hashes,
then creates six allowlisted files: named Setup, Setup SHA256, full nupkg,
channel JSON, `echo-update.json`, and `SHA256SUMS.txt`. It does not publish.
Never upload `setup-build.json`, local paths, logs or acceptance user directories.

Publish all six files under the immutable `v<version>` release and verify anonymous
complete downloads. For the persistent `updates` release, publish the immutable
nupkg first, channel JSON second, and `echo-update.json` last. Retain previous
nupkgs so a client already downloading an earlier version can finish. Do not
replace an existing version's binaries or move the channel backwards. Promote
the human-facing version release only after verification; `updates` is a service
release and must not become the human-facing latest version.

CNB write credentials belong only in the publishing process, never in the
application, public files, source, environment files or command-line arguments.
Old clients that still hardcode GitHub require one manual Setup installation;
publishing a CNB feed cannot rewrite their embedded address.

For a local update acceptance bridge, use a lower RC version such as
`0.2.6-rc.1`; Python metadata normalizes it to `0.2.6rc1`, and `version.py`
exposes the installer spelling. Refresh metadata and rebuild for each version.
Keep RC installers local; this publication preparer only permits stable versions.

------------------------------------------------------------------------

## 5. Running Tests

Validate `$EchoPython` and target `PYTHONPATH` as in section 3.2 before running
commands. Focused means the files or nodes protecting the affected contract and
is the daily baseline. Add Smoke, the affected Domain and relevant slow
integrations as needed; use Fast for broader cross-domain regression and Full
at appropriate phase or release gates. Do not mechanically run every tier.

Before adding tests, inspect existing coverage and weigh regression value against
maintenance cost, duplication and brittleness. TDD is optional: simple, low-risk,
directly verifiable changes need neither a failing test first nor new tests.
Complex algorithms, important bug regressions and high-risk behavior favor
targeted tests; privacy, data integrity, authorization, identity, authentication,
generation isolation, resource ownership and installation admission require sufficient regression
protection. Avoid tests tied to internal implementation details, redundant
parameter combinations or low-value scenarios. Record the validation chosen and
its limits; a passing existing test may be sufficient evidence for a small change.

```powershell
& $EchoPython -m pytest tests/test_facade.py -q
& $EchoPython -m pytest -m smoke -q
& $EchoPython -m pytest -m "qq and not slow_integration and not known_failure" -q
```

Every collected case has exactly one primary domain; Smoke can coexist with it.
Native markers are registered in `pyproject.toml`. The explicit module ownership
and exact Smoke node IDs live in `tests/conftest.py`; update them when adding or
renaming tests. New unassigned modules fail collection rather than silently
falling outside domain selection. Collection from the repository root or `tests`
rejects missing Smoke nodes before `-m`, `-k` or `--deselect` selection.
File/node Focused runs and explicit
`--ignore` / `--ignore-glob` runs are partial and do not require the entire Smoke
list. After changing markers, the domain inventory or Smoke node IDs, check
the relevant selection with collection; full and Smoke examples are:

```powershell
& $EchoPython -m pytest --collect-only -q
& $EchoPython -m pytest -m smoke --collect-only -q
```

| Domain marker | Primary contract and cross-domain ownership |
| --- | --- |
| `core` | Source-neutral analysis, models, filtering and shared import/analysis orchestration, even with source-specific fixtures |
| `qq` | QQ providers, adapters, acquisition, authentication and runtime ownership |
| `wechat` | WeChat providers, adapters, setup, keys and source-specific facade setup |
| `ui_report` | CLI/GUI interaction (including source/update UI wiring), shared Facade analysis/report orchestration, presentation, report publication/storage/deletion and rendering |
| `system` | Desktop bootstrap/exit, diagnostics, packaging (including frozen QQ contracts), updates/uninstall, cross-source shutdown and platform/test isolation |

Replace `qq` in the Domain command with any marker above. Domain selection alone
includes its slow/known-failure tests; use the explicit exclusions for a fast
Domain run, or select the relevant integration nodes directly when required.
Shared contracts or fixture/test-infrastructure changes warrant broader regression.
Fast excludes only the two markers below; unmarked tests stay in Fast regardless
of their measured duration. Full adds no marker exclusion (individual tests can
still skip or depend on their environment):

```powershell
# Fast: cross-domain regression excluding heavy integrations and known failures
& $EchoPython -m pytest -m "not slow_integration and not known_failure" -q
# Full: complete regression when warranted by impact/risk or release acceptance
& $EchoPython -m pytest -q
```

Smoke uses synthetic inputs and bounded local seams; it is a small health check,
not comprehensive coverage. Preserve privacy, authentication, generation isolation,
path ownership and cleanup safety regressions regardless of the selected tier.
Smoke, Domain and Fast do not replace required focused `slow_integration` tests
when changing packaging, Chromium rendering, CLI subprocesses, PowerShell helpers,
Windows runtime integration or specific WeChat integration. Required release
build, Full and human acceptance gates also remain in force.

### 5.1 Isolation, determinism and regression value

- Use fictional inputs only. `tests/conftest.py` redirects user-data/home paths,
  replaces default QQ process/session ownership, and cleans test-created Qt roots
  and finished worker relays. Reuse these fixtures; preserve pre-existing resources
  and active work. They do not sandbox every external process or registry access.
  Reuse existing fixtures and regression paths before adding helpers; exercise
  production behavior through bounded seams rather than a parallel test system.
- Before launching diagnostics or child processes, isolate their user directories,
  persisted config and any registry access they exercise. Keep the verified target
  source path in subprocesses; remove unrelated IDE `PYTHONPATH`/startup shims
  instead of weakening privacy assertions. The isolation regression lives in
  `tests/test_test_user_data_isolation.py`.
- For deterministic waits, use one coherent clock for monotonic time, deadlines
  and sleeping. Prefer bounded condition/event waits and targeted Qt event
  delivery to arbitrary fixed sleeps. Tests may replace UX delays locally;
  do not shorten production safety timeouts to improve test speed.
- Restore monkeypatches and shared state; release only test-owned widgets,
  workers, processes, files and handles. Distinguish active workers, stale relays
  and pending callback dispatch; do not hide leaks by clearing active registries.
- Keep unique historical regressions and security/lifecycle/platform contracts.
  Prove equivalent coverage before removing duplicate tests: owning layers test
  business rules, upper layers protect their boundary contracts. Test counts and
  elapsed time are not quality targets; environment coupling is a reason to fix
  isolation, not to delete coverage or quarantine a new regression for convenience.

If Windows temporary-directory permission problems appear, pass a local base
directory to the same explicit interpreter:

```powershell
& $EchoPython -m pytest --basetemp=.pytest-temp
```

Do not commit temporary test directories, test counts, or timing snapshots.

------------------------------------------------------------------------

## 6. Git Workflow

Prefer short-lived branches and reuse a suitable workspace. A separate worktree
is optional, useful when concurrent work or risk warrants isolation. Before editing, run:

``` powershell
git status --short --branch
```

Identify and preserve existing working-tree changes. Do not use `git restore`,
`git checkout`, or broad cleanup to remove changes whose source is unknown.

Daily work favors a short-lived branch, appropriate validation, a local commit,
integration into main, push and branch cleanup. PRs are useful for large features,
important architectural changes, high-risk review or collaboration; they are not
a default step. Neither Squash nor a single merge method is mandatory.

All commit, push, merge, PR and destructive cleanup actions require the current
user's explicit authorization. Human review and workflow examples do not grant
execution permission. Implement and validate the reviewable result first; stop
at the authorized boundary, retaining work awaiting review with an end condition.

For an authorized simple integration, adapt this example to the reviewed branch
and explicitly list the files (placeholders must be replaced before execution):

```powershell
git add -- <reviewed-file-1> <reviewed-file-2>
git diff --cached --check
git diff --cached --stat
git diff --cached
git commit -m '<reviewed-message>'
git switch main
git pull --ff-only origin main
git merge --ff-only <reviewed-branch>
git push origin main
```

Review the staged diff to exclude unrelated material already in the index. Switch
only with a suitable clean worktree; if main is checked out elsewhere, use its
verified worktree instead. If fast-forward fails or main has unexpected changes,
inspect divergence and resolve within the approved scope; do not force, reset or
silently choose another merge strategy. Verify local/remote SHAs after push and
perform branch/worktree cleanup only under section 6.1 and the task's authorization.

Do not use `git add .`; stage only explicitly named files. Run
`git diff --check` before completion and confirm the changed-file list stays
within the allowed task scope.

Do not commit: - real chat data; - generated outputs; - local
configuration; - virtual environments.

### 6.1 Worktree lifecycle and Windows PowerShell cleanup

When selecting, isolating, integrating or releasing a workspace, inspect
`git worktree list --porcelain`, `git branch -vv` and each candidate's status and
task occupancy. Prefer a clean, suitable existing workspace. At completion,
record dispositions for worktrees, branches, stashes and temporary assets involved
in the task; unrelated assets do not require a new audit.
Uncommitted changes or an old backup are not, by themselves, reasons to keep an
idle workspace indefinitely.
Choose authorized integration, minimum recoverable preservation, or explicitly
authorized abandonment. Work awaiting review can remain in place with its task
and end condition; this is not permission to clean or discard it.

For an authorized cleanup, use the applicable checks below from the repository
root. Stash, remote-branch, independent-clone and directory-removal checks apply
only to those objects; do not expand a simple task into a repository-wide cleanup.

1. Fetch `origin` and check the registered path, branch, HEAD and full status
   against the approved scope. Inspect both untracked files and ignored assets:

   ```powershell
   git worktree list --porcelain
   git branch -vv
   git -C $ReviewedWorktree status --short --branch --untracked-files=all
   git -C $ReviewedWorktree ls-files --others --ignored --exclude-standard --directory
   git stash list --format='%gd %H %s'
   ```

2. Confirm the workspace is not used by another task or process. Protect user
   data, environments, runtime directories and local configuration. If a new
   unique result appears, retain that object and continue with other confirmed
   targets. Do not expose private configuration or chat data in the report.
3. Check `git merge-base --is-ancestor <reviewed-head> origin/main`. A failed
   ancestry check is not proof of lost work after squash/rebase: verify the final
   changes and integration result (including the PR if used) before deciding.
   For useful unmerged commits, only when push is authorized, push the branch and
   verify `git ls-remote --heads origin <reviewed-ref>` matches its
   full SHA before releasing the worktree; retain the unmerged branch. If push
   is not authorized, retain the work or verify an authorized minimal recovery
   copy before removing its workspace.
4. Preserve only necessary files or patches outside the repository, including
   untracked files. For a stash containing untracked files, inspect its third
   parent as well as the tracked diff. Verify hashes and the recovery method,
   and mark candidate fixes as unapproved. Identify stashes by full SHA, then
   resolve their current selector immediately before an authorized drop.
5. Use ordinary `git worktree remove` for a clean, unused worktree. If abandoning
   changes is explicitly authorized, recheck the exact file list and discard
   only those tracked changes and reviewed new files first. A dirty-worktree
   refusal is a reason to investigate, never to add `--force`.
6. Delete merged local branches with `git branch -d` after verification. Before
   an authorized remote branch deletion, verify its live remote SHA is the
   reviewed merged commit; a changed remote head must be retained.
7. Treat independent clones separately: inspect their own branches, unique
   commits, status, ignored assets and stashes. A directory absent from the
   worktree list is not automatically disposable.
8. For directory removal, use PowerShell throughout. Resolve each approved
   literal target with `Get-Item`/`Resolve-Path -LiteralPath`, verify its absolute
   location is exactly within the named scope, and reject junctions, symlinks
   and other reparse points, including nested ones. Use `Remove-Item -LiteralPath`
   only on checked targets. Never enumerate an unknown parent and recursively
   delete its children or pass computed deletion paths to another shell.
9. Recheck affected objects and protected assets. Briefly record actual
   dispositions, remaining blockers and end conditions. If reporting recovered
   space, measure deleted file bytes and/or disk free space; distinguish logical
   file size from physical free-space changes and do not present an estimate as
   a measurement.

Never use `git worktree remove --force`, `git clean -fdx` or `git reset --hard`.
Do not automatically delete unmerged branches, another task's worktree or unknown
files. If private historical material prevents a decision, retain only that small
blocking payload, not its surrounding obsolete builds. Keep local cleanup records,
absolute paths, usernames and experimental assets out of commits. A docs-only
lifecycle update needs diff/scope verification; it does not require executing
Python tests, packaging or installing dependencies.

------------------------------------------------------------------------
