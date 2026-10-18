# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for the Local Chat Analyzer desktop app.

Build with:
    python -m PyInstaller LocalChatAnalyzer.spec

Output: dist/Echo/Echo.exe
"""

from pathlib import Path
from importlib.metadata import version
import tomllib

from PyInstaller.utils.hooks import copy_metadata


project_root = Path(SPEC).resolve().parent
release_version = tomllib.loads(
    (project_root / "pyproject.toml").read_text(encoding="utf-8")
)["project"]["version"]
if version("qq-chat-analyzer") != release_version:
    raise RuntimeError(
        "Installed Echo version differs from pyproject.toml; "
        "refresh the project installation before building."
    )
if version("velopack") != "1.2.161":
    raise RuntimeError("The desktop build requires Velopack 1.2.161.")
resources = (
    project_root / "stopwords.txt",
    project_root / "stopwords_topic.txt",
    project_root / "stopwords_culture.txt",
    project_root / "wechat_login_guide.png",
)
echo_icon = project_root / "assets/branding/echo/echo_icon.ico"
windows_exe_icon = project_root / "branding/Echo.ico"
echo_favicon = project_root / "assets/branding/echo/echo_icon_32.png"
echo_report_logo = project_root / "assets/branding/echo/echo_wordmark_with_slogan.png"
echo_expression_assets = project_root / "frontend/echo_report/wechat-emojis"
echo_qq_expression_assets = project_root / "frontend/echo_report/qq-emojis"
datas = [(str(path), ".") for path in resources]
datas.append((str(project_root / "scripts/windows_runtime_manifest.json"), "scripts"))
datas.append((str(project_root / "scripts/qq_napcat_runtime_pins.json"), "scripts"))
datas += copy_metadata("qq-chat-analyzer")
datas += copy_metadata("velopack")
datas.append((str(echo_icon), "assets/branding/echo"))
datas.append((str(echo_favicon), "assets/branding/echo"))
datas.append((str(echo_report_logo), "assets/branding/echo"))
datas.append((str(echo_expression_assets), "frontend/echo_report/wechat-emojis"))
datas.append((str(echo_qq_expression_assets), "frontend/echo_report/qq-emojis"))


# Libraries that only the legacy CLI artifacts need. The desktop app writes
# nothing but echo-report.json / echo-report.html, so its import graph never
# reaches matplotlib, wordcloud, Pillow or pandas (nor pytest/pygments, which
# pandas.testing drags in). Excluding them keeps Echo.exe small; the source
# install and the ``qqchat`` CLI keep the full dependency set.
#
# jieba reaches numpy only through jieba.lac_small.predict / .utils, which are
# imported lazily from inside jieba.Tokenizer.cut behind
# ``use_paddle and is_paddle_installed``. Echo uses plain jieba.lcut /
# jieba.load_userdict and never enables paddle, so that subpackage is dead
# code in the frozen app -- and with it, numpy and its numpy.libs OpenBLAS
# runtime. Both names are excluded explicitly: excluding the subpackage is
# what actually removes numpy, while listing numpy keeps the intent (and its
# absence from the package) asserted by the build contract tests.
desktop_excludes = [
    "matplotlib",
    "mpl_toolkits",
    "wordcloud",
    "pandas",
    "PIL",
    "contourpy",
    "kiwisolver",
    "fontTools",
    "pytest",
    "_pytest",
    "pygments",
    "jieba.lac_small",
    "numpy",
]


a = Analysis(
    ["desktop_entry.py"],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=desktop_excludes,
    noarchive=False,
    optimize=0,
)
# The upstream jieba hook collects all data independently of module excludes.
# Ordinary lcut uses dict.txt and the Python HMM; only Paddle uses lac_small.
# Installation provenance can contain a builder's local source path. Runtime
# version/dependency/entrypoint metadata remains available without direct_url.
a.datas = [
    entry for entry in a.datas
    if Path(entry[0]).parts[:2] != ("jieba", "lac_small")
    and not (Path(entry[0]).name == "direct_url.json"
             and Path(entry[0]).parent.name.endswith(".dist-info"))
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Echo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=str(windows_exe_icon),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Echo",
)
