"""Names from authenticated, account-scoped QQ metadata databases."""
from contextlib import closing
from pathlib import Path
import sqlite3,time
from .files import SourceError,_safe,_file

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
    if (group is not None and not positive(group)) or len(members) > 10000 or not all(map(positive, members)):
        raise SourceError("metadata_identity_scope_required")
    keys = sorted(members)
    marks = ",".join("?" for _ in keys)
    paths = [_safe(Path(path)) for path in (group_database, profile_database)]
    for path in paths:
        _file(path)

    def query(path, sql, values, *, table, columns):
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            db.execute("PRAGMA trusted_schema=OFF")
            end = time.monotonic() + 10
            db.set_progress_handler(lambda: int(time.monotonic() >= end), 10000)
            # Name caches are optional. Inspect only the fixed requested table;
            # absent fields must never become SQLite quoted string literals.
            present = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
            if not set(columns) <= present:
                return []
            rows = db.execute(sql + " LIMIT 20001", values).fetchall()
            if len(rows) > 20000:
                raise SourceError("metadata_scoped_row_limit")
            return rows

    profile_rows = {}
    uid_uins, uin_uids, profile_nicks = {}, {}, {}
    for table in ("profile_info_v2", "profile_info_v6"):
        rows = query(paths[1], f'SELECT "1002","1000","20002" FROM "{table}" '
                     f'WHERE CAST("1002" AS TEXT) IN ({marks})', keys,
                     table=table, columns=('1002','1000','20002'))
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
                 [int(group), *keys, *safe_uids], table='group_member3',
                 columns=('60001','1002','1000')) if group is not None and members else []
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
    clauses, parameters = [], [int(group)] if group is not None else []
    if eligible and group is not None:
        clauses.append('CAST("1002" AS TEXT) IN (' + ','.join('?' for _ in eligible) + ')')
        parameters.extend(eligible)
    if proven_uids and group is not None:
        clauses.append('(("1002" IS NULL OR "1002"=0) AND "1000" IN ('
                       + ','.join('?' for _ in proven_uids) + '))')
        parameters.extend(proven_uids)
    rows = query(paths[0], 'SELECT "60001","1002","1000","64003","20002" '
                 'FROM group_member3 WHERE "60001"=? AND (' + ' OR '.join(clauses) + ')', parameters,
                 table='group_member3', columns=('60001','1002','1000','64003','20002')) if clauses else []
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
    for table in (("group_list", "group_detail_info_ver1") if group is not None else ()):
        selected = query(paths[0], f'SELECT "60001","60007" FROM "{table}" WHERE "60001"=?', [int(group)],
                         table=table, columns=('60001','60007'))
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
