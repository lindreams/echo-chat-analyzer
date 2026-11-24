"""Read-only QQ discovery and conflict detection; ownership comes from the launch registry."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from functools import lru_cache
import os

from ...providers.qq_independent.files import SourceError
from ...providers.qq_independent.process import process_creation_ticks


_ERROR_NO_MORE_FILES = 18
_ERROR_ACCESS_DENIED = 5
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
    "creation": "process_creation_failed",
    "desktop_session": "desktop_session_failed",
    "desktop_snapshot": "desktop_snapshot_failed",
}


class QQProcessDetectionError(OSError):
    """Fixed diagnostic fields, without localized native exception text."""

    def __init__(self, stage: str, winerror: int, *, query_result='not_called',
                 length_result='not_checked', candidate_session='unknown'):
        super().__init__("QQ process detection failed")
        self._stage = stage
        self.winerror = winerror
        self.query_result = query_result if query_result in {'failed','succeeded'} else 'not_called'
        self.length_result = length_result if length_result in {'zero','out_of_range','valid'} else 'not_checked'
        self.candidate_session = candidate_session if candidate_session in {'same','different'} else 'unknown'

    @property
    def stage(self) -> str:
        return self._stage if self._stage in _ERROR_CATEGORIES else "enumeration"

    @property
    def category(self) -> str:
        return _ERROR_CATEGORIES.get(self._stage, "unexpected_failure")

    @property
    def candidate_access_denied(self) -> bool:
        return (self._stage in {"process_open", "image"} and self.winerror == _ERROR_ACCESS_DENIED
                and self.query_result != 'succeeded')


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


class _WtsProcessInfoW(C.Structure):
    _fields_ = [("session", W.DWORD), ("pid", W.DWORD), ("image", W.LPWSTR), ("sid", C.c_void_p)]


@lru_cache(maxsize=1)
def _desktop_api():
    api = C.WinDLL("wtsapi32", use_last_error=True)
    api.WTSEnumerateProcessesExW.argtypes = [W.HANDLE, C.POINTER(W.DWORD), W.DWORD,
                                            C.POINTER(C.POINTER(_WtsProcessInfoW)), C.POINTER(W.DWORD)]
    api.WTSEnumerateProcessesExW.restype = W.BOOL
    api.WTSFreeMemoryExW.argtypes = [C.c_int, C.c_void_p, W.ULONG]
    api.WTSFreeMemoryExW.restype = W.BOOL
    return api


def _desktop_process_rows(kernel) -> list[tuple[int, str]]:
    """Scope interactive login discovery. The offline guard still uses Toolhelp."""
    api = _desktop_api()
    session = W.DWORD()
    C.set_last_error(0)
    if not kernel.ProcessIdToSessionId(os.getpid(), C.byref(session)):
        raise QQProcessDetectionError("desktop_session", C.get_last_error())
    level, count = W.DWORD(0), W.DWORD()
    rows = C.POINTER(_WtsProcessInfoW)()
    C.set_last_error(0)
    if not api.WTSEnumerateProcessesExW(None, C.byref(level), session, C.byref(rows), C.byref(count)):
        raise QQProcessDetectionError("desktop_snapshot", C.get_last_error())
    try:
        if count.value and not rows:
            raise QQProcessDetectionError("desktop_snapshot", 0)
        return [(row.pid, row.image) for row in rows[:count.value]
                if row.session == session.value and row.image]
    finally:
        C.set_last_error(0)
        if rows and not api.WTSFreeMemoryExW(0, rows, count):
            raise QQProcessDetectionError("close", C.get_last_error())


@lru_cache(maxsize=1)
def _metadata_api():
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.ProcessIdToSessionId.argtypes = [W.DWORD, C.POINTER(W.DWORD)]
    kernel.ProcessIdToSessionId.restype = W.BOOL
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


def _candidate_error(kernel, pid, stage, code, **details):
    # Recheck only the relationship, never retain/log a PID or session number.
    # Failure to query is diagnostic uncertainty, never permission to skip it.
    ours, theirs = W.DWORD(), W.DWORD()
    relation = 'unknown'
    try:
        if (kernel.ProcessIdToSessionId(os.getpid(), C.byref(ours))
                and kernel.ProcessIdToSessionId(pid, C.byref(theirs))):
            relation = 'same' if ours.value == theirs.value else 'different'
    except (OSError, AttributeError):
        pass
    return QQProcessDetectionError(stage, code, candidate_session=relation, **details)


def selected_qq_processes(executable, *, include_children=False) -> list[tuple[int, int]]:
    """Return PID and exact creation time for candidates in Echo's login session."""
    if os.name != "nt":
        raise QQProcessDetectionError("api_bind", 0)
    try:
        kernel = _metadata_api()
        rows = _desktop_process_rows(kernel)
    except QQProcessDetectionError:
        raise
    except (OSError, AttributeError):
        raise QQProcessDetectionError("api_bind", C.get_last_error()) from None
    expected = os.path.normcase(str(executable))
    result = []
    for pid, name in rows:
        if name.casefold() != "qq.exe":
            continue
        C.set_last_error(0)
        handle = kernel.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            raise _candidate_error(kernel, pid, "process_open", C.get_last_error())
        failed = False
        try:
            image = C.create_unicode_buffer(32768)
            size = W.DWORD(len(image))
            C.set_last_error(0)
            queried = kernel.QueryFullProcessImageNameW(handle, 0, image, C.byref(size))
            error = C.get_last_error()
            if not queried:
                raise _candidate_error(kernel, pid, "image", error, query_result='failed')
            if not 0 < size.value < len(image):
                # GetLastError is undefined on success; do not report stale access denial.
                raise _candidate_error(kernel, pid, "image", 0, query_result='succeeded',
                                       length_result='zero' if size.value == 0 else 'out_of_range')
            if os.path.normcase(image.value) == expected and (include_children or not _is_secondary_process(handle)):
                C.set_last_error(0)
                try:
                    created = process_creation_ticks(kernel, handle)
                except SourceError:
                    raise QQProcessDetectionError("creation", C.get_last_error()) from None
                result.append((pid, created))
        except BaseException:
            failed = True
            raise
        finally:
            C.set_last_error(0)
            if not kernel.CloseHandle(handle) and not failed:
                raise QQProcessDetectionError("close", C.get_last_error())
    return sorted(set(result))
