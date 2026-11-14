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
import os
from pathlib import Path

from qq_windows_source import SourceError, _file, _local_path


def probe_modules(pid: int, expected_executable: Path, expected_module: Path):
    """Request query/read rights, return counts and an exact module-path match.

    Module APIs can inspect loader metadata internally. This component does not
    call ReadProcessMemory, read key candidates, persist module paths, elevate,
    retry denied access, suspend, inject, patch, or terminate the target.
    """
    if os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise SourceError("windows_x64_required")
    if type(pid) is not int or pid <= 0 or pid > 0xFFFFFFFF:
        raise SourceError("invalid_process_selection")
    expected_executable = _local_path(expected_executable)
    expected_module = _local_path(expected_module)
    _file(expected_executable)
    _file(expected_module)
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
        result = {"state": "queried", "query_and_read_handle_opened": True,
                  "module_count": count, "expected_module_loaded": matched,
                  "key_scan_attempted": False, "qq_lifecycle_changed": False}
    finally:
        if not native.CloseHandle(handle):
            raise SourceError("process_handle_close_failed")
    result["process_handle_closed"] = True
    return result
