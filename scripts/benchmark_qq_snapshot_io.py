"""Synthetic-only benchmark for QQ capture, WAL merge, and patched decryption.

The output directory must not exist.  The script creates its own fictional
SQLite/WAL source and never accepts an existing database.  Results describe
warm-cache local I/O; the formal source-lock handshake is intentionally outside
the measured core pipeline.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import statistics
import subprocess
import sys


FICTIONAL_PASSPHRASE = "fictional-local-passphrase"


class IOCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "read_ops", "write_ops", "other_ops",
            "read_bytes", "write_bytes", "other_bytes",
        )
    ]


class MemoryCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
        (name, ctypes.c_size_t)
        for name in (
            "peak_rss", "rss", "peak_paged", "paged",
            "peak_nonpaged", "nonpaged", "private", "peak_private",
        )
    ]


def process_counters(handle: int) -> dict[str, int]:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetProcessIoCounters.argtypes = [ctypes.c_void_p, ctypes.POINTER(IOCounters)]
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(MemoryCounters), wintypes.DWORD,
    ]
    io = IOCounters()
    memory = MemoryCounters()
    memory.cb = ctypes.sizeof(memory)
    if not kernel.GetProcessIoCounters(handle, ctypes.byref(io)) or not psapi.GetProcessMemoryInfo(
        handle, ctypes.byref(memory), memory.cb,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        "read_bytes": io.read_bytes,
        "write_bytes": io.write_bytes,
        "read_ops": io.read_ops,
        "write_ops": io.write_ops,
        "peak_rss": memory.peak_rss,
        "peak_private": memory.peak_private,
    }


def reserve_48_bytes(path: Path) -> None:
    sqlite3.sqlite_version  # Ensure the process SQLite DLL is loaded.
    library = ctypes.CDLL("sqlite3.dll")
    library.sqlite3_open.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
    library.sqlite3_file_control.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p,
    ]
    library.sqlite3_exec.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p,
    ]
    library.sqlite3_close.argtypes = [ctypes.c_void_p]
    database = ctypes.c_void_p()
    if library.sqlite3_open(os.fsencode(path), ctypes.byref(database)) != 0:
        raise RuntimeError("fixture open failed")
    try:
        reserved = ctypes.c_int(48)
        if library.sqlite3_file_control(database, b"main", 38, ctypes.byref(reserved)) != 0:
            raise RuntimeError("fixture reserve failed")
        if library.sqlite3_exec(database, b"VACUUM", None, None, None) != 0:
            raise RuntimeError("fixture vacuum failed")
    finally:
        library.sqlite3_close(database)


def generate_fixture(root: Path, rows: int, blob_bytes: int, project: Path) -> tuple[Path, Path]:
    plain = root / "plain.db"
    reserve_48_bytes(plain)
    with closing(sqlite3.connect(plain)) as writer:
        if writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
            raise RuntimeError("WAL unavailable")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE payload (id INTEGER PRIMARY KEY, body BLOB NOT NULL)")
        writer.executemany(
            "INSERT INTO payload(body) VALUES (zeroblob(?))",
            ((blob_bytes,) for _ in range(rows)),
        )
        writer.commit()
        if writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
            raise RuntimeError("fixture checkpoint failed")
        writer.execute(
            "UPDATE payload SET body=randomblob(?) WHERE id <= ?",
            (blob_bytes, min(rows, 16)),
        )
        writer.commit()
        encrypted = root / "encrypted.db"
        encrypted_wal = root / "encrypted.db-wal"
        environment = dict(os.environ, ECHO_POC_PASSPHRASE=FICTIONAL_PASSPHRASE)
        completed = subprocess.run(
            [
                "node", str(project / "scripts/qq_direct_db_snapshot/main_wal_poc.mjs"),
                "fixture", str(plain), str(plain) + "-wal",
                str(encrypted), str(encrypted_wal),
            ],
            cwd=project,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if json.loads(completed.stdout) != {"ok": True, "fixture": True}:
            raise RuntimeError("encrypted fixture failed")
    return encrypted, encrypted_wal


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def capture_module(project: Path, root: Path, batch_pages: int) -> str:
    source = project / "scripts/qq_direct_db_snapshot/main_wal.mjs"
    if batch_pages == 256:
        return source.resolve().as_uri()
    text = source.read_text(encoding="utf-8")
    replacements = {
        "Math.min(256, available - index) * frameSize":
            f"Math.min({batch_pages}, available - index) * frameSize",
        "offset += 1024 * 1024": f"offset += {batch_pages} * PAGE_SIZE",
        "Math.min(1024 * 1024, size - offset)":
            f"Math.min({batch_pages} * PAGE_SIZE, size - offset)",
        "const outputBatch = Buffer.alloc(256 * PAGE_SIZE);":
            f"const outputBatch = Buffer.alloc({batch_pages} * PAGE_SIZE);",
        "Math.floor((number - 1) / 256) * 256":
            f"Math.floor((number - 1) / {batch_pages}) * {batch_pages}",
        "Math.min(256, mainPages - mainBatchStart + 1) * PAGE_SIZE":
            f"Math.min({batch_pages}, mainPages - mainBatchStart + 1) * PAGE_SIZE",
        "outputPages === 256": f"outputPages === {batch_pages}",
    }
    for old, new in replacements.items():
        if text.count(old) != 1:
            raise RuntimeError(f"capture batch anchor changed: {old}")
        text = text.replace(old, new)
    generated = root / f"main_wal_batch_{batch_pages}.mjs"
    generated.write_text(text, encoding="utf-8")
    return generated.resolve().as_uri()


def runner_source(project: Path, module_url: str) -> str:
    pins = json.loads((project / "scripts/qq_napcat_runtime_pins.json").read_text(encoding="utf-8"))
    decoder = pins["napcatPatch"]["replacements"][4]["replacement"]
    capsule = (project / "tests/fixtures/napcat_41834_database_crypto.mjs").read_text(encoding="utf-8")
    return f"""
