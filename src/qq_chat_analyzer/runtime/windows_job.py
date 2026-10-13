"""Windows-only, atomic ownership of a newly created process tree.

An unnamed, non-inheritable Job belongs to this Echo process, not to the
launcher PID. Keep it alive after the launcher exits; release it only on
explicit session cleanup or Echo exit. No scanning, adoption, or late assign.
Requires Windows 10+; any native creation failure is fatal (no Popen fallback).
"""
from __future__ import annotations

import atexit
from contextlib import ExitStack
import ctypes as C
from ctypes import wintypes as W
from functools import lru_cache
import io
import os
import subprocess
import sys
import threading
import time

_KILL_ON_CLOSE = 0x2000
_JOB_LIST = 0x2000D
_HANDLE_LIST = 0x20002
_EXTENDED_STARTUPINFO_PRESENT = 0x80000
_CREATE_UNICODE_ENVIRONMENT = 0x400
_LIVE: set[WindowsJobProcess] = set()
_LIVE_LOCK = threading.RLock()
_LAUNCH_LOCK = threading.RLock()


class _BasicLimits(C.Structure):
    _fields_ = [("PerProcessUserTimeLimit", C.c_int64),
                ("PerJobUserTimeLimit", C.c_int64), ("LimitFlags", W.DWORD),
                ("MinimumWorkingSetSize", C.c_size_t),
                ("MaximumWorkingSetSize", C.c_size_t),
                ("ActiveProcessLimit", W.DWORD), ("Affinity", C.c_size_t),
                ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD)]


class _IOCounters(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in
                ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                 "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimits(C.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IOCounters),
                ("ProcessMemoryLimit", C.c_size_t), ("JobMemoryLimit", C.c_size_t),
                ("PeakProcessMemoryUsed", C.c_size_t), ("PeakJobMemoryUsed", C.c_size_t)]


class _Accounting(C.Structure):
    _fields_ = [(name, C.c_int64) for name in
                ("TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime",
                 "ThisPeriodTotalKernelTime")] + [(name, W.DWORD) for name in
                ("TotalPageFaultCount", "TotalProcesses", "ActiveProcesses",
                 "TotalTerminatedProcesses")]


class _StartupInfo(C.Structure):
    _fields_ = [("cb", W.DWORD), ("lpReserved", W.LPWSTR),
                ("lpDesktop", W.LPWSTR), ("lpTitle", W.LPWSTR),
                ("dwX", W.DWORD), ("dwY", W.DWORD), ("dwXSize", W.DWORD),
                ("dwYSize", W.DWORD), ("dwXCountChars", W.DWORD),
                ("dwYCountChars", W.DWORD), ("dwFillAttribute", W.DWORD),
                ("dwFlags", W.DWORD), ("wShowWindow", W.WORD),
                ("cbReserved2", W.WORD), ("lpReserved2", C.POINTER(W.BYTE)),
                ("hStdInput", W.HANDLE), ("hStdOutput", W.HANDLE),
                ("hStdError", W.HANDLE)]


class _StartupInfoEx(C.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", C.c_void_p)]


class _ProcessInfo(C.Structure):
    _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE),
                ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]


