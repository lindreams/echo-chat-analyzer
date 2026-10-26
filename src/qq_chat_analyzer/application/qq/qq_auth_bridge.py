"""Application-layer bridge that starts and tracks QQ authorization.

The bundled Echo NapCat launcher owns the QQ login window.

``start_auth_flow()`` reuses the existing setup/connection services to start
the runtime, opens the runtime's own login window, and returns a lifecycle
snapshot. The caller keeps polling ``get_snapshot()`` (or the facade's
snapshot method) until the snapshot reports ``CONNECTED``; that probe path is
the existing provider health/data check, so no new state machine is needed.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from ...runtime.windows_job import launch_owned_process

from ..connection_models import ConnectionSnapshot, ConnectionState
from .qq_connection_manager import (
    HINT_WAITING_AUTH,
    MESSAGE_WAITING_AUTH,
    QQConnectionManager,
    SOURCE_QQ,
)
from .qq_environment_config import (
    QQConfigNotFound,
    QQEnvironmentConfigLoader,
)
from .qq_process_registry import (
    QQProcessRegistry,
    default_qq_process_registry,
)
from .qq_process_detection import QQProcessDetectionError, find_conflicting_qq_pids
from .qq_version import read_qq_version, read_qq_resources, QQResources, QQVersionConflict
from .qq_runtime_session import default_qq_runtime_session


_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.qq_auth_bridge")
PROGRESS_WAITING_QQ_EXIT = "请完全退出 QQ"
# Explicit minimum in the official NapCat v4.18.33 release notes:
# https://github.com/NapNeko/NapCatQQ/releases/tag/v4.18.33
# Passing this gate is not a claim of full compatibility with the pinned 4.18.34.
_MIN_WINDOWS_QQ_BUILD = 40768
# The Direct DB snapshot helper reports its failure stage and guard code only
# through ``QCE_LOG_FILE`` (a retained historical variable name). Its lines are
# privacy-safe by construction: fixed stage names, stable guard codes, opaque
# generation ids, counters, timestamps and module hashes. Without this channel
# every capture failure collapses into the single public ``snapshot_unstable``
# code, so the real failing stage can never be observed in production.
SNAPSHOT_DIAGNOSTIC_FILENAME = "qq-snapshot-diagnostics.log"


class _AuthCancelled(Exception):
    """Cooperative cancellation before any subsequent lifecycle mutation."""


MESSAGE_ERROR = (
    "\u65e0\u6cd5\u542f\u52a8 QQ \u767b\u5f55\u6388\u6743\uff0c"
    "\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"
)
HINT_RETRY = "\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"
MESSAGE_RUNTIME_UNAVAILABLE = (
    "\u672a\u627e\u5230\u53ef\u7528\u7684 QQ \u8fd0\u884c\u7ec4\u4ef6\uff0c"
    "\u8bf7\u786e\u8ba4 Echo \u5b89\u88c5\u5b8c\u6574\u540e\u91cd\u8bd5\u3002"
)

MESSAGE_WINDOW_MISSING = (
    "\u672a\u627e\u5230 QQ \u767b\u5f55\u7a97\u53e3\u5165\u53e3\uff0c"
    "\u8bf7\u786e\u8ba4\u8fd0\u884c\u73af\u5883\u5b8c\u6574\u540e\u91cd\u8bd5\u3002"
)
MESSAGE_QQ_MISSING = (
    "\u672a\u68c0\u6d4b\u5230 QQ \u5ba2\u6237\u7aef\uff0c"
    "\u8bf7\u5148\u5b89\u88c5 QQ \u540e\u91cd\u8bd5\u3002"
)
QQ_INSTALL_PATH_MISSING_CODE = "qq_install_path_missing"
MESSAGE_MAIN_MISSING = (
    "\u672a\u627e\u5230 QQ \u8fd0\u884c\u65f6\u5165\u53e3\uff0c"
    "\u8bf7\u786e\u8ba4\u8fd0\u884c\u73af\u5883\u5b8c\u6574\u540e\u91cd\u8bd5\u3002"
)

PROGRESS_CHECKING = "正在检查 QQ 运行环境..."
PROGRESS_STARTING = "正在启动 QQ 环境..."
PROGRESS_LOADING_NAPCAT = "正在加载 NapCat..."
PROGRESS_WAITING_LOGIN = "等待 QQ 登录..."
PROGRESS_CONNECTED = "QQ 已连接"


class QQAuthWindowUnavailable(Exception):
    """Raised when the runtime's login window cannot be opened."""

    code = "qq_auth_window_unavailable"
    public_message = MESSAGE_WINDOW_MISSING

    def __init__(
        self,
        public_message: str | None = None,
        *,
        code: str | None = None,
    ) -> None:
        self.code = code or type(self).code
        self.public_message = public_message or type(self).public_message
        super().__init__(self.public_message)


