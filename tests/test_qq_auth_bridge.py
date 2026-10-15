"""Behavior tests for the QQ authorization bridge.

Everything here is fictional. No real QQ process, launcher, or login window
is started; runtime launch is stubbed and the default window launcher is
exercised against temp files with the platform launcher mocked.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _launch_target(module):
    return (module, "launch_owned_process") if module.os.name == "nt" else (module.subprocess, "Popen")


def _bridge_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_auth_bridge"
    )


@pytest.fixture(autouse=True)
def fictional_processes_only(monkeypatch):
    # Never inspect the developer's real QQ clients during auth tests.
    monkeypatch.setattr(_bridge_module(), "find_conflicting_qq_pids", lambda owned: [], raising=False)


def _connection_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_connection_manager"
    )


def _config_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_environment_config"
    )


def _status(
    *,
    available=False,
    runtime_running=False,
    qq_online=False,
    version=None,
    message="",
    action_hint="",
):
    module = importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_connection_service"
    )
    return module.QQConnectionStatus(
        available=available,
        runtime_running=runtime_running,
        qq_online=qq_online,
        version=version,
        message=message,
        action_hint=action_hint,
    )


class _StubConnectionService:
    def __init__(self, status=None, queue=()):
        self._status = status
        self._queue = list(queue)
        self.check_calls = 0

    def check_status(self):
        self.check_calls += 1
        if self._queue:
            return self._queue.pop(0)
        return self._status


class _StubSetupService:
    def __init__(
        self,
        connect_status=None,
        error=None,
        runtime_status=None,
        config=None,
        config_missing=False,
    ):
        self._connect_status = connect_status
        self._error = error
        self._runtime_status = runtime_status
        self._config = config
        self._config_missing = config_missing
        self.connect_calls = 0
        self.config_calls = 0
        self.save_calls = 0
        self.start_runtime_calls = 0

    def connect(self):
        self.connect_calls += 1
        if self._error is not None:
            raise self._error
        return self._connect_status

    def save_environment(self, config):
        self.save_calls += 1
        if self._error is not None:
            raise self._error
        self._config = config
        self._config_missing = False
        return self._connect_status

    def get_environment_config(self):
        self.config_calls += 1
        if self._error is not None:
            raise self._error
        if self._config_missing:
            raise _config_module().QQConfigNotFound()
        return self._config

    def get_runtime_status(self):
        return self._runtime_status

    def start_runtime(self):
        self.start_runtime_calls += 1
        raise AssertionError("auth flow must reuse the manager connect path")


def _runtime_status(state: str = "running"):
    runtime = importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_runtime_manager"
    )
    return runtime.QQRuntimeStatus(
        state=runtime.QQRuntimeState(state),
        available=True,
        message="ok",
    )


def _bridge(
    *,
    setup_service=None,
    connection_service=None,
    manager=None,
    window_launcher=None,
    process_registry=None,
    qrcode_path=None,
    runtime_cleaner=None,
):
    if process_registry is None:
        registry_module = importlib.import_module(
            "qq_chat_analyzer.application.qq.qq_process_registry"
        )
        process_registry = registry_module.QQProcessRegistry(terminator=lambda _pid: True)
    return _bridge_module().QQAuthBridge(
        setup_service=setup_service,
        connection_service=connection_service,
        manager=manager,
        window_launcher=window_launcher,
        process_registry=process_registry,
        qrcode_path=qrcode_path,
        runtime_cleaner=runtime_cleaner,
    )


class _RecordingLauncher:
    def __init__(self, error=None):
        self.calls = 0
        self._error = error

    def __call__(self):
        self.calls += 1
        if self._error is not None:
            raise self._error


def _process_wait_bridge(monkeypatch, samples, **kwargs):
    launcher = _RecordingLauncher()
    sequence = iter(samples)
    observed = []

    def find(owned):
        sample = next(sequence)
        observed.append(sample)
        assert launcher.calls == 0
        if isinstance(sample, Exception):
            raise sample
        return sample

    monkeypatch.setattr(_bridge_module(), "find_conflicting_qq_pids", find)
    bridge = _bridge_module().QQAuthBridge(
        setup_service=_StubSetupService(),
        connection_service=_StubConnectionService(_status()),
        window_launcher=launcher,
        process_registry=importlib.import_module(
            "qq_chat_analyzer.application.qq.qq_process_registry"
        ).QQProcessRegistry(terminator=lambda _pid: True),
        **kwargs,
    )
    return bridge, launcher, observed


@pytest.mark.parametrize("samples", [[[]], [[101, 102], [102], []]])
def test_auth_waits_for_every_conflict_then_automatically_launches(monkeypatch, samples):
    bridge, launcher, observed = _process_wait_bridge(monkeypatch, samples, process_poll_interval=0)
    progress = []
    result = bridge.start_auth_flow(progress=progress.append)
    assert observed == samples
    assert launcher.calls == 1
    assert result.state is _connection_module().ConnectionState.WAITING_AUTH
    if samples[0]:
        assert "请完全退出 QQ" in progress
        assert progress.index("请完全退出 QQ") < progress.index(_bridge_module().PROGRESS_STARTING)
    else:
        assert "请完全退出 QQ" not in progress


def test_process_detection_failure_does_not_launch(monkeypatch):
    bridge, launcher, _ = _process_wait_bridge(monkeypatch, [OSError("fictional detection failure")])
    result = bridge.start_auth_flow()
    assert result.code == "qq_process_detection_failed"
    assert result.state is _connection_module().ConnectionState.ERROR
    assert launcher.calls == 0


@pytest.mark.parametrize("error_type", [OSError, ValueError])
def test_detection_diagnostics_never_log_exception_details(monkeypatch, caplog, error_type):
    error = error_type("RAW_EXCEPTION_SENTINEL Z:/private/fictional account=fictional credential=fictional")
    # Untrusted exception attributes must not become diagnostic fields either.
    error.stage = "UNSAFE_STAGE_SENTINEL"
    bridge, launcher, _ = _process_wait_bridge(monkeypatch, [error])
    with caplog.at_level("INFO", logger=_bridge_module()._LOGGER.name):
        result = bridge.start_auth_flow()
    records = [record for record in caplog.records if "process detection" in record.getMessage()]
    assert result.code == "qq_process_detection_failed" and launcher.calls == 0
    assert len(records) == 1
    message = records[0].getMessage()
    assert "stage=enumeration" in message and "category=unexpected_failure" in message
    assert "elapsed_ms=" in message
    assert records[0].exc_info is None
    assert "SENTINEL" not in caplog.text
    assert "Z:/private" not in caplog.text
    assert "account=" not in caplog.text and "credential=" not in caplog.text


def test_cancel_during_process_detection_prevents_late_launch(monkeypatch):
    cancelled = threading.Event()
    bridge, launcher, _ = _process_wait_bridge(monkeypatch, [])
    def detect(owned):
        cancelled.set()
        return []
    monkeypatch.setattr(_bridge_module(), "find_conflicting_qq_pids", detect)
    result = bridge.start_auth_flow(cancel_event=cancelled)
    assert result.code == "qq_auth_cancelled"
    assert launcher.calls == 0
    assert bridge.is_qrcode_ready() is False


def test_stale_owned_runtime_cleanup_precedes_conflict_detection(monkeypatch, tmp_path):
    events = []
    registry_module = importlib.import_module("qq_chat_analyzer.application.qq.qq_process_registry")
    registry = registry_module.QQProcessRegistry(terminator=lambda pid: events.append(("owned", pid)))
    registry.record(201)
    def detect(owned):
        events.append(("detect", owned))
        return []
    monkeypatch.setattr(_bridge_module(), "find_conflicting_qq_pids", detect)
    bridge = _bridge(setup_service=_StubSetupService(config=type("Config", (), {"runtime_directory": tmp_path})()),
                     connection_service=_StubConnectionService(_status()),
                     process_registry=registry,
                     runtime_cleaner=lambda directory: events.append(("runtime", directory)),
                     window_launcher=lambda: events.append(("launch", None)))
    bridge.start_auth_flow()
    assert [event[0] for event in events] == ["owned", "runtime", "detect", "launch"]


def test_cancel_while_resolving_launcher_never_spawns_qq(monkeypatch, tmp_path):
    cancelled = threading.Event()
    launches = []
    def resolve(config, **_kwargs):
        cancelled.set()
        return lambda: launches.append("spawn")
    monkeypatch.setattr(_bridge_module(), "default_auth_window_launcher", resolve)
    bridge = _bridge(setup_service=_StubSetupService(config=_runtime_config(tmp_path)),
                     connection_service=_StubConnectionService(_status()))
    result = bridge.start_auth_flow(cancel_event=cancelled)
    assert result.code == "qq_auth_cancelled"
    assert launches == []
    assert bridge.is_qrcode_ready() is False


def test_old_cancel_cleanup_cannot_stop_new_auth_attempt(monkeypatch):
    bridge, launcher, _ = _process_wait_bridge(monkeypatch, [[]])
    old = threading.Event()
    old.set()
    bridge.start_auth_flow(cancel_event=old)
    current = threading.Event()
    bridge.start_auth_flow(cancel_event=current)
    bridge.cancel_auth_flow(old)
    # Reuse the current launcher; late cleanup must not clear its guard.
    bridge.start_auth_flow(cancel_event=current)
    assert launcher.calls == 1


def test_cancel_cleanup_after_worker_result_stops_only_its_owned_runtime(monkeypatch):
    bridge, launcher, _ = _process_wait_bridge(monkeypatch, [[]])
    terminated = []
    registry = importlib.import_module("qq_chat_analyzer.application.qq.qq_process_registry").QQProcessRegistry(
        terminator=lambda pid: terminated.append(pid))
    bridge._process_registry = registry
    cancelled = threading.Event()
    bridge.start_auth_flow(cancel_event=cancelled)
    registry.record(301)
    bridge.cancel_auth_flow(cancelled)
    assert terminated == [301]
    assert not bridge._auth_launch_started


def test_failed_owned_cleanup_reports_error_instead_of_waiting_on_echo_or_launching(monkeypatch):
    bridge, launcher, observed = _process_wait_bridge(monkeypatch, [])
    registry = importlib.import_module("qq_chat_analyzer.application.qq.qq_process_registry").QQProcessRegistry(
        terminator=lambda pid: False)
    registry.record(301)
    bridge._process_registry = registry
    result = bridge.start_auth_flow()
    assert result.code == "qq_runtime_cleanup_failed"
    assert observed == []
    assert launcher.calls == 0


def test_cancel_does_not_clean_an_existing_valid_connection(monkeypatch):
    cleaned = []
    bridge = _bridge(setup_service=_StubSetupService(),
                     connection_service=_StubConnectionService(_status(available=True)),
                     runtime_cleaner=lambda directory: cleaned.append(directory))
    # A previous Echo login is already valid when Connect is clicked again.
    bridge._auth_launch_started = True
    bridge._launcher_event = threading.Event()
    token = threading.Event()
    assert bridge.start_auth_flow(cancel_event=token).connected
    bridge.cancel_auth_flow(token)
    assert bridge._auth_launch_started
    assert cleaned == []


def test_new_attempt_cleans_cancelled_launcher_even_when_old_cleanup_is_queued(monkeypatch):
    bridge, launcher, observed = _process_wait_bridge(monkeypatch, [[]])
    old = threading.Event()
    bridge.start_auth_flow(cancel_event=old)
    old.set()
    # The new worker wins the lock before the cancelled worker's cleanup task.
    monkeypatch.setattr(_bridge_module(), "find_conflicting_qq_pids", lambda owned: [])
    bridge.start_auth_flow(cancel_event=threading.Event())
    bridge.cancel_auth_flow(old)
    assert launcher.calls == 2
    assert bridge._auth_launch_started


# ------------------------------------------------------------------ connected


def test_start_auth_flow_returns_connected_without_starting_anything() -> None:
    module = _connection_module()
    service = _StubConnectionService(
        _status(
            available=True,
            runtime_running=True,
            qq_online=True,
            message="QQ \u5df2\u8fde\u63a5\u3002",
        )
    )
    setup = _StubSetupService()
    launcher = _RecordingLauncher()

    snapshot = _bridge(
        setup_service=setup,
        connection_service=service,
        window_launcher=launcher,
    ).start_auth_flow()

    assert snapshot.state is module.ConnectionState.CONNECTED
    assert setup.connect_calls == 0
    assert launcher.calls == 0


# ---------------------------------------------------------- waiting for auth


def test_start_auth_flow_rejects_pre_existing_qrcode_until_session_update(
    tmp_path: Path,
) -> None:
    module = _connection_module()
    qr_path = tmp_path / "cache" / "qrcode.png"
    qr_path.parent.mkdir()
    qr_path.write_bytes(b"stale-qr-before-session")
    setup = _StubSetupService(
        connect_status=_status(
            available=False,
            runtime_running=True,
            qq_online=False,
        ),
        runtime_status=_runtime_status(),
        config=_runtime_config(tmp_path),
    )
    service = _StubConnectionService(
        _status(available=False, runtime_running=True, qq_online=False)
    )
    bridge = _bridge(
        setup_service=setup,
        connection_service=service,
        window_launcher=_RecordingLauncher(),
    )

    snapshot = bridge.start_auth_flow()

    assert snapshot.state is module.ConnectionState.WAITING_AUTH
    assert bridge.is_qrcode_ready() is False

    qr_path.write_bytes(b"fresh-qr-from-this-session")
    assert bridge.is_qrcode_ready() is True


def test_is_qrcode_ready_accepts_qrcode_after_auth_session_starts(
    tmp_path: Path,
) -> None:
    qr_path = tmp_path / "cache" / "qrcode.png"
    qr_path.parent.mkdir()
    setup = _StubSetupService(
        connect_status=_status(
            available=False,
            runtime_running=True,
            qq_online=False,
        ),
        runtime_status=_runtime_status(),
        config=_runtime_config(tmp_path),
    )
    service = _StubConnectionService(
        _status(available=False, runtime_running=True, qq_online=False)
    )
    bridge = _bridge(
        setup_service=setup,
        connection_service=service,
        window_launcher=_RecordingLauncher(),
        qrcode_path=qr_path,
    )

    assert bridge.is_qrcode_ready() is False
    bridge.start_auth_flow()
    assert bridge.is_qrcode_ready() is False

    qr_path.write_bytes(b"fresh-qr-from-this-session")
    assert bridge.is_qrcode_ready() is True


def test_start_auth_flow_does_not_launch_twice_while_waiting() -> None:
    module = _connection_module()
    service = _StubConnectionService(
        _status(available=False, runtime_running=True, qq_online=True)
    )
    setup = _StubSetupService(runtime_status=_runtime_status())
    launcher = _RecordingLauncher()
    bridge = _bridge(
        setup_service=setup,
        connection_service=service,
        window_launcher=launcher,
    )

    first = bridge.start_auth_flow()
    second = bridge.start_auth_flow()

    assert first.state is module.ConnectionState.WAITING_AUTH
    assert second.state is module.ConnectionState.WAITING_AUTH
    assert launcher.calls == 1


def test_disconnect_stops_runtime_and_returns_disconnected(
    tmp_path: Path,
) -> None:
    module = _connection_module()
    events: list[str] = []

    class _RecordingRegistry:
        def __init__(self) -> None:
            self.terminate_calls = 0

        def terminate_all(self) -> int:
            self.terminate_calls += 1
            return 1

    def cleaner(directory: Path) -> None:
        events.append(f"clean:{directory}")

    registry = _RecordingRegistry()
    setup = _StubSetupService(
        config=_runtime_config(tmp_path),
        runtime_status=_runtime_status("running"),
    )
    service = _StubConnectionService(
        _status(available=False, runtime_running=True, qq_online=True)
    )
    bridge = _bridge(
        setup_service=setup,
        connection_service=service,
        process_registry=registry,
        runtime_cleaner=cleaner,
    )

    snapshot = bridge.disconnect()

    assert snapshot.state is module.ConnectionState.DISCONNECTED
    assert registry.terminate_calls == 1
    assert events == [f"clean:{tmp_path}"]


# -------------------------------------------------------------------- errors


# ------------------------------------------------------- default window entry


def _runtime_config(tmp_path: Path, *, with_qq_path: bool = True):
    module = importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_environment_config"
    )
    (tmp_path / "NapCatWinBootMain.exe").write_text("fake", encoding="utf-8")
    (tmp_path / "NapCatWinBootHook.dll").write_text("fake", encoding="utf-8")
    (tmp_path / "napcat.mjs").write_text("export {}", encoding="utf-8")
    (tmp_path / "qqnt.json").write_text("{}", encoding="utf-8")
    (tmp_path / "launcher-user.bat").write_text(
        "@echo off\n",
        encoding="utf-8",
    )
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    qq_path = None
    if with_qq_path:
        qq_path = tmp_path / "QQ.exe"
        qq_path.write_text("fake", encoding="utf-8")
        package = tmp_path / "resources/app/package.json"
        package.parent.mkdir(parents=True, exist_ok=True)
        package.write_text('{"name":"QQ","version":"9.9.36-53644","buildVersion":"53644","main":"index.js"}', encoding="utf-8")
        (package.parent / "wrapper.node").write_bytes(b"fictional native resource")
        (config_dir / "qq_path.txt").write_text(
            str(qq_path),
            encoding="utf-8",
        )
    return module.QQEnvironmentConfig(
        runtime_directory=tmp_path,
        runtime_mode="custom",
        qq_install_path=qq_path,
    )


def test_default_launcher_strips_napcat_quick_login_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Echo's bundled NapCat must stay QR-only, not quick-login.

    Quick-login variables belong to other NapCat setups on the host; they must
    not leak into the child env Echo hands to its own runtime launcher.
    """
    bridge = _bridge_module()
    config = _runtime_config(tmp_path)
    spawned = {}
    monkeypatch.setattr(bridge.os, "name", "posix")
    monkeypatch.setenv("NAPCAT_QUICK_ACCOUNT", "10001")
    monkeypatch.setenv("NAPCAT_QUICK_PASSWORD", "fictional-password")
    monkeypatch.setenv("NAPCAT_QUICK_PASSWORD_MD5", "fictional-md5-hash")

    def _fake_popen(args, **kwargs):
        spawned["kwargs"] = kwargs
        return _FakeProcess(pid=4248)

    monkeypatch.setattr(*_launch_target(bridge), _fake_popen)

    bridge.default_auth_window_launcher(config)()

    child_env = spawned["kwargs"]["env"]
    assert "NAPCAT_QUICK_ACCOUNT" not in child_env
    assert "NAPCAT_QUICK_PASSWORD" not in child_env
    assert "NAPCAT_QUICK_PASSWORD_MD5" not in child_env
    assert child_env["NAPCAT_QQ_PATH"] == str(
        (tmp_path / "QQ.exe").resolve()
    )








