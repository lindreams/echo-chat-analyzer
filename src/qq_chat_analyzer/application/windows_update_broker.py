"""Windows witnesses for the existing deterministic admission protocol.

These objects own real kernel handles. They do not turn caller-created DTOs
into authentication, launch an updater, or provide a default production feed.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import lru_cache
import math
from pathlib import Path
import sys
import time

from .setup_update_broker import OwnerExit, OwnerWitness, ProcessIdentity, WaitStatus, _process_identity


@lru_cache(maxsize=1)
def _kernel():
    if sys.platform != 'win32':
        raise OSError('Windows witnesses require Windows')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    declarations = {
        'OpenProcess': ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
        'GetProcessTimes': ([wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4, wintypes.BOOL),
        'QueryFullProcessImageNameW': ([wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                      ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        'WaitForSingleObject': ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        'GetExitCodeProcess': ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        'CreateFileW': ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
        'GetFileInformationByHandle': ([wintypes.HANDLE, wintypes.LPVOID], wintypes.BOOL),
    }
    for name, (args, result) in declarations.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result
    return kernel


class _Handle:
    def __init__(self, handle):
        self._handle = handle

    def close(self) -> None:
        if self._handle is not None:
            handle, self._handle = self._handle, None
            if not _kernel().CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def handle(self):
        if self._handle is None:
            raise OSError('Closed witness handle')
        return self._handle


class ProcessHandle(_Handle):
    """SYNCHRONIZE plus QUERY_LIMITED_INFORMATION; never reopen a PID to wait."""
    def __init__(self, handle, pid: int):
        super().__init__(handle)
        self._pid = pid
        self._identity = None

    @classmethod
    def capture(cls, expected: ProcessIdentity, deadline: float):
        if not _process_identity(expected):
            raise ValueError('Invalid owner identity')
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError('Invalid capture deadline')
        if time.monotonic() >= deadline:
            raise TimeoutError('Owner capture deadline expired')
        process = cls.open(expected.pid)
        try:
            if process._identity != expected:
                raise ValueError('Owner identity changed')
            if time.monotonic() >= deadline:
                raise TimeoutError('Owner capture deadline expired')
            return process
        except BaseException:
            process.close()
            raise

    @classmethod
    def open(cls, pid: int):
        if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
            raise ValueError('Invalid process identifier')
        handle = _kernel().OpenProcess(0x00100000 | 0x1000, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        process = cls(handle, pid)
        try:
            process._identity = process.identity()
            return process
        except BaseException:
            process.close()
            raise

    def identity(self) -> ProcessIdentity:
        created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        kernel = _kernel()
        if not kernel.GetProcessTimes(self.handle, ctypes.byref(created), ctypes.byref(exited),
                ctypes.byref(kernel_time), ctypes.byref(user_time)):
            raise ctypes.WinError(ctypes.get_last_error())
        image, length = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        if not kernel.QueryFullProcessImageNameW(self.handle, 0, image, ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())
        return ProcessIdentity(self._pid, (created.dwHighDateTime << 32) | created.dwLowDateTime,
                               str(Path(image.value).absolute()))

    def wait(self, deadline: float) -> OwnerExit:
        if type(deadline) not in (float, int) or not math.isfinite(deadline):
            raise ValueError('Invalid wait deadline')
        remaining = deadline - time.monotonic()
        owner = OwnerWitness(self._identity, self)
        if remaining <= 0:
            return OwnerExit(owner, WaitStatus.TIMED_OUT, None)
        milliseconds = min(0xFFFFFFFE, max(0, int(remaining * 1000)))
        status = _kernel().WaitForSingleObject(self.handle, milliseconds)
        if status == 258:
            return OwnerExit(owner, WaitStatus.TIMED_OUT, None)
        if status != 0:
            return OwnerExit(owner, WaitStatus.FAILED, None)
        code = wintypes.DWORD()
        if not _kernel().GetExitCodeProcess(self.handle, ctypes.byref(code)):
            return OwnerExit(owner, WaitStatus.FAILED, None)
        return OwnerExit(owner, WaitStatus.EXITED, code.value)


class _FileInformation(ctypes.Structure):
    _fields_ = [('attributes', wintypes.DWORD), ('created', wintypes.FILETIME),
                ('accessed', wintypes.FILETIME), ('written', wintypes.FILETIME),
                ('volume', wintypes.DWORD), ('size_high', wintypes.DWORD),
                ('size_low', wintypes.DWORD), ('links', wintypes.DWORD),
                ('index_high', wintypes.DWORD), ('index_low', wintypes.DWORD)]


def _plain_path(path: Path) -> None:
    if not path.is_absolute():
        raise ValueError('Witness paths must be absolute')
    for part in (path, *path.parents):
        if part.lstat().st_file_attributes & 0x400:
            raise ValueError('Reparse path is not admissible')


class FileGuard(_Handle):
    """Retain read access without write/delete sharing; no path resolution."""
    def __init__(self, path: Path):
        self._open(Path(path), access=0x80000000, sharing=1, disposition=3)

    def _open(self, path: Path, *, access: int, sharing: int, disposition: int):
        _plain_path(path if disposition == 3 else path.parent)
        # OPEN_REPARSE_POINT means a last-component link cannot be followed
        # between the path check and CreateFile. Verify that same handle below.
        handle = _kernel().CreateFileW(str(path), access, sharing, None, disposition,
                                       0x00200000 | 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        super().__init__(handle)
        try:
            information = _FileInformation()
            if not _kernel().GetFileInformationByHandle(self.handle, ctypes.byref(information)):
                raise ctypes.WinError(ctypes.get_last_error())
            if information.attributes & (0x400 | 0x10):
                raise ValueError('A plain file is required')
            _plain_path(path)
        except BaseException:
            self.close()
            raise


class MaintenanceLease(FileGuard):
    """Kernel-enforced exclusive reservation on an installation-owned file.

    This excludes competing brokers only. It does NOT attest that every GUI,
    launcher or third-party helper participates in a maintenance protocol.
    """
    def __init__(self, path: Path):
        self._open(Path(path), access=0x80000000 | 0x40000000, sharing=0, disposition=4)


class StartupAdmission(FileGuard):
    """Shared lifetime admission; maintenance must use the identical root file.

    No delete sharing: a live admission cannot be bypassed by replacing its file.
    An exclusive maintenance holder denies new admission atomically in CreateFile.
    This does not prevent Windows creating a process before it runs admission.
    """
    def __init__(self, path: Path):
        self._open(Path(path), access=0x80000000, sharing=3, disposition=4)
