"""Acquire the WeChat 4.x database key from a running Weixin.exe process.

This service wraps the verified ``wx_key.dll`` hook surface:
``InitializeHook(pid)``, ``PollKeyData(buffer, size)``, and
``CleanupHook()``. It never reads databases and never prints the key.
Development logs record only flow milestones and safe error types, never the
key value or raw helper output. Callers inject fake process finders and DLL
adapters in tests so no real WeChat process or native library is ever touched.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable

from ...resources import default_wechat_wx_key_dll_path
from ...runtime.windows_job import launch_owned_process
from ..errors import ApplicationServiceError
from ..shutdown_models import ShutdownStatus
from .wechat_connection_progress import WeChatConnectionProgress


KEY_LENGTH = 64
BUFFER_SIZE = 65
DEFAULT_POLL_INTERVAL_SECONDS = 0.2
DEFAULT_TIMEOUT_SECONDS = 600.0
WECHAT_PROCESS_NAME = "Weixin.exe"
HELPER_FILE_NAME = "wx_key_helper.cjs"
_MAX_RETAINED_ERROR_LINES = 20
_HELPER_WAIT_SLICE_SECONDS = 0.5
_HELPER_RELEASE_SECONDS = 3.0
_HELPER_TREE_POLL_SECONDS = 0.05
_KEY_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
# Process-local bridge for the manual WCDB diagnostic runner: the freshly
# obtained key is exposed to child processes for the lifetime of this process
# only (never persisted, never logged, never printed).
KEY_ENVIRONMENT_VARIABLE = "ECHO_WX_DB_KEY"
_HELPER_READY_PATTERN = re.compile(
    r"(?:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z )?hook_success=true"
)
_HELPER_PIDS_PATTERN = re.compile(
    r"weixin pids:\s*([0-9,\s]*)", re.IGNORECASE
)
_HELPER_HOOK_SUCCESS_PATTERN = re.compile(
    r"initializehook\([^)]*\)\s*->\s*true", re.IGNORECASE
)
_HELPER_HOOK_FAILURE_PATTERN = re.compile(
    r"initializehook\([^)]*\)\s*->\s*false", re.IGNORECASE
)
_HELPER_STAGE_PATTERN = re.compile(
    r"helper_stage=(node_start|koffi_load|process_enumeration|dll_load)"
)
_HELPER_PROCESS_PATTERN = re.compile(
    r"process_found=(true|false),\s*process_count=(\d+)", re.IGNORECASE
)
MESSAGE_KEY_NOT_CAPTURED = (
    "无法获取微信登录密钥。\n可能原因：\n"
    "- 微信未处于可连接状态\n"
    "- 权限不足\n"
    "- 微信版本或环境不支持"
)
MESSAGE_HOOK_FAILED = (
    "无法获取微信登录密钥。\n可能原因：\n"
    "- 微信版本或环境不支持\n"
    "- 权限不足\n"
    "- 微信未处于可连接状态"
)
MESSAGE_WAIT_TIMEOUT = (
    "等待微信登录超时，请重新点击连接，等待 Echo 提示可以登录后，再完成登录。"
)
MESSAGE_WECHAT_NOT_RUNNING = (
    "未检测到微信，请先打开微信并停留在登录界面，"
    "返回 Echo 重试连接，等待提示可以登录后再登录。"
)

_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.wechat_key_service")


class WeChatKeyUnavailable(ApplicationServiceError):
    """Raised when the WeChat database key cannot be acquired safely."""

    code = "wechat_key_unavailable"
    public_message = "\u5fae\u4fe1\u8fde\u63a5\u51c6\u5907\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5\u3002"

    def __init__(
        self,
        public_message: str | None = None,
        *,
        code: str | None = None,
    ) -> None:
        self.code = code or type(self).code
        self.public_message = public_message or type(self).public_message
        super().__init__()


class WeChatKeyService:
    """Detect WeChat, hook it, and return a 64-hex database key."""

    def __init__(
        self,
        *,
        dll_path: str | Path | None = None,
        process_finder: Callable[[], list[int]] | None = None,
        dll_loader: Callable[[Path], Any] | None = None,
        buffer_factory: Callable[[int], Any] | None = None,
        sleep: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        helper_path: str | Path | None = None,
        node_executable: str = "node",
        node_finder: Callable[[str], str | None] | None = None,
        koffi_module_path: str | Path | None = None,
        process_launcher: Callable[..., Any] | None = None,
        progress_callback: Callable[[WeChatConnectionProgress], None] | None = None,
    ) -> None:
        self._dll_path = (
            Path(dll_path)
            if dll_path is not None
            else default_wechat_wx_key_dll_path()
        )
        self._process_finder = process_finder or _find_weixin_pids
        self._dll_loader = dll_loader or _load_hook_api
        self._buffer_factory = buffer_factory or _create_buffer
        self._sleep = sleep or time.sleep
        self._monotonic = monotonic or time.monotonic
        self._poll_interval = poll_interval
        self._timeout = timeout
        self._helper_path = (
            Path(helper_path)
            if helper_path is not None
            else self._dll_path.with_name(HELPER_FILE_NAME)
        )
        self._node_executable = node_executable
        self._node_finder = node_finder or shutil.which
        self._process_launcher = process_launcher
        self._progress_callback = progress_callback
        self._lifecycle_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._acquire_finished = threading.Event()
        self._acquire_finished.set()
        self._acquiring = False
        self._closing = False
        self._used = False
        self._helper_process: Any = None
        self._helper_tree_status = ShutdownStatus.UNKNOWN
        self._helper_resource_status = ShutdownStatus.UNKNOWN
        self._helper_readers: tuple[threading.Thread, ...] = ()
        # PID observation is shared by the helper path; only an explicit native
        # adapter opts into the separate in-process DLL contract.
        self._legacy_injected = dll_loader is not None
        self._koffi_module_path = (
            Path(koffi_module_path) if koffi_module_path is not None
            else self._helper_path.parent / "node_modules"
        )

    def clear(self) -> None:
        """Drop the process-local key so helpers start without stale state."""
        _clear_key_environment()

    def acquire(
        self,
        timeout: float | None = None,
        progress: Callable[[WeChatConnectionProgress], None] | None = None,
        *, cancel_event: threading.Event | None = None,
    ) -> str:
        """Return one 64-hex database key, raising a user-safe error."""
        with self._lifecycle_lock:
            if self._closing:
                self._check_cancelled()
            if self._acquiring or self._helper_process is not None:
                raise WeChatKeyUnavailable(
                    "微信连接仍在进行或清理中，请稍后重试。",
                    code="wechat_key_busy",
                )
            self._cancel_event = cancel_event if cancel_event is not None else threading.Event()
            self._check_cancelled()
            self._acquiring = True
            self._acquire_finished.clear()
            self._used = True
        try:
            key = self._acquire_key(timeout, progress)
            with self._lifecycle_lock:
                self._check_cancelled()
                _expose_key_to_environment(key)
            return key
        finally:
            with self._lifecycle_lock:
                self._acquiring = False
                self._acquire_finished.set()

    def cancel(self) -> None:
        """Request cancellation; the acquire owner alone releases its helper.

        Admission stays occupied until that owner finishes cleanup. A launcher
        already running may return later; its result is still owned by acquire.
        """
        with self._lifecycle_lock:
            if self._acquiring:
                self._cancel_event.set()

    def shutdown(self, timeout: float = 0) -> ShutdownStatus:
        """Close admission; only background callers opt into a bounded drain.

        Tree/resource evidence cannot prove Node CleanupHook completion.
        Once used, even a fully released helper remains UNKNOWN.
        """
        deadline = self._monotonic() + max(0.0, timeout)
        with self._lifecycle_lock:
            self._closing = True
            self._cancel_event.set()
            if not self._used:
                return ShutdownStatus.SUCCESS
        if timeout > 0:
            if not self._acquire_finished.wait(max(0.0, deadline - self._monotonic())):
                return ShutdownStatus.TIMED_OUT
            status = self.retry_cleanup(timeout=max(0.0, deadline - self._monotonic()))
            if status in (ShutdownStatus.FAILED, ShutdownStatus.TIMED_OUT):
                return status
        return ShutdownStatus.UNKNOWN

    @property
    def helper_tree_status(self) -> ShutdownStatus:
        """Latest helper tree evidence only; excludes readers, pipes and handles."""
        with self._lifecycle_lock:
            return self._helper_tree_status

    @property
    def helper_resource_status(self) -> ShutdownStatus:
        """Python/native-handle evidence, independent of Node CleanupHook."""
        with self._lifecycle_lock:
            return self._helper_resource_status

    def retry_cleanup(self, timeout: float = _HELPER_RELEASE_SECONDS) -> ShutdownStatus:
        """Retry retained resources under the existing single-owner admission.

        Shutdown/cancel still only signal; a concurrent owner is never joined or
        displaced here. A successful resource retry is not native-hook evidence.
        """
        with self._lifecycle_lock:
            if self._acquiring:
                return ShutdownStatus.UNKNOWN
            process = self._helper_process
            if process is None:
                return self._helper_resource_status
            readers = self._helper_readers
            self._acquiring = True
            self._acquire_finished.clear()
        try:
            return self._release_helper(
                process, list(readers), process.returncode is not None,
                deadline=self._monotonic() + max(0.0, timeout),
            )
        finally:
            with self._lifecycle_lock:
                self._acquiring = False
                self._acquire_finished.set()

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise WeChatKeyUnavailable(
                "已取消微信连接，请重新点击连接。", code="wechat_key_cancelled"
            )

    def _acquire_key(
        self,
        timeout: float | None,
        progress: Callable[[WeChatConnectionProgress], None] | None,
    ) -> str:
        _LOGGER.info("wechat.connect.start")
        timeout_seconds = self._timeout if timeout is None else timeout
        deadline = self._monotonic() + max(0.0, timeout_seconds)
        last_progress: WeChatConnectionProgress | None = None
        progress_lock = threading.Lock()

        def report(stage: WeChatConnectionProgress) -> None:
            # stderr arrives on a reader thread. Once credentials arrive,
            # delayed diagnostics must not invite another login.
            nonlocal last_progress
            with progress_lock:
                if (
                    last_progress is WeChatConnectionProgress.CREDENTIAL_RECEIVED
                    or stage is last_progress
                ):
                    return
                last_progress = stage
                self._report_progress(stage, progress)

        report(WeChatConnectionProgress.PREPARING)
        try:
            self._check_cancelled()
            key = self._acquire(deadline=deadline, progress=report)
            self._check_cancelled()
        except Exception as error:
            _LOGGER.warning(
                "wechat.key.capture success=false error_type=%s code=%s",
                type(error).__name__,
                getattr(error, "code", ""),
            )
            raise
        _LOGGER.info("wechat.key.capture success=true key_capture_success=true")
        report(WeChatConnectionProgress.CREDENTIAL_RECEIVED)
        return key

    def _acquire(
        self,
        deadline: float,
        progress: Callable[[WeChatConnectionProgress], None] | None = None,
    ) -> str:
        """Return one 64-hex database key, raising a user-safe error."""
        _clear_key_environment()
        if not self._dll_path.is_file():
            raise WeChatKeyUnavailable(
                "\u4f59\u97f3\u7684\u5fae\u4fe1\u8fde\u63a5\u7ec4\u4ef6"
                "\u4e0d\u5b8c\u6574\uff0c\u8bf7\u91cd\u65b0\u5b89\u88c5"
                "\u540e\u91cd\u8bd5\u3002",
                code="wechat_environment_missing",
            )

        if not self._legacy_injected:
            key = self._acquire_with_helper(deadline, progress)
            return key

        pids = self._wait_for_new_pids(deadline, progress)
        api = self._dll_loader(self._dll_path)

        hook_succeeded = False
        hook_failed = False
        capture_failed = False
        for pid in pids:
            self._remaining_budget(deadline)
            try:
                hooked = bool(api.initialize(pid))
            except Exception:
                hook_failed = True
                _LOGGER.warning("wechat.key.hook hook_success=false")
                continue

            if not hooked:
                hook_failed = True
                _LOGGER.warning("wechat.key.hook hook_success=false")
                continue

            hook_succeeded = True
            _LOGGER.info("wechat.key.hook hook_success=true")
            try:
                self._remaining_budget(deadline)
                self._report_progress(
                    WeChatConnectionProgress.READY_FOR_LOGIN, progress
                )
                key = self._poll_key(api, deadline)
                if key:
                    self._remaining_budget(deadline)
                    _LOGGER.info("wechat.key.capture key_capture_success=true")
                    return key
            finally:
                try:
                    api.cleanup()
                except Exception:
                    pass
            capture_failed = True
            _LOGGER.warning("wechat.key.capture key_capture_success=false")

        self._remaining_budget(deadline)
        if hook_failed and not hook_succeeded:
            raise WeChatKeyUnavailable(
                MESSAGE_HOOK_FAILED,
                code="wechat_hook_failed",
            )
        if capture_failed:
            raise WeChatKeyUnavailable(
                MESSAGE_KEY_NOT_CAPTURED,
                code="wechat_key_not_captured",
            )
        raise WeChatKeyUnavailable(
            MESSAGE_WAIT_TIMEOUT,
            code="wechat_key_timeout",
        )

    def _wait_for_new_pids(
        self,
        deadline: float,
        progress: Callable[[WeChatConnectionProgress], None] | None,
    ) -> list[int]:
        """Observe every initial PID absent before accepting start candidates.

        After that observation, a reused PID is eligible. A restart entirely
        between snapshots with the same PID conservatively remains waiting.
        """
        old_pids = set(self._process_finder())
        _LOGGER.info(
            "wechat.key.process process_found=%s process_count=%d",
            "true" if old_pids else "false",
            len(old_pids),
        )
        waiting_for_exit = bool(old_pids)
        self._report_progress(
            WeChatConnectionProgress.WAITING_FOR_WECHAT_EXIT
            if waiting_for_exit else WeChatConnectionProgress.WAITING_FOR_WECHAT_START,
            progress,
        )
        while True:
            self._remaining_budget(deadline)
            pids = self._process_finder()
            remaining = self._remaining_budget(deadline)
            if waiting_for_exit and old_pids.isdisjoint(pids):
                waiting_for_exit = False
                self._report_progress(
                    WeChatConnectionProgress.WAITING_FOR_WECHAT_START, progress
                )
            if not waiting_for_exit and pids:
                _LOGGER.info(
                    "wechat.key.process process_found=true process_count=%d",
                    len(pids),
                )
                return list(dict.fromkeys(pids))
            self._sleep(min(self._poll_interval, remaining))

    def _remaining_budget(self, deadline: float) -> float:
        self._check_cancelled()
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise WeChatKeyUnavailable(
                MESSAGE_WAIT_TIMEOUT, code="wechat_key_timeout"
            )
        return remaining

    def _acquire_with_helper(
        self,
        deadline: float,
        progress: Callable[[WeChatConnectionProgress], None] | None,
    ) -> str:
        if not self._helper_path.is_file():
            raise WeChatKeyUnavailable(
                "\u4f59\u97f3\u7684\u5fae\u4fe1\u8fde\u63a5\u7ec4\u4ef6"
                "\u4e0d\u5b8c\u6574\uff0c\u8bf7\u91cd\u65b0\u5b89\u88c5"
                "\u540e\u91cd\u8bd5\u3002",
                code="wechat_environment_missing",
            )
        command, options = self._build_helper_invocation(
            self._remaining_budget(deadline)
        )
        pids = self._wait_for_new_pids(deadline, progress)
        last_error: WeChatKeyUnavailable | None = None
        for index, pid in enumerate(pids):
            # Divide only the remaining acquisition budget, reserving time for
            # other candidates even if this listener never captures a key.
            budget = self._remaining_budget(deadline) / (len(pids) - index)
            candidate_command = list(command)
            candidate_command[candidate_command.index("--timeout-ms") + 1] = str(
                int(budget * 1000)
            )
            candidate_command.extend(["--pid", str(pid)])
            candidate_options = dict(options, timeout=budget)
            try:
                key = self._run_helper_streaming(
                    candidate_command, candidate_options, progress, deadline
                )
            except WeChatKeyUnavailable as error:
                if error.code not in {
                    "wechat_hook_failed", "wechat_key_not_captured",
                    "wechat_key_timeout", "wechat_not_running",
                }:
                    raise
                last_error = error
                continue
            self._remaining_budget(deadline)
            return key
        self._remaining_budget(deadline)
        assert last_error is not None
        raise last_error

    def _build_helper_invocation(
        self, timeout_seconds: float
    ) -> tuple[list[str], dict[str, Any]]:
        """Build the streaming helper's command and acquisition budget."""
        command = [
            self._resolve_node_executable(),
            str(self._helper_path),
            "--dll",
            str(self._dll_path),
            "--timeout-ms",
            str(max(0, round(timeout_seconds * 1000))),
        ]
        environment = os.environ.copy()
        environment["NODE_PATH"] = str(self._koffi_module_path)
        options: dict[str, Any] = {
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": max(0.0, timeout_seconds),
            "env": environment,
            "cwd": str(self._helper_path.parent),
        }
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        return command, options

    def _resolve_node_executable(self) -> str:
        bundled_node = self._helper_path.with_name("node.exe")
        if bundled_node.is_file():
            return str(bundled_node)

        system_node = self._node_finder(self._node_executable)
        if system_node:
            return str(system_node)

        raise WeChatKeyUnavailable(
            "微信连接组件缺少 Node.js 运行环境，"
            "请重新安装余音后重试。"
        )

    def _run_helper_streaming(
        self,
        command: list[str],
        options: dict[str, Any],
        progress: Callable[[WeChatConnectionProgress], None] | None,
        deadline: float,
    ) -> str:
        """Run the helper and report each stderr line while it still runs.

        The helper writes only the key to stdout and every diagnostic to
        stderr, so a reader thread drains stderr into acquisition milestones
        while the main thread waits for stdout. Timeouts are distinguished from
        launch failures because they need different user guidance.
        """
        launcher = self._process_launcher or (
            launch_owned_process if os.name == "nt" else subprocess.Popen
        )
        popen_options = dict(options)
        wait_timeout = popen_options.pop("timeout")
        popen_options["stdout"] = subprocess.PIPE
        popen_options["stderr"] = subprocess.PIPE
        popen_options["stdin"] = subprocess.DEVNULL
        if launcher is launch_owned_process:
            # Declare PIPE ownership before the process enters the atexit registry.
            popen_options["external_readers"] = True

        started = self._monotonic()
        self._check_cancelled()
        with self._lifecycle_lock:
            if self._helper_process is not None:
                raise WeChatKeyUnavailable(
                    "微信连接仍在清理中，请稍后重试。", code="wechat_key_busy"
                )
        try:
            process = launcher(command, **popen_options)
        except subprocess.TimeoutExpired:
            raise WeChatKeyUnavailable(
                _helper_timeout_message(), code="wechat_key_timeout"
            ) from None
        except (OSError, subprocess.SubprocessError):
            raise WeChatKeyUnavailable(_helper_launch_message()) from None

        # From this point acquire is the sole release owner, even if a reader
        # cannot be constructed/started or the launcher returned after shutdown.
        with self._lifecycle_lock:
            self._helper_process = process
            self._helper_tree_status = ShutdownStatus.UNKNOWN
            self._helper_resource_status = ShutdownStatus.UNKNOWN
            self._helper_readers = ()
        recent_errors: list[str] = []
        readers: list[threading.Thread] = []
        register_readers = getattr(process, "set_external_readers", None)
        process_exited = False
        stdout_lines: list[str] = []

        def _read_stdout(stream: Any) -> None:
            if stream is None:
                return
            try:
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    stdout_lines.append(line)
            except Exception:
                return

        try:
            self._check_cancelled()
            reader = threading.Thread(
                target=self._drain_progress,
                args=(process.stderr, recent_errors, progress),
                daemon=True,
            )
            readers.append(reader)
            with self._lifecycle_lock:
                self._helper_readers = tuple(readers)
            if callable(register_readers):
                register_readers(readers)
            reader.start()
            stdout_reader = threading.Thread(
                target=_read_stdout, args=(process.stdout,), daemon=True,
            )
            readers.append(stdout_reader)
            with self._lifecycle_lock:
                self._helper_readers = tuple(readers)
            if callable(register_readers):
                register_readers(readers)
            stdout_reader.start()
            wait_budget = wait_timeout - (self._monotonic() - started)
            while True:
                self._check_cancelled()
                remaining = min(deadline - self._monotonic(), wait_budget)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, wait_timeout)
                wait_slice = min(_HELPER_WAIT_SLICE_SECONDS, remaining)
                try:
                    process.wait(timeout=wait_slice)
                except subprocess.TimeoutExpired:
                    wait_budget -= wait_slice
                    continue
                process_exited = process.returncode is not None
                if not process_exited:
                    raise WeChatKeyUnavailable(
                        "微信连接组件未能确认退出，请重试。",
                        code="wechat_helper_exit_unknown",
                    )
                self._check_cancelled()
                break
        except subprocess.TimeoutExpired:
            raise WeChatKeyUnavailable(
                _helper_timeout_message(), code="wechat_key_timeout"
            ) from None
        except (OSError, subprocess.SubprocessError):
            raise WeChatKeyUnavailable(_helper_launch_message()) from None
        finally:
            cleanup_status = self._release_helper(process, readers, process_exited)

        if cleanup_status is not ShutdownStatus.SUCCESS:
            raise WeChatKeyUnavailable(
                "微信连接组件未完成清理，请稍后重试。",
                code="wechat_helper_cleanup_incomplete",
            )

        stdout = "".join(stdout_lines)
        if process.returncode != 0:
            stderr = "\n".join(recent_errors)
            _log_helper_diagnostics(stderr, process.returncode)
            raise WeChatKeyUnavailable(
                _helper_failure_message(stderr),
                code=_helper_failure_code(stderr),
            )
        try:
            key = self._finalize_key(stdout)
        except WeChatKeyUnavailable:
            _log_helper_diagnostics(
                "\n".join(recent_errors), process.returncode
            )
            raise
        return key

    def _drain_progress(
        self,
        stream: Any,
        recent_errors: list[str],
        progress: Callable[[WeChatConnectionProgress], None] | None = None,
    ) -> None:
        """Translate helper readiness facts, never forwarding diagnostic text."""
        if stream is None:
            return
        try:
            while True:
                line = stream.readline()
                if not line:
                    break
                text = str(line).strip()
                if not text:
                    continue
                if len(recent_errors) >= _MAX_RETAINED_ERROR_LINES:
                    recent_errors.pop(0)
                recent_errors.append(text)
                if _HELPER_READY_PATTERN.fullmatch(text):
                    self._report_progress(
                        WeChatConnectionProgress.READY_FOR_LOGIN, progress
                    )
        except Exception:
            return

    def _report_progress(
        self,
        stage: WeChatConnectionProgress,
        progress: Callable[[WeChatConnectionProgress], None] | None = None,
    ) -> None:
        callback = progress or self._progress_callback
        if callback is None:
            return
        try:
            callback(stage)
        except Exception as error:
            _LOGGER.warning(
                "wechat.progress.callback success=false error_type=%s",
                type(error).__name__,
            )
            return

    def _release_helper(
        self, process: Any, readers: list[threading.Thread], process_exited: bool,
        *, deadline: float | None = None,
    ) -> ShutdownStatus:
        """One owner/deadline for tree, root, readers, pipes and native handles."""
        if deadline is None:
            deadline = self._monotonic() + _HELPER_RELEASE_SECONDS
        if callable(getattr(process, "active_process_count", None)):
            with self._lifecycle_lock:
                tree_status = self._helper_tree_status
            # A prior empty-Job observation remains valid on this same retained
            # helper, including a partial close that already released its Job.
            if tree_status is not ShutdownStatus.SUCCESS:
                tree_status = self._release_helper_tree(process, deadline=deadline)
            with self._lifecycle_lock:
                self._helper_tree_status = tree_status
            if tree_status is not ShutdownStatus.SUCCESS:
                return tree_status
        try:
            status = self._release_helper_resources(process, readers, process_exited, deadline)
        except subprocess.TimeoutExpired:
            status = ShutdownStatus.TIMED_OUT
        except Exception:
            status = ShutdownStatus.FAILED
        with self._lifecycle_lock:
            self._helper_resource_status = status
            if status is ShutdownStatus.SUCCESS:
                self._helper_process = None
                self._helper_readers = ()
        return status

    def _cleanup_remaining(self, deadline: float) -> float:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired("wechat helper cleanup", 0)
        return remaining

    def _release_helper_resources(
        self, process: Any, readers: list[threading.Thread], process_exited: bool,
        deadline: float,
    ) -> ShutdownStatus:
        if not process_exited or process.returncode is None:
            if not callable(getattr(process, "active_process_count", None)):
                self._cleanup_remaining(deadline)
                process.kill()
            process.wait(timeout=self._cleanup_remaining(deadline))
        if process.returncode is None:
            return ShutdownStatus.UNKNOWN
        for reader in readers:
            if reader.ident is None:
                continue
            reader.join(timeout=self._cleanup_remaining(deadline))
            if reader.is_alive():
                return ShutdownStatus.TIMED_OUT
        self._cleanup_remaining(deadline)
        closer = getattr(process, "close_after_readers", None)
        if callable(closer):
            closer(readers, deadline=deadline)
        else:
            # Legacy/injected launchers may expose no bounded handle API. Drain
            # their pipes but never invoke an arbitrary unbounded close().
            status = ShutdownStatus.SUCCESS
            for stream in (process.stdout, process.stderr):
                if stream is None or getattr(stream, "closed", None) is True:
                    continue
                self._cleanup_remaining(deadline)
                closer = getattr(stream, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except Exception:
                        status = ShutdownStatus.FAILED
                else:
                    status = ShutdownStatus.UNKNOWN
            if status is not ShutdownStatus.SUCCESS:
                return status
        self._cleanup_remaining(deadline)
        pipes_closed = all(stream is None or getattr(stream, "closed", None) is True
                           for stream in (process.stdout, process.stderr))
        if not pipes_closed or getattr(process, "closed", None) is not True:
            return ShutdownStatus.UNKNOWN
        return ShutdownStatus.SUCCESS

    def _release_helper_tree(self, process: Any, *, deadline: float) -> ShutdownStatus:
        """Prove the retained Job empty, never infer exit from kill/close/root."""
        query = getattr(process, "active_process_count", None)
        stop = getattr(process, "terminate_tree", None)
        if not callable(query) or not callable(stop):
            return ShutdownStatus.UNKNOWN
        stopped = False
        while True:
            if self._monotonic() >= deadline:
                return ShutdownStatus.TIMED_OUT
            try:
                count = query()
            except Exception:
                _LOGGER.warning("wechat.key.helper tree_exit_status=unknown reason=query_failed")
                return ShutdownStatus.UNKNOWN
            if self._monotonic() >= deadline:
                return ShutdownStatus.TIMED_OUT
            if count is None:
                _LOGGER.warning("wechat.key.helper tree_exit_status=unknown reason=job_closed")
                return ShutdownStatus.UNKNOWN
            if type(count) is not int or count < 0:
                return ShutdownStatus.UNKNOWN
            if count == 0:
                return ShutdownStatus.SUCCESS
            if not stopped:
                try:
                    if stop() is not True:
                        return ShutdownStatus.UNKNOWN
                except Exception:
                    return ShutdownStatus.FAILED
                stopped = True
                # Probe immediately after stopping, using the same deadline.
                continue
            self._sleep(max(0.0, min(_HELPER_TREE_POLL_SECONDS, deadline - self._monotonic())))

    @staticmethod
    def _finalize_key(stdout: Any) -> str:
        key = str(stdout or "").replace("\x00", "").strip()
        if len(key) < KEY_LENGTH:
            raise WeChatKeyUnavailable(
                MESSAGE_KEY_NOT_CAPTURED,
                code="wechat_key_not_captured",
            )
        return key[:KEY_LENGTH].lower()

    # ---------------------------------------------------------------- internals

    def _poll_key(self, api: Any, deadline: float) -> str | None:
        while self._monotonic() < deadline:
            buffer = self._buffer_factory(BUFFER_SIZE)
            try:
                got = bool(api.poll_key(buffer, BUFFER_SIZE))
            except Exception:
                return None
            if got:
                key = _extract_key(buffer)
                if key:
                    return key
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return None
            self._sleep(min(self._poll_interval, remaining))
        return None

def _expose_key_to_environment(key: str) -> None:
    """Share the just-acquired key with child processes (for example the
    WCDB diagnostic runner) for the lifetime of this process only."""
    os.environ[KEY_ENVIRONMENT_VARIABLE] = key


def _clear_key_environment() -> None:
    """Drop any previously exposed key so a failed acquisition never
    leaves a stale key behind for child processes."""
    os.environ.pop(KEY_ENVIRONMENT_VARIABLE, None)


def _helper_timeout_message() -> str:
    """Waiting ran out of time. The user can retry while WeChat logs in."""
    return MESSAGE_WAIT_TIMEOUT


def _helper_launch_message() -> str:
    """The helper process could not start at all."""
    return (
        "\u65e0\u6cd5\u542f\u52a8\u5fae\u4fe1\u8fde\u63a5\u7ec4\u4ef6\uff0c"
        "\u8bf7\u91cd\u65b0\u5b89\u88c5\u4f59\u97f3\u540e\u91cd\u8bd5\u3002"
    )


def _helper_failure_message(stderr: Any) -> str:
    # Native/helper details stay out of the public error surface.
    detail = str(stderr or "").strip().lower()
    if "no weixin process" in detail:
        return MESSAGE_WECHAT_NOT_RUNNING
    if "key unavailable" in detail:
        return MESSAGE_KEY_NOT_CAPTURED
    if "initializehook" in detail and "-> true" not in detail:
        return MESSAGE_HOOK_FAILED
    if "timeout" in detail:
        return MESSAGE_WAIT_TIMEOUT
    if (
        _helper_runtime_failure(detail)
        or _last_helper_stage(detail) == "dll_load"
        or "dll" in detail
        or "load" in detail
    ):
        return "微信连接组件加载失败，请重新安装余音后重试。"
    return "微信连接准备失败，请重试。"

def _helper_failure_code(stderr: Any) -> str:
    detail = str(stderr or "").lower()
    if "no weixin process" in detail:
        return "wechat_not_running"
    if "key unavailable" in detail:
        return "wechat_key_not_captured"
    if "initializehook" in detail and "-> true" not in detail:
        return "wechat_hook_failed"
    if _helper_runtime_failure(detail) or _last_helper_stage(detail) == "dll_load":
        return "wechat_environment_missing"
    if "timeout" in detail:
        return "wechat_key_timeout"
    if "dll" in detail or "load" in detail:
        return "wechat_environment_missing"
    return "wechat_process_incompatible"


def _helper_runtime_failure(detail: str) -> bool:
    """Tell helper bootstrap/environment failures from hook-stage failures."""
    return (
        "cannot find module" in detail
        or "node_module_version" in detail
        or "was compiled against" in detail
        or ("koffi" in detail and ("error" in detail or "fail" in detail))
        or ("spawn " in detail and "enoent" in detail)
        or ("command failed" in detail and "powershell" in detail)
    )


def _last_helper_stage(stderr: Any) -> str:
    stages = _HELPER_STAGE_PATTERN.findall(str(stderr or "").lower())
    return stages[-1] if stages else "unknown"


def _helper_error_category(stage: str, exit_code: Any) -> str:
    if stage == "dll_load":
        return "dll_load_failed"
    if stage == "process_enumeration":
        return "process_enumeration_failed"
    if stage in {"node_start", "koffi_load"}:
        return "runtime_load_failed"
    if isinstance(exit_code, int) and exit_code < 0:
        return "native_process_exit"
    return "helper_failed"


def _log_helper_diagnostics(stderr: Any, exit_code: Any = None) -> None:
    """Record safe helper milestones; helper details never enter logs.

    Stages the helper never reached are logged as explicit ``null`` so a
    failure can be attributed to the earliest missing milestone.
    """
    text = str(stderr or "").lower()
    stage = _last_helper_stage(text)
    safe_exit_code = exit_code if isinstance(exit_code, int) else "unknown"
    _LOGGER.warning(
        "wechat.key.helper helper_exit_code=%s helper_stage=%s "
        "helper_error_category=%s",
        safe_exit_code,
        stage,
        _helper_error_category(stage, exit_code),
    )
    process_match = _HELPER_PROCESS_PATTERN.search(text)
    match = _HELPER_PIDS_PATTERN.search(text)
    if process_match:
        _LOGGER.info(
            "wechat.key.process process_found=%s process_count=%d",
            process_match.group(1).lower(),
            int(process_match.group(2)),
        )
    elif match:
        count = sum(1 for item in match.group(1).split(",") if item.strip())
        _LOGGER.info(
            "wechat.key.process process_found=%s process_count=%d",
            "true" if count else "false",
            count,
        )
    elif "no weixin process" in text:
        _LOGGER.info("wechat.key.process process_found=false process_count=0")
    else:
        _LOGGER.info("wechat.key.process process_found=null process_count=null")
    if "hook_success=true" in text or _HELPER_HOOK_SUCCESS_PATTERN.search(text):
        _LOGGER.info("wechat.key.hook hook_success=true")
    elif "hook_success=false" in text or _HELPER_HOOK_FAILURE_PATTERN.search(text):
        _LOGGER.warning("wechat.key.hook hook_success=false")
    else:
        _LOGGER.info("wechat.key.hook hook_success=null")
    _LOGGER.warning("wechat.key.capture key_capture_success=false")


def _extract_key(buffer: Any) -> str | None:
    if hasattr(buffer, "raw"):
        raw = buffer.raw
    elif isinstance(buffer, (bytes, bytearray)):
        raw = bytes(buffer)
    else:
        raw = str(buffer).encode("utf-8", errors="replace")
    text = raw.split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()
    if _KEY_PATTERN.fullmatch(text):
        return text.lower()
    return None


def _create_buffer(size: int) -> Any:
    return ctypes.create_string_buffer(size)


def _load_hook_api(path: Path) -> Any:
    if os.name != "nt":
        raise WeChatKeyUnavailable("\u4ec5\u652f\u6301 Windows \u5fae\u4fe1 4.x\u3002")
    library = ctypes.WinDLL(str(path))
    library.InitializeHook.argtypes = [wintypes.DWORD]
    library.InitializeHook.restype = wintypes.BOOL
    library.PollKeyData.argtypes = [ctypes.c_char_p, ctypes.c_int32]
    library.PollKeyData.restype = wintypes.BOOL
    library.CleanupHook.argtypes = []
    library.CleanupHook.restype = wintypes.BOOL
    library.GetLastErrorMsg.argtypes = []
    library.GetLastErrorMsg.restype = ctypes.c_char_p
    return _WxKeyHookApi(library)


class _WxKeyHookApi:
    """Thin ctypes adapter around the verified wx_key.dll exports."""

    def __init__(self, library: Any) -> None:
        self._initialize = library.InitializeHook
        self._poll = library.PollKeyData
        self._cleanup = library.CleanupHook
        self._error = library.GetLastErrorMsg

    def initialize(self, pid: int) -> bool:
        return bool(self._initialize(pid))

    def poll_key(self, buffer: Any, size: int) -> bool:
        return bool(self._poll(buffer, size))

    def cleanup(self) -> bool:
        return bool(self._cleanup())

    def error_message(self) -> bytes:
        return self._error() or b""


def _find_weixin_pids() -> list[int]:
    """Return every running Weixin.exe process id, never raising."""
    if os.name != "nt":
        return []

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32W),
    ]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry32W),
    ]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot in (0, ctypes.c_void_p(-1).value):
        return []

    pids: list[int] = []
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(ProcessEntry32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == WECHAT_PROCESS_NAME.lower():
                pids.append(int(entry.th32ProcessID))
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return pids


__all__ = [
    "WeChatKeyService",
    "WeChatKeyUnavailable",
    "_extract_key",
]
