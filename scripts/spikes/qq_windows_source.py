"""Independent Windows QQ source spike. Explicit authorized inputs only.

Local-host inventory requires an explicit opt-in and reads metadata / magic only.
Connections require frozen inputs. No process access, client launch, background
watch or WAL recovery. Not wired to the production source path.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile


SQLITE = b"SQLite format 3\0"
WRAPPED = b"SQLite header 3\0"
MAX_BYTES = 64 * 1024 * 1024  # Existing codec is in-memory; fail, never truncate.
TABLES = ("c2c_msg_table", "group_msg_table")
COLUMNS = {"40001", "40027", "40030", "40033", "40050", "40800"}


class SourceError(Exception):
    """Only a fixed public code; no path, SQL, key or native exception text."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _local_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    if os.name == "nt" and str(path).startswith("\\\\"):
        raise SourceError("local_path_required")
    return path


def _safe(path: Path) -> Path:
    path = _local_path(path)
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise SourceError("linked_path")
    return path


def _file(path: Path):
    info = _safe(path).stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SourceError("invalid_file")
    return info


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _no_sidecars(path):
    if any(os.path.lexists(str(path) + suffix) for suffix in ("-wal", "-shm", "-journal")):
        raise SourceError("frozen_main_required")


def _read_unchanged(path, *, prefix_bytes=None):
    before = _file(path)
    if prefix_bytes is None and before.st_size > MAX_BYTES:
        raise SourceError("prototype_size_limit")
    with path.open("rb", buffering=0) as stream:
        opened = os.fstat(stream.fileno())
        # Windows Python stat/fstat expose different ctime meanings. Compare
        # identity/size/mtime across APIs; retain ctime within each API below.
        if _identity(opened)[:4] != _identity(before)[:4]:
            raise SourceError("input_changed")
        data = stream.read(prefix_bytes if prefix_bytes is not None else MAX_BYTES + 1)
        if _identity(os.fstat(stream.fileno())) != _identity(opened):
            raise SourceError("input_changed")
    if _identity(_file(path)) != _identity(before):
        raise SourceError("input_changed")
    if prefix_bytes is None and len(data) != before.st_size:
        raise SourceError("input_changed")
    return data, before.st_size


def _read(path, *, header_only=False):
    _no_sidecars(path)
    data, size = _read_unchanged(path, prefix_bytes=1040 if header_only else None)
    _no_sidecars(path)
    return data, size


def _format(header, size):
    if header.startswith(SQLITE) and len(header) >= 100:
        page = int.from_bytes(header[16:18], "big")
        page = 65536 if page == 1 else page
        if page < 512 or page > 65536 or page & (page - 1) or size % page:
            raise SourceError("invalid_sqlite_size")
        if not int.from_bytes(header[28:32], "big") or header[24:28] != header[92:96]:
            raise SourceError("untrusted_page_count")
        if int.from_bytes(header[28:32], "big") != size // page:
            raise SourceError("page_count_mismatch")
        return "plaintext_candidate"
    if header.startswith(WRAPPED):
        if size < 1024 + 4096 or (size - 1024) % 4096:
            raise SourceError("invalid_encrypted_size")
        return "key_required"  # Header recognition is not authentication.
    raise SourceError("unsupported_header")


def doctor(qq_executable=None):
    result = {"system": platform.system(), "architecture": platform.machine(),
              "node_available": shutil.which("node") is not None,
              "process_access": False, "automatic_key_capture": False,
              "input_mode": "explicit_frozen_main", "qq_version": "not_inspected"}
    if qq_executable is not None:
        from qq_chat_analyzer.application.qq.qq_version import read_qq_resources
        executable = _safe(Path(qq_executable))
        _file(executable)
        try:
            resources = read_qq_resources(executable)
        except (OSError, ValueError, RuntimeError):
            raise SourceError("resources_unverified") from None
        if resources is None or resources.version is None or resources.wrapper_path is None:
            raise SourceError("resources_unverified")
        result["qq_version"] = ".".join(map(str, resources.version[:3])) + "-" + str(resources.version[3])
        result["independent_54395_verified"] = False
    return result