def test_default_launcher_rejects_immediate_batch_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    config = _runtime_config(tmp_path)

    class _FailedProcess(_FakeProcess):
        def poll(self):
            return 7

    monkeypatch.setattr(
        *_launch_target(bridge),
        lambda args, **kwargs: _FailedProcess(pid=4246),
    )

    with pytest.raises(bridge.QQAuthWindowUnavailable):
        bridge.default_auth_window_launcher(config)()




def test_auth_flow_records_the_launched_window_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    registry_module = importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_process_registry"
    )
    config = _runtime_config(tmp_path)
    setup = _StubSetupService(
        connect_status=_status(
            available=False,
            runtime_running=True,
            qq_online=False,
        ),
        runtime_status=_runtime_status(),
        config=config,
    )
    service = _StubConnectionService(
        _status(available=False, runtime_running=True, qq_online=False)
    )
    registry = registry_module.QQProcessRegistry()

    def _fake_popen(args, **kwargs):
        return _FakeProcess(pid=7777)

    monkeypatch.setattr(*_launch_target(bridge), _fake_popen)

    snapshot = _bridge(
        setup_service=setup,
        connection_service=service,
        process_registry=registry,
    ).start_auth_flow()

    assert snapshot.state is _connection_module().ConnectionState.WAITING_AUTH
    assert registry.recorded() == (7777,)


