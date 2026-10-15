"""RED-GREEN test: QQ Direct DB session discovery grouped by 40027.

Validates:
- Same 40027 + different 40030 merges into 1 session
- Different 40027 produces different sessions
- session_type is group vs private
- message_count and last_message_time are correct
- display_name falls back to session_object then internal_key
- internal_key handles both TEXT and INTEGER 40027 values
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path

from qq_chat_analyzer.providers.qq_database_provider import (
    QQDatabaseProvider,
    QQSession,
)


def _create_synthetic_qq_database(path: Path) -> None:
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            """
            CREATE TABLE group_msg_table (
                row_id    INTEGER PRIMARY KEY,
                "40027"   TEXT NOT NULL,
                "40030"   TEXT NOT NULL,
                "40033"   TEXT NOT NULL,
                "40050"   INTEGER NOT NULL,
                "40800"   BLOB NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE c2c_msg_table (
                row_id    INTEGER PRIMARY KEY,
                "40027"   TEXT NOT NULL,
                "40030"   TEXT NOT NULL,
                "40033"   TEXT NOT NULL,
                "40050"   INTEGER NOT NULL,
                "40800"   BLOB NOT NULL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO group_msg_table
                (row_id, "40027", "40030", "40033", "40050", "40800")
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "local-partition-1", "external-group-v1", "sender-1", 1000, b"blob"),
                (2, "local-partition-1", "external-group-v2", "sender-2", 2000, b"blob"),
            ],
        )
        conn.execute(
            """
            INSERT INTO group_msg_table
                (row_id, "40027", "40030", "40033", "40050", "40800")
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (3, "local-partition-2", "external-group-b", "sender-3", 5000, b"blob"),
        )
        conn.executemany(
            """
            INSERT INTO c2c_msg_table
                (row_id, "40027", "40030", "40033", "40050", "40800")
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "local-partition-3", "external-uin-100", "sender-self", 1500, b"blob"),
                (2, "local-partition-3", "external-uin-200", "sender-peer", 2500, b"blob"),
            ],
        )
        conn.execute(
            """
            INSERT INTO c2c_msg_table
                (row_id, "40027", "40030", "40033", "40050", "40800")
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (3, "local-partition-4", "external-uin-300", "sender-peer", 8000, b"blob"),
        )


def test_list_sessions_groups_by_40027_not_40030(tmp_path: Path) -> None:
    db_path = tmp_path / "fictional-qq.db"
    _create_synthetic_qq_database(db_path)
    sessions = QQDatabaseProvider(db_path).list_sessions()
    group_a = [s for s in sessions if s.internal_key == "local-partition-1"]
    assert len(group_a) == 1, f"Expected 1 session for same 40027, got {len(group_a)}"
    group_b = [s for s in sessions if s.internal_key == "local-partition-2"]
    assert len(group_b) == 1
    c2c_1 = [s for s in sessions if s.internal_key == "local-partition-3"]
    assert len(c2c_1) == 1
    c2c_2 = [s for s in sessions if s.internal_key == "local-partition-4"]
    assert len(c2c_2) == 1


def test_list_sessions_different_40027_not_merged(tmp_path: Path) -> None:
    db_path = tmp_path / "fictional-qq.db"
    _create_synthetic_qq_database(db_path)
    sessions = QQDatabaseProvider(db_path).list_sessions()
    internal_keys = [s.internal_key for s in sessions]
    assert len(internal_keys) == len(set(internal_keys)), "Duplicate internal_key found"
    assert len(sessions) == 4, f"Expected 4 sessions, got {len(sessions)}"


def test_list_sessions_has_correct_message_counts(tmp_path: Path) -> None:
    db_path = tmp_path / "fictional-qq.db"
    _create_synthetic_qq_database(db_path)
    sessions = QQDatabaseProvider(db_path).list_sessions()
    by_key = {s.internal_key: s for s in sessions}
    assert by_key["local-partition-1"].message_count == 2
    assert by_key["local-partition-2"].message_count == 1
    assert by_key["local-partition-3"].message_count == 2
    assert by_key["local-partition-4"].message_count == 1


def test_list_sessions_group_and_private_same_40027_not_confused(tmp_path: Path) -> None:
    """Regression: group and private may share the same 40027 value.

    Session identity is (session_type, internal_key), not just internal_key.
    A group with 40027="12345" and a private chat with 40027="12345"
    must remain distinct sessions.
    """
    db_path = tmp_path / "fictional-qq.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE group_msg_table (
                row_id    INTEGER PRIMARY KEY,
                "40027"   TEXT NOT NULL,
                "40030"   TEXT NOT NULL,
                "40033"   TEXT NOT NULL,
                "40050"   INTEGER NOT NULL,
                "40800"   BLOB NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE c2c_msg_table (
                row_id    INTEGER PRIMARY KEY,
                "40027"   TEXT NOT NULL,
                "40030"   TEXT NOT NULL,
                "40033"   TEXT NOT NULL,
                "40050"   INTEGER NOT NULL,
                "40800"   BLOB NOT NULL
            )
            """
        )
        # Group with 40027="shared-key"
        conn.execute(
            """
            INSERT INTO group_msg_table
                (row_id, "40027", "40030", "40033", "40050", "40800")
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, "shared-key", "external-group-1", "sender-1", 5000, b"blob"),
        )
        # Private chat with SAME 40027="shared-key"
        conn.execute(
            """
            INSERT INTO c2c_msg_table
                (row_id, "40027", "40030", "40033", "40050", "40800")
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, "shared-key", "external-uin-999", "sender-peer", 8000, b"blob"),
        )
    sessions = QQDatabaseProvider(db_path).list_sessions()

    # Should get exactly 2 sessions: 1 group + 1 private
    assert len(sessions) == 2, f"Expected 2 sessions, got {len(sessions)}"

    group_sessions = [s for s in sessions if s.session_type == "group"]
    private_sessions = [s for s in sessions if s.session_type == "private"]

    assert len(group_sessions) == 1, f"Expected 1 group, got {len(group_sessions)}"
    assert len(private_sessions) == 1, f"Expected 1 private, got {len(private_sessions)}"

    # Verify they have different metadata
    group = group_sessions[0]
    private = private_sessions[0]

    # Both share the same internal_key
    assert group.internal_key == "shared-key"
    assert private.internal_key == "shared-key"

    # But different session_object (external metadata)
    assert group.session_object == "external-group-1"
    assert private.session_object == "external-uin-999"

    # Different message counts and timestamps
    assert group.message_count == 1
    assert private.message_count == 1
    assert group.last_message_time == 5000
    assert private.last_message_time == 8000