class WindowsQQSource:
    """Locate an explicit local root; connect through a private temporary copy."""

    def __init__(self, data_root, work_parent):
        self.root = _safe(Path(data_root))
        self.work = _safe(Path(work_parent))
        if not self.root.is_dir() or not self.work.is_dir():
            raise SourceError("directory_required")
        if self.root.is_relative_to(self.work) or self.work.is_relative_to(self.root):
            raise SourceError("workspace_overlap")

    def _paths(self):
        # Deliberately bounded QQ layouts, no recursive scan of user profiles.
        paths = [self.root / name for name in (
            "nt_msg.db", "nt_db/nt_msg.db", "nt_qq/nt_db/nt_msg.db",
        )]
        with os.scandir(self.root) as entries:
            for index, entry in enumerate(entries):
                if index >= 256:
                    raise SourceError("discovery_limit")
                if entry.name.startswith("nt_qq_"):
                    paths.append(Path(entry.path) / "nt_db/nt_msg.db")
                elif re.fullmatch(r"[0-9]{5,20}", entry.name):
                    paths.append(Path(entry.path) / "nt_qq/nt_db/nt_msg.db")
        result = {}
        for path in paths:
            if os.path.lexists(path):
                _file(path)
                identifier = hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest()[:24]
                result[identifier] = path
        return result

    def inspect(self):
        """Live-directory preflight: stat sidecars, read only 16 magic bytes.

        Never open SQLite, authenticate/decrypt, copy a database or infer an
        account identity. Sidecar absence does not prove a frozen database.
        """
        result = []
        for identifier, path in self._paths().items():
            record = {"database_id": identifier, "authenticated": False}
            parts = path.relative_to(self.root).parts
            record["layout"] = (
                "{account}/nt_qq/nt_db/nt_msg.db" if len(parts) == 4 else
                "nt_qq_*/nt_db/nt_msg.db" if parts[0].startswith("nt_qq_") else
                "/".join(parts)
            )
            try:
                magic, size = _read_unchanged(path, prefix_bytes=16)
                record.update(main_bytes=size, header_bytes_read=len(magic))
                if magic == WRAPPED:
                    record["container"] = "qq_wrapped_candidate"
                    record["candidate_page_alignment"] = size >= 5120 and (size - 1024) % 4096 == 0
                elif magic == SQLITE:
                    record["container"] = "sqlite_candidate"
                else:
                    record["container"] = "unknown"
                sidecars = {}
                for name, suffix in (("wal", "-wal"), ("shm", "-shm"), ("journal", "-journal")):
                    sidecar = Path(str(path) + suffix)
                    sidecars[name] = {"present": os.path.lexists(sidecar)}
                    if sidecars[name]["present"]:
                        sidecars[name]["size_bytes"] = _file(sidecar).st_size
                record["sidecars"] = sidecars
                record["connection_readiness"] = "frozen_input_not_proven"
            except (SourceError, OSError) as error:
                record["state"] = error.code if isinstance(error, SourceError) else "filesystem_unavailable"
            result.append(record)
        return result

    def locate(self):
        result = []
        for identifier, path in self._paths().items():
            try:
                header, size = _read(path, header_only=True)
                state = _format(header, size)
            except SourceError as error:
                state, size = error.code, None
            result.append({"database_id": identifier, "state": state, "size_bytes": size,
                           "authenticated": False})
        return result

    @contextmanager
    def connect(self, database_id=None, *, key_file=None):
        paths = self._paths()
        if database_id is None:
            if len(paths) != 1:
                raise SourceError("database_selection_required")
            database_id = next(iter(paths))
        if database_id not in paths:
            raise SourceError("database_not_found")
        path = paths[database_id]
        header, size = _read(path, header_only=True)
        kind = _format(header, size)
        key = None
        if kind == "key_required":
            if key_file is None:
                raise SourceError("key_required")
            _file(Path(key_file))
            if Path(key_file).stat().st_size > 4096:
                raise SourceError("invalid_key_file")
            try:
                key = json.loads(Path(key_file).read_text(encoding="utf-8"))
                valid = isinstance(key, dict) and key.get("kind") in ("raw", "passphrase") and isinstance(key.get("value"), str) and bool(key["value"])
                if not valid or key["kind"] == "raw" and len(bytes.fromhex(key["value"])) != 32:
                    raise ValueError
            except (ValueError, TypeError):
                raise SourceError("invalid_key_file") from None
        data, _ = _read(path)
        # Validate the bytes actually copied, not only the earlier probe.
        if _format(data[:1040], len(data)) != kind:
            raise SourceError("input_changed")
        with tempfile.TemporaryDirectory(prefix="qq-independent-", dir=self.work) as directory:
            owned = Path(directory)
            snapshot = owned / "snapshot.db"
            if kind == "key_required":
                encrypted = owned / "encrypted.db"
                encrypted.write_bytes(data)
                self._decrypt(encrypted, snapshot, key)
                encrypted.unlink()
            else:
                snapshot.write_bytes(data)
            with snapshot.open("rb") as stream:
                if stream.read(20)[18:20] != b"\1\1":
                    raise SourceError("frozen_main_required")
            try:
                with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
                    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                        raise SourceError("integrity_failed")
                    for table in TABLES:
                        columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
                        if not COLUMNS <= columns:
                            raise SourceError("unsupported_schema")
            except sqlite3.DatabaseError:
                raise SourceError("integrity_failed") from None
            from qq_chat_analyzer.providers.qq_database_provider import QQDatabaseProvider
            yield QQDatabaseProvider(snapshot)

    @staticmethod
    def _decrypt(encrypted, output, key):
        node = shutil.which("node")
        if not node:
            raise SourceError("node_required")
        codec = Path(__file__).with_name("qq_independent_codec.mjs").as_uri()
        program = """
import {readFileSync,writeFileSync} from 'node:fs';
import {pbkdf2Sync} from 'node:crypto';
import {decode} from CODEC;
try {
 const record=JSON.parse(readFileSync(0,'utf8'));
 const data=readFileSync(process.argv[1]),salt=data.subarray(1024,1040);
 const key=record.kind==='raw'?Buffer.from(record.value,'hex'):pbkdf2Sync(record.value,salt,4000,32,'sha512');
 writeFileSync(process.argv[2],decode(data,key,salt),{flag:'wx'});
 console.log('ok');
} catch { console.log('decode_rejected'); process.exitCode=3; }
""".replace("CODEC", json.dumps(codec))
        environment = os.environ.copy()
        for name in ("NODE_OPTIONS", "NODE_PATH"):
            environment.pop(name, None)
        for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
            target = output.parent / name
            target.mkdir()
            environment[name] = str(target)
        try:
            completed = subprocess.run([node, "--input-type=module", "--eval", program, str(encrypted), str(output)],
                input=json.dumps(key), env=environment, encoding="utf-8", capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            raise SourceError("decoder_unavailable") from None
        if completed.returncode != 0 or completed.stdout.strip() != "ok":
            raise SourceError("decode_rejected")


def local_host_locations():
    """Opt-in caller only: fixed QQ registry / known folders, no drive scan."""
    if os.name != "nt":
        raise SourceError("windows_required")
    import winreg
    from qq_chat_analyzer.application.qq.qq_auth_bridge import _qq_install_candidates
    installations = _qq_install_candidates()  # Existing read-only registry/path helper.
    documents = Path.home() / "Documents"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            value, _ = winreg.QueryValueEx(key, "Personal")
            if isinstance(value, str) and value:
                documents = Path(os.path.expandvars(value))
    except OSError:
        pass
    roots = {"documents_tencent": documents / "Tencent Files"}
    for variable, label in (("APPDATA", "roaming"), ("LOCALAPPDATA", "local")):
        if os.environ.get(variable):
            for client in ("QQ", "QQNT"):
                roots[f"{label}_{client.lower()}"] = Path(os.environ[variable]) / "Tencent" / client
    return installations, roots


def inventory(installations, roots, work_parent):
    """Sanitized inventory; locations stay in memory and never enter receipts."""
    result = {"installations": [], "data_roots": [], "process_access": False,
              "messages_read": False, "qq_54395": "not_verified"}
    seen = set()
    for executable in installations:
        try:
            executable = _local_path(executable)
            if not os.path.lexists(executable):
                continue
            canonical = os.path.normcase(os.path.abspath(executable))
            if canonical in seen:
                continue
            seen.add(canonical)
            info = doctor(executable)
            result["installations"].append({"installation_index": len(seen), "resource_version": info["qq_version"]})
        except (SourceError, OSError) as error:
            result["installations"].append({"state": error.code if isinstance(error, SourceError) else "filesystem_unavailable"})
    for label, root in roots.items():
        record = {"root_kind": label, "exists": None}
        try:
            root = _local_path(root)
            record["exists"] = os.path.lexists(root)
            if record["exists"]:
                record["databases"] = WindowsQQSource(root, work_parent).inspect()
        except (SourceError, OSError) as error:
            record["state"] = error.code if isinstance(error, SourceError) else "filesystem_unavailable"
        result["data_roots"].append(record)
    return result


def inspect_local_host(work_parent):
    # Capture only authorized location hints before isolating diagnostic imports.
    # No QQ/Echo saved config, login state or process enumeration is consulted.
    installations, roots = local_host_locations()
    work = _safe(Path(work_parent))
    with tempfile.TemporaryDirectory(prefix="qq-inventory-", dir=work) as directory:
        previous = {}
        try:
            for name in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "MPLCONFIGDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
                target = Path(directory) / name
                target.mkdir()
                previous[name] = os.environ.get(name)
                os.environ[name] = str(target)
            return inventory(installations, roots, work)
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("doctor", "inventory", "locate", "connect"))
    parser.add_argument("--inspect-local-host", action="store_true")
    parser.add_argument("--qq-executable")
    parser.add_argument("--data-root")
    parser.add_argument("--work-parent")
    parser.add_argument("--database-id")
    parser.add_argument("--key-file")
    args = parser.parse_args()
    try:
        if args.operation == "inventory":
            if not args.inspect_local_host or not args.work_parent:
                parser.error("inventory requires --inspect-local-host and --work-parent")
            result = inspect_local_host(args.work_parent)
        elif args.operation == "doctor":
            result = doctor(args.qq_executable)
        else:
            if not args.data_root or not args.work_parent:
                parser.error("--data-root and --work-parent are required")
            source = WindowsQQSource(args.data_root, args.work_parent)
            if args.operation == "locate":
                result = {"databases": source.locate()}
            else:
                with source.connect(args.database_id, key_file=args.key_file) as provider:
                    result = {"state": "ready", "session_count": len(provider.list_sessions()),
                              "qq_54395": "not_verified"}
        print(json.dumps(result, ensure_ascii=False))
    except (SourceError, OSError) as error:
        print(json.dumps({"state": "refused", "code": error.code if isinstance(error, SourceError) else "filesystem_unavailable"}))
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