def test_runtime_cleaner_refuses_path_only_process_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    monkeypatch.setattr(bridge.os, "name", "nt")
    monkeypatch.setattr(
        bridge.subprocess,
        "CREATE_NO_WINDOW",
        0x08000000,
        raising=False,
    )
    calls = []

    def _fake_run(command, **options):
        calls.append((command, options))

    monkeypatch.setattr(bridge.subprocess, "run", _fake_run)

    bridge.terminate_bundled_runtime_sessions(tmp_path)

    assert calls == []


class _FakeProcess:
    """Minimal stand-in for a spawned launcher subprocess."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self):
        return None


# ------------------------------------------------------------ config recovery


# ------------------------------------------------------- launcher relaunch


def test_reconnect_after_timeout_does_not_reuse_old_session(
    tmp_path: Path,
) -> None:
    """RED: After timeout+disconnect, a new auth flow starts fresh.

    Verifies the full lifecycle:
    1. start_auth_flow() -> WAITING_AUTH, baseline set
    2. disconnect() -> session reset (what timeout should call)
    3. start_auth_flow() again -> new baseline, old QR rejected

    The key behavioral assertion is that after disconnect+restart:
    - is_qrcode_ready() returns False (no QR at session start)
    - A new QR file must be generated for the new session
    """
    import time as _time

    qr_path = tmp_path / "cache" / "qrcode.png"
    qr_path.parent.mkdir()
    qr_path.write_bytes(b"first-session-qr")

    bridge_mod = _bridge_module()
    service = _StubConnectionService(
        _status(available=False, runtime_running=True, qq_online=False)
    )
    setup = _StubSetupService(
        connect_status=_status(
            available=False,
            runtime_running=True,
            qq_online=False,
        ),
        runtime_status=_runtime_status(),
        config=_runtime_config(tmp_path),
    )
    launcher = _RecordingLauncher()

    bridge = _bridge(
        setup_service=setup,
        connection_service=service,
        window_launcher=launcher,
        qrcode_path=qr_path,
    )

    # First auth flow
    snap1 = bridge.start_auth_flow()
    assert snap1.state is bridge_mod.ConnectionState.WAITING_AUTH
    baseline1 = bridge._qr_baseline
    assert baseline1 is not None
    assert bridge._qr_session_started is True

    # Simulate timeout: disconnect should be called
    snap2 = bridge.disconnect()
    assert snap2.state is bridge_mod.ConnectionState.DISCONNECTED
    assert bridge._qr_session_started is False
    assert bridge._qr_baseline is None

    # Second auth flow - should start fresh
    snap3 = bridge.start_auth_flow()
    assert snap3.state is bridge_mod.ConnectionState.WAITING_AUTH
    assert bridge._qr_session_started is True

    # Key assertion: old QR file should be rejected because it predates the new session
    # (baseline was set to the old QR file, and it hasn't changed)
    assert bridge.is_qrcode_ready() is False, (
        "Old QR from previous session should be rejected after disconnect+restart. "
        "The new session recorded the same QR file as baseline, so it's stale."
    )

    # Simulate a new QR being generated for the new session
    _time.sleep(0.05)
    qr_path.write_bytes(b"second-session-qr")
    assert bridge.is_qrcode_ready() is True, (
        "New QR generated after second session start should be accepted."
    )
