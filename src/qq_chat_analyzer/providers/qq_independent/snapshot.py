"""Frozen encrypted inputs and strict group partition binding."""
import ctypes
from ctypes import wintypes
import hashlib,json,os,subprocess,time,uuid
from pathlib import Path
from .files import SourceError,_safe,_file,_identity,_no_sidecars,_format
MAX_BYTES=1024**3
OWNER={"kind":"echo-qq-full-read","version":1}

def bind_live_database_paths(paths, expected_uin):
    """Bind process-owned paths to an independently established canonical UIN.

    The caller must verify the process generation and provenance of all paths.
    This check neither discovers the current user nor proves a login epoch or
    snapshot consistency. It only checks directory scope and file metadata.
    No directory enumeration or database content read is performed.
    """
    if (not isinstance(expected_uin, bytes) or not expected_uin.isdigit()
            or expected_uin.startswith(b'0') or not 5 <= len(expected_uin) <= 20):
        raise SourceError('independent_owner_reference_required')
    accounts, main = set(), set()
    for raw in paths:
        path = Path(raw)
        if (not path.is_absolute() or path.parent.name.casefold() != 'nt_db'
                or path.parent.parent.name.casefold() != 'nt_qq'):
            raise SourceError('database_path_shape_unknown')
        accounts.add(path.parent.parent.parent)
        if path.name.casefold() == 'nt_msg.db':
            main.add(path)
    if len(accounts) != 1 or len(main) != 1:
        raise SourceError('database_binding_not_unique')
    if next(iter(accounts)).name.encode('ascii', errors='replace') != expected_uin:
        raise SourceError('database_account_mismatch')
    main = next(iter(main))
    for path in (main, Path(str(main)+'-wal'), Path(str(main)+'-shm')):
        _file(path)
    return main


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
