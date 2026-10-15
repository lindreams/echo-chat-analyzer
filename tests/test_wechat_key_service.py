"""Behavior tests for the WeChat DB key acquisition service.

No real WeChat process, DLL, or key is touched. Every native call is replaced
by a fake adapter and a fake process finder.
"""

from __future__ import annotations

import importlib
import json
import logging
import io
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _module():
    return importlib.import_module(
        "qq_chat_analyzer.application.wechat.wechat_key_service"
    )


class _FakeHookApi:
    def __init__(
        self,
        *,
        key: str | None = None,
        hook_ok: bool = True,
        poll_raises: bool = False,
    ) -> None:
        self.key = key
        self.hook_ok = hook_ok
        self.poll_raises = poll_raises
        self.initialize_calls: list[int] = []
        self.poll_calls = 0
        self.cleanup_calls = 0

    def initialize(self, pid: int) -> bool:
        self.initialize_calls.append(pid)
        return self.hook_ok

    def poll_key(self, buffer, size: int) -> bool:
        self.poll_calls += 1
        if self.poll_raises:
            raise RuntimeError("native poll exploded with secret")
        if self.key is None:
            return False
        payload = self.key.encode("ascii")
        buffer[: len(payload)] = payload
        return True

    def cleanup(self) -> bool:
        self.cleanup_calls += 1
        return True

    def error_message(self) -> bytes:
        return b"hook denied by wechat process"


def _service(
    tmp_path: Path,
    *,
    api: _FakeHookApi,
    pids: list[int],
    timeout: float = 5.0,
    monotonic=None,
):
    dll_path = tmp_path / "wx_key.dll"
    dll_path.write_bytes(b"fake")
    module = _module()
    snapshots = iter([[], pids])
    elapsed = 0.0

    def sleep(seconds):
        nonlocal elapsed
        elapsed += seconds

    return module.WeChatKeyService(
        dll_path=dll_path,
        process_finder=lambda: next(snapshots, pids),
        dll_loader=lambda _path: api,
        buffer_factory=lambda size: bytearray(size),
        sleep=sleep,
        monotonic=monotonic or (lambda: elapsed),
        timeout=timeout,
    )


def _lifecycle_service(tmp_path, snapshots, *, hook_ok=True, timeout=5.0):
    """Drive process snapshots and elapsed time without real processes."""
    api = _FakeHookApi(key="ab12" * 16, hook_ok=hook_ok)
    service = _service(tmp_path, api=api, pids=[])
    remaining = iter(snapshots)
    current = []
    elapsed = 0.0
    seen = []

    def find():
        nonlocal current
        current = next(remaining, current)
        # No listener may be installed while waiting for process transitions.
        assert api.initialize_calls == []
        assert "READY_FOR_LOGIN" not in seen
        return current

    def sleep(seconds):
        nonlocal elapsed
        elapsed += seconds

    service._process_finder = find
    service._sleep = sleep
    service._monotonic = lambda: elapsed
    service._timeout = timeout
    return service, api, seen


@pytest.mark.parametrize("snapshots, expected", [
    ([[101, 202], [202, 303], [303]], [
        "PREPARING", "WAITING_FOR_WECHAT_EXIT", "WAITING_FOR_WECHAT_START",
        "READY_FOR_LOGIN", "CREDENTIAL_RECEIVED",
    ]),
    ([[], [], [303]], [
        "PREPARING", "WAITING_FOR_WECHAT_START", "READY_FOR_LOGIN",
        "CREDENTIAL_RECEIVED",
    ]),
    ([[101], [], [], [303]], [
        "PREPARING", "WAITING_FOR_WECHAT_EXIT", "WAITING_FOR_WECHAT_START",
        "READY_FOR_LOGIN", "CREDENTIAL_RECEIVED",
    ]),
])
def test_lifecycle_waits_for_new_pid_before_ready(tmp_path, snapshots, expected):
    service, api, seen = _lifecycle_service(tmp_path, snapshots)

    class Listener(_FakeHookApi):
        def initialize(self, pid):
            assert seen[-1] == "WAITING_FOR_WECHAT_START"
            return super().initialize(pid)

        def poll_key(self, buffer, size):
            assert seen[-1] == "READY_FOR_LOGIN"
            return super().poll_key(buffer, size)

    listener = Listener(key=api.key)
    service._dll_loader = lambda _path: listener
    assert service.acquire(progress=lambda event: seen.append(event.name)) == api.key
    assert listener.initialize_calls == [303]
    assert listener.cleanup_calls == 1
    assert seen == expected


def test_lifecycle_failed_new_pid_hook_never_reports_ready(tmp_path):
    service, api, seen = _lifecycle_service(tmp_path, [[], [303]], hook_ok=False)
    with pytest.raises(_module().WeChatKeyUnavailable) as caught:
        service.acquire(progress=lambda event: seen.append(event.name))
    assert caught.value.code == "wechat_hook_failed"
    assert api.initialize_calls == [303]
    assert api.poll_calls == 0
    assert seen == ["PREPARING", "WAITING_FOR_WECHAT_START"]


