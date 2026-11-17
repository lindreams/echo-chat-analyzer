"""Single explicitly approved metadata experiment; NEVER invokes key/DB readers.

Self-checks use only our fictional host. Real mode observes one bounded send
metadata record and target-owned file-handle paths; it never scans account dirs.
Only fixed codes/counts/booleans leave private pipes. No account/path receipt.
"""
from __future__ import annotations

import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import struct
import subprocess
import sys
import threading
import time

from qq_chat_analyzer.providers.qq_independent.files import SourceError, _file
from qq_chat_analyzer.providers.qq_independent.process import verified_process, process_creation_ticks, loaded_module
from qq_chat_analyzer.providers.qq_independent.snapshot import bind_live_database_paths as bind_paths
from qq_chat_analyzer.runtime.windows_job import launch_owned_process

MAGIC = 0x32535145
MODULE_HASH = 'fed532ad58d2404dcedf2858554e8fa52a5f4e65b271c008d2faca4011d7d4a2'
HERE = Path(__file__).resolve().parent


def emit(phase, **fields):
    line = json.dumps({'phase': phase, **fields}, ensure_ascii=True)
    if len(line) > 2048:
        raise SourceError('diagnostic_limit')
    print(line, flush=True)


def digest(path):
    _file(path)
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked_build(root):
    root = root.resolve(strict=True)
    if not root.is_relative_to(HERE.parents[2] / 'build'):
        raise SourceError('isolated_build_required')
    receipt = json.loads((root/'build-receipt.json').read_text(encoding='utf-8-sig'))
    if receipt.get('identity_metadata_only') is not True or receipt.get('build') != '9.9.37-54395':
        raise SourceError('metadata_component_required')
    for name in ('echo_qq_event_host.exe', 'echo_event_fixture.dll', 'echo_event_54395.dll', 'echo_event_loader.exe'):
        if digest(root/name) != receipt['binaries'].get(name):
            raise SourceError('component_hash_mismatch')
    return root


def private_environment():
    result = os.environ.copy()
    for key in ('ECHO_METADATA_OWNER', 'ECHO_METADATA_LOGIN_EVENT', 'NODE_OPTIONS', 'NODE_PATH', 'PYTHONSTARTUP'):
        result.pop(key, None)
    return result


def child(argv, **kwargs):
    # Called only inside our Job, or by the fictional self-check. No QQ adoption.
    return subprocess.Popen([str(x) for x in argv], env=private_environment(),
        stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, **kwargs)


def record(payload, expected):
    if len(payload) != 36:
        raise SourceError('metadata_record_invalid')
    magic, version, raw_type, count = struct.unpack_from('<4I', payload)
    if magic != 0x31444945 or version != 1 or not 1 <= count <= 20:
        raise SourceError('metadata_record_invalid')
    value = payload[16:16+count]
    if not value.isdigit() or value.startswith(b'0') or any(payload[16+count:]):
        raise SourceError('account_representation_unknown')
    if value != expected:
        raise SourceError('independent_owner_mismatch')
    return raw_type


def frames(process):
    messages = queue.Queue(maxsize=6)
    def read_exact(count):
        value = bytearray()
        while len(value) < count:
            part = process.stdout.read(count-len(value))
            if not part:
                raise EOFError
            value.extend(part)
        return value
    def reader():
        try:
            # Exactly Ready, optional bounded metadata, Finished; EOF thereafter.
            for _ in range(4):
                header = read_exact(16)
                magic, kind, length, reserved = struct.unpack('<4I', header)
                if magic != MAGIC or reserved or kind not in (1, 2, 3) or length not in (0, 16, 36):
                    raise ValueError
                messages.put((kind, read_exact(length)))
        except (EOFError, OSError, ValueError):
            messages.put(None)
    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    return messages, thread


def native_api():
    api = C.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]; api.OpenProcess.restype = W.HANDLE
    api.CloseHandle.argtypes = [W.HANDLE]; api.CloseHandle.restype = W.BOOL
    api.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]; api.WaitForSingleObject.restype = W.DWORD
    api.GetCurrentProcess.restype = W.HANDLE
    api.CreateEventW.argtypes = [C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR]; api.CreateEventW.restype = W.HANDLE
    api.OpenEventW.argtypes = [W.DWORD, W.BOOL, W.LPCWSTR]; api.OpenEventW.restype = W.HANDLE
    api.SetEvent.argtypes = [W.HANDLE]; api.SetEvent.restype = W.BOOL
    api.DuplicateHandle.argtypes = [W.HANDLE, W.HANDLE, W.HANDLE, C.POINTER(W.HANDLE), W.DWORD, W.BOOL, W.DWORD]
    api.DuplicateHandle.restype = W.BOOL
    api.GetFileType.argtypes = [W.HANDLE]; api.GetFileType.restype = W.DWORD
    api.GetFinalPathNameByHandleW.argtypes = [W.HANDLE, W.LPWSTR, W.DWORD, W.DWORD]
    api.GetFinalPathNameByHandleW.restype = W.DWORD
    return api


