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


@pytest.mark.parametrize("fault", ["workspace", "binding", "none"])
def test_pre_auth_diagnostics_distinguish_early_returns_without_private_data(tmp_path, monkeypatch, caplog, fault):
    from types import SimpleNamespace
    from qq_chat_analyzer.application.connection_models import ConnectionSnapshot, ConnectionState
    from qq_chat_analyzer.application.qq.qq_runtime_workspace import QQWorkspaceError
    from qq_chat_analyzer.providers import napcat_qq_provider

    private = "fictional-secret-token account=12345678 C:/private/qq raw-response"
    config = SimpleNamespace(runtime_mode="managed", napcat_bridge_url="http://127.0.0.1:40655")
    paths = SimpleNamespace(runtime_id="a" * 64)
    def prepare(*, prepare):
        assert prepare is True
        if fault == "workspace":
            error = QQWorkspaceError(private)
            error.code = private
            raise error
        return paths
    setup = SimpleNamespace(get_runtime_paths=prepare, get_environment_config=lambda: config)
    manager = SimpleNamespace(get_snapshot=lambda: ConnectionSnapshot(ConnectionState.CONNECTED, "qq", ""),
                              end_auth_waiting=lambda: None)
    monkeypatch.setattr(napcat_qq_provider, "NapCatQQProvider", lambda *a, **k: SimpleNamespace(
        status=lambda: SimpleNamespace(runtime_id=("b" if fault == "binding" else "a") * 64)))
    caplog.set_level("INFO")
    result = _bridge(setup_service=setup, manager=manager).start_auth_flow()
    assert "stage=workspace_prepare outcome=started" in caplog.text
    if fault == "workspace":
        assert result.state is ConnectionState.ERROR
        assert "stage=workspace_prepare outcome=failed" in caplog.text
        assert "failure_code=workspace_error snapshot_code=unspecified" in caplog.text
    elif fault == "binding":
        assert result.code == "qq_runtime_identity_mismatch"
        assert "stage=workspace_prepare outcome=success" in caplog.text
        assert "stage=runtime_binding outcome=failed" in caplog.text
        assert "snapshot_code=qq_runtime_identity_mismatch" in caplog.text
    else:
        assert result.state is ConnectionState.CONNECTED
        assert "stage=workspace_prepare outcome=success" in caplog.text
        assert "stage=runtime_binding outcome=success" in caplog.text
    if fault != "none":
        assert "start_auth_flow entered" not in caplog.text
    for value in (private, "12345678", "C:/private", "a" * 64, "b" * 64):
        assert value not in caplog.text


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


@pytest.mark.parametrize("samples", [[[]], [[101, 102], [102], []], [[101], [102], []]])
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


def test_connected_auth_never_detects_or_cleans_processes(monkeypatch):
    def forbidden(*args):
        raise AssertionError("connected session must be preserved")
    monkeypatch.setattr(_bridge_module(), "find_conflicting_qq_pids", forbidden)
    bridge = _bridge(setup_service=_StubSetupService(),
                     connection_service=_StubConnectionService(_status(available=True, runtime_running=True, qq_online=True)),
                     window_launcher=forbidden, runtime_cleaner=forbidden)
    assert bridge.start_auth_flow().connected


def test_process_detection_failure_does_not_launch(monkeypatch):
    bridge, launcher, _ = _process_wait_bridge(monkeypatch, [OSError("fictional detection failure")])
    result = bridge.start_auth_flow()
    assert result.code == "qq_process_detection_failed"
    assert result.state is _connection_module().ConnectionState.ERROR
    assert launcher.calls == 0


@pytest.mark.parametrize("error_type", [OSError, ValueError, RuntimeError])
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


def test_detection_success_diagnostics_are_bounded_and_do_not_list_processes(monkeypatch, caplog):
    bridge, launcher, _ = _process_wait_bridge(
        monkeypatch, [[87654321], [87654321], [87654321], []], process_poll_interval=0,
    )
    with caplog.at_level("INFO", logger=_bridge_module()._LOGGER.name):
        result = bridge.start_auth_flow()
    records = [record for record in caplog.records if "process detection" in record.getMessage()]
    assert result.state is _connection_module().ConnectionState.WAITING_AUTH
    assert launcher.calls == 1
    assert len(records) == 2  # initial conflict and eventual clear, not every poll
    assert "category=conflict" in records[0].getMessage()
    assert "category=clear" in records[1].getMessage()
    assert all("stage=complete" in record.getMessage() and "elapsed_ms=" in record.getMessage()
               for record in records)
    assert "87654321" not in caplog.text