def test_lifecycle_helper_hooks_only_selected_new_pid(tmp_path):
    service, api, seen = _lifecycle_service(tmp_path, [[101], [], [], [303]])
    helper = tmp_path / "wx_key_helper.cjs"
    helper.write_text("", encoding="utf-8")
    service._helper_path = helper
    service._legacy_injected = False
    service._node_finder = lambda _name: "node"

    def launch(command, **_options):
        assert command[command.index("--pid") + 1] == "303"
        assert seen[-1] == "WAITING_FOR_WECHAT_START"
        assert api.initialize_calls == []
        return _FakePopen(stdout=api.key, stderr_lines=("hook_success=true",))

    service._process_launcher = launch
    assert service.acquire(progress=lambda event: seen.append(event.name)) == api.key
    assert seen == [
        "PREPARING", "WAITING_FOR_WECHAT_EXIT", "WAITING_FOR_WECHAT_START",
        "READY_FOR_LOGIN", "CREDENTIAL_RECEIVED",
    ]


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _budget_service(tmp_path, snapshots, mode="native"):
    service, api, seen = _lifecycle_service(tmp_path, snapshots, timeout=1.0)
    clock = _FakeClock()
    service._monotonic = clock
    service._sleep = clock.sleep
    if mode != "native":
        helper = tmp_path / "wx_key_helper.cjs"
        helper.write_text("", encoding="utf-8")
        service._helper_path = helper
        service._node_finder = lambda _name: "node"
        service._legacy_injected = False
    return service, api, seen, clock


@pytest.mark.parametrize("mode", ["native", "streaming"])
def test_smallfix_reused_pid_after_observed_exit_is_new_candidate(tmp_path, mode):
    service, api, seen, clock = _budget_service(tmp_path, [[101], [], [101]], mode)
    calls = []

    def run(command, **_options):
        calls.append(int(command[command.index("--pid") + 1]))
        return _Completed(stdout=api.key)

    if mode == "streaming":
        def launch(command, **options):
            run(command, **options)
            return _FakePopen(stdout=api.key, stderr_lines=("hook_success=true",))
        service._process_launcher = launch

    assert service.acquire(progress=lambda event: seen.append(event.name)) == api.key
    assert (api.initialize_calls if mode == "native" else calls) == [101]
    assert seen[:3] == [
        "PREPARING", "WAITING_FOR_WECHAT_EXIT", "WAITING_FOR_WECHAT_START",
    ]


def test_smallfix_same_pid_without_observed_exit_times_out(tmp_path):
    service, api, seen, clock = _budget_service(tmp_path, [[101], [101]])
    with pytest.raises(_module().WeChatKeyUnavailable) as caught:
        service.acquire(progress=lambda event: seen.append(event.name))
    assert caught.value.code == "wechat_key_timeout"
    assert api.initialize_calls == []
    assert seen == ["PREPARING", "WAITING_FOR_WECHAT_EXIT"]
    assert clock.now == pytest.approx(1.0)


def test_smallfix_native_polling_consumes_remaining_acquire_budget(tmp_path):
    service, api, seen, clock = _budget_service(tmp_path, [[101], [101], [], [], [303]])
    api.key = None
    with pytest.raises(_module().WeChatKeyUnavailable):
        service.acquire()
    assert api.initialize_calls == [303]
    assert clock.now == pytest.approx(1.0)
    assert api.cleanup_calls == 1


@pytest.mark.parametrize("mode", ["buffered", "streaming"])
def test_smallfix_helper_tries_second_pid_with_remaining_budget(tmp_path, mode):
    service, api, seen, clock = _budget_service(tmp_path, [[], [], [101, 202]], mode)
    calls = []

    def run(command, **options):
        pid = int(command[command.index("--pid") + 1])
        budget = int(command[command.index("--timeout-ms") + 1]) / 1000
        calls.append((pid, clock.now, budget, options.get("timeout")))
        if pid == 101:
            clock.sleep(0.1)
            return _Completed(1, stderr="InitializeHook(101) -> false\nkey unavailable")
        return _Completed(stdout=api.key)

    if mode == "buffered":
        service._subprocess_runner = run
    else:
        def launch(command, **options):
            result = run(command, **options)
            return _FakePopen(
                stdout=result.stdout, stderr_lines=tuple(result.stderr.splitlines()),
                returncode=result.returncode,
            )
        service._process_launcher = launch

    assert service.acquire() == api.key
    assert [call[0] for call in calls] == [101, 202]
    assert calls[0][2] == pytest.approx(0.4)
    assert calls[1][2] == pytest.approx(0.7)
    if mode == "buffered":
        assert calls[0][3] <= 0.4
        assert calls[1][3] <= 0.7


