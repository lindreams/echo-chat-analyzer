"""Behavior tests for QQ configuration persistence and passive auth reuse.

Everything here uses fictional temp paths and stub runtime/connection
collaborators. No real QQ process, authorization, or chat data is ever touched.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _module():
    return importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_setup_service"
    )


def _connection_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_connection_service"
    )


def _runtime_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_runtime_manager"
    )


class _FakeRuntimeManager:
    """Stand in for QQRuntimeManager with configurable lifecycle state."""

    def __init__(
        self,
        *,
        running: bool = False,
        available: bool = True,
        start_error: bool = False,
    ) -> None:
        self._running = running
        self._available = available
        self._start_error = start_error
        self.start_calls = 0

    def get_status(self):
        module = _runtime_module()
        if not self._available:
            return module.QQRuntimeStatus(
                state=module.QQRuntimeState.UNAVAILABLE,
                available=False,
                message="\u672a\u68c0\u6d4b\u5230 QQ \u6570\u636e\u6e90\u3002",
                action_hint="",
            )
        if self._start_error:
            return module.QQRuntimeStatus(
                state=module.QQRuntimeState.ERROR,
                available=True,
                message="\u64cd\u4f5c\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002",
                action_hint="\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002",
            )
        return module.QQRuntimeStatus(
            state=(
                module.QQRuntimeState.RUNNING
                if self._running
                else module.QQRuntimeState.STOPPED
            ),
            available=self._running,
            message="",
            action_hint="",
        )

    def start(self):
        self.start_calls += 1
        if self._start_error:
            return self.get_status()
        self._running = True
        return self.get_status()


class _FakeConnectionService:
    def __init__(self, status, after_start_status=None):
        self._status = status
        self._after_start_status = after_start_status
        self.check_calls = 0

    def check_status(self):
        self.check_calls += 1
        if self._after_start_status is not None and self.check_calls > 1:
            return self._after_start_status
        return self._status


class _FakeProviderFactory:
    def __init__(self):
        self.invalidate_calls = 0

    def invalidate(self):
        self.invalidate_calls += 1


def _config(tmp_path: Path, *, complete: bool = True):
    module = _module()
    runtime = tmp_path / "runtime"
    if complete:
        for name in ("napcat.mjs", "NapCatWinBootMain.exe", "NapCatWinBootHook.dll", "plugins/napcat-plugin-echo/index.mjs", "plugins/napcat-plugin-echo/bridge.mjs"):
            path = runtime / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fictional", encoding="utf-8")
    return module.QQEnvironmentConfig(runtime_directory=runtime, runtime_mode="custom")


def _connection_status(*, available: bool = True):
    module = _connection_module()
    return module.QQConnectionStatus(
        available=available,
        runtime_running=available,
        qq_online=available,
        version="4.1.0",
        message=(
            "QQ \u5df2\u8fde\u63a5\u3002"
            if available
            else "QQ \u672a\u8fde\u63a5\u3002"
        ),
        action_hint="",
    )


def _service(
    tmp_path: Path,
    *,
    config,
    runtime_manager,
    connection_status=None,
    connection_after_status=None,
    provider_factory=None,
    with_connection: bool = True,
):
    module = _module()
    return module.QQSetupService(
        config_loader=module.QQEnvironmentConfigLoader(
            config_path=tmp_path / "qq.json"
        ),
        config_writer=module.QQEnvironmentConfigWriter(
            config_path=tmp_path / "qq.json"
        ),
        provider_factory=provider_factory,
        connection_service=(
            _FakeConnectionService(
                connection_status,
                after_start_status=connection_after_status,
            )
            if with_connection
            else None
        ),
        runtime_manager=runtime_manager,
    )


def _stored_config(tmp_path: Path):
    module = _module()
    return module.QQEnvironmentConfigLoader(
        config_path=tmp_path / "qq.json"
    ).load()


# ------------------------------------------------------------------ connect


def test_save_environment_persists_default_without_starting_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _config(tmp_path)
    env_module = importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_environment_config"
    )
    monkeypatch.setattr(
        env_module,
        "bundled_qq_runtime_available",
        lambda: True,
    )
    monkeypatch.setattr(
        env_module,
        "default_qq_environment_config",
        lambda: config,
    )
    manager = _FakeRuntimeManager()
    factory = _FakeProviderFactory()
    status = _connection_status()
    service = _service(
        tmp_path,
        config=config,
        runtime_manager=manager,
        connection_status=_connection_status(available=False),
        connection_after_status=status,
        provider_factory=factory,
    )

    result = service.save_environment(config)

    assert manager.start_calls == 0
    assert factory.invalidate_calls == 1
    assert result.available is False
    assert result.runtime_running is False
    assert result.qq_online is False
    stored = _stored_config(tmp_path)
    assert stored.runtime_directory == config.runtime_directory


def test_auth_flow_keeps_an_existing_user_config(tmp_path: Path) -> None:
    module = _module()
    writer = module.QQEnvironmentConfigWriter(
        config_path=tmp_path / "qq.json"
    )
    from dataclasses import replace
    custom = replace(_config(tmp_path), napcat_bridge_url="http://127.0.0.1:40999")
    writer.save(custom)

    manager = _FakeRuntimeManager()
    factory = _FakeProviderFactory()
    service = _service(
        tmp_path,
        config=custom,
        runtime_manager=manager,
        connection_status=_connection_status(),
        provider_factory=factory,
    )

    before = (tmp_path / "qq.json").read_bytes()
    from qq_chat_analyzer.application.qq.qq_auth_bridge import QQAuthBridge

    def unexpected_launch():
        raise AssertionError("a connected source must not launch again")

    result = QQAuthBridge(
        setup_service=service,
        connection_service=service._connection_service,
        window_launcher=unexpected_launch,
    ).start_auth_flow()

    assert result.connected
    assert manager.start_calls == 0
    assert factory.invalidate_calls == 0
    assert (tmp_path / "qq.json").read_bytes() == before
    stored = _stored_config(tmp_path)
    assert stored.napcat_bridge_url == "http://127.0.0.1:40999"
