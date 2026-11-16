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


def scoped_names(group_database, profile_database, group, member_keys):
    """Read only the authorized group and explicit report UINs, never messages.

    Caller owns authenticated temporary DBs. Known NT columns: 60001 group code,
    60007 group name, 1000 UID, 1002 UIN, 64003 group card, 20002 nickname.
    Unknown remark fields are deliberately not interpreted.
    """
    from qq_chat_analyzer.identity_names import first_identity_name
    from qq_chat_analyzer.rich_message import SenderIdentity

    def positive(value):
        return (isinstance(value, str) and value.isascii() and value.isdecimal()
                and str(int(value)) == value and int(value) > 0)

    members = frozenset(member_keys)
    if not positive(group) or not 0 < len(members) <= 10000 or not all(map(positive, members)):
        raise SourceError("metadata_identity_scope_required")
    keys = sorted(members)
    marks = ",".join("?" for _ in keys)
    paths = [_safe(Path(path)) for path in (group_database, profile_database)]
    for path in paths:
        _file(path)

    def query(path, sql, values):
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            end = time.monotonic() + 10
            db.set_progress_handler(lambda: int(time.monotonic() >= end), 10000)
            rows = db.execute(sql + " LIMIT 20001", values).fetchall()
            if len(rows) > 20000:
                raise SourceError("metadata_scoped_row_limit")
            return rows

    profile_rows = {}
    uid_uins, uin_uids, profile_nicks = {}, {}, {}
    for table in ("profile_info_v2", "profile_info_v6"):
        rows = query(paths[1], f'SELECT "1002","1000","20002" FROM "{table}" '
                     f'WHERE CAST("1002" AS TEXT) IN ({marks})', keys)
        profile_rows[table] = len(rows)
        for raw, uid, nickname in rows:
            uin = str(raw)
            if uin not in members:
                raise SourceError("metadata_member_scope_mismatch")
            if isinstance(uid, str) and uid and uid != "0":
                uid_uins.setdefault(uid, set()).add(uin)
                uin_uids.setdefault(uin, set()).add(uid)
            if name := first_identity_name(nickname):
                profile_nicks.setdefault(uin, set()).add(name)

    safe_uids = sorted(uid_uins)
    predicate = f'CAST("1002" AS TEXT) IN ({marks})'
    if safe_uids:
        predicate += ' OR "1000" IN (' + ",".join("?" for _ in safe_uids) + ")"
    identity_rows = query(paths[0], 'SELECT "60001","1002","1000" '
                 'FROM group_member3 WHERE "60001"=? AND (' + predicate + ")",
                 [int(group), *keys, *safe_uids])
    # First collect all witnesses; never accept a row before later conflicts
    # in this same scoped selection have been considered.
    for selected_group, raw, uid in identity_rows:
        if str(selected_group) != group:
            raise SourceError("metadata_group_scope_mismatch")
        uin = str(raw) if raw is not None else ""
        if uin not in ("", "0") and uin not in members:
            # A known UID accompanied by another nonzero UIN is a conflict,
            # never permission to attach that row's name to a report member.
            if isinstance(uid, str) and uid in uid_uins:
                uid_uins[uid].add(uin)
        elif uin in members and isinstance(uid, str) and uid and uid != "0":
            uid_uins.setdefault(uid, set()).add(uin)
            uin_uids.setdefault(uin, set()).add(uid)
    conflicts = {u for values in uid_uins.values() if len(values) != 1 for u in values if u in members}
    conflicts |= {u for u, values in uin_uids.items() if len(values) != 1}
    eligible = sorted(members - conflicts)
    proven_uids = sorted(uid for uid, values in uid_uins.items()
                         if len(values) == 1 and values <= members - conflicts)
    clauses, parameters = [], [int(group)]
    if eligible:
        clauses.append('CAST("1002" AS TEXT) IN (' + ','.join('?' for _ in eligible) + ')')
        parameters.extend(eligible)
    if proven_uids:
        clauses.append('(("1002" IS NULL OR "1002"=0) AND "1000" IN ('
                       + ','.join('?' for _ in proven_uids) + '))')
        parameters.extend(proven_uids)
    rows = query(paths[0], 'SELECT "60001","1002","1000","64003","20002" '
                 'FROM group_member3 WHERE "60001"=? AND (' + ' OR '.join(clauses) + ')', parameters) if clauses else []
    cards, nicks, linked, direct, witnessed = {}, {}, set(), set(), set()
    refused = len(identity_rows) - len(rows)
    for selected_group, raw, uid, card, nickname in rows:
        uin = str(raw) if raw is not None else ""
        if uin not in ("", "0"):
            if uin not in members or uin in conflicts:
                refused += 1
                continue
            direct.add(uin)
        else:
            proof = uid_uins.get(uid, set())
            if len(proof) != 1 or proof & conflicts:
                refused += 1
                continue
            uin = next(iter(proof))
            if uin not in members:
                refused += 1
                continue
            witnessed.add(uin)
        linked.add(uin)
        for value, target in ((card, cards), (nickname, nicks)):
            if name := first_identity_name(value):
                target.setdefault(uin, set()).add(name)

    names = {}
    source_hits = {"group_card": 0, "group_nickname": 0, "profile_nickname": 0}
    ambiguous_names = set()
    for uin in members - conflicts:
        card_set, nick_set = cards.get(uin, set()), nicks.get(uin, set())
        if len(card_set) > 1 or len(nick_set) > 1:
            ambiguous_names.add(uin)
            continue
        card = next(iter(card_set), None)
        nickname = next(iter(nick_set), None)
        if nickname is None:
            candidates = profile_nicks.get(uin, set())
            if len(candidates) == 1:
                nickname = next(iter(candidates))
                source_hits["profile_nickname"] += 1
            elif len(candidates) > 1:
                ambiguous_names.add(uin)
        else:
            source_hits["group_nickname"] += 1
        if card:
            source_hits["group_card"] += 1
        if display := first_identity_name(card, nickname):
            names[uin] = SenderIdentity(uin, display, nickname=nickname, contextual_name=card)

    titles = set()
    title_rows = []
    for table in ("group_list", "group_detail_info_ver1"):
        selected = query(paths[0], f'SELECT "60001","60007" FROM "{table}" WHERE "60001"=?', [int(group)])
        if len(selected) > 1 or any(str(row[0]) != group for row in selected):
            raise SourceError("metadata_group_identity_ambiguous")
        title_rows.append(len(selected))
        titles.update(name for _, value in selected if (name := first_identity_name(value)))
    if len(titles) > 1:
        raise SourceError("metadata_group_name_conflict")
    summary = {"member_total": len(members), "profile_rows": profile_rows,
               "group_selected_rows": len(identity_rows), "group_linked_members": len(linked),
               "direct_uin_links": len(direct), "uid_witness_links": len(witnessed),
               "identity_conflict_members": len(conflicts), "rejected_group_rows": refused,
               "source_name_hits": source_hits, "remark_fields_verified": False,
               "named_members": len(names), "ambiguous_name_members": len(ambiguous_names),
               "missing_name_members": len(members - conflicts - names.keys()),
               "group_title_rows": title_rows, "group_name_available": bool(titles),
               "outside_group_name_rows_read": 0, "outside_report_profile_rows_read": 0}
    return names, next(iter(titles), None), summary


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
