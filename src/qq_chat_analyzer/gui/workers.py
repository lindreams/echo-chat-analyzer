"""Background execution for facade calls.

Every facade call is potentially slow: listing WeChat sessions touches an
external CLI, and analysis walks the whole message set. Running those on the
Qt main thread would freeze the window, so this module moves them onto a
worker thread and reports back through signals.

The worker knows nothing about analysis. It runs a callable, then emits either
the result or a :class:`FacadeError`. That keeps every decision about *what*
to run on the page, and every decision about *how* to report failure in one
place.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from ..application.facade import FacadeError


GENERIC_ERROR_MESSAGE = (
    "\u5206\u6790\u8fc7\u7a0b\u51fa\u73b0\u672a\u9884\u671f\u7684\u9519"
    "\u8bef\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"
)

# Workers are kept alive until they report completion. The thread pool would
# otherwise delete a finished QRunnable together with its signal object, and
# any cross-thread callback still queued for the UI thread would be dropped.
_PENDING: set["FacadeWorker"] = set()
_RELAYS: set["_CallbackRelay"] = set()

_WORKER_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.worker")




def _invoke(operation: Callable[..., Any], report: Callable[[Any], None] | None) -> Any:
    """Call ``operation``, passing a progress reporter only when one is wanted.

    Existing callers pass zero-argument operations, so the reporter is only
    supplied when a progress callback was registered.
    """
    if report is None:
        return operation()
    return operation(report)


class WorkerSignals(QObject):
    """Signals emitted by :class:`FacadeWorker`."""

    succeeded = Signal(object)
    failed = Signal(str, str)
    finished = Signal()
    progress = Signal(object)


class _CallbackRelay(QObject):
    """Deliver worker callbacks on the thread that created the worker.

    Qt only queues a signal to a QObject receiver. Connecting a signal
    directly to a plain Python lambda runs it on the worker thread, where
    widget updates and ``QTimer.singleShot`` do not behave correctly. This
    relay lives on the GUI thread, so its slots are queued back to it.
    """

    def __init__(
        self,
        on_success: Callable[[Any], None],
        on_error: Callable[[str, str], None],
        on_finished: Callable[[], None] | None,
        on_progress: Callable[[Any], None] | None,
    ) -> None:
        super().__init__()
        self._on_success = on_success
        self._on_error = on_error
        self._on_finished = on_finished
        self._on_progress = on_progress

    @Slot(object)
    def _succeeded(self, result: Any) -> None:
        self._on_success(result)

    @Slot(str, str)
    def _failed(self, code: str, message: str) -> None:
        self._on_error(code, message)

    @Slot(object)
    def _progress(self, message: Any) -> None:
        _WORKER_LOGGER.info("[worker] forward progress: %s", message)
        if self._on_progress is not None:
            self._on_progress(message)

    @Slot()
    def _finished(self) -> None:
        if self._on_finished is not None:
            self._on_finished()
        _RELAYS.discard(self)


class FacadeWorker(QRunnable):
    """Run one facade call off the UI thread."""

    def __init__(
        self,
        operation: Callable[..., Any],
        *,
        reports_progress: bool = False,
        signals_parent: QObject | None = None,
    ) -> None:
        super().__init__()
        self._operation = operation
        self._reports_progress = reports_progress
        self._cancelled = threading.Event()
        self.signals = WorkerSignals(signals_parent)
        self.setAutoDelete(False)
        if signals_parent is not None:
            signals_parent.destroyed.connect(
                lambda _object=None: self.cancel()
            )

    def _emit(
        self,
        signal_name: str,
        *args: Any,
        allow_after_cancel: bool = False,
    ) -> bool:
        """Emit one worker signal unless the worker was stopped or died."""
        if not allow_after_cancel and self._cancelled.is_set():
            return False
        try:
            signal = getattr(self.signals, signal_name)
            signal.emit(*args)
        except RuntimeError as error:
            message = str(error)
            if (
                "Signal source has been deleted" in message
                or "deleted" in message.lower()
            ):
                self._cancelled.set()
                return False
            raise
        return True

    @Slot()
    def run(self) -> None:
        _WORKER_LOGGER.info("[worker] facade operation started")
        try:
            def _report_progress(message: Any) -> None:
                if self._cancelled.is_set():
                    raise _OperationCancelled
                _WORKER_LOGGER.info("[wechat worker] emit progress: %s", message)
                self._emit("progress", message)
                if self._cancelled.is_set():
                    raise _OperationCancelled

            result = _invoke(
                self._operation,
                _report_progress if self._reports_progress else None,
            )
        except _OperationCancelled:
            _WORKER_LOGGER.info("[worker] facade operation cancelled")
        except FacadeError as error:
            if self._cancelled.is_set():
                return
            _WORKER_LOGGER.warning(
                "facade operation failed code=%s message=%s",
                error.code,
                error.public_message,
            )
            self._emit("failed", error.code, error.public_message)
        except Exception as error:
            if self._cancelled.is_set():
                return
            _WORKER_LOGGER.exception("facade operation crashed", exc_info=error)
            self._emit(
                "failed",
                "unexpected_error",
                GENERIC_ERROR_MESSAGE,
            )
        else:
            if self._cancelled.is_set():
                return
            _WORKER_LOGGER.info("[worker] facade operation succeeded")
            self._emit("succeeded", result)
        finally:
            emitted = self._emit(
                "finished",
                allow_after_cancel=True,
            )
            _PENDING.discard(self)
            if not emitted:
                relay = getattr(self, "_callback_relay", None)
                if relay is not None:
                    _RELAYS.discard(relay)

    def cancel(self) -> None:
        """Request cooperative cancellation and suppress late callbacks."""
        self._cancelled.set()


class _OperationCancelled(Exception):
    """Internal control flow used when an operation reaches a progress point."""


def submit(
    operation: Callable[..., Any],
    *,
    on_success: Callable[[Any], None],
    on_error: Callable[[str, str], None],
    on_finished: Callable[[], None] | None = None,
    on_progress: Callable[[Any], None] | None = None,
    pool: QThreadPool | None = None,
) -> FacadeWorker:
    """Queue ``operation`` and wire its outcome to the given callbacks.

    When ``on_progress`` is given, ``operation`` is called with a reporter
    callable it can use to publish intermediate status. The reporter crosses
    back to the UI thread through an object signal (strings remain supported),
    so callers never touch widgets from the worker thread.
    """
    relay = _CallbackRelay(on_success, on_error, on_finished, on_progress)
    worker = FacadeWorker(
        operation,
        reports_progress=on_progress is not None,
        signals_parent=relay,
    )
    worker.signals.succeeded.connect(relay._succeeded)
    worker.signals.failed.connect(relay._failed)
    worker.signals.progress.connect(relay._progress)
    worker.signals.finished.connect(relay._finished)
    worker.signals.finished.connect(lambda: _PENDING.discard(worker))
    worker._callback_relay = relay

    _PENDING.add(worker)
    _RELAYS.add(relay)
    (pool or QThreadPool.globalInstance()).start(worker)
    return worker


def is_idle() -> bool:
    """Read existing worker ownership only; no cancellation or waiting."""
    return not _PENDING and not _RELAYS and QThreadPool.globalInstance().activeThreadCount() == 0


def shutdown() -> bool:
    """Cancel without waiting; report only an already quiescent pool/relay set."""
    for worker in tuple(_PENDING):
        worker.cancel()
    pool = QThreadPool.globalInstance()
    pool.clear()
    return is_idle()


def run_inline(
    operation: Callable[..., Any],
    *,
    on_success: Callable[[Any], None],
    on_error: Callable[[str, str], None],
    on_finished: Callable[[], None] | None = None,
    on_progress: Callable[[Any], None] | None = None,
) -> None:
    """Run ``operation`` on the calling thread.

    Useful for tests and for callers that need a deterministic, synchronous
    result. The failure translation is identical to :func:`submit`, so the
    surrounding page cannot tell the two apart.
    """
    try:
        result = _invoke(operation, on_progress)
    except FacadeError as error:
        on_error(error.code, error.public_message)
    except Exception:
        on_error("unexpected_error", GENERIC_ERROR_MESSAGE)
    else:
        on_success(result)
    finally:
        if on_finished is not None:
            on_finished()
