"""Synthetic-only QQ SQLite comparison; never accepts an existing database.

Run with the verified project interpreter and PYTHONPATH=src. Results describe
warm OS-cache runs and process I/O counters, not physical disk traffic. Each
query uses a fresh, isolated process. The output directory must be new.
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
import statistics
import subprocess
import sys
import time


QUERY = (
    'SELECT "40027" AS internal_key, '
    'MAX(CASE WHEN TRIM(CAST("40030" AS TEXT)) NOT IN (\'\', \'0\') '
    'THEN "40030" END) AS session_object, COUNT(*) AS message_count, '
    'MAX("40050") AS last_message_time FROM group_msg_table {hint} '
    'GROUP BY "40027" ORDER BY last_message_time DESC'
)


def counters():
    """Windows process counters; mapping page faults bypass ReadTransferCount."""
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
                    ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

    class Memory(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in
            ("peak_rss", "rss", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "private", "peak_private")]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    handle = kernel.GetCurrentProcess()
    io = IO()
    memory = Memory()
    memory.cb = ctypes.sizeof(memory)
    kernel.GetProcessIoCounters.argtypes = [ctypes.c_void_p, ctypes.POINTER(IO)]
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Memory), wintypes.DWORD]
    if not kernel.GetProcessIoCounters(handle, ctypes.byref(io)) or not psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(memory), memory.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return dict(read_bytes=io.read_bytes, write_bytes=io.write_bytes, read_ops=io.read_ops,
                write_ops=io.write_ops, peak_rss=memory.peak_rss, peak_private=memory.peak_private)


def worker(args):
    # Load the verified Frozen DLL only in this diagnostic process, before sqlite3.
    if args.dll:
        ctypes.CDLL(str(Path(args.dll).resolve()))
    import sqlite3
    control = None
    if args.qq_layout:
        from qq_chat_analyzer.providers.qq_sqlite_reader import _pending_byte_control
        control = _pending_byte_control()
        control(11, 0x40000000 - 1024)

    database = Path(args.output) / "fictional.db"
    before = counters()
    started = time.perf_counter()
    with closing(sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        mmap = connection.execute(f"PRAGMA mmap_size={args.mmap}").fetchone()[0]
        if args.cache:
            connection.execute(f"PRAGMA cache_size=-{args.cache}")
        query = "PRAGMA quick_check(1)" if args.stage == "check" else QUERY.format(hint=args.hint)
        if args.unordered_group:
            query = query.replace('GROUP BY "40027"', 'GROUP BY +"40027"')
        plan = [] if args.stage == "check" else connection.execute("EXPLAIN QUERY PLAN " + query).fetchall()
        rows = connection.execute(query).fetchall()
    elapsed = time.perf_counter() - started
    if control:
        control(11, 0x40000000)
    after = counters()
    result = dict(seconds=elapsed, mmap=mmap, sqlite=sqlite3.sqlite_version, plan=plan,
                  result_hash=hashlib.sha256(repr(rows).encode()).hexdigest(),
                  rows=len(rows), check=rows if args.stage == "check" else None)
    result.update({key: after[key] - before[key] if key.endswith(("bytes", "ops")) else after[key]
                   for key in after})
    print(json.dumps(result))


def generate(root, rows, qq_layout):
    import sqlite3

    root.mkdir(parents=True, exist_ok=False)
    database = root / "fictional.db"
    if qq_layout:
        # Reserve QQ's 48-byte page tail and allocate with its pending-byte
        # layout. All changes are confined to this generated fictional image.
        from qq_chat_analyzer.providers.qq_sqlite_reader import _pending_byte_control
        control = _pending_byte_control()
        control(11, 0x40000000 - 1024)
        library = ctypes.CDLL("sqlite3.dll")
        library.sqlite3_open.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        library.sqlite3_file_control.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
        library.sqlite3_exec.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        library.sqlite3_close.argtypes = [ctypes.c_void_p]
        handle, reserved = ctypes.c_void_p(), ctypes.c_int(48)
        assert library.sqlite3_open(os.fsencode(database), ctypes.byref(handle)) == 0
        try:
            assert library.sqlite3_file_control(handle, b"main", 38, ctypes.byref(reserved)) == 0
            assert library.sqlite3_exec(handle, b"VACUUM", None, None, None) == 0
        finally:
            assert library.sqlite3_close(handle) == 0
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=OFF")  # Fixture construction only.
        connection.execute('CREATE TABLE group_msg_table ("40001" INTEGER PRIMARY KEY, '
                           '"40027" INTEGER, "40030" TEXT, "40033" TEXT, "40050" INTEGER, "40800" BLOB)')
        blob = b"fictional-only " * 73
        for start in range(0, rows, 10000):
            connection.executemany("INSERT INTO group_msg_table VALUES(?,?,?,?,?,?)", (
                (number, number % 200 + 1, str(800000 + number % 200), str(900000 + number % 30),
                 1700000000 + number, blob) for number in range(start, min(start + 10000, rows))))
        connection.execute('CREATE INDEX fictional_partition_time ON group_msg_table("40027", "40050")')
        connection.execute('CREATE INDEX fictional_message_time ON group_msg_table("40050")')
        connection.commit()
    if qq_layout:
        control(11, 0x40000000)
    (root / "profile").mkdir()
    (root / "temp").mkdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output")
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--stage", choices=("check", "groups"), default="check")
    parser.add_argument("--mmap", type=int, default=0)
    parser.add_argument("--cache", type=int, default=0)
    parser.add_argument("--hint", default="")
    parser.add_argument("--dll")
    parser.add_argument("--qq-layout", action="store_true")
    parser.add_argument("--unordered-group", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return
    root = Path(args.output).resolve()
    generate(root, args.rows, args.qq_layout)
    env = dict(os.environ)
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        env[name] = str(root / "profile")
    for name in ("TEMP", "TMP", "SQLITE_TMPDIR"):
        env[name] = str(root / "temp")
    env.pop("PYTHONSTARTUP", None)
    variants = [("check", 0, 0, False), ("check", 0, 16384, False),
                ("check", 268435456, 0, False), ("check", 1073741824, 0, False),
                ("groups", 0, 0, False), ("groups", 0, 0, True),
                ("groups", 268435456, 0, False), ("groups", 268435456, 0, True)]
    results = {}
    # Alternate order to avoid treating cache warm-up/order as optimization.
    for repeat in range(3):
        for stage, mmap, cache, unordered in (variants if repeat % 2 == 0 else reversed(variants)):
            command = [sys.executable, str(Path(__file__).resolve()), str(root), "--worker",
                       "--stage", stage, "--mmap", str(mmap), "--cache", str(cache)]
            if args.dll:
                command += ["--dll", args.dll]
            if args.qq_layout:
                command += ["--qq-layout"]
            if unordered:
                command += ["--unordered-group"]
            completed = subprocess.run(command, env=env, check=True, capture_output=True, text=True, timeout=300)
            result = json.loads(completed.stdout)
            label = f"{stage}:mmap={mmap}:cache={cache}:unordered={unordered}"
            results.setdefault(label, []).append(result)
            print(label, round(result["seconds"], 3), flush=True)
    report = dict(rows=args.rows, database_bytes=(root / "fictional.db").stat().st_size,
                  results=results, medians={label: statistics.median(r["seconds"] for r in runs)
                                           for label, runs in results.items()})
    (root / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["medians"], indent=2))


if __name__ == "__main__":
    main()
