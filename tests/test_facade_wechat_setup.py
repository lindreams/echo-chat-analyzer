"""Facade-level tests for the WeChat setup entry point.

Privacy: all configuration values here are fabricated.
"""

from __future__ import annotations

from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from qq_chat_analyzer.application.facade import (
    ChatAnalyzerFacade,
    ChatSource,
    FacadeError,
    SourceUnavailable,
)
from qq_chat_analyzer.application.wechat.wechat_environment_config import (
    WeChatConfigWriteFailed,
    WeChatEnvironmentConfig,
)
from qq_chat_analyzer.providers.wechat_database_provider import (
    DatabaseUnreadable,
)


class _StubSetupService:
    def __init__(
        self,
        *,
        status: object = None,
        error: Exception | None = None,
        detected_root: Path | None = None,
        detected_roots: list[Path] | None = None,
    ):
        self.status = status
        self.error = error
        self.detected_root = detected_root
        self.detected_roots = list(detected_roots or [])
        self.saved: list[WeChatEnvironmentConfig] = []
        self.checks = 0
        self.detects = 0
        self.detects_roots = 0

    def check_setup(self) -> object:
        self.checks += 1
        if self.error is not None:
            raise self.error
        return self.status

    def detect_wechat_data_root(self) -> Path | None:
        self.detects += 1
        if self.error is not None:
            raise self.error
        return self.detected_root

    def detect_wechat_data_roots(self) -> list[Path]:
        self.detects_roots += 1
        if self.error is not None:
            raise self.error
        return list(self.detected_roots)

    def save_environment(self, config: WeChatEnvironmentConfig) -> object:
        if self.error is not None:
            raise self.error
        self.saved.append(config)
        return self.status


def test_cancel_token_crosses_facade_setup_into_key_owner(tmp_path, monkeypatch):
    from qq_chat_analyzer.application.wechat.wechat_setup_service import WeChatSetupService
    from qq_chat_analyzer.application.wechat.wechat_key_service import WeChatKeyService
    from qq_chat_analyzer.application.wechat.wechat_environment_config import WeChatEnvironmentConfigLoader, WeChatEnvironmentConfigWriter
    owner = WeChatKeyService()
    setup = WeChatSetupService(key_service=owner,
        config_loader=WeChatEnvironmentConfigLoader(tmp_path / "fictional.json"),
        config_writer=WeChatEnvironmentConfigWriter(tmp_path / "fictional.json"))
    facade = ChatAnalyzerFacade(wechat_setup_service=setup)
    token = threading.Event()
    facade.cancel_wechat_connection(token)
    with pytest.raises(FacadeError) as error:
        facade.acquire_wechat_db_key(cancel_event=token)
    assert error.value.code == "wechat_key_cancelled"
    assert not (tmp_path / "fictional.json").exists()


@pytest.mark.parametrize("pause,cancel", [("load", True), ("save", True), ("load", False)])
def test_old_config_commit_cannot_overwrite_new_attempt(tmp_path, pause, cancel):
    from qq_chat_analyzer.application.wechat.wechat_setup_service import WeChatSetupService
    from qq_chat_analyzer.application.wechat.wechat_environment_config import (
        WeChatEnvironmentConfigLoader, WeChatEnvironmentConfigWriter,
    )
    target = tmp_path / "fictional-commit.json"
    loader, writer = WeChatEnvironmentConfigLoader(target), WeChatEnvironmentConfigWriter(target)
    writer.save(WeChatEnvironmentConfig(db_key="initial-fictional"))
    paused, resume, new_acquired, new_done = (threading.Event() for _ in range(4))
    old_token, new_token = threading.Event(), threading.Event()
    writes, invalidations, outcomes = [], [], {}

    def block():
        paused.set()
        assert resume.wait(5)

    class Loader:
        def load(self):
            config = loader.load()
            if pause == "load" and threading.current_thread().name == "old-commit":
                block()
            return config

    class Writer:
        def save(self, config):
            if pause == "save" and config.db_key == "old-fictional":
                block()
            writer.save(config)
            writes.append(config.db_key)

    class Keys:
        def acquire(self, *, progress=None, cancel_event=None):
            if cancel_event is new_token:
                new_acquired.set()
                return "new-fictional"
            return "old-fictional"

    def invalidate():
        invalidations.append(loader.load().db_key)

    facade = ChatAnalyzerFacade(wechat_setup_service=WeChatSetupService(
        config_loader=Loader(), config_writer=Writer(), key_service=Keys(),
        provider_factory=SimpleNamespace(invalidate=invalidate)))

    def connect(name, token):
        try:
            outcomes[name] = facade.acquire_wechat_db_key(cancel_event=token)
        except FacadeError as error:
            outcomes[name] = error.code
        finally:
            if name == "new":
                new_done.set()

    old = threading.Thread(target=connect, args=("old", old_token), name="old-commit")
    new = threading.Thread(target=connect, args=("new", new_token), name="new-commit")
    try:
        old.start()
        assert paused.wait(5)
        if cancel:
            facade.cancel_wechat_connection(old_token)  # Returns while IO is blocked.
        new.start()
        assert new_acquired.wait(5)
        if pause == "load":
            assert new_done.wait(5)  # A stale read need not delay the new commit.
        else:
            # An in-flight write must serialize before the new commit.
            new_done.wait(0.1)
        resume.set()
        old.join(5)
        new.join(5)
        assert not old.is_alive() and not new.is_alive()
        assert loader.load().db_key == "new-fictional"
        assert outcomes == {"old": "wechat_key_cancelled", "new": "new-fictional"}
        assert invalidations == writes  # Every successful write invalidates before the next.
        assert writes == (["old-fictional", "new-fictional"] if pause == "save" else ["new-fictional"])
    finally:
        resume.set()
        old.join(5)
        if new.ident is not None:
            new.join(5)