def test_cancelled_failed_detection_never_logs_or_launches(monkeypatch, caplog):
    cancelled = threading.Event()
    bridge, launcher, _ = _process_wait_bridge(monkeypatch, [])
    def detect(owned):
        cancelled.set()
        raise OSError("RAW_EXCEPTION_SENTINEL")
    monkeypatch.setattr(_bridge_module(), "find_conflicting_qq_pids", detect)
    with caplog.at_level("INFO", logger=_bridge_module()._LOGGER.name):
        result = bridge.start_auth_flow(cancel_event=cancelled)
    assert result.code == "qq_auth_cancelled"
    assert launcher.calls == 0
    assert not any("process detection" in record.getMessage() for record in caplog.records)


def test_process_wait_timeout_does_not_launch(monkeypatch):
    bridge, launcher, _ = _process_wait_bridge(monkeypatch, [[101]], process_wait_timeout=0)
    result = bridge.start_auth_flow()
    assert result.code == "qq_process_exit_timeout"
    assert launcher.calls == 0


@pytest.mark.parametrize("first_sample,expected_code", [
    ([101], "qq_process_exit_timeout"),
    (OSError("fictional snapshot failure"), "qq_process_detection_failed"),
])
def test_same_bridge_rechecks_processes_after_failed_attempt(
    monkeypatch, first_sample, expected_code,
):
    # Catch a failed attempt retaining a launch/wait guard or cached conflict.
    # A zero deadline makes the timeout deterministic without sleeping.
    bridge, launcher, observed = _process_wait_bridge(
        monkeypatch, [first_sample, []], process_wait_timeout=0,
    )
    failed = bridge.start_auth_flow()
    assert failed.code == expected_code
    assert failed.state is _connection_module().ConnectionState.ERROR
    assert launcher.calls == 0
    assert bridge.get_snapshot().state is _connection_module().ConnectionState.DISCONNECTED
    assert bridge.is_qrcode_ready() is False

    # External QQ has exited (or enumeration recovered). Reuse the bridge,
    # without disconnecting it or manually resetting any internal state.
    progress = []
    retried = bridge.start_auth_flow(progress.append)
    assert observed == [first_sample, []]
    assert retried.state is _connection_module().ConnectionState.WAITING_AUTH
    assert launcher.calls == 1
    assert "请完全退出 QQ" not in progress
    assert _bridge_module().PROGRESS_WAITING_LOGIN in progress


def test_same_bridge_retries_after_cancelled_conflict_wait(monkeypatch):
    bridge, launcher, observed = _process_wait_bridge(monkeypatch, [[101], []])
    old = threading.Event()

    def cancel_when_waiting(message):
        if message == "请完全退出 QQ":
            old.set()

    cancelled = bridge.start_auth_flow(cancel_when_waiting, cancel_event=old)
    assert cancelled.code == "qq_auth_cancelled"
    assert launcher.calls == 0
    assert bridge.get_snapshot().state is _connection_module().ConnectionState.DISCONNECTED
    assert bridge.is_qrcode_ready() is False

    current = threading.Event()
    retried = bridge.start_auth_flow(cancel_event=current)
    assert retried.state is _connection_module().ConnectionState.WAITING_AUTH
    assert observed == [[101], []]
    assert launcher.calls == 1
    # Cleanup queued by the old cancelled worker must preserve the new wait.
    bridge.cancel_auth_flow(old)
    assert bridge.get_snapshot().state is _connection_module().ConnectionState.WAITING_AUTH
    assert bridge.start_auth_flow(cancel_event=current).state is _connection_module().ConnectionState.WAITING_AUTH
    assert launcher.calls == 1


