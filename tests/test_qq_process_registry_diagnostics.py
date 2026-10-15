"""RED coverage for the runtime termination diagnostics.

Echo left an owned launcher tree running after shutdown and nothing recorded
whether the registry still held the PID, whether taskkill ran, or what it
answered.  These tests pin the privacy-safe diagnostics that answer those
questions.  Only fake PIDs and fake taskkill results are used.
"""

from __future__ import annotations

import importlib
import logging
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

REGISTRY_LOGGER = "qq_chat_analyzer.desktop.qq_process_registry"


def _module():
    return importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_process_registry"
    )


def _nt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module_os_name_target()[0], "name", "nt")
    monkeypatch.setattr(
        module_os_name_target()[1],
        "CREATE_NO_WINDOW",
        0x08000000,
        raising=False,
    )


def module_os_name_target():
    module = _module()
    return module.os, module.subprocess


def test_taskkill_timeout_is_logged_and_reported(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    module = _module()
    _nt(monkeypatch)

    def _timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=5)

    monkeypatch.setattr(module.subprocess, "run", _timeout)

    with caplog.at_level(logging.INFO, logger=REGISTRY_LOGGER):
        result = module._terminate_process_tree(7152)

    assert result is False
    assert "timeout" in caplog.text.lower()


def test_successful_termination_forgets_the_owned_pid() -> None:
    module = _module()
    registry = module.QQProcessRegistry(terminator=lambda pid: True)
    registry.record(7152)

    assert registry.terminate_all() == 1

    assert registry.recorded() == ()


def test_failed_termination_keeps_the_owned_pid_recorded() -> None:
    """A failed kill must not silently drop Echo's ownership record.

    Otherwise the process stays alive with nobody accountable for it and the
    application-exit hook has nothing left to terminate.
    """
    module = _module()
    registry = module.QQProcessRegistry(terminator=lambda pid: False)
    registry.record(7152)

    assert registry.terminate_all() == 1

    assert registry.recorded() == (7152,)


def test_raising_termination_keeps_the_owned_pid_recorded() -> None:
    module = _module()

    def _explode(pid: int) -> None:
        raise OSError("cannot kill")

    registry = module.QQProcessRegistry(terminator=_explode)
    registry.record(7152)

    assert registry.terminate_all() == 1

    assert registry.recorded() == (7152,)


def test_a_retry_after_a_failed_kill_still_targets_the_same_pid() -> None:
    module = _module()
    attempts: list[int] = []

    def _flaky(pid: int) -> bool:
        attempts.append(pid)
        return len(attempts) > 1

    registry = module.QQProcessRegistry(terminator=_flaky)
    registry.record(7152)

    registry.terminate_all()
    registry.terminate_all()

    assert attempts == [7152, 7152]
    assert registry.recorded() == ()
