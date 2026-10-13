"""Retain only resources Echo created, without scanning or adoption.

Windows QQ launch paths register a native Job process object, not a taskkill
PID. Legacy injected runtimes retain PID cleanup for compatibility. A PID
associated with a Job never falls back to the legacy terminator.
"""

from __future__ import annotations

import locale
import logging
import os
import signal
import subprocess
import threading
from typing import Any, Callable
from ..shutdown_models import ShutdownStatus


_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.qq_process_registry")

#: taskkill output is diagnostic only, so it is collapsed to one line and
#: truncated before it reaches the log.
_MAX_OUTPUT_SUMMARY = 200


class QQProcessRegistry:
    """Record launched PIDs and terminate only them, best-effort."""

    def __init__(
        self,
        terminator: Callable[[int], Any] | None = None,
    ) -> None:
        self._terminator = terminator or _terminate_process_tree
        self._pids: set[int] = set()
        self._jobs: dict[int, Any] = {}
        # Tombstones prevent late/repeated legacy registration of a closed Job
        # PID from turning into taskkill against an unrelated, reused PID.
        self._job_pids: set[int] = set()
        self._lock = threading.RLock()
        self._unverified_retired = False
        self._closing = False

    def record_process(self, process: Any) -> None:
        """Retain a session's native resource; never convert it to PID cleanup."""
        pid = getattr(process, "pid", None)
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise ValueError("Invalid owned process PID")
        if not callable(getattr(process, "close", None)):
            raise ValueError("Owned process must have explicit resource cleanup")
        with self._lock:
            if self._closing:
                raise RuntimeError('QQ process registration is closed')
            self._jobs[id(process)] = process
            self._job_pids.add(pid)
            self._pids.discard(pid)
        _LOGGER.info("QQ owned Job recorded pid=%s", pid)

    def record(self, pid: int | None) -> None:
        """Remember one PID LCA launched. Invalid values are ignored."""
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return
        with self._lock:
            if self._closing:
                raise RuntimeError('QQ process registration is closed')
            if pid in self._job_pids:
                return
            self._pids.add(pid)
        _LOGGER.info(
            "QQ owned process recorded pid=%s owned=%s",
            pid,
            len(self._pids),
        )

    def discard(self, pid: int | None) -> None:
        """Forget one PID, e.g. after it was stopped normally."""
        if isinstance(pid, bool) or not isinstance(pid, int):
            return
        with self._lock:
            if pid in self._pids:
                self._unverified_retired = True
            from ...runtime.windows_job import WindowsJobProcess
            for process in self._jobs.values():
                if (process.pid == pid and getattr(process, 'closed', False)
                        and not (type(process) is WindowsJobProcess and process.exit_verified)):
                    self._unverified_retired = True
            self._pids.discard(pid)
            self._jobs = {key: process for key, process in self._jobs.items()
                          if process.pid != pid or not getattr(process, "closed", False)}

    def recorded(self) -> tuple[int, ...]:
        """Return the currently recorded PIDs."""
        with self._lock:
            return tuple(sorted(self._pids | {process.pid for process in self._jobs.values()}))

    def terminate_all(self) -> int:
        """Close owned Jobs, then legacy PIDs; retain failed cleanup for retry."""
        with self._lock:
            count = len(self._jobs)
            for key, process in tuple(self._jobs.items()):
                try:
                    process.close()
                except Exception as error:
                    _LOGGER.warning("QQ Job cleanup failed pid=%s error=%s",
                                    process.pid, type(error).__name__)
                else:
                    from ...runtime.windows_job import WindowsJobProcess
                    if not (type(process) is WindowsJobProcess and process.exit_verified):
                        self._unverified_retired = True
                    self._jobs.pop(key, None)
            if self._pids:
                self._unverified_retired = True
            return count + self._terminate_legacy_pids()

    def shutdown(self) -> ShutdownStatus:
        """Seal registration and collect existing native whole-tree evidence."""
        from ...runtime.windows_job import WindowsJobProcess
        with self._lock:
            self._closing = True
            for process in tuple(self._jobs.values()):
                if type(process) is WindowsJobProcess:
                    try:
                        process.close_with_exit_evidence()
                    except Exception:
                        # Preserve ordinary exit cleanup and ownership on failure.
                        pass
            self.terminate_all()
            if self._jobs or self._pids:
                return ShutdownStatus.FAILED
            return (ShutdownStatus.UNKNOWN if self._unverified_retired
                    else ShutdownStatus.SUCCESS)

    def _terminate_legacy_pids(self) -> int:
        """Terminate every recorded process tree and clear the registry.

        Never raises: a missing process, a permission failure, or a slow
        kill cannot block application shutdown.  A terminator that reports
        ``False``, raises, or times out is counted as failed, so the log can
        tell "no owned PID" apart from "the kill did not work".

        A PID whose termination failed stays recorded.  Ownership has to
        outlive a failed kill: forgetting it would leave the process running
        with nobody accountable for it, and the application-exit hook would
        have nothing left to terminate.
        """
        pids = tuple(sorted(self._pids))
        self._pids.clear()
        _LOGGER.info("QQ runtime termination requested pids=%s", pids)
        failed = 0
        survived: list[int] = []
        for pid in pids:
            _LOGGER.info("QQ runtime terminating pid=%s", pid)
            try:
                result = self._terminator(pid)
            except Exception as error:
                failed += 1
                survived.append(pid)
                _LOGGER.warning(
                    "QQ runtime termination failed pid=%s error=%s",
                    pid,
                    type(error).__name__,
                )
                continue
            if result is False:
                failed += 1
                survived.append(pid)
                _LOGGER.warning("QQ runtime termination failed pid=%s", pid)
        if survived:
            self._pids.update(survived)
        _LOGGER.info(
            "QQ runtime termination finished pids=%s terminated=%s failed=%s "
            "still_owned=%s",
            len(pids),
            len(pids) - failed,
            failed,
            tuple(sorted(self._pids)),
        )
        return len(pids)

    def clear(self) -> None:
        """Forget legacy PIDs; native resources remain owned until closed."""
        with self._lock:
            if self._pids:
                self._unverified_retired = True
            self._pids.clear()


