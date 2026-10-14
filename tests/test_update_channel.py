"""Production update channel wiring (no network, no SDK, no Qt).

These tests pin the fixed production identity/source, prove composition is
inert, prove foreign Setup identities are rejected, and prove the install
handoff is safe-disabled while the Velopack wait-failure risk is unapproved.
No real feed, installer or chat data is used.
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

from qq_chat_analyzer.application import update_channel
from qq_chat_analyzer.application.installable_update_service import (
    InstallableUpdateResult,
    InstallHandoffResult,
)

PRODUCTION_SOURCE = "https://github.com/lindreams/echo-chat-analyzer"


def test_production_identity_and_source_are_fixed():
    feed = update_channel.production_feed()
    assert feed.source == PRODUCTION_SOURCE
    assert feed.package_id == "Lindreams.Echo"
    assert feed.channel == "win-x64-stable"


def test_production_source_is_not_derived_from_the_environment(monkeypatch):
    monkeypatch.setenv("ECHO_UPDATE_SOURCE", "https://example.invalid/attacker")
    monkeypatch.setenv("ECHO_UPDATE_PACKAGE_ID", "Attacker.Package")
    monkeypatch.setenv("ECHO_UPDATE_CHANNEL", "attacker-channel")
    feed = update_channel.production_feed()
    assert (feed.source, feed.package_id, feed.channel) == (
        PRODUCTION_SOURCE,
        "Lindreams.Echo",
        "win-x64-stable",
    )


def test_module_is_qt_free():
    source = pathlib.Path(update_channel.__file__).read_text(encoding="utf-8")
    assert "PySide6" not in source
    assert "PyQt" not in source


def test_install_handoff_is_not_approved_by_default():
    assert update_channel.PRODUCTION_INSTALL_HANDOFF_APPROVED is False


class _FakeInner:
    """Stand-in core that would happily hand off a fictional install."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def check(self) -> InstallableUpdateResult:
        self.calls.append("check")
        return InstallableUpdateResult("available", "0.2.0", "9.9.9")

    def download(self, *, progress=None) -> InstallableUpdateResult:
        self.calls.append("download")
        return InstallableUpdateResult("downloaded", "0.2.0", "9.9.9", progress=100)

    def get_status(self) -> InstallableUpdateResult:
        return InstallableUpdateResult("idle")

    def prepare_install(self) -> InstallHandoffResult:
        self.calls.append("prepare")
        return InstallHandoffResult("ready", "9.9.9", "fictional-token")

    def handoff(self, token, shutdown) -> InstallHandoffResult:
        self.calls.append("handoff")
        return InstallHandoffResult("started", "9.9.9")


def test_gate_forwards_inspection_and_denies_install_handoff():
    inner = _FakeInner()
    gate = update_channel.guard_install_handoff(inner, approved=False)
    assert gate.get_status().status == "idle"
    assert gate.check().status == "available"
    assert gate.download(progress=lambda _percent: None).status == "downloaded"
    assert inner.calls == ["check", "download"]

    denied = gate.prepare_install()
    assert denied.status == "denied"
    assert denied.token is None
    assert gate.handoff("fictional-token", object()).status == "denied"
    # The unapproved gate never reaches the core's install handoff.
    assert inner.calls == ["check", "download"]


def test_approved_gate_forwards_the_install_handoff():
    inner = _FakeInner()
    gate = update_channel.guard_install_handoff(inner, approved=True)
    assert gate.prepare_install().status == "ready"
    assert gate.handoff("fictional-token", object()).status == "started"
    assert inner.calls == ["prepare", "handoff"]


def test_production_service_is_a_guarded_configured_service():
    built = update_channel.production_update_service()
    assert isinstance(built, update_channel.InstallHandoffGate)
    assert built.install_handoff_approved is False
    # A configured feed reports idle before any worker runs.
    assert built.get_status().status == "idle"


def test_application_construction_is_offline_and_sdk_free(monkeypatch):
    import velopack

    from qq_chat_analyzer.gui import app as gui_app

    def forbidden(*_args, **_kwargs):
        raise AssertionError("SDK must not be constructed during composition")

    monkeypatch.setattr(velopack, "UpdateManager", forbidden)
    facade = gui_app.build_facade()
    assert facade.get_update_status().status == "idle"