class QQAuthBridge:
    """Start the QQ authorization flow and keep it observable.

    The bridge only composes existing collaborators. Runtime start stays in
    the setup service, QQ data availability stays in the connection service,
    and snapshot mapping stays in the connection manager.
    """

    def __init__(
        self,
        *,
        setup_service: Any = None,
        connection_service: Any = None,
        manager: Any = None,
        window_launcher: Callable[[], Any] | None = None,
        process_registry: QQProcessRegistry | None = None,
        qrcode_path: Path | None = None,
        runtime_cleaner: Callable[[Path], None] | None = None,
        credential: Any = None,
        process_wait_timeout: float = 120,
        process_poll_interval: float = 0.5,
    ) -> None:
        self._setup_service = setup_service
        self._connection_service = connection_service
        self._manager = manager
        self._window_launcher = window_launcher
        self._qrcode_path = qrcode_path
        self._runtime_cleaner = runtime_cleaner
        # One owner for the bridge credential of the runtime Echo launches.
        self._credential_source = credential or default_qq_runtime_session()
        self._process_wait_timeout = process_wait_timeout
        self._process_poll_interval = process_poll_interval
        self._auth_lock = threading.Lock()
        self._cancel_event: threading.Event | None = None
        self._launcher_event: threading.Event | None = None
        self._auth_launch_started = False
        self._launched_process: Any | None = None
        self._qr_session_started = False
        self._qr_baseline: tuple[str, int, int] | None = None
        self._qr_session_started_at: float | None = None
        self._qr_ready_logged = False
        self._process_registry = (
            process_registry or default_qq_process_registry()
        )
        self._runtime_paths = None
        self._session_lock = threading.RLock()
        self._session_generation = 0

    def start_auth_flow(
        self,
        progress: Callable[[str], None] | None = None,
        *,
        cancel_event: threading.Event | None = None,
    ) -> ConnectionSnapshot:
        """Serialize auth attempts; a cancelled detector cannot resume a launch."""
        cancelled = cancel_event or threading.Event()
        with self._auth_lock:
            if cancelled.is_set():
                return self._cancelled_snapshot()
            self._cancel_event = cancelled
            try:
                return self._start_auth_flow(progress, cancelled)
            except _AuthCancelled:
                return self._cancelled_snapshot()
            finally:
                if cancelled.is_set() and self._launcher_event is cancelled:
                    if self._auth_launch_started:
                        self._terminate_runtime_sessions()
                    self._reset_auth_session()
                    self._manager_instance().end_auth_waiting()

    def cancel_auth_flow(self, cancel_event: threading.Event) -> None:
        """Background cleanup only if the cancelled attempt still owns auth."""
        cancel_event.set()
        with self._auth_lock:
            if (
                self._cancel_event is not cancel_event
                or self._launcher_event is not cancel_event
            ):
                return
            self._terminate_runtime_sessions()
            self._reset_auth_session()
            self._manager_instance().end_auth_waiting()

    @staticmethod
    def _check_cancelled(cancelled: threading.Event) -> None:
        if cancelled.is_set():
            raise _AuthCancelled

    @staticmethod
    def _cancelled_snapshot() -> ConnectionSnapshot:
        return ConnectionSnapshot(
            ConnectionState.DISCONNECTED, SOURCE_QQ,
            "已取消 QQ 连接。", code="qq_auth_cancelled",
        )

    def _wait_for_conflicting_processes(
        self,
        progress: Callable[[str], None] | None,
        cancelled: threading.Event,
    ) -> ConnectionSnapshot | None:
        wait_started = time.monotonic()
        deadline = wait_started + self._process_wait_timeout
        waiting = False
        while True:
            self._check_cancelled(cancelled)
            detection_started = time.monotonic()
            try:
                pids = find_conflicting_qq_pids(self._process_registry.recorded())
            except Exception as error:
                self._check_cancelled(cancelled)
                stage, category = "enumeration", "unexpected_failure"
                if isinstance(error, QQProcessDetectionError):
                    stage, category = error.stage, error.category
                _LOGGER.warning(
                    "[qq auth] QQ process detection stage=%s category=%s elapsed_ms=%s",
                    stage, category, int((time.monotonic() - detection_started) * 1000),
                )
                return self._error_snapshot(
                    "无法检测 QQ 进程，请稍后重试。", HINT_RETRY,
                    code="qq_process_detection_failed",
                )
            self._check_cancelled(cancelled)
            # At most the initial conflict and eventual clear; no per-poll list
            # or raw exception details are recorded, even before log filtering.
            if not waiting or not pids:
                _LOGGER.info(
                    "[qq auth] QQ process detection stage=complete category=%s elapsed_ms=%s",
                    "conflict" if pids else "clear",
                    int((time.monotonic() - detection_started) * 1000),
                )
            if not pids:
                return None
            if not waiting:
                _report_progress(progress, PROGRESS_WAITING_QQ_EXIT)
                waiting = True
            self._check_cancelled(cancelled)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _LOGGER.warning(
                    "[qq auth] QQ process detection stage=conflict_wait category=timeout elapsed_ms=%s",
                    int((time.monotonic() - wait_started) * 1000),
                )
                return self._error_snapshot(
                    "等待 QQ 退出超时，请完全退出 QQ 后重新连接。",
                    HINT_RETRY, code="qq_process_exit_timeout",
                )
            cancelled.wait(min(self._process_poll_interval, remaining))

    def _start_auth_flow(
        self,
        progress: Callable[[str], None] | None,
        cancelled: threading.Event,
    ) -> ConnectionSnapshot:
        """Launch QQ authorization and return the immediate lifecycle state.

        When QQ data is already usable this returns ``CONNECTED`` without
        touching the runtime. Otherwise the runtime's own login window is
        opened by the Echo NapCat launcher. Later bridge probes detect login.
        """
        _report_progress(progress, PROGRESS_CHECKING)
        manager = self._manager_instance()
        if self._auth_launch_started and not self._launcher_process_alive():
            self._auth_launch_started = False
        getter = getattr(self._setup_service, "get_runtime_paths", None)
        if callable(getter):
            _LOGGER.info("[qq auth] stage=workspace_prepare outcome=started")
            try:
                self._runtime_paths = getter(prepare=not self._auth_launch_started)
            except Exception as error:
                from .qq_runtime_workspace import QQWorkspaceBusy, QQWorkspaceError
                from .qq_runtime_paths import AmbiguousQQRuntime
                category = (
                    "workspace_busy" if isinstance(error, QQWorkspaceBusy) else
                    "workspace_error" if isinstance(error, QQWorkspaceError) else
                    "ownership_unknown" if isinstance(error, AmbiguousQQRuntime) else
                    "unexpected_error"
                )
                # Only this known code is logged; collaborators' arbitrary code
                # and exception text may contain private runtime information.
                safe_code = "qq_runtime_ownership_unknown" if isinstance(error, AmbiguousQQRuntime) else "unspecified"
                _LOGGER.info(
                    "[qq auth] stage=workspace_prepare outcome=failed failure_code=%s snapshot_code=%s",
                    category, safe_code,
                )
                manager.end_auth_waiting()
                return self._error_snapshot(_public_message(error, MESSAGE_ERROR), HINT_RETRY,
                                            code=getattr(error, "code", None))
            _LOGGER.info("[qq auth] stage=workspace_prepare outcome=success")
        snapshot = self._check_runtime_binding(manager.get_snapshot())
        if snapshot.code == "qq_runtime_identity_mismatch":
            return snapshot
        self._check_cancelled(cancelled)
        _LOGGER.info(
            "[qq auth] start_auth_flow entered state=%s setup_service=%s",
            _state_value(snapshot.state),
            self._setup_service is not None,
        )
        if snapshot.state is ConnectionState.CONNECTED:
            _report_progress(progress, PROGRESS_CONNECTED)
            return snapshot
        if snapshot.state is not ConnectionState.WAITING_AUTH:
            self._auth_launch_started = False
        if self._setup_service is None:
            return self._error_snapshot(MESSAGE_ERROR, HINT_RETRY)

        if snapshot.state in (
            ConnectionState.INITIALIZING,
            ConnectionState.STARTING,
        ):
            return snapshot

        try:
            previous_cancelled = (
                self._launcher_event is not None and self._launcher_event.is_set()
            )
            needs_launch = (
                not self._auth_launch_started
                or not self._launcher_process_alive()
                or previous_cancelled
            )
            if needs_launch:
                self._check_cancelled(cancelled)
                self._reset_auth_session()
                self._launcher_event = cancelled
                self._process_registry.terminate_all()
                self._clean_stale_runtime()
                self._check_cancelled(cancelled)
                if self._process_registry.recorded():
                    return self._error_snapshot(
                        "无法清理 Echo 的旧 QQ 连接，请退出 Echo 后重试。",
                        HINT_RETRY,
                        code="qq_runtime_cleanup_failed",
                    )
                failure = self._wait_for_conflicting_processes(progress, cancelled)
                if failure is not None:
                    return failure
                self._check_cancelled(cancelled)
                self._remember_qr_baseline()
            _report_progress(progress, PROGRESS_STARTING)
            _report_progress(progress, PROGRESS_LOADING_NAPCAT)
            self._check_cancelled(cancelled)
            manager.begin_auth_waiting()
            _LOGGER.info("[qq auth] opening login window")
            self._launch_window(cancelled)
            self._check_cancelled(cancelled)
        except _AuthCancelled:
            manager.end_auth_waiting()
            raise
        except Exception as error:
            manager.end_auth_waiting()
            _LOGGER.warning(
                "[qq auth] login window launch failed error=%s",
                type(error).__name__,
            )
            return self._error_snapshot(
                _public_message(error, MESSAGE_ERROR),
                HINT_RETRY,
                code=getattr(error, "code", None),
            )
        _LOGGER.info("[qq auth] login window launched")
        _report_progress(progress, PROGRESS_WAITING_LOGIN)

        latest = self._check_runtime_binding(manager.get_snapshot())
        self._check_cancelled(cancelled)
        if latest.state is ConnectionState.CONNECTED:
            manager.end_auth_waiting()
            _report_progress(progress, PROGRESS_CONNECTED)
            return latest
        if latest.state is ConnectionState.ERROR:
            manager.end_auth_waiting()
            return latest
        return replace(
            latest,
            state=ConnectionState.WAITING_AUTH,
            message=MESSAGE_WAITING_AUTH,
            action_hint=HINT_WAITING_AUTH,
        )

    def get_snapshot(self) -> ConnectionSnapshot:
        """Return the current lifecycle snapshot for continued detection."""
        return self._check_runtime_binding(self._manager_instance().get_snapshot())

    def _check_runtime_binding(self, snapshot: ConnectionSnapshot) -> ConnectionSnapshot:
        """Refuse a connected bridge from a different managed path contract."""
        config = self._environment_config()
        if (snapshot.state is not ConnectionState.CONNECTED or self._runtime_paths is None
                or getattr(config, "runtime_mode", None) != "managed"):
            _LOGGER.info("[qq auth] stage=runtime_binding outcome=skipped")
            return snapshot
        from ...providers.napcat_qq_provider import NapCatQQProvider
        try:
            status = NapCatQQProvider(
                config.napcat_bridge_url, timeout=1, credential=self._credential_source
            ).status()
            if status.runtime_id == self._runtime_paths.runtime_id:
                _LOGGER.info("[qq auth] stage=runtime_binding outcome=success")
                return snapshot
            category = "runtime_identity_mismatch"
        except Exception:
            category = "binding_probe_failed"
        _LOGGER.info(
            "[qq auth] stage=runtime_binding outcome=failed failure_code=%s snapshot_code=qq_runtime_identity_mismatch",
            category,
        )
        return self._error_snapshot(MESSAGE_ERROR, HINT_RETRY, code="qq_runtime_identity_mismatch")

    def is_qrcode_ready(self) -> bool:
        """Return whether the QR cache belongs to the current auth session.

        No QR file is accepted until this Echo instance has started its own
        auth session; otherwise a QR left by an earlier runtime session would
        be shown and scanned as if it were fresh.

        A fresh auth flow records the QR cache state before launching NapCat.
        Until the file changes, any pre-existing ``qrcode.png`` is treated as
        stale and must not be shown to the user.
        """
        if not self._qr_session_started:
            return False
        path = self._qrcode_cache_path()
        if path is None:
            return False
        fingerprint = _qr_fingerprint(path)
        if fingerprint is None:
            self._qr_ready_logged = False
            return False
        fresh = (
            self._qr_baseline is None
            or fingerprint != self._qr_baseline
        )
        if fresh:
            if self._qr_baseline is not None and not self._qr_ready_logged:
                _LOGGER.info("[qq auth] qr accepted")
                self._qr_ready_logged = True
        else:
            self._qr_ready_logged = False
        return fresh

    def get_qrcode_path(self) -> Path | None:
        """Return the current auth session's fresh QR path, or no image."""
        if not self.is_qrcode_ready():
            return None
        return self._qrcode_cache_path()

    def disconnect(self) -> ConnectionSnapshot:
        """Stop the LCA-owned QQ session and return a disconnected snapshot.

        Runtime files and the stored QQ configuration are left untouched; only
        the running login session is stopped so a different account can start
        a fresh QR flow.
        """
        _LOGGER.info("[qq auth] disconnect requested")
        with self._session_lock:
            self._session_generation += 1
            self._terminate_runtime_sessions()
            self._reset_auth_session()
        return self._manager_instance().disconnect()

    # ---------------------------------------------------------------- internals

    def _manager_instance(self) -> QQConnectionManager:
        if self._manager is None:
            self._manager = QQConnectionManager(
                setup_service=self._setup_service,
                connection_service=self._connection_service,
            )
        return self._manager

    def _launch_window(self, cancelled: threading.Event | None = None) -> None:
        cancelled = cancelled or threading.Event()
        self._check_cancelled(cancelled)
        self._launcher_event = cancelled
        with self._session_lock:
            generation = self._session_generation
        if self._auth_launch_started and self._launcher_process_alive():
            _LOGGER.info("[qq auth] launcher already started; reusing")
            return
        self._auth_launch_started = False
        if self._window_launcher is not None:
            _LOGGER.info("[qq auth] using injected window launcher")
            process = self._window_launcher()
        else:
            try:
                config = self._setup_service.get_environment_config()
            except QQConfigNotFound:
                config = self._recover_environment_config()
            _LOGGER.info("[qq auth] building default window launcher")
            try:
                launcher = default_auth_window_launcher(
                    config, paths=self._runtime_paths, credential=self._credential_source
                )
            finally:
                # Cancellation wins even if the completed version read would
                # otherwise reject this attempt as too old.
                self._check_cancelled(cancelled)
            process = launcher()
        with self._session_lock:
            if generation != self._session_generation:
                close = getattr(process, "close", None)
                try:
                    if callable(close):
                        close()
                finally:
                    self._credential_source.retire_process(process)
                raise QQAuthWindowUnavailable()
            self._auth_launch_started = True
            self._launched_process = process
            if callable(getattr(process, "close", None)):
                self._process_registry.record_process(process)
            elif getattr(process, "pid", None) is not None:
                self._process_registry.record(getattr(process, "pid", None))

    def _launcher_process_alive(self) -> bool:
        """Return whether the launched window process is still running.

        An injected launcher does not expose a process, so it is treated as
        alive to preserve the single-launch guard used by tests and stubs.
        """
        process = self._launched_process
        if process is None:
            return True
        tree_running = getattr(process, "tree_running", None)
        if callable(tree_running):
            return tree_running()
        poll = getattr(process, "poll", None)
        if not callable(poll):
            return True
        return poll() is None

    def _terminate_runtime_sessions(self) -> None:
        """Stop owned processes and bundled runtime sessions, best-effort.

        The instance's credential is retired as well: once Echo has asked its own
        runtime to stop, a value minted for it must not be able to reach whatever
        might answer on the port later. The direction of this decision is
        deliberate - failing closed on later probes is preferred over keeping a
        credential alive for an instance Echo just stopped. A kill that failed is
        still retained by the process registry for retry, and orphan plaintext is
        also swept by the runtime's own in-process recovery.
        """
        try:
            self._process_registry.terminate_all()
        except Exception as error:
            _LOGGER.warning(
                "[qq auth] disconnect process cleanup failed error=%s",
                type(error).__name__,
            )
        config = self._environment_config()
        if config is None:
            return self._retire_bridge_credential()
        directory = _path_value(getattr(config, "runtime_directory", None))
        if self._runtime_paths is not None:
            directory = self._runtime_paths.program_root
        if directory is None:
            return self._retire_bridge_credential()
        cleaner = self._runtime_cleaner or terminate_bundled_runtime_sessions
        try:
            cleaner(directory)
        except Exception as error:
            _LOGGER.warning(
                "[qq auth] disconnect runtime cleanup failed error=%s",
                type(error).__name__,
            )
        self._retire_bridge_credential()

    def _retire_bridge_credential(self) -> None:
        """Drop the credential of the runtime session Echo just stopped."""
        retire = getattr(self._credential_source, "retire", None)
        if callable(retire):
            retire()

    def _reset_auth_session(self) -> None:
        """Forget the current launcher/QR session so the next login is fresh."""
        self._auth_launch_started = False
        self._launched_process = None
        self._qr_session_started = False
        self._qr_baseline = None
        self._qr_session_started_at = None
        self._qr_ready_logged = False
        self._launcher_event = None

    def _recover_environment_config(self) -> Any:
        """Persist the effective default config, then return it for launch.

        The launcher still owns the runtime lifecycle, so recovery only
        writes qq.json without starting a process.
        """
        _LOGGER.info("[qq auth] environment config missing; auto-initializing")
        try:
            config = QQEnvironmentConfigLoader().load_or_default()
            saver = getattr(self._setup_service, "save_environment", None)
            if not callable(saver):
                raise QQConfigNotFound()
            saver(config)
            return self._setup_service.get_environment_config()
        except QQConfigNotFound:
            raise QQConfigNotFound(MESSAGE_RUNTIME_UNAVAILABLE) from None

    def _remember_qr_baseline(self) -> None:
        """Record the QR cache state that predates this auth session."""
        self._qr_session_started = True
        self._qr_session_started_at = time.monotonic()
        self._qr_ready_logged = False
        path = self._qrcode_cache_path()
        self._qr_baseline = _qr_fingerprint(path)
        if path is None:
            _LOGGER.info("[qq auth] qr baseline unavailable")
            return
        if self._qr_baseline is None:
            _LOGGER.info("[qq auth] qr baseline missing")
            return
        _LOGGER.info("[qq auth] qr baseline exists")

    def _clean_stale_runtime(self) -> None:
        """Stop old Echo-launched runtime sessions before a fresh launch."""
        if self._runtime_cleaner is None:
            return
        config = self._environment_config()
        if config is None:
            return
        directory = _path_value(getattr(config, "runtime_directory", None))
        if self._runtime_paths is not None:
            directory = self._runtime_paths.program_root
        if directory is None:
            return
        _LOGGER.info("[qq auth] stopping stale runtime sessions")
        try:
            self._runtime_cleaner(directory)
        except Exception as error:
            _LOGGER.warning(
                "[qq auth] stale runtime cleanup failed error=%s",
                type(error).__name__,
            )

    def _qrcode_cache_path(self) -> Path | None:
        """Resolve the bundled runtime's QR cache path when available."""
        if self._qrcode_path is not None:
            return Path(self._qrcode_path)
        if self._runtime_paths is not None:
            return self._runtime_paths.work_root / "cache/qrcode.png"
        config = self._environment_config()
        if config is None:
            return None
        directory = _path_value(getattr(config, "runtime_directory", None))
        if directory is None:
            return None
        return directory / "cache" / "qrcode.png"

    def _environment_config(self) -> Any:
        if self._setup_service is None:
            return None
        getter = getattr(self._setup_service, "get_environment_config", None)
        if getter is None:
            return None
        try:
            return getter()
        except Exception:
            _LOGGER.debug("[qq auth] environment config unavailable")
            return None

    @staticmethod
    def _error_snapshot(
        message: str,
        action_hint: str,
        *,
        code: str | None = None,
    ) -> ConnectionSnapshot:
        return ConnectionSnapshot(
            state=ConnectionState.ERROR,
            source=SOURCE_QQ,
            message=message,
            action_hint=action_hint,
            code=code,
        )


