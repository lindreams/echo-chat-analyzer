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


def _isolated_setup_service(tmp_path: Path, **overrides) -> WeChatSetupService:
    """Build a setup service whose persisted config lives under tmp_path."""
    target = tmp_path / "config" / "wechat.json"
    defaults = {
        "config_loader": WeChatEnvironmentConfigLoader(target),
        "config_writer": WeChatEnvironmentConfigWriter(target),
    }
    defaults.update(overrides)
    return WeChatSetupService(**defaults)


def test_media_authority_survives_same_root_save_and_is_cleared_on_account_switch(tmp_path):
    from dataclasses import replace
    path = tmp_path / "config.json"
    original = replace(_config(tmp_path), sticker_media_roots=(tmp_path / "originals",))
    writer = WeChatEnvironmentConfigWriter(path)
    loader = WeChatEnvironmentConfigLoader(path)
    writer.save(original)
    service = WeChatSetupService(config_loader=loader, config_writer=writer)
    service.save_environment(WeChatEnvironmentConfig(data_root=original.data_root))
    assert loader.load().sticker_media_roots == original.sticker_media_roots
    service.save_environment(WeChatEnvironmentConfig(data_root=tmp_path / "different-account"))
    assert loader.load().sticker_media_roots == ()


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


def test_writer_round_trips_through_loader(tmp_path: Path) -> None:
    target = tmp_path / "wechat.json"
    original = _config(tmp_path)

    WeChatEnvironmentConfigWriter(target).save(original)
    restored = WeChatEnvironmentConfigLoader(target).load()

    assert restored == original


# ------------------------------------------------------------- check_setup


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


# ------------------------------------------------------ detect_data_root


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


# --------------------------------------------------------- save_environment


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
