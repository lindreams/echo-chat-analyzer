"""Tests for the QQ process registry.

Only fake PIDs and injected terminators are used; nothing is ever killed.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _module():
    return importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_process_registry"
    )


class _RecordingTerminator:
    def __init__(self):
        self.terminated: list[int] = []

    def __call__(self, pid: int) -> None:
        self.terminated.append(pid)


def test_record_keeps_only_valid_pids() -> None:
    module = _module()
    registry = module.QQProcessRegistry()

    registry.record(1001)
    registry.record(1001)
    registry.record(0)
    registry.record(-1)
    registry.record(True)
    registry.record(None)

    assert registry.recorded() == (1001,)


def test_terminate_all_stops_only_recorded_pids() -> None:
    module = _module()
    terminator = _RecordingTerminator()
    registry = module.QQProcessRegistry(terminator=terminator)
    registry.record(2001)

    count = registry.terminate_all()

    assert count == 1
    assert terminator.terminated == [2001]
    assert registry.recorded() == ()


def test_terminate_all_never_raises_on_terminator_failure() -> None:
    module = _module()

    def _explode(pid: int) -> None:
        raise OSError("cannot kill")

    registry = module.QQProcessRegistry(terminator=_explode)
    registry.record(3001)

    assert registry.terminate_all() == 1