def test_smallfix_candidate_seen_after_deadline_is_not_hooked(tmp_path):
    service, api, seen, clock = _budget_service(tmp_path, [[]])
    snapshots = iter([[], [303]])

    def find():
        pids = next(snapshots)
        if pids:
            clock.sleep(1.1)
        return pids

    service._process_finder = find
    with pytest.raises(_module().WeChatKeyUnavailable) as caught:
        service.acquire()
    assert caught.value.code == "wechat_key_timeout"
    assert api.initialize_calls == []


def test_smallfix_hook_consumes_budget_and_cleans_up_without_ready(tmp_path):
    service, api, seen, clock = _budget_service(tmp_path, [[], [101, 202]])

    class Listener(_FakeHookApi):
        def initialize(self, pid):
            clock.sleep(1.1)
            return super().initialize(pid)

    listener = Listener(key=api.key)
    service._dll_loader = lambda _path: listener
    with pytest.raises(_module().WeChatKeyUnavailable) as caught:
        service.acquire(progress=lambda event: seen.append(event.name))
    assert caught.value.code == "wechat_key_timeout"
    assert listener.initialize_calls == [101]
    assert listener.cleanup_calls == 1
    assert listener.poll_calls == 0
    assert seen == ["PREPARING", "WAITING_FOR_WECHAT_START"]


@pytest.mark.parametrize("mode", ["buffered", "streaming"])
def test_smallfix_candidate_timeout_reserves_budget_for_second_pid(tmp_path, mode):
    service, api, seen, clock = _budget_service(tmp_path, [[], [101, 202]], mode)
    calls = []

    if mode == "buffered":
        def run(command, **options):
            pid = int(command[command.index("--pid") + 1])
            calls.append(pid)
            if pid == 101:
                clock.sleep(options["timeout"])
                raise subprocess.TimeoutExpired(command, options["timeout"])
            return _Completed(stdout=api.key)
        service._subprocess_runner = run
    else:
        class Process(_FakePopen):
            def wait(self, timeout=None):
                if not self.killed:
                    clock.sleep(timeout)
                    raise subprocess.TimeoutExpired("node", timeout)
                return 1

        def launch(command, **_options):
            pid = int(command[command.index("--pid") + 1])
            calls.append(pid)
            return Process() if pid == 101 else _FakePopen(stdout=api.key)
        service._process_launcher = launch

    assert service.acquire() == api.key
    assert calls == [101, 202]
    assert clock.now == pytest.approx(0.5)


def test_smallfix_helper_does_not_retry_environment_failure(tmp_path):
    service, api, seen, clock = _budget_service(tmp_path, [[], [101, 202]], "buffered")
    calls = []

    def run(command, **_options):
        calls.append(command)
        return _Completed(1, stderr="Cannot find module 'koffi'")

    service._subprocess_runner = run
    with pytest.raises(_module().WeChatKeyUnavailable) as caught:
        service.acquire()
    assert caught.value.code == "wechat_environment_missing"
    assert len(calls) == 1


def test_zero_acquire_budget_times_out_without_hook(tmp_path: Path) -> None:
    module = _module()
    api = _FakeHookApi(key=None)
    service = _service(tmp_path, api=api, pids=[789], timeout=0.0)

    with pytest.raises(module.WeChatKeyUnavailable) as caught:
        service.acquire()

    assert caught.value.code == "wechat_key_timeout"
    assert api.initialize_calls == []
    assert api.cleanup_calls == 0


def test_poll_exception_does_not_leak(tmp_path: Path) -> None:
    module = _module()
    api = _FakeHookApi(key=None, poll_raises=True)
    service = _service(
        tmp_path,
        api=api,
        pids=[111],
        timeout=1.0,
    )

    with pytest.raises(module.WeChatKeyUnavailable) as caught:
        service.acquire()

    assert caught.value.code == "wechat_key_not_captured"
    assert "native poll exploded with secret" not in caught.value.public_message
    assert "Traceback" not in caught.value.public_message


class _Completed:
    def __init__(self, code=0, stdout="", stderr=""):
        self.returncode = code
        self.stdout = stdout
        self.stderr = stderr


def _helper_service(
    tmp_path: Path,
    result=None,
    runner=None,
    *,
    node_finder=lambda _name: "node",
):
    dll = tmp_path / "wx_key.dll"
    helper = tmp_path / "wx_key_helper.cjs"
    dll.write_bytes(b"fake")
    helper.write_text("", encoding="utf-8")
    module = _module()
    service = module.WeChatKeyService(
        dll_path=dll,
        helper_path=helper,
        subprocess_runner=runner or (lambda *_args, **_kwargs: result),
        node_finder=node_finder,
    )
    snapshots = iter([[], [4242]])
    service._process_finder = lambda: next(snapshots, [4242])
    service._monotonic = lambda: 0.0
    return service


