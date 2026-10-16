"""Audit regressions for QQ Direct DB acquisition."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from qq_chat_analyzer.providers.qq_database_provider import (
    QQDatabaseProvider,
    QQSession,
)


def _create_group_database_with_blob(path: Path, invalid_blob: object) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            '''
            CREATE TABLE group_msg_table (
                "40001" INTEGER PRIMARY KEY,
                "40027" TEXT NOT NULL,
                "40030" TEXT NOT NULL,
                "40033" TEXT NOT NULL,
                "40050" INTEGER NOT NULL,
                "40800"
            )
            '''
        )
        connection.executemany(
            '''
            INSERT INTO group_msg_table
                ("40001", "40027", "40030", "40033", "40050", "40800")
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            [
                (1, "group-key", "external-group", "sender", 1000, invalid_blob),
                (2, "group-key", "external-group", "sender", 2000, b"valid-blob"),
            ],
        )


@pytest.mark.parametrize("invalid_blob", [None, "sensitive-content", b""])
def test_materialize_session_skips_invalid_40800_rows(
    tmp_path: Path,
    invalid_blob: object,
) -> None:
    """NULL, TEXT, and empty BLOB 40800 values do not abort acquisition."""
    db_path = tmp_path / "invalid-blob.db"
    _create_group_database_with_blob(db_path, invalid_blob)
    session = QQSession(
        internal_key="group-key",
        session_object="external-group",
        display_name="external-group",
        session_type="group",
    )
    payload_path = tmp_path / "payload.json"

    with pytest.warns(RuntimeWarning, match="Skipped QQ DB record with invalid 40800"):
        QQDatabaseProvider(db_path).materialize_session_payload(session, payload_path)

    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert [record["record_id"] for record in payload["records"]] == ["2"]
    assert "sensitive-content" not in payload_path.read_text(encoding="utf-8")


def test_sqlite_failure_logs_privacy_safe_file_and_quick_check_diagnostics(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One failed read identifies the query point and snapshot health."""
    db_path = tmp_path / "snapshot.db"
    db_path.write_bytes(b"fictional-not-a-sqlite-database")
    (tmp_path / "snapshot.db-wal").write_bytes(b"fictional-wal")
    (tmp_path / "snapshot.db-shm").write_bytes(b"fictional-shm")

    with caplog.at_level(
        "WARNING",
        logger="qq_chat_analyzer.desktop.qq_database",
    ):
        with pytest.raises(sqlite3.DatabaseError):
            QQDatabaseProvider(db_path).list_sessions()

    diagnostic = caplog.text
    assert "operation=list_sessions" in diagnostic
    assert "table=group_msg_table" in diagnostic
    assert "stage=query" in diagnostic
    assert "database_name=snapshot.db" in diagnostic
    assert "header_valid=false" in diagnostic
    assert "wal_present=true" in diagnostic
    assert "shm_present=true" in diagnostic
    assert "quick_check=error" in diagnostic
    assert str(tmp_path) not in diagnostic
    assert "fictional-not-a-sqlite-database" not in diagnostic


@pytest.mark.parametrize('kind, category', [('missing', 'access'), ('corrupt', 'corrupt'), ('btree', 'integrity')])
def test_quick_check_distinguishes_access_from_corruption(tmp_path, caplog, kind, category):
    path = tmp_path / 'private-snapshot.db'
    if kind == 'corrupt':
        path.write_bytes(b'fictional private content, not SQLite')
    elif kind == 'btree':
        _create_group_database_with_blob(path, b'fictional')
        data = bytearray(path.read_bytes())
        # Inflate the freeblock count of the table leaf. It opens normally but
        # quick_check returns an integrity row rather than throwing an exception.
        page_size = int.from_bytes(data[16:18], 'big')
        data[page_size + 7] = 61
        path.write_bytes(data)
    with caplog.at_level('WARNING', logger='qq_chat_analyzer.desktop.qq_database'):
        assert QQDatabaseProvider.quick_check(path) != 'ok'
    assert f'category={category}' in caplog.text
    assert str(tmp_path) not in caplog.text
    assert 'private-snapshot' not in caplog.text
    assert 'fictional private content' not in caplog.text
