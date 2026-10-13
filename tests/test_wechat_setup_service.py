"""Tests for the WeChat setup service and config writer.

Privacy: every path, key, and identifier here is fabricated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qq_chat_analyzer.application.wechat.wechat_environment_config import (
    WeChatConfigCorrupted,
    WeChatConfigNotFound,
    WeChatConfigWriteFailed,
    WeChatEnvironmentConfig,
    WeChatEnvironmentConfigLoader,
    WeChatEnvironmentConfigWriter,
)
from qq_chat_analyzer.application.wechat.wechat_key_service import (
    WeChatKeyUnavailable,
)
from qq_chat_analyzer.application.wechat.wechat_provider_factory import (
    WeChatProviderFactory,
)
from qq_chat_analyzer.application.wechat.wechat_setup_service import (
    WeChatSetupService,
    WeChatSetupState,
    WeChatSetupStatus,
)
from qq_chat_analyzer.providers.wechat_database_provider import (
    DatabaseUnreadable,
)


def _config(tmp_path: Path) -> WeChatEnvironmentConfig:
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "wcdb_cli.exe").write_text("fake", encoding="utf-8")
    (runtime / "WCDB.dll").write_text("fake", encoding="utf-8")
    return WeChatEnvironmentConfig(
        data_root=tmp_path / "fake_xwechat_files",
        db_key="0f0f0f0f",
        wcdb_cli_path=tmp_path / "runtime" / "wcdb_cli.exe",
        wcdb_dll_path=tmp_path / "runtime" / "WCDB.dll",
    )


def _valid_wechat_root(
    tmp_path: Path,
    name: str = "wxid_fictional",
) -> Path:
    """Create one provider-readable WeChat 4.x account directory."""
    root = tmp_path / "xwechat_files" / name
    message_dir = root / "db_storage" / "message"
    message_dir.mkdir(parents=True, exist_ok=True)
    (message_dir / "session.db").write_text("fake", encoding="utf-8")
    (message_dir / "message_0.db").write_text("fake", encoding="utf-8")
    return root


def _isolated_setup_service(tmp_path: Path, **overrides) -> WeChatSetupService:
    """Build a setup service whose persisted config lives under tmp_path."""
    target = tmp_path / "config" / "wechat.json"
    defaults = {
        "config_loader": WeChatEnvironmentConfigLoader(target),
        "config_writer": WeChatEnvironmentConfigWriter(target),
    }
    defaults.update(overrides)
    return WeChatSetupService(**defaults)


class _StubConnectionService:
    def __init__(self, status: object) -> None:
        self._status = status
        self.calls = 0

    def check_status(self) -> object:
        self.calls += 1
        return self._status


class _StubKeyService:
    def __init__(
        self, *, key: str = "default_key", error: Exception | None = None, progress_callback=None
    ) -> None:
        self.key = key
        self.error = error
        self.calls = 0
        self.clear_calls = 0
        self._progress = progress_callback

    def clear(self) -> None:
        self.clear_calls += 1

    def acquire(self, progress=None) -> str:
        self.calls += 1
        callback = progress or self._progress
        if callback is not None:
            callback("helper line 1")
            callback("helper line 2")
        if self.error is not None:
            raise self.error
        return self.key


class _CountingFactory:
    def __init__(self) -> None:
        self.invalidations = 0

    def invalidate(self) -> None:
        self.invalidations += 1


# ------------------------------------------------------------------- writer


def test_writer_saves_config_as_stable_json(tmp_path: Path) -> None:
    target = tmp_path / "config" / "wechat.json"
    writer = WeChatEnvironmentConfigWriter(target)

    writer.save(_config(tmp_path))

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["db_key"] == "0f0f0f0f"
    assert payload["data_root"] == str(tmp_path / "fake_xwechat_files")
    assert list(payload) == sorted(payload)


def test_writer_creates_missing_directories(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "config" / "wechat.json"
    writer = WeChatEnvironmentConfigWriter(target)

    writer.save(_config(tmp_path))

    assert target.exists()


def test_writer_round_trips_through_loader(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"
    original = _config(tmp_path)

    WeChatEnvironmentConfigWriter(target).save(original)
    restored = WeChatEnvironmentConfigLoader(target).load()

    assert restored == original


def test_writer_omits_absent_optional_fields(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"
    writer = WeChatEnvironmentConfigWriter(target)

    writer.save(WeChatEnvironmentConfig(data_root=tmp_path / "only_root"))

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert "data_root" in payload
    assert payload.get("db_key") is None


def test_writer_converts_os_error_to_user_safe_error(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise OSError("ENOSPC on device 0xdeadbeef")

    writer = WeChatEnvironmentConfigWriter(target, writer=_explode)

    with pytest.raises(WeChatConfigWriteFailed) as caught:
        writer.save(_config(tmp_path))

    assert caught.value.code == "wechat_config_write_failed"
    assert caught.value.public_message
    assert "0xdeadbeef" not in caught.value.public_message
    assert "ENOSPC" not in caught.value.public_message


# ------------------------------------------------------------- check_setup


def test_check_setup_reports_missing_config(tmp_path: Path) -> None:
    class _MissingLoader:
        def config_path(self):
            return tmp_path / "wechat.json"

        def load(self):
            raise WeChatConfigNotFound()

        def load_or_default(self):
            raise WeChatConfigNotFound()

    service = _isolated_setup_service(
        tmp_path,
        config_loader=_MissingLoader(),
    )

    status = service.check_setup()

    assert isinstance(status, WeChatSetupStatus)
    assert status.state is WeChatSetupState.CONFIG_MISSING
    assert status.configured is False
    assert status.message
    assert status.action_hint


def test_check_setup_uses_bundled_defaults(tmp_path: Path) -> None:
    default_config = WeChatEnvironmentConfig(
        wcdb_cli_path=tmp_path / "bundled" / "wcdb_cli.exe",
        wcdb_dll_path=tmp_path / "bundled" / "WCDB.dll",
    )

    class _DefaultLoader:
        def config_path(self):
            return tmp_path / "wechat.json"

        def load(self):
            raise WeChatConfigNotFound()

        def load_or_default(self):
            return default_config

    service = _isolated_setup_service(
        tmp_path,
        config_loader=_DefaultLoader(),
    )

    status = service.check_setup()

    assert status.state is WeChatSetupState.CONFIG_READY
    assert status.configured is True


def test_check_setup_reports_ready_config(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"
    WeChatEnvironmentConfigWriter(target).save(_config(tmp_path))
    service = _isolated_setup_service(
        tmp_path,
        config_loader=WeChatEnvironmentConfigLoader(target),
    )

    status = service.check_setup()

    assert status.state is WeChatSetupState.CONFIG_READY
    assert status.configured is True


def test_check_setup_reports_invalid_config(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"
    target.write_text("{ this is not json", encoding="utf-8")
    service = _isolated_setup_service(
        tmp_path,
        config_loader=WeChatEnvironmentConfigLoader(target),
    )

    status = service.check_setup()

    assert status.state is WeChatSetupState.CONFIG_INVALID
    assert status.configured is False


def test_check_setup_never_raises_loader_errors(tmp_path: Path) -> None:
    class _AngryLoader:
        def config_path(self) -> Path:
            return tmp_path / "wechat.json"

        def load(self) -> WeChatEnvironmentConfig:
            raise RuntimeError("native handle 0xfeedface collapsed")

    status = _isolated_setup_service(
        tmp_path,
        config_loader=_AngryLoader(),
    ).check_setup()

    assert status.state is WeChatSetupState.CONFIG_INVALID
    assert "0xfeedface" not in status.message


def test_check_setup_exposes_config_path(tmp_path: Path) -> None:
    target = tmp_path / "config" / "wechat.json"
    service = _isolated_setup_service(
        tmp_path,
        config_loader=WeChatEnvironmentConfigLoader(target),
    )

    assert service.check_setup().config_path == target


# ------------------------------------------------------ detect_data_root


def test_detect_wechat_data_root_returns_detected_path(tmp_path: Path) -> None:
    detected = _valid_wechat_root(tmp_path)
    service = _isolated_setup_service(
        tmp_path,
        data_root_detector=lambda: detected,
    )

    assert service.detect_wechat_data_root() == detected


def test_detect_wechat_data_root_returns_none_when_missing(tmp_path: Path) -> None:
    service = _isolated_setup_service(
        tmp_path,
        data_root_detector=lambda: None,
    )

    assert service.detect_wechat_data_root() is None


def test_detect_wechat_data_root_swallows_detector_errors(tmp_path: Path) -> None:
    def _explode() -> Path:
        raise OSError("cannot read home 0xdeadbeef")

    service = _isolated_setup_service(tmp_path, data_root_detector=_explode)

    assert service.detect_wechat_data_root() is None


def test_detect_wechat_data_root_uses_provider_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    detector_module = __import__(
        "qq_chat_analyzer.application.wechat.wechat_data_detector",
        fromlist=["registered_wechat_data_dirs"],
    )
    monkeypatch.setattr(
        detector_module,
        "registered_wechat_data_dirs",
        lambda: [],
    )
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    service = _isolated_setup_service(tmp_path)

    detected = service.detect_wechat_data_root()

    assert detected is None or isinstance(detected, Path)


def test_detect_wechat_data_roots_returns_injected_roots(
    tmp_path: Path,
) -> None:
    roots = [
        _valid_wechat_root(tmp_path, "wxid_a"),
        _valid_wechat_root(tmp_path, "wxid_b"),
    ]
    service = _isolated_setup_service(
        tmp_path,
        data_roots_detector=lambda: roots,
    )

    assert service.detect_wechat_data_roots() == roots
    assert service.detect_wechat_data_root() is None


def test_detect_wechat_data_root_returns_single_roots_value(
    tmp_path: Path,
) -> None:
    root = _valid_wechat_root(tmp_path, "wxid_single")
    service = _isolated_setup_service(
        tmp_path,
        data_roots_detector=lambda: [root],
    )

    assert service.detect_wechat_data_roots() == [root]
    assert service.detect_wechat_data_root() == root


def test_detect_wechat_data_root_rejects_invalid_detector_result(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "WeChat Files" / "wxid_old"
    msg_dir = legacy / "Msg"
    msg_dir.mkdir(parents=True)
    (msg_dir / "MSG0.db").write_text("fake", encoding="utf-8")
    service = _isolated_setup_service(
        tmp_path,
        data_root_detector=lambda: legacy,
    )

    assert service.detect_wechat_data_root() is None


def test_detect_wechat_data_roots_filters_invalid_injected_roots(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "WeChat Files" / "wxid_old"
    msg_dir = legacy / "Msg"
    msg_dir.mkdir(parents=True)
    (msg_dir / "MSG0.db").write_text("fake", encoding="utf-8")
    valid = _valid_wechat_root(tmp_path, "wxid_valid")
    service = _isolated_setup_service(
        tmp_path,
        data_roots_detector=lambda: [legacy, valid],
    )

    assert service.detect_wechat_data_roots() == [valid]


def test_detect_wechat_data_roots_swallows_detector_errors(tmp_path: Path) -> None:
    def _explode() -> list[Path]:
        raise OSError("cannot read storage 0xdeadbeef")

    service = _isolated_setup_service(tmp_path, data_roots_detector=_explode)

    assert service.detect_wechat_data_roots() == []
    assert service.detect_wechat_data_root() is None


def test_detect_wechat_data_roots_restores_saved_valid_root(
    tmp_path: Path,
) -> None:
    target = tmp_path / "wechat.json"
    saved_root = tmp_path / "saved" / "wxid_fictional"
    message_dir = saved_root / "db_storage" / "message"
    message_dir.mkdir(parents=True)
    (message_dir / "session.db").write_text("fake", encoding="utf-8")
    (message_dir / "message_0.db").write_text("fake", encoding="utf-8")
    WeChatEnvironmentConfigWriter(target).save(
        WeChatEnvironmentConfig(data_root=saved_root, db_key="a" * 64)
    )
    detector_calls = []
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        data_roots_detector=lambda: detector_calls.append(1) or [],
    )

    assert service.detect_wechat_data_roots() == [saved_root]
    assert detector_calls == []


def test_invalid_saved_root_is_redetected_and_persisted(
    tmp_path: Path,
) -> None:
    target = tmp_path / "wechat.json"
    stale_root = tmp_path / "moved" / "old"
    detected_root = _valid_wechat_root(tmp_path, "wxid_fictional")
    WeChatEnvironmentConfigWriter(target).save(
        WeChatEnvironmentConfig(data_root=stale_root, db_key="b" * 64)
    )
    factory = _CountingFactory()
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        provider_factory=factory,
        data_roots_detector=lambda: [detected_root],
    )

    assert service.detect_wechat_data_roots() == [detected_root]
    restored = WeChatEnvironmentConfigLoader(target).load()
    assert restored.data_root == detected_root
    assert restored.db_key == "b" * 64
    assert factory.invalidations == 1


# --------------------------------------------------------- save_environment


def test_save_environment_persists_config(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
    )

    service.save_environment(_config(tmp_path))

    assert WeChatEnvironmentConfigLoader(target).load() == _config(tmp_path)
    assert service.check_setup().state is WeChatSetupState.CONFIG_READY


def test_save_environment_keeps_existing_db_key(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"
    key_service = _StubKeyService(key="b" * 64)
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        key_service=key_service,
    )
    original_key = "a" * 64

    service.save_environment(
        WeChatEnvironmentConfig(
            data_root=tmp_path / "data",
            db_key=original_key,
        )
    )

    assert key_service.calls == 0
    assert WeChatEnvironmentConfigLoader(target).load().db_key == original_key


def test_save_environment_survives_a_key_service_crash(tmp_path: Path) -> None:
    """A broken key service must not block saving the data root."""
    target = tmp_path / "wechat.json"
    key_service = _StubKeyService(error=RuntimeError("boom"))
    factory = _CountingFactory()
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        provider_factory=factory,
        key_service=key_service,
    )

    service.save_environment(
        WeChatEnvironmentConfig(data_root=tmp_path / "data")
    )

    assert target.exists() is True
    assert factory.invalidations == 1


def test_save_environment_without_key_service_keeps_missing_key(
    tmp_path: Path,
) -> None:
    target = tmp_path / "wechat.json"
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
    )

    service.save_environment(
        WeChatEnvironmentConfig(data_root=tmp_path / "data")
    )

    assert WeChatEnvironmentConfigLoader(target).load().db_key is None


def test_save_environment_invalidates_provider_factory(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"
    builds: list[WeChatEnvironmentConfig] = []

    def _builder(config: WeChatEnvironmentConfig) -> object:
        builds.append(config)
        return object()

    WeChatEnvironmentConfigWriter(target).save(
        WeChatEnvironmentConfig(data_root=tmp_path / "first_root")
    )
    factory = WeChatProviderFactory(
        config_loader=WeChatEnvironmentConfigLoader(target),
        provider_builder=_builder,
    )
    factory.create()
    assert builds[0].data_root == tmp_path / "first_root"

    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        provider_factory=factory,
    )
    service.save_environment(
        WeChatEnvironmentConfig(data_root=tmp_path / "second_root")
    )
    factory.create()

    assert len(builds) == 2
    assert builds[1].data_root == tmp_path / "second_root"


def test_save_environment_returns_fresh_connection_status(
    tmp_path: Path,
) -> None:
    target = tmp_path / "wechat.json"
    sentinel = object()
    connection = _StubConnectionService(sentinel)
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        connection_service=connection,
    )

    result = service.save_environment(_config(tmp_path))

    assert result is sentinel
    assert connection.calls == 1


def test_save_environment_without_connection_service(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
    )

    assert service.save_environment(_config(tmp_path)) is None


def test_save_environment_rejects_wrong_type(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
    )

    with pytest.raises(WeChatSetupService.InvalidEnvironment) as caught:
        service.save_environment({"data_root": "not a config"})

    assert caught.value.public_message


def test_save_environment_propagates_write_failure(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk 0xbadf00d offline")

    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target, writer=_explode),
    )

    with pytest.raises(WeChatConfigWriteFailed) as caught:
        service.save_environment(_config(tmp_path))

    assert "0xbadf00d" not in caught.value.public_message


def test_save_environment_does_not_invalidate_on_failure(
    tmp_path: Path,
) -> None:
    target = tmp_path / "wechat.json"

    class _CountingFactory:
        def __init__(self) -> None:
            self.invalidations = 0

        def invalidate(self) -> None:
            self.invalidations += 1

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise OSError("write refused")

    factory = _CountingFactory()
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target, writer=_explode),
        provider_factory=factory,
    )

    with pytest.raises(WeChatConfigWriteFailed):
        service.save_environment(_config(tmp_path))

    assert factory.invalidations == 0


# ------------------------------------------------------- boundary contracts


def test_setup_service_does_not_touch_database_modules() -> None:
    from qq_chat_analyzer.application.wechat import wechat_setup_service as module

    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "WeChatDatabaseProvider" not in source
    assert "wechat_db_adapter" not in source
    assert "import sqlite3" not in source


def test_loader_errors_remain_distinct(tmp_path: Path) -> None:
    missing = WeChatEnvironmentConfigLoader(tmp_path / "nope.json")
    with pytest.raises(WeChatConfigNotFound):
        missing.load()

    broken = tmp_path / "broken.json"
    broken.write_text("[]", encoding="utf-8")
    with pytest.raises(WeChatConfigCorrupted):
        WeChatEnvironmentConfigLoader(broken).load()


def test_save_environment_succeeds_when_key_acquisition_fails(
    tmp_path: Path,
) -> None:
    """Saving the data root must not depend on WeChat being at a login moment."""
    target = tmp_path / "wechat.json"
    key_service = _StubKeyService(
        error=WeChatKeyUnavailable(
            "\u83b7\u53d6\u5fae\u4fe1\u6570\u636e\u5e93\u5bc6\u94a5\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5\u3002"
        )
    )
    factory = _CountingFactory()
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        provider_factory=factory,
        key_service=key_service,
    )

    service.save_environment(
        WeChatEnvironmentConfig(data_root=tmp_path / "data")
    )

    stored = WeChatEnvironmentConfigLoader(target).load()
    assert stored.data_root == tmp_path / "data"
    assert stored.db_key is None
    assert factory.invalidations == 1


def test_save_environment_does_not_acquire_a_key(tmp_path: Path) -> None:
    """Key acquisition belongs to the connect flow, not to saving settings."""
    target = tmp_path / "wechat.json"
    key_service = _StubKeyService(key="d" * 64)
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        key_service=key_service,
    )

    service.save_environment(
        WeChatEnvironmentConfig(data_root=tmp_path / "data")
    )

    assert key_service.calls == 0


def test_save_environment_still_keeps_an_explicit_db_key(tmp_path: Path) -> None:
    """A key supplied by the connect flow is persisted untouched."""
    target = tmp_path / "wechat.json"
    supplied = "e" * 64
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        key_service=_StubKeyService(key="f" * 64),
    )

    service.save_environment(
        WeChatEnvironmentConfig(
            data_root=tmp_path / "data",
            db_key=supplied,
        )
    )

    assert WeChatEnvironmentConfigLoader(target).load().db_key == supplied


def test_acquire_db_key_is_available_for_the_connect_flow(tmp_path: Path) -> None:
    """The connect flow can still obtain and persist a key after saving."""
    target = tmp_path / "wechat.json"
    acquired = "a" * 64
    key_service = _StubKeyService(key=acquired)
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        key_service=key_service,
    )
    service.save_environment(
        WeChatEnvironmentConfig(data_root=tmp_path / "data")
    )
    assert WeChatEnvironmentConfigLoader(target).load().db_key is None

    service.acquire_db_key()

    assert key_service.calls == 1
    stored = WeChatEnvironmentConfigLoader(target).load()
    assert stored.db_key == acquired
    assert stored.data_root == tmp_path / "data"


def test_acquire_db_key_propagates_a_user_safe_error(tmp_path: Path) -> None:
    """A failed acquisition surfaces the key service's own safe message."""
    target = tmp_path / "wechat.json"
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        key_service=_StubKeyService(
            error=WeChatKeyUnavailable(
                "\u672a\u68c0\u6d4b\u5230\u5fae\u4fe1\u8fdb\u7a0b\uff0c\u8bf7\u5148\u767b\u5f55\u5fae\u4fe1\u3002"
            )
        ),
    )

    with pytest.raises(WeChatKeyUnavailable) as caught:
        service.acquire_db_key()

    assert caught.value.code == "wechat_key_unavailable"
    assert "Traceback" not in caught.value.public_message


