"""One approved QQ context window -> ephemeral candidates -> page-one MAC.

Default is plan-only. A window needs independently observed context evidence;
this tool does NOT discover that address, walk heaps or scan an address space.
Executing against real business memory requires separate human approval.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from qq_windows_source import SourceError, WRAPPED, _file, _safe, _format, _read_unchanged
from qq_windows_process_probe import verified_process, loaded_module, process_creation_ticks

MAX_WINDOW = 65536
CHUNK = 4096
MAX_CANDIDATES = 16
WORK_SECONDS = 8
HARD_SECONDS = 10
# Observed representation, not upstream scan code. A complete SQLCipher raw
# key literal contains 32 key bytes + 16 salt bytes. Matching salt is NOT proof.
LITERAL = re.compile(rb"x'([0-9a-fA-F]{64})([0-9a-fA-F]{32})'")


def plan(spec, *, fixture=False):
    if not isinstance(spec, dict) or set(spec) != {"pid", "executable", "created_ticks", "module", "database", "window"}:
        raise SourceError("invalid_request")
    if type(spec["pid"]) is not int or not 0 < spec["pid"] <= 0xFFFFFFFF:
        raise SourceError("invalid_process_selection")
    if type(spec["created_ticks"]) is not int or spec["created_ticks"] <= 0:
        raise SourceError("process_creation_required")
    for field in ("executable", "module", "database"):
        if not isinstance(spec[field], str) or not spec[field] or "\0" in spec[field] or not Path(spec[field]).is_absolute():
            raise SourceError("invalid_request")
    window = spec["window"]
    if not isinstance(window, dict) or set(window) != {"address", "size", "evidence"}:
        raise SourceError("bounded_key_context_missing")
    evidence = "owned_fixture" if fixture else "observed_codec_context"
    if window["evidence"] != evidence:
        raise SourceError("bounded_key_context_missing")
    address, size = window["address"], window["size"]
    if type(address) is not int or type(size) is not int or not 0 < size <= MAX_WINDOW or not 0x10000 <= address < address + size <= 0x7FFFFFFFFFFF:
        raise SourceError("window_limit")
    return {"state": "planned", "approval_required": True, "target_processes": 1,
            "window_bytes": size, "maximum_memory_bytes": MAX_WINDOW,
            "maximum_read_calls": (size + CHUNK - 1) // CHUNK,
            "database_prefix_bytes": 5120, "database_maximum_bytes_read": 10240,
            "maximum_candidates": MAX_CANDIDATES,
            "worker_seconds": WORK_SECONDS, "hard_seconds": HARD_SECONDS,
            "key_material_persisted": False}


class MemoryInfo(ctypes.Structure):
    _fields_ = [("base", ctypes.c_void_p), ("allocation", ctypes.c_void_p),
                ("allocation_protection", wintypes.DWORD), ("partition", wintypes.WORD),
                ("size", ctypes.c_size_t), ("state", wintypes.DWORD),
                ("protection", wintypes.DWORD), ("kind", wintypes.DWORD)]


def _guard(deadline):
    if time.monotonic() >= deadline:
        raise SourceError("deadline_reached")


def _capture(spec, *, fixture=False):
    plan(spec, fixture=fixture)
    deadline = time.monotonic() + WORK_SECONDS
    executable, module = Path(spec["executable"]), Path(spec["module"])
    _file(executable)
    _file(module)
    if fixture:
        if executable.resolve() != Path(sys._base_executable).resolve() or module != executable:
            raise SourceError("fixture_identity_mismatch")
    else:
        from qq_chat_analyzer.application.qq.qq_version import read_qq_resources
        resources = read_qq_resources(executable)
        if executable.name.lower() != "qq.exe" or resources is None or resources.version != (9, 9, 37, 54395) or resources.wrapper_path != module:
            raise SourceError("resource_identity_mismatch")
    candidates, data, page = [], bytearray(), bytearray()
    try:
        with verified_process(spec["pid"], executable) as (native, handle):
            if process_creation_ticks(native, handle) != spec["created_ticks"]:
                raise SourceError("process_generation_changed")
            if not loaded_module(native, handle, module)[1]:
                raise SourceError("expected_module_not_loaded")
            _guard(deadline)
            prefix, size = _read_unchanged(Path(spec["database"]), prefix_bytes=5120)
            if len(prefix) != 5120 or not prefix.startswith(WRAPPED) or _format(prefix, size) != "key_required":
                raise SourceError("unsupported_database")
            page = bytearray(prefix)
            salt = page[1024:1040].hex().encode("ascii")
            native.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MemoryInfo), ctypes.c_size_t]
            native.VirtualQueryEx.restype = ctypes.c_size_t
            native.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
            native.ReadProcessMemory.restype = wintypes.BOOL
            address, total = spec["window"]["address"], spec["window"]["size"]
            # Exactly this prelocalized window. No VirtualQueryEx address walk.
            for offset in range(0, total, CHUNK):
                _guard(deadline)
                count = min(CHUNK, total - offset)
                location = address + offset
                info = MemoryInfo()
                got = native.VirtualQueryEx(handle, location, ctypes.byref(info), ctypes.sizeof(info))
                if got != ctypes.sizeof(info) or info.state != 0x1000 or info.kind != 0x20000 or info.protection not in (0x02, 0x04) or not info.base <= location < location + count <= info.base + info.size:
                    raise SourceError("window_not_private_readable")
                buffer = (ctypes.c_ubyte * count)()
                read = ctypes.c_size_t()
                try:
                    if not native.ReadProcessMemory(handle, location, buffer, count, ctypes.byref(read)) or read.value != count:
                        raise SourceError("memory_read_refused")
                    data.extend(buffer)
                finally:
                    ctypes.memset(buffer, 0, count)
            # Bound candidates before authentication; do not retain raw samples.
            for match in LITERAL.finditer(data):
                if match.group(2).lower() == salt:
                    candidate = bytearray.fromhex(match.group(1).decode("ascii"))
                    if candidate not in candidates:
                        if len(candidates) == MAX_CANDIDATES:
                            candidate[:] = b"\0" * len(candidate)
                            raise SourceError("candidate_limit")
                        candidates.append(candidate)
                    else:
                        candidate[:] = b"\0" * len(candidate)
            _guard(deadline)
            # Validate the same observed encrypted page, never decrypt or query.
            current, _ = _read_unchanged(Path(spec["database"]), prefix_bytes=5120)
            if current != page:
                raise SourceError("database_changed")
        # Target handle is already closed before launching the MAC-only helper.
        node = shutil.which("node")
        if not node:
            raise SourceError("node_required")
        _guard(deadline)
        if candidates:
            request = json.dumps({"page": base64.b64encode(page).decode("ascii"),
                                  "keys": [key.hex() for key in candidates]})
            completed = subprocess.run([node, str(Path(__file__).with_name("qq_key_auth.mjs"))],
                input=request, text=True, encoding="utf-8", stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=max(0.01, deadline - time.monotonic()),
                creationflags=subprocess.CREATE_NO_WINDOW)
            if completed.returncode != 0:
                raise SourceError("authentication_worker_failed")
            authentication = json.loads(completed.stdout)
            if (set(authentication) != {"matched", "authenticated_candidates"}
                    or type(authentication["matched"]) is not bool
                    or type(authentication["authenticated_candidates"]) is not int
                    or not 0 <= authentication["authenticated_candidates"] <= len(candidates)
                    or authentication["matched"] != (authentication["authenticated_candidates"] > 0)):
                raise SourceError("authentication_worker_failed")
        else:
            authentication = {"matched": False, "authenticated_candidates": 0}
        _guard(deadline)
        return {"state": "matched" if authentication["matched"] else "not_matched",
                "candidates_tested": len(candidates), "authenticated_candidates": authentication["authenticated_candidates"],
                "memory_bytes_read": len(data), "process_handle_closed": True,
                "authentication_scope": "observed_main_page_one_only",
                "qq_54395": "not_verified", "key_material_persisted": False}
    finally:
        data[:] = b"\0" * len(data)
        page[:] = b"\0" * len(page)
        for candidate in candidates:
            candidate[:] = b"\0" * len(candidate)
        # Immutable Python/JSON/runtime copies cannot be guaranteed wiped.
        # The isolated worker exits; no key output, environment entry or file.


def run(spec, work_parent, *, approved=False, fixture=False, cancel_event=None):
    proposal = plan(spec, fixture=fixture)
    if not approved:
        return proposal
    if work_parent is None:
        raise SourceError("workspace_required")
    work_parent = _safe(Path(work_parent))
    if not work_parent.is_dir() or any(work_parent.is_relative_to(Path(spec[name]).absolute().parent)
                                     for name in ("database", "executable", "module")):
        raise SourceError("workspace_overlap")
    if len(json.dumps(spec)) > 8192:
        raise SourceError("request_limit")
    from qq_chat_analyzer.runtime.windows_job import launch_owned_process
    cancel_event = cancel_event if cancel_event is not None else threading.Event()
    if cancel_event.is_set():
        raise SourceError("cancelled")
    with tempfile.TemporaryDirectory(prefix="qq-key-", dir=work_parent) as directory:
        environment = os.environ.copy()
        for name in ("NODE_OPTIONS", "NODE_PATH", "ECHO_QQ_KEY_REQUEST", "ECHO_QQ_KEY_FIXTURE"):
            environment.pop(name, None)
        for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "MPLCONFIGDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
            target = Path(directory) / name
            target.mkdir()
            environment[name] = str(target)
        # Metadata only. Candidates are never put in arguments or environment.
        environment["ECHO_QQ_KEY_REQUEST"] = json.dumps(spec)
        environment["ECHO_QQ_KEY_FIXTURE"] = "1" if fixture else "0"
        process = launch_owned_process([sys.executable, str(Path(__file__).resolve()), "--worker"],
            env=environment, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + HARD_SECONDS
            while process.poll() is None:
                if cancel_event.wait(0.05):
                    raise SourceError("cancelled")
                _guard(deadline)
            output, _ = process.communicate(timeout=max(0.01, deadline - time.monotonic()))
            result = json.loads(output)
            if process.returncode != 0:
                # Never propagate arbitrary helper output, even as an error.
                known = {"process_generation_changed", "expected_module_not_loaded",
                         "window_not_private_readable", "memory_read_refused", "candidate_limit",
                         "database_changed", "deadline_reached", "process_identity_mismatch",
                         "process_read_access_unavailable", "resource_identity_mismatch"}
                raise SourceError(result.get("code") if result.get("code") in known else "worker_refused")
            if set(result) != {"state", "candidates_tested", "authenticated_candidates", "memory_bytes_read",
                               "process_handle_closed", "authentication_scope", "qq_54395", "key_material_persisted"}:
                raise SourceError("worker_protocol_failed")
            if (result["state"] not in ("matched", "not_matched")
                    or any(type(result[n]) is not int for n in ("candidates_tested", "authenticated_candidates", "memory_bytes_read"))
                    or not 0 <= result["authenticated_candidates"] <= result["candidates_tested"] <= MAX_CANDIDATES
                    or result["memory_bytes_read"] != spec["window"]["size"]
                    or (result["state"] == "matched") != (result["authenticated_candidates"] > 0)
                    or result["process_handle_closed"] is not True or result["key_material_persisted"] is not False
                    or result["authentication_scope"] != "observed_main_page_one_only" or result["qq_54395"] != "not_verified"):
                raise SourceError("worker_protocol_failed")
        finally:
            # Only our worker and descendants belong to this Job. QQ is never
            # adopted or assigned; Ctrl+C/timeout cannot terminate daily QQ.
            process.close_with_exit_evidence(timeout=3)
        result["owned_worker_tree_released"] = process.exit_verified
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-approved-window", action="store_true")
    parser.add_argument("--work-parent")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.worker:
            spec = json.loads(os.environ.pop("ECHO_QQ_KEY_REQUEST"))
            result = _capture(spec, fixture=os.environ.pop("ECHO_QQ_KEY_FIXTURE") == "1")
        else:
            raw = sys.stdin.read(8193)
            if len(raw) > 8192:
                raise SourceError("request_limit")
            spec = json.loads(raw)
            result = run(spec, args.work_parent, approved=args.execute_approved_window)
        print(json.dumps(result))
    except (Exception, KeyboardInterrupt) as error:
        code = error.code if isinstance(error, SourceError) else "cancelled" if isinstance(error, KeyboardInterrupt) else "experiment_failed"
        print(json.dumps({"state": "refused", "code": code, "key_material_persisted": False}))
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