def test_process_wait_timeout_has_safe_phase_and_duration(monkeypatch, caplog):
    bridge, launcher, _ = _process_wait_bridge(monkeypatch, [[87654321]], process_wait_timeout=0)
    with caplog.at_level("INFO", logger=_bridge_module()._LOGGER.name):
        result = bridge.start_auth_flow()
    assert result.code == "qq_process_exit_timeout" and launcher.calls == 0
    records = [record for record in caplog.records if "category=timeout" in record.getMessage()]
    assert len(records) == 1
    assert "stage=conflict_wait" in records[0].getMessage()
    assert "elapsed_ms=" in records[0].getMessage()
    assert "87654321" not in caplog.text


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


def test_cancel_process_wait_wakes_without_waiting_for_poll_interval(monkeypatch):
    bridge, launcher, _ = _process_wait_bridge(monkeypatch, [[101]], process_poll_interval=60)
    cancelled = threading.Event()
    entered = threading.Event()
    results = []
    def report(message):
        if message == "请完全退出 QQ":
            entered.set()
    worker = threading.Thread(target=lambda: results.append(bridge.start_auth_flow(report, cancel_event=cancelled)))
    worker.start()
    try:
        assert entered.wait(2)
        cancelled.set()
        worker.join(2)
        assert not worker.is_alive()
        assert results[0].code == "qq_auth_cancelled"
        assert launcher.calls == 0
    finally:
        cancelled.set()
        worker.join(2)


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


def test_start_auth_flow_does_not_pre_start_runtime_before_launcher() -> None:
    module = _connection_module()
    service = _StubConnectionService(
        _status(available=False, runtime_running=False, qq_online=False)
    )
    setup = _StubSetupService(
        connect_status=_status(
            available=False,
            runtime_running=True,
            qq_online=False,
        ),
        runtime_status=_runtime_status(),
    )
    launcher = _RecordingLauncher()

    snapshot = _bridge(
        setup_service=setup,
        connection_service=service,
        window_launcher=launcher,
    ).start_auth_flow()

    assert setup.connect_calls == 0
    assert launcher.calls == 1
    assert snapshot.state is module.ConnectionState.WAITING_AUTH




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


def test_is_qrcode_ready_rejects_orphan_qrcode_without_auth_session(
    tmp_path: Path,
) -> None:
    """A QR left by an old Echo/runtime session must not be shown yet."""
    qr_path = tmp_path / "cache" / "qrcode.png"
    qr_path.parent.mkdir()
    qr_path.write_bytes(b"orphan-qr-from-old-session")
    bridge = _bridge(qrcode_path=qr_path)

    assert bridge.is_qrcode_ready() is False


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