@lru_cache(maxsize=1)
def _kernel32():
    api = C.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([C.c_void_p, W.LPCWSTR], W.HANDLE),
        "SetInformationJobObject": ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
        "QueryInformationJobObject": ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD,
                                       C.c_void_p], W.BOOL),
        "CloseHandle": ([W.HANDLE], W.BOOL),
        "GetCurrentProcess": ([], W.HANDLE),
        "DuplicateHandle": ([W.HANDLE, W.HANDLE, W.HANDLE, C.POINTER(W.HANDLE),
                             W.DWORD, W.BOOL, W.DWORD], W.BOOL),
        "InitializeProcThreadAttributeList": ([C.c_void_p, W.DWORD, W.DWORD,
                                               C.POINTER(C.c_size_t)], W.BOOL),
        "UpdateProcThreadAttribute": ([C.c_void_p, W.DWORD, C.c_size_t, C.c_void_p,
                                       C.c_size_t, C.c_void_p, C.c_void_p], W.BOOL),
        "DeleteProcThreadAttributeList": ([C.c_void_p], None),
        "CreateProcessW": ([W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL,
                            W.DWORD, C.c_void_p, W.LPCWSTR, C.c_void_p,
                            C.POINTER(_ProcessInfo)], W.BOOL),
        "WaitForSingleObject": ([W.HANDLE, W.DWORD], W.DWORD),
        "GetExitCodeProcess": ([W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
        "TerminateProcess": ([W.HANDLE, W.UINT], W.BOOL),
        "TerminateJobObject": ([W.HANDLE, W.UINT], W.BOOL),
    }
    for name, (args, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = args, result
    return api


def _check(result):
    if not result:
        raise C.WinError(C.get_last_error())
    return result


def _close_handle(api, handle):
    _check(api.CloseHandle(handle))


def _close_process_info(api, info):
    """Registered before CreateProcess: also handles interrupted result checks."""
    try:
        if info.hThread:
            _close_handle(api, info.hThread)
            info.hThread = None
    finally:
        if info.hProcess:
            _close_handle(api, info.hProcess)
            info.hProcess = None


class WindowsJobProcess:
    """The small Popen surface used by QQ, plus explicit whole-tree close.

    poll/wait/communicate refer to the launcher; tree_running refers to the
    entire session. Neither waiting nor draining logs releases ownership.
    """

    def __init__(self, api, info, job, args, stdout, stderr, *, external_readers=False):
        self.pid = info.dwProcessId
        self.args = args
        self.returncode = None
        self.stdin = None  # QQ launch accepts DEVNULL only
        self.stdout, self.stderr = stdout, stderr
        self._api = api
        self._process_handle = info.hProcess
        self._job_handle = job
        self._lock = threading.RLock()
        self._close_lock = threading.RLock()
        self._readers = None
        self._external_readers = () if external_readers else None
        self._output = [None, None]
        self._read_errors = []
        self._exit_verified = False

    @property
    def exit_verified(self):
        """Sticky proof obtained while the native Job was still queryable."""
        with self._lock:
            return (self._exit_verified and self.closed
                    and not any(reader.is_alive() for reader in (self._readers or ()))
                    and all(stream is None or stream.closed
                            for stream in (self.stdout, self.stderr)))

    def close_with_exit_evidence(self, timeout=5.0):
        """QQ-only close: query whole-tree exit BEFORE releasing the Job.

        Historical close/closed/tree_running flags are not exit attestations.
        External helper readers retain their separate owner protocol.
        """
        deadline = time.monotonic() + timeout
        if not self._close_lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise subprocess.TimeoutExpired(self.args, timeout)
        try:
            if self.exit_verified:
                return
            if self._external_readers is not None or self.active_process_count() is None:
                raise RuntimeError('No queryable QQ Job exit evidence')
            self.terminate_tree()
            while self.active_process_count() != 0:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(self.args, timeout)
                time.sleep(0.01)
            # Record before close, which destroys the only tree-query handle.
            with self._lock:
                self._exit_verified = True
            self.close()
        finally:
            self._close_lock.release()

    def poll(self):
        with self._lock:
            if self.returncode is not None:
                return self.returncode
            result = self._api.WaitForSingleObject(self._process_handle, 0)
            if result == 0xFFFFFFFF:
                raise C.WinError(C.get_last_error())
            if result == 0:
                code = W.DWORD()
                _check(self._api.GetExitCodeProcess(self._process_handle, C.byref(code)))
                self.returncode = code.value
            return self.returncode

    @property
    def closed(self):
        with self._lock:
            return self._process_handle is None and self._job_handle is None

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self.args, timeout)
            time.sleep(0.01)
        return self.returncode

    def tree_running(self):
        with self._lock:
            if self._job_handle is None:
                return False
            accounting = _Accounting()
            _check(self._api.QueryInformationJobObject(
                self._job_handle, 1, C.byref(accounting), C.sizeof(accounting), None))
            return accounting.ActiveProcesses > 0

    def active_process_count(self):
        """Query a live Job; None means its handle was already closed.

        Unlike tree_running's historical QQ contract, an unavailable Job is
        never reported as empty. Query and close serialize on the same lock.
        Native query failure raises rather than manufacturing exit evidence.
        """
        with self._lock:
            if self._job_handle is None:
                return None
            accounting = _Accounting()
            _check(self._api.QueryInformationJobObject(
                self._job_handle, 1, C.byref(accounting), C.sizeof(accounting), None))
            return accounting.ActiveProcesses

    def terminate_tree(self):
        """Terminate our tree without closing the Job needed to prove exit.

        False means the Job was already closed; True only confirms the native
        termination request, not process exit. Existing QQ kill/close stays as-is.
        """
        with self._lock:
            if self._job_handle is None:
                return False
            _check(self._api.TerminateJobObject(self._job_handle, 1))
            return True

    def terminate(self):
        """Close only our Job; never issue taskkill against the launcher PID."""
        with self._lock:
            if self._job_handle is not None:
                _close_handle(self._api, self._job_handle)
                self._job_handle = None

    kill = terminate

    def _read(self, index, stream):
        try:
            self._output[index] = stream.read()
        except Exception as error:
            self._read_errors.append(error)
        finally:
            stream.close()

    def communicate(self, input=None, timeout=None):
        if input is not None:
            raise ValueError("QQ owned launcher stdin is DEVNULL")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._lock:
            if self._external_readers is not None:
                raise RuntimeError("PIPE readers belong to the helper owner")
            if self._readers is None:
                self._readers = []
                for index, stream in enumerate((self.stdout, self.stderr)):
                    if stream is not None and not stream.closed:
                        reader = threading.Thread(target=self._read, args=(index, stream),
                                                  name="echo-qq-pipe", daemon=True)
                        self._readers.append(reader)
                        reader.start()
            readers = tuple(self._readers)
        self.wait(timeout=timeout)
        for reader in readers:
            remaining = None if deadline is None else max(0, deadline - time.monotonic())
            reader.join(remaining)
            if reader.is_alive():
                raise subprocess.TimeoutExpired(self.args, timeout)
        if self._read_errors:
            raise self._read_errors[0]
        return tuple(self._output)

    def close(self):
        """Idempotent session shutdown, including launcher and pipe resources."""
        if self._external_readers is not None:
            return self._close_external_readers(deadline=time.monotonic() + 5)
        with self._close_lock:
            self.terminate()
            self.wait(timeout=5)
            try:
                self.communicate(timeout=5)
            finally:
                if not any(reader.is_alive() for reader in (self._readers or ())):
                    self._stream_resources.close()
                with self._lock:
                    if self._process_handle is not None:
                        _close_handle(self._api, self._process_handle)
                        self._process_handle = None
                with _LIVE_LOCK:
                    _LIVE.discard(self)

    def set_external_readers(self, readers):
        """Record the helper's existing readers before they start; never read PIPEs."""
        with self._close_lock, self._lock:
            if self.closed:
                raise RuntimeError("Cannot register readers after process close")
            if self._readers is not None:
                raise RuntimeError("PIPE readers already belong to communicate")
            self._external_readers = tuple(readers)

    def _close_external_readers(self, *, deadline):
        """Exit fallback: kill the tree and join only registered helper readers."""
        remaining = lambda: max(0, deadline - time.monotonic())
        if not self._close_lock.acquire(timeout=remaining()):
            raise subprocess.TimeoutExpired(self.args, 5)
        try:
            if not self._lock.acquire(timeout=remaining()):
                raise subprocess.TimeoutExpired(self.args, 5)
            try:
                self.terminate()  # Kill-on-close still covers every descendant.
            finally:
                self._lock.release()
            try:
                self.wait(timeout=remaining())
                for reader in self._external_readers:
                    if reader.ident is not None:
                        reader.join(remaining())
                self.close_after_readers(self._external_readers, deadline=deadline)
            finally:
                # A stuck reader retains its PIPE, but must not leak native handles.
                if self._lock.acquire(timeout=remaining()):
                    try:
                        if self._process_handle is not None:
                            _close_handle(self._api, self._process_handle)
                            self._process_handle = None
                    finally:
                        self._lock.release()
        finally:
            self._close_lock.release()

    def close_after_readers(self, readers, *, deadline):
        """Release drained helper resources without communicate or new readers.

        The caller owns/drains the pipes and supplies ONE monotonic deadline.
        Successful closes are recorded individually, so retries skip released
        resources. This additive API leaves QQ's existing close path unchanged.
        """
        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise subprocess.TimeoutExpired(self.args, 0)
            return value

        if not self._close_lock.acquire(timeout=remaining()):
            raise subprocess.TimeoutExpired(self.args, 0)
        try:
            if not self._lock.acquire(timeout=remaining()):
                raise subprocess.TimeoutExpired(self.args, 0)
            try:
                if any(reader.is_alive() for reader in (*readers, *(self._readers or ()))):
                    raise RuntimeError("Cannot release pipes with active readers")
                self.wait(timeout=remaining())
                if self._job_handle is not None and self.active_process_count() != 0:
                    raise RuntimeError("Cannot release a running Job")
                errors = []
                for stream in (self.stdout, self.stderr):
                    if stream is None or stream.closed:
                        continue
                    remaining()
                    try:
                        stream.close()
                    except Exception as error:
                        errors.append(error)
                    remaining()
                for name in ("_process_handle", "_job_handle"):
                    handle = getattr(self, name)
                    if handle is None:
                        continue
                    remaining()
                    try:
                        _close_handle(self._api, handle)
                    except Exception as error:
                        errors.append(error)
                    else:
                        setattr(self, name, None)
                    remaining()
                pipes_closed = all(stream is None or stream.closed
                                   for stream in (self.stdout, self.stderr))
                if pipes_closed:
                    # The wrappers already closed their raw readers. Discard
                    # callbacks only after verifying both closures, not before.
                    self._stream_resources.pop_all()
                if errors:
                    raise errors[0]
                if self.closed and pipes_closed:
                    with _LIVE_LOCK:
                        _LIVE.discard(self)
            finally:
                self._lock.release()
        finally:
            self._close_lock.release()


def launch_owned_process(args, *, cwd=None, env=None, stdin=None, stdout=None,
                         stderr=None, text=False, encoding=None, errors=None,
                         creationflags=0, external_readers=False):
    """Create an executable atomically inside a new kill-on-close Job.

    None standard streams become DEVNULL, including Frozen/windowed parents
    without console handles. stdout/stderr may be PIPE; no shell or adoption.
    """
    if sys.platform != "win32":
        raise OSError("Windows Job Objects require Windows")
    if stdin not in (None, subprocess.DEVNULL):
        raise ValueError("QQ owned launcher stdin must be DEVNULL")
    if stdout not in (None, subprocess.DEVNULL, subprocess.PIPE) or stderr not in (
            None, subprocess.DEVNULL, subprocess.PIPE):
        raise ValueError("QQ owned launcher output must be PIPE or DEVNULL")
    # No breakaway or suspended process API exposed to application callers.
    if creationflags & ~subprocess.CREATE_NO_WINDOW:
        raise ValueError("Unsupported owned-process creation flags")
    command_args = [os.fspath(arg) for arg in args]
    if not command_args or any("\0" in arg for arg in command_args):
        raise ValueError("Invalid launcher command")
    environment = os.environ.copy() if env is None else dict(env)
    for key, value in environment.items():
        if not isinstance(key, str) or not isinstance(value, str) or not key or (
                "\0" in key or "\0" in value or "=" in key[1:]):
            raise ValueError("Invalid child environment")
    environment_block = C.create_unicode_buffer("\0".join(
        f"{key}={value}" for key, value in sorted(environment.items(),
                                                  key=lambda item: item[0].upper())) + "\0\0")
    api = _kernel32()
    import msvcrt
    with ExitStack() as resources:
        readers = ExitStack()
        resources.callback(readers.close)
        job = _check(api.CreateJobObjectW(None, None))
        job_cleanup = ExitStack()
        resources.callback(job_cleanup.close)
        job_cleanup.callback(_close_handle, api, job)
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _KILL_ON_CLOSE
        _check(api.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits)))
        child_streams, parent_streams = [], []
        for output in (stdout, stderr):
            if output == subprocess.PIPE:
                read_fd, write_fd = os.pipe()
                read_stream = os.fdopen(read_fd, "rb")
                readers.callback(read_stream.close)
                write_stream = resources.enter_context(os.fdopen(write_fd, "wb"))
                if text or encoding or errors:
                    read_stream = io.TextIOWrapper(read_stream, encoding=encoding or "utf-8",
                                                   errors=errors or "strict")
                    readers.callback(read_stream.close)
                parent_streams.append(read_stream)
                child_streams.append(write_stream)
            else:
                parent_streams.append(None)
                child_streams.append(resources.enter_context(open(os.devnull, "wb")))
        child_stdin = resources.enter_context(open(os.devnull, "rb"))
        # Restrict inheritance to duplicate stdio handles. The Job and process
        # handles are never inheritable. Serialize our transient duplicates.
        with _LAUNCH_LOCK, ExitStack() as transient:
            inherited = []
            current = api.GetCurrentProcess()
            for stream in (child_stdin, *child_streams):
                duplicate = W.HANDLE()
                _check(api.DuplicateHandle(current, msvcrt.get_osfhandle(stream.fileno()),
                                           current, C.byref(duplicate), 0, True, 2))
                transient.callback(_close_handle, api, duplicate.value)
                inherited.append(duplicate.value)
            size = C.c_size_t()
            api.InitializeProcThreadAttributeList(None, 2, 0, C.byref(size))
            if not size.value:
                raise C.WinError(C.get_last_error())
            storage = C.create_string_buffer(size.value)
            _check(api.InitializeProcThreadAttributeList(storage, 2, 0, C.byref(size)))
            transient.callback(api.DeleteProcThreadAttributeList, storage)
            jobs = (W.HANDLE * 1)(job)
            handles = (W.HANDLE * 3)(*inherited)
            _check(api.UpdateProcThreadAttribute(storage, 0, _JOB_LIST, jobs,
                                                 C.sizeof(jobs), None, None))
            _check(api.UpdateProcThreadAttribute(storage, 0, _HANDLE_LIST, handles,
                                                 C.sizeof(handles), None, None))
            startup = _StartupInfoEx()
            startup.StartupInfo.cb = C.sizeof(startup)
            startup.StartupInfo.dwFlags = 0x100  # STARTF_USESTDHANDLES
            (startup.StartupInfo.hStdInput, startup.StartupInfo.hStdOutput,
             startup.StartupInfo.hStdError) = inherited
            startup.lpAttributeList = C.cast(storage, C.c_void_p)
            info = _ProcessInfo()
            resources.callback(_close_process_info, api, info)
            command = C.create_unicode_buffer(subprocess.list2cmdline(command_args))
            flags = creationflags | _EXTENDED_STARTUPINFO_PRESENT | _CREATE_UNICODE_ENVIRONMENT
            _check(api.CreateProcessW(command_args[0], command, None, None, True,
                                      flags, environment_block,
                                      None if cwd is None else os.fspath(cwd),
                                      C.byref(startup), C.byref(info)))
            # From here on every failure closes the Job and kills its tree.
            _close_handle(api, info.hThread)
            info.hThread = None
        # Commit ownership only after temporary inherited handles and child
        # pipe ends have closed successfully. Any earlier failure kills Job.
        for stream in (child_stdin, *child_streams):
            stream.close()
        process = WindowsJobProcess(api, info, job, command_args, *parent_streams,
                                    external_readers=external_readers)
        process._stream_resources = readers.pop_all()
        with _LIVE_LOCK:
            _LIVE.add(process)
        job_cleanup.pop_all()
        info.hProcess = None
        return process


def _shutdown_owned_jobs():
    with _LIVE_LOCK:
        processes = tuple(_LIVE)
    for process in processes:
        try:
            process.close()
        except Exception:
            # At interpreter exit the OS still closes the non-inherited Job.
            pass


atexit.register(_shutdown_owned_jobs)

__all__ = ["WindowsJobProcess", "launch_owned_process"]