import * as fs from 'node:fs';
import {{createDecipheriv as GL,pbkdf2Sync as aI}} from 'node:crypto';
import {{createMergedEncryptedDatabase,finalizeStandaloneSnapshot}} from '{module_url}';
const $e=fs;
{capsule}
{decoder}
const [mainPath,walPath,mergedPath,snapshotPath]=process.argv.slice(1);
const captureStarted=performance.now();
const captured=await createMergedEncryptedDatabase({{mainPath,walPath,outputPath:mergedPath}});
const captureMs=performance.now()-captureStarted;
const decryptStarted=performance.now();
if(!zE(mergedPath,Buffer.from(process.env.ECHO_POC_PASSPHRASE),snapshotPath)) throw Error('decrypt');
const decryptMs=performance.now()-decryptStarted;
const finalizeStarted=performance.now();
finalizeStandaloneSnapshot(snapshotPath,captured.pages);
const finalizeMs=performance.now()-finalizeStarted;
console.log(JSON.stringify({{capture_ms:captureMs,decrypt_ms:decryptMs,finalize_ms:finalizeMs,
  pages:captured.pages,merged_bytes:fs.statSync(mergedPath).size,snapshot_bytes:fs.statSync(snapshotPath).size}}));
"""


def run_pipeline(
    project: Path,
    root: Path,
    source: str,
    encrypted: Path,
    wal: Path,
    batch_pages: int,
    repeat: int,
) -> dict:
    merged = root / f"merged-{batch_pages}-{repeat}.db"
    snapshot = root / f"snapshot-{batch_pages}-{repeat}.db"
    environment = dict(os.environ, ECHO_POC_PASSPHRASE=FICTIONAL_PASSPHRASE)
    process = subprocess.Popen(
        ["node", "--input-type=module", "--eval", source, str(encrypted), str(wal), str(merged), str(snapshot)],
        cwd=project,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    returncode = process.wait(timeout=300)
    counters = process_counters(int(process._handle))  # type: ignore[attr-defined]
    stdout = process.stdout.read() if process.stdout else ""
    stderr = process.stderr.read() if process.stderr else ""
    if returncode or stderr:
        raise RuntimeError(f"pipeline failed: {returncode} {stderr}")
    result = json.loads(stdout)
    with closing(sqlite3.connect(f"{snapshot.resolve().as_uri()}?mode=ro", uri=True)) as reader:
        if reader.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
            raise RuntimeError("snapshot check failed")
        result["rows"] = reader.execute("SELECT count(*) FROM payload").fetchone()[0]
    result["snapshot_hash"] = sha256(snapshot)
    result["batch_pages"] = batch_pages
    result["peak_pipeline_temp_bytes"] = result["merged_bytes"] + result["snapshot_bytes"]
    result.update(counters)
    merged.unlink()
    snapshot.unlink()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("--rows", type=int, default=512)
    parser.add_argument("--blob-bytes", type=int, default=256 * 1024)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--batch-pages", type=int, nargs="+", default=(256, 1024))
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Windows only")
    project = Path(__file__).resolve().parents[1]
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / "profile").mkdir()
    (root / "temp").mkdir()
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "TEMP", "TMP"):
        os.environ[name] = str(root / ("temp" if name in {"TEMP", "TMP"} else "profile"))
    encrypted, wal = generate_fixture(root, args.rows, args.blob_bytes, project)
    sources = {
        batch_pages: runner_source(project, capture_module(project, root, batch_pages))
        for batch_pages in args.batch_pages
    }
    results = {str(batch_pages): [] for batch_pages in args.batch_pages}
    for repeat in range(args.repeats):
        order = args.batch_pages if repeat % 2 == 0 else tuple(reversed(args.batch_pages))
        for batch_pages in order:
            result = run_pipeline(
                project, root, sources[batch_pages], encrypted, wal, batch_pages, repeat,
            )
            results[str(batch_pages)].append(result)
            print(batch_pages, repeat + 1, round(result["capture_ms"] / 1000, 3),
                  round(result["decrypt_ms"] / 1000, 3), flush=True)
    all_runs = [run for runs in results.values() for run in runs]
    if len({run["snapshot_hash"] for run in all_runs}) != 1:
        raise RuntimeError("snapshot output changed between runs")
    report = {
        "fixture": {
            "rows": args.rows,
            "blob_bytes": args.blob_bytes,
            "encrypted_main_bytes": encrypted.stat().st_size,
            "encrypted_wal_bytes": wal.stat().st_size,
        },
        "runs": results,
        "variants": {
            batch_pages: {
                "medians": {
                    key: statistics.median(run[key] for run in runs)
                    for key in ("capture_ms", "decrypt_ms", "finalize_ms", "read_bytes", "write_bytes", "read_ops", "write_ops")
                },
                "maxima": {
                    key: max(run[key] for run in runs)
                    for key in ("peak_rss", "peak_private", "peak_pipeline_temp_bytes")
                },
            }
            for batch_pages, runs in results.items()
        },
    }
    (root / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["variants"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