def process_candidates():
    """Executable/module metadata only; no command lines or user configuration."""
    from qq_chat_analyzer.application.qq.qq_version import read_qq_resources
    class Entry(C.Structure):
        _fields_ = [('size', W.DWORD), ('usage', W.DWORD), ('pid', W.DWORD), ('heap', C.c_size_t),
            ('module', W.DWORD), ('threads', W.DWORD), ('parent', W.DWORD), ('priority', W.LONG),
            ('flags', W.DWORD), ('name', W.WCHAR*260)]
    api = native_api()
    api.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]; api.CreateToolhelp32Snapshot.restype = W.HANDLE
    api.Process32FirstW.argtypes = api.Process32NextW.argtypes = [W.HANDLE, C.POINTER(Entry)]
    api.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    snapshot = api.CreateToolhelp32Snapshot(2, 0)
    if snapshot == W.HANDLE(-1).value:
        raise SourceError('process_snapshot_unavailable')
    result, qq_count = [], 0
    try:
        entry = Entry(); entry.size = C.sizeof(entry)
        ok = api.Process32FirstW(snapshot, C.byref(entry))
        while ok:
            if entry.name.casefold() == 'qq.exe':
                qq_count += 1
                handle = api.OpenProcess(0x1000, False, entry.pid)
                if not handle:
                    raise SourceError('qq_process_metadata_unavailable')
                try:
                    image = C.create_unicode_buffer(32768); length = W.DWORD(len(image))
                    if not api.QueryFullProcessImageNameW(handle, 0, image, C.byref(length)):
                        raise SourceError('qq_process_metadata_unavailable')
                    image = Path(image.value)
                finally:
                    api.CloseHandle(handle)
                resources = read_qq_resources(image)
                if resources is None or resources.version != (9, 9, 37, 54395) or resources.wrapper_path is None:
                    raise SourceError('exact_active_version_required')
                with verified_process(entry.pid, image) as (query, process):
                    if loaded_module(query, process, resources.wrapper_path)[1]:
                        result.append((entry.pid, process_creation_ticks(query, process), image, resources))
            ok = api.Process32NextW(snapshot, C.byref(entry))
    finally:
        api.CloseHandle(snapshot)
    if qq_count > 24 or len(result) != 1:
        emit('process_selection_refused', qq_process_count=qq_count, loaded_wrapper_candidates=len(result))
        raise SourceError('unique_loaded_qq_process_required')
    return result[0]


PATH_COUNTS = ('target_file_handles', 'duplicated_handles', 'disk_handles', 'resolved_paths', 'database_paths',
    'verified_raw_device_endpoints')
PATH_NATIVE_FIELDS = {'win32_error': (0, 0xffffffff), 'file_kind': (0, 0xffff),
    'device_type': (0, 0xffff), 'nt_status': (-0x80000000, 0x7fffffff)}


def path_reply(raw, returncode):
    """Forward only fixed child failures/counters, never its private paths."""
    if len(raw) > 131072:
        raise SourceError('target_paths_reply_limit')
    reply = json.loads(raw)
    if not isinstance(reply, dict):
        raise SourceError('target_paths_reply_invalid')
    counts = reply.get('counts', {})
    if not isinstance(counts, dict) or set(counts)-(set(PATH_COUNTS)|set(PATH_NATIVE_FIELDS)) or any(
        type(v) is not int or not PATH_NATIVE_FIELDS.get(k, (0, 16384))[0] <= v <= PATH_NATIVE_FIELDS.get(k, (0, 16384))[1]
        for k, v in counts.items()):
        raise SourceError('target_paths_reply_invalid')
    if returncode or reply.get('phase') == 'paths_refused':
        reason = reply.get('reason')
        allowed = {'process_generation_changed', 'handle_query_unavailable', 'handle_snapshot_unavailable',
            'handle_snapshot_limit', 'handle_snapshot_invalid', 'file_handle_type_unavailable',
            'target_handle_limit', 'target_file_handle_changed_or_inaccessible', 'target_disk_path_unavailable',
            'target_file_kind_query_failed',
            'local_database_path_required', 'database_path_limit', 'duplicate_close_unconfirmed',
            'process_read_access_unavailable', 'process_identity_unavailable', 'process_identity_mismatch',
            'process_handle_close_failed', 'unknown_device_name_unavailable', 'unknown_device_name_invalid'}
        if not isinstance(reason, str) or (reason not in allowed and not re.fullmatch(r'target_file_kind_unknown_device_[0-9]{1,10}_status_-?[0-9]{1,10}', reason)):
            reason = 'target_paths_unavailable'
        emit('path_query_refused', reason=reason, **counts)
        raise SourceError(reason)
    paths = reply.get('paths')
    if reply.get('phase') != 'paths' or not isinstance(paths, list) or len(paths) > 128 or any(not isinstance(p, str) or len(p) > 32768 for p in paths):
        raise SourceError('target_paths_reply_invalid')
    emit('path_query_verified', **counts)
    return paths