def default_auth_window_launcher(config: Any, *, paths=None, credential: Any = None) -> Callable[[], None]:
    """Build a callable that opens the bundled runtime's login window.

    The runtime's own launcher decides the login form; this code only locates
    the launcher, the QQ install, and the injection hook. No QR code or
    account number is assumed or passed.

    ``credential`` is the session that owns the bridge credential for the
    instance this launcher starts; when it is omitted the process-wide default
    session is used, so a launch never produces a bridge without a credential.
    """
    from .qq_runtime_paths import resolve_runtime_paths
    paths = paths or resolve_runtime_paths(config, prepare=True)
    runtime_directory = paths.program_root
    qq_path = resolve_qq_install_path(config, runtime_directory)
    if qq_path is None or not qq_path.is_file():
        raise QQAuthWindowUnavailable(MESSAGE_QQ_MISSING, code=QQ_INSTALL_PATH_MISSING_CODE)
    # Capture the same executable for the version read and the eventual command;
    # do not resolve a different install again inside the launch callable.
    qq_path = qq_path.resolve()
    resources = _checked_qq_resources(qq_path)
    _check_qq_version(qq_path, resources=resources)
    if not (runtime_directory / "NapCatWinBootMain.exe").is_file() or not (runtime_directory / "NapCatWinBootHook.dll").is_file():
        raise QQAuthWindowUnavailable(MESSAGE_WINDOW_MISSING)
    managed = getattr(config, "runtime_mode", None) == "managed"
    return lambda: _launch_auth_window(runtime_directory, runtime_directory / "NapCatWinBootMain.exe", qq_path,
                                       paths=paths, managed=managed, credential=credential, resources=resources)