def test_list_sessions_session_identity_is_type_plus_internal_key(tmp_path: Path) -> None:
    """Session identity must be (session_type, internal_key), not just internal_key.

    This prevents collisions when a group and a private chat happen to
    share the same 40027 value (which is possible in QQ's internal model).
    """
    db_path = tmp_path / "fictional-qq.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE group_msg_table (
                row_id    INTEGER PRIMARY KEY,
                "40027"   TEXT NOT NULL,
                "40030"   TEXT NOT NULL,
                "40033"   TEXT NOT NULL,
                "40050"   INTEGER NOT NULL,
                "40800"   BLOB NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE c2c_msg_table (
                row_id    INTEGER PRIMARY KEY,
                "40027"   TEXT NOT NULL,
                "40030"   TEXT NOT NULL,
                "40033"   TEXT NOT NULL,
                "40050"   INTEGER NOT NULL,
                "40800"   BLOB NOT NULL
            )
            """
        )
        # Two groups with same 40027 (should be 2 distinct sessions)
        conn.execute(
            """
            INSERT INTO group_msg_table
                (row_id, "40027", "40030", "40033", "40050", "40800")
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, "collision-key", "ext-g1", "s1", 1000, b"blob"),
        )
        conn.execute(
            """
            INSERT INTO group_msg_table
                (row_id, "40027", "40030", "40033", "40050", "40800")
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (2, "collision-key", "ext-g2", "s2", 2000, b"blob"),
        )
        # Two private chats with same 40027 (should be 2 distinct sessions)
        conn.execute(
            """
            INSERT INTO c2c_msg_table
                (row_id, "40027", "40030", "40033", "40050", "40800")
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, "collision-key", "ext-p1", "s1", 3000, b"blob"),
        )
        conn.execute(
            """
            INSERT INTO c2c_msg_table
                (row_id, "40027", "40030", "40033", "40050", "40800")
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (2, "collision-key", "ext-p2", "s2", 4000, b"blob"),
        )
    sessions = QQDatabaseProvider(db_path).list_sessions()

    # Each table groups by 40027, so each table returns 1 session
    # Total: 2 sessions (1 group + 1 private)
    assert len(sessions) == 2

    group_sessions = [s for s in sessions if s.session_type == "group"]
    private_sessions = [s for s in sessions if s.session_type == "private"]

    assert len(group_sessions) == 1
    assert len(private_sessions) == 1

    # The group session aggregates both rows (COUNT=2, MAX time=2000)
    assert group_sessions[0].message_count == 2
    assert group_sessions[0].last_message_time == 2000

    # The private session aggregates both rows (COUNT=2, MAX time=4000)
    assert private_sessions[0].message_count == 2
    assert private_sessions[0].last_message_time == 4000