def test_helper_key_unavailable_is_not_captured(tmp_path: Path):
    module = _module()
    service = _helper_service(
        tmp_path,
        _Completed(
            1,
            stderr=(
                "Weixin PIDs: 101, 202\n"
                "InitializeHook(101) -> true\n"
                "key unavailable"
            ),
        ),
    )
    with pytest.raises(module.WeChatKeyUnavailable) as caught:
        service.acquire()
    assert caught.value.code == "wechat_key_not_captured"
    assert "无法获取微信登录密钥" in caught.value.public_message


@pytest.mark.parametrize(
    "install_dir",
    [
        "软件之学习工作/微信/Weixin",
        "we chat install/Weixin",
    ],
)
def test_helper_invocation_preserves_path_characters(
    tmp_path: Path,
    install_dir: str,
) -> None:
    module = _module()
    runtime_dir = tmp_path / install_dir
    runtime_dir.mkdir(parents=True)
    dll = runtime_dir / "wx_key.dll"
    helper = runtime_dir / "wx_key_helper.cjs"
    node = runtime_dir / "node.exe"
    dll.write_bytes(b"fake")
    helper.write_text("", encoding="utf-8")
    node.write_bytes(b"fake")
    service = module.WeChatKeyService(
        dll_path=dll,
        helper_path=helper,
        koffi_module_path=runtime_dir / "node_modules",
        node_finder=lambda _name: str(node),
    )

    command, options = service._build_helper_invocation(30.0)

    assert command == [
        str(node),
        str(helper),
        "--dll",
        str(dll),
        "--timeout-ms",
        "30000",
    ]
    assert options["cwd"] == str(runtime_dir)
    assert options["env"]["NODE_PATH"] == str(runtime_dir / "node_modules")
    assert options.get("shell", False) is False


@pytest.mark.skipif(
    os.name != "nt"
    or not (PROJECT_ROOT / "runtime" / "wechat" / "node.exe").is_file(),
    reason="bundled Windows Node.js is required",
)
def test_node_subprocess_round_trips_chinese_and_space_paths(
    tmp_path: Path,
) -> None:
    module = _module()
    runtime_dir = tmp_path / "软件之学习工作 微信空间" / "Echo Runtime"
    runtime_dir.mkdir(parents=True)
    dll = runtime_dir / "wx_key.dll"
    helper = runtime_dir / "wx_key_helper.cjs"
    dll.write_bytes(b"fake")
    helper.write_text(
        "const path = require('path');"
        "const dll = process.argv[process.argv.indexOf('--dll') + 1];"
        "process.stdout.write(JSON.stringify({ dll: dll, cwd: process.cwd(), "
        "resolved: path.resolve(dll) }) + '\\n');",
        encoding="utf-8",
    )
    node = PROJECT_ROOT / "runtime" / "wechat" / "node.exe"
    service = module.WeChatKeyService(
        dll_path=dll,
        helper_path=helper,
        koffi_module_path=PROJECT_ROOT / "runtime" / "wechat" / "node_modules",
        node_finder=lambda _name: str(node),
    )

    command, options = service._build_helper_invocation(5.0)
    options["capture_output"] = True
    options["check"] = False
    options["timeout"] = 20.0
    result = subprocess.run(command, **options)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["dll"] == str(dll)
    assert payload["resolved"] == str(dll.resolve())
    assert payload["cwd"] == str(runtime_dir)


@pytest.mark.skipif(
    os.name != "nt"
    or not (PROJECT_ROOT / "runtime" / "wechat" / "node.exe").is_file()
    or not (PROJECT_ROOT / "runtime" / "wechat" / "node_modules" / "koffi").is_dir()
    or not (PROJECT_ROOT / "runtime" / "wechat" / "wx_key.dll").is_file(),
    reason="bundled Windows Node.js, koffi and wx_key.dll are required",
)
def test_koffi_loads_dll_from_chinese_and_space_path(tmp_path: Path) -> None:
    module = _module()
    runtime_dir = tmp_path / "软件之学习工作 微信空间"
    runtime_dir.mkdir()
    source_dll = PROJECT_ROOT / "runtime" / "wechat" / "wx_key.dll"
    dll = runtime_dir / "wx_key.dll"
    shutil.copy2(source_dll, dll)
    helper = runtime_dir / "probe.cjs"
    helper.write_text(
        "const koffi = require('koffi');"
        "const dll = process.argv[process.argv.indexOf('--dll') + 1];"
        "const lib = koffi.load(dll);"
        "process.stdout.write(JSON.stringify({ loaded: !!lib, dll: dll }) + '\\n');",
        encoding="utf-8",
    )
    node = PROJECT_ROOT / "runtime" / "wechat" / "node.exe"
    service = module.WeChatKeyService(
        dll_path=dll,
        helper_path=helper,
        koffi_module_path=PROJECT_ROOT / "runtime" / "wechat" / "node_modules",
        node_finder=lambda _name: str(node),
    )

    command, options = service._build_helper_invocation(5.0)
    options["capture_output"] = True
    options["check"] = False
    options["timeout"] = 20.0
    result = subprocess.run(command, **options)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["loaded"] is True
    assert payload["dll"] == str(dll)


