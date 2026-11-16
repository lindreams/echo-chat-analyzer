"""Research helpers for one authorized conversation, never an automatic QQ entry.

Prepare only while QQ is exited. A write-denying source handle plus absence of
ALL sidecars is required; an existing WAL is refused, never ignored/deleted.
The approved session runner owns temporary plaintext and its outer Job cleanup.
"""
from __future__ import annotations

from contextlib import closing
from collections import Counter, defaultdict
import ctypes
from ctypes import wintypes
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import uuid

from qq_windows_source import SourceError, _file, _safe, _identity, _no_sidecars, _format

MAX_BYTES = 1024 ** 3
OWNER = {"kind": "echo-qq-full-read", "version": 1}
DICTIONARY_SHA256 = "7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8"


def _powershell(program, *, env=None):
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(executable), "-NoProfile", "-NonInteractive", "-Command", program],
        env=env, capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise SourceError("preparation_os_check_failed")
    return result.stdout.strip()


def assert_qq_exited():
    if _powershell("@(Get-Process -Name QQ -ErrorAction SilentlyContinue).Count") != b"0":
        raise SourceError("normal_qq_exit_required")


def _protect_new_root(root):
    environment = os.environ.copy()
    environment["ECHO_OWNED_FULL_ROOT"] = str(root)
    _powershell("""$ErrorActionPreference='Stop'
$p=$env:ECHO_OWNED_FULL_ROOT
$u=[Security.Principal.WindowsIdentity]::GetCurrent().User
if((Get-Acl -LiteralPath $p).Owner -ne $u.Translate([Security.Principal.NTAccount]).Value){exit 1}
$a=New-Object Security.AccessControl.DirectorySecurity
$a.SetAccessRuleProtection($true,$false)
foreach($s in @($u,(New-Object Security.Principal.SecurityIdentifier('S-1-5-18')))) {
 $r=New-Object Security.AccessControl.FileSystemAccessRule($s,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
 $a.AddAccessRule($r)
}
# The creator must already own this new directory; changing ownership would
# require WRITE_OWNER even when the current owner can safely protect its DACL.
# Persist only the DACL section changed above. Set-Acl also attempts
# audit-security updates on an already protected directory, requiring an
# unrelated SeSecurityPrivilege and refusing an otherwise identical ACL.
[IO.Directory]::SetAccessControl($p,$a)
$v=Get-Acl -LiteralPath $p
if(-not $v.AreAccessRulesProtected -or $v.Owner -ne $u.Translate([Security.Principal.NTAccount]).Value){exit 1}
foreach($r in $v.Access){$s=$r.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
 if($s -ne $u.Value -and $s -ne 'S-1-5-18'){exit 1}}
""", env=environment)


def _read_locked(path):
    """Windows share-read ONLY: existing/future writers make this fail closed."""
    import msvcrt
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x08000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise SourceError("source_read_lock_unavailable")
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    return os.fdopen(descriptor, "rb", buffering=0)


def prepare(database, work_parent):
    """Return private paths to caller only; never print/persist source location."""
    database, parent = _safe(Path(database)), _safe(Path(work_parent))
    if database.is_relative_to(parent) or parent.is_relative_to(database.parent):
        raise SourceError("workspace_overlap")
    assert_qq_exited()
    _no_sidecars(database)
    before = _file(database)
    if not 5120 <= before.st_size <= MAX_BYTES:
        raise SourceError("full_snapshot_size_limit")
    root = parent / ("qq-authorized-full-" + uuid.uuid4().hex)
    root.mkdir()
    _protect_new_root(root)  # No sensitive bytes exist before ACL verification.
    (root / "owner.json").write_text(json.dumps(OWNER), encoding="ascii")
    output = root / "encrypted.db"
    digest, count = hashlib.sha256(), 0
    try:
        with _read_locked(database) as source, output.open("xb") as destination:
            opened = os.fstat(source.fileno())
            if _identity(opened)[:4] != _identity(before)[:4]:
                raise SourceError("source_changed")
            header = source.read(5120)
            if len(header) != 5120 or _format(header, before.st_size) != "key_required":
                raise SourceError("encrypted_source_required")
            destination.write(header); digest.update(header); count += len(header)
            deadline = time.monotonic() + 60
            while block := source.read(1024 * 1024):
                if time.monotonic() >= deadline or count + len(block) > MAX_BYTES:
                    raise SourceError("snapshot_copy_limit")
                destination.write(block); digest.update(block); count += len(block)
            if count != before.st_size or _identity(os.fstat(source.fileno())) != _identity(opened):
                raise SourceError("source_changed")
            _no_sidecars(database)
            if _identity(_file(database)) != _identity(before):
                raise SourceError("source_changed")
        assert_qq_exited()
        _no_sidecars(database)
        # Independently hash the completed copy; never rely on path existence.
        with output.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest.hexdigest():
                raise SourceError("snapshot_copy_mismatch")
        manifest = {"size": count, "sha256": digest.hexdigest(), "wal_state": "absent_under_read_lock"}
        (root / "snapshot.json").write_text(json.dumps(manifest), encoding="ascii")
        return {"root": str(root), "snapshot": str(output), **manifest}
    except BaseException:
        if output.exists():
            _file(output); output.unlink()
        raise


