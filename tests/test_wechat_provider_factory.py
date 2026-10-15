"""RED tests for Phase 8.6.4B: unified WeChat provider configuration.

These tests pin the invariant that the WeChat connection status and the
WeChat session/message reads are built from one configuration source and one
provider instance. No real WeChat data, keys, or databases are involved.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _factory_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.wechat.wechat_provider_factory"
    )


def _config_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.wechat.wechat_environment_config"
    )


def _connection_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.wechat.wechat_connection_service"
    )


def _export_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.wechat.wechat_export_import_service"
    )


def _write_config(directory: Path, **overrides) -> Path:
    (directory / "wcdb_cli.exe").write_text("fake", encoding="utf-8")
    (directory / "WCDB.dll").write_text("fake", encoding="utf-8")
    payload = {
        "data_root": str(directory / "data"),
        "db_key": "fictional-key",
        "wcdb_cli_path": str(directory / "wcdb_cli.exe"),
        "wcdb_dll_path": str(directory / "WCDB.dll"),
    }
    payload.update(overrides)
    config_path = directory / "wechat.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


class _StubProvider:
    def __init__(self, config):
        self.config = config


def _factory(tmp_path, *, builder=_StubProvider, **overrides):
    config_module = _config_module()
    loader = config_module.WeChatEnvironmentConfigLoader(
        _write_config(tmp_path, **overrides)
    )
    return _factory_module().WeChatProviderFactory(
        config_loader=loader,
        provider_builder=builder,
    )


# ------------------------------------------------------- factory behaviour


# ------------------------------------------- shared source across services


def test_config_change_is_visible_to_both_services(tmp_path):
    factory = _factory(tmp_path, db_key="first-key")

    connection_service = _connection_module().WeChatConnectionService(
        provider_factory=factory,
    )
    export_service = _export_module().WeChatExportImportService(
        provider_factory=factory,
    )

    assert connection_service.provider().config.db_key == "first-key"

    _write_config(tmp_path, db_key="second-key")
    factory.invalidate()

    assert connection_service.provider().config.db_key == "second-key"
    assert export_service.provider().config.db_key == "second-key"
    assert connection_service.provider() is export_service.provider()


# ----------------------------------------------------- architecture guards