def _check_qq_version(qq_path: Path, *, resources: QQResources | None = None) -> None:
    """Reject only a reliably identified build below the documented minimum."""
    started = time.monotonic()
    version = _known_qq_version(qq_path, resources=resources)
    result = "unknown"
    if version is not None:
        result = "below_minimum" if version[3] < _MIN_WINDOWS_QQ_BUILD else "minimum_met"
    _LOGGER.info("[qq auth] version_check result=%s qq_version=%s elapsed_ms=%s", result,
                 ".".join(str(part) for part in version) if version is not None else "unknown",
                 max(0, int((time.monotonic() - started) * 1000)))
    if result == "below_minimum":
        major, minor, patch, build = version
        raise QQAuthWindowUnavailable(
            f"当前 QQ 版本过旧（检测到 {major}.{minor}.{patch}-{build}），"
            "暂不符合 Echo 内置 NapCat 的兼容要求，请更新 QQ 后重试。",
            code="qq_version_too_old",
        )


def _checked_qq_resources(path: Path) -> QQResources | None:
    try:
        return read_qq_resources(path)
    except QQVersionConflict:
        raise QQAuthWindowUnavailable(
            "QQ 程序资源的版本信息不一致，请完成 QQ 更新后重试。",
            code="qq_version_metadata_conflict",
        ) from None
    except (OSError, ValueError, RuntimeError):
        raise QQAuthWindowUnavailable(
            "无法确认 QQ 当前启用的程序资源，请完成 QQ 更新后重试。",
            code="qq_resources_unverified",
        ) from None


