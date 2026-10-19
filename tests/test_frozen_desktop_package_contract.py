"""Frozen Windows package contracts for retained modules and retired capabilities.

Full-only: this inspects an already built ``dist/Echo`` tree. Building the
package is a separate step (``scripts/build_windows_exe.ps1``), so the tests
skip when no frozen artifact exists instead of starting a build here.
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import importlib.metadata
import sys
import tomllib
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_APP = PROJECT_ROOT / "dist" / "Echo"
INTERNAL = DIST_APP / "_internal"
EXECUTABLE = DIST_APP / "Echo.exe"

# Retained on purpose: Echo never uses jieba LAC, but plain segmentation and
# the other jieba data files stay in the package.
KEPT_RUNTIME_DIRECTORIES = ("PySide6", "shiboken6", "zstandard")

RETIRED_QQ_MODULES = (
    "qq_chat_analyzer.providers.qq_chat_exporter_provider",
    "qq_chat_analyzer.application.qq.qce_compat",
    "qq_chat_analyzer.application.qq_export_import_service",
    "qq_chat_analyzer.application.export_task_manager",
    "qq_chat_analyzer.application.qq_transient_export",
    "qq_chat_analyzer.qq_chat_exporter_adapter",
    "qq_chat_analyzer.parser",
)

pytestmark = pytest.mark.slow_integration


def _require_frozen_build() -> None:
    if not EXECUTABLE.is_file():
        pytest.skip(f"no frozen desktop build at {DIST_APP}")


def _frozen_modules() -> dict:
    """Return the module table embedded in the frozen executable's PYZ."""
    _require_frozen_build()
    from PyInstaller.archive.readers import CArchiveReader

    reader = CArchiveReader(str(EXECUTABLE))
    return reader.open_embedded_archive("PYZ.pyz").toc


@pytest.mark.parametrize("filename", [
    "windows_runtime_manifest.json",
    "qq_napcat_runtime_pins.json",
    "sqlite_runtime_pins.json",
])
def test_frozen_package_ships_current_qq_resource_contract(filename, monkeypatch) -> None:
    _require_frozen_build()
    from qq_chat_analyzer import resources

    packaged = INTERNAL / "scripts" / filename
    assert packaged.is_file(), packaged
    assert hashlib.sha256(packaged.read_bytes()).hexdigest() == hashlib.sha256(
        (PROJECT_ROOT / "scripts" / filename).read_bytes()
    ).hexdigest(), filename
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(INTERNAL), raising=False)
    assert resources.resource_path("scripts/" + filename) == packaged


def test_frozen_managed_qq_resolves_from_packaged_metadata(monkeypatch, tmp_path) -> None:
    _require_frozen_build()
    from qq_chat_analyzer import resources
    from qq_chat_analyzer.application.qq.qq_environment_config import QQEnvironmentConfig
    from qq_chat_analyzer.application.qq.qq_runtime_paths import resolve_runtime_paths

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(INTERNAL), raising=False)
    monkeypatch.setattr(sys, "executable", str(EXECUTABLE))
    monkeypatch.setattr(resources, "_PROJECT_ROOT", tmp_path / "absent-checkout")
    user = resources.user_data_root()
    paths = resolve_runtime_paths(QQEnvironmentConfig(runtime_mode="managed"))
    assert paths.program_root == DIST_APP / "runtime/qq-napcat-candidate"
    assert paths.work_root.parent == user / "runtime/qq"
    assert paths.snapshot_root == user / "transient/qq-direct-db"
    assert not user.exists()


def test_frozen_release_version_is_available_without_source_checkout() -> None:
    modules = _frozen_modules()
    assert "qq_chat_analyzer.version" in modules
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    distributions = [
        distribution for distribution in importlib.metadata.distributions(path=[str(INTERNAL)])
        if distribution.metadata["Name"] == "qq-chat-analyzer"
    ]
    assert len(distributions) == 1
    assert distributions[0].version == project["project"]["version"]
    assert not list(INTERNAL.glob("*.dist-info/direct_url.json"))


def _manifest() -> dict:
    return json.loads(
        (INTERNAL / "scripts/windows_runtime_manifest.json").read_text(encoding="utf-8")
    )


def test_frozen_release_tree_has_no_run_residue() -> None:
    """A smoke run must never reach the release tree the user receives."""
    _require_frozen_build()

    residue = [
        relative
        for relative in _manifest()["releaseTreePrivatePaths"]
        if (DIST_APP / relative).exists()
    ]

    assert residue == []


def test_frozen_package_ships_the_pinned_wechat_native_assets() -> None:
    """Only the pinned WeChat native binaries may be shipped."""
    _require_frozen_build()
    runtime = DIST_APP / "runtime"

    for relative, expected in _manifest()["wechatPinnedAssets"].items():
        artifact = runtime / relative
        assert artifact.is_file(), relative
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected, relative


def test_frozen_sqlite_uses_the_pinned_dll() -> None:
    _require_frozen_build()
    import runpy

    tools = runpy.run_path(str(PROJECT_ROOT / "scripts/bootstrap_sqlite_runtime.py"))
    tools["verify_dll"](INTERNAL / "sqlite3.dll")
    assert (INTERNAL / "_sqlite3.pyd").is_file()
    assert list(INTERNAL.rglob("sqlite3.dll")) == [INTERNAL / "sqlite3.dll"]


def test_packaged_sqlite_extension_performs_transactions_and_backup(tmp_path) -> None:
    """Exercise the packaged CPython extension, not just LoadLibrary/version."""
    _require_frozen_build()
    result = subprocess.run([sys.executable, "-c", """
import ctypes, hashlib, json, sys
from pathlib import Path
from contextlib import closing
internal, work = map(Path, sys.argv[1:])
sys.path.insert(0, str(internal))
import _sqlite3, sqlite3
assert Path(_sqlite3.__file__).resolve() == internal / '_sqlite3.pyd'
pins = json.loads((internal / 'scripts/sqlite_runtime_pins.json').read_text())
assert sqlite3.sqlite_version == pins['version']
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel.GetModuleHandleW.restype = ctypes.c_void_p
kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
buffer = ctypes.create_unicode_buffer(32768)
assert kernel.GetModuleFileNameW(kernel.GetModuleHandleW('sqlite3.dll'), buffer, len(buffer))
loaded = Path(buffer.value).resolve()
assert loaded == internal / 'sqlite3.dll'
assert hashlib.sha256(loaded.read_bytes()).hexdigest() == pins['dllSha256']
with closing(sqlite3.connect(work / 'fictional.db')) as db:
    assert db.execute('SELECT sqlite_source_id()').fetchone() == (pins['sourceId'],)
    db.execute('CREATE TABLE entries(id INTEGER PRIMARY KEY, body TEXT, data BLOB)')
    db.execute('INSERT INTO entries VALUES(?,?,?)', (1, 'fictional', b'\\x00\\xff'))
    db.commit()
    db.execute('DELETE FROM entries')
    db.rollback()
    assert db.execute('SELECT body,data FROM entries').fetchall() == [('fictional', b'\\x00\\xff')]
    with closing(sqlite3.connect(work / 'backup.db')) as backup:
        db.backup(backup)
        assert backup.execute('SELECT count(*) FROM entries').fetchone() == (1,)
        assert backup.execute('PRAGMA quick_check(1)').fetchone() == ('ok',)
    assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
""", str(INTERNAL.resolve()), str(tmp_path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
