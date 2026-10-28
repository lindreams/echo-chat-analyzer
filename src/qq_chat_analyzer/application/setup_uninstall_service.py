"""Attested Setup removal after natural exit and explicit local-data choice.

Velopack 1.2.161 uninstall has no waitPid option and force-stops the package.
The broker therefore captures our process handle, acknowledges readiness, and
invokes the attested updater only after a successful natural process exit.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, replace
from contextlib import contextmanager
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree

from ..resources import user_data_root
from ..version import APP_VERSION
from .installable_update_service import _setup_runtime
from .shutdown_models import ShutdownResult


@dataclass(frozen=True)
class UninstallResult:
    status: str
    token: str | None = None
    public_message: str | None = None


@dataclass(frozen=True)
class _Installation:
    root: Path
    updater: Path
    package_id: str
    registration: dict[str, str]
    hashes: dict[str, str]
    data_root: Path | None = None
    cleanup_mode: str = 'keep'


def _maintenance_name(root: Path) -> str:
    return 'Local\\Echo.DataMaintenance.' + hashlib.sha256(
        str(root.absolute()).casefold().encode('utf-8')).hexdigest()


@contextmanager
def maintenance_gate(*, require_held=False):
    """Serialize startup against the broker's data-cleanup/uninstall window."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.ReleaseMutex.argtypes = kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, _maintenance_name(user_data_root()))
    if not handle:
        raise OSError('Maintenance gate unavailable')
    acquired = False
    try:
        result = kernel.WaitForSingleObject(handle, 0)
        acquired = result in (0, 0x80)
        if (require_held and result != 0x102) or (not require_held and not acquired):
            raise OSError('Maintenance in progress or broker absent')
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def _registration(package_id: str) -> dict[str, str]:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + package_id) as key:
        return {name: winreg.QueryValueEx(key, name)[0] for name in (
            'InstallLocation', 'DisplayVersion', 'DisplayIcon', 'DisplayName', 'UninstallString')}


def _updater_version(path: Path) -> tuple[int, int, int]:
    """Read the PE fixed file version without executing an untrusted binary."""
    import ctypes
    from ctypes import wintypes
    version = ctypes.WinDLL('version', use_last_error=True)
    version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                     ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        raise ValueError('Missing PE version')
    buffer = ctypes.create_string_buffer(size)
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if (not version.GetFileVersionInfoW(str(path), 0, size, buffer)
            or not version.VerQueryValueW(buffer, '\\', ctypes.byref(pointer), ctypes.byref(length))
            or length.value < 52):
        raise ValueError('Invalid PE version')
    fields = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
    if fields[0] != 0xFEEF04BD:
        raise ValueError('Invalid PE signature')
    return fields[2] >> 16, fields[2] & 65535, fields[3] >> 16


