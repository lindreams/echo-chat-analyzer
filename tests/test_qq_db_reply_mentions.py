"""A6.2 regressions shaped like the verified client, with fictional data only."""

from __future__ import annotations

import base64
import json
import sqlite3

import pytest

from qq_chat_analyzer.analysis.analyzers.expression_analyzer import ExpressionAnalyzer
from qq_chat_analyzer.application.import_request import ImportRequest
from qq_chat_analyzer.application.import_service import ImportService
from qq_chat_analyzer.legacy_projection import project_legacy_messages
from qq_chat_analyzer.providers.qq_database_provider import QQDatabaseProvider, QQSession
from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages
from qq_chat_analyzer.rich_message import ExpressionContent, MentionRelation, ReplyRelation, TextContent


def _varint(n: int) -> bytes:
    result = bytearray()
    while n > 127:
        result.append((n & 127) | 128)
        n >>= 7
    result.append(n)
    return bytes(result)


def _scalar(tag: int, n: int) -> bytes:
    return _varint(tag << 3) + _varint(n)


def _bytes(tag: int, value: bytes) -> bytes:
    return _varint((tag << 3) | 2) + _varint(len(value)) + value


def _text(value: str) -> bytes:
    return _scalar(45002, 1) + _bytes(45101, value.encode()) + _scalar(45102, 0)


def _mention(label: str = "@Fictional display") -> bytes:
    return (
        _scalar(45002, 1) + _bytes(45101, label.encode())
        + _scalar(45102, 2) + _bytes(45105, b"fictional-nt-uid")
    )


def _reply(seq: int = 42) -> bytes:
    return (
        _scalar(45002, 7) + _scalar(47402, seq)
        + _scalar(47404, 100) + _bytes(40020, b"fictional-nt-uid")
        + _bytes(47423, b"opaque fictional bytes: never authored text")
    )


def _record(identifier: str, seq, *segments: bytes, key: str = "fictional-key") -> dict:
    return {
        "record_id": identifier,
        "fields": {"40003": seq, "40027": key, "40030": "fictional-room",
                   "40033": "fictional-sender", "40050": 100},
        "blob_encoding": "base64",
        "message_blob": base64.b64encode(b"".join(_bytes(40800, s) for s in segments)).decode(),
        "source_meta": {"table": "group_msg_table"},
    }


def _payload(*records: dict, session_type: str = "group") -> dict:
    return {
        "format": "qq-db-json", "format_version": 0,
        "source": "qq", "source_type": "qq-db-json",
        "query": {"session_type": session_type, "internal_key": "fictional-key",
                  "session_object": "fictional-room"},
        "records": list(records),
    }


@pytest.mark.parametrize("segments,expected_relations", [
    ((_reply(), _mention(), _text("answer")), (ReplyRelation("target"), MentionRelation(None, "@Fictional display"))),
    ((_reply(), _text("answer")), (ReplyRelation("target"),)),
    ((_mention(), _text("answer")), (MentionRelation(None, "@Fictional display"),)),
])
def test_reply_and_mentions_preserve_facts_without_polluting_authored_text(segments, expected_relations) -> None:
    messages, warnings = parse_qq_db_rich_messages(_payload(
        _record("target", 42, _text("original")),
        _record("current", 43, *segments),
    ))
    assert warnings == ()
    assert len(messages) == 2
    assert messages[1].contents == (TextContent("answer"),)
    assert messages[1].relations == expected_relations
    assert project_legacy_messages(messages)[1].text == "answer"


@pytest.mark.parametrize("target_records", [
    [],
    [_record("target", 42, _text("original")), _record("duplicate", 42, _text("duplicate"))],
    [_record("foreign", 42, _text("foreign"), key="other-key")],
    [_record("missing-sequence", None, _text("original"))],
])
def test_missing_duplicate_foreign_or_absent_sequence_targets_stay_unresolved(target_records) -> None:
    messages, warnings = parse_qq_db_rich_messages(_payload(
        *target_records, _record("current", 43, _reply(), _text("answer")),
    ))
    assert warnings == ()
    assert messages[-1].relations == ()
    assert messages[-1].contents == (TextContent("answer"),)


