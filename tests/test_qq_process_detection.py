"""Toolhelp contracts using fictional snapshots, never host QQ processes."""
import ctypes as C
from ctypes import wintypes as W
import importlib
import io
import logging
import os
import subprocess

import pytest


def _module():
    return importlib.import_module("qq_chat_analyzer.application.qq.qq_process_detection")


class _Function:
    def __init__(self, call):
        self.call = call

    def __call__(self, *args):
        return self.call(*args)


class _SnapshotApi:
    """Model documented API results and last-error state at the DLL boundary."""

    def __init__(self, rows=(), *, fail=None, error=5, close_error=False):
        self.rows = list(rows)
        self.fail, self.error, self.close_error = fail, error, close_error
        self.index = 0
        self.closed = []
        self.handle = 0x100000123 if C.sizeof(C.c_void_p) == 8 else 0x123
        self.CreateToolhelp32Snapshot = _Function(self.create)
        self.Process32FirstW = _Function(self.first)
        self.Process32NextW = _Function(self.next)
        self.CloseHandle = _Function(self.close)

    def create(self, flags, pid):
        assert (flags, pid) == (2, 0)  # processes only, no modules or heaps
        if self.fail == "snapshot":
            C.set_last_error(self.error)
            return C.c_void_p(-1).value
        return self.handle

    def write(self, handle, pointer):
        assert handle == self.handle
        entry = pointer._obj
        assert entry.dwSize == C.sizeof(entry)
        if self.index == len(self.rows):
            C.set_last_error(18)  # ERROR_NO_MORE_FILES
            return False
        entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile = self.rows[self.index]
        return True

    def first(self, handle, pointer):
        if self.fail == "first":
            C.set_last_error(self.error)
            return False
        return self.write(handle, pointer)

    def next(self, handle, pointer):
        self.index += 1
        if self.fail == "next":
            C.set_last_error(self.error)
            return False
        return self.write(handle, pointer)

    def close(self, handle):
        self.closed.append(handle)
        if self.close_error:
            C.set_last_error(6)
            return False
        return True


@pytest.fixture
def native_api(monkeypatch):
    module = _module()
    monkeypatch.setattr(module.os, "name", "nt")
    # A PowerShell fallback would make both reliability and privacy regress.
    def forbidden(*args, **kwargs):
        raise AssertionError("process detection must not launch a subprocess")
    monkeypatch.setattr(subprocess, "run", forbidden)

    def install(api):
        def load(name, *, use_last_error):
            assert name == "kernel32" and use_last_error is True
            return api
        monkeypatch.setattr(C, "WinDLL", load)
        loader = getattr(module, "_kernel32", None)
        if loader is not None:
            loader.cache_clear()
        return api

    yield install
    loader = getattr(module, "_kernel32", None)
    if loader is not None:
        loader.cache_clear()


@pytest.mark.parametrize("rows,expected", [
    ([(7, 1, "Other.exe")], []),
    ([(501, 1, "QQ.exe")], [501]),
    ([(502, 501, "qq.EXE"), (501, 1, "QQ.exe"),
      (503, 1, "QQ.exe.helper"), (504, 1, "虚构程序.exe")], [501, 502]),
])
def test_detection_returns_only_qq_and_closes_snapshot(native_api, rows, expected):
    api = native_api(_SnapshotApi(rows))
    assert _module().find_conflicting_qq_pids(()) == expected
    assert api.closed == [api.handle]


def test_detection_excludes_owned_launcher_tree_but_keeps_all_user_qq(native_api):
    # Deliberately put grandchildren before parents to require transitive closure.
    api = native_api(_SnapshotApi([
        (12, 11, "QQ.exe"), (11, 10, "QQ.exe"),
        (10, 1, "NapCatWinBootMain.exe"),
        (20, 1, "QQ.exe"), (21, 20, "qq.EXE"), (30, 1, "Other.exe"),
    ]))
    assert _module().find_conflicting_qq_pids((10,)) == [20, 21]
    assert api.closed == [api.handle]


def test_parent_cycles_do_not_hang_or_hide_user_qq(native_api):
    native_api(_SnapshotApi([(11, 12, "QQ.exe"), (12, 11, "QQ.exe"), (20, 20, "QQ.exe")]))
    assert _module().find_conflicting_qq_pids((10,)) == [11, 12, 20]


@pytest.mark.parametrize("external_session", [2])
def test_unowned_qq_blocks_regardless_of_windows_session(native_api, external_session):
    # Fictional Echo runs in session 1. Session 2 models another signed-in
    # desktop; session 0 models a noninteractive session. Toolhelp's process
    # entry has no session ID, so the session metadata stays in this fixture.
    # This characterizes current blocking, not proof that ignoring it is safe.
    processes = [
        {"pid": 10, "parent": 1, "name": "NapCatWinBootMain.exe", "session": 1},
        {"pid": 11, "parent": 10, "name": "QQ.exe", "session": 1},
        {"pid": 20, "parent": 1, "name": "QQ.exe", "session": external_session},
    ]
    api = native_api(_SnapshotApi([
        (row["pid"], row["parent"], row["name"]) for row in processes
    ]))
    assert _module().find_conflicting_qq_pids((10,)) == [20]
    assert api.closed == [api.handle]


