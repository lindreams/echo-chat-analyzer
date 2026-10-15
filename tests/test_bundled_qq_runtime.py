"""Behavior tests for the bundled QQ runtime process integration.

No real NapCat executable is ever started. The platform launcher is mocked and the
health endpoint is simulated with an injected checker, so the tests cover the
runtime lifecycle without touching external processes or real chat data.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest import mock

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _runtime_module():
    return importlib.import_module("qq_chat_analyzer.runtime")


def _launch_target(module):
    return (module, "launch_owned_process") if module.os.name == "nt" else (module.subprocess, "Popen")


class _FakePopen:
    """Stand in for a spawned NapCat subprocess."""

    def __init__(
        self,
        args,
        *,
        cwd=None,
        env=None,
        running: bool = True,
        exit_code: int = 0,
    ) -> None:
        self.args = args
        self.cwd = cwd
        self.env = env
        self.pid = 9001
        self._running = running
        self._exit_code = exit_code
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    def poll(self) -> int | None:
        return None if self._running else self._exit_code

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        self._running = False
        return self._exit_code

    def terminate(self) -> None:
        self.terminate_calls += 1
        self._running = False

    def kill(self) -> None:
        self.kill_calls += 1
        self._running = False


def _config(
    *,
    executable: Path,
    working_directory: Path,
    base_url: str = "http://127.0.0.1:40655",
) -> object:
    module = _runtime_module()
    return module.QQRuntimeConfig(
        executable_path=executable,
        working_directory=working_directory,
        base_url=base_url,
        version="9.9.9",
    )




def _make_runtime(
    *,
    executable: Path,
    working_directory: Path,
    health: bool = False,
    health_error: Exception | None = None,
    ready_timeout: float = 5.0,
    poll_interval: float = 0.1,
    monotonic: object | None = None,
):
    module = _runtime_module()

    def _checker(base_url: str) -> bool:
        if health_error is not None:
            raise health_error
        return health

    return module.BundledQQRuntime(
        _config(
            executable=executable,
            working_directory=working_directory,
            base_url="http://127.0.0.1:40655",
        ),
        health_checker=_checker,
        ready_timeout=ready_timeout,
        poll_interval=poll_interval,
        monotonic=monotonic,
    )


def _popen_patch(runtime_module, **popen_kwargs):
    fake = _FakePopen(
        ["fake-napcat"],
        running=popen_kwargs.get("running", True),
        exit_code=popen_kwargs.get("exit_code", 0),
    )

    def _popen(args, **kwargs):
        fake.args = args
        fake.cwd = kwargs.get("cwd")
        fake.env = kwargs.get("env")
        return fake

    patcher = mock.patch.object(
        *_launch_target(runtime_module),
        side_effect=_popen,
    )
    patcher.start()
    return fake, patcher


# ---------------------------------------------------------- file existence


def _started_runtime(tmp_path: Path, **runtime_kwargs):
    module = _runtime_module()
    executable = tmp_path / "NapCatWinBootMain.exe"
    executable.write_text("fake", encoding="utf-8")
    runtime = _make_runtime(
        executable=executable,
        working_directory=tmp_path,
        **runtime_kwargs,
    )
    fake, patcher = _popen_patch(module)
    try:
        runtime.start()
    finally:
        patcher.stop()
    return runtime, fake


# ---------------------------------------------------------------- starting


@pytest.mark.parametrize("parent_value", [None, ""])
def test_start_disables_ffmpeg_download_only_in_child(tmp_path, monkeypatch, parent_value):
    module = _runtime_module()
    variable = "NAPCAT_DISABLE_FFMPEG_DOWNLOAD"
    if parent_value is None:
        monkeypatch.delenv(variable, raising=False)
    else:
        monkeypatch.setenv(variable, parent_value)
    executable = tmp_path / "NapCatWinBootMain.exe"
    executable.write_text("fictional")
    runtime = _make_runtime(executable=executable, working_directory=tmp_path)
    fake, patcher = _popen_patch(module)
    try:
        runtime.start()
    finally:
        patcher.stop()
    assert fake.env.get(variable) == "1"
    assert module.os.environ.get(variable) == parent_value


def test_start_spawns_the_process_and_returns_info(tmp_path: Path) -> None:
    module = _runtime_module()
    executable = tmp_path / "NapCatWinBootMain.exe"
    executable.write_text("fake", encoding="utf-8")
    runtime = _make_runtime(
        executable=executable,
        working_directory=tmp_path,
    )
    fake, patcher = _popen_patch(module)
    try:
        info = runtime.start()
    finally:
        patcher.stop()

    assert runtime.is_installed() is True
    assert info.pid == 9001
    assert info.version == "9.9.9"
    assert info.owned_process is True
    assert Path(fake.cwd) == tmp_path
    assert runtime.running() is True


def test_start_reuses_healthy_external_runtime_without_spawning(
    tmp_path: Path,
) -> None:
    module = _runtime_module()
    executable = tmp_path / "NapCatWinBootMain.exe"
    executable.write_text("fake", encoding="utf-8")
    runtime = _make_runtime(
        executable=executable,
        working_directory=tmp_path,
        health=True,
    )

    with mock.patch.object(*_launch_target(module)) as popen:
        info = runtime.start()

    popen.assert_not_called()
    assert info.pid is None
    assert info.version == "9.9.9"
    assert info.owned_process is False
    assert runtime.running() is True


def test_start_failure_raises_user_safe_error(tmp_path: Path) -> None:
    module = _runtime_module()
    executable = tmp_path / "NapCatWinBootMain.exe"
    executable.write_text("fake", encoding="utf-8")
    runtime = _make_runtime(
        executable=executable,
        working_directory=tmp_path,
    )
    patcher = mock.patch.object(
        *_launch_target(module),
        side_effect=OSError("spawn exploded with secret"),
    )
    patcher.start()
    try:
        with pytest.raises(module.QQChatRuntimeError) as excinfo:
            runtime.start()
    finally:
        patcher.stop()

    assert "spawn exploded with secret" not in excinfo.value.public_message
    assert "Traceback" not in excinfo.value.public_message


# ----------------------------------------------------------------- stopping


def test_stop_terminates_and_clears_state(tmp_path: Path) -> None:
    module = _runtime_module()
    executable = tmp_path / "NapCatWinBootMain.exe"
    executable.write_text("fake", encoding="utf-8")
    runtime = _make_runtime(
        executable=executable,
        working_directory=tmp_path,
    )
    fake, patcher = _popen_patch(module)
    try:
        runtime.start()
        runtime.stop()
    finally:
        patcher.stop()

    assert fake.terminate_calls == 1
    assert fake.wait_calls == 1
    assert runtime.running() is False


def test_stop_does_not_terminate_healthy_external_runtime(tmp_path: Path) -> None:
    module = _runtime_module()
    executable = tmp_path / "NapCatWinBootMain.exe"
    executable.write_text("fake", encoding="utf-8")
    runtime = _make_runtime(
        executable=executable,
        working_directory=tmp_path,
        health=True,
    )

    with mock.patch.object(*_launch_target(module)) as popen:
        runtime.start()
        runtime.stop()

    popen.assert_not_called()
    assert runtime.get_info().owned_process is False


# -------------------------------------------------------- process lifecycle


# ------------------------------------------------------------------ readiness


def test_wait_ready_times_out_with_user_safe_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _runtime_module()
    clock = [0.0]
    runtime, _ = _started_runtime(
        tmp_path,
        health=False,
        ready_timeout=5.0,
        poll_interval=1.0,
        monotonic=lambda: clock[0],
    )

    def _advance(seconds: float) -> None:
        """Deterministic stand-in for time.sleep: advance the fake clock."""
        clock[0] += seconds

    monkeypatch.setattr(module.time, "sleep", _advance)

    with pytest.raises(module.QQChatRuntimeError) as excinfo:
        runtime.wait_ready()

    assert excinfo.value.public_message != ""
    assert "Traceback" not in excinfo.value.public_message
    assert clock[0] >= 5.0