def test_composition_root_injects_the_guarded_production_service(monkeypatch):
    from qq_chat_analyzer.gui import app as gui_app

    captured = {}
    original = update_channel.guard_install_handoff

    def spy(service, **kwargs):
        gate = original(service, **kwargs)
        captured["service"] = service
        captured["gate"] = gate
        return gate

    monkeypatch.setattr(update_channel, "guard_install_handoff", spy)
    facade = gui_app.build_facade()
    assert captured["service"]._feed == update_channel.production_feed()
    assert captured["gate"].install_handoff_approved is False
    assert facade._installable_update_service is captured["gate"]


class _FakeManager:
    def __init__(self, *, app_id: str, version: str = "0.2.0", portable: bool = False) -> None:
        self._app_id = app_id
        self._version = version
        self._portable = portable
        self.queries = 0

    def get_is_portable(self) -> bool:
        return self._portable

    def get_app_id(self) -> str:
        return self._app_id

    def get_current_version(self) -> str:
        return self._version

    def get_update_pending_restart(self):
        return None

    def check_for_updates(self):
        self.queries += 1
        return None


def _channel_service(manager: _FakeManager):
    from qq_chat_analyzer.application.installable_update_service import (
        InstallableUpdateService,
    )

    return update_channel.guard_install_handoff(
        InstallableUpdateService(
            feed=update_channel.production_feed(),
            manager_factory=lambda _feed: manager,
            setup_runtime=lambda: True,
        ),
        approved=False,
    )


@pytest.mark.parametrize(
    "app_id", ["EchoA1.Fictional", "Lindreams.Echo.Extra", "lindreams.echo"]
)
def test_foreign_setup_identity_is_rejected_without_querying_the_feed(app_id):
    manager = _FakeManager(app_id=app_id)
    result = _channel_service(manager).check()
    assert result.status == "unsupported"
    assert manager.queries == 0


def test_matching_setup_identity_is_accepted_without_network():
    manager = _FakeManager(app_id="Lindreams.Echo")
    result = _channel_service(manager).check()
    assert result.status == "no_update"
    assert manager.queries == 1


def test_portable_installation_is_not_treated_as_a_setup():
    manager = _FakeManager(app_id="Lindreams.Echo", portable=True)
    result = _channel_service(manager).check()
    assert result.status == "unsupported"
    assert manager.queries == 0


def test_composition_root_cannot_start_unapproved_auto_install(monkeypatch):
    import velopack

    from qq_chat_analyzer.gui import app as gui_app

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unapproved install must not reach the SDK")

    monkeypatch.setattr(velopack, "UpdateManager", forbidden)
    facade = gui_app.build_facade()
    result = facade.prepare_update_install()
    assert result.status == "denied"
    assert result.token is None


def test_source_or_portable_keeps_the_release_page_fallback(monkeypatch):
    from qq_chat_analyzer.application import facade as facade_module
    from qq_chat_analyzer.application.update_check_service import UpdateCheckResult
    from qq_chat_analyzer.gui import app as gui_app

    stub_result = UpdateCheckResult(
        "update_available",
        "0.2.0",
        latest_version="0.3.0",
        release_url="https://github.com/lindreams/echo-chat-analyzer/releases/tag/v0.3.0",
    )

    class _StubChecker:
        def check(self, *, manual: bool = False):
            return stub_result

    monkeypatch.setattr(facade_module, "UpdateCheckService", lambda *a, **k: _StubChecker())
    facade = gui_app.build_facade()
    # A non-Setup (source/portable) environment is unsupported by the feed...
    assert facade.check_installable_update().status == "unsupported"
    # ...so the existing formal release-page path stays available.
    assert facade.check_for_updates(manual=True) is stub_result


def test_downloaded_result_still_requires_the_approved_gate():
    """Even a fully staged core cannot hand off while the gate is closed."""
    inner = _FakeInner()
    gate = update_channel.guard_install_handoff(inner, approved=False)
    assert gate.check().status == "available"
    assert gate.download().status == "downloaded"
    assert str(gate.prepare_install().status) == "denied"
    assert inner.calls == ["check", "download"]