@pytest.mark.parametrize("stage", ["snapshot", "first", "next"])
@pytest.mark.parametrize("error", [0, 5])
def test_detection_fails_closed_on_native_error(native_api, stage, error):
    api = native_api(_SnapshotApi([(501, 1, "QQ.exe")], fail=stage, error=error))
    with pytest.raises(OSError) as caught:
        _module().find_conflicting_qq_pids(())
    assert caught.value.stage == stage
    assert caught.value.winerror == error
    assert api.closed == ([] if stage == "snapshot" else [api.handle])


def test_close_failure_cannot_return_a_successful_empty_list(native_api):
    api = native_api(_SnapshotApi(close_error=True))
    with pytest.raises(OSError) as caught:
        _module().find_conflicting_qq_pids(())
    assert caught.value.stage == "close"
    assert caught.value.winerror == 6
    assert api.closed == [api.handle]


def test_enumeration_error_is_preserved_when_close_also_fails(native_api):
    api = native_api(_SnapshotApi(fail="first", error=5, close_error=True))
    with pytest.raises(OSError) as caught:
        _module().find_conflicting_qq_pids(())
    assert caught.value.stage == "first"
    assert caught.value.winerror == 5
    assert api.closed == [api.handle]


@pytest.mark.parametrize("first", [True, False])
def test_failed_api_without_last_error_cannot_reuse_old_normal_end(native_api, first):
    api = native_api(_SnapshotApi([(501, 1, "QQ.exe")]))
    # A stale ERROR_NO_MORE_FILES from a previous query must not authorize a
    # partial/empty snapshot if this failing call provides no error code.
    def fail(handle, pointer):
        return False
    if first:
        api.Process32FirstW = _Function(fail)
    else:
        original = api.first
        def succeed(handle, pointer):
            result = original(handle, pointer)
            C.set_last_error(18)
            return result
        api.Process32FirstW = _Function(succeed)
        api.Process32NextW = _Function(fail)
    C.set_last_error(18)
    with pytest.raises(OSError) as caught:
        _module().find_conflicting_qq_pids(())
    assert caught.value.stage == ("first" if first else "next")
    assert caught.value.winerror == 0
    assert api.closed == [api.handle]


def test_toolhelp_signatures_and_entry_layout_preserve_pointer_width(native_api):
    api = native_api(_SnapshotApi([(501, 1, "QQ.exe")]))
    assert _module().find_conflicting_qq_pids(()) == [501]
    assert api.CreateToolhelp32Snapshot.argtypes == [W.DWORD, W.DWORD]
    assert api.CreateToolhelp32Snapshot.restype is W.HANDLE
    assert api.CloseHandle.argtypes == [W.HANDLE]
    assert api.CloseHandle.restype is W.BOOL
    for function in (api.Process32FirstW, api.Process32NextW):
        assert function.argtypes[0] is W.HANDLE
        assert function.restype is W.BOOL
        entry = function.argtypes[1]._type_
        if C.sizeof(C.c_void_p) == 8:
            assert C.sizeof(entry) == 568
            assert entry.th32DefaultHeapID.offset == 16
            assert entry.szExeFile.offset == 44
        else:
            assert C.sizeof(entry) == 556
            assert entry.th32DefaultHeapID.offset == 12
            assert entry.szExeFile.offset == 36


@pytest.mark.slow_integration
@pytest.mark.skipif(os.name != "nt", reason="Windows native ABI contract")
def test_native_calling_convention_with_fictional_snapshot(native_api):
    """Typed native callbacks test ABI marshalling without enumerating the host."""
    api = _SnapshotApi([(501, 1, "QQ.exe"), (502, 501, "qq.EXE")])

    # Documented ABI independent of the production structure declaration.
    class Entry(C.Structure):
        _fields_ = [
            ("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
            ("th32DefaultHeapID", C.c_size_t), ("th32ModuleID", W.DWORD),
            ("cntThreads", W.DWORD), ("th32ParentProcessID", W.DWORD),
            ("pcPriClassBase", W.LONG), ("dwFlags", W.DWORD), ("szExeFile", W.WCHAR * 260),
        ]

    def entry_call(handle, pointer, *, first):
        if not first:
            api.index += 1
        if api.index == len(api.rows):
            C.set_last_error(18)
            return False
        assert handle == api.handle and pointer.contents.dwSize == C.sizeof(Entry)
        row = api.rows[api.index]
        pointer.contents.th32ProcessID = row[0]
        pointer.contents.th32ParentProcessID = row[1]
        pointer.contents.szExeFile = row[2]
        return True

    api.CreateToolhelp32Snapshot = C.WINFUNCTYPE(W.HANDLE, W.DWORD, W.DWORD, use_last_error=True)(api.create)
    signature = C.WINFUNCTYPE(W.BOOL, W.HANDLE, C.POINTER(Entry), use_last_error=True)
    api.Process32FirstW = signature(lambda h, p: entry_call(h, p, first=True))
    api.Process32NextW = signature(lambda h, p: entry_call(h, p, first=False))
    api.CloseHandle = C.WINFUNCTYPE(W.BOOL, W.HANDLE, use_last_error=True)(api.close)
    native_api(api)
    assert _module().find_conflicting_qq_pids(()) == [501, 502]
    assert api.closed == [api.handle]
