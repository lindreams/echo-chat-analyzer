"""R2.2 cleanup deadlines and retained ownership; fictional resources only."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from contextlib import ExitStack
import io
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from qq_chat_analyzer.application.shutdown_models import ShutdownStatus as Status
from qq_chat_analyzer.application.wechat import wechat_key_service as keys
from qq_chat_analyzer.runtime import windows_job as jobs

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolate_source(monkeypatch):
    import qq_chat_analyzer
    assert Path(qq_chat_analyzer.__file__).resolve() == ROOT / "src/qq_chat_analyzer/__init__.py"
    assert Path(keys.__file__).resolve() == ROOT / "src/qq_chat_analyzer/application/wechat/wechat_key_service.py"
    assert Path(jobs.__file__).resolve() == ROOT / "src/qq_chat_analyzer/runtime/windows_job.py"
    monkeypatch.delenv(keys.KEY_ENVIRONMENT_VARIABLE, raising=False)


class Clock:
    value = 0.0
    def now(self):
        return self.value
    def sleep(self, seconds):
        self.value += seconds


class Stream(io.StringIO):
    def __init__(self, text=""):
        super().__init__(text)
        self.closes = 0
    def close(self):
        self.closes += 1
        super().close()


class Process:
    def __init__(self, clock=None):
        self.clock = clock
        self.returncode = 0
        self.stdout, self.stderr = Stream("ab12" * 16), Stream()
        self.deadlines, self.waits = [], []
        self.closed = False
        self.stops = 0
        self.close_error = False
    def active_process_count(self):
        return 0
    def terminate_tree(self):
        self.stops += 1
        return True
    def wait(self, timeout=None):
        self.waits.append(timeout)
        return self.returncode
    def close_after_readers(self, readers, *, deadline):
        assert not any(reader.is_alive() for reader in readers)
        self.deadlines.append(deadline)
        if self.close_error:
            raise OSError("fictional close failure")
        for stream in (self.stdout, self.stderr):
            if not stream.closed:
                stream.close()
        self.closed = True
    def close(self):
        pytest.fail("unbounded close/communicate path")


def instance(clock=None):
    return keys.WeChatKeyService(**({"monotonic": clock.now, "sleep": clock.sleep} if clock else {}))


def own(service, process, readers=()):
    service._helper_process = process
    service._helper_readers = tuple(readers)
    service._used = True


class BudgetReader:
    ident = 1
    def __init__(self, clock, cost):
        self.clock, self.cost = clock, cost
        self.waits = []
    def join(self, timeout=None):
        self.waits.append(timeout)
        self.clock.sleep(min(self.cost, timeout))
    def is_alive(self):
        return False


def test_entire_release_passes_one_deadline_and_remaining_join_budget():
    clock = Clock()
    service, process = instance(clock), Process(clock)
    first, second = BudgetReader(clock, 0.8), BudgetReader(clock, 0.4)
    own(service, process, [first, second])
    proof_deadlines = []
    def proof(_process, *, deadline):
        proof_deadlines.append(deadline)
        clock.sleep(0.6)
        return Status.SUCCESS
    service._release_helper_tree = proof
    service._release_helper(process, [first, second], True)
    assert proof_deadlines == process.deadlines
    assert first.waits == [pytest.approx(2.4)]
    assert second.waits == [pytest.approx(1.6)]
    assert service.helper_resource_status is Status.SUCCESS
    assert process.closed and process.stdout.closed and process.stderr.closed
    assert service.shutdown() is Status.UNKNOWN


def test_budget_exhaustion_never_starts_a_new_release_window():
    clock = Clock()
    service, process = instance(clock), Process(clock)
    reader = BudgetReader(clock, 20)
    own(service, process, [reader])
    service._release_helper(process, [reader], True)
    assert clock.value == pytest.approx(3)
    assert process.deadlines == []
    assert service.helper_resource_status is Status.TIMED_OUT
    assert service._helper_process is process


def test_blocked_reader_retained_then_retry_without_double_close(monkeypatch):
    monkeypatch.setattr(keys, "_HELPER_RELEASE_SECONDS", 0.04, raising=False)
    entered, release = threading.Event(), threading.Event()
    def read():
        entered.set()
        assert release.wait(5)
    reader = threading.Thread(target=read)
    reader.start()
    service, process = instance(), Process()
    own(service, process, [reader])
    try:
        assert entered.wait(5)
        service._release_helper(process, [reader], True)
        assert service.helper_resource_status is Status.TIMED_OUT
        assert service._helper_process is process
        assert service._helper_readers == (reader,)
        assert not process.stdout.closed and not process.stderr.closed
        release.set()
        assert service.retry_cleanup() is Status.SUCCESS
        assert service._helper_process is None
        assert service.retry_cleanup() is Status.SUCCESS
        assert process.stdout.closes == process.stderr.closes == 1
    finally:
        release.set()
        reader.join(5)


def test_never_join_unstarted_reader():
    reader = threading.Thread(target=lambda: None)
    service, process = instance(), Process()
    own(service, process, [reader])
    service._release_helper(process, [reader], True)
    assert service.helper_resource_status is Status.SUCCESS
    assert process.closed


def test_attempt_cancel_before_admission_never_starts_and_next_attempt_can_connect(monkeypatch):
    service = instance()
    cancelled = threading.Event()
    cancelled.set()
    calls = []
    monkeypatch.setattr(service, "_acquire_key", lambda *_: calls.append(1) or "ab12" * 16)
    with pytest.raises(keys.WeChatKeyUnavailable) as error:
        service.acquire(cancel_event=cancelled)
    assert error.value.code == "wechat_key_cancelled"
    assert calls == []
    assert service.acquire(cancel_event=threading.Event()) == "ab12" * 16
    assert cancelled.is_set()  # Never clear the previous attempt's signal.


def test_normal_output_with_failed_release_is_not_a_successful_connection():
    process = Process()
    process.close_error = True
    service = keys.WeChatKeyService(process_launcher=lambda *_args, **_options: process)
    with pytest.raises(keys.WeChatKeyUnavailable) as error:
        service._run_helper_streaming(["fictional", "--timeout-ms", "3000"],
                                     {"timeout": 3}, None, time.monotonic() + 3)
    assert error.value.code == "wechat_helper_cleanup_incomplete"
    assert service.helper_resource_status is Status.FAILED
    assert service._helper_process is process
    process.close_error = False
    assert service.retry_cleanup() is Status.SUCCESS


def test_user_reconnect_retries_retained_cleanup_before_new_acquisition(tmp_path, monkeypatch):
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
    from qq_chat_analyzer.application.wechat.wechat_setup_service import WeChatSetupService
    from qq_chat_analyzer.application.wechat.wechat_environment_config import WeChatEnvironmentConfigLoader, WeChatEnvironmentConfigWriter
    service, process = instance(), Process()
    process.close_error = True
    own(service, process)
    assert service._release_helper(process, [], True) is Status.FAILED
    process.close_error = False
    def next_acquire(*_):
        assert process.closed and service._helper_process is None
        return "ab12" * 16
    monkeypatch.setattr(service, "_acquire_key", next_acquire)
    target = tmp_path / "fictional-reconnect.json"
    facade = ChatAnalyzerFacade(wechat_setup_service=WeChatSetupService(key_service=service,
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target)))
    assert facade.acquire_wechat_db_key(cancel_event=threading.Event()) == "ab12" * 16
    assert process.stdout.closes == process.stderr.closes == 1
    assert not facade.shutdown().can_apply_update


def test_background_shutdown_waits_for_owner_but_never_takes_its_resources(monkeypatch):
    service, process = instance(), Process()
    entered, release, closing = threading.Event(), threading.Event(), threading.Event()
    outcomes = []
    def acquire(*_):
        own(service, process)
        entered.set()
        assert release.wait(5)
        service._release_helper(process, [], True)
        service._check_cancelled()
        return "ab12" * 16
    monkeypatch.setattr(service, "_acquire_key", acquire)
    def run():
        try:
            service.acquire()
        except keys.WeChatKeyUnavailable as error:
            outcomes.append(error.code)
        except Exception as error:
            outcomes.append(error)
    worker = threading.Thread(target=run)
    worker.start()
    def close():
        closing.set()
        try:
            outcomes.append(service.shutdown(timeout=1))
        except Exception as error:
            outcomes.append(error)
    shutdown = threading.Thread(target=close)
    try:
        assert entered.wait(5)
        shutdown.start()
        assert closing.wait(5)
        assert service._cancel_event.wait(1)
        assert shutdown.is_alive()
        assert not process.closed
        release.set()
        shutdown.join(2)
        worker.join(2)
        assert not shutdown.is_alive() and not worker.is_alive()
        assert "wechat_key_cancelled" in outcomes and Status.UNKNOWN in outcomes
        assert process.closed and service._helper_process is None
    finally:
        release.set()
        worker.join(5)
        if shutdown.ident is not None:
            shutdown.join(5)


def test_close_error_can_retry_under_the_same_owner():
    service, process = instance(), Process()
    process.close_error = True
    own(service, process)
    service._release_helper(process, [], True)
    assert service.helper_resource_status is Status.FAILED
    assert service._helper_process is process
    with pytest.raises(keys.WeChatKeyUnavailable) as busy:
        service.acquire()
    assert busy.value.code == "wechat_key_busy"
    process.close_error = False
    assert service.retry_cleanup() is Status.SUCCESS
    assert len(process.deadlines) == 2
    assert process.stdout.closes == process.stderr.closes == 1


def test_concurrent_shutdown_and_retry_do_not_compete_for_release():
    service, process = instance(), Process()
    own(service, process)
    entered, release = threading.Event(), threading.Event()
    original = process.close_after_readers
    def blocked(readers, *, deadline):
        entered.set()
        assert release.wait(max(0, deadline - time.monotonic()))
        original(readers, deadline=deadline)
    process.close_after_readers = blocked
    results = []
    retry_cleanup = service.retry_cleanup
    worker = threading.Thread(target=lambda: results.append(retry_cleanup()))
    try:
        worker.start()
        assert entered.wait(5)
        barrier = threading.Barrier(3)
        contenders = []
        def contend(action):
            barrier.wait(5)
            contenders.append(action())
        close = threading.Thread(target=contend, args=(service.shutdown,))
        retry = threading.Thread(target=contend, args=(service.retry_cleanup,))
        close.start()
        retry.start()
        barrier.wait(5)
        close.join(5)
        retry.join(5)
        assert contenders == [Status.UNKNOWN, Status.UNKNOWN]
    finally:
        release.set()
        worker.join(5)
    assert results == [Status.SUCCESS]
    assert process.stdout.closes == process.stderr.closes == 1
    assert service.shutdown() is Status.UNKNOWN


class Kernel:
    def __init__(self):
        self.closed_handles = []
        self.fail_handle = None
    def WaitForSingleObject(self, handle, timeout):
        return 0
    def GetExitCodeProcess(self, handle, output):
        ctypes.cast(output, ctypes.POINTER(wintypes.DWORD)).contents.value = 0
        return 1
    def QueryInformationJobObject(self, handle, kind, output, size, unused):
        ctypes.cast(output, ctypes.POINTER(jobs._Accounting)).contents.ActiveProcesses = 0
        return 1
    def CloseHandle(self, handle):
        if handle == self.fail_handle:
            raise OSError("fictional handle close failure")
        self.closed_handles.append(handle)
        return 1


def job(api):
    process = jobs.WindowsJobProcess(api, jobs._ProcessInfo(hProcess=111, dwProcessId=123),
                                     222, ["fictional"], Stream(), Stream())
    process._stream_resources = ExitStack()
    return process


def test_atexit_helper_never_starts_competing_pipe_readers(monkeypatch):
    release, stdout_entered = threading.Event(), threading.Event()

    class ExitKernel(Kernel):
        def WaitForSingleObject(self, handle, timeout):
            return 0 if release.is_set() else 258

        def CloseHandle(self, handle):
            result = super().CloseHandle(handle)
            if handle == 222:
                release.set()
            return result

    class ExternalStream(Stream):
        competing_reads = 0

        def readline(self):
            stdout_entered.set()
            assert release.wait(5)
            return super().readline()

        def read(self, *args):
            self.competing_reads += 1
            return ""

    api = ExitKernel()
    process = job(api)
    process.stdout = ExternalStream("ab12" * 16)
    process.stderr = Stream("[KEY_HELPER_READY]\n")
    # Use the production launcher selection so reader ownership must cross it.
    launch_options = []
    def launch(*args, **options):
        launch_options.append(options)
        return process
    monkeypatch.setattr(keys, "launch_owned_process", launch)
    monkeypatch.setattr(jobs, "_LIVE", {process})
    service = instance()
    outcomes = []
    def acquire():
        try:
            outcomes.append(service._run_helper_streaming(["fictional"],
                {"timeout": 5}, None, time.monotonic() + 5))
        except Exception as error:
            outcomes.append(error)
    worker = threading.Thread(target=acquire)
    try:
        worker.start()
        assert stdout_entered.wait(5)
        jobs._shutdown_owned_jobs()
        worker.join(5)
        assert not worker.is_alive()
        assert process.stdout.competing_reads == 0
        assert process._readers is None
        assert process.closed and process.stdout.closed and process.stderr.closed
        assert sorted(api.closed_handles) == [111, 222]
        assert process.stdout.closes == process.stderr.closes == 1
        jobs._shutdown_owned_jobs()
        process.close()
        assert sorted(api.closed_handles) == [111, 222]
        assert process.stdout.closes == process.stderr.closes == 1
        assert launch_options[0]["external_readers"] is True
    finally:
        release.set()
        worker.join(5)


def test_external_reader_exit_timeout_reclaims_handles_and_retains_live_pipes(monkeypatch):
    api, release = Kernel(), threading.Event()
    process = job(api)
    reader = threading.Thread(target=lambda: release.wait(5))
    process.set_external_readers([reader])
    monkeypatch.setattr(jobs, "_LIVE", {process})
    reader.start()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            process._close_external_readers(deadline=time.monotonic() + 0.03)
        assert sorted(api.closed_handles) == [111, 222]
        assert not process.stdout.closed and not process.stderr.closed
        assert process._readers is None
        assert process in jobs._LIVE  # PIPE ownership survives the timed-out join.
        release.set()
        reader.join(5)
        process.close()
        process.close()
        assert process not in jobs._LIVE
        assert sorted(api.closed_handles) == [111, 222]
        assert process.stdout.closes == process.stderr.closes == 1
    finally:
        release.set()
        reader.join(5)


@pytest.mark.slow_integration
@pytest.mark.skipif(sys.platform != "win32", reason="Windows native resources")
def test_native_atexit_joins_external_readers_without_communicate(monkeypatch):
    process = jobs.launch_owned_process(
        [sys.executable, "-c", "import sys,time; print('fictional', flush=True); time.sleep(20)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, external_readers=True)
    monkeypatch.setattr(jobs, "_LIVE", {process})
    entered = threading.Event()
    output = []
    def read():
        output.append(process.stdout.readline())
        entered.set()
        output.append(process.stdout.read())
    readers = [threading.Thread(target=read),
               threading.Thread(target=lambda: process.stderr.read())]
    process.set_external_readers(readers)
    try:
        for reader in readers:
            reader.start()
        assert entered.wait(5)
        jobs._shutdown_owned_jobs()
        assert all(not reader.is_alive() for reader in readers)
        assert output[0] == "fictional\n"
        assert process._readers is None
        assert process.closed and process.stdout.closed and process.stderr.closed
        assert process not in jobs._LIVE
        process.close()
    finally:
        process.close()
        for reader in readers:
            if reader.ident is not None:
                reader.join(5)


@pytest.mark.parametrize("failed_handle", [111, 222])
def test_handle_close_failure_retains_only_failed_handle_and_retry(failed_handle):
    api = Kernel()
    api.fail_handle = failed_handle
    process = job(api)
    with pytest.raises(OSError):
        process.close_after_readers([], deadline=time.monotonic() + 1)
    assert not process.closed
    assert failed_handle not in api.closed_handles
    api.fail_handle = None
    process.close_after_readers([], deadline=time.monotonic() + 1)
    assert process.closed
    assert api.closed_handles.count(111) == api.closed_handles.count(222) == 1
    assert process.stdout.closes == process.stderr.closes == 1
    assert process._readers is None


def test_pipe_close_failure_releases_other_resources_then_skips_completed_closes():
    api = Kernel()
    process = job(api)
    service = instance()
    own(service, process)
    original = process.stdout.close
    failed = True
    def close():
        if failed:
            raise OSError("fictional PIPE close failure")
        original()
    process.stdout.close = close
    try:
        assert service._release_helper(process, [], False) is Status.FAILED
        assert not process.stdout.closed and process.stderr.closed
        assert service._helper_process is process
        assert process._process_handle is None and process._job_handle is None
        failed = False
        assert service.retry_cleanup() is Status.SUCCESS
        assert service._helper_process is None
        assert process.stdout.closes == process.stderr.closes == 1
        assert api.closed_handles.count(111) == api.closed_handles.count(222) == 1
    finally:
        io.StringIO.close(process.stdout)


def test_successful_close_call_without_closed_pipe_stays_unknown():
    service, process = instance(), Process()
    own(service, process)
    original = process.stdout.close
    process.stdout.close = lambda: None
    try:
        assert service._release_helper(process, [], True) is Status.UNKNOWN
        assert service._helper_process is process
        process.stdout.close = original
        assert service.retry_cleanup() is Status.SUCCESS
        assert process.stderr.closes == 1
    finally:
        io.StringIO.close(process.stdout)


def test_native_resource_api_does_not_compete_with_live_reader():
    api = Kernel()
    process = job(api)
    release = threading.Event()
    reader = threading.Thread(target=lambda: release.wait(5))
    reader.start()
    try:
        with pytest.raises(RuntimeError):
            process.close_after_readers([reader], deadline=time.monotonic() + 1)
        assert api.closed_handles == []
        assert not process.stdout.closed
    finally:
        release.set()
        reader.join(5)


def test_close_lock_wait_uses_callers_deadline():
    process = job(Kernel())
    entered, release = threading.Event(), threading.Event()
    def hold():
        with process._close_lock:
            entered.set()
            release.wait(5)
    worker = threading.Thread(target=hold)
    worker.start()
    try:
        assert entered.wait(5)
        with pytest.raises(subprocess.TimeoutExpired):
            process.close_after_readers([], deadline=time.monotonic() + 0.03)
        assert not process.closed
    finally:
        release.set()
        worker.join(5)


@pytest.mark.slow_integration
@pytest.mark.skipif(sys.platform != "win32", reason="Windows native resources")
@pytest.mark.parametrize("role", ["normal", "error", "cancel", "timeout", "close", "cancel-reconnect", "release-failure"])
def test_real_dual_pipe_helper_release_and_source_isolation(tmp_path, monkeypatch, role):
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, FacadeError
    from qq_chat_analyzer.application.wechat.wechat_setup_service import WeChatSetupService
    from qq_chat_analyzer.application.wechat.wechat_environment_config import WeChatEnvironmentConfigLoader, WeChatEnvironmentConfigWriter
    assert hasattr(jobs.WindowsJobProcess, "close_after_readers")
    owned, outcomes = [], []
    original = jobs.launch_owned_process
    def launch(*args, **options):
        process = original(*args, **options)
        owned.append(process)
        return process
    monkeypatch.setattr(keys, "launch_owned_process", launch)
    service = keys.WeChatKeyService(dll_path=tmp_path / "wx_key.dll", helper_path=tmp_path / "helper.cjs")
    target = tmp_path / "fictional-config.json"
    facade = ChatAnalyzerFacade(wechat_setup_service=WeChatSetupService(key_service=service,
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target)))
    cancel_event = threading.Event()
    service._dll_path.write_bytes(b"fictional")
    service._helper_path.write_text("fictional")
    snapshots = iter([[], [4242]])
    service._process_finder = lambda: next(snapshots, [4242])
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", role, str(tmp_path),
               "--timeout-ms", "8000"]
    service._build_helper_invocation = lambda _budget: (command, dict(timeout=8, text=True, encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW))
    def acquire():
        try:
            if role == "timeout":
                outcomes.append(service.acquire(timeout=1, cancel_event=cancel_event))
            else:
                outcomes.append(facade.acquire_wechat_db_key(cancel_event=cancel_event))
        except Exception as error:
            outcomes.append(error)
    worker = threading.Thread(target=acquire)
    try:
        worker.start()
        until = time.monotonic() + 5
        while not (tmp_path / "ready").exists() and time.monotonic() < until:
            time.sleep(0.01)
        assert (tmp_path / "ready").exists()
        process = owned[0]
        bounded_close = process.close_after_readers
        if role == "release-failure":
            def failed_close(*_args, **_options):
                raise OSError("fictional native release failure")
            process.close_after_readers = failed_close
        if role in ("cancel", "cancel-reconnect"):
            facade.cancel_wechat_connection(cancel_event)
        elif role == "close":
            result = facade.shutdown()  # Background owner in production.
            assert not result.can_apply_update
            assert result.status is Status.UNKNOWN
        elif role in ("normal", "error", "release-failure"):
            (tmp_path / "go").write_text("fictional release")
        worker.join(6)
        assert not worker.is_alive()
        if role == "release-failure":
            assert outcomes[0].code == "wechat_helper_cleanup_incomplete"
            assert service.helper_resource_status is Status.FAILED
            assert service._helper_process is process
            assert not target.exists()
            failure_result = facade.shutdown()
            assert failure_result.status is Status.FAILED
            assert not failure_result.can_apply_update
            process.close_after_readers = bounded_close
            assert service.retry_cleanup() is Status.SUCCESS
            assert facade.shutdown() is failure_result  # Never launder failure.
        assert service.helper_tree_status is Status.SUCCESS
        assert service.helper_resource_status is Status.SUCCESS
        assert process.stdout.closed and process.stderr.closed and process.closed
        assert process._readers is None  # communicate never acquired a PIPE.
        assert process._process_handle is None and process._job_handle is None
        assert process not in jobs._LIVE
        assert service._helper_process is None and service._helper_readers == ()
        if role == "normal":
            assert outcomes == ["ab12" * 16]
        else:
            assert isinstance(outcomes[0], (keys.WeChatKeyUnavailable, FacadeError))
        if role == "cancel-reconnect":
            assert outcomes[0].code == "wechat_key_cancelled"
            next_dir = tmp_path / "reconnect"
            next_dir.mkdir()
            (next_dir / "go").write_text("fictional release")
            snapshots = iter([[], [4242]])
            next_command = [sys.executable, str(Path(__file__).resolve()), "--worker", "normal", str(next_dir),
                            "--timeout-ms", "8000"]
            service._build_helper_invocation = lambda _budget: (next_command, dict(timeout=8, text=True,
                encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW))
            # Reconnect precedes permanent admission closure on Echo exit.
            assert facade.acquire_wechat_db_key(cancel_event=threading.Event()) == "ab12" * 16
            assert len(owned) == 2 and owned[1].closed
            assert owned[1].stdout.closed and owned[1].stderr.closed
        assert not facade.shutdown().can_apply_update
    finally:
        service.cancel()
        (tmp_path / "go").write_text("fictional cleanup")
        worker.join(6)
        for process in owned:
            process.close()


def _worker(role, directory):
    import qq_chat_analyzer
    assert Path(qq_chat_analyzer.__file__).resolve() == ROOT / "src/qq_chat_analyzer/__init__.py"
    assert Path(jobs.__file__).resolve() == ROOT / "src/qq_chat_analyzer/runtime/windows_job.py"
    assert Path(keys.__file__).resolve() == ROOT / "src/qq_chat_analyzer/application/wechat/wechat_key_service.py"
    print("x" * 160000, file=sys.stderr, flush=True)
    (directory / "ready").write_text("fictional helper")
    end = time.monotonic() + 15
    while not (directory / "go").exists() and time.monotonic() < end:
        time.sleep(0.01)
    if role == "error":
        raise SystemExit(1)
    print("ab12" * 16, flush=True)


if __name__ == "__main__" and sys.argv[1] == "--worker":
    _worker(sys.argv[2], Path(sys.argv[3]))