def test_foreign_reply_record_cannot_use_current_session_index() -> None:
    messages, _ = parse_qq_db_rich_messages(_payload(
        _record("target", 42, _text("original")),
        _record("foreign-reply", 43, _reply(), _text("answer"), key="other-key"),
    ))
    assert messages[-1].relations == ()


def test_private_reply_does_not_map_group_sequence() -> None:
    records = [_record("target", 42, _text("original")), _record("current", 43, _reply(), _mention(), _text("answer"))]
    for record in records:
        record["source_meta"]["table"] = "c2c_msg_table"
    messages, _ = parse_qq_db_rich_messages(_payload(*records, session_type="private"))
    assert messages[-1].relations == (MentionRelation(None, "@Fictional display"),)
    assert project_legacy_messages(messages)[-1].text == "answer"


@pytest.mark.parametrize("segments", [(_reply(),), (_mention(),), (_reply(), _mention())])
def test_relation_only_messages_are_not_dropped(segments) -> None:
    messages, warnings = parse_qq_db_rich_messages(_payload(_record("current", 43, *segments)))
    assert warnings == ()
    assert len(messages) == 1
    assert messages[0].contents == ()
    assert project_legacy_messages(messages)[0].text == ""


def test_mention_display_emoji_does_not_enter_expression_report() -> None:
    messages, warnings = parse_qq_db_rich_messages(_payload(
        _record("current", 43, _mention("@Fictional 🦊"), _text("answer 😂")),
    ))
    assert warnings == ()
    report = ExpressionAnalyzer().analyze(project_legacy_messages(messages), messages)
    assert report.expression_occurrence_count == 1
    assert report.top_expressions[0].expression_key == "😂"


def _create_database(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE group_msg_table ("40001" INTEGER PRIMARY KEY, "40003" INTEGER, "40027" TEXT, "40030" TEXT, "40033" TEXT, "40050" INTEGER, "40800" BLOB)')
        records = [_record("1", 42, _text("original")), _record("2", 43, _reply(), _mention(), _text("answer"))]
        connection.executemany('INSERT INTO group_msg_table VALUES (?, ?, ?, ?, ?, ?, ?)', [
            (int(r["record_id"]), r["fields"]["40003"], "fictional-key", "fictional-room", "fictional-sender", time, base64.b64decode(r["message_blob"]))
            for r, time in zip(records, (100, 200), strict=True)
        ])


@pytest.mark.parametrize("session_path", [False, True])
def test_provider_import_rich_relations_and_legacy_chain(tmp_path, session_path) -> None:
    database = tmp_path / "fictional.db"
    _create_database(database)
    before = database.read_bytes()
    provider = QQDatabaseProvider(database)
    path = tmp_path / "fictional.json"
    if session_path:
        provider.materialize_session_payload(QQSession("fictional-key", "fictional-room", "fictional name", "group"), path)
    else:
        provider.materialize_group_payload("fictional-room", path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert [r["fields"]["40003"] for r in payload["records"]] == [42, 43]
    assert database.read_bytes() == before
    outcome = ImportService().execute(ImportRequest(input_path=path, platform="qq"))
    assert outcome.result.warnings == ()
    assert len(outcome.messages) == len(outcome.rich_messages) == 2
    assert outcome.rich_messages[-1].relations == (ReplyRelation("1"), MentionRelation(None, "@Fictional display"))
    assert outcome.messages[-1].text == "answer"


def test_target_outside_provider_time_range_is_not_resolved(tmp_path) -> None:
    database = tmp_path / "fictional.db"
    _create_database(database)
    path = tmp_path / "fictional.json"
    QQDatabaseProvider(database).materialize_group_payload("fictional-room", path, start_time=150)
    outcome = ImportService().execute(ImportRequest(input_path=path, platform="qq"))
    assert len(outcome.messages) == 1
    assert outcome.rich_messages[0].relations == (MentionRelation(None, "@Fictional display"),)
    assert outcome.messages[0].text == "answer"
