"""QQ integration contracts with fictional process resources only."""
from types import SimpleNamespace
import sys

import pytest

from qq_chat_analyzer import runtime
from qq_chat_analyzer.application.qq import qq_auth_bridge as bridge
from qq_chat_analyzer.application.qq.qq_process_registry import QQProcessRegistry
from qq_chat_analyzer.application.qq.qq_runtime_manager import QQRuntimeManager


class JobProcess:
    pid = 48299
    def __init__(self):
        self.closed = False
        self.root_exited = False
    def close(self):
        self.closed = True
    def tree_running(self):
        return not self.closed
    def poll(self):
        return 0 if self.root_exited or self.closed else None


def test_direct_runtime_uses_owned_launcher_and_retains_handle(tmp_path, monkeypatch):
    executable = tmp_path / "fictional.exe"
    executable.write_text("fictional")
    process = JobProcess()
    calls = []
    def launch(args, **options):
        calls.append((args, options))
        return process
    monkeypatch.setattr(runtime, "launch_owned_process", launch, raising=False)
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **k: pytest.fail("unmanaged launch"))
    registry = QQProcessRegistry(terminator=lambda pid: pytest.fail("PID fallback"))
    instance = runtime.BundledQQRuntime(runtime.QQRuntimeConfig(executable, tmp_path),
                                        health_checker=lambda url: False)
    manager = QQRuntimeManager(instance, process_registry=registry)
    assert manager.start().state.value == "running"
    assert calls[0][0] == [str(executable)]
    assert instance.get_info().owned_process_handle is process
    process.root_exited = True
    assert instance.running()
    assert manager.stop().state.value == "stopped"
    assert process.closed
    registry.terminate_all()


def test_auth_launcher_uses_job_and_closes_failed_launch(tmp_path, monkeypatch):
    (tmp_path / "napcat.mjs").write_text("// fictional")
    resources = tmp_path / "resources/app"
    resources.mkdir(parents=True)
    (resources / "package.json").write_text('{"version":"9.9.36-53644","buildVersion":"53644","main":"fake"}')
    (resources / "wrapper.node").write_bytes(b"fictional native resource")
    process = JobProcess()
    process.poll = lambda: 9
    monkeypatch.setattr(bridge, "launch_owned_process", lambda *a, **k: process, raising=False)
    monkeypatch.setattr(bridge.subprocess, "Popen", lambda *a, **k: pytest.fail("unmanaged launch"))
    with pytest.raises(bridge.QQAuthWindowUnavailable):
        bridge._launch_auth_window(tmp_path, tmp_path / "fictional.exe", tmp_path / "QQ.exe")
    assert process.closed


def test_path_only_cleaner_cannot_terminate_external_processes(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: pytest.fail("process scan"))
    bridge.terminate_bundled_runtime_sessions(tmp_path)


def test_cancel_during_launch_closes_late_process_and_does_not_register(monkeypatch):
    registry = QQProcessRegistry(terminator=lambda pid: pytest.fail("PID fallback"))
    process = JobProcess()
    manager = SimpleNamespace(disconnect=lambda: None)
    auth = bridge.QQAuthBridge(setup_service=SimpleNamespace(
        get_environment_config=lambda: None), manager=manager, process_registry=registry)
    def launch():
        auth.disconnect()
        return process
    monkeypatch.setattr(bridge, "default_auth_window_launcher", lambda *a, **k: launch)
    with pytest.raises(bridge.QQAuthWindowUnavailable):
        auth._launch_window()
    assert process.closed
    assert registry.recorded() == ()


def test_repeated_start_keeps_owned_job_when_service_becomes_healthy(tmp_path):
    executable = tmp_path / "fictional.exe"
    executable.write_text("fictional")
    process = JobProcess()
    healthy = [False]
    instance = runtime.BundledQQRuntime(runtime.QQRuntimeConfig(executable, tmp_path),
        health_checker=lambda url: healthy[0], launcher=lambda: process)
    first = instance.start()
    healthy[0] = True
    assert instance.start() is first
    instance.stop()
    assert process.closed


def test_finished_job_is_released_by_manager_stop(tmp_path):
    executable = tmp_path / "fictional.exe"
    executable.write_text("fictional")
    process = JobProcess()
    instance = runtime.BundledQQRuntime(runtime.QQRuntimeConfig(executable, tmp_path),
        health_checker=lambda url: False, launcher=lambda: process)
    registry = QQProcessRegistry(terminator=lambda pid: pytest.fail("PID fallback"))
    manager = QQRuntimeManager(instance, process_registry=registry)
    manager.start()
    process.tree_running = lambda: False
    assert manager.stop().state.value == "stopped"
    assert process.closed
    assert registry.recorded() == ()


