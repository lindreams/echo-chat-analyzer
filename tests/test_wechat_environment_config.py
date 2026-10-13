"""Behavior tests for the WeChat environment config loader.

All tests use temporary config files. No real WeChat data, key, or runtime
path is touched.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.application.wechat.wechat_environment_config import (  # noqa: E402
    WeChatConfigCorrupted,
    WeChatConfigNotFound,
    WeChatEnvironmentConfig,
    WeChatEnvironmentConfigLoader,
)


def _loader(tmp_path: Path, payload: object) -> WeChatEnvironmentConfigLoader:
    config_path = tmp_path / "wechat.json"
    if isinstance(payload, str):
        config_path.write_text(payload, encoding="utf-8")
    else:
        config_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    return WeChatEnvironmentConfigLoader(config_path)


def test_loader_reads_a_complete_config(tmp_path: Path) -> None:
    loader = _loader(
        tmp_path,
        {
            "data_root": "D:\\WeChatData\\xwechat_files",
            "db_key": "a" * 64,
            "wcdb_cli_path": "C:\\tools\\wcdb_cli.exe",
            "wcdb_dll_path": "C:\\tools\\WCDB.dll",
        },
    )

    config = loader.load()

    assert config.data_root == Path("D:\\WeChatData\\xwechat_files")
    assert config.db_key == "a" * 64
    assert config.wcdb_cli_path == Path("C:\\tools\\wcdb_cli.exe")
    assert config.wcdb_dll_path == Path("C:\\tools\\WCDB.dll")
    assert dataclasses.is_dataclass(config)


def test_loader_treats_missing_config_as_a_user_safe_error(
    tmp_path: Path,
) -> None:
    loader = WeChatEnvironmentConfigLoader(tmp_path / "absent.json")

    with pytest.raises(WeChatConfigNotFound) as excinfo:
        loader.load()

    assert excinfo.value.code == "wechat_config_not_found"
    assert excinfo.value.public_message != ""


def test_loader_treats_corrupted_config_as_a_user_safe_error(
    tmp_path: Path,
) -> None:
    loader = _loader(tmp_path, "{not-json")

    with pytest.raises(WeChatConfigCorrupted) as excinfo:
        loader.load()

    assert excinfo.value.code == "wechat_config_corrupted"
    assert excinfo.value.public_message != ""
    assert "not-json" not in str(excinfo.value)


def test_loader_treats_non_object_json_as_corrupted(tmp_path: Path) -> None:
    loader = _loader(tmp_path, ["not", "a", "config"])

    with pytest.raises(WeChatConfigCorrupted):
        loader.load()


def _patch_bundled_defaults(monkeypatch, module, bundle: Path):
    wechat = bundle / "runtime" / "wechat"
    monkeypatch.setattr(
        module,
        "default_wechat_wcdb_cli_path",
        lambda: wechat / "wcdb_cli.exe",
    )
    monkeypatch.setattr(
        module,
        "default_wechat_wcdb_dll_path",
        lambda: wechat / "WCDB.dll",
    )


def test_load_or_default_uses_bundled_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    wechat = bundle / "runtime" / "wechat"
    wechat.mkdir(parents=True)
    (wechat / "wcdb_cli.exe").write_text("fake", encoding="utf-8")
    (wechat / "WCDB.dll").write_text("fake", encoding="utf-8")
    module = importlib.import_module(
        "qq_chat_analyzer.application.wechat.wechat_environment_config"
    )
    _patch_bundled_defaults(monkeypatch, module, bundle)

    config = module.WeChatEnvironmentConfigLoader(
        tmp_path / "absent.json"
    ).load_or_default()

    assert config.wcdb_cli_path == wechat / "wcdb_cli.exe"
    assert config.wcdb_dll_path == wechat / "WCDB.dll"


def test_load_or_default_raises_without_bundled_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "empty-bundle"
    bundle.mkdir(parents=True)
    module = importlib.import_module(
        "qq_chat_analyzer.application.wechat.wechat_environment_config"
    )
    _patch_bundled_defaults(monkeypatch, module, bundle)

    with pytest.raises(module.WeChatConfigNotFound):
        module.WeChatEnvironmentConfigLoader(
            tmp_path / "absent.json"
        ).load_or_default()


def test_load_or_default_prefers_user_config(tmp_path: Path) -> None:
    runtime = tmp_path / "custom-runtime"
    runtime.mkdir()
    cli = runtime / "wcdb_cli.exe"
    dll = runtime / "WCDB.dll"
    cli.write_text("fake", encoding="utf-8")
    dll.write_text("fake", encoding="utf-8")
    loader = _loader(
        tmp_path,
        {
            "wcdb_cli_path": str(cli),
            "wcdb_dll_path": str(dll),
        },
    )

    config = loader.load_or_default()

    assert config.wcdb_cli_path == cli
    assert config.wcdb_dll_path == dll


def test_load_or_default_repairs_stale_runtime_paths(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    wechat = bundle / "runtime" / "wechat"
    wechat.mkdir(parents=True)
    (wechat / "wcdb_cli.exe").write_text("fake", encoding="utf-8")
    (wechat / "WCDB.dll").write_text("fake", encoding="utf-8")
    module = importlib.import_module(
        "qq_chat_analyzer.application.wechat.wechat_environment_config"
    )
    _patch_bundled_defaults(monkeypatch, module, bundle)
    loader = _loader(
        tmp_path,
        {
            "data_root": str(tmp_path / "saved-root"),
            "db_key": "c" * 64,
            "wcdb_cli_path": str(tmp_path / "old" / "wcdb_cli.exe"),
            "wcdb_dll_path": str(tmp_path / "old" / "WCDB.dll"),
        },
    )

    config = loader.load_or_default()

    assert config.data_root == tmp_path / "saved-root"
    assert config.db_key == "c" * 64
    assert config.wcdb_cli_path == wechat / "wcdb_cli.exe"
    assert config.wcdb_dll_path == wechat / "WCDB.dll"


def _fictional_runtime(root: Path) -> Path:
    """Create a fictional ``runtime/wechat`` directory holding one pair."""
    wechat = root / "runtime" / "wechat"
    wechat.mkdir(parents=True)
    (wechat / "wcdb_cli.exe").write_text("fake", encoding="utf-8")
    (wechat / "WCDB.dll").write_text("fake", encoding="utf-8")
    return wechat


def _config_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.wechat.wechat_environment_config"
    )


def test_load_or_default_rebinds_a_removed_portable_install_to_this_setup_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A Portable install the user removed falls back to this Setup runtime.

    The whole path chain is exercised end to end: the loader asks the resource
    helper, which resolves the runtime next to the frozen executable of the
    current installation rather than inside the bundle or a source checkout.
    """
    resources = importlib.import_module("qq_chat_analyzer.resources")
    current = tmp_path / "Echo" / "current"
    setup_wechat = _fictional_runtime(current)
    monkeypatch.setattr(resources, "_PROJECT_ROOT", tmp_path / "source-checkout")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(current / "Echo.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "meipass"), raising=False)
    removed_portable = tmp_path / "Echo-0.1.0-portable"
    loader = _loader(
        tmp_path,
        {
            "data_root": str(tmp_path / "saved-root"),
            "db_key": "b" * 64,
            "wcdb_cli_path": str(
                removed_portable / "runtime" / "wechat" / "wcdb_cli.exe"
            ),
            "wcdb_dll_path": str(
                removed_portable / "runtime" / "wechat" / "WCDB.dll"
            ),
        },
    )

    config = loader.load_or_default()

    assert config.wcdb_cli_path == setup_wechat / "wcdb_cli.exe"
    assert config.wcdb_dll_path == setup_wechat / "WCDB.dll"
    assert config.data_root == tmp_path / "saved-root"
    assert config.db_key == "b" * 64


def test_load_or_default_keeps_a_complete_pair_from_an_older_install(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A saved pair that still exists is kept, whatever install produced it."""
    bundle = tmp_path / "current-setup"
    _fictional_runtime(bundle)
    module = _config_module()
    _patch_bundled_defaults(monkeypatch, module, bundle)
    older = _fictional_runtime(tmp_path / "Echo-0.1.0-portable")
    loader = _loader(
        tmp_path,
        {
            "wcdb_cli_path": str(older / "wcdb_cli.exe"),
            "wcdb_dll_path": str(older / "WCDB.dll"),
        },
    )

    config = loader.load_or_default()

    assert config.wcdb_cli_path == older / "wcdb_cli.exe"
    assert config.wcdb_dll_path == older / "WCDB.dll"


@pytest.mark.parametrize("surviving", ["older-install", "custom-directory"])
def test_load_or_default_never_mixes_a_surviving_path_with_this_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    surviving: str,
) -> None:
    """Half of a saved pair must not be completed from another installation.

    The surviving CLI may belong to the user, and an old bundled path cannot be
    told apart from a custom one, so the saved pair is returned exactly as it is
    instead of being blended with this installation's DLL. The missing half then
    surfaces as a missing component instead of a runtime that looks complete.
    """
    bundle = tmp_path / "current-setup"
    setup_wechat = _fictional_runtime(bundle)
    module = _config_module()
    _patch_bundled_defaults(monkeypatch, module, bundle)
    source = _fictional_runtime(
        tmp_path
        / ("Echo-0.1.0-portable" if surviving == "older-install" else "custom-tools")
    )
    (source / "WCDB.dll").unlink()
    loader = _loader(
        tmp_path,
        {
            "wcdb_cli_path": str(source / "wcdb_cli.exe"),
            "wcdb_dll_path": str(source / "WCDB.dll"),
        },
    )
    saved = loader.config_path().read_text(encoding="utf-8")

    config = loader.load_or_default()

    assert config.wcdb_cli_path == source / "wcdb_cli.exe"
    assert config.wcdb_dll_path == source / "WCDB.dll"
    assert config.wcdb_dll_path != setup_wechat / "WCDB.dll"
    assert loader.config_path().read_text(encoding="utf-8") == saved


def test_load_or_default_reports_missing_runtime_instead_of_faking_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With no usable pair anywhere, saved paths stay and nothing is invented."""
    empty_bundle = tmp_path / "incomplete-setup"
    empty_bundle.mkdir()
    module = _config_module()
    _patch_bundled_defaults(monkeypatch, module, empty_bundle)
    loader = _loader(
        tmp_path,
        {
            "data_root": str(tmp_path / "saved-root"),
            "db_key": "d" * 64,
            "wcdb_cli_path": str(tmp_path / "gone" / "wcdb_cli.exe"),
            "wcdb_dll_path": str(tmp_path / "gone" / "WCDB.dll"),
        },
    )

    config = loader.load_or_default()

    assert config.wcdb_cli_path == tmp_path / "gone" / "wcdb_cli.exe"
    assert config.wcdb_dll_path == tmp_path / "gone" / "WCDB.dll"
    assert config.data_root == tmp_path / "saved-root"
    assert config.db_key == "d" * 64


def test_loader_tolerates_missing_fields(tmp_path: Path) -> None:
    loader = _loader(tmp_path, {})

    config = loader.load()

    assert config == WeChatEnvironmentConfig()
    assert config.data_root is None
    assert config.db_key is None
    assert config.wcdb_cli_path is None
    assert config.wcdb_dll_path is None


def test_loader_parses_path_fields_and_ignores_empty_values(
    tmp_path: Path,
) -> None:
    loader = _loader(
        tmp_path,
        {
            "data_root": "C:\\WeChat",
            "db_key": "",
            "wcdb_cli_path": 123,
            "wcdb_dll_path": "   ",
        },
    )

    config = loader.load()

    assert config.data_root == Path("C:\\WeChat")
    assert config.db_key is None
    assert config.wcdb_cli_path is None
    assert config.wcdb_dll_path is None


def test_environment_config_is_frozen() -> None:
    config = WeChatEnvironmentConfig(data_root=Path("C:\\WeChat"))

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.data_root = Path("D:\\Other")
