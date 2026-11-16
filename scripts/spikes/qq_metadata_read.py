"""Restricted research staging; no discovery, value queries or name inference.

The existing runner owns the Job and TemporaryDirectory. After independent MAC
verification, expose ONLY SQLite schema to the operator. Its bounded review
window allows a source-specific, authorized-group query after the schema is
understood. Completion, cancellation, failure and timeout all leave the outer
owner responsible for removing plaintext; no key crosses this boundary.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

from qq_full_read import validate_prepared
from qq_windows_source import SourceError, _safe, _file

OWNER = {"kind": "echo-qq-metadata-experiment", "version": 1}
ROLES = ("group_info", "profile_info")
TOTAL_SECONDS = 1800
REVIEW_SECONDS = 1200


def selection(path):
    path = _safe(Path(path))
    _file(path)
    root = path.parent
    _file(root / "owner.json")
    if path.name != "selection.json" or json.loads((root / "owner.json").read_text()) != OWNER:
        raise SourceError("owned_metadata_selection_required")
    value = json.loads(path.read_text(encoding="ascii"))
    if value.get("kind") != OWNER["kind"] or value.get("version") != 1:
        raise SourceError("metadata_selection_refused")
    if not all(isinstance(value.get(key), str) and value[key].isascii() and value[key].isdecimal()
               and str(int(value[key])) == value[key] and int(value[key]) > 0 for key in ("account", "group")):
        raise SourceError("metadata_authorization_required")
    if value.get("account_scope_verified") is not True:
        raise SourceError("metadata_account_scope_unproven")
    sources = value.get("sources")
    if not isinstance(sources, list) or len(sources) != 2:
        raise SourceError("metadata_selection_refused")
    for item, role in zip(sources, ROLES, strict=True):
        if item.get("role") != role:
            raise SourceError("metadata_selection_refused")
        frozen = _safe(Path(item["path"]))
        if frozen.parent.parent != root:
            raise SourceError("metadata_owned_snapshot_required")
        manifest = validate_prepared(frozen, item["sha256"])
        if manifest["size"] != item["size"] or item["size"] > 32 * 1024**2:
            raise SourceError("metadata_snapshot_limit")
    if len({item["path"] for item in sources}) != 2:
        raise SourceError("metadata_selection_refused")
    anchor = value["anchor"]
    validate_prepared(anchor["path"], anchor["sha256"])
    report = _safe(Path(value["report_json"]))
    _file(report)
    with report.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != value["report_sha256"]:
            raise SourceError("metadata_report_changed")
    return value


def schema_inventory(path):
    """Read no table values, default expressions, index SQL or chat content."""
    path = _safe(Path(path))
    _file(path)
    end = time.monotonic() + 15
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.set_progress_handler(lambda: int(time.monotonic() >= end), 10000)
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise SourceError("metadata_sqlite_integrity_failed")
        tables = connection.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name LIMIT 65").fetchall()
        if len(tables) > 64:
            raise SourceError("metadata_schema_limit")
        result = []
        for index, (name,) in enumerate(tables):
            quoted = '"' + name.replace('"', '""') + '"'
            columns = connection.execute("PRAGMA table_xinfo(" + quoted + ")").fetchall()
            if len(columns) > 256:
                raise SourceError("metadata_schema_limit")
            # Real names are retained only in the private workspace for exact
            # identifier selection. Public schema summaries must redact long IDs.
            result.append({"table_index": index, "name": name,
                           "columns": [{"index": row[0], "name": row[1], "type": row[2],
                                        "not_null": bool(row[3]), "primary_key": row[5]}
                                       for row in columns]})
    return result


def safe_schema(inventory):
    def label(value):
        if not re.fullmatch(r"[A-Za-z_0-9]+", value):
            return "<nonstatic_identifier>"
        value = re.sub(r"(?:^|_)u_[A-Za-z0-9_]{12,}", "_<identifier>", value)
        value = re.sub(r"[A-Za-z0-9]{24,}", "<identifier>", value)
        return re.sub(r"[0-9]{7,}", "<identifier>", value)
    return [{**table, "name": label(table["name"]), "columns": [
        {**column, "name": label(column["name"]), "type": label(column["type"])}
        for column in table["columns"]]} for table in inventory]


from qq_chat_analyzer.providers.qq_independent.metadata import scoped_names

def review(value, plaintext, emit, cancelled):
    """No DB values are read automatically; never treat schema as identity proof."""
    root = Path(value["selection_path"]).parent
    inventories = {}
    for role, path in zip(ROLES, plaintext, strict=True):
        inventories[role] = schema_inventory(path)
        emit({"phase": "metadata_sqlite_check", "role": role, "integrity_ok": True,
              "table_count": len(inventories[role]), "metadata_value_rows_read": 0})
    private = Path(plaintext[0]).parent / "metadata-schema.json"
    private.write_text(json.dumps(inventories, ensure_ascii=True), encoding="ascii")
    (root / "schema-summary.json").write_text(json.dumps({role: safe_schema(items)
        for role, items in inventories.items()}, ensure_ascii=True), encoding="ascii")
    ready = root / "review-ready.json"
    ready.write_text(json.dumps({"plaintext": dict(zip(ROLES, map(str, plaintext), strict=True)),
        "schema": str(private), "metadata_value_rows_read": 0}), encoding="ascii")
    emit({"phase": "metadata_schema_ready", "databases_verified": 2,
          "metadata_value_rows_read": 0, "review_budget_seconds": REVIEW_SECONDS})
    complete = root / "review-complete.json"
    end = time.monotonic() + REVIEW_SECONDS
    try:
        while not complete.exists():
            if cancelled():
                raise SourceError("metadata_review_cancelled")
            if time.monotonic() >= end:
                raise SourceError("metadata_review_deadline")
            time.sleep(0.1)
        _safe(complete); _file(complete)
        outcome = json.loads(complete.read_text(encoding="ascii"))
        # The reviewer's bounded receipt is separate from any private name map.
        if outcome.get("state") != "verified":
            raise SourceError("metadata_mapping_not_verified")
        if outcome.get("all_identity_checks_passed") is not True or outcome.get("report_invariants_verified") is not True:
            raise SourceError("metadata_acceptance_unproven")
        emit({"phase": "metadata_result", "state": "verified",
              "report_generated": outcome.get("report_generated") is True})
    finally:
        ready.unlink(missing_ok=True)
