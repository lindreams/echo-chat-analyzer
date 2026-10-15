"""RED coverage for the shutdown diagnostics and the ordered step budget.

Echo's real Windows shutdown abandoned ``direct_db_cleanup`` at the facade's
10s window and then left the owned launcher tree running, with no log line that
could say why.  These tests pin the two things that were missing:

* the facade's Direct DB step window must cover the bounded budget the Direct
  DB service declares for itself (drain + readiness recover), so a normal
  bounded cleanup is never truncated and killed by the process exit; and
* every ordered step, and the Direct DB service internals, must emit
  privacy-safe diagnostics (started / finished / failed / timed out, drain and
  recover boundaries, pid lists) so the next real run is diagnosable.

Only fake services, fake PIDs and fictional values are used.
"""

from __future__ import annotations

import importlib
import logging
import sys
import threading
import time
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

FACADE_LOGGER = "qq_chat_analyzer.desktop.facade"
DIRECT_DB_LOGGER = "qq_chat_analyzer.desktop.qq_direct_database"


def _facade_module():
    return importlib.import_module("qq_chat_analyzer.application.facade")


def _direct_db_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_direct_database_import_service"
    )


def _runtime_module():
    return importlib.import_module(
        "qq_chat_analyzer.providers.qq_direct_snapshot_runtime"
    )


class _SilentClient:
    """A snapshot runtime client that never touches anything real."""

    def __init__(self, fail_after: int | None = None) -> None:
        self.calls = 0
        self._fail_after = fail_after

    def recover(self, *, deadline: float | None = None) -> None:
        self.calls += 1
        if self._fail_after is not None and self.calls > self._fail_after:
            raise _runtime_module().QQSnapshotRuntimeError("fictional failure")

    def acquire(self) -> str:
        raise AssertionError("no generation may be acquired during shutdown")

    def generation_directory(self, generation_id):
        raise AssertionError("no generation directory may be read")

    def cleanup(self, generation_id) -> None:
        raise AssertionError("nothing may be cleaned after shutdown")


class _FakeRegistry:
    def __init__(self, events: list[str] | None = None) -> None:
        self._events = events if events is not None else []

    def terminate_all(self) -> int:
        self._events.append("qq_terminate")
        return 0


# --------------------------------------------------------------- step budget


def test_direct_db_step_window_covers_the_budget_the_service_declares() -> None:
    """A bounded Direct DB cleanup must finish before the runtime is stopped.

    The service settles its own bounded budget before returning; if the facade
    truncates the step below that budget the cleanup is abandoned, the runtime
    is terminated underneath it and the process exit kills it mid-recover.
    """
    events: list[str] = []

    class _BudgetedService:
        shutdown_budget_seconds = 0.30

        def shutdown(self) -> None:
            events.append("direct_db_start")
            time.sleep(0.40)
            events.append("direct_db_end")

    facade = _facade_module().ChatAnalyzerFacade(
        qq_service=_BudgetedService(),
        qq_process_registry=_FakeRegistry(events),
        shutdown_step_seconds=0.05,
    )

    facade.shutdown()

    assert events == ["direct_db_start", "direct_db_end", "qq_terminate"]


# ------------------------------------------------------------- step logging


def test_step_runner_logs_the_timeout_and_keeps_going(
    caplog: pytest.LogCaptureFixture,
) -> None:
    release = threading.Event()
    events: list[str] = []

    class _HungService:
        def shutdown(self) -> None:
            release.wait(5.0)

    facade = _facade_module().ChatAnalyzerFacade(
        qq_service=_HungService(),
        qq_process_registry=_FakeRegistry(events),
        shutdown_step_seconds=0.05,
    )

    with caplog.at_level(logging.INFO, logger=FACADE_LOGGER):
        facade.shutdown()

    assert "exceeded" in caplog.text
    assert "step=direct_db_cleanup" in caplog.text
    assert events == ["qq_terminate"]
    release.set()


# ------------------------------------------------------- direct db logging


def test_direct_db_shutdown_diagnostics_never_leak_private_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = _direct_db_module().QQDirectDatabaseImportService(
        runtime_client=_SilentClient(),
        shutdown_drain_seconds=0.05,
    )
    service.start()

    with caplog.at_level(logging.DEBUG, logger=DIRECT_DB_LOGGER):
        service.shutdown()

    lines = [
        record.getMessage()
        for record in caplog.records
        if record.name == DIRECT_DB_LOGGER
    ]

    assert lines
    lowered = " ".join(lines).lower()
    for forbidden in ("uin", "passphrase", "token", "password", "message"):
        assert forbidden not in lowered