def test_is_qrcode_ready_accepts_refreshed_qrcode_after_expiry(
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

    bridge.start_auth_flow()
    qr_path.write_bytes(b"first-qr")
    assert bridge.is_qrcode_ready() is True

    qr_path.write_bytes(b"refreshed-qr-after-expiry")
    assert bridge.is_qrcode_ready() is True


def test_start_auth_flow_logs_qr_stages_without_private_metadata(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
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

    with caplog.at_level("INFO", logger="qq_chat_analyzer.desktop.qq_auth_bridge"):
        bridge.start_auth_flow()
        assert bridge.is_qrcode_ready() is False
        qr_path.write_bytes(b"fresh-qr-from-this-session")
        assert bridge.is_qrcode_ready() is True

    messages = [record.message for record in caplog.records]
    assert any("qr baseline exists" in message for message in messages)
    assert any("qr accepted" in message for message in messages)
    assert "sha256=" not in caplog.text
    assert str(tmp_path) not in caplog.text
    assert "stale-qr-before-session" not in caplog.text
    assert "fresh-qr-from-this-session" not in caplog.text


def test_start_auth_flow_reports_existing_backend_stages() -> None:
    service = _StubConnectionService(
        _status(available=False, runtime_running=False, qq_online=False)
    )
    setup = _StubSetupService(
        connect_status=_status(
            available=False,
            runtime_running=True,
            qq_online=False,
        ),
        runtime_status=_runtime_status(),
    )
    progress: list[str] = []

    _bridge(
        setup_service=setup,
        connection_service=service,
        window_launcher=_RecordingLauncher(),
    ).start_auth_flow(progress=progress.append)

    assert progress == [
        "正在检查 QQ 运行环境...",
        "正在启动 QQ 环境...",
        "正在加载 NapCat...",
        "等待 QQ 登录...",
    ]


def test_start_auth_flow_reopens_window_when_already_waiting() -> None:
    module = _connection_module()
    service = _StubConnectionService(
        _status(available=False, runtime_running=True, qq_online=True)
    )
    setup = _StubSetupService(runtime_status=_runtime_status())
    launcher = _RecordingLauncher()

    snapshot = _bridge(
        setup_service=setup,
        connection_service=service,
        window_launcher=launcher,
    ).start_auth_flow()

    assert setup.connect_calls == 0
    assert launcher.calls == 1
    assert snapshot.state is module.ConnectionState.WAITING_AUTH


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


def test_start_auth_flow_picks_up_login_completed_during_launch() -> None:
    module = _connection_module()
    service = _StubConnectionService(
        queue=[
            _status(available=False, runtime_running=False),
            _status(available=False, runtime_running=False),
            _status(
                available=True,
                runtime_running=True,
                qq_online=True,
                message="QQ \u5df2\u8fde\u63a5\u3002",
            ),
        ]
    )
    setup = _StubSetupService(
        connect_status=_status(
            available=False,
            runtime_running=True,
            qq_online=False,
        ),
        runtime_status=_runtime_status(),
    )
    launcher = _RecordingLauncher()

    snapshot = _bridge(
        setup_service=setup,
        connection_service=service,
        window_launcher=launcher,
    ).start_auth_flow()

    assert launcher.calls == 1
    assert snapshot.state is module.ConnectionState.WAITING_AUTH
    assert (
        _bridge(
            setup_service=setup,
            connection_service=service,
            window_launcher=launcher,
        ).get_snapshot().state
        is module.ConnectionState.CONNECTED
    )


def test_polling_after_auth_launch_keeps_waiting_until_bridge_ready() -> None:
    module = _connection_module()
    service = _StubConnectionService(
        queue=[
            _status(available=False, runtime_running=False),
            _status(available=False, runtime_running=False),
            _status(available=False, runtime_running=False),
            _status(available=False, runtime_running=False),
            _status(
                available=True,
                runtime_running=True,
                qq_online=True,
                message="QQ \u5df2\u8fde\u63a5\u3002",
            ),
        ]
    )
    setup = _StubSetupService(
        runtime_status=_runtime_status("stopped"),
    )
    bridge = _bridge(
        setup_service=setup,
        connection_service=service,
        window_launcher=_RecordingLauncher(),
    )

    bridge.start_auth_flow()

    assert bridge.get_snapshot().state is module.ConnectionState.WAITING_AUTH
    assert bridge.get_snapshot().state is module.ConnectionState.WAITING_AUTH
    assert bridge.get_snapshot().state is module.ConnectionState.CONNECTED


def test_start_auth_flow_stops_previous_runtime_before_relaunch(
    tmp_path: Path,
) -> None:
    module = _connection_module()
    events: list[str] = []

    def cleaner(directory: Path) -> None:
        events.append(f"clean:{directory}")

    def launcher() -> None:
        events.append("launch")

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
        window_launcher=launcher,
        runtime_cleaner=cleaner,
    )

    snapshot = bridge.start_auth_flow()

    assert snapshot.state is module.ConnectionState.WAITING_AUTH
    assert events == [f"clean:{tmp_path}", "launch"]


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


def test_start_auth_flow_does_not_clean_runtime_when_reusing_launcher(
    tmp_path: Path,
) -> None:
    module = _connection_module()
    events: list[str] = []

    def cleaner(directory: Path) -> None:
        events.append(f"clean:{directory}")

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
    launcher = _RecordingLauncher()
    bridge = _bridge(
        setup_service=setup,
        connection_service=service,
        window_launcher=launcher,
        runtime_cleaner=cleaner,
    )

    first = bridge.start_auth_flow()
    second = bridge.start_auth_flow()

    assert first.state is module.ConnectionState.WAITING_AUTH
    assert second.state is module.ConnectionState.WAITING_AUTH
    assert launcher.calls == 1
    assert events == [f"clean:{tmp_path}"]


def test_get_snapshot_delegates_to_the_connection_manager() -> None:
    module = _connection_module()
    service = _StubConnectionService(
        _status(available=False, runtime_running=True, qq_online=False)
    )

    snapshot = _bridge(connection_service=service).get_snapshot()

    assert snapshot.state is module.ConnectionState.WAITING_AUTH


# -------------------------------------------------------------------- errors


def test_window_launch_failure_returns_a_safe_error_snapshot() -> None:
    module = _connection_module()
    service = _StubConnectionService(
        _status(available=False, runtime_running=True, qq_online=False)
    )
    setup = _StubSetupService(runtime_status=_runtime_status())
    launcher = _RecordingLauncher(error=RuntimeError("login window exploded"))

    snapshot = _bridge(
        setup_service=setup,
        connection_service=service,
        window_launcher=launcher,
    ).start_auth_flow()

    assert snapshot.state is module.ConnectionState.ERROR
    assert "login window exploded" not in snapshot.message
    assert snapshot.action_hint


def test_missing_qq_window_launch_reports_install_path_code() -> None:
    module = _connection_module()
    bridge = _bridge_module()
    service = _StubConnectionService(
        _status(available=False, runtime_running=True, qq_online=False)
    )
    setup = _StubSetupService(runtime_status=_runtime_status())
    launcher = _RecordingLauncher(
        error=bridge.QQAuthWindowUnavailable(
            bridge.MESSAGE_QQ_MISSING,
            code=bridge.QQ_INSTALL_PATH_MISSING_CODE,
        )
    )

    snapshot = _bridge(
        setup_service=setup,
        connection_service=service,
        window_launcher=launcher,
    ).start_auth_flow()

    assert snapshot.state is module.ConnectionState.ERROR
    assert snapshot.code == "qq_install_path_missing"


def test_start_auth_flow_without_setup_service_reports_error() -> None:
    module = _connection_module()

    snapshot = _bridge().start_auth_flow()

    assert snapshot.state is module.ConnectionState.ERROR
    assert snapshot.message


def test_start_auth_flow_logs_the_auth_flow(
    caplog: pytest.LogCaptureFixture,
) -> None:
    module = _connection_module()
    service = _StubConnectionService(
        _status(available=False, runtime_running=True, qq_online=False)
    )
    setup = _StubSetupService(runtime_status=_runtime_status())
    launcher = _RecordingLauncher()

    with caplog.at_level("INFO", logger="qq_chat_analyzer.desktop.qq_auth_bridge"):
        snapshot = _bridge(
            setup_service=setup,
            connection_service=service,
            window_launcher=launcher,
        ).start_auth_flow()

    assert snapshot.state is module.ConnectionState.WAITING_AUTH
    assert any("start_auth_flow entered" in record.message for record in caplog.records)
    assert any("login window launched" in record.message for record in caplog.records)


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


def test_default_launcher_opens_the_runtime_login_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    config = _runtime_config(tmp_path)
    spawned = {}
    monkeypatch.setattr(bridge.os, "name", "posix")
    monkeypatch.setenv("ECHO_MODE", "inherited-parent-value")

    def _fake_popen(args, **kwargs):
        spawned["args"] = list(args)
        spawned["kwargs"] = kwargs
        return _FakeProcess(pid=4242)

    monkeypatch.setattr(*_launch_target(bridge), _fake_popen)

    bridge.default_auth_window_launcher(config)()

    assert spawned["args"] == [
        str(tmp_path / "NapCatWinBootMain.exe"),
        str(tmp_path / "QQ.exe"),
        str(tmp_path / "NapCatWinBootHook.dll"),
    ]
    assert spawned["kwargs"]["cwd"] == str(tmp_path)
    assert "creationflags" not in spawned["kwargs"]
    assert spawned["kwargs"]["env"]["NAPCAT_QQ_PATH"] == str(
        (tmp_path / "QQ.exe").resolve()
    )
    assert "ECHO_MODE" not in spawned["kwargs"]["env"]


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








def test_default_launcher_hides_napcat_console_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    config = _runtime_config(tmp_path)
    spawned = {}

    def _fake_popen(args, **kwargs):
        spawned["args"] = list(args)
        spawned["kwargs"] = kwargs
        return _FakeProcess(pid=4245)

    monkeypatch.setattr(bridge.os, "name", "nt")
    monkeypatch.setattr(
        bridge.subprocess,
        "CREATE_NO_WINDOW",
        0x08000000,
        raising=False,
    )
    monkeypatch.setattr(*_launch_target(bridge), _fake_popen)

    bridge.default_auth_window_launcher(config)()

    assert spawned["args"] == [
        str(tmp_path / "NapCatWinBootMain.exe"),
        str(tmp_path / "QQ.exe"),
        str(tmp_path / "NapCatWinBootHook.dll"),
    ]
    assert spawned["kwargs"]["cwd"] == str(tmp_path)
    assert spawned["kwargs"]["creationflags"] == 0x08000000
    assert spawned["kwargs"]["stdin"] is bridge.subprocess.DEVNULL
    assert spawned["kwargs"]["stdout"] is bridge.subprocess.PIPE
    assert spawned["kwargs"]["stderr"] is bridge.subprocess.PIPE


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




def test_default_launcher_logs_completed_stdout_and_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bridge = _bridge_module()
    config = _runtime_config(tmp_path)

    class _CompletedProcess(_FakeProcess):
        def poll(self):
            return 0

        def communicate(self):
            return ("launcher output", "launcher warning")

    monkeypatch.setattr(
        *_launch_target(bridge),
        lambda args, **kwargs: _CompletedProcess(pid=4247),
    )

    with caplog.at_level("INFO", logger="qq_chat_analyzer.desktop.qq_auth_bridge"):
        bridge.default_auth_window_launcher(config)()

    assert "returncode=0" in caplog.text
    assert "stdout=bytes=15" in caplog.text
    assert "stderr=bytes=16" in caplog.text


def test_default_launcher_logs_safe_launch_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bridge = _bridge_module()
    config = _runtime_config(tmp_path)
    spawned = {}

    def _fake_popen(args, **kwargs):
        spawned["args"] = list(args)
        return _FakeProcess(pid=4243)

    monkeypatch.setattr(*_launch_target(bridge), _fake_popen)

    with caplog.at_level("INFO", logger="qq_chat_analyzer.desktop.qq_auth_bridge"):
        bridge.default_auth_window_launcher(config)()

    assert "launch requested" in caplog.text
    assert "launch command=" not in caplog.text
    assert "qq_path=" not in caplog.text
    assert str(tmp_path) not in caplog.text
    assert "launch result pid=4243 returncode=None" in caplog.text
    assert "launcher-user.bat" not in caplog.text
    assert "NapCatWinBootMain.exe" not in caplog.text


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


def test_default_launcher_prefers_the_configured_qq_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    module = importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_environment_config"
    )
    (tmp_path / "NapCatWinBootMain.exe").write_text("fake", encoding="utf-8")
    (tmp_path / "NapCatWinBootHook.dll").write_text("fake", encoding="utf-8")
    (tmp_path / "napcat.mjs").write_text("export {}", encoding="utf-8")
    (tmp_path / "launcher-user.bat").write_text("@echo off\n", encoding="utf-8")
    configured = tmp_path / "configured/QQ.exe"
    configured.parent.mkdir()
    configured.write_text("fake", encoding="utf-8")
    package = configured.parent / "resources/app/package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"name":"QQ","version":"9.9.36-53644","buildVersion":"53644","main":"index.js"}', encoding="utf-8")
    (package.parent / "wrapper.node").write_bytes(b"fictional native resource")
    saved = tmp_path / "saved-qq.exe"
    saved.write_text("fake", encoding="utf-8")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "qq_path.txt").write_text(str(saved), encoding="utf-8")
    config = module.QQEnvironmentConfig(
        runtime_directory=tmp_path,
        runtime_mode="custom",
        qq_install_path=configured,
    )
    spawned = {}

    def _fake_popen(args, **kwargs):
        spawned["args"] = list(args)
        spawned["kwargs"] = kwargs
        return _FakeProcess(pid=4244)

    monkeypatch.setattr(*_launch_target(bridge), _fake_popen)

    bridge.default_auth_window_launcher(config)()

    assert spawned["args"][1] == str(configured)
    assert spawned["args"][-1] == str(tmp_path / "NapCatWinBootHook.dll")
    assert str(saved) not in spawned["args"]
    assert spawned["kwargs"]["env"]["NAPCAT_QQ_PATH"] == str(
        configured.resolve()
    )


