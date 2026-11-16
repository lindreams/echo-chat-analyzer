"""Explicit-PID module metadata probe; no key scan or QQ lifecycle operations.

Calling this against QQ requires separate user approval. Merely discovering an
installation or supplying a PID does not grant that approval. Self-checks use
only a Python child created by the research check script.

Win32 contracts: OpenProcess, QueryFullProcessImageNameW,
K32EnumProcessModulesEx, K32GetModuleFileNameExW, CloseHandle.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import os
from pathlib import Path

from .files import SourceError, _file, _local_path


@contextmanager
def verified_process(pid: int, expected_executable: Path):
    """One read/query handle, verified image, one owner, unconditional close."""
    if os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise SourceError("windows_x64_required")
    if type(pid) is not int or pid <= 0 or pid > 0xFFFFFFFF:
        raise SourceError("invalid_process_selection")
    expected_executable = _local_path(expected_executable)
    _file(expected_executable)
    native = ctypes.WinDLL("kernel32", use_last_error=True)
    native.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    native.OpenProcess.restype = wintypes.HANDLE
    native.CloseHandle.argtypes = [wintypes.HANDLE]
    native.CloseHandle.restype = wintypes.BOOL
    native.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    native.QueryFullProcessImageNameW.restype = wintypes.BOOL
    native.K32EnumProcessModulesEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    native.K32EnumProcessModulesEx.restype = wintypes.BOOL
    native.K32GetModuleFileNameExW.argtypes = [wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    native.K32GetModuleFileNameExW.restype = wintypes.DWORD
    # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, never ALL_ACCESS.
    handle = native.OpenProcess(0x0410, False, pid)
    if not handle:
        raise SourceError("process_read_access_unavailable")
    try:
        image = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(image))
        if not native.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length)):
            raise SourceError("process_identity_unavailable")
        if os.path.normcase(image.value) != os.path.normcase(str(expected_executable)):
            raise SourceError("process_identity_mismatch")
        yield native, handle
    finally:
        if not native.CloseHandle(handle):
            raise SourceError("process_handle_close_failed")


def process_creation_ticks(native, handle):
    native.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    native.GetProcessTimes.restype = wintypes.BOOL
    times = [wintypes.FILETIME() for _ in range(4)]
    if not native.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
        raise SourceError("process_identity_unavailable")
    return times[0].dwHighDateTime << 32 | times[0].dwLowDateTime


def loaded_module(native, handle, expected_module):
    expected_module = _local_path(expected_module)
    _file(expected_module)
    modules = (wintypes.HMODULE * 2048)()
    needed = wintypes.DWORD()
    if not native.K32EnumProcessModulesEx(handle, modules, ctypes.sizeof(modules), ctypes.byref(needed), 3):
        raise SourceError("module_metadata_unavailable")
    if needed.value > ctypes.sizeof(modules) or needed.value % ctypes.sizeof(wintypes.HMODULE):
        raise SourceError("module_snapshot_unbounded")
    count = needed.value // ctypes.sizeof(wintypes.HMODULE)
    matched = False
    for module in modules[:count]:
        name = ctypes.create_unicode_buffer(32768)
        length = native.K32GetModuleFileNameExW(handle, module, name, len(name))
        if not length or length >= len(name) - 1:
            raise SourceError("module_metadata_changed")
        matched |= os.path.normcase(name.value) == os.path.normcase(str(expected_module))
    return count, matched


def probe_modules(pid: int, expected_executable: Path, expected_module: Path):
    """Metadata only; no ReadProcessMemory or target lifecycle operations."""
    with verified_process(pid, expected_executable) as (native, handle):
        count, matched = loaded_module(native, handle, expected_module)
    return {"state": "queried", "query_and_read_handle_opened": True,
            "module_count": count, "expected_module_loaded": matched,
            "key_scan_attempted": False, "qq_lifecycle_changed": False,
            "process_handle_closed": True}
