"""RED-GREEN coverage for who owns the desktop process exit.

``MainWindow.closeEvent`` may not run the cleanup itself and Qt/interpreter
teardown may not decide when the process leaves.  The desktop entry point
starts the window's single-flight shutdown protocol if it has not started yet,
waits for it with a bounded budget, returns on completion and forces the
process out after a timeout.
"""

from __future__ import annotations

import importlib
import os
import sys
import threading
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app_module():
    return importlib.import_module("qq_chat_analyzer.gui.app")


def _thread_named(name: str):
    return next(
        (
            candidate
            for candidate in threading.enumerate()
            if candidate.name == name
        ),
        None,
    )


class _RecordingWindow:
    """Stand in for MainWindow and record the exit-protocol conversation."""

    def __init__(self, finished: bool = True, error: Exception | None = None):
        self._finished = finished
        self._error = error
        self.events: list[str] = []
        self.waits: list[float | None] = []

    def begin_shutdown(self) -> bool:
        self.events.append("begin")
        return True

    def await_shutdown(self, timeout=None) -> bool:
        self.events.append("await")
        self.waits.append(timeout)
        if self._error is not None:
            raise self._error
        return self._finished


def test_exit_starts_and_waits_for_the_window_shutdown_protocol() -> None:
    module = _app_module()
    window = _RecordingWindow()
    exits: list[int] = []

    module._finish_process_exit(0, window=window, hard_exit=exits.append)

    assert window.events == ["begin", "await"]
    assert window.waits == [module.SHUTDOWN_WAIT_SECONDS]
    assert exits == []


def test_exit_still_forces_out_when_the_protocol_times_out() -> None:
    module = _app_module()
    window = _RecordingWindow(finished=False)
    exits: list[int] = []

    started = time.monotonic()
    module._finish_process_exit(1, window=window, hard_exit=exits.append)
    elapsed = time.monotonic() - started

    assert elapsed < 5.0
    assert exits == [1]


def test_exit_arms_a_last_resort_forced_exit_beyond_the_wait() -> None:
    module = _app_module()
    exits: list[int] = []

    module._finish_process_exit(
        4,
        window=_RecordingWindow(),
        hard_exit=exits.append,
    )

    watchdog = _thread_named(module.FORCED_EXIT_THREAD_NAME)
    assert watchdog is not None
    assert watchdog.daemon is True
    assert module.FORCED_EXIT_SECONDS > module.SHUTDOWN_WAIT_SECONDS


def test_forced_exit_watchdog_fires_when_teardown_hangs() -> None:
    module = _app_module()
    exits: list[int] = []

    module._arm_forced_exit(5, exits.append, delay=0.05)

    deadline = time.monotonic() + 2.0
    while not exits and time.monotonic() < deadline:
        time.sleep(0.005)

    assert exits == [5]


def test_hard_exit_uses_the_os_level_forced_exit(
    monkeypatch,
) -> None:
    """The fallback must bypass interpreter and Qt teardown entirely."""
    module = _app_module()
    calls: list[int] = []
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.os, "_exit", calls.append)

    module._hard_exit(9)

    assert calls == [9]