def test_find_qq_script_hides_powershell_console_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    script = tmp_path / "find-qq.ps1"
    script.write_text("Write-Output 'fictional'", encoding="utf-8")
    calls = []

    class _Completed:
        stdout = ""

    def _fake_run(command, **options):
        calls.append((command, options))
        return _Completed()

    monkeypatch.setattr(bridge.os, "name", "nt")
    monkeypatch.setattr(
        bridge.subprocess,
        "CREATE_NO_WINDOW",
        0x08000000,
        raising=False,
    )
    monkeypatch.setattr(bridge.subprocess, "run", _fake_run)

    assert bridge._detect_qq_path_with_script(script) is None

    assert calls[0][0] == [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
    ]
    assert calls[0][1]["creationflags"] == 0x08000000


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


def test_runtime_cleaner_skips_non_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    monkeypatch.setattr(bridge.os, "name", "posix")
    calls = []
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *args, **kwargs: calls.append(args),
    )

    bridge.terminate_bundled_runtime_sessions(tmp_path)

    assert calls == []


class _FakeProcess:
    """Minimal stand-in for a spawned launcher subprocess."""

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self):
        return None


def test_default_launcher_rejects_a_missing_qq_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [])
    config = _runtime_config(tmp_path, with_qq_path=False)

    with pytest.raises(bridge.QQAuthWindowUnavailable) as excinfo:
        bridge.default_auth_window_launcher(config)

    assert excinfo.value.code == "qq_install_path_missing"


