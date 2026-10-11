"""QQ build gate against fictional installations; never launch a real client."""

from __future__ import annotations

import threading
import json
from dataclasses import replace

import pytest

from test_qq_auth_bridge import (
    _FakeProcess, _StubConnectionService, _StubSetupService, _bridge,
    _bridge_module, _connection_module, _launch_target, _runtime_config,
    _runtime_status, _status,
)


@pytest.fixture(autouse=True)
def fictional_processes(monkeypatch):
    monkeypatch.setattr(_bridge_module(), "find_conflicting_qq_pids", lambda _: [])


def _auth(tmp_path):
    config = _runtime_config(tmp_path)
    return _bridge(
        setup_service=_StubSetupService(config=config, runtime_status=_runtime_status()),
        connection_service=_StubConnectionService(_status(available=False)),
    ), config


def _base_build(config, build):
    (config.qq_install_path.parent / "resources/app/package.json").write_text(json.dumps({
        "version": f"9.9.15-{build}", "buildVersion": str(build), "main": "index.js",
    }), encoding="utf-8")


@pytest.mark.parametrize("build,blocked", [(27597, True), (40767, True), (40768, False), (53644, False)])
def test_build_gate_precedes_any_runtime_launch(tmp_path, monkeypatch, caplog, build, blocked):
    module = _bridge_module()
    instance, config = _auth(tmp_path)
    _base_build(config, build)
    launched = []
    read = []

    original_read = module.read_qq_resources

    def version(path):
        read.append(path)
        return original_read(path)

    monkeypatch.setattr(module, "read_qq_resources", version)
    monkeypatch.setattr(module, "read_qq_version", lambda _: (9, 9, 36, 53644))
    monkeypatch.setattr(*_launch_target(module), lambda *a, **k: launched.append(a) or _FakeProcess(4243))
    with caplog.at_level("DEBUG", logger="qq_chat_analyzer.desktop.qq_auth_bridge"):
        snapshot = instance.start_auth_flow()

    assert read and set(read) == {config.qq_install_path.resolve()}
    if blocked:
        assert snapshot.state is _connection_module().ConnectionState.ERROR
        assert snapshot.code == "qq_version_too_old"
        assert "QQ 版本过旧" in snapshot.message
        assert f"9.9.15-{build}" in snapshot.message
        assert "更新 QQ" in snapshot.message
        assert not launched
        assert instance._setup_service.start_runtime_calls == 0
        assert not (tmp_path / "loadNapCat.js").exists()
        assert not instance._auth_launch_started
    else:
        assert snapshot.state is _connection_module().ConnectionState.WAITING_AUTH
        assert len(launched) == 1
    assert str(tmp_path) not in snapshot.message + snapshot.action_hint + caplog.text
    assert "ECHO_BRIDGE_TOKEN" not in caplog.text


@pytest.mark.parametrize("version", [None, "9.9.15-27597 private-account", (9, 9, 15, 0)])
def test_unknown_or_malformed_version_does_not_claim_incompatibility(tmp_path, monkeypatch, version):
    module = _bridge_module()
    instance, _ = _auth(tmp_path)
    monkeypatch.setattr(module, "read_qq_version", lambda _: version, raising=False)
    monkeypatch.setattr(*_launch_target(module), lambda *a, **k: _FakeProcess(4243))
    snapshot = instance.start_auth_flow()
    assert snapshot.state is _connection_module().ConnectionState.WAITING_AUTH
    assert snapshot.code != "qq_version_too_old"
    assert "兼容" not in snapshot.message
    assert "private-account" not in snapshot.message


def test_version_read_exception_is_unknown_without_private_logging(tmp_path, monkeypatch, caplog):
    module = _bridge_module()
    instance, _ = _auth(tmp_path)

    def fail(_):
        raise OSError(f"{tmp_path} fictional-account fictional-token fictional-chat")

    monkeypatch.setattr(module, "read_qq_version", fail, raising=False)
    monkeypatch.setattr(*_launch_target(module), lambda *a, **k: _FakeProcess(4243))
    with caplog.at_level("DEBUG"):
        snapshot = instance.start_auth_flow()
    assert snapshot.state is _connection_module().ConnectionState.WAITING_AUTH
    assert str(tmp_path) not in caplog.text
    for secret in ("fictional-account", "fictional-token", "fictional-chat"):
        assert secret not in caplog.text + snapshot.message