def _known_qq_version(path: Path, *, resources: QQResources | None = None) -> tuple[int, int, int, int] | None:
    try:
        resources = resources if resources is not None else read_qq_resources(path)
        version = resources.version if resources is not None else None
        if version is not None and version[3] >= _MIN_WINDOWS_QQ_BUILD and resources.wrapper_path is None:
            return None
    except Exception:
        return None
    known = (
        isinstance(version, tuple) and len(version) == 4
        and all(type(part) is int and 0 <= part <= 65535 for part in version)
        and version[:2] == (9, 9) and version[3] > 0
    )
    return version if known else None


def resolve_qq_install_path(
    config: Any,
    runtime_directory: Path | None = None,
) -> Path | None:
    """Resolve the QQ install executable for the bundled runtime.

    Explicit API/user settings win. Automatic discovery compares historical
    config, launcher cache, script and registry/common-directory candidates.
    Prefer the first confirmed minimum build; otherwise retain source order
    so unknown metadata never supplies a compatibility verdict.
    """
    configured = _path_value(getattr(config, "qq_install_path", None))
    if configured is not None and getattr(config, "qq_install_path_explicit", False) is True:
        return _existing_qq_executable(configured)

    directory = runtime_directory or _runtime_directory(config)
    saved = _read_saved_qq_path(directory / "config" / "qq_path.txt")
    candidates = [configured, saved]
    detector = directory / "find-qq.ps1"
    if detector.is_file():
        detected = _detect_qq_path_with_script(detector)
        candidates.append(detected)
    candidates.extend(_qq_install_candidates())
    return _select_qq_install_path(candidates)


