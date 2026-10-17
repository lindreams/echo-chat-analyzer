"""One opt-in, local integrity result, released only after snapshot cleanup.

Never serialize SQLite text, page bytes, identifiers, paths, credentials or
fingerprints. The pending directory is an in-memory ownership check only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from threading import Lock

_lock = Lock()
_claimed = False
_pending: tuple[Path, dict] | None = None


def classify_integrity_result(value: object) -> str:
    if not isinstance(value, str):
        return "unknown"
    if value == "ok":
        return "ok"
    # Constraint diagnostics contain arbitrary schema names after these prefixes.
    if value.startswith(("NULL value in ", "CHECK constraint failed in ", "non-")):
        return "constraint"
    text = value.lower()
    if "freelist" in text or "free-list" in text:
        return "freelist"
    if "overflow" in text:
        return "overflow"
    if any(token in text for token in ("fragmentation", "freeblock", "multiple uses for byte", "cell size", "cell offset")):
        return "cell_layout"
    if any(token in text for token in ("invalid page number", "never used", "used more than once", "page reference", "2nd reference")):
        return "page_reference"
    if any(token in text for token in ("btreeinitpage", "tree depth", "rowid", "key order")):
        return "btree"
    return "unknown"


def _page_verification(value: object) -> dict:
    if not isinstance(value, dict):
        return {"status": "absent"}
    status = value.get("status")
    if status in ("unavailable", "unstable"):
        return {"status": status}
    counts = ("pages", "main_pages", "wal_pages", "main_mismatches", "wal_mismatches")
    if (status != "verified" or any(type(value.get(k)) is not int or not 0 <= value[k] <= 10_000_000 for k in counts)
            or value["pages"] < 1 or value["main_pages"] + value["wal_pages"] != value["pages"]
            or value["main_mismatches"] > value["main_pages"] or value["wal_mismatches"] > value["wal_pages"]
            or type(value.get("header_equal")) is not bool or type(value.get("reserve")) is not int
            or value["reserve"] not in (48, 80)):
        return {"status": "invalid"}
    return {"status": "verified", **{k: value[k] for k in counts},
            "header_equal": value["header_equal"], "reserve": value["reserve"]}


def collect_integrity_probe(database: Path, initial_result: str, verification: object) -> None:
    """Run once, on a validated owned generation while its existing lease holds."""
    global _claimed, _pending
    if os.environ.get("ECHO_QQ_INTEGRITY_CHECK") != "1":
        return
    with _lock:
        if _claimed:
            return
        _claimed = True
    result = {"probe": "qq-integrity-1", "initial_check": initial_result if initial_result in ("ok", "failed", "error") else "unknown",
              "category": "unknown", "layout": {}, "page_verification": _page_verification(verification)}
    try:
        # A second real read-only check on the immutable generation. Never use
        # writable, immutable=1, recovery, VACUUM or a source database here.
        with database.open("rb") as stream:
            header = stream.read(100)
            size = os.fstat(stream.fileno()).st_size
        if len(header) == 100 and header[:16] == b"SQLite format 3\0":
            page_size = int.from_bytes(header[16:18], "big")
            page_size = 65536 if page_size == 1 else page_size
            if page_size >= 512 and page_size <= 65536 and page_size & (page_size - 1) == 0:
                header_pages = int.from_bytes(header[28:32], "big")
                result["layout"] = {"page_size": page_size, "reserve": header[20],
                    "read_version": header[19], "write_version": header[18],
                    "physical_pages": size // page_size, "whole_pages": size % page_size == 0,
                    "header_pages": header_pages, "header_count_authoritative": header_pages != 0 and header[24:28] == header[92:96],
                    "header_count_matches": header_pages == size // page_size,
                    "freelist_pages": int.from_bytes(header[36:40], "big"),
                    "schema_format": int.from_bytes(header[44:48], "big"),
                    "text_encoding": int.from_bytes(header[56:60], "big"),
                    "auto_vacuum": int.from_bytes(header[52:56], "big") != 0}
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
        try:
            row = connection.execute("PRAGMA quick_check(1)").fetchone()
            result["category"] = classify_integrity_result(row[0] if row else None)
            result["repeat_matches"] = (result["category"] == "ok") == (initial_result == "ok")
        finally:
            connection.close()
    except (OSError, sqlite3.DatabaseError):
        result["category"] = "check_error"
    except Exception:
        # Diagnostics cannot replace the original validation/cleanup outcome.
        result["category"] = "probe_error"
    with _lock:
        _pending = (database.parent, result)


def finish_integrity_probe(directory: Path, cleanup_completed: bool) -> None:
    """Publish the allowlisted result after cleanup; never overwrite a file."""
    global _pending
    with _lock:
        if _pending is None or _pending[0] != directory:
            return
        _, result = _pending
        _pending = None
    try:
        result["cleanup"] = "confirmed" if cleanup_completed and not directory.exists() else "not_confirmed"
        output = os.environ.get("ECHO_QQ_INTEGRITY_CHECK_OUTPUT")
        if output:
            # Exclusive create refuses existing files and symlinks. No directory
            # traversal, stdout, exception text or ordinary log export.
            with Path(output).open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(result, ensure_ascii=True, sort_keys=True) + "\n")
    except Exception:
        pass