def query_paths(pid, created, image):
    process = launch_owned_process([sys.executable, str(HERE/'identity_probe.py'), '--paths', '--pid', str(pid),
        '--created', str(created), '--image', str(image)], env=private_environment(),
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        raw, _ = process.communicate(timeout=8)
        return path_reply(raw, process.returncode)
    finally:
        # Includes a possible venv redirector child. Never terminate QQ or the
        # outer observer's Job when a filesystem-driver query times out.
        process.close_with_exit_evidence(timeout=3)


def raw_device_endpoint(name):
    # A successful native object-name query must identify the device itself,
    # with NO file component. Such a handle is not an account's regular DB file.
    # Never skip an unknown filesystem path, unnamed object or failed query.
    prefix = '\\device\\'
    if not name.casefold().startswith(prefix):
        return False
    leaf = name[len(prefix):]
    return leaf not in ('.', '..') and re.fullmatch(r'[A-Za-z0-9_.{}-]{1,128}', leaf) is not None


def file_object_name(nt, handle, counts):
    """Metadata only, ONLY in the separately bounded file-query child.

    Native name queries can block in a driver. The parent retains its existing
    8-second budget and owned Job; failure/unknown release never becomes success.
    The name stays on private memory and is never a public diagnostic.
    """
    class UnicodeString(C.Structure):
        _fields_ = [('length', W.USHORT), ('capacity', W.USHORT), ('data', C.c_void_p)]
    nt.NtQueryObject.argtypes = [W.HANDLE, W.ULONG, C.c_void_p, W.ULONG, C.POINTER(W.ULONG)]
    nt.NtQueryObject.restype = W.LONG
    data = C.create_string_buffer(65536+64); required = W.ULONG()
    result = nt.NtQueryObject(handle, 1, data, len(data), C.byref(required))
    counts['nt_status'] = result
    if result != 0 or required.value > len(data):
        raise SourceError('unknown_device_name_unavailable')
    value = UnicodeString.from_buffer(data)
    start, end = C.addressof(data)+C.sizeof(UnicodeString), C.addressof(data)+len(data)
    if not value.length or value.length%2 or value.capacity%2 or value.capacity < value.length or not value.data or not start <= value.data <= end-value.capacity:
        raise SourceError('unknown_device_name_invalid')
    try:
        name = C.string_at(value.data, value.length).decode('utf-16-le')
        if '\0' in name:
            raise SourceError('unknown_device_name_invalid')
        return name
    finally:
        C.memset(C.addressof(data), 0, len(data))


def handle_paths(pid, created, image, counts):
    """Private child: duplicate/query ONLY this exact process's DISK handles.

    No ReadFile, ReadProcessMemory or file-content API. Parent
    bounds this child because a filesystem metadata query may block in a driver.
    """
    class Entry(C.Structure):
        _fields_ = [('object', C.c_void_p), ('pid', C.c_size_t), ('handle', C.c_size_t),
            ('access', W.ULONG), ('trace', W.USHORT), ('type', W.USHORT), ('attributes', W.ULONG), ('reserved', W.ULONG)]
    with verified_process(pid, image) as (query, process):
        if process_creation_ticks(query, process) != created:
            raise SourceError('process_generation_changed')
        api = native_api(); source = api.OpenProcess(0x1040, False, pid)
        if not source:
            counts['win32_error'] = C.get_last_error()
            raise SourceError('handle_query_unavailable')
        # Learn the File object type from an owned, known regular file. This
        # excludes unrelated object types WITHOUT querying their names. A failed
        # duplication of a target File handle cannot silently hide an account.
        import msvcrt
        reference_file = Path(__file__).open('rb')
        try:
            nt = C.WinDLL('ntdll')
            nt.NtQuerySystemInformation.argtypes = [W.ULONG, C.c_void_p, W.ULONG, C.POINTER(W.ULONG)]
            nt.NtQuerySystemInformation.restype = W.LONG
            size = 1 << 20
            while True:
                data = C.create_string_buffer(size); needed = W.ULONG()
                status = nt.NtQuerySystemInformation(64, data, size, C.byref(needed))
                if status == 0:
                    break
                if status != -1073741820 or size >= 64*1024*1024:
                    counts['nt_status'] = status
                    raise SourceError('handle_snapshot_unavailable')
                size = max(size*2, needed.value+65536)
                if size > 64*1024*1024:
                    raise SourceError('handle_snapshot_limit')
            count = C.c_size_t.from_buffer(data).value
            offset = 2*C.sizeof(C.c_size_t)
            if count > (size-offset)//C.sizeof(Entry):
                raise SourceError('handle_snapshot_invalid')
            entries = (Entry*count).from_buffer(data, offset)
            reference = msvcrt.get_osfhandle(reference_file.fileno())
            file_types = {item.type for item in entries if item.pid == os.getpid() and item.handle == reference}
            if len(file_types) != 1:
                raise SourceError('file_handle_type_unavailable')
            file_type = next(iter(file_types))
            selected = [item.handle for item in entries if item.pid == pid and item.type == file_type]
            counts['target_file_handles'] = min(len(selected), 16384)
            if len(selected) > 16384:
                raise SourceError('target_handle_limit')
            paths = set()
            for value in selected:
                for field in PATH_NATIVE_FIELDS:
                    counts.pop(field, None)
                duplicate = W.HANDLE()
                # Zero access: GetFileType/name queries require no content rights.
                # Never close/change the target's handle or duplicate WRITE rights.
                if not api.DuplicateHandle(source, value, api.GetCurrentProcess(), C.byref(duplicate), 0, False, 0):
                    counts['win32_error'] = C.get_last_error()
                    raise SourceError('target_file_handle_changed_or_inaccessible')
                counts['duplicated_handles'] += 1
                try:
                    C.set_last_error(0)
                    kind = api.GetFileType(duplicate)
                    counts['file_kind'] = kind
                    counts['win32_error'] = C.get_last_error()
                    if kind in (2, 3):
                        continue
                    if kind != 1:
                        # Diagnostic metadata only. A valid UNKNOWN can be a
                        # kernel device, but never silently assume it is safe.
                        class Status(C.Structure):
                            _fields_ = [('status', C.c_void_p), ('information', C.c_size_t)]
                        status = Status(); device = (W.ULONG*2)()
                        if kind != 0 or counts['win32_error'] != 0:
                            raise SourceError('target_file_kind_query_failed')
                        nt.NtQueryVolumeInformationFile.argtypes = [W.HANDLE, C.POINTER(Status), C.c_void_p, W.ULONG, W.ULONG]
                        nt.NtQueryVolumeInformationFile.restype = W.LONG
                        result = nt.NtQueryVolumeInformationFile(duplicate, C.byref(status), device, C.sizeof(device), 4)
                        counts['nt_status'] = result
                        counts['device_type'] = device[0]
                        # Classify the object, not a list of driver type codes.
                        # A valid UNKNOWN still needs independent successful
                        # device metadata AND a bounded exact endpoint name.
                        if result == 0:
                            if raw_device_endpoint(file_object_name(nt, duplicate, counts)):
                                counts['verified_raw_device_endpoints'] += 1
                                continue
                        raise SourceError('target_file_kind_unknown_device_'+str(device[0])+'_status_'+str(result))
                    name = C.create_unicode_buffer(32768)
                    counts['disk_handles'] += 1
                    n = api.GetFinalPathNameByHandleW(duplicate, name, len(name), 0)
                    if not n or n >= len(name) or not name.value.startswith('\\\\?\\'):
                        counts['win32_error'] = C.get_last_error()
                        raise SourceError('target_disk_path_unavailable')
                    counts['resolved_paths'] += 1
                    if n and n < len(name) and name.value.startswith('\\\\?\\'):
                        path = name.value[4:]
                        if '\\nt_qq\\nt_db\\' in path.casefold():
                            if len(path) < 3 or path[1:3] != ':\\':
                                raise SourceError('local_database_path_required')
                            paths.add(path)
                            counts['database_paths'] = len(paths)
                            if len(paths) > 128:
                                raise SourceError('database_path_limit')
                finally:
                    if not api.CloseHandle(duplicate):
                        raise SourceError('duplicate_close_unconfirmed')
            if process_creation_ticks(query, process) != created:
                raise SourceError('process_generation_changed')
            return sorted(paths)
        finally:
            reference_file.close()
            api.CloseHandle(source)


def self_check(root):
    host, fixture, production = (root/n for n in ('echo_qq_event_host.exe', 'echo_event_fixture.dll', 'echo_event_54395.dll'))
    checks = 0
    for scenario in ('delivery', 'heap', 'invalid', 'cancel', 'timeout', 'install_failure', 'production_gate'):
        p = child([host, production if scenario == 'production_gate' else fixture, scenario], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        output, _ = p.communicate(timeout=10)
        if p.returncode or output != struct.pack('<4I', MAGIC, 1, 1, 0):
            raise SourceError('metadata_fixture_refused')
        checks += 1
    for scenario in ('session-delivery', 'session-cancel', 'session-timeout'):
        p = child([host, fixture, scenario], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            head = p.stdout.read(16)
            magic, pid, created = struct.unpack('<IIQ', head)
            if magic != MAGIC:
                raise SourceError('fixture_identity_invalid')
            loader = child([root/'echo_event_loader.exe', '--fixture', pid, created, host, fixture, '9.9.37-54395'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            messages, reader = frames(loader)
            loader.stdin.write(struct.pack('<4I32s', MAGIC, 54395, 1000, 0, bytes.fromhex(digest(host)))); loader.stdin.flush()
            ready = delivered = finished = False
            while True:
                item = messages.get(timeout=5)
                if item is None:
                    break
                kind, value = item
                if kind == 1 and not ready:
                    ready = True
                    if scenario == 'session-cancel':
                        loader.stdin.write(b'X'); loader.stdin.flush()
                elif kind == 2 and ready and not delivered:
                    if record(value, b'100000001') != 1:
                        raise SourceError('fixture_type_invalid')
                    delivered = True
                elif kind == 3:
                    finished = struct.unpack('<4I', value) == (1, 1, 0, 1)
            loader.wait(timeout=4); reader.join(timeout=1)
            loader.stdin.close(); loader.stdout.close()
            tail, _ = p.communicate(timeout=4)
            if loader.returncode or p.returncode or not ready or not finished or delivered != (scenario == 'session-delivery') or tail != struct.pack('<4I', MAGIC, 1, 1, 128):
                raise SourceError('metadata_transport_fixture_refused')
        finally:
            if p.poll() is None:
                p.stdin.write(b'X'); p.stdin.flush(); p.wait(timeout=4)
        checks += 1
    for payload in (b'', struct.pack('<4I20s', 0x31444945, 1, 1, 9, b'100000002')):
        try:
            record(payload, b'100000001')
        except SourceError:
            checks += 1
        else:
            raise SourceError('metadata_rejection_fixture_failed')
    holder = child([sys.executable, HERE/'identity_probe.py', '--build-root', root, '--fixture-file-holder'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        identity = json.loads(holder.stdout.readline(4096))
        paths = query_paths(identity['pid'], identity['created'], identity['image'])
        main = bind_paths(paths, b'100000001')
        if main != Path(identity['main']) or not main.is_relative_to(root/'fictional'):
            raise SourceError('fixture_path_binding_failed')
        checks += 1
        for evidence, owner in ((paths, b'100000002'),
            (paths+[str(root/'fictional'/'100000002'/'nt_qq'/'nt_db'/'nt_msg.db')], b'100000001')):
            try:
                bind_paths(evidence, owner)
            except SourceError:
                checks += 1
            else:
                raise SourceError('fixture_binding_conflict_accepted')
        import shutil
        node = shutil.which('node')
        if not node:
            raise SourceError('node_required')
        lock = child([node, HERE/'identity_lock_probe.mjs'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        metadata, _ = lock.communicate(json.dumps({'main': str(main), 'wal': str(main)+'-wal'}).encode('utf-8'), timeout=16)
        result = json.loads(metadata)
        if lock.returncode or not all(result.get(key) is True for key in ('locks_acquired', 'witness_valid', 'released')):
            raise SourceError('fixture_lock_metadata_probe_failed')
        checks += 1
    finally:
        holder.stdin.close(); holder.wait(timeout=5); holder.stdout.close()
    if holder.returncode:
        raise SourceError('fixture_source_release_failed')
    # A helper refusal must retain its specific fixed condition and counts.
    try:
        path_reply(json.dumps({'phase': 'paths_refused', 'reason': 'target_disk_path_unavailable',
            'counts': {'target_file_handles': 7, 'duplicated_handles': 3, 'disk_handles': 1}}).encode(), 1)
    except SourceError as error:
        if error.code != 'target_disk_path_unavailable':
            raise SourceError('fixture_path_refusal_lost')
    else:
        raise SourceError('fixture_path_refusal_accepted')
    checks += 1
    if not raw_device_endpoint('\\Device\\FictionalGraphicsDevice') or any(raw_device_endpoint(name) for name in (
        '', '\\Device\\DxgKrnl\\nt_qq\\nt_db\\nt_msg.db',
        '\\Device\\HarddiskVolume1\\nt_qq\\nt_db\\nt_msg.db', '\\Device\\..', '\\??\\C:\\nt_qq\\nt_db')):
        raise SourceError('fixture_graphics_classification_failed')
    checks += 1
    emit('offline_verified', checks=checks, real_qq_accessed=False, payload_guard_page_untouched=True,
         original_function_preserved=True, fixture_components_unloaded=True)


def fixture_file_holder(root, *, graphics=False, network_device=False):
    """Only this build's freshly created fictional files, never a user folder."""
    from contextlib import ExitStack
    import sqlite3
    import uuid
    directory = root/'fictional'/uuid.uuid4().hex/'100000001'/'nt_qq'/'nt_db'
    directory.mkdir(parents=True, exist_ok=False)
    api = native_api()
    api.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    image = C.create_unicode_buffer(32768); length = W.DWORD(len(image))
    if not api.QueryFullProcessImageNameW(api.GetCurrentProcess(), 0, image, C.byref(length)):
        raise SourceError('fixture_process_identity_failed')
    with ExitStack() as resources:
        if network_device:
            # Open an owned zero-access NSI device handle, without querying
            # adapters, addresses, network configuration or sending traffic.
            api.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
            api.CreateFileW.restype = W.HANDLE
            device = api.CreateFileW('\\\\.\\Nsi', 0, 7, None, 3, 0, None)
            if device == W.HANDLE(-1).value:
                raise SourceError('fixture_network_device_unavailable')
            resources.callback(api.CloseHandle, device)
            # Ensure this fixture actually reproduces the observed network
            # class, rather than merely passing with some unrelated handle.
            class IoStatus(C.Structure):
                _fields_ = [('status', C.c_void_p), ('information', C.c_size_t)]
            nt = C.WinDLL('ntdll')
            nt.NtQueryVolumeInformationFile.argtypes = [W.HANDLE, C.POINTER(IoStatus), C.c_void_p, W.ULONG, W.ULONG]
            nt.NtQueryVolumeInformationFile.restype = W.LONG
            info = (W.ULONG*2)(); status = IoStatus()
            result = nt.NtQueryVolumeInformationFile(device, C.byref(status), info, C.sizeof(info), 4)
            if api.GetFileType(device) != 0 or result != 0 or info[0] != 18:
                raise SourceError('fixture_network_device_class_not_reproduced')
        if graphics:
            # Owned Windows graphics device, to reproduce file-device handles
            # used by desktop apps without launching or inspecting QQ.
            d3d = C.WinDLL('d3d11')
            d3d.D3D11CreateDevice.argtypes = [C.c_void_p, C.c_uint, W.HMODULE, C.c_uint,
                C.c_void_p, C.c_uint, C.c_uint, C.POINTER(C.c_void_p), C.POINTER(C.c_uint), C.POINTER(C.c_void_p)]
            d3d.D3D11CreateDevice.restype = W.LONG
            device, context, level = C.c_void_p(), C.c_void_p(), C.c_uint()
            result = d3d.D3D11CreateDevice(None, 1, None, 0, None, 0, 7,
                C.byref(device), C.byref(level), C.byref(context))
            def release(value):
                if value:
                    table = C.cast(value, C.POINTER(C.POINTER(C.c_void_p))).contents
                    C.WINFUNCTYPE(W.ULONG, C.c_void_p)(table[2])(value)
            resources.callback(release, device); resources.callback(release, context)
            if result < 0 or not device or not context:
                raise SourceError('fixture_graphics_unavailable')
        connection = sqlite3.connect(directory/'nt_msg.db')
        resources.callback(connection.close)
        connection.execute('PRAGMA page_size=4096')
        if connection.execute('PRAGMA journal_mode=WAL').fetchone()[0] != 'wal':
            raise SourceError('fixture_wal_unavailable')
        connection.execute('CREATE TABLE fictional(value INTEGER)')
        connection.execute('INSERT INTO fictional VALUES(1)'); connection.commit()
        for suffix in ('', '-wal', '-shm'):
            resources.enter_context((directory/('nt_msg.db'+suffix)).open('rb'))
        print(json.dumps({'pid': os.getpid(), 'created': process_creation_ticks(api, api.GetCurrentProcess()),
            'image': image.value, 'main': str(directory/'nt_msg.db')}), flush=True)
        sys.stdin.buffer.read(1)


def read_owner_reference():
    """Operator-only masked input; never a product identity input or file."""
    import getpass
    import msvcrt
    mode = W.DWORD()
    api = native_api()
    api.GetConsoleMode.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    if not api.GetConsoleMode(msvcrt.get_osfhandle(sys.stdin.fileno()), C.byref(mode)):
        raise SourceError('private_console_required')
    reference = getpass.getpass('Private owner reference (hidden): ')
    if not reference.isascii() or not reference.isdigit() or reference.startswith('0') or not 5 <= len(reference) <= 20:
        raise SourceError('independent_owner_reference_required')
    return reference


def probe_lock_metadata(main):
    import shutil
    node = shutil.which('node')
    if not node:
        raise SourceError('node_required')
    probe = child([node, HERE/'identity_lock_probe.mjs'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        lock_output, _ = probe.communicate(json.dumps({'main': str(main), 'wal': str(main)+'-wal'}).encode('utf-8'), timeout=16)
        if len(lock_output) > 2048:
            raise SourceError('lock_diagnostic_limit')
        result = json.loads(lock_output)
        allowed = {'phase', 'locks_acquired', 'witness_valid', 'released', 'database_content_read',
            'committed_boundary_present', 'refusal'}
        if not isinstance(result, dict) or set(result)-allowed or result.get('phase') != 'lock_probe':
            raise SourceError('lock_diagnostic_invalid')
        emit('live_lock_metadata', locks_acquired=result.get('locks_acquired') is True,
             witness_valid=result.get('witness_valid') is True, released=result.get('released') is True,
             database_content_read=False, full_snapshot_attempted=False,
             refusal=result.get('refusal') if result.get('refusal') in {
                 'source_guard_failed', 'checkpoint_witness_missing', 'checkpoint_witness_torn',
                 'checkpoint_witness_invalid', 'checkpoint_state_invalid', 'short_read',
                 'lock_or_witness_unavailable', 'source_release_unconfirmed'} else None)
        if probe.returncode or not all(result.get(k) is True for k in ('locks_acquired', 'witness_valid', 'released')):
            reason = result.get('refusal')
            if reason not in {'source_guard_failed', 'checkpoint_witness_missing', 'checkpoint_witness_torn',
                'checkpoint_witness_invalid', 'checkpoint_state_invalid', 'short_read',
                'lock_or_witness_unavailable', 'source_release_unconfirmed'}:
                reason = 'live_lock_validation_failed'
            raise SourceError(reason)
    finally:
        if probe.poll() is None:
            probe.terminate(); probe.wait(timeout=3) # Only our Node; guard also has its own TTL.
        for stream in (probe.stdin, probe.stdout):
            if stream and not stream.closed:
                stream.close()


def real_worker(root):
    expected = os.environ.pop('ECHO_METADATA_OWNER', '').encode('ascii')
    if not expected.isdigit() or expected.startswith(b'0') or not 5 <= len(expected) <= 20:
        raise SourceError('independent_owner_reference_required')
    pid, created, image, resources = process_candidates()
    if digest(resources.wrapper_path) != MODULE_HASH:
        raise SourceError('module_hash_mismatch')
    # This independent disk inspection confirms where the pinned native log
    # obtains the account string and type argument. It proves a layout, NOT a
    # current identity. Only the later runtime/owner comparison can do that.
    from identity_layout_check import inspect
    wrapper, _, _ = inspect()
    if wrapper != resources.wrapper_path:
        raise SourceError('installed_module_selection_conflict')
    api = native_api()
    generation = api.OpenProcess(0x101000, False, pid) # QUERY_LIMITED + SYNCHRONIZE
    if not generation:
        raise SourceError('generation_handle_unavailable')
    try:
        if process_creation_ticks(api, generation) != created:
            raise SourceError('generation_handle_unavailable')
        attempt = root/'metadata-attempt-started'
        # Exclusive one-shot marker: no retry against another generation with this build.
        with attempt.open('x', encoding='ascii') as stream:
            stream.write('metadata-only; no key or chat read\n')
    except Exception:
        api.CloseHandle(generation)
        raise
    helper = None
    login_name = os.environ.pop('ECHO_METADATA_LOGIN_EVENT', '')
    login_event = api.OpenEventW(0x100000, False, login_name)
    if not login_name.startswith('Local\\EchoQQMetadataLogin-') or not login_event:
        api.CloseHandle(generation)
        raise SourceError('independent_login_confirmation_unavailable')
    armed = finished = False
    observation_end = time.monotonic()+120
    try:
        helper = child([root/'echo_event_loader.exe', '--approved-qq', pid, created, image, root/'echo_event_54395.dll', '9.9.37-54395'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        messages, reader = frames(helper)
        helper.stdin.write(struct.pack('<4I32s', MAGIC, 54395, 120000, 0, bytes.fromhex(digest(image)))); helper.stdin.flush()
        captured_type = None
        while time.monotonic() < observation_end+4:
            try:
                item = messages.get(timeout=0.2)
            except queue.Empty:
                if helper.poll() is not None:
                    break
                continue
            if item is None:
                break
            kind, value = item
            try:
                if kind == 1 and not armed and not value:
                    armed = True
                    remaining = max(0, int((observation_end-time.monotonic())*1000))
                    emit('armed', remaining_login_ms=remaining,
                         login_before_utc=(datetime.now(timezone.utc)+timedelta(milliseconds=remaining)).isoformat(),
                         metadata_only=True, key_capture_enabled=False)
                elif kind == 2 and armed and captured_type is None:
                    captured_type = record(value, expected)
                elif kind == 3 and armed:
                    stopped = struct.unpack('<4I', value)
                    finished = stopped == (1, 1, 0, 1)
                    if not finished:
                        raise SourceError('observation_stop_unconfirmed')
                    emit('observation_stopped', owner_reference_matches=captured_type is not None,
                         candidate_records=int(captured_type is not None), raw_account_type=captured_type,
                         reads_stopped=True, inflight=0, component_unloaded=False)
                else:
                    raise SourceError('metadata_frame_order_invalid')
            finally:
                value[:] = b'\0'*len(value)
        helper.wait(timeout=3); reader.join(timeout=1)
        if helper.returncode or not finished or captured_type is None:
            raise SourceError('metadata_observation_incomplete')
        # The targeted send may precede completion of normal QQ login. Do not
        # misclassify a not-yet-open database as a binding failure, or infer
        # online state from that outgoing task. Operator forwards the owner's
        # explicit normal-login confirmation through a private nonce event.
        emit('awaiting_login_confirmation', automatic_online_detection_proven=False)
        confirmation_end = min(observation_end+30, time.monotonic()+90)
        while api.WaitForSingleObject(login_event, 100) == 258:
            if time.monotonic() >= confirmation_end or api.WaitForSingleObject(generation, 0) != 258:
                raise SourceError('independent_login_confirmation_missing')
        # A numeric match alone is deliberately NOT a production account-type
        # enum definition or a continuous login-generation/online declaration.
        # Bind the single authorized process/path as experimental evidence only.
        paths = query_paths(pid, created, image)
        main = bind_paths(paths, expected)
        del paths
        emit('path_binding', current_authorized_account_match=True, unique_account_directory=True,
             process_generation_matches=process_creation_ticks(api, generation) == created,
             observed_namespace_matches_independent_uin=True,
             raw_type_general_enum_definition_proven=False, production_binding_ready=False)
        # The observed string is independently confirmed as THIS owner's UIN.
        # Do not invent a global enum mapping or treat every numeric task as
        # a current-user declaration. This evidence is scoped to this attempt.
        probe_lock_metadata(main)
        # Re-enumerate the same target after releasing source locks. A newly
        # opened second account or vanished source invalidates this experiment.
        if bind_paths(query_paths(pid, created, image), expected) != main:
            raise SourceError('post_lock_account_binding_changed')
        emit('metadata_validation_complete', observed_owner_and_path_match=True,
             live_locks_and_witness_valid=True, account_binding_rechecked=True,
             current_online_role_automatically_proven=False, login_epoch_observed=False,
             production_prerequisites_complete=False)
    except Exception as error:
        emit('experiment_stopped', reason=error.code if isinstance(error, SourceError) else 'metadata_experiment_refused',
             armed=armed, stop_confirmed=finished, key_extraction_attempted=False, database_content_read=False,
             automatic_retry=False)
    finally:
        expected = b''
        api.CloseHandle(login_event)
        if helper:
            if helper.stdin and not helper.stdin.closed:
                helper.stdin.close() # Parent EOF requests observation stop.
            try:
                helper.wait(timeout=4)
            except subprocess.TimeoutExpired:
                helper.terminate(); helper.wait(timeout=3) # Own loader ONLY.
            if helper.stdout:
                helper.stdout.close()
        emit('awaiting_normal_qq_exit', user_action_required=True, component_unloaded=False,
             no_keys_or_plaintext_created=True)
        end = time.monotonic()+900
        while api.WaitForSingleObject(generation, 200) == 258 and time.monotonic() < end:
            pass
        exited = api.WaitForSingleObject(generation, 0) == 0
        api.CloseHandle(generation)
        emit('cleanup', bound_qq_generation_exited=exited, component_unloaded=exited,
             no_keys_or_plaintext_created=True, private_identity_not_persisted=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', type=Path)
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--check-worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--fixture-file-holder', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--fixture-graphics', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--fixture-network-device', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--approved-single-session', action='store_true')
    parser.add_argument('--owner-reference-stdin', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--paths', action='store_true')
    parser.add_argument('--pid', type=int); parser.add_argument('--created', type=int); parser.add_argument('--image', type=Path)
    args = parser.parse_args()
    if args.paths:
        # Private pipe output only; outer owned Job contains this child.
        counts = dict.fromkeys(PATH_COUNTS, 0)
        try:
            paths = handle_paths(args.pid, args.created, args.image, counts)
        except Exception as error:
            print(json.dumps({'phase': 'paths_refused', 'reason': error.code if isinstance(error, SourceError)
                else 'target_paths_unavailable', 'counts': counts}), flush=True)
            raise SystemExit(1)
        print(json.dumps({'phase': 'paths', 'paths': paths, 'counts': counts}), flush=True)
        return
    root = checked_build(args.build_root)
    if args.fixture_file_holder:
        fixture_file_holder(root, graphics=args.fixture_graphics, network_device=args.fixture_network_device)
        return
    if args.worker:
        if not args.approved_single_session:
            raise SourceError('single_session_approval_required')
        real_worker(root)
        return
    if args.self_check and args.check_worker:
        self_check(root)
        return
    # All probes and fictional hosts are atomically created inside our Job.
    command = [sys.executable, str(HERE/'identity_probe.py'), '--build-root', str(root)]
    command += ['--worker', '--approved-single-session'] if args.approved_single_session else ['--self-check', '--check-worker']
    if not args.approved_single_session and not args.self_check:
        raise SourceError('single_session_approval_required')
    if args.owner_reference_stdin:
        # Operator supplies the previously confirmed reference through a masked
        # console input, never a shell argument, saved file or printed prompt.
        if not args.approved_single_session:
            raise SourceError('single_session_approval_required')
        os.environ['ECHO_METADATA_OWNER'] = read_owner_reference()
    environment = os.environ.copy()
    os.environ.pop('ECHO_METADATA_OWNER', None)
    login_event = None
    api = native_api()
    if args.approved_single_session:
        import uuid
        login_name = 'Local\\EchoQQMetadataLogin-'+uuid.uuid4().hex
        login_event = api.CreateEventW(None, True, False, login_name)
        if not login_event:
            raise SourceError('login_confirmation_event_unavailable')
        environment['ECHO_METADATA_LOGIN_EVENT'] = login_name
    try:
        process = launch_owned_process(command, cwd=root, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW, external_readers=True,
            text=True, encoding='ascii')
    except Exception:
        if login_event:
            api.CloseHandle(login_event)
        raise
    environment.pop('ECHO_METADATA_OWNER', None)
    controls_done = threading.Event()
    armed_seen = threading.Event()
    def confirm_login():
        import msvcrt
        while not controls_done.wait(.02):
            if msvcrt.kbhit():
                value = msvcrt.getwch()
                if value.upper() == 'L' and armed_seen.is_set():
                    api.SetEvent(login_event)
                    return
    def forward():
        for _ in range(32):
            line = process.stdout.readline(2049)
            if not line:
                return
            if len(line) > 2048:
                return
            if json.loads(line).get('phase') == 'armed':
                armed_seen.set()
            print(line.rstrip(), flush=True)
    reader = threading.Thread(target=forward, daemon=True)
    process.set_external_readers((reader,)); reader.start()
    controls = None
    if login_event and args.owner_reference_stdin:
        controls = threading.Thread(target=confirm_login, daemon=True)
        controls.start()
    try:
        process.wait(timeout=1040)
        reader.join(timeout=2)
        if process.returncode:
            raise SourceError('metadata_worker_refused')
    finally:
        controls_done.set()
        if controls:
            controls.join(timeout=1)
        if login_event:
            api.CloseHandle(login_event)
        process.terminate_tree() # The Job NEVER contains the user-owned QQ.
        end = time.monotonic()+4
        while process.active_process_count() and time.monotonic() < end:
            time.sleep(.01)
        if process.active_process_count():
            raise SourceError('owned_helpers_release_unconfirmed')
        reader.join(timeout=1)
        process.close_after_readers((reader,), deadline=time.monotonic()+2)
        emit('owned_helpers_released', active_helpers=0)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        emit('refused', reason=error.code if isinstance(error, SourceError) else 'metadata_probe_refused')
        sys.exit(1)