def validate_prepared(path, digest):
    path = _safe(Path(path))
    _file(path)
    for marker in ("owner.json", "snapshot.json"):
        _file(path.parent / marker)
    if path.name != "encrypted.db" or json.loads((path.parent / "owner.json").read_text()) != OWNER:
        raise SourceError("owned_snapshot_required")
    manifest = json.loads((path.parent / "snapshot.json").read_text())
    if manifest["sha256"] != digest or manifest["size"] != path.stat().st_size or manifest["wal_state"] != "absent_under_read_lock":
        raise SourceError("prepared_snapshot_changed")
    _no_sidecars(path)
    return manifest


def verify_dictionary(path):
    """Use the existing version's real dictionary, never fictional vocabulary."""
    path = _safe(Path(path))
    _file(path)
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != DICTIONARY_SHA256:
            raise SourceError("report_dictionary_identity_refused")
    return path


def assert_memory_available():
    # The existing decoder now accepts bounded reads and a page sink. Reserve
    # room for Node plus the later provider/analysis run, never allocate a DB buffer.
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [(name, ctypes.c_ulonglong)
            for name in ("total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]
    status = MemoryStatus(); status.length = ctypes.sizeof(status)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MemoryStatus)]
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(status)) or status.available < 1024 ** 3:
        raise SourceError("full_read_memory_budget_unavailable")


def authorized_group_partition(connection, group, on_status):
    """Bind an external group to one partition using metadata, never bodies.

    A zero 40030 is not an identity. It needs the same row's 40021 witness;
    neither partition membership nor the Provider's MAX object proves this.
    """
    keys = connection.execute('''SELECT DISTINCT CAST("40027" AS TEXT)
        FROM group_msg_table WHERE CAST("40030" AS TEXT)=? LIMIT 2''', (group,)).fetchall()
    if len(keys) != 1 or not keys[0][0] or keys[0][0].strip() in ("", "0"):
        on_status({"phase": "group_partition_mapping", "state": "refused", "candidate_partitions": len(keys)})
        raise SourceError("authorized_session_missing_or_ambiguous")
    key = keys[0][0]
    columns = {row[1] for row in connection.execute("PRAGMA table_info(group_msg_table)")}
    has_object = "40021" in columns
    # SQL NULL must count as unproven, not silently disappear from != tests.
    number = '''typeof("40030") IN ('integer','text') AND CAST("40030" AS TEXT)=:group'''
    zero = '''typeof("40030") IN ('integer','text') AND CAST("40030" AS TEXT)='0' '''
    object_matches = '''typeof("40021") IN ('integer','text') AND CAST("40021" AS TEXT)=:group''' if has_object else "0"
    count, first, last, numbered, witnessed_zero, object_conflicts, key_types = connection.execute(f'''
        SELECT COUNT(*), MIN("40050"), MAX("40050"),
          SUM(CASE WHEN {number} THEN 1 ELSE 0 END),
          SUM(CASE WHEN ({zero}) AND ({object_matches}) THEN 1 ELSE 0 END),
          SUM(CASE WHEN ({object_matches}) THEN 0 ELSE 1 END),
          COUNT(DISTINCT typeof("40027"))
        FROM group_msg_table WHERE CAST("40027" AS TEXT)=:key''', {"group": group, "key": key}).fetchone()
    # Legacy fixtures without 40021 retain the strict all-40030 rule. When
    # present, require a uniform object binding even on nonzero anchor rows.
    valid = bool(count and numbered + witnessed_zero == count and key_types == 1
                 and (not has_object or object_conflicts == 0))
    on_status({"phase": "group_partition_mapping", "state": "verified" if valid else "refused",
        "candidate_partitions": 1, "partition_rows": count, "group_number_rows": numbered or 0,
        "zero_number_object_confirmed_rows": witnessed_zero or 0,
        "unproven_number_rows": count - (numbered or 0) - (witnessed_zero or 0),
        "object_column_present": has_object, "object_conflict_rows": object_conflicts if has_object else 0,
        "partition_storage_types": key_types})
    if not valid:
        raise SourceError("authorized_partition_mismatch")
    return key, count, first, last