def test_resolve_qq_install_path_reads_the_saved_launcher_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [])
    qq_path = tmp_path / "QQ.exe"
    qq_path.write_text("fake", encoding="utf-8")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "qq_path.txt").write_text(str(qq_path), encoding="utf-8")

    resolved = bridge.resolve_qq_install_path(None, tmp_path)

    assert resolved == qq_path


def test_resolve_qq_install_path_prefers_a_custom_configured_path(
    tmp_path: Path,
) -> None:
    bridge = _bridge_module()
    config_module = importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_environment_config"
    )
    custom = tmp_path / "Custom Install" / "QQ.exe"
    custom.parent.mkdir()
    custom.write_text("fictional", encoding="utf-8")
    saved = tmp_path / "saved-qq.exe"
    saved.write_text("fictional", encoding="utf-8")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "qq_path.txt").write_text(str(saved), encoding="utf-8")
    config = config_module.QQEnvironmentConfig(qq_install_path=custom)

    resolved = bridge.resolve_qq_install_path(config, tmp_path)

    assert resolved == custom


def test_resolve_qq_install_path_uses_python_detector_when_script_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    found = tmp_path / "Detected" / "QQ.exe"
    found.parent.mkdir()
    found.write_text("fictional", encoding="utf-8")
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [found])

    resolved = bridge.resolve_qq_install_path(None, tmp_path)

    assert resolved == found