def _existing_qq_executable(path: Path | None) -> Path | None:
    try:
        if path is not None and path.name.lower() == "qq.exe" and path.is_file():
            return path.resolve()
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def _select_qq_install_path(candidates: list[Path | None]) -> Path | None:
    first = None
    seen: set[Path] = set()
    for candidate in candidates:
        path = _existing_qq_executable(candidate)
        if path is None or path in seen:
            continue
        seen.add(path)
        if first is None:
            first = path
        version = _known_qq_version(path)
        if version is not None and version[3] >= _MIN_WINDOWS_QQ_BUILD:
            return path
    return first


def _runtime_directory(config: Any) -> Path:
    directory = _path_value(getattr(config, "runtime_directory", None))
    return directory if directory is not None else Path(".")


def _path_value(value: Any) -> Path | None:
    if value is None:
        return None
    if isinstance(value, Path):
        return value
    text = str(value).strip()
    return Path(text) if text else None


def _read_saved_qq_path(path: Path) -> Path | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in raw.splitlines():
        candidate = line.strip().strip('"')
        if not candidate:
            continue
        resolved = _existing_qq_executable(Path(candidate))
        if resolved is not None:
            return resolved
    return None


def _detect_qq_install_path() -> Path | None:
    """Select a QQ.exe from the bounded registry/common locations."""
    return _select_qq_install_path(_qq_install_candidates())


def _qq_install_candidates() -> list[Path]:
    candidates: list[Path] = []
    if os.name == "nt":
        try:
            import winreg
        except ImportError:
            winreg = None
        if winreg is not None:
            candidates.extend(_registry_qq_install_candidates(winreg))
    candidates.extend(_common_qq_install_candidates())
    return candidates


def _registry_qq_install_candidates(winreg: Any) -> list[Path]:
    candidates: list[Path] = []
    for root, subkey in (
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
        ),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
        ),
        (
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQ",
        ),
    ):
        values = _registry_values(winreg, root, subkey)
        if not values:
            continue
        display = _strip_icon_index(values.get("DisplayIcon"))
        if display:
            candidates.append(Path(os.path.expandvars(display)))
        location = _registry_text(values.get("InstallLocation"))
        if location:
            candidates.append(Path(os.path.expandvars(location)) / "QQ.exe")
        uninstall = _registry_text(values.get("UninstallString"))
        if uninstall:
            command = uninstall.strip('"')
            if command:
                candidates.append(
                    Path(os.path.expandvars(command)).parent / "QQ.exe"
                )

    for root, subkey in (
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\QQ.exe",
        ),
        (
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\QQ.exe",
        ),
    ):
        values = _registry_values(winreg, root, subkey)
        if values:
            default = _registry_text(values.get(""))
            if default:
                candidates.append(Path(os.path.expandvars(default)))

    values = _registry_values(
        winreg,
        winreg.HKEY_CLASSES_ROOT,
        r"Tencent\shell\open\command",
    )
    if values:
        command = _registry_text(values.get(""))
        if command:
            match = re.search(r'"([^"]+)"', command)
            if match:
                directory = Path(match.group(1)).parent
                for _ in range(6):
                    candidates.append(directory / "QQ.exe")
                    parent = directory.parent
                    if parent == directory:
                        break
                    directory = parent
    return candidates