def _plain_path(path: Path) -> None:
    # Reject junctions and every other reparse type, including ancestors.
    for part in (path, *path.parents):
        if part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Reparse path')


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Fixed code; paths/identity are transported as base64 JSON, never shell text.
_BROKER = r'''
$ErrorActionPreference = 'Stop'
$armed = $false
try {
    $spec = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__SPEC__')) | ConvertFrom-Json
    $owner = [Diagnostics.Process]::GetProcessById($spec.pid)
    $null = $owner.Handle
    function Assert-Installation {
        # Velopack force-stops the whole package. Never sacrifice another
        # Echo instance's work; inspect named processes, not other directories.
        foreach ($running in [Diagnostics.Process]::GetProcessesByName('Echo')) {
            try {
                if ($running.Id -ne $spec.pid) {
                    throw 'Another Echo instance is running'
                }
            } finally { $running.Dispose() }
        }
        foreach ($entry in $spec.hashes.PSObject.Properties) {
            $item = Get-Item -LiteralPath $entry.Name -Force
            while ($null -ne $item) {
                if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse path' }
                if ($item -is [IO.FileInfo]) { $item = $item.Directory }
                else { $item = $item.Parent }
            }
            if ((Get-FileHash -LiteralPath $entry.Name -Algorithm SHA256).Hash -ne $entry.Value) { throw 'Changed file' }
        }
        if ((Test-Path -LiteralPath (Join-Path $spec.root '.portable')) -or
            (Test-Path -LiteralPath (Join-Path $spec.root 'current/.portable')) -or
            (Test-Path -LiteralPath (Join-Path $spec.root '.msi-installed'))) { throw 'Unsupported installation' }
        $reg = Get-ItemProperty -LiteralPath ('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\' + $spec.package_id)
        foreach ($entry in $spec.registration.PSObject.Properties) {
            if ($reg.($entry.Name) -cne $entry.Value) { throw 'Changed registration' }
        }
    }
    Assert-Installation
    [Console]::Out.WriteLine('READY')
    if ([Console]::In.ReadLine() -cne 'GO') { exit 1 }
    $armed = $true
    [Console]::Out.WriteLine('ARMED')
    $owner.WaitForExit()
    if ($owner.ExitCode -ne 0) { throw 'Echo did not exit normally' }
    $maintenance = New-Object Threading.Mutex($false, $spec.maintenance)
    try { $held = $maintenance.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) { throw 'Maintenance already active' }
    Assert-Installation
    $cleaner = Start-Process -FilePath $spec.executable -ArgumentList @('--echo-uninstall-cleanup', $spec.cleanup) -WindowStyle Hidden -PassThru -Wait
    if ($cleaner.ExitCode -ne 0) { throw 'Local data cleanup incomplete' }
    Assert-Installation
    $uninstaller = Start-Process -FilePath $spec.updater -ArgumentList @('--uninstall') -WindowStyle Hidden -PassThru -Wait
    if ($uninstaller.ExitCode -ne 0) { throw 'Uninstaller failed' }
} catch {
    if ($armed) {
        Add-Type -AssemblyName System.Windows.Forms
        [void][System.Windows.Forms.MessageBox]::Show('数据清理或卸载未完成，可能已有部分数据被删除。未确认全部清除；请重新打开 Echo 后重试。','Echo 卸载未完成')
    } else { [Console]::Out.WriteLine('FAILED') }
    exit 1
} finally {
    if ($held) { $maintenance.ReleaseMutex() }
    if ($null -ne $maintenance) { $maintenance.Dispose() }
}
'''


def _broker_command(snapshot: _Installation, pid: int) -> list[str]:
    spec = dict(root=str(snapshot.root), updater=str(snapshot.updater), pid=pid,
                package_id=snapshot.package_id, registration=snapshot.registration,
                hashes=snapshot.hashes, executable=str(snapshot.root / 'current/Echo.exe'),
                cleanup=snapshot.cleanup_mode,
                maintenance=_maintenance_name(snapshot.data_root or user_data_root()))
    payload = base64.b64encode(json.dumps(spec, ensure_ascii=True).encode()).decode()
    return _powershell_command(_BROKER.replace('__SPEC__', payload))


def _powershell_command(script: str) -> list[str]:
    # Use the Windows system executable, never PATH or a user-supplied shell.
    from ctypes import create_unicode_buffer, windll
    buffer = create_unicode_buffer(32768)
    if not windll.kernel32.GetSystemDirectoryW(buffer, len(buffer)):
        raise OSError('System directory unavailable')
    powershell = Path(buffer.value) / 'WindowsPowerShell/v1.0/powershell.exe'
    return [str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive',
            '-ExecutionPolicy', 'Bypass', '-EncodedCommand',
            base64.b64encode(script.encode('utf-16le')).decode()]


def register_uninstall_entry() -> None:
    """Replace only this attested installation's Windows uninstall command."""
    import winreg
    snapshot = SetupUninstallService()._inspect()
    key_path = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + snapshot.package_id
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
        if _registration(snapshot.package_id) != snapshot.registration:
            raise ValueError('Changed registration')
        try:
            winreg.DeleteValue(key, 'QuietUninstallString')
        except FileNotFoundError:
            pass
        winreg.SetValueEx(key, 'UninstallString', 0, winreg.REG_SZ,
                         f'"{snapshot.root / "current/Echo.exe"}" --echo-uninstall')