def test_gate_uses_same_resolved_install_as_launch_not_echo_version(tmp_path, monkeypatch):
    module = _bridge_module()
    config = _runtime_config(tmp_path)
    saved = tmp_path / "other/QQ.exe"
    saved.parent.mkdir()
    saved.write_bytes(b"fictional other installation")
    (tmp_path / "config/qq_path.txt").write_text(str(saved), encoding="utf-8")
    config = replace(config, version="9.9.15-27597")
    seen = []
    launched = []
    original_read = module.read_qq_resources
    monkeypatch.setattr(module, "read_qq_resources", lambda p: seen.append(p) or original_read(p))
    monkeypatch.setattr(*_launch_target(module), lambda a, **k: launched.append(a) or _FakeProcess(4243))
    module.default_auth_window_launcher(config)()
    assert seen and set(seen) == {config.qq_install_path.resolve()}
    assert launched[0][1] == str(seen[0])


@pytest.mark.parametrize("first_build", [27597, 53644])
def test_cancel_during_version_read_never_launches_and_retry_rechecks(tmp_path, monkeypatch, first_build):
    module = _bridge_module()
    instance, config = _auth(tmp_path)
    _base_build(config, first_build)
    cancelled = threading.Event()
    reads = []
    launches = []

    original_read = module.read_qq_resources

    def read(path):
        reads.append(True)
        if len(reads) == 1:
            cancelled.set()
        return original_read(path)

    monkeypatch.setattr(module, "read_qq_resources", read)
    monkeypatch.setattr(*_launch_target(module), lambda *a, **k: launches.append(True) or _FakeProcess(4243))
    first = instance.start_auth_flow(cancel_event=cancelled)
    assert first.code == "qq_auth_cancelled"
    assert not launches
    _base_build(config, 53644)
    second = instance.start_auth_flow(cancel_event=threading.Event())
    assert second.state is _connection_module().ConnectionState.WAITING_AUTH
    assert len(reads) >= 2
    assert launches == [True]


def test_old_version_rejection_can_retry_after_update(tmp_path, monkeypatch):
    module = _bridge_module()
    instance, config = _auth(tmp_path)
    _base_build(config, 27597)
    launches = []
    monkeypatch.setattr(*_launch_target(module), lambda *a, **k: launches.append(True) or _FakeProcess(4243))
    assert instance.start_auth_flow().code == "qq_version_too_old"
    assert not launches
    _base_build(config, 53644)
    assert instance.start_auth_flow().state is _connection_module().ConnectionState.WAITING_AUTH
    assert launches == [True]


def test_process_detection_failure_remains_fail_closed_not_version_failure(tmp_path, monkeypatch, caplog):
    module = _bridge_module()
    instance, config = _auth(tmp_path)
    _base_build(config, 27597)

    def fail(_):
        raise OSError(f"{tmp_path} fictional-token")

    monkeypatch.setattr(module, "find_conflicting_qq_pids", fail)
    monkeypatch.setattr(module, "read_qq_version", lambda _: pytest.fail("must not reach version check"), raising=False)
    monkeypatch.setattr(module, "read_qq_resources", lambda _: pytest.fail("must not reach resource check"))
    monkeypatch.setattr(*_launch_target(module), lambda *a, **k: pytest.fail("must not launch"))
    with caplog.at_level("DEBUG"):
        snapshot = instance.start_auth_flow()
    assert snapshot.code == "qq_process_detection_failed"
    assert "版本" not in snapshot.message
    assert "fictional-token" not in caplog.text
    assert str(tmp_path) not in caplog.text


def test_windows_resource_rejects_old_qq_before_bootstrap_or_credential(tmp_path, monkeypatch):
    from test_qq_version import _module, _VersionApi

    module = _bridge_module()
    reader = _module()
    instance, config = _auth(tmp_path)
    _base_build(config, 27597)
    monkeypatch.setattr(reader.sys, "platform", "win32")
    monkeypatch.setattr(reader.ctypes, "WinDLL", lambda *a, **k: _VersionApi(), raising=False)
    assert reader.read_qq_version(config.qq_install_path) == (9, 9, 15, 27597)
    monkeypatch.setattr(*_launch_target(module), lambda *a, **k: pytest.fail("old QQ must not launch"))
    monkeypatch.setattr(instance._credential_source, "begin_launch", lambda: pytest.fail("must not mint credential"))
    assert instance.start_auth_flow().code == "qq_version_too_old"
    assert not (tmp_path / "qqnt.echo.json").exists()
    assert not (tmp_path / "loadNapCat.js").exists()