def _registry_values(winreg: Any, root: Any, subkey: str) -> dict[str, str]:
    try:
        with winreg.OpenKey(root, subkey) as key:
            values: dict[str, str] = {}
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                text = _registry_text(value)
                if text is not None:
                    values[name] = text
                index += 1
            return values
    except OSError:
        return {}


def _registry_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _strip_icon_index(value: Any) -> str | None:
    text = _registry_text(value)
    if text is None:
        return None
    match = re.match(r"^(.*?),\s*\d+$", text)
    if match:
        return match.group(1).strip().strip('"') or None
    return text.strip('"') or None


def _common_qq_install_candidates() -> list[Path]:
    roots: list[Path] = []
    for name in (
        "ProgramFiles",
        "ProgramFiles(x86)",
        "ProgramW6432",
        "LOCALAPPDATA",
    ):
        value = os.environ.get(name)
        if value:
            roots.append(Path(value))
    if os.name == "nt":
        system_drive = os.environ.get("SystemDrive", "C:")
        roots.append(Path(system_drive) / "Program Files")
        roots.append(Path(system_drive) / "Program Files (x86)")
    roots.extend((Path("D:/Program Files"), Path("D:/Program Files (x86)")))
    patterns = (
        Path("Tencent/QQNT/QQ.exe"),
        Path("Tencent/QQNT/Bin/QQ.exe"),
        Path("Tencent/QQ/QQ.exe"),
        Path("Tencent/QQ/Bin/QQ.exe"),
    )
    return [root / pattern for root in roots for pattern in patterns]


def _detect_qq_path_with_script(script: Path) -> Path | None:
    options = {
        "capture_output": True,
        "text": True,
        "timeout": 10,
        "check": False,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ],
            **options,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in (completed.stdout or "").splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        resolved = _existing_qq_executable(Path(candidate))
        if resolved is not None:
            return resolved
    return None


def terminate_bundled_runtime_sessions(runtime_directory: Path) -> None:
    """Legacy no-op: a runtime directory is not evidence of ownership.

    Only the caller's registry may close its Jobs. Old-version orphans and
    another Echo's processes must never be adopted by executable-path scans.
    """
    _LOGGER.info("[qq auth] path-only runtime cleanup skipped; ownership required")


def _snapshot_diagnostic_log_path() -> Path | None:
    """Return the acquisition diagnostic log path, or ``None`` if unavailable.

    Best effort only: a diagnostic channel must never block the QQ launch.
    The file lives beside ``echo.log`` so support can collect it with the rest
    of the desktop diagnostics, and it carries only the privacy-safe lines the
    snapshot helper already produces.
    """
    try:
        from ...diagnostics import log_path

        path = log_path().parent / SNAPSHOT_DIAGNOSTIC_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:  # pragma: no cover - defensive, diagnostics are optional
        _LOGGER.info("[qq auth] snapshot diagnostic channel unavailable")
        return None