def test_resolve_qq_install_path_returns_none_when_not_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [])

    resolved = bridge.resolve_qq_install_path(None, tmp_path)

    assert resolved is None


def test_detect_qq_install_path_returns_first_existing_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    missing = tmp_path / "missing.exe"
    found = tmp_path / "QQ.exe"
    found.write_text("fictional", encoding="utf-8")
    monkeypatch.setattr(
        bridge,
        "_qq_install_candidates",
        lambda: [missing, found],
    )

    assert bridge._detect_qq_install_path() == found


# ------------------------------------------------------------ config recovery


def test_launch_window_recovers_missing_qq_config_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    config = _runtime_config(tmp_path)
    setup = _StubSetupService(config_missing=True)
    launcher = _RecordingLauncher()

    class _FakeLoader:
        @staticmethod
        def load_or_default():
            return config

    monkeypatch.setattr(bridge, "QQEnvironmentConfigLoader", _FakeLoader)
    monkeypatch.setattr(bridge, "default_auth_window_launcher", lambda _, **_kwargs: launcher)

    instance = _bridge(setup_service=setup)
    instance._launch_window()

    assert setup.config_calls == 2
    assert setup.save_calls == 1
    assert setup.connect_calls == 0
    assert launcher.calls == 1
    assert instance._auth_launch_started is True


