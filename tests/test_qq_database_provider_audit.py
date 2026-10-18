"""Audit regressions for QQ Direct DB acquisition."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock

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
    if kind == 'btree' and sqlite3.sqlite_version == '3.50.4':
        assert 'integrity_kind=btree' in caplog.text
    assert str(tmp_path) not in caplog.text
    assert 'private-snapshot' not in caplog.text
    assert 'fictional private content' not in caplog.text


@pytest.mark.parametrize("message, kind", [
    ("*** in database main ***\nFragmentation of 0 bytes reported as 61 on page 2", "btree"),
    ("*** in database main ***\nTree 2 page 2 cell 0: overflow list length is 1 but should be 3", "overflow"),
    ("*** in database main ***\nFreelist: size is 3 but should be 4", "freelist"),
    ("*** in database main ***\nPage 7: never used", "page_reference"),
    ("NULL value in PRIVATE_TABLE.PRIVATE_COLUMN", "constraint"),
    ("unable to validate the inverted index for FTS4 table main.PRIVATE_TABLE: SQL logic error", "virtual_table"),
    ("PRIVATE_PATH/overflow btree rowid=123", "unknown"),
    ("unable to validate the inverted index for FTS4 table main.PRIVATE_TABLE: SQL logic error\nPRIVATE_CONTEXT", "unknown"),
])
def test_quick_check_logs_only_fixed_classification(tmp_path, monkeypatch, caplog, message, kind):
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = (message,)
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: connection)
    monkeypatch.setattr(sqlite3, "sqlite_version", "3.50.4")

    with caplog.at_level("WARNING", logger="qq_chat_analyzer.desktop.qq_database"):
        assert QQDatabaseProvider.quick_check(tmp_path / "PRIVATE_PATH.db") == "failed"

    assert [record.getMessage() for record in caplog.records] == [
        "QQ snapshot quick_check result=failed category=integrity "
        f"integrity_kind={kind} sqlite_version=3.50.4 classifier_version=1"
    ]
    assert not any(record.exc_info or record.stack_info for record in caplog.records)
    connection.execute.assert_called_once_with("PRAGMA quick_check(1)")
    connection.close.assert_called_once()


def test_quick_check_unknown_versions_and_private_exception_stay_closed(tmp_path, monkeypatch, caplog):
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = (
        "unable to validate the inverted index for FTS4 table main.PRIVATE_TABLE: SQL logic error",
    )
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: connection)
    for version, safe_version in [("3.54.1", "3.54.1"), ("PRIVATE_PATH", "unknown")]:
        caplog.clear()
        monkeypatch.setattr(sqlite3, "sqlite_version", version)
        assert QQDatabaseProvider.quick_check(tmp_path / "PRIVATE_PATH.db") == "failed"
        assert f"integrity_kind=unknown sqlite_version={safe_version}" in caplog.text
        assert "PRIVATE" not in caplog.text
    caplog.clear()
    connection.execute.side_effect = sqlite3.DatabaseError("PRIVATE_PATH/PRIVATE_TABLE rowid=123")
    assert QQDatabaseProvider.quick_check(tmp_path / "PRIVATE_PATH.db") == "error"
    assert "category=sqlite sqlite_errorcode=0 sqlite_version=unknown" in caplog.text
    assert "PRIVATE" not in caplog.text and "rowid" not in caplog.text


@pytest.mark.skipif(sqlite3.sqlite_version != "3.50.4", reason="Upstream false positive reproduced on 3.50.4")
def test_contentless_fts4_is_classified_but_still_rejected_by_facade(tmp_path, caplog):
    from qq_direct_db_testing import FakeSnapshotRuntime
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, ChatSource, FacadeError
    from qq_chat_analyzer.application.qq.qq_direct_database_import_service import QQDirectDatabaseImportService

    path = tmp_path / "PRIVATE_PATH.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE VIRTUAL TABLE PRIVATE_TABLE USING fts4(body, content='')")
        connection.execute("INSERT INTO PRIVATE_TABLE(rowid,body) VALUES(1,'PRIVATE_CONTENT')")
        connection.commit()
        assert connection.execute(
            "SELECT rowid FROM PRIVATE_TABLE WHERE PRIVATE_TABLE MATCH 'PRIVATE_CONTENT'"
        ).fetchall() == [(1,)]
    before = path.read_bytes()
    runtime = FakeSnapshotRuntime(tmp_path / "runtime", snapshot_path=path)
    facade = ChatAnalyzerFacade(qq_service=QQDirectDatabaseImportService(runtime_client=runtime))
    with caplog.at_level("INFO"), pytest.raises(FacadeError) as caught:
        facade.list_sessions(ChatSource.QQ)
    assert caught.value.code == "qq_direct_snapshot_invalid"
    assert "integrity_kind=virtual_table sqlite_version=3.50.4 classifier_version=1" in caplog.text
    assert "PRIVATE" not in caplog.text and "PRIVATE" not in caught.value.public_message
    assert runtime.cleaned == runtime.acquired
    assert not any((runtime.root / "generations").glob("*"))
    assert path.read_bytes() == before
