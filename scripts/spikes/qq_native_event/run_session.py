"""Prepared real-QQ entrypoint. DO NOT RUN without separate per-run approval.

One explicit existing pre-login QQ main process; no launch/exit/login automation.
Only encrypted DB prefix, public installation/process metadata, and own helpers.
The real QQ process is NEVER adopted by an Echo Job or terminated by this tool.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qq_windows_source import SourceError, _file, _safe, _format, _read_unchanged
from qq_windows_process_probe import verified_process, process_creation_ticks, loaded_module


def events():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateEventW.restype = wintypes.HANDLE
    api.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    api.OpenEventW.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.SetEvent.argtypes = [wintypes.HANDLE]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    return api


def owned_worker(args):
    """Reuse the existing DEVNULL-stdin Job contract; only its worker opens PIPE."""
    from qq_chat_analyzer.runtime.windows_job import launch_owned_process
    api = events()
    prefix = "Local\\EchoQQExperimentStop-"
    name = args.cancel_event or prefix + uuid.uuid4().hex
    suffix = name.removeprefix(prefix)
    if not name.startswith(prefix) or len(suffix) != 32 or any(c not in "0123456789abcdef" for c in suffix):
        raise SourceError("invalid_cancel_event")
    ctypes.set_last_error(0)
    cancel = api.CreateEventW(None, True, False, name)
    if not cancel:
        raise SourceError("cancel_event_unavailable")
    try:
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS: never reuse another session's event.
            raise SourceError("cancel_event_already_owned")
        with tempfile.TemporaryDirectory(prefix="qq-owner-", dir=Path(args.build_root).resolve().parent) as temporary:
            env = os.environ.copy()
            for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "MPLCONFIGDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
                directory = Path(temporary) / key
                directory.mkdir()
                env[key] = str(directory)
            process = launch_owned_process([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:],
                "--owned-worker", "--cancel-event", name], cwd=temporary, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW,
                external_readers=True)
            def forward():
                try:
                    for _ in range(4):
                        line = process.stdout.readline(1025)
                        if not line or len(line) > 1024:
                            break
                        print(json.dumps(json.loads(line)), flush=True)
                except (OSError, ValueError):
                    pass
            reader = threading.Thread(target=forward, daemon=True)
            process.set_external_readers((reader,))
            reader.start()
            try:
                end = time.monotonic()+140
                while process.poll() is None:
                    try:
                        time.sleep(0.05)
                    except KeyboardInterrupt:
                        api.SetEvent(cancel)
                        end = min(end, time.monotonic()+7)
                    if time.monotonic() >= end:
                        raise SourceError("owned_worker_stop_unconfirmed")
                if process.returncode:
                    raise SourceError("owned_worker_refused")
            finally:
                # This tree contains our Python, Node and loader, NEVER QQ.
                process.terminate_tree()
                end = time.monotonic()+3
                while process.active_process_count() != 0 and time.monotonic() < end:
                    time.sleep(0.01)
                if process.active_process_count() != 0:
                    raise SourceError("owned_tree_not_released")
                reader.join(timeout=1)
                process.close_after_readers((reader,), deadline=time.monotonic()+2)
    finally:
        api.CloseHandle(cancel)


def run(args):
    if not args.approved_single_session:
        raise SourceError("separate_approval_required")
    from qq_chat_analyzer.application.qq.qq_version import read_qq_resources
    # This worker and every subprocess inherit the outer research Job.
    image, database, build = (_safe(Path(value)) for value in (args.executable, args.database, args.build_root))
    _file(image)
    resources = read_qq_resources(image)
    if resources is None or resources.version != (9, 9, 37, 54395) or resources.wrapper_path is None:
        raise SourceError("exact_active_version_required")
    _file(resources.wrapper_path)
    with resources.wrapper_path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != "fed532ad58d2404dcedf2858554e8fa52a5f4e65b271c008d2faca4011d7d4a2":
            raise SourceError("module_identity_refused")
    with image.open("rb") as stream:
        image_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    prefix, size = _read_unchanged(database, prefix_bytes=5120)
    if len(prefix) != 5120 or _format(prefix, size) != "key_required":
        raise SourceError("encrypted_prefix_required")
    node = shutil.which("node")
    if not node:
        raise SourceError("node_required")
    page = bytearray(prefix)
    result = None
    with verified_process(args.pid, image) as (native, handle):
        if process_creation_ticks(native, handle) != args.created or not loaded_module(native, handle, resources.wrapper_path)[1]:
            raise SourceError("selected_process_changed")
        # The Job contains Node and our loader only. QQ is an unrelated, already
        # running process; CreateRemoteThread does not make it a child process.
        with tempfile.TemporaryDirectory(prefix="qq-session-", dir=build.parent) as temporary:
            env = os.environ.copy()
            for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "MPLCONFIGDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
                directory = Path(temporary) / name
                directory.mkdir()
                env[name] = str(directory)
            env.pop("NODE_OPTIONS", None)
            env.pop("NODE_PATH", None)
            request = {"directory": str(build), "timeoutMs": 120000,
                "target": {"mode": "approved-qq", "version": "9.9.37-54395", "pid": args.pid,
                    "created": str(args.created), "image": str(image), "sha256": image_hash}}
            metadata = json.dumps(request, ensure_ascii=True).encode("ascii")
            if len(metadata) > 131072:
                raise SourceError("selection_limit")
            process = subprocess.Popen([node, "--max-old-space-size=96", str(Path(__file__).with_name("approved_session.mjs"))],
                cwd=temporary, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            messages = queue.Queue(maxsize=8)
            def read_status():
                try:
                    for _ in range(4):
                        line = process.stdout.readline(1025)
                        if not line:
                            break
                        if len(line) > 1024:
                            messages.put(None)
                            return
                        messages.put(line)
                except (OSError, ValueError):
                    pass
                finally:
                    messages.put(None)
            reader = threading.Thread(target=read_status, daemon=True)
            reader.start()
            api = events()
            cancel = api.OpenEventW(0x00100002, False, args.cancel_event)
            try:
                if not cancel:
                    raise SourceError("cancel_event_unavailable")
                process.stdin.write(struct.pack("<I", len(metadata)) + metadata + page)
                process.stdin.flush()
                end, stopping = time.monotonic()+135, False
                while True:
                    try:
                        line = messages.get(timeout=0.1)
                        if line is None:
                            break
                        status = json.loads(line)
                        if status.get("phase") == "armed":
                            print('{"phase":"armed","manual_login_window_open":true}', flush=True)
                        elif status.get("phase") == "stopped":
                            print('{"phase":"stopped","component_unloaded":false}', flush=True)
                        elif status.get("phase") == "result":
                            result = status
                        else:
                            raise SourceError("status_refused")
                    except queue.Empty:
                        pass
                    except KeyboardInterrupt:
                        api.SetEvent(cancel)
                    if not stopping and api.WaitForSingleObject(cancel, 0) == 0:
                        stopping = True
                        process.stdin.write(b"\x01")
                        process.stdin.flush()
                        end = min(end, time.monotonic()+5)
                    if time.monotonic() >= end:
                        raise SourceError("helper_stop_unconfirmed")
                if process.wait(timeout=3) or result is None:
                    raise SourceError("session_stop_unconfirmed")
            finally:
                page[:] = b"\x00" * len(page)
                if cancel:
                    api.CloseHandle(cancel)
                if process.poll() is None:
                    process.kill()  # Own Node only; outer Job owns its helpers.
                process.wait(timeout=3)
                process.stdin.close()
                reader.join(timeout=1)
                process.stdout.close()
            current, _ = _read_unchanged(database, prefix_bytes=5120)
            if current != prefix or read_qq_resources(image) != resources or process_creation_ticks(native, handle) != args.created:
                raise SourceError("input_or_generation_changed")
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-single-session", action="store_true")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--created", type=int, required=True)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--build-root", required=True)
    parser.add_argument("--owned-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cancel-event", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        import qq_chat_analyzer
        if Path(qq_chat_analyzer.__file__).resolve() != Path(__file__).resolve().parents[3] / "src/qq_chat_analyzer/__init__.py":
            raise SourceError("current_checkout_required")
        if not args.approved_single_session:
            raise SourceError("separate_approval_required")
        if args.owned_worker:
            if not args.cancel_event or not args.cancel_event.startswith("Local\\EchoQQExperimentStop-"):
                raise SourceError("owned_cancel_required")
            run(args)
        else:
            owned_worker(args)
    except (Exception, KeyboardInterrupt):
        # No exception strings, tracebacks, paths, PID or metadata to public logs.
        print('{"phase":"result","state":"refused","authenticated":false,"recovery":"normal_qq_exit_if_component_loaded"}', flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