def test_cancel_during_injected_launch_also_closes_job():
    registry = QQProcessRegistry()
    process = JobProcess()
    manager = SimpleNamespace(disconnect=lambda: None)
    auth = bridge.QQAuthBridge(manager=manager, process_registry=registry)
    def launch():
        auth.disconnect()
        return process
    auth._window_launcher = launch
    with pytest.raises(bridge.QQAuthWindowUnavailable):
        auth._launch_window()
    assert process.closed


def test_job_close_failure_retains_ownership_for_retry():
    registry = QQProcessRegistry(terminator=lambda pid: pytest.fail("PID fallback"))
    process = JobProcess()
    attempts = []
    def close():
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("fictional close failure")
        process.closed = True
    process.close = close
    registry.record_process(process)
    registry.terminate_all()
    assert registry.recorded() == (48299,)
    registry.terminate_all()
    assert process.closed
    assert registry.recorded() == ()


def test_direct_start_cancelled_before_launcher_returns_closes_late_job(tmp_path):
    executable = tmp_path / "fictional.exe"
    executable.write_text("fictional")
    process = JobProcess()
    def launch():
        instance.stop()
        return process
    instance = runtime.BundledQQRuntime(runtime.QQRuntimeConfig(executable, tmp_path),
        health_checker=lambda url: False, launcher=launch)
    with pytest.raises(runtime.QQChatRuntimeError):
        instance.start()
    assert process.closed
    assert instance.get_info().owned_process is False


def test_failed_launcher_closes_job_before_blocking_log_drain(tmp_path, monkeypatch):
    (tmp_path / "napcat.mjs").write_text("// fictional")
    resources = tmp_path / "resources/app"
    resources.mkdir(parents=True)
    (resources / "package.json").write_text('{"version":"9.9.36-53644","buildVersion":"53644","main":"fake"}')
    (resources / "wrapper.node").write_bytes(b"fictional native resource")
    events = []
    process = JobProcess()
    process.poll = lambda: 7
    def close():
        events.append("close")
        process.closed = True
    def communicate():
        events.append("drain")
        return ("", "")
    process.close = close
    process.communicate = communicate
    monkeypatch.setattr(bridge, "launch_owned_process", lambda *a, **k: process)
    with pytest.raises(bridge.QQAuthWindowUnavailable):
        bridge._launch_auth_window(tmp_path, tmp_path / "fictional.exe", tmp_path / "QQ.exe")
    assert events == ["close", "drain"]


@pytest.mark.slow_integration
@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job API")
@pytest.mark.parametrize("entry", ["runtime", "auth"])
def test_both_qq_entries_close_real_fictional_descendants(tmp_path, monkeypatch, entry):
    from test_windows_job_process import _command, _tree_handles, _dead, _until, _native
    from qq_chat_analyzer.runtime.windows_job import launch_owned_process
    registry = QQProcessRegistry(terminator=lambda pid: pytest.fail("PID fallback"))
    spawned = []
    def launch(args, **options):
        # Substitute only the fictional command; exercise actual native launch
        # with the QQ entry's env/cwd/creationflags/standard streams intact.
        process = launch_owned_process(_command(tmp_path), **options)
        spawned.append(process)
        return process
    handles = []
    try:
        if entry == "runtime":
            executable = tmp_path / "fictional.exe"
            executable.write_text("fictional")
            monkeypatch.setattr(runtime, "launch_owned_process", launch)
            instance = runtime.BundledQQRuntime(runtime.QQRuntimeConfig(executable, tmp_path),
                health_checker=lambda url: False)
            QQRuntimeManager(instance, process_registry=registry).start()
        else:
            (tmp_path / "napcat.mjs").write_text("// fictional")
            resources = tmp_path / "resources/app"
            resources.mkdir(parents=True)
            (resources / "package.json").write_text('{"version":"9.9.36-53644","buildVersion":"53644","main":"fake"}')
            (resources / "wrapper.node").write_bytes(b"fictional native resource")
            monkeypatch.setattr(bridge, "launch_owned_process", launch)
            process = bridge._launch_auth_window(tmp_path, tmp_path / "fictional.exe",
                                                  tmp_path / "QQ.exe")
            registry.record_process(process)
        handles = _tree_handles(tmp_path)
        assert spawned[0].tree_running()
        registry.terminate_all()
        _until(lambda: _dead(handles))
        assert registry.recorded() == ()
    finally:
        for process in spawned:
            process.close()
        for handle in handles:
            _native().CloseHandle(handle)
