"""Fictional scoped NT metadata: direct IDs, UID witnesses and fail-closed conflicts."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

from qq_metadata_read import scoped_names
from qq_windows_source import SourceError

def main():
    with tempfile.TemporaryDirectory(prefix="qq-names-fixture-", dir=Path(sys.argv[1])) as owned:
        root = Path(owned)
        group, profile = root / "group.db", root / "profile.db"
        with closing(sqlite3.connect(group)) as db:
            db.executescript('''
                CREATE TABLE group_list ("60001" INTEGER,"60007" TEXT);
                CREATE TABLE group_detail_info_ver1 ("60001" INTEGER,"60007" TEXT);
                CREATE TABLE group_member3 ("60001" INTEGER,"1002" INTEGER,"1000" TEXT,"64003" TEXT,"20002" TEXT);
                INSERT INTO group_list VALUES(900000001,'Fictional group');
                INSERT INTO group_detail_info_ver1 VALUES(900000001,'Fictional group');
            ''')
            db.executemany('INSERT INTO group_member3 VALUES(?,?,?,?,?)', [
                (900000001,100000001,"uid-a","Card A","Nick A"),
                (900000001,0,"uid-b","Card B","Nick B"),
                (900000001,100000003,"uid-c","0",""),
                (900000002,100000001,"uid-a","OTHER_GROUP_SENTINEL","OTHER_GROUP_SENTINEL"),
                (900000001,999999999,"uid-other","OTHER_MEMBER_SENTINEL","OTHER_MEMBER_SENTINEL"),
            ]); db.commit()
        with closing(sqlite3.connect(profile)) as db:
            for table in ("profile_info_v2","profile_info_v6"):
                db.execute(f'CREATE TABLE {table} ("1002" INTEGER,"1000" TEXT,"20002" TEXT)')
                db.executemany(f'INSERT INTO {table} VALUES(?,?,?)', [
                    (100000001,"uid-a","Profile A"),(100000002,"uid-b","Profile B"),
                    (100000003,"uid-c","Profile C"),(999999999,"uid-other","OTHER_PROFILE_SENTINEL"),
                ])
            db.commit()
        members = {"100000001","100000002","100000003"}
        names, title, counts = scoped_names(group, profile, "900000001", members)
        assert title == "Fictional group" and set(names) == members
        assert names["100000001"].contextual_name == "Card A"
        assert names["100000002"].nickname == "Nick B" and counts["uid_witness_links"] == 1
        assert names["100000003"].nickname == "Profile C"
        assert counts["source_name_hits"] == {"group_card":2,"group_nickname":2,"profile_nickname":1}
        assert all("SENTINEL" not in repr(value) for value in names.values())
        assert counts["outside_group_name_rows_read"] == counts["outside_report_profile_rows_read"] == 0
        # A conflicting nonzero UIN cannot be reconciled using an otherwise-known UID.
        with closing(sqlite3.connect(group)) as db:
            db.execute('INSERT INTO group_member3 VALUES(?,?,?,?,?)',
                       (900000001,999999998,"uid-b","BAD_CARD","BAD_NICK")); db.commit()
        names, _, counts = scoped_names(group, profile, "900000001", members)
        assert "100000002" not in names and counts["identity_conflict_members"] == 1
        assert counts["rejected_group_rows"] == 2
        # The same UIN accompanied by multiple UIDs is also withheld, regardless
        # of agreeing names or a direct group UIN match.
        with closing(sqlite3.connect(profile)) as db:
            db.execute('INSERT INTO profile_info_v6 VALUES(?,?,?)',(100000001,"uid-new","Profile A")); db.commit()
        names, _, counts = scoped_names(group, profile, "900000001", members)
        assert set(names) == {"100000003"} and counts["identity_conflict_members"] == 2
        # Unknown UID does not become a member. Duplicate card evidence is not
        # resolved by row order, and inconsistent group titles stop acceptance.
        with closing(sqlite3.connect(group)) as db:
            db.execute('INSERT INTO group_member3 VALUES(?,?,?,?,?)',(900000001,0,"uid-unknown","BAD","BAD"))
            db.execute('INSERT INTO group_member3 VALUES(?,?,?,?,?)',(900000001,100000003,"uid-c","Conflicting A","Nick"))
            db.execute('INSERT INTO group_member3 VALUES(?,?,?,?,?)',(900000001,100000003,"uid-c","Conflicting B","Nick"))
            db.commit()
        names, _, counts = scoped_names(group, profile, "900000001", members)
        assert not names and counts["ambiguous_name_members"] == 1
        for value in ("0","-1","900000001 OR 1=1"):
            try: scoped_names(group, profile, value, members)
            except SourceError as error: assert error.code == "metadata_identity_scope_required"
            else: raise AssertionError("invalid scope accepted")
        with closing(sqlite3.connect(group)) as db:
            db.execute('UPDATE group_list SET "60007"=?',("Different title",)); db.commit()
        try: scoped_names(group, profile, "900000001", members)
        except SourceError as error: assert error.code == "metadata_group_name_conflict"
        else: raise AssertionError("title conflict accepted")
    assert not root.exists()
    print(json.dumps({"fictional_scoped_metadata_checks":"passed","identity_conflicts_withheld":True,
                      "other_groups_and_members_excluded":True,"real_qq_accessed":False}))

if __name__ == "__main__":
    main()