def _sender_state(value):
    from qq_chat_analyzer.qq_db_identity import canonical_qq_uin
    if value is None: return "null_or_missing"
    if isinstance(value, str) and not value.strip(): return "blank"
    if isinstance(value, (int, str)) and not isinstance(value, bool) and str(value).strip() == "0": return "zero"
    return "identified" if canonical_qq_uin(value) is not None else "invalid"


def _count_native_types(counter, fields):
    for column in ("40011", "40012"):
        value = fields.get(column)
        code = str(value) if type(value) is int and 0 <= value <= 255 else "unavailable_or_other"
        label = column + ":" + code
        if label not in counter and len(counter) >= 16: label = "other_type_buckets"
        counter[label] += 1


def _time_bucket(stamp, low, high):
    if stamp is None: return "invalid_time"
    if low is None or high is None or high < low: return "unknown_bounds"
    return "q" + str(min(3, max(0, (stamp-low)*4//max(1, high-low+1)))+1)


def audit_provider_skips(connection, key, first, last, on_status):
    """Describe unusable body rows without selecting any body bytes."""
    from qq_chat_analyzer.analysis.timestamps import to_epoch_seconds
    present = {row[1] for row in connection.execute("PRAGMA table_info(group_msg_table)")}
    columns = ",".join('"' + column + '"' if column in present else "NULL"
        for column in ("40011", "40012"))
    states, types, periods, blob_types = Counter(), Counter(), Counter(), Counter()
    low, high = to_epoch_seconds(first), to_epoch_seconds(last)
    rows, at_first, at_last, missing_body = 0, 0, 0, 0
    for sender, stamp, body_type, native_type, subtype in connection.execute(
        'SELECT "40033","40050",typeof("40800"),' + columns +
        ' FROM group_msg_table WHERE CAST("40027" AS TEXT)=?'
        ' AND NOT (typeof("40800")=\'blob\' AND length("40800")>0)', (key,)):
        rows += 1
        states[_sender_state(sender)] += 1
        _count_native_types(types, {"40011": native_type, "40012": subtype})
        normalized = to_epoch_seconds(stamp)
        periods[_time_bucket(normalized, low, high)] += 1
        blob_types[body_type] += 1
        # Real 54395 evidence: these rows have no body to interpret, rather
        # than supported content lost in conversion. Do not infer "system",
        # fabricate a message, or allow other invalid-body shapes silently.
        if (body_type == "null" and _sender_state(sender) == "zero"
                and type(native_type) is int and native_type == 1
                and type(subtype) is int and subtype in (0, 1)):
            missing_body += 1
        at_first += normalized is not None and normalized == low
        at_last += normalized is not None and normalized == high
    on_status({"phase": "provider_skipped_rows", "reason": "invalid_40800", "rows": rows,
        "sender_states": dict(states), "native_types": dict(types), "blob_storage_types": dict(blob_types),
        "relative_time_quartiles": dict(periods), "at_raw_first_rows": at_first, "at_raw_last_rows": at_last,
        "verified_missing_body_rows": missing_body, "unclassified_rows": rows-missing_body})
    return {"missing_body_rows": missing_body, "unclassified_rows": rows-missing_body}


def audit_adapter(payload, source_rows, source_directions, first, last, self_uin, on_status,
        *, provider_exclusions=None, parse_messages=None):
    """Account for actual parser decisions; never infer system rows from UIN=0.

    Observers see only this already-authorized payload, in memory. Receipts
    contain fixed categories/counts, bounded native type codes and relative
    time quartiles, never values of identities, timestamps or message content.
    """
    from qq_chat_analyzer.analysis.timestamps import to_epoch_seconds
    from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages_with_media_facts
    from qq_chat_analyzer.qq_db_identity import canonical_qq_uin
    from qq_chat_analyzer.legacy_projection import project_legacy_message
    low, high = to_epoch_seconds(first), to_epoch_seconds(last)
    counts = Counter()
    legacy_sender_drops = Counter()
    senders = defaultdict(Counter)
    types = defaultdict(Counter)
    segment_types = defaultdict(Counter)
    protobuf_errors = defaultdict(Counter)
    no_segments = Counter()
    times = defaultdict(Counter)
    directions = defaultdict(lambda: [0, 0, 0])
    bounds = {}
    mismatches = Counter()
    owner = canonical_qq_uin(self_uin)
    excluded = provider_exclusions or {"missing_body_rows": 0, "unclassified_rows": 0}
    missing_body = excluded["missing_body_rows"]

    def observe(record, message, reason, diagnostics):
        fields = record.get("fields", {}) if isinstance(record, dict) else {}
        if not isinstance(fields, dict): fields = {}
        sender = fields.get("40033")
        identity = canonical_qq_uin(sender)
        direction = 2 if identity is None else (0 if identity == owner else 1)
        state = _sender_state(sender)
        bucket = "accepted_missing_sender" if reason == "accepted" and state in ("null_or_missing", "blank") else reason
        counts[bucket] += 1
        if reason == "accepted" and sender in (None, ""):
            legacy_sender_drops[bucket] += 1
        senders[bucket][state] += 1
        directions[bucket][direction] += 1
        _count_native_types(types[bucket], fields)
        for code in diagnostics.get("segment_types", ()):
            if code not in segment_types[bucket] and len(segment_types[bucket]) >= 16:
                code = "other_type_buckets"
            segment_types[bucket][code] += 1
        protobuf_errors[bucket].update(diagnostics.get("protobuf_errors", ()))
        if diagnostics.get("segment_count") == 0:
            no_segments[bucket] += 1
        if message is not None and diagnostics.get("protobuf_errors"):
            mismatches["malformed_protobuf"] += 1
        stamp = to_epoch_seconds(fields.get("40050"))
        times[bucket][_time_bucket(stamp, low, high)] += 1
        if stamp is not None:
            a, b = bounds.get(bucket, (stamp, stamp))
            bounds[bucket] = min(a, stamp), max(b, stamp)
        if message is not None:
            expected_self = (True, False, None)[direction]
            legacy = project_legacy_message(message)
            if message.is_self is not expected_self or legacy.is_self is not expected_self:
                mismatches["direction"] += 1
            if message.sender.identity_id != identity or legacy.sender_id != identity:
                mismatches["identity"] += 1
            if identity is None and (message.sender.display_name or legacy.sender):
                mismatches["unknown_label"] += 1
            if message.timestamp != fields.get("40050") or legacy.timestamp != message.timestamp:
                mismatches["timestamp"] += 1

    parse = parse_messages or parse_qq_db_rich_messages_with_media_facts
    rich, _, _ = parse(payload, on_record=observe)
    accepted = sum(value for reason, value in counts.items() if reason.startswith("accepted"))
    all_directions = tuple(sum(values[i] for values in directions.values()) for i in range(3))
    reconciled_directions = (all_directions[0], all_directions[1], all_directions[2]+missing_body)
    for reason in sorted(counts):
        endpoint = bounds.get(reason)
        on_status({"phase": "adapter_disposition", "reason": reason, "rows": counts[reason],
            "legacy_missing_sender_drop_candidates": legacy_sender_drops[reason],
            "sender_states": dict(senders[reason]), "native_types": dict(types[reason]),
            "segment_type_rows": dict(segment_types[reason]),
            "protobuf_error_rows": dict(protobuf_errors[reason]), "no_segment_rows": no_segments[reason],
            "relative_time_quartiles": dict(times[reason]),
            "at_raw_first": endpoint is not None and endpoint[0] == low,
            "at_raw_last": endpoint is not None and endpoint[1] == high,
            "own_other_unknown": directions[reason]})
    on_status({"phase": "message_verification", "stage": "adapter_accounting",
        "source_rows": source_rows, "provider_rows": len(payload["records"]),
        "provider_missing_body_rows": missing_body, "provider_unclassified_rows": excluded["unclassified_rows"],
        "accepted_rows": accepted, "skipped_rows": sum(counts.values())-accepted,
        "accounted_rows": sum(counts.values())+missing_body, "field_mismatches": dict(mismatches),
        "source_directions_match": reconciled_directions == source_directions})
    if excluded["unclassified_rows"]:
        raise SourceError("provider_unclassified_records")
    if len(payload["records"])+missing_body != source_rows or sum(counts.values()) != len(payload["records"]):
        raise SourceError("provider_record_accounting_mismatch")
    if len(rich) != accepted or mismatches or reconciled_directions != source_directions:
        raise SourceError("adapter_field_accounting_mismatch")
    # No observed native type has yet proven a normal non-chat exclusion.
    # Unsupported/invalid content remains an explicit blocker, not a guessed
    # system filter. Normal analysis filters are counted separately below.
    if accepted != sum(counts.values()):
        raise SourceError("adapter_unclassified_records")
    accepted_bounds = [bounds[key] for key in bounds if key.startswith("accepted")]
    first_accepted = min((item[0] for item in accepted_bounds), default=None)
    last_accepted = max((item[1] for item in accepted_bounds), default=None)
    return {"provider_rows": len(payload["records"]), "provider_missing_body_rows": missing_body,
        "imported_rows": accepted, "first": first_accepted, "last": last_accepted,
        "own": sum(value[0] for key, value in directions.items() if key.startswith("accepted")),
        "unknown": sum(value[2] for key, value in directions.items() if key.startswith("accepted"))}


def validate_media_roots(roots, self_uin):
    """Validate explicit scopes against the formal layout; never discover roots."""
    import re
    from qq_chat_analyzer.application.qq.qq_media_directories import qq_media_search_roots
    validated = []
    for supplied in roots:
        path = Path(supplied)
        if not path.is_absolute() or ".." in path.parts:
            raise SourceError("media_account_scope_unconfirmed")
        root = _safe(path)
        if not root.is_dir():
            raise SourceError("media_account_scope_unconfirmed")
        if root.name == "marketface" and root.parent.name == "Emoji":
            data = root.parent.parent
        elif root.name == "Ori" and re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", root.parent.name):
            base, = qq_media_search_roots((root,))
            if base == root:
                raise SourceError("media_account_scope_unconfirmed")
            data = base.parent if base.name == "Pic" else base.parent.parent
        else:
            raise SourceError("media_account_scope_unconfirmed")
        owner = data.parent.parent if data.parent.name == "nt_qq" else data.parent
        if data.name != "nt_data" or owner.name != self_uin:
            raise SourceError("media_account_scope_unconfirmed")
        if root not in validated:
            validated.append(root)
    return tuple(validated)


def finish_report(database, temporary, report_directory, group, self_uin, dictionary,
        *, on_status=lambda status: print(json.dumps(status), flush=True),
        recover_sticker_media=False, sticker_media_roots=()):
    """No other conversation records are selected. Diagnostics contain no text."""
    if sticker_media_roots and not recover_sticker_media:
        raise SourceError("explicit_media_recovery_required")
    sticker_media_roots = validate_media_roots(sticker_media_roots, self_uin)
    logging.disable(logging.CRITICAL)
    import jieba
    jieba.set_dictionary(str(verify_dictionary(dictionary)))
    jieba.initialize()
    from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
    from qq_chat_analyzer.application.dto import AnalysisRequestDTO, AnalysisStatus
    from qq_chat_analyzer.providers.qq_database_provider import QQDatabaseProvider
    from qq_chat_analyzer.qq_db_identity import canonical_qq_uin
    from qq_chat_analyzer.resources import resource_path
    if not group.isdecimal() or not self_uin.isdecimal():
        raise SourceError("explicit_group_and_self_required")
    _file(database); _no_sidecars(database)
    deadline = time.monotonic() + 180
    stage = "sqlite_open"
    on_status({"phase": "database_verification_started"})
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
            stage = "integrity_check"
            connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                on_status({"phase": "database_read_failure", "stage": stage, "reason": "integrity_result_not_ok"})
                raise SourceError("full_integrity_check_failed")
            on_status({"phase": "database_verified", "integrity_check": "ok"})
            stage = "selected_partition_read"
            key, count, first, last = authorized_group_partition(connection, group, on_status)
            provider_exclusions = audit_provider_skips(connection, key, first, last, on_status)
            own, other, unknown = 0, 0, 0
            for sender, amount in connection.execute('SELECT "40033",COUNT(*) FROM group_msg_table WHERE CAST("40027" AS TEXT)=? GROUP BY "40033"', (key,)):
                canonical = canonical_qq_uin(sender)
                if canonical is None: unknown += amount
                elif canonical == canonical_qq_uin(self_uin): own += amount
                else: other += amount
            stage = "sqlite_close"
    except sqlite3.Error as error:
        status = {"phase": "database_read_failure", "stage": stage,
            "reason": "sqlite_error", "deadline_exceeded": time.monotonic() >= deadline}
        code = getattr(error, "sqlite_errorcode", None)
        if isinstance(code, int) and 0 <= code <= 0xffff:
            status["sqlite_errorcode"] = code
        on_status(status)  # Never SQLite error text: it may contain data or paths.
        raise SourceError("sqlite_read_refused") from None
    provider = QQDatabaseProvider(database)
    session = provider.find_session("group:" + key, self_uin=self_uin)
    if session is None or session.session_object != group:
        on_status({"phase": "message_verification", "stage": "provider_identity", "state": "refused",
            "session_found": session is not None, "external_group_matches": False, "source_rows": count})
        raise SourceError("provider_session_mismatch")
    payload = Path(temporary) / "selected.json"
    materialize_started = time.monotonic()
    on_status({"phase": "provider_materialization_started"})
    provider.materialize_session_payload(session, payload, self_uin=self_uin)
    on_status({"phase": "provider_materialization_completed",
        "elapsed_ms": round((time.monotonic()-materialize_started)*1000)})
    # Observe the owning application's ONE import in this dedicated research
    # worker. Return exactly its parsed Rich/PIC objects after the same audit;
    # do not create a verification graph only to discard and parse it again.
    from unittest.mock import patch
    from qq_chat_analyzer.application import import_service
    original_parse = import_service.parse_qq_db_rich_messages_with_media_facts
    audit = None
    def verified_parse(raw):
        nonlocal audit
        if audit is not None:
            raise SourceError("unexpected_repeated_import")
        parsed = None
        def parse_once(value, *, on_record):
            nonlocal parsed
            parsed = original_parse(value, on_record=on_record)
            return parsed
        audit = audit_adapter(raw, count, (own, other, unknown), first, last, self_uin, on_status,
            provider_exclusions=provider_exclusions, parse_messages=parse_once)
        on_status({"phase": "messages_verified", "selected_source_rows": count,
            "provider_missing_body_rows": audit["provider_missing_body_rows"],
            "own_messages": audit["own"], "unknown_direction_messages": audit["unknown"],
            "direction_verified": True, "timestamp_fields_verified": True})
        return parsed
    analysis_started = time.monotonic()
    progress_step = 0
    def analysis_progress(_message):
        nonlocal progress_step
        progress_step += 1
        # Only the ordinal leaves the callback, never arbitrary progress text.
        on_status({"phase": "analysis_progress", "step": progress_step,
            "elapsed_ms": round((time.monotonic()-analysis_started)*1000)})
    analysis = AnalysisApplicationService()
    on_status({"phase": "analysis_started"})
    with patch.object(import_service, "parse_qq_db_rich_messages_with_media_facts", verified_parse):
        result = analysis.execute(AnalysisRequestDTO(input_path=payload,
            output_directory=report_directory, stopwords_path=resource_path("stopwords.txt"),
            conversation_kind="group", export_echo_report=not recover_sticker_media), progress=analysis_progress)
    if audit is None:
        raise SourceError("verified_import_required")
    on_status({"phase": "analysis_completed", "elapsed_ms": round((time.monotonic()-analysis_started)*1000)})
    if recover_sticker_media and result.echo_report_view is not None:
        from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
        # Reuse the formal target selection, PIC local validation and MFACE
        # local->raw200 recovery. No connected provider, source builder or
        # runtime identity is supplied: this never acquires a NapCat runtime,
        # discovers account directories or performs native PIC downloads.
        facade = ChatAnalyzerFacade(analysis_service=analysis)
        from qq_chat_analyzer.presentation.stickers import sticker_report_targets
        local_states = {}
        associate = facade.associate_sticker_media
        def observe_local(data, **options):
            # MFACE has its own exact-coordinate reader. Do not make the PIC
            # inventory traverse that directory as well.
            options["roots"] = tuple(root for root in options["roots"] if root.name != "marketface")
            updated = associate(data, **options)
            keys = set(options["media_keys"])
            local_states.update((item.media_key, (item.status, item.reason))
                for item in updated.media if item.media_key in keys)
            return updated
        facade.associate_sticker_media = observe_local
        media_started = time.monotonic()
        on_status({"phase": "media_preparation_started", "media_budget_seconds": 45 if len(sticker_report_targets(result.echo_report_view.stickers)) > 12 else 30})
        stickers = facade._prepare_qq_report_media(result, payload, session,
            sticker_media_roots, None, lambda: False)
        media_elapsed_ms = round((time.monotonic() - media_started) * 1000)
        try:
            on_status({"phase": "media_preparation_completed", "elapsed_ms": media_elapsed_ms})
            on_status({"phase": "report_export_started"})
            export_started = time.monotonic()
            result = analysis.export_sticker_report(result, stickers, report_directory)
            on_status({"phase": "report_export_completed", "elapsed_ms": round((time.monotonic()-export_started)*1000)})
            chapter = result.echo_report_view.stickers
            targets = sticker_report_targets(chapter)
            primary = {t.media_key for t in sticker_report_targets(chapter, primary_only=True)}
            media = {item.media_key: item for item in stickers.media}
            assets = {asset.key: asset for asset in chapter.assets}
            categories, reasons, local_miss_reasons = Counter(), Counter(), Counter()
            usable = primary_usable = animated_gifs = 0
            uris = set()
            for target in targets:
                item = media.get(target.media_key)
                asset = assets[target.asset_key]
                reason = asset.reason or "none"
                reasons[reason] += 1
                if asset.data_uri and asset.status in {"available", "preview"}:
                    usable += 1
                    primary_usable += target.media_key in primary
                    uris.add(asset.data_uri)
                    animated_gifs += item.format == "GIF" and (item.frame_count or 0) > 1
                    category = ("mface_local" if reason == "marketface_local_resource_verified" else
                        "mface_raw200_preview" if reason == "marketface_cdn_raw200_resource_verified" else
                        "pic_local" if asset.status == "available" else "other_preview")
                elif reason in {"original_digest_unproven", "invalid_digest"}:
                    category = "insufficient_evidence"
                elif asset.status == "limited":
                    category = "budget_limited"
                elif local_states.get(target.media_key, (None,))[0] == "missing":
                    # Name/path miss or digest mismatch is NOT proof of deletion
                    # or absence elsewhere. Report the authorized search result.
                    category = "pic_cache_unrecovered"
                    local_miss_reasons[local_states[target.media_key][1]] += 1
                elif asset.status == "missing":
                    category = "resource_unavailable"
                else:
                    category = "other_failure"
                categories[category] += 1
            on_status({"phase": "sticker_media_verification", "targets": len(targets),
                "categories": dict(categories), "reason_counts": dict(reasons),
                "local_miss_reason_counts": dict(local_miss_reasons),
                "media_budget_seconds": 30 if len(targets) <= 12 else 45,
                "media_elapsed_ms": media_elapsed_ms, "primary_targets": len(primary),
                "primary_usable": primary_usable, "usable_assets": usable,
                "animated_gif_assets": animated_gifs, "distinct_exported_files": len(uris),
                "all_media_files_exist": all((report_directory / uri).is_file() for uri in uris),
                "category_total_verified": sum(categories.values()) == len(targets)})
        finally:
            # Match the formal facade's ownership after exporting media files.
            for item in stickers.media:
                if item.stored is not None:
                    item.stored.close()
    if result.status not in (AnalysisStatus.COMPLETED, AnalysisStatus.EXPRESSION_ONLY) or not result.artifacts:
        raise SourceError("report_not_completed")
    if any(not (report_directory / artifact.filename).is_file() for artifact in result.artifacts):
        raise SourceError("report_artifact_missing")
    chapter = result.echo_report_view.stickers if result.echo_report_view else None
    on_status({"phase": "sticker_verification", "recovery_requested": recover_sticker_media,
        "trusted_root_count": len(sticker_media_roots), "sends": len(result.stickers.sends),
        "identity_bases": dict(Counter(send.identity_basis for send in result.stickers.sends)),
        "pic_message_facts": len(result.qq_pic_media_facts),
        "view_send_count": chapter.total_send_count if chapter else None,
        "asset_targets": len(chapter.assets) if chapter else 0,
        "asset_status_counts": dict(Counter(asset.status for asset in chapter.assets)) if chapter else {},
        "asset_with_uri_count": sum(bool(asset.data_uri) for asset in chapter.assets) if chapter else 0})
    # The application owns all scope/profile/quality filters. Reconcile its
    # existing counters instead of copying them or extending the raw time span.
    from qq_chat_analyzer.analysis.timestamps import to_chat_datetime
    counts = result.diagnostic_counts
    view = result.echo_report_view
    activity = result.reports.activity
    profiles = result.reports.user_profiles
    conversations = result.reports.conversations
    summaries = conversations.conversations if conversations else ()
    start = min((item.start_timestamp for item in summaries if item.start_timestamp is not None), default=None)
    end = max((item.end_timestamp for item in summaries if item.end_timestamp is not None), default=None)
    span = ((to_chat_datetime(end).date()-to_chat_datetime(start).date()).days+1
        if start is not None and end is not None else 0)
    time_verified = (activity is not None and view is not None
        and activity.calendar_day_count == view.calendar_day_count == span
        and ((start is end is None) or (audit["first"] is not None
            and audit["first"] <= start <= end <= audit["last"])))
    counts_verified = (counts is not None and activity is not None and view is not None
        and counts.raw_message_count == audit["provider_rows"] and counts.imported_message_count == audit["imported_rows"]
        and count >= counts.imported_message_count >= counts.scope_message_count >= counts.filtered_message_count
        and counts.filtered_message_count == counts.analyzed_message_count == activity.total_message_count
        == view.total_message_count == sum(item.message_count for item in summaries))
    report_known = sum(item.message_count for item in profiles.profiles) if profiles else 0
    report_own = sum(item.message_count for item in profiles.profiles
        if item.speaker_key == canonical_qq_uin(self_uin)) if profiles else 0
    direction_verified = (view is not None and profiles is not None
        and profiles.total_message_count == view.total_message_count
        and report_own == sum(item.message_count for item in view.members if item.is_viewer)
        and 0 <= report_own <= audit["own"]
        and 0 <= view.total_message_count-report_known <= audit["unknown"])
    on_status({"phase": "report_verification", "counts_verified": counts_verified,
        "analysis_status": result.status.value,
        "time_range_verified": time_verified, "time_basis": "kept_messages_valid_dates",
        "direction_verified": direction_verified, "report_own_messages": report_own,
        "report_unknown_identity_messages": view.total_message_count-report_known if view else None,
        "raw_rows": count, "imported_rows": counts.imported_message_count if counts else None,
        "provider_missing_body_rows": audit["provider_missing_body_rows"],
        "analysis_raw_rows": counts.raw_message_count if counts else None,
        "scope_rows": counts.scope_message_count if counts else None,
        "filtered_rows": counts.filtered_message_count if counts else None,
        "report_rows": view.total_message_count if view else None,
        "report_endpoints_equal_adapter": (start, end) == (audit["first"], audit["last"])})
    if not counts_verified or not time_verified or not direction_verified:
        raise SourceError("report_accounting_mismatch")
    return {"phase": "full_read_result", "database_decrypted": True, "integrity_check": "ok",
        "messages_read": True, "selected_source_rows": count, "own_messages": audit["own"],
        "source_unknown_rows": unknown, "unknown_direction_messages": audit["unknown"],
        "provider_missing_body_rows": audit["provider_missing_body_rows"],
        "direction_verified": True, "time_range_verified": True, "report_generated": True,
        "analysis_status": result.status.value,
        "content_semantics": "existing_adapter_automated_only_user_spot_check_pending",
        "imported_messages": counts.imported_message_count,
        "analyzed_messages": counts.analyzed_message_count, "report_files": len(result.artifacts)}