def _launch_auth_window(
    runtime_directory: Path,
    launcher: Path,
    qq_path: Path,
    *, paths=None, managed=False, credential=None, resources: QQResources | None = None,
) -> Any:
    """Open the runtime login window once, without waiting for login."""
    current = _checked_qq_resources(qq_path)
    if resources is not None and current != resources:
        raise QQAuthWindowUnavailable(
            "QQ 程序资源已变化，请重试连接。", code="qq_resources_changed",
        )
    if resources is None and current is not None:
        _check_qq_version(qq_path, resources=current)
    resources = resources if resources is not None else current
    if resources is None:
        raise QQAuthWindowUnavailable(MESSAGE_QQ_MISSING)
    if resources.version is None or resources.wrapper_path is None:
        raise QQAuthWindowUnavailable(
            "无法确认 QQ 当前启用的程序资源，请完成 QQ 更新后重试。",
            code="qq_resources_unverified",
        )
    environment = os.environ.copy()
    environment.pop("ECHO_MODE", None)
    # Quick-login credentials may belong to other NapCat setups on the host;
    # these three variables must not leak into Echo's child process.
    environment.pop("NAPCAT_QUICK_ACCOUNT", None)
    environment.pop("NAPCAT_QUICK_PASSWORD", None)
    environment.pop("NAPCAT_QUICK_PASSWORD_MD5", None)
    for key in ("NAPCAT_QQ_VERSION_CONFIG_PATH", "NAPCAT_QQ_PACKAGE_INFO_PATH", "NAPCAT_WRAPPER_PATH"):
        environment.pop(key, None)
    environment["NAPCAT_QQ_PATH"] = str(qq_path.resolve())
    import json
    work_root = paths.work_root if paths is not None else runtime_directory
    _ensure_load_script(runtime_directory, work_root)
    package = json.loads(resources.package_text)
    package["main"] = "./loadNapCat.js"
    if resources.version is not None:
        major, minor, patch, build = resources.version
        package["version"] = package["curVersion"] = f"{major}.{minor}.{patch}-{build}"
        package["buildVersion"] = str(build)
    patch_package = work_root / "qqnt.echo.json"
    patch_package.write_text(json.dumps(package), encoding="utf-8")
    environment["NAPCAT_QQ_PACKAGE_INFO_PATH"] = str(patch_package)
    if resources.version is not None:
        # Reuse the owned bootstrap file to bind NapCat's version and package
        # lookup to the same validated resource version, including base installs.
        environment["NAPCAT_QQ_VERSION_CONFIG_PATH"] = str(patch_package)
    if resources.wrapper_path is not None:
        environment["NAPCAT_WRAPPER_PATH"] = str(resources.wrapper_path)
    environment.update({
        "NAPCAT_PATCH_PACKAGE": str(patch_package),
        "NAPCAT_LOAD_PATH": str(work_root / "loadNapCat.js"),
        "NAPCAT_WORKDIR": str(work_root),
        "NAPCAT_INJECT_PATH": str(runtime_directory / "NapCatWinBootHook.dll"),
        "NAPCAT_MAIN_PATH": str(runtime_directory / "napcat.mjs"),
        "ECHO_BRIDGE_PORT": "40655",
        "NAPCAT_DISABLE_FFMPEG_DOWNLOAD": "1",
    })
    if paths is not None:
        environment["ECHO_SNAPSHOT_ROOT"] = str(paths.snapshot_root)
    # The snapshot helper's acquisition diagnostics are opt-in through a path
    # Echo owns. An inherited value is never trusted, so a foreign parent
    # environment cannot redirect or silence the channel.
    environment.pop("QCE_LOG_FILE", None)
    diagnostic_log = _snapshot_diagnostic_log_path()
    if diagnostic_log is not None:
        environment["QCE_LOG_FILE"] = str(diagnostic_log)
    environment.pop("ECHO_RUNTIME_ID", None)
    if managed:
        environment["ECHO_RUNTIME_ID"] = paths.runtime_id
    # Mint this launch's own credential and hand it to the child through its
    # private environment only. A value inherited from the parent is never
    # trusted, and Echo's own environment never carries one.
    session = credential or default_qq_runtime_session()
    environment.pop("ECHO_BRIDGE_TOKEN", None)
    token = session.begin_launch()
    environment["ECHO_BRIDGE_TOKEN"] = token
    command = [str(launcher), str(qq_path), environment["NAPCAT_INJECT_PATH"]]
    _LOGGER.info("[qq auth] launch requested")
    launch_options = {
        "cwd": str(work_root),
        "env": environment,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        launch_options["creationflags"] = subprocess.CREATE_NO_WINDOW
    process = None
    try:
        spawn = launch_owned_process if os.name == "nt" else subprocess.Popen
        process = spawn(
            command,
            **launch_options,
        )
        return_code = process.poll()
    except Exception as error:
        _LOGGER.warning(
            "[qq auth] launch failed error=%s",
            type(error).__name__,
        )
        session.retire(token)
        close = getattr(process, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        raise QQAuthWindowUnavailable() from None
    _LOGGER.info(
        "[qq auth] launch result pid=%s returncode=%s",
        getattr(process, "pid", None),
        return_code,
    )
    if return_code not in (None, 0):
        session.retire(token)
        # Descendants can retain stdout/stderr after the launcher fails. Kill
        # our Job before draining, otherwise synchronous log collection hangs.
        close = getattr(process, "close", None)
        if callable(close):
            close()
    communicate = getattr(process, "communicate", None)
    if callable(communicate):
        if return_code is None:
            threading.Thread(
                target=_log_launcher_completion,
                args=(process,),
                name="echo-qq-launcher-log",
                daemon=True,
            ).start()
        else:
            _log_launcher_completion(process)
    if return_code not in (None, 0):
        # A launch that never produced a running instance must not leave a
        # credential behind for whatever else might answer on that port.
        session.retire(token)
        raise QQAuthWindowUnavailable()
    session.bind_process(process, token)
    return process


def _log_launcher_completion(process: Any) -> None:
    """Consume launcher pipes and record its eventual result without blocking."""
    try:
        stdout, stderr = process.communicate()
    except Exception as error:
        _LOGGER.warning(
            "[qq auth] launcher output unavailable error=%s",
            type(error).__name__,
        )
        return
    _LOGGER.info(
        "[qq auth] launcher completed returncode=%s stdout=%s stderr=%s",
        getattr(process, "returncode", process.poll()),
        f"bytes={len(stdout or '')}",
        f"bytes={len(stderr or '')}",
    )


def _ensure_load_script(runtime_directory: Path, work_root: Path | None = None) -> None:
    """Refresh the bootstrap file the launcher injects into QQ."""
    napcat_main = (runtime_directory / "napcat.mjs").resolve()
    if not napcat_main.is_file():
        raise QQAuthWindowUnavailable(MESSAGE_MAIN_MISSING)
    import json
    load_js = (work_root or runtime_directory) / "loadNapCat.js"
    content = (
        '(async () => {await import('
        + json.dumps(napcat_main.as_uri())
        + ')})()\n'
    )
    load_js.write_text(content, encoding="utf-8")


def _public_message(error: Exception, fallback: str) -> str:
    message = getattr(error, "public_message", None)
    if isinstance(message, str) and message.strip():
        return message.strip()
    return fallback


def _report_progress(
    progress: Callable[[str], None] | None,
    message: str,
) -> None:
    """Publish an observed backend stage without affecting the auth flow."""
    if progress is None:
        return
    try:
        progress(message)
    except Exception:
        _LOGGER.debug("[qq auth] progress callback failed")


def _state_value(state: Any) -> Any:
    return getattr(state, "value", state)


def _qr_fingerprint(path: Path | None) -> tuple[str, int, int] | None:
    """Return a stable identity for the QR file, or None when unreadable."""
    if path is None:
        return None
    try:
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return (digest, stat.st_mtime_ns, stat.st_size)


__all__ = [
    "QQAuthBridge",
    "QQAuthWindowUnavailable",
    "default_auth_window_launcher",
    "resolve_qq_install_path",
    "terminate_bundled_runtime_sessions",
]