_REGISTER_BROKER = r'''
$ErrorActionPreference = 'Stop'
try {
    $spec = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__SPEC__')) | ConvertFrom-Json
    $owner = [Diagnostics.Process]::GetProcessById($spec.pid)
    $null = $owner.Handle
    [Console]::Out.WriteLine('READY')
    $owner.WaitForExit()
    if ($owner.ExitCode -ne 0) { throw 'Setup failed' }
    foreach ($entry in $spec.hashes.PSObject.Properties) {
        $item = Get-Item -LiteralPath $entry.Name -Force
        while ($null -ne $item) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse path' }
            if ($item -is [IO.FileInfo]) { $item = $item.Directory } else { $item = $item.Parent }
        }
        if ((Get-FileHash -LiteralPath $entry.Name -Algorithm SHA256).Hash -ne $entry.Value) { throw 'Changed file' }
    }
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Uninstall\' + $spec.package_id, $true)
    if ($null -eq $key) { throw 'Missing registration' }
    try {
        foreach ($entry in $spec.registration.PSObject.Properties) {
            $expected = $entry.Value
            if ($entry.Name -eq 'UninstallString' -and $key.GetValue($entry.Name) -ceq $spec.command) { continue }
            if ($key.GetValue($entry.Name) -cne $expected) { throw 'Changed registration' }
        }
        $key.DeleteValue('QuietUninstallString', $false)
        $key.SetValue('UninstallString', $spec.command, [Microsoft.Win32.RegistryValueKind]::String)
    } finally { $key.Dispose() }
} catch { exit 1 }
'''


def register_after_setup(*_args) -> None:
    """The SDK writes registration AFTER install hooks: wait for its process.

    Only fixed file identities and the expected registration cross to this
    helper. It never discovers installations or invokes an uninstall command.
    Normal startup retries the same idempotent registration if interrupted.
    """
    executable = Path(sys.executable).absolute()
    root = executable.parent.parent
    expected = dict(InstallLocation=str(root), DisplayVersion=APP_VERSION,
                    DisplayIcon=str(executable), DisplayName='Echo',
                    UninstallString=f'"{root / "Update.exe"}" --uninstall')
    snapshot = SetupUninstallService(registration=lambda _: expected)._inspect()
    spec = dict(pid=os.getppid(), hashes=snapshot.hashes,
                package_id=snapshot.package_id, registration=expected,
                command=f'"{executable}" --echo-uninstall')
    payload = base64.b64encode(json.dumps(spec, ensure_ascii=True).encode()).decode()
    process = subprocess.Popen(_powershell_command(_REGISTER_BROKER.replace('__SPEC__', payload)),
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW, cwd=root.parent, text=True, encoding='utf-8')
    lines: queue.Queue = queue.Queue()
    def read_ready():
        lines.put(process.stdout.readline().strip())
    threading.Thread(target=read_ready, daemon=True).start()
    try:
        if lines.get(timeout=5) != 'READY':
            raise OSError('Registration broker not ready')
    except BaseException:
        process.kill()
        process.wait(timeout=5)
        raise
    finally:
        process.stdout.close()


def cleanup_entry(mode: str) -> int:
    """Internal broker child: no Qt, logging, source construction or config load."""
    try:
        if mode not in ('keep', 'purge'):
            return 1
        with maintenance_gate(require_held=True):
            snapshot = SetupUninstallService()._inspect()
            from .uninstall_data import cleanup_local_data
            cleanup_local_data(snapshot.data_root, purge=mode == 'purge')
        return 0
    except Exception:
        return 1


def _launch_broker(snapshot: _Installation) -> subprocess.Popen:
    process = subprocess.Popen(_broker_command(snapshot, os.getpid()),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding='utf-8', cwd=snapshot.root.parent,
        creationflags=subprocess.CREATE_NO_WINDOW, shell=False)
    lines: queue.Queue = queue.Queue()
    def read():
        try:
            lines.put(process.stdout.readline().strip())
            lines.put(process.stdout.readline().strip())
        except (OSError, ValueError):
            lines.put('FAILED')
    threading.Thread(target=read, daemon=True).start()
    try:
        if lines.get(timeout=5) != 'READY':
            raise OSError('Broker not ready')
        process.stdin.write('GO\n')
        process.stdin.flush()
        if lines.get(timeout=5) != 'ARMED' or process.poll() is not None:
            raise OSError('Broker not armed')
    except BaseException:
        process.kill()
        process.wait(timeout=5)
        raise
    finally:
        process.stdin.close()
        process.stdout.close()
    return process


