"""RED-GREEN coverage for the desktop shutdown protocol.

Echo must disappear the moment the user closes the window, but the process
still owns transient Direct DB plaintext and the QQ runtime process tree it
launched.  These tests pin the contract that closes that gap:

* exactly one single-flight background protocol owns the cleanup,
* the protocol is bounded, so a caller can wait for it,
* repeated closes never start a second, competing cleanup.
"""

from __future__ import annotations

import importlib
import sys
import threading
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _module():
    return importlib.import_module("qq_chat_analyzer.gui.shutdown")


def test_begin_runs_the_owner_once_and_reports_completion() -> None:
    module = _module()
    protocol = module.ShutdownProtocol(wait_seconds=2.0)
    calls: list[int] = []

    assert protocol.begin(lambda: calls.append(1)) is True

    assert protocol.wait(2.0) is True
    assert calls == [1]
    assert protocol.started is True
    assert protocol.finished is True
    assert protocol.timed_out is False


def test_repeated_begin_is_single_flight() -> None:
    """A second close must never start a competing shutdown."""
    module = _module()
    protocol = module.ShutdownProtocol(wait_seconds=2.0)
    release = threading.Event()
    calls: list[int] = []

    def _owner() -> None:
        calls.append(1)
        release.wait(5.0)

    assert protocol.begin(_owner) is True
    assert protocol.begin(_owner) is False
    assert protocol.begin(None) is False
    release.set()

    assert protocol.wait(2.0) is True
    assert calls == [1]


def test_wait_is_bounded_and_reports_the_timeout() -> None:
    module = _module()
    protocol = module.ShutdownProtocol(wait_seconds=0.05)
    release = threading.Event()

    protocol.begin(lambda: release.wait(5.0))

    started = time.monotonic()
    assert protocol.wait() is False
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert protocol.timed_out is True
    assert protocol.finished is False

    release.set()
    assert protocol.wait(2.0) is True
    assert protocol.finished is True


def test_owner_failure_still_completes_the_protocol() -> None:
    module = _module()
    protocol = module.ShutdownProtocol(wait_seconds=2.0)

    def _explode() -> None:
        raise RuntimeError("simulated shutdown failure")

    protocol.begin(_explode)

    assert protocol.wait(2.0) is True
    assert protocol.finished is True
    assert protocol.timed_out is False