def test_acquire_db_key_without_key_service_is_a_no_op(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
    )

    assert service.acquire_db_key() is None


def test_acquire_db_key_accepts_progress_callback(tmp_path: Path) -> None:
    """The progress callback must be passed through to the key service."""
    target = tmp_path / "wechat.json"
    seen = []
    key_service = _StubKeyService(key="e" * 64, progress_callback=seen.append)
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        key_service=key_service,
    )
    service.save_environment(WeChatEnvironmentConfig(data_root=tmp_path / "data"))

    service.acquire_db_key(progress=lambda msg: seen.append(msg))

    assert key_service.calls == 1
    assert len(seen) == 2
    assert seen[0] == "helper line 1"
    assert seen[1] == "helper line 2"


def test_disconnect_clears_key_but_keeps_environment(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"
    WeChatEnvironmentConfigWriter(target).save(_config(tmp_path))
    key_service = _StubKeyService(key="g" * 64)
    factory = _CountingFactory()
    sentinel = object()
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        provider_factory=factory,
        connection_service=_StubConnectionService(sentinel),
        key_service=key_service,
    )

    result = service.disconnect()

    stored = WeChatEnvironmentConfigLoader(target).load()
    assert result is sentinel
    assert stored.data_root == _config(tmp_path).data_root
    assert stored.db_key is None
    assert stored.wcdb_cli_path == _config(tmp_path).wcdb_cli_path
    assert stored.wcdb_dll_path == _config(tmp_path).wcdb_dll_path
    assert factory.invalidations == 1
    assert key_service.clear_calls == 1