class SetupUninstallService:
    def __init__(self, *, executable: Callable = lambda: Path(sys.executable),
                 setup_runtime: Callable = _setup_runtime, data_root: Callable = user_data_root,
                 registration: Callable = _registration, updater_version: Callable = _updater_version,
                 launcher: Callable = _launch_broker) -> None:
        self._executable, self._setup_runtime, self._data_root = executable, setup_runtime, data_root
        self._registration, self._updater_version, self._launcher = registration, updater_version, launcher
        self._pending: tuple[str, _Installation] | None = None
        self._lock = threading.Lock()
        self._broker = None

    def _inspect(self) -> _Installation:
        if not self._setup_runtime():
            raise ValueError('Source or unsupported platform')
        executable = Path(self._executable()).absolute()
        _plain_path(executable)
        current, root = executable.parent, executable.parent.parent
        updater, manifest = root / 'Update.exe', current / 'sq.version'
        if (executable.name != 'Echo.exe' or current.name.lower() != 'current'
                or not executable.is_file() or (root / '.portable').exists()
                or (current / '.portable').exists() or (root / '.msi-installed').exists()):
            raise ValueError('Unsupported installation')
        data = Path(self._data_root()).absolute()
        _plain_path(data)
        data = data.resolve()
        if root.is_relative_to(data) or data.is_relative_to(root):
            raise ValueError('Data overlaps installation')
        for path in (updater, manifest):
            _plain_path(path)
            if not path.is_file():
                raise ValueError('Missing installation file')
        tree = ElementTree.fromstring(manifest.read_bytes())
        fields = {}
        for node in tree.iter():
            name = node.tag.rsplit('}', 1)[-1]
            if name in ('id', 'version', 'channel', 'mainExe', 'title'):
                if name in fields:
                    raise ValueError('Ambiguous manifest')
                fields[name] = node.text or ''
        package_id = fields.get('id', '')
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,63}', package_id)
                or fields.get('version') != APP_VERSION or fields.get('mainExe') != 'Echo.exe'
                or fields.get('title') != 'Echo' or not fields.get('channel')):
            raise ValueError('Wrong Echo identity')
        registration = dict(self._registration(package_id))
        expected = dict(InstallLocation=str(root), DisplayVersion=APP_VERSION,
                        DisplayIcon=str(executable), DisplayName='Echo',
                        UninstallString=f'"{updater}" --uninstall')
        if registration.get('UninstallString') == f'"{executable}" --echo-uninstall':
            expected['UninstallString'] = registration['UninstallString']
        if registration != expected or self._updater_version(updater) != (1, 2, 161):
            raise ValueError('Wrong Setup registration or updater')
        return _Installation(root, updater, package_id, registration,
                             {str(p): _hash(p) for p in (executable, updater, manifest)}, data)

    def is_available(self) -> bool:
        try:
            self._inspect()
            return True
        except Exception:
            return False

    def prepare(self, cleanup_mode: str = 'keep') -> UninstallResult:
        import secrets
        with self._lock:
            if self._pending is not None or self._broker is not None:
                return UninstallResult('busy')
            try:
                if cleanup_mode not in ('keep', 'purge'):
                    raise ValueError('Invalid cleanup choice')
                snapshot = replace(self._inspect(), cleanup_mode=cleanup_mode)
            except Exception:
                return UninstallResult('denied', public_message='当前安装身份或卸载器无效，无法卸载。')
            token = secrets.token_urlsafe(32)
            self._pending = token, snapshot
            return UninstallResult('ready', token)

    def handoff(self, token: str, shutdown: ShutdownResult) -> UninstallResult:
        with self._lock:
            pending, self._pending = self._pending, None
            if (pending is None or token != pending[0] or not isinstance(shutdown, ShutdownResult)
                    or not shutdown.can_apply_update):
                return UninstallResult('denied', public_message='安全退出证据不完整，未启动卸载。')
            try:
                if replace(self._inspect(), cleanup_mode=pending[1].cleanup_mode) != pending[1]:
                    raise ValueError('Changed installation')
                self._broker = self._launcher(pending[1])
                return UninstallResult('started')
            except Exception:
                return UninstallResult('failed', public_message='卸载交接失败，未确认卸载。请通过 Windows 设置重试。')
