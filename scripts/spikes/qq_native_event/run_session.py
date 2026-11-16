"""Prepared real-QQ entrypoint. DO NOT RUN without separate per-run approval.

One explicit existing pre-login QQ main process; no launch/exit/login automation.
Default: encrypted DB prefix, public installation metadata, and own helpers.
Optional full-read consumes an explicitly prepared frozen encrypted snapshot.
The real QQ process is NEVER adopted by an Echo Job or terminated by this tool.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
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

MODULE_SHA256 = "fed532ad58d2404dcedf2858554e8fa52a5f4e65b271c008d2faca4011d7d4a2"
# End-to-end report work has its own finite allowance. Native observation,
# authenticated-key consumption and formal media budgets remain unchanged.
FULL_READ_TOTAL_SECONDS = 1800
CONFIG_FIELDS = {"baseVersion", "curVersion", "prevVersion", "onErrorVersions", "buildId",
    "unzipRetryCount", "readyVersion", "readyInstaller", "retryTimes", "notarized"}


def emit(status, args):
    """Write bounded evidence and keep its operator login prompt fail-closed."""
    if status.get("phase") == "armed":
        deadline = datetime.fromisoformat(status["login_before_utc"])
        remaining = max(0, min(status["remaining_login_ms"],
            int((deadline-datetime.now(timezone.utc)).total_seconds()*1000)))
        status = {**status, "remaining_login_ms": remaining, "manual_login_window_open": remaining > 0,
            "login_prompt": "login_now" if remaining > 0 else "window_elapsed_do_not_login"}
    elif status.get("phase") == "stopped":
        status = {**status, "manual_login_window_open": False, "login_prompt": "observation_stopped_do_not_login"}
    status = {**status, "recorded_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}
    line = json.dumps(status, ensure_ascii=True)
    if len(line) > 2048:
        raise SourceError("diagnostic_size_limit")
    receipt = getattr(args, "_receipt", None)
    if receipt is not None:
        _safe(receipt.parent)
        _file(receipt)
        with receipt.open("a", encoding="ascii") as stream:
            stream.write(line + "\n"); stream.flush(); os.fsync(stream.fileno())
    print(line, flush=True)


def attempt_directory(args):
    if not args.attempt_id or len(args.attempt_id) != 32 or any(c not in "0123456789abcdef" for c in args.attempt_id):
        raise SourceError("invalid_attempt_identity")
    return _safe(Path(args.full_snapshot)).parent / "attempts" / args.attempt_id


def resource_hashes(resources):
    """Freeze every non-config resource, retaining existing metadata checks."""
    result = {}
    for index, state in enumerate(resources.file_states):
        path, size, modified, inode = state
        if resources.config_text is not None and index == 0:
            continue
        before = _file(path)
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (size, modified, inode):
            raise SourceError("resource_changed")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = _file(path)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise SourceError("resource_changed")
        result[path] = digest
    return result


def compare_resources(before, after, hashes):
    """Allow config serialization/metadata rewrites only, never field changes."""
    if after is None:
        return {"resource_identity_same": False}
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    old = json.loads(before.config_text) if before.config_text is not None else None
    new = json.loads(after.config_text) if after.config_text is not None else None
    changed = {key for key in set(old or {}) | set(new or {})
        if key not in (old or {}) or key not in (new or {}) or canonical(old[key]) != canonical(new[key])}
    config_same = canonical(old) == canonical(new)
    old_states, new_states = before.file_states, after.file_states
    config_paths_same = True
    metadata_changed = False
    if old is not None and new is not None:
        config_paths_same = old_states[0][0] == new_states[0][0]
        metadata_changed = old_states[0] != new_states[0]
        _safe(old_states[0][0]); _file(new_states[0][0])
        old_states, new_states = old_states[1:], new_states[1:]
    same = ((before.package_path, before.package_text, before.version, before.wrapper_path) ==
        (after.package_path, after.package_text, after.version, after.wrapper_path) and
        config_same and config_paths_same and old_states == new_states)
    if same:
        same = resource_hashes(after) == hashes
    return {"resource_identity_same": same, "config_json_same": config_same,
        "config_metadata_changed": metadata_changed,
        "config_serialization_changed": before.config_text != after.config_text,
        "config_changed_fields": sorted(changed & CONFIG_FIELDS),
        "unrecognized_config_fields_changed": bool(changed - CONFIG_FIELDS)}


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
    # Resolve selected inputs in the caller's cwd BEFORE creating an attempt.
    # The worker reparses argv after moving into its owned temporary directory.
    selected_inputs = {}
    for field in ("executable", "database", "build_root", "metadata_selection"):
        value = getattr(args, field, None)
        if value:
            selected_inputs[field] = str(_safe(Path(value)))
            setattr(args, field, selected_inputs[field])
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
        metadata_selection = None
        if args.metadata_selection:
            from qq_metadata_read import selection
            metadata_selection = selection(args.metadata_selection)
        parent = (Path(args.metadata_selection).parent if metadata_selection else
                  Path(args.full_snapshot).parent if args.full_snapshot else Path(args.build_root).resolve().parent)
        if metadata_selection:
            # A second process cannot consume this one-shot authorization.
            (parent / "capture-started.json").open("x", encoding="ascii").close()
            args._receipt = parent / "verification.jsonl"
            args._receipt.touch(exist_ok=False)
            emit({"phase": "attempt_started", "metadata_only": True, "source_count": 2,
                  "total_budget_seconds": FULL_READ_TOTAL_SECONDS}, args)
        if args.full_snapshot:
            from qq_full_read import validate_prepared, verify_dictionary, assert_memory_available, validate_media_roots
            validate_prepared(args.full_snapshot, args.full_snapshot_sha256)
            verify_dictionary(args.dictionary)
            assert_memory_available()
            validate_media_roots(args.sticker_media_root, args.self_uin)
            # Reuse the immutable encrypted copy with a NEW explicitly approved
            # attempt; preserve the old attempt marker and every prior receipt.
            attempts = parent / "attempts"
            attempts.mkdir(exist_ok=True); _safe(attempts)
            directory = attempt_directory(args)
            directory.mkdir(exist_ok=False)
            (directory / "attempt.json").write_text(json.dumps({"kind": "echo-qq-full-read-attempt", "version": 2}), encoding="ascii")
            args._receipt = directory / "verification.jsonl"
            args._receipt.touch(exist_ok=False)
            emit({"phase": "attempt_started", "snapshot_verified": True,
                "total_budget_seconds": FULL_READ_TOTAL_SECONDS}, args)
        with tempfile.TemporaryDirectory(prefix="qq-owner-", dir=parent) as temporary:
            if args.full_snapshot:
                (Path(temporary) / "owner.json").write_text(json.dumps({"kind": "echo-qq-full-read-temporary", "version": 1}), encoding="ascii")
            env = os.environ.copy()
            for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "MPLCONFIGDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
                directory = Path(temporary) / key
                directory.mkdir()
                env[key] = str(directory)
            worker_args = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--owned-worker", "--cancel-event", name]
            for field, value in selected_inputs.items():
                worker_args.extend(["--" + field.replace("_", "-"), value])
            if args.full_snapshot:
                worker_args.extend(["--attempt-id", args.attempt_id])
            process = launch_owned_process(worker_args, cwd=temporary, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW,
                external_readers=True)
            def forward():
                try:
                    # Full-read per-disposition accounting adds bounded rows
                    # after the existing authentication/decode progress rows.
                    for _ in range(48):
                        line = process.stdout.readline(2049)
                        if not line or len(line) > 2048:
                            break
                        print(json.dumps(json.loads(line)), flush=True)
                except (OSError, ValueError):
                    pass
            reader = threading.Thread(target=forward, daemon=True)
            process.set_external_readers((reader,))
            reader.start()
            try:
                end = time.monotonic()+(FULL_READ_TOTAL_SECONDS if args.full_snapshot or metadata_selection else 140)
                total_deadline = end
                while process.poll() is None:
                    try:
                        time.sleep(0.05)
                    except KeyboardInterrupt:
                        api.SetEvent(cancel)
                        end = min(end, time.monotonic()+7)
                    if time.monotonic() >= end:
                        raise SourceError("full_read_total_deadline" if args.full_snapshot
                            and time.monotonic() >= total_deadline else "owned_worker_stop_unconfirmed")
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
    metadata_selection = None
    if args.metadata_selection:
        from qq_metadata_read import selection
        metadata_selection = selection(args.metadata_selection)
        metadata_selection["selection_path"] = args.metadata_selection
        args._receipt = Path(args.metadata_selection).parent / "verification.jsonl"
        _file(args._receipt)
    if args.full_snapshot:
        args._receipt = attempt_directory(args) / "verification.jsonl"
        _file(args._receipt)
        spikes = Path(__file__).resolve().parents[1]
        emit({"phase": "diagnostic_contract", "version": 2, "source_sha256": {
            role: hashlib.sha256(path.read_bytes()).hexdigest() for role, path in {
                "codec": spikes / "qq_independent_codec.mjs",
                "reader": spikes / "qq_full_read.mjs",
                "bridge": Path(__file__).with_name("approved_session.mjs"),
                "finalizer": spikes.parent / "qq_direct_db_snapshot/main_wal.mjs",
                "report_reader": spikes / "qq_full_read.py",
                "key_scope": spikes / "qq_key_source.mjs",
                "transport": Path(__file__).with_name("connect.mjs"),
                "worker": Path(__file__).resolve(),
            }.items()}}, args)
    _file(image)
    resources = read_qq_resources(image)
    if resources is None or resources.version != (9, 9, 37, 54395) or resources.wrapper_path is None:
        raise SourceError("exact_active_version_required")
    _file(resources.wrapper_path)
    hashes = resource_hashes(resources)
    if hashes.get(resources.wrapper_path) != MODULE_SHA256:
        raise SourceError("module_identity_refused")
    image_hash = hashes[image]
    snapshot = None
    if args.full_snapshot:
        from qq_full_read import validate_prepared
        snapshot = validate_prepared(args.full_snapshot, args.full_snapshot_sha256)
    if metadata_selection and database != Path(metadata_selection["anchor"]["path"]):
        raise SourceError("metadata_anchor_selection_mismatch")
    prefix, size = _read_unchanged(Path(args.full_snapshot) if snapshot else database, prefix_bytes=5120)
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
        with tempfile.TemporaryDirectory(prefix="qq-session-", dir=Path(os.environ['TEMP']) if snapshot or metadata_selection else build.parent) as temporary:
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
            plain = Path(temporary) / "snapshot.db"
            if snapshot:
                request["snapshot"] = {"path": str(Path(args.full_snapshot).resolve()), "sha256": snapshot["sha256"],
                    "size": snapshot["size"], "output": str(plain)}
            metadata_plaintext = [Path(temporary) / (role + ".db") for role in ("group_info", "profile_info")]
            if metadata_selection:
                request["metadata"] = [{**item, "output": str(output)} for item, output in
                    zip(metadata_selection["sources"], metadata_plaintext, strict=True)]
            metadata = json.dumps(request, ensure_ascii=True).encode("ascii")
            if len(metadata) > 131072:
                raise SourceError("selection_limit")
            process = subprocess.Popen([node, "--max-old-space-size=" + ("512" if snapshot or metadata_selection else "96"), str(Path(__file__).with_name("approved_session.mjs"))],
                cwd=temporary, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            messages = queue.Queue(maxsize=8)
            def read_status():
                try:
                    for _ in range(40 if metadata_selection else 24):
                        line = process.stdout.readline(2049)
                        if not line:
                            break
                        if len(line) > 2048:
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
                end, stopping = time.monotonic()+(265 if snapshot or metadata_selection else 135), False
                while True:
                    try:
                        line = messages.get(timeout=0.1)
                        if line is None:
                            break
                        status = json.loads(line)
                        if status.get("phase") == "armed":
                            emit(status, args)
                        elif status.get("phase") == "stopped":
                            emit({**status, "component_unloaded": False}, args)
                        elif status.get("phase") in ("authentication", "authenticated_header", "decryption",
                                "snapshot_progress", "snapshot_finalization", "snapshot_failure", "metadata_snapshot_result"):
                            emit(status, args)
                        elif status.get("phase") == "result":
                            result = status
                            emit({**result, "phase": "capture_result", "final_identity_verified": False}, args)
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
            identity = compare_resources(resources, read_qq_resources(image), hashes)
            identity["process_generation_same"] = process_creation_ticks(native, handle) == args.created
            identity["expected_module_loaded"] = loaded_module(native, handle, resources.wrapper_path)[1]
            emit({"phase": "identity_check", **identity}, args)
            if not all(identity.get(key) is True for key in ("resource_identity_same", "process_generation_same", "expected_module_loaded")):
                raise SourceError("input_or_generation_changed")
            if not snapshot:
                current, _ = _read_unchanged(database, prefix_bytes=5120)
                if current != prefix:
                    raise SourceError("input_or_generation_changed")
            if metadata_selection:
                receipts = result.get("metadata_snapshots", [])
                if (not result.get("authenticated") or not result.get("observation_stopped") or
                    len(receipts) != 2 or any(item.get("role") != role or
                    not item.get("complete_image") or not item.get("all_pages_authenticated")
                    for item, role in zip(receipts, ("group_info", "profile_info"), strict=True))):
                    raise SourceError("metadata_snapshots_not_authenticated")
                from qq_metadata_read import review
                review_cancel = api.OpenEventW(0x00100000, False, args.cancel_event)
                if not review_cancel:
                    raise SourceError("cancel_event_unavailable")
                try:
                    review(metadata_selection, metadata_plaintext, lambda status: emit(status, args),
                           lambda: api.WaitForSingleObject(review_cancel, 0) == 0)
                finally:
                    api.CloseHandle(review_cancel)
            if snapshot:
                # The encrypted snapshot predates login; subsequent source writes
                # cannot invalidate that frozen, fully fingerprinted image.
                if not result.get("authenticated") or not result.get("observation_stopped") or not result.get("full_snapshot", {}).get("complete_image"):
                    raise SourceError("full_snapshot_not_authenticated")
                from qq_full_read import finish_report
                report = _safe(Path(args.report_directory).parent) / Path(args.report_directory).name
                # A fresh attempt may own its report beside its marker/receipt.
                # Preserve earlier failed or completed report assets in place.
                allowed_parents = (Path(args.full_snapshot).resolve().parent, attempt_directory(args))
                if report.parent not in allowed_parents or report.name != "report" or report.exists():
                    raise SourceError("owned_new_report_directory_required")
                report.mkdir()
                try:
                    emit(finish_report(plain, temporary, report, args.group, args.self_uin, args.dictionary,
                        on_status=lambda status: emit(status, args),
                        recover_sticker_media=args.recover_sticker_media,
                        sticker_media_roots=tuple(args.sticker_media_root)), args)
                except Exception:
                    # Partial local reports are not a successful delivery.
                    # Owned TemporaryDirectory still removes ALL DB/payload data.
                    emit({"phase": "full_read_result", "report_generated": False, "partial_report_retained": True}, args)
                    raise
    if snapshot or metadata_selection:
        emit({"phase": "temporary_data_removed", "plaintext_retained": False}, args)
        return
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-single-session", action="store_true")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--created", type=int, required=True)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--build-root", required=True)
    parser.add_argument("--metadata-selection", help="Explicit one-shot metadata selection, no message read/analysis")
    parser.add_argument("--full-snapshot")
    parser.add_argument("--full-snapshot-sha256")
    parser.add_argument("--group")
    parser.add_argument("--self-uin")
    parser.add_argument("--report-directory")
    parser.add_argument("--dictionary")
    parser.add_argument("--recover-sticker-media", action="store_true",
        help="Reuse formal local PIC and local/CDN MFACE recovery; no QQ media RPCs")
    parser.add_argument("--sticker-media-root", action="append", default=[],
        help="Explicitly authorized media scope; repeatable, never inferred from message paths")
    parser.add_argument("--attempt-id", help=argparse.SUPPRESS)
    parser.add_argument("--owned-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cancel-event", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args._receipt = None
    try:
        full = [args.full_snapshot, args.full_snapshot_sha256, args.group, args.self_uin, args.report_directory, args.dictionary]
        if args.metadata_selection and (any(full) or args.recover_sticker_media or args.sticker_media_root):
            raise SourceError("metadata_full_read_modes_exclusive")
        if any(full) and not all(full):
            raise SourceError("complete_full_read_selection_required")
        if (args.recover_sticker_media or args.sticker_media_root) and not all(full):
            raise SourceError("complete_full_read_selection_required")
        if args.sticker_media_root and not args.recover_sticker_media:
            raise SourceError("explicit_media_recovery_required")
        if args.full_snapshot and args.attempt_id is None and not args.owned_worker:
            args.attempt_id = uuid.uuid4().hex
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
    except (Exception, KeyboardInterrupt) as error:
        # No exception strings, tracebacks, paths, PID or metadata to public logs.
        emit({"phase": "result", "state": "refused", "authenticated": False,
            "code": error.code if isinstance(error, SourceError) else "experiment_failed",
            "recovery": "normal_qq_exit_if_component_loaded"}, args)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
