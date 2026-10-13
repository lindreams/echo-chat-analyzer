"""R2.1 tree evidence: deterministic faults and fictional Windows processes."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import io
import os
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
def source_isolation(monkeypatch):
    import qq_chat_analyzer

    assert Path(qq_chat_analyzer.__file__).resolve() == ROOT / "src/qq_chat_analyzer/__init__.py"
    assert Path(keys.__file__).resolve() == ROOT / "src/qq_chat_analyzer/application/wechat/wechat_key_service.py"
    assert Path(jobs.__file__).resolve() == ROOT / "src/qq_chat_analyzer/runtime/windows_job.py"
    monkeypatch.delenv(keys.KEY_ENVIRONMENT_VARIABLE, raising=False)


class Clock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class Tree:
    def __init__(self, counts, *, clock=None, query_cost=0, stop_cost=0, stop=True):
        self.counts = iter(counts)
        self.last = 1
        self.clock = clock
        self.query_cost, self.stop_cost = query_cost, stop_cost
        self.stop = stop
        self.stops = 0
        self.queries = 0
        self.returncode = 0
        self.stdout, self.stderr = io.StringIO("ab12" * 16), io.StringIO()
        self.close_calls = 0

    def active_process_count(self):
        self.queries += 1
        if self.clock:
            self.clock.sleep(self.query_cost)
        self.last = next(self.counts, self.last)
        if isinstance(self.last, Exception):
            raise self.last
        return self.last

    def terminate_tree(self):
        self.stops += 1
        if self.clock:
            self.clock.sleep(self.stop_cost)
        if isinstance(self.stop, Exception):
            raise self.stop
        return self.stop

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        pytest.fail("tree proof used kill-on-close instead of retained Job")

    def close(self):
        self.close_calls += 1
        self.stdout.close()
        self.stderr.close()

    @property
    def closed(self):
        return self.stdout.closed and self.stderr.closed

    def close_after_readers(self, readers, *, deadline):
        assert not any(reader.is_alive() for reader in readers)
        self.close()


def service(clock=None):
    clock = clock or Clock()
    return keys.WeChatKeyService(monotonic=clock.now, sleep=clock.sleep)


@pytest.mark.parametrize("counts,stop,want,stops", [
    ([0], True, Status.SUCCESS, 0),
    ([2, 1, 0], True, Status.SUCCESS, 1),
    ([None], True, Status.UNKNOWN, 0),
    ([OSError("fictional query failure")], True, Status.UNKNOWN, 0),
    ([2, OSError("fictional post-stop query failure")], True, Status.UNKNOWN, 1),
    ([2, None], True, Status.UNKNOWN, 1),
    ([2], False, Status.UNKNOWN, 1),
    ([2], OSError("fictional termination failure"), Status.FAILED, 1),
    ([2, 2], True, Status.TIMED_OUT, 1),
])
def test_tree_exit_evidence(counts, stop, want, stops):
    clock = Clock()
    tree = Tree(counts, stop=stop)
    assert service(clock)._release_helper_tree(tree, deadline=0.2) is want
    assert tree.stops == stops
    assert clock.value <= 0.2
    assert tree.close_calls == 0


@pytest.mark.parametrize("query_cost,stop_cost", [(0.08, 0.11), (0, 0.21), (0.21, 0)])
def test_tree_operations_share_absolute_deadline(query_cost, stop_cost):
    clock = Clock()
    tree = Tree([1, 0], clock=clock, query_cost=query_cost, stop_cost=stop_cost)
    assert service(clock)._release_helper_tree(tree, deadline=0.2) is Status.TIMED_OUT
    assert tree.close_calls == 0
    assert clock.value < 0.4  # A restarted post-stop budget would exceed this.


@pytest.mark.parametrize("counts,reason", [
    ([None], "job_closed"),
    ([OSError("fictional query failure")], "query_failed"),
])
def test_unknown_tree_proof_distinguishes_closed_job_from_query_failure(caplog, counts, reason):
    assert service()._release_helper_tree(Tree(counts), deadline=1) is Status.UNKNOWN
    assert f"tree_exit_status=unknown reason={reason}" in caplog.text
    assert "fictional query failure" not in caplog.text


@pytest.mark.parametrize("counts,want", [([0], Status.SUCCESS), ([None], Status.UNKNOWN)])
def test_release_records_tree_proof_before_close(counts, want):
    instance = service()
    tree = Tree(counts)
    instance._helper_process = tree
    instance._used = True
    instance._release_helper(tree, [], True)
    assert instance.helper_tree_status is want
    assert tree.close_calls == (1 if want is Status.SUCCESS else 0)
    assert (instance._helper_process is None) == (want is Status.SUCCESS)
    assert instance.shutdown() is Status.UNKNOWN


def test_returncode_none_cannot_grant_key_or_release_evidence():
    instance = service()
    tree = Tree([None])
    tree.returncode = None
    instance._process_launcher = lambda *_a, **_k: tree
    with pytest.raises(keys.WeChatKeyUnavailable) as error:
        instance._run_helper_streaming(["fictional"], {"timeout": 1}, None, 1)
    assert error.value.code == "wechat_helper_exit_unknown"
    assert instance.helper_tree_status is Status.UNKNOWN
    assert instance._helper_process is tree
    assert tree.close_calls == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows production launcher")
@pytest.mark.parametrize("launch_fails", [False, True])
def test_windows_default_launcher_owns_helper_without_fallback(monkeypatch, launch_fails):
    tree = Tree([0])
    calls = []

    def launch(command, **options):
        calls.append((command, options))
        if launch_fails:
            raise OSError("fictional Job creation failure")
        return tree

    monkeypatch.setattr(keys, "launch_owned_process", launch, raising=False)
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("unowned fallback"))
    instance = service()
    if launch_fails:
        with pytest.raises(keys.WeChatKeyUnavailable):
            instance._run_helper_streaming(["fictional"], {"timeout": 1}, None, 1)
    else:
        assert instance._run_helper_streaming(["fictional"], {"timeout": 1}, None, 1) == "ab12" * 16
        assert instance.helper_tree_status is Status.SUCCESS
    assert len(calls) == 1
    assert calls[0][1]["stdin"] == subprocess.DEVNULL


class Kernel:
    def __init__(self):
        self.count = 2
        self.calls = []

    def QueryInformationJobObject(self, handle, kind, output, size, unused):
        self.calls.append(("query", handle))
        assert handle == 222 and kind == 1
        ctypes.cast(output, ctypes.POINTER(jobs._Accounting)).contents.ActiveProcesses = self.count
        return 1

    def TerminateJobObject(self, handle, code):
        self.calls.append(("stop", handle))
        assert handle == 222
        self.count = 0
        return 1

    def CloseHandle(self, handle):
        self.calls.append(("close", handle))
        return 1


def job(api):
    info = jobs._ProcessInfo(hProcess=111, dwProcessId=123)
    return jobs.WindowsJobProcess(api, info, 222, ["fictional"], None, None)


def test_new_job_operations_preserve_handle_and_existing_qq_terminate():
    api = Kernel()
    process = job(api)
    assert process.active_process_count() == 2
    assert process.terminate_tree() is True
    assert process.active_process_count() == 0
    assert ("close", 222) not in api.calls
    process.terminate()  # Existing QQ semantics: close Job, do not change it.
    assert process.active_process_count() is None
    assert process.terminate_tree() is False
    assert process.tree_running() is False
    assert api.calls.count(("stop", 222)) == 1
    assert api.calls.count(("close", 222)) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="WinError propagation")
@pytest.mark.parametrize("operation", ["query", "stop"])
def test_job_native_failures_preserve_handle(operation):
    api = Kernel()

    def fail(*_a):
        ctypes.set_last_error(5)
        return 0

    if operation == "query":
        api.QueryInformationJobObject = fail
    else:
        api.TerminateJobObject = fail
    process = job(api)
    with pytest.raises(OSError):
        (process.active_process_count if operation == "query" else process.terminate_tree)()
    assert process._job_handle == 222
    assert ("close", 222) not in api.calls


@pytest.mark.parametrize("operation", ["query", "stop"])
def test_job_close_serializes_with_native_operation(operation):
    api = Kernel()
    entered, release, close_started, closed = (threading.Event() for _ in range(4))
    target = "QueryInformationJobObject" if operation == "query" else "TerminateJobObject"
    original = getattr(api, target)

    def blocked(*args):
        entered.set()
        assert release.wait(5)
        assert ("close", 222) not in api.calls
        return original(*args)

    setattr(api, target, blocked)
    process = job(api)
    native_operation = process.active_process_count if operation == "query" else process.terminate_tree
    outcomes = []

    def run_operation():
        outcomes.append(native_operation())

    def close():
        close_started.set()
        process.terminate()
        closed.set()

    worker = threading.Thread(target=run_operation)
    closer = threading.Thread(target=close)
    try:
        worker.start()
        assert entered.wait(5)
        closer.start()
        assert close_started.wait(5)
        assert not closed.is_set()
    finally:
        release.set()
        if worker.ident is not None:
            worker.join(5)
        if closer.ident is not None:
            closer.join(5)
    assert not worker.is_alive() and not closer.is_alive()
    assert outcomes == ([2] if operation == "query" else [True])
    assert process.active_process_count() is None
    assert service()._release_helper_tree(process, deadline=1) is Status.UNKNOWN


def _until(predicate):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("fictional helper did not reach expected state")


def _native():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, args, result in [
        ("OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
        ("WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        ("IsProcessInJob", [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
    ]:
        function = getattr(api, name)
        function.argtypes, function.restype = args, result
    return api


def _worker_command(role, directory):
    return [sys.executable, str(Path(__file__).resolve()), "--fictional-worker", role, str(directory)]


@pytest.mark.slow_integration
@pytest.mark.skipif(sys.platform != "win32", reason="real Windows Job handles")
@pytest.mark.parametrize("role", ["normal", "parent-exits", "cancel"])
def test_native_helper_tree_and_unassociated_external_process(tmp_path, monkeypatch, role):
    assert hasattr(jobs.WindowsJobProcess, "active_process_count")
    external_dir = tmp_path / "external"
    external_dir.mkdir()
    external = subprocess.Popen(_worker_command("leaf", external_dir),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    api = _native()
    handles, owned, outcomes = [], [], []
    real_launch = jobs.launch_owned_process
    instance = keys.WeChatKeyService(dll_path=tmp_path / "wx_key.dll",
                                    helper_path=tmp_path / "helper.cjs")
    instance._dll_path.write_bytes(b"fictional")
    instance._helper_path.write_text("fictional", encoding="utf-8")
    snapshots = iter([[], [4242]])
    instance._process_finder = lambda: next(snapshots, [4242])
    instance._build_helper_invocation = lambda _budget: (
        [*_worker_command(role, tmp_path), "--timeout-ms", "8000"],
        dict(timeout=8, text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW))

    def launch(*args, **options):
        process = real_launch(*args, **options)
        owned.append(process)
        return process

    monkeypatch.setattr(keys, "launch_owned_process", launch, raising=False)
    proof_snapshots = []
    real_proof = instance._release_helper_tree

    def proof(process, *, deadline):
        status = real_proof(process, deadline=deadline)
        proof_snapshots.append((deadline, status, process.active_process_count(),
                                [api.WaitForSingleObject(handle, 0) for handle in handles]))
        return status

    instance._release_helper_tree = proof

    def acquire():
        try:
            outcomes.append(instance.acquire())
        except Exception as error:
            outcomes.append(error)

    worker = threading.Thread(target=acquire)
    try:
        worker.start()
        names = [(tmp_path, "root.pid"), (external_dir, "leaf.pid")]
        if role != "normal":
            names.append((tmp_path, "leaf.pid"))
        for directory, name in names:
            path = directory / name
            _until(lambda: path.exists() and path.stat().st_size)
            handle = api.OpenProcess(0x100000 | 0x1000, False, int(path.read_text()))
            assert handle
            handles.append(handle)
        process = owned[0]
        for index, handle in enumerate(handles):
            member = wintypes.BOOL()
            assert api.IsProcessInJob(handle, process._job_handle, ctypes.byref(member))
            assert bool(member.value) == (index != 1)
        if role == "cancel":
            instance.cancel()
        else:
            (tmp_path / "root-exit").write_text("fictional release")
        worker.join(8)
        assert not worker.is_alive()
        assert instance.helper_tree_status is Status.SUCCESS
        assert instance.shutdown() is Status.UNKNOWN
        # Job accounting can reach zero before the individual process objects
        # become signaled. Confirm their exit within the SAME release deadline,
        # using retained handles, never a PID disappearance or a new wait budget.
        deadline = proof_snapshots[0][0]
        for index, handle in enumerate(handles):
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            assert api.WaitForSingleObject(handle, 0 if index == 1 else remaining_ms) == (
                258 if index == 1 else 0), (index, proof_snapshots)
        assert time.monotonic() < deadline
        assert external.poll() is None
        if role == "cancel":
            assert outcomes[0].code == "wechat_key_cancelled"
        else:
            assert outcomes == ["ab12" * 16]
    finally:
        instance.cancel()
        (tmp_path / "root-exit").write_text("fictional cleanup")
        for process in owned:
            process.close()
        if worker.ident is not None:
            worker.join(8)
        external.terminate()
        external.wait(timeout=8)
        for handle in handles:
            api.CloseHandle(handle)


@pytest.mark.slow_integration
@pytest.mark.skipif(sys.platform != "win32", reason="real Windows Job close")
def test_native_closed_job_is_unknown_even_after_root_handle_signals():
    process = jobs.launch_owned_process([sys.executable, "-c", "import time; time.sleep(20)"],
                                        creationflags=subprocess.CREATE_NO_WINDOW)
    api = _native()
    handle = api.OpenProcess(0x100000 | 0x1000, False, process.pid)
    assert handle
    try:
        assert process.active_process_count() > 0
        process.terminate()  # Retains QQ's close-on-terminate behavior.
        assert process.active_process_count() is None
        assert service()._release_helper_tree(process, deadline=1) is Status.UNKNOWN
        assert api.WaitForSingleObject(handle, 3000) == 0
        assert process.active_process_count() is None
        assert service()._release_helper_tree(process, deadline=1) is Status.UNKNOWN
    finally:
        process.close()
        api.CloseHandle(handle)


def _fictional_worker(role, directory):
    import qq_chat_analyzer

    assert Path(qq_chat_analyzer.__file__).resolve() == ROOT / "src/qq_chat_analyzer/__init__.py"
    assert Path(jobs.__file__).resolve() == ROOT / "src/qq_chat_analyzer/runtime/windows_job.py"
    if role not in ("normal", "leaf"):
        subprocess.Popen(_worker_command("leaf", directory), stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    name = "leaf.pid" if role == "leaf" else "root.pid"
    (directory / name).write_text(str(os.getpid()))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if role in ("normal", "parent-exits") and (directory / "root-exit").exists():
            print("ab12" * 16, flush=True)
            return
        time.sleep(0.02)


if __name__ == "__main__" and sys.argv[1] == "--fictional-worker":
    _fictional_worker(sys.argv[2], Path(sys.argv[3]))
