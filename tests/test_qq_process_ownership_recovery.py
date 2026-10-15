"""Ownership contracts for Echo-created Jobs and the legacy PID registry.

All process IDs, executable paths, runtime identities, and process-table
responses in this file are fictional.  The injected table is the only thing
that can "terminate" a process; these tests never inspect or control a real
QQ/NapCat process.

Jobs prevent new orphans instead of adopting processes on the next startup.
Port health and executable naming are never ownership proof.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


_MANAGED_RUNTIME_ID = "a" * 64
_MANAGED_LAUNCH_ID = "fictional-managed-launch-0001"
_LAUNCHER_PID = 48101


def _registry_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_process_registry"
    )


def _runtime_manager_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_runtime_manager"
    )


def _facade_module():
    return importlib.import_module("qq_chat_analyzer.application.facade")


@dataclass(frozen=True)
class _ProcessIdentity:
    """Fictional stable identity for one lifetime of a PID."""

    pid: int
    creation_time: int
    executable_path: Path


class _FakeProcessTable:
    def __init__(self, *identities: _ProcessIdentity) -> None:
        self._identities = {identity.pid: identity for identity in identities}
        self.terminated: list[int] = []

    def identity(self, pid: int) -> _ProcessIdentity | None:
        return self._identities.get(pid)

    def remove(self, pid: int) -> None:
        self._identities.pop(pid, None)

    def replace(self, identity: _ProcessIdentity) -> None:
        self._identities[identity.pid] = identity

    def terminate(self, pid: int) -> bool:
        self.terminated.append(pid)
        self.remove(pid)
        return True


class _FakeRuntime:
    def __init__(
        self,
        *,
        pid: int | None,
        owned_process: bool,
    ) -> None:
        self._pid = pid
        self._owned_process = owned_process
        self._running = pid is None

    def is_installed(self) -> bool:
        return True

    def running(self) -> bool:
        return self._running

    def start(self):
        self._running = True
        info = SimpleNamespace(
            pid=self._pid,
            version="fictional-1.0",
            owned_process=self._owned_process,
        )
        if self._owned_process is None:
            del info.owned_process
        return info

    def stop(self) -> None:
        self._running = False


def _identity(tmp_path: Path, pid: int, creation_time: int, name: str):
    return _ProcessIdentity(
        pid=pid,
        creation_time=creation_time,
        executable_path=tmp_path / "fictional-bin" / name,
    )


class _FictionalJobProcess:
    def __init__(self, pid=_LAUNCHER_PID):
        self.pid = pid
        self.closed = False
        self.close_calls = 0

    def close(self):
        if not self.closed:
            self.close_calls += 1
            self.closed = True


def _manager(registry, *, pid: int | None, owned_process: bool):
    return _runtime_manager_module().QQRuntimeManager(
        _FakeRuntime(pid=pid, owned_process=owned_process),
        process_registry=registry,
    )


def _shutdown(registry) -> None:
    facade = _facade_module().ChatAnalyzerFacade(
        qq_process_registry=registry,
        shutdown_step_seconds=0.05,
    )
    facade.shutdown()


def test_job_ownership_survives_launcher_reference_loss_until_shutdown() -> None:
    """A: hold the session resource, not merely a launcher/log-thread PID.

    Forced-owner-exit behavior is tested against the native module separately.
    """
    import weakref
    registry = _registry_module().QQProcessRegistry(
        terminator=lambda pid: pytest.fail("Job must not fall back to PID termination"))
    process = _FictionalJobProcess()
    reference = weakref.ref(process)
    registry.record_process(process)
    del process
    assert reference() is not None
    _shutdown(registry)
    assert registry.recorded() == ()


@pytest.mark.parametrize("owned_process", [False, None, 1, "true"])
def test_healthy_external_service_without_echo_record_is_never_claimed(
    tmp_path: Path,
    owned_process,
) -> None:
    """Health, the usual port, and a familiar image name prove no ownership."""
    new_echo = _identity(tmp_path, 47002, 200, "Echo-new.exe")
    external_launcher = _identity(
        tmp_path,
        _LAUNCHER_PID,
        300,
        "NapCatWinBootMain.exe",
    )
    table = _FakeProcessTable(new_echo, external_launcher)
    registry = _registry_module().QQProcessRegistry(
        terminator=table.terminate,
    )

    # Even if a future health probe can observe a PID, owned_process=False is
    # authoritative: observation must never turn into ownership.
    _manager(
        registry,
        pid=_LAUNCHER_PID,
        owned_process=owned_process,
    ).start()
    _shutdown(registry)

    assert table.terminated == []


@pytest.mark.parametrize("pid", [None, True, 0, "invalid"])
def test_owned_runtime_with_invalid_pid_is_not_registered(pid) -> None:
    class _RejectingRegistry:
        def record(self, pid):
            raise AssertionError("invalid PID must not reach the registry")

    status = _manager(_RejectingRegistry(), pid=pid, owned_process=True).start()

    assert status.state is _runtime_manager_module().QQRuntimeState.RUNNING


def test_independent_instances_close_only_their_own_job() -> None:
    """C: no cross-instance record/adoption exists."""
    first = _registry_module().QQProcessRegistry()
    second = _registry_module().QQProcessRegistry()
    process_a = _FictionalJobProcess(48101)
    process_b = _FictionalJobProcess(48102)
    first.record_process(process_a)
    second.record_process(process_b)
    _shutdown(second)
    assert process_b.closed
    assert not process_a.closed
    first.terminate_all()
    assert process_a.closed


def test_job_and_legacy_pid_record_never_double_kill_a_reused_pid() -> None:
    """D: a Job-associated PID must never reach the legacy terminator."""
    terminated = []
    registry = _registry_module().QQProcessRegistry(terminator=terminated.append)
    process = _FictionalJobProcess()
    registry.record(process.pid)
    registry.record_process(process)
    registry.record(process.pid)  # manager records the same launch again
    process.close()  # runtime stop already released its kernel resource
    registry.terminate_all()
    registry.terminate_all()
    assert terminated == []
    assert process.close_calls == 1


def test_newly_started_managed_launcher_keeps_normal_shutdown_cleanup(
    tmp_path: Path,
) -> None:
    echo = _identity(tmp_path, 47001, 100, "Echo.exe")
    launcher = _identity(
        tmp_path,
        _LAUNCHER_PID,
        300,
        "NapCatWinBootMain.exe",
    )
    table = _FakeProcessTable(echo, launcher)
    registry = _registry_module().QQProcessRegistry(
        terminator=table.terminate,
    )

    _manager(
        registry,
        pid=_LAUNCHER_PID,
        owned_process=True,
    ).start()
    _shutdown(registry)

    assert table.terminated == [_LAUNCHER_PID]
