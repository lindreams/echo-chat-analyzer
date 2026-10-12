"""Own one bounded, single-flight shutdown protocol for the desktop process.

The window has to disappear the instant the user closes it, but the process
still owns transient Direct DB plaintext and the QQ runtime process tree Echo
launched.  A bare daemon thread cannot carry that responsibility: CPython never
joins daemon threads, so interpreter finalization froze the cleanup mid-flight
and the owned process tree survived.

This module closes that gap with one small protocol object:

* :meth:`ShutdownProtocol.begin` starts the owner callable on exactly one
  daemon thread, and every later call is ignored, so a repeated close can never
  start a second, competing cleanup;
* the protocol is bounded - callers pass their window to
  :meth:`ShutdownProtocol.wait`, which records a timeout instead of raising -
  so a stuck cleanup can never hold the process exit;
* the desktop entry point waits on this object, not on interpreter teardown,
  before the process is allowed to leave.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from ..application.facade import ShutdownResult, ShutdownStatus, ShutdownStepResult


_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.shutdown")

#: Default window the desktop entry point gives the protocol before it forces
#: the process out.  Deliberately larger than the sum of the facade's bounded
#: shutdown steps, so a normal shutdown always finishes and only a wedged one
#: reaches the forced-exit fallback.
DEFAULT_SHUTDOWN_WAIT_SECONDS = 40.0

THREAD_NAME = "echo-shutdown"


class ShutdownProtocol:
    """Run one owned shutdown callable once, on one bounded background thread."""

    def __init__(
        self,
        wait_seconds: float = DEFAULT_SHUTDOWN_WAIT_SECONDS,
    ) -> None:
        self._wait_seconds = wait_seconds
        self._started = threading.Event()
        self._finished = threading.Event()
        self._timed_out = False
        self._elapsed_seconds = 0.0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._result = ShutdownResult()

    @property
    def result(self) -> ShutdownResult:
        """Separate resource evidence from finished/wait task-completion flags."""
        if self._timed_out:
            return ShutdownResult(self._result.steps + (
                ShutdownStepResult('protocol_wait', ShutdownStatus.TIMED_OUT),
            ))
        if not self.finished:
            return ShutdownResult()
        return self._result

    @property
    def wait_seconds(self) -> float:
        """Return the default window a caller should wait for."""
        return self._wait_seconds

    @property
    def started(self) -> bool:
        """Return whether this protocol was started at all."""
        return self._started.is_set()

    @property
    def finished(self) -> bool:
        """Return whether the owner callable has run to completion."""
        return self._finished.is_set()

    @property
    def timed_out(self) -> bool:
        """Return whether a wait gave up before the protocol finished."""
        return self._timed_out

    @property
    def elapsed_seconds(self) -> float:
        """Return how long the owner callable took, once it has finished."""
        return self._elapsed_seconds

    def begin(self, owner: Callable[[], ShutdownResult | None] | None) -> bool:
        """Start the protocol once; every later call is ignored.

        Returns ``True`` only for the call that actually started it.  ``None``
        stands for an owner without a shutdown entry point and completes
        immediately, so the exit path never stalls on a protocol that has
        nothing to do.
        """
        with self._lock:
            if self._started.is_set():
                return False
            self._started.set()
        if owner is None:
            _LOGGER.info("Echo shutdown protocol has nothing to clean up")
            self._finished.set()
            return True
        _LOGGER.info("Echo shutdown protocol started")
        thread = threading.Thread(
            target=self._run,
            args=(owner,),
            name=THREAD_NAME,
            daemon=True,
        )
        self._thread = thread
        thread.start()
        return True

    def wait(self, timeout: float | None = None) -> bool:
        """Wait, bounded, for the protocol and report whether it finished.

        A timeout is recorded rather than raised: the caller decides how to
        fall back, and Echo must never hang on exit.
        """
        budget = self._wait_seconds if timeout is None else timeout
        if self._finished.wait(timeout=max(0.0, budget)):
            return True
        self._timed_out = True
        _LOGGER.warning(
            "Echo shutdown protocol did not finish within %.1fs",
            budget,
        )
        return False

    def _run(self, owner: Callable[[], ShutdownResult | None]) -> None:
        started_at = time.monotonic()
        try:
            result = owner()
            if isinstance(result, ShutdownResult):
                self._result = result
        except BaseException as error:  # noqa: BLE001 - shutdown never raises
            self._result = ShutdownResult((
                ShutdownStepResult('owner', ShutdownStatus.FAILED),
            ))
            _LOGGER.warning(
                "Echo shutdown protocol failed error=%s",
                type(error).__name__,
            )
        finally:
            self._elapsed_seconds = time.monotonic() - started_at
            self._finished.set()
            _LOGGER.info(
                "Echo shutdown protocol finished in %.2fs",
                self._elapsed_seconds,
            )


__all__ = [
    "DEFAULT_SHUTDOWN_WAIT_SECONDS",
    "THREAD_NAME",
    "ShutdownProtocol",
]
