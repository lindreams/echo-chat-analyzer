"""Native broker tests use fictional files/processes, never an installation."""
import importlib
import os
import subprocess
import sys
import time
from queue import Queue
from threading import Thread

import pytest

from test_setup_uninstall_broker import recording_exe

pytestmark = [pytest.mark.slow_integration,
              pytest.mark.skipif(sys.platform != 'win32', reason='Windows native witnesses')]


def native():
    name = 'qq_chat_analyzer.application.windows_update_broker'
    assert importlib.util.find_spec(name) is not None, 'Windows witnesses are missing'
    return importlib.import_module(name)


def test_startup_admission_is_shared_and_excludes_maintenance(tmp_path):
    mod = native()
    path = tmp_path / '.echo-startup-admission'
    with mod.StartupAdmission(path), mod.StartupAdmission(path):
        with pytest.raises(OSError):
            mod.MaintenanceLease(path)
        with pytest.raises(OSError):
            path.unlink()
    with mod.MaintenanceLease(path):
        with pytest.raises(OSError):
            mod.StartupAdmission(path)
    with mod.StartupAdmission(path):
        pass


def _admission_child(path, kind):
    script = '''
import sys, os
print('pid:' + str(os.getpid()), flush=True)
from pathlib import Path
from qq_chat_analyzer.application.windows_update_broker import StartupAdmission, MaintenanceLease
print('ready', flush=True)
sys.stdin.readline()
try:
    handle = (StartupAdmission if sys.argv[2] == 'startup' else MaintenanceLease)(Path(sys.argv[1]))
except OSError:
    print('denied', flush=True)
else:
    print('held', flush=True)
    sys.stdin.readline()
    handle.close()
'''
    child = subprocess.Popen([sys.executable, '-u', '-c', script, str(path), kind],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    child.actual_pid = int(_line(child).removeprefix('pid:'))
    return child


def _line(child):
    result = Queue()
    Thread(target=lambda: result.put(child.stdout.readline().strip()), daemon=True).start()
    return result.get(timeout=5)


def _desktop_child(root, hook=False):
    script = '''
import sys, os, importlib.abc, importlib.util
print('pid:' + str(os.getpid()), flush=True)
from types import SimpleNamespace
from pathlib import Path
sys.frozen = True
sys.executable = str(Path(sys.argv[1]) / 'current' / 'Echo.exe')
class App:
    def set_args(self, args): return self
    def set_auto_apply_on_startup(self, value):
        assert value is False
        return self
    def run(self):
        if sys.argv[2] == 'hook': raise SystemExit(0)
sys.modules['velopack'] = SimpleNamespace(App=App)
class GUI(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'qq_chat_analyzer.gui.app':
            return importlib.util.spec_from_loader(fullname, self)
    def create_module(self, spec): return None
    def exec_module(self, module):
        print('gui-imported', flush=True)
        module._run_gui = lambda args: 7
sys.meta_path.insert(0, GUI())
from qq_chat_analyzer.desktop import main
print('result:' + str(main([])), flush=True)
sys.stdin.readline()
'''
    child = subprocess.Popen([sys.executable, '-u', '-c', script, str(root),
        'hook' if hook else 'normal'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    child.actual_pid = int(_line(child).removeprefix('pid:'))
    return child


def _stop_child(child):
    if child.poll() is None:
        # Windows venv redirectors can have a distinct child PID. Terminate only
        # the synthetic PID reported through this child's private pipe.
        import _winapi
        try:
            handle = _winapi.OpenProcess(1, False, child.actual_pid)
        except OSError:
            pass
        else:
            try:
                _winapi.TerminateProcess(handle, 77)
            finally:
                _winapi.CloseHandle(handle)
    child.wait(timeout=5)
    for stream in (child.stdin, child.stdout, child.stderr):
        stream.close()


def test_desktop_rejects_before_gui_import_during_maintenance(tmp_path):
    with native().MaintenanceLease(tmp_path / '.echo-startup-admission'):
        child = _desktop_child(tmp_path)
        try:
            assert _line(child) == 'result:75'
        finally:
            _stop_child(child)


def test_desktop_retains_admission_after_gui_returns_until_process_exit(tmp_path):
    child = _desktop_child(tmp_path)
    try:
        assert _line(child) == 'gui-imported'
        assert _line(child) == 'result:7'
        with pytest.raises(OSError):
            native().MaintenanceLease(tmp_path / '.echo-startup-admission')
        child.stdin.write('exit\n')
        child.stdin.flush()
        assert child.wait(timeout=5) == 0
    finally:
        _stop_child(child)
    with native().MaintenanceLease(tmp_path / '.echo-startup-admission'):
        pass


def test_desktop_unknown_admission_failure_is_closed(tmp_path):
    (tmp_path / '.echo-startup-admission').mkdir()
    child = _desktop_child(tmp_path)
    try:
        assert _line(child) == 'result:75'
    finally:
        _stop_child(child)


def test_installer_hook_dispatch_still_exits_before_admission(tmp_path):
    with native().MaintenanceLease(tmp_path / '.echo-startup-admission'):
        child = _desktop_child(tmp_path, hook=True)
        try:
            assert child.wait(timeout=5) == 0
            assert child.stdout.read() == ''
        finally:
            _stop_child(child)


def test_pre_admission_suspended_package_process_can_still_be_force_stopped(tmp_path,
                                                                          recording_exe):
    # Reproduce the OS boundary, not a fake invocation of the real updater:
    # CreateProcess maps an image before even its first instruction can acquire
    # admission. Velopack's directory selection has no admission-state filter.
    import shutil
    import _winapi
    from qq_chat_analyzer.application.setup_update_broker import WaitStatus
    current = tmp_path / 'current'
    current.mkdir()
    image = current / 'Echo.exe'
    shutil.copyfile(recording_exe, image)
    with native().MaintenanceLease(tmp_path / '.echo-startup-admission'):
        child = subprocess.Popen([str(image), 'hold'],
            creationflags=0x4 | subprocess.CREATE_NO_WINDOW)  # CREATE_SUSPENDED
        try:
            with native().ProcessHandle.open(child.pid) as witness:
                assert os.path.samefile(witness.identity().image, image)
                assert child.poll() is None
                # Same rights as 1.2.161 get_processes_running_in_directory.
                handle = _winapi.OpenProcess(0x1000 | 1, False, child.pid)
                try:
                    _winapi.TerminateProcess(handle, 77)
                finally:
                    _winapi.CloseHandle(handle)
                exited = witness.wait(time.monotonic() + 5)
                assert exited.status is WaitStatus.EXITED and exited.exit_code == 77
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


@pytest.mark.parametrize('first', ['startup', 'maintenance', 'simultaneous'])
def test_real_subprocess_admission_race_has_exactly_one_winner(tmp_path, first):
    # Synchronize starts and retain the winner until both results are observed.
    children = {kind: _admission_child(tmp_path / '.echo-startup-admission', kind)
                for kind in ('startup', 'maintenance')}
    try:
        for child in children.values():
            assert _line(child) == 'ready'
        results = {}
        order = list(children) if first == 'simultaneous' else [first,
            'maintenance' if first == 'startup' else 'startup']
        for kind in order:
            children[kind].stdin.write('go\n')
            children[kind].stdin.flush()
            if first != 'simultaneous':
                results[kind] = _line(children[kind])
        if first == 'simultaneous':
            results = {kind: _line(child) for kind, child in children.items()}
        assert sorted(results.values()) == ['denied', 'held']
        if first != 'simultaneous':
            assert results[first] == 'held'
    finally:
        for child in children.values():
            _stop_child(child)


@pytest.mark.parametrize('code', [0, 7])
def test_retained_handle_observes_identity_and_native_exit_code(code):
    mod = native()
    from qq_chat_analyzer.application.setup_update_broker import WaitStatus
    owner = subprocess.Popen([sys.executable, '-c',
        'import sys; sys.stdin.readline(); sys.exit(' + str(code) + ')'],
        stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    handle = None
    try:
        handle = mod.ProcessHandle.open(owner.pid)
        identity = handle.identity()
        assert identity.pid == owner.pid and identity.created_at > 0
        assert os.path.samefile(identity.image, sys.executable)
        owner.stdin.write(b'exit\n')
        owner.stdin.flush()
        result = handle.wait(time.monotonic() + 5)
        assert result.status is WaitStatus.EXITED and result.exit_code == code
        assert result.owner.handle is handle and result.owner.identity == identity
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.wait(timeout=5)
        owner.stdin.close()
        if handle:
            handle.close()


def test_native_wait_timeout_never_becomes_success():
    mod = native()
    from qq_chat_analyzer.application.setup_update_broker import WaitStatus
    with mod.ProcessHandle.open(os.getpid()) as handle:
        result = handle.wait(time.monotonic() + 0.02)
        assert result.status is WaitStatus.TIMED_OUT and result.exit_code is None


def test_native_read_guard_prevents_write_delete_and_replace(tmp_path):
    mod = native()
    path = tmp_path / 'fictional.nupkg'
    path.write_bytes(b'fictional package')
    replacement = tmp_path / 'replacement'
    replacement.write_bytes(b'other bytes')
    with mod.FileGuard(path):
        assert path.read_bytes() == b'fictional package'
        for operation in (lambda: path.write_bytes(b'changed'), path.unlink,
                          lambda: replacement.replace(path)):
            with pytest.raises(PermissionError):
                operation()
    path.write_bytes(b'after close')
    assert path.read_bytes() == b'after close'


def test_native_maintenance_reservation_excludes_second_broker(tmp_path):
    mod = native()
    path = tmp_path / 'fictional-lease'
    with mod.MaintenanceLease(path):
        with pytest.raises(OSError):
            mod.MaintenanceLease(path)
    with mod.MaintenanceLease(path):
        pass


@pytest.mark.parametrize('field,value', [('created_at', 1), ('image', 'other.exe'), ('pid', True)])
def test_capture_rejects_changed_or_wrongly_typed_expected_identity(field, value):
    from dataclasses import replace
    mod = native()
    assert hasattr(mod.ProcessHandle, 'capture'), 'Identity-bound capture is missing'
    with mod.ProcessHandle.open(os.getpid()) as observed:
        expected = replace(observed.identity(), **{field: value})
    with pytest.raises((ValueError, OSError)):
        mod.ProcessHandle.capture(expected, time.monotonic() + 5)


def test_capture_rejects_expired_deadline_without_returning_a_handle():
    mod = native()
    assert hasattr(mod.ProcessHandle, 'capture'), 'Identity-bound capture is missing'
    with mod.ProcessHandle.open(os.getpid()) as observed:
        identity = observed.identity()
    with pytest.raises(TimeoutError):
        mod.ProcessHandle.capture(identity, time.monotonic() - 1)


@pytest.mark.parametrize('outcome', ['normal', 'crash', 'timeout', 'closed_handle', 'query_denied'])
def test_real_owner_outcome_controls_protocol_apply(outcome):
    """Only owner capture/wait are native here; other witnesses are fictional."""
    from test_setup_update_broker import Witnesses
    from qq_chat_analyzer.application import setup_update_broker as core
    mod = native()
    assert hasattr(mod.ProcessHandle, 'capture'), 'Identity-bound capture is missing'
    owner = subprocess.Popen([sys.executable, '-c',
        'import sys; sys.stdin.readline(); sys.exit(' + ('7' if outcome == 'crash' else '0') + ')'],
        stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    captured = None
    calls = []
    try:
        with mod.ProcessHandle.open(owner.pid) as observed:
            identity = observed.identity()
        witnesses = Witnesses(core, time.monotonic)
        witnesses.identity = identity
        witnesses.permit = core.ExitPermit(identity, 'fictional-native-grant', core.PermitStatus.ACTIVE)
        def capture(expected, deadline):
            nonlocal captured
            captured = mod.ProcessHandle.capture(expected, deadline)
            return core.OwnerWitness(captured.identity(), captured)
        witnesses.capture_owner = capture
        witnesses.wait_owner = lambda owner_witness, deadline: owner_witness.handle.wait(deadline)
        deadline = time.monotonic() + (0.2 if outcome == 'timeout' else 5)
        broker = core.UpdateBroker(owner=identity, installation=witnesses.installation,
            package=witnesses.package, authorization=core.HandoffAuthorization('fictional-native-grant'),
            witnesses=witnesses, deadline=deadline, clock=time.monotonic, apply_recorder=calls.append)
        assert broker.ready() is core.BrokerState.READY
        assert broker.go('fictional-native-grant') is core.BrokerState.GO
        assert broker.arm() is core.BrokerState.ARMED
        if outcome == 'closed_handle':
            captured.close()
        elif outcome == 'query_denied':
            # Reproduce the pinned SDK's actual Windows rights defect, using a
            # real synchronization-only handle rather than mocking an API.
            import ctypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            from ctypes import wintypes
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            restricted = kernel.OpenProcess(0x00100000, False, owner.pid)
            assert restricted
            captured.close()
            captured._handle = restricted
        if outcome not in ('timeout', 'closed_handle'):
            owner.stdin.write(b'exit\n')
            owner.stdin.flush()
        result = broker.approve()
        if outcome == 'normal':
            assert result is core.BrokerState.APPLY_APPROVED
            assert calls == [witnesses.package] and owner.wait(timeout=5) == 0
        else:
            assert result is core.BrokerState.REJECTED and calls == []
            assert broker.approve() is core.BrokerState.REJECTED
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.wait(timeout=5)
        owner.stdin.close()
        if captured:
            captured.close()


def test_exclusive_broker_reservation_does_not_prevent_new_package_process(tmp_path, recording_exe):
    """Concrete integration blocker: file reservation is not a producer gate."""
    mod = native()
    root = tmp_path / 'fictional-installation'
    current = root / 'current'
    current.mkdir(parents=True)
    executable = current / 'Echo.exe'
    executable.write_bytes(recording_exe.read_bytes())
    process = None
    try:
        with mod.MaintenanceLease(root / 'echo-maintenance.lock'):
            # This starts AFTER the exclusive reservation is acquired. A
            # one-time process scan before launch would miss this instance.
            process = subprocess.Popen([str(executable), 'hold'],
                creationflags=subprocess.CREATE_NO_WINDOW)
            with mod.ProcessHandle.open(process.pid) as captured:
                assert os.path.samefile(captured.identity().image, executable)
                assert process.poll() is None
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
