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
import os
import sys
import tomllib

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_APP = Path(os.environ.get("ECHO_TEST_FROZEN_APP", PROJECT_ROOT / "dist" / "Echo"))
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


def test_frozen_package_retains_original_image_verification() -> None:
    modules = _frozen_modules()
    for name in ("qq_chat_analyzer.application.sticker_media", "PIL.Image",
                 "PIL.PngImagePlugin", "PIL.JpegImagePlugin", "PIL.GifImagePlugin",
                 "PIL.WebPImagePlugin"):
        assert name in modules, name
    assert list((INTERNAL / "PIL").glob("_imaging*.pyd"))
    assert list((INTERNAL / "PIL").glob("_webp*.pyd"))
    assert list(INTERNAL.glob("pillow-*.dist-info/licenses/LICENSE"))


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