def test_launch_window_keeps_existing_config_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    setup = _StubSetupService(config=_runtime_config(tmp_path))
    launcher = _RecordingLauncher()

    monkeypatch.setattr(bridge, "default_auth_window_launcher", lambda _, **_kwargs: launcher)

    instance = _bridge(setup_service=setup)
    instance._launch_window()

    assert setup.config_calls == 1
    assert setup.save_calls == 0
    assert setup.connect_calls == 0
    assert launcher.calls == 1


def test_start_auth_flow_missing_config_recovery_failure_returns_friendly_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _connection_module()
    bridge = _bridge_module()
    config_error = _config_module().QQConfigNotFound()
    setup = _StubSetupService(error=config_error, config_missing=True)
    service = _StubConnectionService(
        _status(available=False, runtime_running=False, qq_online=False)
    )
    launcher = _RecordingLauncher()

    class _FakeLoader:
        @staticmethod
        def load_or_default():
            raise _config_module().QQConfigNotFound()

    monkeypatch.setattr(bridge, "QQEnvironmentConfigLoader", _FakeLoader)
    monkeypatch.setattr(bridge, "default_auth_window_launcher", lambda _, **_kwargs: launcher)

    snapshot = _bridge(
        setup_service=setup,
        connection_service=service,
    ).start_auth_flow()

    assert snapshot.state is module.ConnectionState.ERROR
    assert snapshot.message == "未找到可用的 QQ 运行组件，请确认 Echo 安装完整后重试。"
    assert setup.save_calls == 0
    assert setup.connect_calls == 0
    assert launcher.calls == 0


# ------------------------------------------------------- launcher relaunch


class _ExitableProcess:
    """Launcher process stub whose exit state can change between launches."""

    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self._exited = False

    def mark_exited(self) -> None:
        self._exited = True

    def poll(self):
        return 1 if self._exited else None


class _ProcessReturningLauncher:
    """Count calls and return the same process stub each time."""

    def __init__(self, process):
        self.calls = 0
        self._process = process

    def __call__(self):
        self.calls += 1
        return self._process


def test_launch_window_relaunches_after_launcher_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge_module()
    setup = _StubSetupService(config=_runtime_config(tmp_path))
    process = _ExitableProcess()
    launcher = _ProcessReturningLauncher(process)

    monkeypatch.setattr(bridge, "default_auth_window_launcher", lambda _, **_kwargs: launcher)

    instance = _bridge(setup_service=setup)
    instance._launch_window()

    assert launcher.calls == 1
    assert instance._auth_launch_started is True

    process.mark_exited()
    instance._launch_window()

    assert launcher.calls == 2
    assert instance._auth_launch_started is True

def test_handle_qq_auth_timeout_calls_facade_disconnect_via_facade(
    tmp_path: Path,
) -> None:
    """RED: After timeout, the facade disconnect path must reset auth state.

    Root cause:
    WAITING_AUTH reaches 120s timeout -> QQWorkspace only does UI cleanup
    -> underlying auth session / connection manager is NOT ended
    -> user clicks "restart" -> start_auth_flow may reuse old session / QR

    The fix: _handle_qq_auth_timeout() must call
    `self._facade.disconnect_qq()` which delegates to
    QQAuthBridge.disconnect() -> _reset_auth_session().

    This test verifies the disconnect path properly resets state so that
    a subsequent start_auth_flow starts fresh.
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

    # Step 1: start_auth_flow -> WAITING_AUTH, baseline set
    snap1 = bridge.start_auth_flow()
    assert snap1.state is bridge_mod.ConnectionState.WAITING_AUTH
    assert bridge._qr_session_started is True
    baseline1 = bridge._qr_baseline
    assert baseline1 is not None

    # Step 2: disconnect (this is what timeout should call via facade)
    snap2 = bridge.disconnect()
    assert snap2.state is bridge_mod.ConnectionState.DISCONNECTED
    assert bridge._qr_session_started is False
    assert bridge._qr_baseline is None
    assert bridge._qr_session_started_at is None
    assert bridge._qr_ready_logged is False

    # Step 3: verify the bridge is in a clean state for a fresh start
    # _qr_session_started must be False so is_qrcode_ready returns False
    assert bridge.is_qrcode_ready() is False, (
        "After disconnect, is_qrcode_ready() must return False. "
        "This is the bootstrap/reset regression: stale QR must not be accepted."
    )


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
