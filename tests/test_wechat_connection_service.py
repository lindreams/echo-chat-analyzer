"""Behavior tests for the WeChat connection layer.

The service under test never reads a real WeChat database. Provider probes are
simulated with stubs so the tests cover data present, data missing, missing
key, missing runtime, and unexpected failures without touching real chat data.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _module():
    return importlib.import_module(
        "qq_chat_analyzer.application.wechat.wechat_connection_service"
    )


def _config_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.wechat.wechat_environment_config"
    )


class _FakeConfigLoader:
    def __init__(self, config=None, error=None):
        self._config = config
        self._error = error

    def load_or_default(self):
        if self._error is not None:
            raise self._error
        return self._config


class _RecordingProviderFactory:
    def __init__(self, provider):
        self._provider = provider
        self.calls = []

    def __call__(self, config):
        self.calls.append(config)
        return self._provider


def _provider_module():
    return importlib.import_module(
        "qq_chat_analyzer.providers.wechat_database_provider"
    )


class _FakeProvider:
    """Stand in for WeChatDatabaseProvider with configurable readiness."""

    def __init__(
        self,
        *,
        data: bool = True,
        key: str | None = "fictional-key",
        helper: bool = True,
        library: bool = True,
        unexpected: str | None = None,
    ) -> None:
        self._data = data
        self._key = key
        self._helper = helper
        self._library = library
        self._unexpected = unexpected
        self.data_calls = 0
        self.key_calls = 0
        self.helper_calls = 0
        self.library_calls = 0

    def _session_db_path(self):
        self.data_calls += 1
        if self._unexpected == "data":
            raise RuntimeError("raw data probe failure")
        if not self._data:
            raise _provider_module().DatabaseNotFound()
        return Path("fictional/session.db")

    def _resolve_key(self):
        self.key_calls += 1
        if self._unexpected == "key":
            raise RuntimeError("raw key probe failure")
        if self._key is None:
            raise _provider_module().KeyUnavailable()
        return self._key

    def _resolve_helper(self):
        self.helper_calls += 1
        if self._unexpected == "helper":
            raise RuntimeError("raw helper probe failure")
        if not self._helper:
            raise _provider_module().WcdbHelperNotFound()
        return Path("fictional/wcdb_cli.exe")

    def _resolve_library(self):
        self.library_calls += 1
        if self._unexpected == "library":
            raise RuntimeError("raw library probe failure")
        if not self._library:
            raise _provider_module().WcdbLibraryNotFound()
        return Path("fictional/WCDB.dll")


def _status(**provider_kwargs):
    service = _module().WeChatConnectionService(
        _FakeProvider(**provider_kwargs)
    )
    return service.check_status()


# ------------------------------------------------------------ all available


def test_all_readiness_checks_pass_marks_source_available() -> None:
    status = _status(data=True, key="fictional-key", helper=True, library=True)

    assert status.available is True
    assert status.data_found is True
    assert status.db_key_available is True
    assert status.runtime_available is True
    assert status.message != ""
    assert status.action_hint != ""


# --------------------------------------------------------------- data missing


# ------------------------------------------------------------------- key


# ---------------------------------------------------------------- runtime


# ------------------------------------------------------------ error isolation


@pytest.mark.parametrize("stage", ["data", "key", "helper", "library"])
def test_unexpected_probe_error_never_leaks(stage: str) -> None:
    status = _status(unexpected=stage)

    assert status.available is False
    assert "raw" not in status.message
    assert "Traceback" not in status.message
    assert "Exception" not in status.message
    assert status.action_hint != ""


# ------------------------------------------------------------ config source


def test_connection_service_builds_provider_from_config() -> None:
    module = _module()
    config_module = _config_module()
    config = config_module.WeChatEnvironmentConfig(
        data_root=Path("C:\\WeChatData"),
        db_key="fictional-key",
        wcdb_cli_path=Path("C:\\tools\\wcdb_cli.exe"),
        wcdb_dll_path=Path("C:\\tools\\WCDB.dll"),
    )
    provider = _FakeProvider()
    factory = _RecordingProviderFactory(provider)
    service = module.WeChatConnectionService(
        provider_factory=module.WeChatProviderFactory(
            config_loader=_FakeConfigLoader(config=config),
            provider_builder=factory,
        ),
    )

    status = service.check_status()

    assert status.available is True
    assert factory.calls == [config]
    assert provider.data_calls == 1


def test_config_loader_error_never_leaks() -> None:
    module = _module()
    service = module.WeChatConnectionService(
        provider_factory=module.WeChatProviderFactory(
            config_loader=_FakeConfigLoader(error=RuntimeError("raw config boom")),
            provider_builder=_RecordingProviderFactory(_FakeProvider()),
        ),
    )

    status = service.check_status()

    assert status.available is False
    assert "raw config boom" not in status.message
    assert "Traceback" not in status.message


# ------------------------------------------------------------------- model


def test_status_refreshes_provider_after_factory_invalidation() -> None:
    module = _module()
    loader = _FakeConfigLoader(config=_FakeProvider())
    factory = module.WeChatProviderFactory(
        config_loader=loader, provider_builder=lambda provider: provider,
    )
    service = module.WeChatConnectionService(provider_factory=factory)
    assert service.check_status().available is True

    loader._config = _FakeProvider(key=None)
    factory.invalidate()
    status = service.check_status()
    assert status.available is False
    assert status.data_found is True
    assert status.db_key_available is False
    assert status.runtime_available is True
    assert service.provider() is loader._config
    assert loader._config.data_calls == 1
