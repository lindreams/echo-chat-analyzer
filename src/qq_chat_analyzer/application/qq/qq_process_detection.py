"""Read-only QQ conflict detection; ownership comes from the launch registry."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from functools import lru_cache
import os


_ERROR_NO_MORE_FILES = 18
_INVALID_HANDLE_VALUE = C.c_void_p(-1).value
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_COMMAND_LINE_INFORMATION = 60
_MAX_COMMAND_LINE_INFORMATION_BYTES = 128 * 1024
_ERROR_CATEGORIES = {
    "api_bind": "api_bind_failed",
    "snapshot": "snapshot_failed",
    "first": "first_failed",
    "next": "next_failed",
    "close": "close_failed",
    "process_open": "process_open_failed",
    "image": "process_image_failed",
    "command_line": "process_command_line_failed",
}


class QQProcessDetectionError(OSError):
    """Fixed diagnostic fields, without localized native exception text."""

    def __init__(self, stage: str, winerror: int):
        super().__init__("QQ process detection failed")
        self._stage = stage
        self.winerror = winerror

    @property
    def stage(self) -> str:
        return self._stage if self._stage in _ERROR_CATEGORIES else "enumeration"

    @property
    def category(self) -> str:
        return _ERROR_CATEGORIES.get(self._stage, "unexpected_failure")


class _ProcessEntry32W(C.Structure):
    _fields_ = [
        ("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
        ("th32DefaultHeapID", C.c_size_t), ("th32ModuleID", W.DWORD),
        ("cntThreads", W.DWORD), ("th32ParentProcessID", W.DWORD),
        ("pcPriClassBase", W.LONG), ("dwFlags", W.DWORD), ("szExeFile", W.WCHAR * 260),
    ]


@lru_cache(maxsize=1)
def _kernel32():
    api = C.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateToolhelp32Snapshot": ([W.DWORD, W.DWORD], W.HANDLE),
        "Process32FirstW": ([W.HANDLE, C.POINTER(_ProcessEntry32W)], W.BOOL),
        "Process32NextW": ([W.HANDLE, C.POINTER(_ProcessEntry32W)], W.BOOL),
        "CloseHandle": ([W.HANDLE], W.BOOL),
    }
    for name, (args, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = args, result
    return api


def _process_rows() -> list[tuple[int, int, str]]:
    try:
        api = _kernel32()
    except (OSError, AttributeError):
        raise QQProcessDetectionError("api_bind", C.get_last_error()) from None
    C.set_last_error(0)
    handle = api.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS only
    if handle is None or handle == _INVALID_HANDLE_VALUE:
        raise QQProcessDetectionError("snapshot", C.get_last_error())
    failed = False
    try:
        entry = _ProcessEntry32W()
        entry.dwSize = C.sizeof(entry)
        rows = []
        function, stage = api.Process32FirstW, "first"
        while True:
            C.set_last_error(0)
            if not function(handle, C.byref(entry)):
                # Capture before CloseHandle can replace the thread's last error.
                error = C.get_last_error()
                if error == _ERROR_NO_MORE_FILES:
                    return rows
                raise QQProcessDetectionError(stage, error)
            rows.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            function, stage = api.Process32NextW, "next"
    except BaseException:
        failed = True
        raise
    finally:
        C.set_last_error(0)
        if not api.CloseHandle(handle) and not failed:
            raise QQProcessDetectionError("close", C.get_last_error())


def find_conflicting_qq_pids(owned_pids: tuple[int, ...]) -> list[int]:
    """Return user QQ processes, excluding recorded launchers and descendants.

    Toolhelp supplies PID, parent PID and Unicode executable name without
    PowerShell, WMI or JSON. Detection errors propagate: a partial/unreadable
    snapshot must never be treated as an empty one. This function only detects
    conflicts; the launch registry's Job resources remain the ownership proof.
    """
    if os.name != "nt":
        return []
    rows = _process_rows()
    owned = set(owned_pids)
    while True:
        children = {pid for pid, parent, _name in rows if parent in owned}
        if children.issubset(owned):
            break
        owned.update(children)
    return sorted({pid for pid, _parent, name in rows
                   if name.lower() == "qq.exe" and pid not in owned})


class _UnicodeString(C.Structure):
    _fields_ = [("length", W.USHORT), ("capacity", W.USHORT), ("buffer", C.c_void_p)]


@lru_cache(maxsize=1)
def _metadata_api():
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    kernel.OpenProcess.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.CloseHandle.restype = W.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = W.BOOL
    return kernel


@lru_cache(maxsize=1)
def _command_line_api():
    query = C.WinDLL("ntdll").NtQueryInformationProcess
    query.argtypes = [W.HANDLE, W.ULONG, C.c_void_p, W.ULONG, C.POINTER(W.ULONG)]
    query.restype = W.LONG
    return query


def _is_secondary_process(handle):
    # ProcessCommandLineInformation supplies a UNICODE_STRING in our buffer.
    # Only classify the role; never retain the command line or read remote memory.
    try:
        query = _command_line_api()
    except (OSError, AttributeError):
        raise QQProcessDetectionError("command_line", 0) from None
    buffer = C.create_string_buffer(_MAX_COMMAND_LINE_INFORMATION_BYTES)
    size = W.ULONG()
    status = query(handle, _PROCESS_COMMAND_LINE_INFORMATION, buffer, len(buffer), C.byref(size))
    header_size = C.sizeof(_UnicodeString)
    if status != 0 or not header_size <= size.value <= len(buffer):
        raise QQProcessDetectionError("command_line", status & 0xFFFFFFFF)
    command = _UnicodeString.from_buffer(buffer)
    start = C.addressof(buffer)
    wchar_size = C.sizeof(W.WCHAR)
    if (not command.buffer or command.buffer % wchar_size or not command.length or command.length % wchar_size
            or command.length > command.capacity
            or not start + header_size <= command.buffer <= start + size.value - command.length):
        raise QQProcessDetectionError("command_line", 0)
    return "--type=" in C.wstring_at(command.buffer, command.length // wchar_size).casefold()


def selected_qq_pids(executable, *, include_children=False) -> list[int]:
    """Read-only candidates for the exact selected image, including no ownership grant."""
    if os.name != "nt":
        raise QQProcessDetectionError("api_bind", 0)
    try:
        kernel = _metadata_api()
    except (OSError, AttributeError):
        raise QQProcessDetectionError("api_bind", C.get_last_error()) from None
    expected = os.path.normcase(str(executable))
    result = []
    for pid, _, name in _process_rows():
        if name.casefold() != "qq.exe":
            continue
        C.set_last_error(0)
        handle = kernel.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            raise QQProcessDetectionError("process_open", C.get_last_error())
        try:
            image = C.create_unicode_buffer(32768)
            size = W.DWORD(len(image))
            C.set_last_error(0)
            if (not kernel.QueryFullProcessImageNameW(handle, 0, image, C.byref(size))
                    or not 0 < size.value < len(image)):
                raise QQProcessDetectionError("image", C.get_last_error())
            if os.path.normcase(image.value) == expected and (include_children or not _is_secondary_process(handle)):
                result.append(pid)
        finally:
            C.set_last_error(0)
            if not kernel.CloseHandle(handle):
                raise QQProcessDetectionError("close", C.get_last_error())
    return sorted(set(result))
