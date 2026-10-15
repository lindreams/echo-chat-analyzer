"""Synthetic end-to-end import coverage for the QQ Direct DB slice."""

from __future__ import annotations

import json
import sqlite3

from qq_db_test_data import synthetic_text_message_blob as _synthetic_text_message_blob

from qq_chat_analyzer.application.import_request import ImportRequest
from qq_chat_analyzer.application.import_service import ImportService
from qq_chat_analyzer.providers.qq_database_provider import QQDatabaseProvider
from qq_chat_analyzer.providers.qq_database_provider import QQSession


def _create_session_database(database_path) -> None:
    with sqlite3.connect(database_path) as connection:
        for table_name in ("group_msg_table", "c2c_msg_table"):
            connection.execute(
                f'''
                CREATE TABLE {table_name} (
                    "40001" INTEGER PRIMARY KEY,
                    "40027" TEXT NOT NULL,
                    "40030" TEXT NOT NULL,
                    "40033" TEXT NOT NULL,
                    "40050" INTEGER NOT NULL,
                    "40800" BLOB NOT NULL
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
                (101, "17", "group-77", "group-sender", 1760000001, _synthetic_text_message_blob("group first")),
                (102, "17", "0", "group-sender-zero", 1760000002, _synthetic_text_message_blob("group zero record")),
                (103, "17", "0", "group-broken", 1760000003, b"not-a-supported-message"),
            ],
        )
        connection.executemany(
            '''
            INSERT INTO c2c_msg_table
                ("40001", "40027", "40030", "40033", "40050", "40800")
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            [
                (201, "17", "private-88", "private-sender", 1760000011, _synthetic_text_message_blob("private first")),
                (202, "17", "0", "private-sender-zero", 1760000012, _synthetic_text_message_blob("private zero record")),
                (203, "17", "0", "private-broken", 1760000013, b"not-a-supported-message"),
            ],
        )


def test_session_payload_import_preserves_session_identity_for_group_and_private(
    tmp_path,
) -> None:
    database_path = tmp_path / "fictional-session-qq.db"
    _create_session_database(database_path)
    provider = QQDatabaseProvider(database_path)
    sessions = {session.session_type: session for session in provider.list_sessions()}

    for session_type, session_object, sender, timestamp, text in (
        ("group", "group-77", "group-sender", 1760000001, "group first"),
        ("private", "private-88", "private-sender", 1760000011, "private first"),
    ):
        session = sessions[session_type]
        assert session.internal_key == "17"
        assert session.session_object == session_object

        payload_path = tmp_path / f"{session_type}.json"
        provider.materialize_session_payload(session, payload_path)
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        assert payload["query"]["session_type"] == session_type
        assert payload["query"]["internal_key"] == "17"
        assert payload["query"]["session_object"] == session_object
        outcome = ImportService().execute(
            ImportRequest(input_path=payload_path, platform="qq")
        )

        assert outcome.processed_message_count == 3
        assert len(outcome.rich_messages) == 2
        assert len(outcome.messages) == 2
        assert outcome.result.warnings == ("qq_db_record_skipped",)
        for rich, chat in zip(outcome.rich_messages, outcome.messages, strict=True):
            assert rich.conversation_type == session_type
            assert rich.conversation_id == session_object
            assert chat.conversation_type == session_type
            assert chat.conversation_id == session_object

        rich = outcome.rich_messages[0]
        chat = outcome.messages[0]
        assert rich.sender.identity_id == sender
        assert rich.timestamp == timestamp
        assert rich.contents[0].text == text
        assert chat.sender_id == sender
        assert chat.timestamp == timestamp
        assert chat.text == text


def test_session_payload_import_falls_back_to_type_and_internal_key_when_40030_is_zero(
    tmp_path,
) -> None:
    database_path = tmp_path / "fictional-zero-session-qq.db"
    with sqlite3.connect(database_path) as connection:
        for table_name in ("group_msg_table", "c2c_msg_table"):
            connection.execute(
                f'''
                CREATE TABLE {table_name} (
                    "40001" INTEGER PRIMARY KEY,
                    "40027" TEXT NOT NULL,
                    "40030" TEXT NOT NULL,
                    "40033" TEXT NOT NULL,
                    "40050" INTEGER NOT NULL,
                    "40800" BLOB NOT NULL
                )
                '''
            )
        connection.execute(
            '''
            INSERT INTO group_msg_table
                ("40001", "40027", "40030", "40033", "40050", "40800")
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (301, "17", "0", "group-sender", 1760000021, _synthetic_text_message_blob("group fallback")),
        )
        connection.execute(
            '''
            INSERT INTO c2c_msg_table
                ("40001", "40027", "40030", "40033", "40050", "40800")
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (401, "17", "0", "private-sender", 1760000031, _synthetic_text_message_blob("private fallback")),
        )

    provider = QQDatabaseProvider(database_path)
    sessions = {session.session_type: session for session in provider.list_sessions()}
    for session_type in ("group", "private"):
        session = sessions[session_type]
        assert session.session_object == ""
        payload_path = tmp_path / f"{session_type}-fallback.json"
        provider.materialize_session_payload(session, payload_path)
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        assert payload["query"]["session_type"] == session_type
        assert payload["query"]["internal_key"] == "17"
        assert payload["query"]["session_object"] is None

        outcome = ImportService().execute(
            ImportRequest(input_path=payload_path, platform="qq")
        )

        expected_conversation_id = f"{session_type}:17"
        assert outcome.rich_messages[0].conversation_type == session_type
        assert outcome.rich_messages[0].conversation_id == expected_conversation_id
        assert outcome.messages[0].conversation_type == session_type
        assert outcome.messages[0].conversation_id == expected_conversation_id
