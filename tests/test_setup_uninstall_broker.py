"""Run the real PowerShell protocol against a recording GUI exe, never an uninstaller."""
import dataclasses
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_setup_uninstall import installation

pytestmark = [pytest.mark.slow_integration,
              pytest.mark.skipif(sys.platform != 'win32', reason='Windows broker')]


@pytest.fixture(scope='module')
def recording_exe(tmp_path_factory):
    directory = tmp_path_factory.mktemp('fictional-uninstaller')
    source, executable = directory / 'Recorder.cs', directory / 'Recorder.exe'
    source.write_text('''
using System;
using System.IO;
using System.Reflection;
[assembly: AssemblyFileVersion("1.2.161.0")]
public class Recorder {
  public static int Main(string[] args) {
    if (args.Length > 0 && args[0] == "hold") { System.Threading.Thread.Sleep(15000); return 0; }
    string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
    System.Threading.Thread.Sleep(200);
    File.WriteAllText(Path.Combine(root, "invocations.txt"), String.Join("|", args));
    return File.Exists(Path.Combine(root, "fail")) ? 7 : 0;
  }
}
''', encoding='utf-8')
    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    result = subprocess.run([str(compiler), '/nologo', '/target:winexe', '/out:' + str(executable), str(source)],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return executable


@pytest.mark.parametrize('outcome', ['success', 'crash', 'changed', 'cancel', 'native_failure', 'cleaner_failure', 'other_instance'])
def test_broker_waits_for_normal_exit_and_rechecks_files(tmp_path, monkeypatch, outcome, recording_exe):
    import winreg
    from qq_chat_analyzer.application import setup_uninstall_service as module
    service, root, data, _, _ = installation(tmp_path)
    substitute = root / 'Update.exe'
    substitute.write_bytes(recording_exe.read_bytes())
    (root / 'current' / 'Echo.exe').write_bytes(recording_exe.read_bytes())
    snapshot = dataclasses.replace(service._inspect(),
        package_id='Echo.FictionalBroker.' + str(os.getpid()) + '.' + outcome)
    record = root / 'invocations.txt'
    if outcome == 'native_failure':
        (root / 'fail').touch()
    elif outcome == 'cleaner_failure':
        (root / 'current/fail').touch()
    key_path = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + snapshot.package_id
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        for name, value in snapshot.registration.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    # Keep failure feedback out of the interactive desktop in this protocol test.
    monkeypatch.setattr(module, '_BROKER', module._BROKER.replace(
        'Add-Type -AssemblyName System.Windows.Forms', '').replace(
        "[void][System.Windows.Forms.MessageBox]::Show('数据清理或卸载未完成，可能已有部分数据被删除。未确认全部清除；请重新打开 Echo 后重试。','Echo 卸载未完成')",
        "[Console]::Error.WriteLine('UNINSTALL_FAILED')"))
    owner = subprocess.Popen([sys.executable, '-c',
        'import sys; sys.stdin.readline(); sys.exit(' + ('7' if outcome == 'crash' else '0') + ')'],
        stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    broker = None
    other = None
    try:
        if outcome == 'other_instance':
            other = subprocess.Popen([str(root / 'current' / 'Echo.exe'), 'hold'],
                creationflags=subprocess.CREATE_NO_WINDOW)
        broker = subprocess.Popen(module._broker_command(snapshot, owner.pid),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, creationflags=subprocess.CREATE_NO_WINDOW, cwd=tmp_path)
        response = broker.stdout.readline().strip()
        if outcome == 'other_instance':
            assert response == 'FAILED'
            assert broker.wait(timeout=10) == 1
            assert other.poll() is None and not record.exists()
            return
        assert response == 'READY'
        assert not record.exists()
        if outcome == 'cancel':
            broker.stdin.close()
            assert broker.wait(timeout=10) != 0
        else:
            broker.stdin.write('GO\n')
            broker.stdin.flush()
            assert broker.stdout.readline().strip() == 'ARMED'
            assert not record.exists() and broker.poll() is None
            if outcome == 'changed':
                substitute.write_bytes(b'replaced bytes')
            owner.stdin.write(b'exit\n')
            owner.stdin.flush()
            assert broker.wait(timeout=15) == (0 if outcome == 'success' else 1)
        assert record.exists() == (outcome in ('success', 'native_failure'))
        if record.exists():
            assert record.read_text() == '--uninstall'
        if outcome == 'cleaner_failure':
            assert (root / 'current/invocations.txt').read_text() == '--echo-uninstall-cleanup|keep'
        assert (data / 'report.html').read_bytes() == b'fictional report'
    finally:
        if other is not None:
            if other.poll() is None:
                other.kill()
            other.wait(timeout=5)
        if broker is not None:
            if broker.poll() is None:
                broker.kill()
            broker.wait(timeout=5)
            for stream in (broker.stdin, broker.stdout, broker.stderr):
                if stream and not stream.closed:
                    stream.close()
        if owner.poll() is None:
            owner.kill()
        owner.wait(timeout=5)
        owner.stdin.close()
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)


def test_reads_pinned_pe_version_without_executing(recording_exe, tmp_path):
    from qq_chat_analyzer.application import setup_uninstall_service as module
    assert module._updater_version(recording_exe) == (1, 2, 161)
    invalid = tmp_path / 'invalid.exe'
    invalid.write_bytes(b'not executable')
    with pytest.raises(ValueError):
        module._updater_version(invalid)


def test_maintenance_gate_blocks_new_startups_but_authorizes_the_broker_child():
    from qq_chat_analyzer.application.setup_uninstall_service import maintenance_gate
    script = '''
from qq_chat_analyzer.application.setup_uninstall_service import maintenance_gate
with maintenance_gate(require_held=True): pass
try:
    with maintenance_gate(): pass
except OSError:
    raise SystemExit(0)
raise SystemExit(9)
'''
    with maintenance_gate():
        result = subprocess.run([sys.executable, '-c', script], capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('outcome', ['success', 'crash', 'changed', 'foreign_registration'])
def test_registration_waits_for_setup_and_only_rewrites_attested_entry(tmp_path, outcome):
    import base64
    import json
    import winreg
    from qq_chat_analyzer.application import setup_uninstall_service as module
    service, root, _, _, _ = installation(tmp_path)
    snapshot = dataclasses.replace(service._inspect(),
        package_id='Echo.FictionalRegistration.' + str(os.getpid()) + '.' + outcome)
    key_path = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + snapshot.package_id
    owner = subprocess.Popen([sys.executable, '-c',
        'import sys; sys.stdin.readline(); sys.exit(' + ('7' if outcome == 'crash' else '0') + ')'],
        stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    command = f'"{root / "current/Echo.exe"}" --echo-uninstall'
    spec = dict(pid=owner.pid, hashes=snapshot.hashes, package_id=snapshot.package_id,
                registration=snapshot.registration, command=command)
    payload = base64.b64encode(json.dumps(spec).encode()).decode()
    broker = None
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            for name, value in snapshot.registration.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            winreg.SetValueEx(key, 'QuietUninstallString', 0, winreg.REG_SZ, 'fictional quiet')
        broker = subprocess.Popen(module._powershell_command(
            module._REGISTER_BROKER.replace('__SPEC__', payload)),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW, cwd=tmp_path)
        assert broker.stdout.readline().strip() == 'READY'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            assert winreg.QueryValueEx(key, 'UninstallString')[0] == snapshot.registration['UninstallString']
        if outcome == 'changed':
            (root / 'current/Echo.exe').write_bytes(b'replaced fictional executable')
        elif outcome == 'foreign_registration':
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, 'DisplayName', 0, winreg.REG_SZ, 'Other app')
        owner.stdin.write(b'exit\n')
        owner.stdin.flush()
        assert broker.wait(timeout=15) == (0 if outcome == 'success' else 1)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            assert winreg.QueryValueEx(key, 'UninstallString')[0] == (
                command if outcome == 'success' else snapshot.registration['UninstallString'])
            if outcome == 'success':
                with pytest.raises(FileNotFoundError):
                    winreg.QueryValueEx(key, 'QuietUninstallString')
    finally:
        if broker is not None:
            if broker.poll() is None:
                broker.kill()
            broker.wait(timeout=5)
            broker.stdout.close()
            broker.stderr.close()
        if owner.poll() is None:
            owner.kill()
        owner.wait(timeout=5)
        owner.stdin.close()
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)


@pytest.mark.parametrize('reply', ['armed', 'failed', 'eof', 'timeout'])
def test_launcher_requires_acknowledged_handoff_and_cleans_failed_broker(tmp_path, monkeypatch, reply):
    from qq_chat_analyzer.application import setup_uninstall_service as module
    service, _, _, _, _ = installation(tmp_path)
    if reply == 'armed':
        script = "[Console]::Out.WriteLine('READY'); $null=[Console]::In.ReadLine(); [Console]::Out.WriteLine('ARMED'); Start-Sleep 15"
    elif reply == 'failed':
        script = "[Console]::Out.WriteLine('FAILED')"
    elif reply == 'eof':
        script = "exit 1"
    else:
        script = "Start-Sleep 15"
    monkeypatch.setattr(module, '_BROKER', script)
    processes = []
    original = subprocess.Popen
    def spawn(args, **kwargs):
        assert kwargs['shell'] is False
        assert kwargs['creationflags'] == subprocess.CREATE_NO_WINDOW
        process = original(args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(module.subprocess, 'Popen', spawn)
    broker = None
    try:
        if reply == 'armed':
            broker = module._launch_broker(service._inspect())
            assert broker.poll() is None
        else:
            with pytest.raises((OSError, module.queue.Empty)):
                module._launch_broker(service._inspect())
            assert len(processes) == 1 and processes[0].poll() is not None
    finally:
        if broker is not None:
            broker.kill()
            broker.wait(timeout=5)