@pytest.mark.parametrize("status", ["failed", "timed_out", "unknown"])
def test_wechat_close_result_propagates_without_building_sources(status):
    from qq_chat_analyzer.application.shutdown_models import ShutdownStatus
    calls = []
    class Setup:
        def shutdown(self):
            calls.append("close")
            return ShutdownStatus(status)
    facade = ChatAnalyzerFacade(wechat_setup_service=Setup(),
        source_builders={ChatSource.QQ: lambda: pytest.fail("must not build during close")})
    result = facade.shutdown()
    assert next(step.status.value for step in result.steps if step.name == "source_lifecycle") == status
    assert not result.can_apply_update
    assert facade.shutdown() is result and calls == ["close"]


def test_wechat_builder_returning_after_close_is_closed_not_published():
    from qq_chat_analyzer.application.shutdown_models import ShutdownStatus
    entered, release = threading.Event(), threading.Event()
    closed, errors = [], []
    class Setup:
        def shutdown(self):
            closed.append(1)
            return ShutdownStatus.UNKNOWN
    def build():
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(setup=Setup())
    facade = ChatAnalyzerFacade(source_builders={ChatSource.WECHAT: build})
    def start():
        try:
            facade.acquire_wechat_db_key()
        except FacadeError as error:
            errors.append(error.code)
    worker = threading.Thread(target=start)
    worker.start()
    try:
        assert entered.wait(5)
        assert not facade.shutdown().can_apply_update
        release.set()
        worker.join(5)
        assert not worker.is_alive()
        assert errors == ["application_closing"]
        assert closed == [1] and ChatSource.WECHAT not in facade._built_sources
    finally:
        release.set()
        worker.join(5)


def test_wechat_publication_and_shutdown_snapshot_share_boundary():
    from qq_chat_analyzer.application.shutdown_models import ShutdownStatus
    publishing, release, finished = threading.Event(), threading.Event(), threading.Event()
    closed, outcomes = [], []
    class Setup:
        def acquire_db_key(self, progress=None):
            return "ab12" * 16
        def shutdown(self):
            closed.append(1)
            return ShutdownStatus.UNKNOWN
    class PausedPublication(dict):
        def __setitem__(self, source, bundle):
            publishing.set()
            assert release.wait(5)
            super().__setitem__(source, bundle)
    facade = ChatAnalyzerFacade(source_builders={ChatSource.WECHAT: lambda: SimpleNamespace(setup=Setup())})
    facade._built_sources = PausedPublication()
    def connect():
        try:
            outcomes.append(facade.acquire_wechat_db_key())
        except FacadeError as error:
            outcomes.append(error.code)
    def close():
        outcomes.append(facade.shutdown())
        finished.set()
    worker, closer = threading.Thread(target=connect), threading.Thread(target=close)
    worker.start()
    try:
        assert publishing.wait(5)
        closer.start()
        finished.wait(0.1)  # Old code closes before the paused publication.
        release.set()
        worker.join(5)
        closer.join(5)
        assert not worker.is_alive() and not closer.is_alive()
        assert closed == [1]
        assert not facade.shutdown().can_apply_update
    finally:
        release.set()
        worker.join(5)
        if closer.ident is not None:
            closer.join(5)


def _isolate_wechat_config(monkeypatch, tmp_path: Path) -> None:
    """Keep composition-root setup config under the test temp directory."""
    from qq_chat_analyzer.application.wechat import wechat_environment_config

    monkeypatch.setattr(
        wechat_environment_config,
        "user_data_dir",
        lambda: tmp_path / "user-data",
    )


def test_composition_root_wires_setup_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from qq_chat_analyzer.gui import app as gui_app

    _isolate_wechat_config(monkeypatch, tmp_path)
    facade = gui_app.build_facade()

    status = facade.get_wechat_setup_status()
    assert hasattr(status, "state")
    assert hasattr(status, "message")


def test_composition_root_shares_factory_with_setup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from qq_chat_analyzer.gui import app as gui_app

    _isolate_wechat_config(monkeypatch, tmp_path)
    facade = gui_app.build_facade()

    setup = facade._wechat_setup_service
    connection = facade._wechat_connection_service
    assert setup._provider_factory is connection._shared_factory


def test_composition_root_injects_lazy_report_package_catalog_manager(
    monkeypatch,
) -> None:
    from qq_chat_analyzer.application import report_package_catalog
    from qq_chat_analyzer.gui import app as gui_app

    def fail_if_storage_is_resolved_during_startup():
        raise AssertionError("history storage resolved during startup")

    monkeypatch.setattr(
        report_package_catalog,
        "user_data_dir",
        fail_if_storage_is_resolved_during_startup,
    )

    facade = gui_app.build_facade()

    assert isinstance(
        facade._report_package_catalog,
        report_package_catalog.ReportPackageCatalog,
    )


class _VerifyingSetupService(_StubSetupService):
    """Record verification calls and optionally fail like a wrong key."""

    def __init__(self, *, error: Exception | None = None, **kwargs):
        super().__init__(**kwargs)
        self.verify_error = error
        self.verifies = 0

    def verify_connection(self) -> None:
        self.verifies += 1
        if self.verify_error is not None:
            raise self.verify_error


def test_facade_translates_an_unreadable_wechat_database() -> None:
    setup = _VerifyingSetupService(error=DatabaseUnreadable())
    facade = ChatAnalyzerFacade(wechat_setup_service=setup)

    with pytest.raises(FacadeError) as failure:
        facade.verify_wechat_database()

    assert failure.value.code == "wechat_database_unreadable"
    assert failure.value.source is ChatSource.WECHAT
    assert DatabaseUnreadable.public_message in failure.value.public_message