def test_disconnect_without_config_is_a_noop(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"
    key_service = _StubKeyService()
    factory = _CountingFactory()
    service = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        provider_factory=factory,
        key_service=key_service,
    )

    service.disconnect()

    assert target.exists() is False
    assert factory.invalidations == 0
    assert key_service.clear_calls == 1


# ------------------------------------------------------------- verification


class _VerifyingProvider:
    """Stand in for the provider's key/database verification step."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def verify_readable(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


class _VerifyingFactory:
    def __init__(self, provider: object) -> None:
        self.provider = provider
        self.creates = 0
        self.invalidations = 0

    def create(self) -> object:
        self.creates += 1
        return self.provider

    def invalidate(self) -> None:
        self.invalidations += 1


def test_verify_connection_uses_the_provider_the_session_read_uses(
    tmp_path: Path,
) -> None:
    provider = _VerifyingProvider()
    factory = _VerifyingFactory(provider)
    service = _isolated_setup_service(tmp_path, provider_factory=factory)

    assert service.verify_connection() is None
    assert provider.calls == 1
    assert factory.creates == 1


def test_verify_connection_propagates_the_unreadable_error(
    tmp_path: Path,
) -> None:
    provider = _VerifyingProvider(DatabaseUnreadable())
    service = _isolated_setup_service(
        tmp_path,
        provider_factory=_VerifyingFactory(provider),
    )

    with pytest.raises(DatabaseUnreadable) as failure:
        service.verify_connection()

    assert failure.value.code == "wechat_database_unreadable"


def test_verify_connection_without_a_provider_factory_does_not_fail(
    tmp_path: Path,
) -> None:
    service = _isolated_setup_service(tmp_path)

    assert service.verify_connection() is None


def test_verify_connection_tolerates_a_provider_without_verification(
    tmp_path: Path,
) -> None:
    class _PlainProvider:
        def list_sessions(self):  # pragma: no cover - contract only
            return []

    service = _isolated_setup_service(
        tmp_path,
        provider_factory=_VerifyingFactory(_PlainProvider()),
    )

    assert service.verify_connection() is None


# ------------------------------------------- runtime pair (Portable to Setup)


def _config_module():
    return __import__(
        "qq_chat_analyzer.application.wechat.wechat_environment_config",
        fromlist=["default_wechat_wcdb_cli_path"],
    )


def _patch_bundled_wechat_runtime(
    monkeypatch: pytest.MonkeyPatch,
    bundle: Path,
) -> Path:
    """Point the bundled runtime at a fictional current Setup install."""
    module = _config_module()
    wechat = bundle / "runtime" / "wechat"
    wechat.mkdir(parents=True, exist_ok=True)
    (wechat / "wcdb_cli.exe").write_text("fake", encoding="utf-8")
    (wechat / "WCDB.dll").write_text("fake", encoding="utf-8")
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
    return wechat


def _half_valid_runtime(tmp_path: Path) -> tuple[Path, Path]:
    """Return a fictional older install whose DLL is already gone."""
    runtime = tmp_path / "Echo-0.1.0-portable" / "runtime" / "wechat"
    runtime.mkdir(parents=True)
    cli = runtime / "wcdb_cli.exe"
    cli.write_text("fake", encoding="utf-8")
    return cli, runtime / "WCDB.dll"


def _saved_config(
    tmp_path: Path,
    *,
    cli: Path,
    dll: Path,
    db_key: str | None,
) -> WeChatEnvironmentConfig:
    return WeChatEnvironmentConfig(
        data_root=tmp_path / "saved-root",
        db_key=db_key,
        wcdb_cli_path=cli,
        wcdb_dll_path=dll,
    )


def _write_saved_config(tmp_path: Path, config: WeChatEnvironmentConfig) -> Path:
    target = tmp_path / "wechat.json"
    WeChatEnvironmentConfigWriter(target).save(config)
    return target


def _setup_service(tmp_path: Path, target: Path, **overrides) -> WeChatSetupService:
    defaults = {
        "config_loader": WeChatEnvironmentConfigLoader(target),
        "config_writer": WeChatEnvironmentConfigWriter(target),
    }
    defaults.update(overrides)
    return WeChatSetupService(**defaults)


def test_save_environment_does_not_mix_a_surviving_path_with_the_bundled_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A surviving older path must never be completed from this install."""
    setup_wechat = _patch_bundled_wechat_runtime(monkeypatch, tmp_path / "Echo")
    cli, dll = _half_valid_runtime(tmp_path)
    target = _write_saved_config(
        tmp_path,
        _saved_config(tmp_path, cli=cli, dll=dll, db_key="a" * 64),
    )
    service = _setup_service(tmp_path, target)

    service.save_environment(
        WeChatEnvironmentConfig(data_root=tmp_path / "saved-root")
    )

    stored = WeChatEnvironmentConfigLoader(target).load()
    assert stored.wcdb_cli_path == cli
    assert stored.wcdb_dll_path == dll
    assert stored.wcdb_dll_path != setup_wechat / "WCDB.dll"
    assert stored.data_root == tmp_path / "saved-root"
    assert stored.db_key == "a" * 64