def _output_summary(value: Any) -> str:
    """Collapse and truncate captured taskkill output for the log."""
    if isinstance(value, bytes):
        text = value.decode(locale.getpreferredencoding(False), errors="replace")
    else:
        text = value if isinstance(value, str) else ""
    collapsed = " ".join(text.split())
    if len(collapsed) > _MAX_OUTPUT_SUMMARY:
        return collapsed[:_MAX_OUTPUT_SUMMARY] + "..."
    return collapsed


def _terminate_process_tree(pid: int) -> bool:
    """Stop one recorded process and its children, reporting the outcome."""
    command = ["taskkill", "/PID", str(pid), "/T", "/F"]
    if os.name == "nt":
        try:
            completed = subprocess.run(  # noqa: S603 - fixed args, specific PID only
                command,
                capture_output=True,
                timeout=5,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            _LOGGER.warning(
                "taskkill did not finish pid=%s command=%s timeout=%s",
                pid,
                command,
                5,
            )
            return False
        except OSError as error:
            _LOGGER.warning(
                "taskkill could not start pid=%s command=%s error=%s",
                pid,
                command,
                type(error).__name__,
            )
            return False
        returncode = getattr(completed, "returncode", None)
        _LOGGER.info(
            "taskkill result pid=%s command=%s returncode=%s stdout=%s stderr=%s",
            pid,
            command,
            returncode,
            _output_summary(getattr(completed, "stdout", "")),
            _output_summary(getattr(completed, "stderr", "")),
        )
        return returncode == 0
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _LOGGER.info("taskkill skipped pid=%s reason=process_lookup_error", pid)
        return True
    except OSError as error:
        _LOGGER.warning(
            "taskkill failed pid=%s error=%s",
            pid,
            type(error).__name__,
        )
        return False
    return True


_DEFAULT_REGISTRY = QQProcessRegistry()


def default_qq_process_registry() -> QQProcessRegistry:
    """Return the shared registry used by the desktop application."""
    return _DEFAULT_REGISTRY


__all__ = [
    "QQProcessRegistry",
    "default_qq_process_registry",
]