def test_helper_prefers_bundled_node_when_system_node_is_unavailable(
    tmp_path: Path,
) -> None:
    calls = []

    def runner(command, **options):
        calls.append((command, options))
        return _Completed(stdout="a" * 64)

    bundled_node = tmp_path / "node.exe"
    bundled_node.write_bytes(b"fictional node")
    service = _helper_service(
        tmp_path,
        runner=runner,
        node_finder=lambda _name: None,
    )

    assert service.acquire() == "a" * 64
    assert calls[0][0][0] == str(bundled_node)


def test_smallfix_native_hook_failure_allows_second_candidate(tmp_path):
    service, api, seen, clock = _budget_service(tmp_path, [[], [101, 202]])

    class Listener(_FakeHookApi):
        def initialize(self, pid):
            clock.sleep(0.25)
            super().initialize(pid)
            return pid == 202

    listener = Listener(key=api.key)
    service._dll_loader = lambda _path: listener
    assert service.acquire() == api.key
    assert listener.initialize_calls == [101, 202]
    assert listener.cleanup_calls == 1
    assert clock.now == pytest.approx(0.5)


@pytest.mark.skipif(
    os.name != "nt"
    or not (PROJECT_ROOT / "runtime" / "wechat" / "node.exe").is_file(),
    reason="bundled Windows Node.js is required",
)
def test_bundled_helper_reaches_process_enumeration_before_dll_load(
    tmp_path: Path,
) -> None:
    invalid_dll = tmp_path / "fictional-invalid.dll"
    invalid_dll.write_bytes(b"not a native library")
    completed = subprocess.run(
        [
            str(PROJECT_ROOT / "runtime" / "wechat" / "node.exe"),
            str(PROJECT_ROOT / "runtime" / "wechat" / "wx_key_helper.cjs"),
            "--dll",
            str(invalid_dll),
            "--pid",
            "1",
            "--timeout-ms",
            "1",
        ],
        cwd=PROJECT_ROOT / "runtime" / "wechat",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode != 0
    stderr = completed.stderr
    markers = [
        "helper_stage=node_start",
        "helper_stage=koffi_load",
        "helper_stage=process_enumeration",
        "process_found=true, process_count=1",
        "helper_stage=dll_load",
    ]
    positions = [stderr.index(marker) for marker in markers]
    assert positions == sorted(positions)


# --------------------------------------------------------------- streaming


class _FakePopen:
    """Minimal Popen stand-in for the streaming helper path."""

    def __init__(
        self,
        *,
        stdout: str = "",
        stderr_lines: tuple[str, ...] = (),
        returncode: int = 0,
        timeout_after: bool = False,
    ) -> None:
        self.stdout = io.StringIO(stdout)
        stderr_text = "".join(line + "\n" for line in stderr_lines)
        self.stderr = io.StringIO(stderr_text)
        self._stderr_size = len(stderr_text)
        self.returncode = returncode
        self._timeout_after = timeout_after
        self.killed = False
        self.waited = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def communicate(self, timeout=None):
        if self._timeout_after:
            import subprocess

            raise subprocess.TimeoutExpired(cmd="node", timeout=timeout or 0)
        # A real helper exits only after its stderr is written; mirror that so
        # the reader thread is not raced by an instant return.
        while self.stderr.tell() < self._stderr_size:
            time.sleep(0.005)
        return self.stdout.read(), ""

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waited = True
        if self._timeout_after:
            import subprocess

            raise subprocess.TimeoutExpired(cmd="node", timeout=timeout or 0)
        return self.returncode

    @property
    def closed(self):
        return self.stdout.closed and self.stderr.closed


def _streaming_service(tmp_path: Path, popen, progress=None):
    dll = tmp_path / "wx_key.dll"
    helper = tmp_path / "wx_key_helper.cjs"
    dll.write_bytes(b"fake")
    helper.write_text("", encoding="utf-8")
    module = _module()
    service = module.WeChatKeyService(
        dll_path=dll,
        helper_path=helper,
        process_launcher=popen,
        progress_callback=progress,
        node_finder=lambda _name: "node",
    )
    snapshots = iter([[], [4242]])
    service._process_finder = lambda: next(snapshots, [4242])
    service._monotonic = lambda: 0.0
    return service


def test_streaming_reader_keeps_receiving_lines_until_exit(tmp_path: Path):
    """The stderr reader must keep draining while stdout is still open."""
    seen = []
    proc = _FakePopen(
        stdout="ab12" * 16 + "\n",
        stderr_lines=(
            "2026-08-09T00:00:00.000Z elapsed=1s, waiting for key...",
            "2026-08-09T00:00:01.000Z elapsed=2s, waiting for key...",
            "2026-08-09T00:00:02.000Z hook_success=true",
            "2026-08-09T00:00:02.000Z elapsed=3s, waiting for key...",
        ),
    )
    service = _streaming_service(
        tmp_path, lambda *_a, **_k: proc, progress=seen.append
    )

    assert service.acquire() == "ab12" * 16
    assert [getattr(event, "name", None) for event in seen] == [
        "PREPARING", "WAITING_FOR_WECHAT_START", "READY_FOR_LOGIN",
        "CREDENTIAL_RECEIVED",
    ]


def test_streaming_progress_never_leaks_internal_terms(tmp_path: Path):
    seen: list[str] = []
    proc = _FakePopen(
        stdout="ef56" * 16 + "\n",
        stderr_lines=(
            "DLL: C:\\secret\\path\\wx_key.dll",
            "InitializeHook(4321) -> true",
            "exports loaded: InitializeHook, PollKeyData, CleanupHook",
        ),
    )
    service = _streaming_service(
        tmp_path, lambda *_a, **_k: proc, progress=seen.append
    )
    service.acquire()
    joined = " ".join(str(event) for event in seen).lower()
    for leaked in ("dll", "initializehook", "koffi", "secret", "pollkeydata"):
        assert leaked not in joined


@pytest.mark.parametrize("diagnostic", [
    "hook_success=false",
    "diagnostic hook_success=true",
    'GetStatusMessage -> true, level=0, status="hook_success=true"',
])
def test_streaming_cannot_allow_login_without_listener_ready(tmp_path, diagnostic):
    seen = []
    proc = _FakePopen(stderr_lines=(diagnostic,), returncode=1)
    service = _streaming_service(tmp_path, lambda *_a, **_k: proc)

    with pytest.raises(_module().WeChatKeyUnavailable):
        service.acquire(progress=seen.append)

    assert [getattr(event, "name", None) for event in seen] == [
        "PREPARING", "WAITING_FOR_WECHAT_START",
    ]


def test_streaming_initialized_pid_without_key_reports_not_captured(
    tmp_path: Path,
):
    module = _module()
    proc = _FakePopen(
        stdout="",
        stderr_lines=(
            "Weixin PIDs: 101, 202",
            "InitializeHook(101) -> true",
            "key unavailable",
        ),
        returncode=1,
    )
    service = _streaming_service(tmp_path, lambda *_a, **_k: proc)

    with pytest.raises(module.WeChatKeyUnavailable) as caught:
        service.acquire()

    assert caught.value.code == "wechat_key_not_captured"
    assert "无法获取微信登录密钥" in caught.value.public_message
    assert "\u91cd\u65b0\u5b89\u88c5" not in caught.value.public_message


# ------------------------------------------------------------------ key bridge

@pytest.fixture(autouse=True)
def _clean_key_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let ECHO_WX_DB_KEY leak between tests."""
    monkeypatch.delenv(_module().KEY_ENVIRONMENT_VARIABLE, raising=False)


def test_acquire_logs_never_contain_the_key(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    key = "cd34" * 16
    caplog.set_level(
        logging.INFO,
        logger="qq_chat_analyzer.desktop.wechat_key_service",
    )
    service = _service(tmp_path, api=_FakeHookApi(key=key), pids=[1000])
    service.acquire()
    assert key not in caplog.text
    assert "wechat.connect.start" in caplog.text
    assert "wechat.key.capture success=true" in caplog.text
    assert "process_found=true process_count=1" in caplog.text
    assert "hook_success=true" in caplog.text
    assert "key_capture_success=true" in caplog.text


def test_acquire_failure_does_not_expose_key(tmp_path: Path) -> None:
    module = _module()
    service = _service(tmp_path, api=_FakeHookApi(key=None), pids=[])
    with pytest.raises(module.WeChatKeyUnavailable):
        service.acquire()
    assert module.KEY_ENVIRONMENT_VARIABLE not in os.environ


def test_acquire_failure_clears_stale_key(tmp_path: Path) -> None:
    module = _module()
    os.environ[module.KEY_ENVIRONMENT_VARIABLE] = "00" * 32
    service = _service(tmp_path, api=_FakeHookApi(key=None, hook_ok=False), pids=[1000])
    with pytest.raises(module.WeChatKeyUnavailable):
        service.acquire()
    assert module.KEY_ENVIRONMENT_VARIABLE not in os.environ


def test_acquire_repeated_uses_newest_key(tmp_path: Path) -> None:
    module = _module()
    first = "ef56" * 16
    second = "7890" * 16
    service = _service(tmp_path, api=_FakeHookApi(key=first), pids=[1000])
    assert service.acquire() == first
    assert os.environ.get(module.KEY_ENVIRONMENT_VARIABLE) == first

    service = _service(tmp_path, api=_FakeHookApi(key=second), pids=[1000])
    assert service.acquire() == second
    assert os.environ.get(module.KEY_ENVIRONMENT_VARIABLE) == second


# R1: events hold the exact launch/wait/release boundary under test.
class _CountedStream(io.StringIO):
    def __init__(self, text=""):
        super().__init__(text)
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        super().close()


class _AdmissionHelper:
    def __init__(self):
        self.stdout = _CountedStream("ab12" * 16 + "\n")
        self.stderr = _CountedStream()
        self.returncode = None
        self.kill_calls = 0
        self.close_calls = 0
        self.wait_entered = threading.Event()
        self.wait_release = threading.Event()
        self.close_entered = threading.Event()
        self.close_release = threading.Event()
        self.close_release.set()

    def wait(self, timeout=None):
        self.wait_entered.set()
        assert self.wait_release.wait(5), "test did not release helper wait"
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fictional-helper", timeout)
        return self.returncode

    def kill(self):
        self.kill_calls += 1
        self.returncode = -1
        self.wait_release.set()

    def close(self):
        self.close_calls += 1
        self.close_entered.set()
        assert self.close_release.wait(5), "test did not release helper close"
        self.stdout.close()
        self.stderr.close()

    @property
    def closed(self):
        return self.stdout.closed and self.stderr.closed

    def close_after_readers(self, readers, *, deadline):
        assert not any(reader.is_alive() for reader in readers)
        self.close()


def _start_acquire(service):
    outcomes = []

    def run():
        try:
            outcomes.append(service.acquire())
        except Exception as error:
            outcomes.append(error)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    return worker, outcomes


def _join_acquire(worker):
    worker.join(5)
    assert not worker.is_alive(), "acquire did not finish"


def test_r1_cancel_does_not_reopen_admission_during_launch(tmp_path):
    helper = _AdmissionHelper()
    entered, release = threading.Event(), threading.Event()
    launches = []

    def launch(*_args, **_kwargs):
        launches.append(helper)
        if len(launches) > 1:
            return _FakePopen(stdout="cd34" * 16)
        entered.set()
        assert release.wait(5)
        return helper

    service = _streaming_service(tmp_path, launch)
    snapshots = iter([[], [4242], [], [4242]])
    service._process_finder = lambda: next(snapshots, [4242])
    worker, outcomes = _start_acquire(service)
    try:
        assert entered.wait(5)
        with pytest.raises(_module().WeChatKeyUnavailable) as busy:
            service.acquire()
        assert busy.value.code == "wechat_key_busy"
        service.cancel()
        with pytest.raises(_module().WeChatKeyUnavailable) as busy:
            service.acquire()
        assert busy.value.code == "wechat_key_busy"
    finally:
        release.set()
        helper.wait_release.set()
        _join_acquire(worker)
    assert len(launches) == 1
    assert outcomes[0].code == "wechat_key_cancelled"
    assert helper.kill_calls == helper.close_calls == 1
    assert _module().KEY_ENVIRONMENT_VARIABLE not in os.environ
    service._process_launcher = lambda *_a, **_k: _FakePopen(stdout="cd34" * 16)
    assert service.acquire() == "cd34" * 16


def test_r1_shutdown_during_launch_adopts_late_helper(tmp_path):
    from qq_chat_analyzer.application.shutdown_models import ShutdownStatus

    helper = _AdmissionHelper()
    entered, release = threading.Event(), threading.Event()

    def launch(*_args, **_kwargs):
        entered.set()
        assert release.wait(5)
        return helper

    service = _streaming_service(tmp_path, launch)
    worker, outcomes = _start_acquire(service)
    try:
        assert entered.wait(5)
        assert service.shutdown() is ShutdownStatus.UNKNOWN
        with pytest.raises(_module().WeChatKeyUnavailable) as closed:
            service.acquire()
        assert closed.value.code == "wechat_key_cancelled"
    finally:
        release.set()
        helper.wait_release.set()
        _join_acquire(worker)
    assert outcomes[0].code == "wechat_key_cancelled"
    assert helper.kill_calls == helper.close_calls == 1
    assert helper.stdout.close_calls == helper.stderr.close_calls == 1
    assert service.shutdown() is ShutdownStatus.UNKNOWN
    assert helper.close_calls == 1


@pytest.mark.parametrize("completed", [False, True])
def test_r1_cancel_shutdown_and_completion_release_once(tmp_path, completed):
    helper = _AdmissionHelper()
    service = _streaming_service(tmp_path, lambda *_a, **_k: helper)
    worker, outcomes = _start_acquire(service)
    barrier = threading.Barrier(3)
    errors = []

    def request(action):
        try:
            barrier.wait(5)
            action()
        except Exception as error:
            errors.append(error)

    cancel = threading.Thread(target=request, args=(lambda: service.cancel(),))
    shutdown = threading.Thread(target=request, args=(lambda: service.shutdown(),))
    try:
        assert helper.wait_entered.wait(5)
        cancel.start()
        shutdown.start()
        barrier.wait(5)
        cancel.join(5)
        shutdown.join(5)
        assert not cancel.is_alive() and not shutdown.is_alive()
        if completed:
            helper.returncode = 0
    finally:
        helper.wait_release.set()
        _join_acquire(worker)
    assert errors == []
    assert outcomes[0].code == "wechat_key_cancelled"
    assert helper.kill_calls == (0 if completed else 1)
    assert helper.close_calls == 1


@pytest.mark.parametrize("failed_start", [1, 2])
def test_r1_reader_start_failure_keeps_release_owner(tmp_path, monkeypatch, failed_start):
    helper = _AdmissionHelper()
    helper.wait_release.set()
    service = _streaming_service(tmp_path, lambda *_a, **_k: helper)
    real_start, real_join = threading.Thread.start, threading.Thread.join
    starts = 0
    unstarted_joins = []

    def start(reader):
        nonlocal starts
        starts += 1
        if starts == failed_start:
            raise RuntimeError("fictional reader start failure")
        return real_start(reader)

    def join(reader, *args, **kwargs):
        if reader.ident is None:
            unstarted_joins.append(reader)
        return real_join(reader, *args, **kwargs)

    monkeypatch.setattr(threading.Thread, "start", start)
    monkeypatch.setattr(threading.Thread, "join", join)
    with pytest.raises(RuntimeError, match="fictional reader start failure"):
        service.acquire()
    assert helper.kill_calls == helper.close_calls == 1
    assert unstarted_joins == []


def test_r1_admission_stays_closed_until_normal_release_finishes(tmp_path):
    helper = _AdmissionHelper()
    helper.returncode = 0
    helper.wait_release.set()
    helper.close_release.clear()
    service = _streaming_service(tmp_path, lambda *_a, **_k: helper)
    worker, outcomes = _start_acquire(service)
    try:
        assert helper.close_entered.wait(5)
        service.cancel()
        with pytest.raises(_module().WeChatKeyUnavailable) as busy:
            service.acquire()
        assert busy.value.code == "wechat_key_busy"
    finally:
        helper.close_release.set()
        _join_acquire(worker)
    assert outcomes[0].code == "wechat_key_cancelled"
    assert helper.kill_calls == 0
    assert helper.close_calls == 1


def test_r1_shutdown_before_first_acquire_refuses_launch(tmp_path):
    from qq_chat_analyzer.application.shutdown_models import ShutdownStatus

    service = _streaming_service(tmp_path, lambda *_a, **_k: pytest.fail("launched after shutdown"))
    assert service.shutdown() is ShutdownStatus.SUCCESS
    with pytest.raises(_module().WeChatKeyUnavailable) as closed:
        service.acquire()
    assert closed.value.code == "wechat_key_cancelled"


def test_r1_failed_stop_does_not_launch_next_pid_candidate(tmp_path):
    launches = []
    helper = _FakePopen(timeout_after=True)

    def failed_kill():
        raise OSError("fictional stop failure")

    helper.kill = failed_kill

    def launch(*_a, **_k):
        launches.append(helper)
        return helper if len(launches) == 1 else _FakePopen(stdout="ab12" * 16)

    service = _streaming_service(tmp_path, launch)
    snapshots = iter([[], [4242, 4243]])
    service._process_finder = lambda: next(snapshots, [4242, 4243])
    with pytest.raises(_module().WeChatKeyUnavailable):
        service.acquire()
    assert len(launches) == 1
    with pytest.raises(_module().WeChatKeyUnavailable) as busy:
        service.acquire()
    assert busy.value.code == "wechat_key_busy"


def test_r1_pipe_close_failure_still_releases_other_pipe(tmp_path):
    helper = _FakePopen(stdout="ab12" * 16)
    helper.stdout = _CountedStream("ab12" * 16)
    helper.stderr = _CountedStream()

    def failed_close():
        raise OSError("fictional close failure")

    helper.stdout.close = failed_close
    service = _streaming_service(tmp_path, lambda *_a, **_k: helper)
    try:
        with pytest.raises(_module().WeChatKeyUnavailable) as incomplete:
            service.acquire()
        assert incomplete.value.code == "wechat_helper_cleanup_incomplete"
        assert helper.stderr.closed
        assert helper.stderr.close_calls == 1
        with pytest.raises(_module().WeChatKeyUnavailable) as busy:
            service.acquire()
        assert busy.value.code == "wechat_key_busy"
    finally:
        io.StringIO.close(helper.stdout)