def test_disconnect_does_not_mix_a_surviving_path_with_the_bundled_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clearing the key must not blend two installations' runtime files."""
    setup_wechat = _patch_bundled_wechat_runtime(monkeypatch, tmp_path / "Echo")
    cli, dll = _half_valid_runtime(tmp_path)
    target = _write_saved_config(
        tmp_path,
        _saved_config(tmp_path, cli=cli, dll=dll, db_key="b" * 64),
    )
    service = _setup_service(tmp_path, target, key_service=_StubKeyService())

    service.disconnect()

    stored = WeChatEnvironmentConfigLoader(target).load()
    assert stored.wcdb_cli_path == cli
    assert stored.wcdb_dll_path == dll
    assert stored.wcdb_dll_path != setup_wechat / "WCDB.dll"
    assert stored.data_root == tmp_path / "saved-root"
    assert stored.db_key is None


def test_acquire_db_key_does_not_mix_a_surviving_path_with_the_bundled_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persisting an acquired key must not blend two installations' files."""
    setup_wechat = _patch_bundled_wechat_runtime(monkeypatch, tmp_path / "Echo")
    cli, dll = _half_valid_runtime(tmp_path)
    target = _write_saved_config(
        tmp_path,
        _saved_config(tmp_path, cli=cli, dll=dll, db_key=None),
    )
    service = _setup_service(
        tmp_path,
        target,
        key_service=_StubKeyService(key="c" * 64),
    )

    assert service.acquire_db_key() == "c" * 64

    stored = WeChatEnvironmentConfigLoader(target).load()
    assert stored.db_key == "c" * 64
    assert stored.wcdb_cli_path == cli
    assert stored.wcdb_dll_path == dll
    assert stored.wcdb_dll_path != setup_wechat / "WCDB.dll"


def test_save_environment_rebinds_an_entirely_stale_pair_to_the_bundled_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fully unusable pair still follows this install as one pair."""
    setup_wechat = _patch_bundled_wechat_runtime(monkeypatch, tmp_path / "Echo")
    stale = tmp_path / "Echo-0.1.0-portable" / "runtime" / "wechat"
    target = _write_saved_config(
        tmp_path,
        _saved_config(
            tmp_path,
            cli=stale / "wcdb_cli.exe",
            dll=stale / "WCDB.dll",
            db_key="d" * 64,
        ),
    )
    service = _setup_service(tmp_path, target)

    service.save_environment(
        WeChatEnvironmentConfig(data_root=tmp_path / "saved-root")
    )

    stored = WeChatEnvironmentConfigLoader(target).load()
    assert stored.wcdb_cli_path == setup_wechat / "wcdb_cli.exe"
    assert stored.wcdb_dll_path == setup_wechat / "WCDB.dll"
    assert stored.data_root == tmp_path / "saved-root"
    assert stored.db_key == "d" * 64
