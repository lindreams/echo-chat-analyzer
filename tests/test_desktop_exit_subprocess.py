"""Observe actual process termination, including real fictional background work."""
import os
from pathlib import Path
import subprocess
import sys
import time
import json

import pytest


@pytest.mark.slow_integration
@pytest.mark.parametrize('attempt', range(3))
@pytest.mark.parametrize('scenario', ['normal', 'failure', 'repeated', 'worker', 'timeout', 'teardown_hang', 'owned_helper'])
def test_desktop_exit_is_bounded_in_a_real_process(tmp_path, scenario, attempt):
    if scenario == 'owned_helper' and sys.platform != 'win32':
        pytest.skip('Windows owned Job lifecycle')
    source = Path(__file__).resolve().parents[1] / 'src'
    env = os.environ.copy()
    env.update(PYTHONPATH=str(source), LOCALAPPDATA=str(tmp_path / 'local'),
               APPDATA=str(tmp_path / 'roaming'), USERPROFILE=str(tmp_path / 'home'),
               HOME=str(tmp_path / 'home'), QT_QPA_PLATFORM='offscreen')
    script = r'''
import ctypes, os, sys, time, threading
from pathlib import Path
if sys.platform == 'win32':
    ctypes.windll.kernel32.SetErrorMode(3)
from PySide6 import QtWidgets
from PySide6.QtCore import QTimer
from qq_chat_analyzer.gui import app, workers
from qq_chat_analyzer import diagnostics
diagnostics.runtime_root = lambda: Path(os.environ['LOCALAPPDATA']) / 'LocalChatAnalyzer'
scenario = sys.argv[1]
marker = Path(sys.argv[2])
original_hard_exit = app._hard_exit
def traced_hard_exit(code):
    (marker.parent / 'forced-exit').write_text(str(code))
    original_hard_exit(code)
app._hard_exit = traced_hard_exit
app.SHUTDOWN_WAIT_SECONDS = 0.05
original_arm = app._arm_forced_exit
app._arm_forced_exit = lambda code, exit: original_arm(code, exit, delay=0.4)
original_build = app.build_facade
def build():
    facade = original_build()
    if scenario == 'owned_helper':
        from qq_chat_analyzer.runtime.windows_job import launch_owned_process
        from qq_chat_analyzer.application.qq.qq_process_registry import QQProcessRegistry
        helper_script = 'import os,time; from pathlib import Path; Path(' + repr(str(marker)) + ').write_text(str(os.getpid())); time.sleep(30)'
        owned = launch_owned_process([sys.executable, '-c', helper_script])
        registry = QQProcessRegistry()
        registry.record_process(owned)
        facade._qq_process_registry = registry
        deadline = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists(), 'fictional helper did not start'
    if scenario == 'failure':
        def failure(): raise RuntimeError('fictional cleanup error')
        facade.shutdown = failure
    if scenario == 'timeout':
        facade.shutdown = lambda: time.sleep(3)
    return facade
app.build_facade = build
original_application = QtWidgets.QApplication
def application(args):
    result = original_application(args)
    def close():
        if scenario == 'worker':
            def operation():
                time.sleep(0.15)
                marker.write_text('finished')
            workers.submit(operation, on_success=lambda _: None, on_error=lambda *_: None)
        if scenario == 'teardown_hang':
            threading.Thread(target=lambda: threading.Event().wait(), daemon=False).start()
        if scenario == 'repeated':
            for w in result.topLevelWidgets():
                if hasattr(w, 'begin_shutdown'):
                    w.begin_shutdown(); w.begin_shutdown()
        result.closeAllWindows()
    QTimer.singleShot(50, close)
    return result
QtWidgets.QApplication = application
raise SystemExit(app._run_gui([]))
'''
    started = time.monotonic()
    completed = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', script,
                                scenario, str(tmp_path / 'worker-finished')],
                               env=env, capture_output=True, timeout=8)
    (tmp_path / 'stderr.log').write_bytes(completed.stderr)
    (tmp_path / 'exit-evidence.json').write_text(json.dumps({
        'scenario': scenario, 'exit_code': completed.returncode,
        'elapsed_seconds': time.monotonic() - started,
    }))
    assert completed.returncode == 0, completed.stderr.decode(errors='replace')
    assert (tmp_path / 'forced-exit').exists() is (scenario in ('timeout', 'teardown_hang'))
    if scenario == 'worker':
        assert (tmp_path / 'worker-finished').read_text() == 'finished'
    if scenario == 'owned_helper':
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        pid = int((tmp_path / 'worker-finished').read_text())
        handle = api.OpenProcess(0x100000, False, pid)
        if handle:
            try:
                assert api.WaitForSingleObject(handle, 2000) == 0, 'owned helper survived Echo exit'
            finally:
                api.CloseHandle(handle)
        else:
            assert ctypes.get_last_error() == 87, 'cannot verify helper exit'
