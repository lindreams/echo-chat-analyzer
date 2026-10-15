"""A6.1 regression coverage using only fictional protobuf messages."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3

import pytest

from qq_chat_analyzer.analysis.analyzers.expression_analyzer import ExpressionAnalyzer
from qq_chat_analyzer.application.import_request import ImportRequest
from qq_chat_analyzer.application.import_service import ImportService
from qq_chat_analyzer.legacy_projection import project_legacy_messages
from qq_chat_analyzer.providers.qq_database_provider import QQDatabaseProvider
from qq_chat_analyzer.qq_db_adapter import WARNING_QQ_DB_RECORD_SKIPPED, parse_qq_db_rich_messages
from qq_chat_analyzer.rich_message import ExpressionContent, MentionRelation, NonTextContent, TextContent


def _varint(value: int) -> bytes:
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def _scalar(tag: int, value: int) -> bytes:
    return _varint(tag << 3) + _varint(value)


def _bytes(tag: int, value: bytes) -> bytes:
    return _varint((tag << 3) | 2) + _varint(len(value)) + value


def _text(value: str) -> bytes:
    return _scalar(45002, 1) + _bytes(45101, value.encode("utf-8"))


def _face(index: int = 14, label: str = "/fictional-face") -> bytes:
    return _scalar(45002, 6) + _scalar(47601, index) + _bytes(47602, label.encode())


def _sticker(identity: bytes = b"fictional-sticker", label: str = "[fictional-sticker]") -> bytes:
    return _scalar(45002, 11) + _bytes(45600, identity) + _bytes(80900, label.encode())


def _body(*segments: bytes) -> bytes:
    return b"".join(_bytes(40800, segment) for segment in segments)


def _payload(*blobs: bytes, session_type: str = "group") -> dict:
    return {
        "format": "qq-db-json", "format_version": 0,
        "source": "qq", "source_type": "qq-db-json",
        "query": {"session_type": session_type, "session_object": "fictional-room"},
        "records": [
            {"record_id": f"fictional-{index}",
             "fields": {"40033": "fictional-sender", "40050": 1760000000 + index},
             "blob_encoding": "base64", "message_blob": base64.b64encode(blob).decode()}
            for index, blob in enumerate(blobs)
        ],
    }


def _parse(*segments: bytes):
    messages, warnings = parse_qq_db_rich_messages(_payload(_body(*segments)))
    assert warnings == ()
    assert len(messages) == 1
    return messages[0]


def test_all_text_segments_and_second_segment_unicode_survive() -> None:
    message = _parse(_text("fictional A "), _text("fictional B 😂"))
    assert message.contents == (TextContent("fictional A "), TextContent("fictional B 😂"))
    legacy = project_legacy_messages([message])
    assert legacy[0].text == "fictional A fictional B 😂"
    report = ExpressionAnalyzer().analyze(legacy, [message])
    assert report.expression_occurrence_count == 1
    assert report.top_expressions[0].expression_key == "😂"


@pytest.mark.parametrize("session_type", ["group"])
@pytest.mark.parametrize("wire_type,size", [(1, 8)])
@pytest.mark.parametrize("location", ["body", "text"])
@pytest.mark.parametrize("prepend", [True])
def test_fixed_width_metadata_preserves_text_and_face(
    session_type, wire_type, size, location, prepend,
) -> None:
    # Even a known field number with a different wire type is opaque metadata.
    tag = {"body": 40800, "text": 45101}[location]
    metadata = _varint((tag << 3) | wire_type) + b"\xff" * size
    text, face = _text("fictional orchard"), _face()
    def attach(value):
        return metadata + value if prepend else value + metadata

    if location == "text":
        text = attach(text)
    blob = _body(text, face)
    if location == "body":
        blob = attach(blob)
    messages, warnings = parse_qq_db_rich_messages(_payload(blob, session_type=session_type))
    assert warnings == ()
    assert len(messages) == 1
    assert messages[0].contents == (
        TextContent("fictional orchard"),
        ExpressionContent("platform_face", "14", "/fictional-face", "qq", position=0),
    )
    assert project_legacy_messages(messages)[0].text == "fictional orchard"
    report = ExpressionAnalyzer().analyze(project_legacy_messages(messages), messages)
    assert report.expression_occurrence_count == 1


@pytest.mark.parametrize("wire_type,size", [(1, 8)])
@pytest.mark.parametrize("location", ["body", "segment"])
def test_truncated_fixed_width_field_rejects_entire_container(wire_type, size, location) -> None:
    # Test every short length, including a tag with no following value.
    for length in range(size):
        truncated = _varint((49000 << 3) | wire_type) + b"x" * length
        blob = (
            _body(_text("must not survive"), _face()) + truncated
            if location == "body"
            else _body(_text("must not survive") + truncated)
        )
        messages, warnings = parse_qq_db_rich_messages(_payload(blob))
        if location == "body":
            assert messages == []
            assert warnings == (WARNING_QQ_DB_RECORD_SKIPPED,)
        else:
            assert warnings == ()
            assert len(messages) == 1
            assert messages[0].contents == (NonTextContent("unknown"),)
            assert project_legacy_messages(messages)[0].text == ""


@pytest.mark.parametrize("invalid", [b"\x00", _varint((49000 << 3) | 2) + _varint(100) + b"short", _varint((49000 << 3) | 2) + b"\x80" * 11])
def test_malformed_body_does_not_return_preceding_valid_content(invalid) -> None:
    fixed = _varint((49000 << 3) | 5) + b"abcd"
    blob = _body(_text("must not survive"), _face()) + fixed + invalid
    messages, warnings = parse_qq_db_rich_messages(_payload(blob))
    assert messages == []
    assert warnings == (WARNING_QQ_DB_RECORD_SKIPPED,)


def test_fixed_width_metadata_does_not_promote_unknown_mentions_or_quotes_to_text() -> None:
    metadata = (
        _varint((49000 << 3) | 5) + b"abcd"
        + _varint((49001 << 3) | 1) + b"abcdefgh"
    )
    message = _parse(
        _scalar(45002, 999) + _bytes(45101, b"unknown content") + metadata,
        _text("@Fictional display") + _scalar(45102, 2) + metadata,
        _scalar(45002, 7) + _bytes(47710, _text("fictional quote")) + metadata,
        _text("authored text"), _face(),
    )
    assert message.message_type == "reply"
    assert message.relations == (MentionRelation(None, "@Fictional display"),)
    assert message.contents[0] == NonTextContent("unknown")
    assert message.contents[1] == TextContent("authored text")
    assert isinstance(message.contents[2], ExpressionContent)
    assert len(message.contents) == 3
    assert project_legacy_messages([message])[0].text == "authored text"


def test_repeated_faces_and_stickers_are_occurrences_with_stable_distinct_keys() -> None:
    message = _parse(_face(), _face(), _sticker(b"14"), _sticker(b"14"))
    assert len(message.contents) == 4
    assert [part.position for part in message.contents] == [0, 1, 2, 3]
    report = ExpressionAnalyzer().analyze(project_legacy_messages([message]), [message])
    by_kind = {item.kind: item for item in report.top_expressions}
    assert report.expression_occurrence_count == 4
    assert report.unique_expression_count == 2
    assert by_kind["platform_face"].count == by_kind["sticker"].count == 2
    assert by_kind["platform_face"].expression_key == "14"
    assert by_kind["sticker"].expression_key.startswith("qq-marketface:sha256:")


@pytest.mark.parametrize("unknown", [
    _scalar(45002, 999) + _bytes(45101, b"not-authored"),
    _scalar(45002, 7) + _bytes(47710, _text("fictional quote")),
    _scalar(45002, 8) + _bytes(80900, b"fictional system text"),
    _scalar(45002, 999) + _varint((49000 << 3) | 5) + b"abcd",
])
def test_unrecognized_block_does_not_stop_scanning_or_leak_text(unknown) -> None:
    message = _parse(_text("A"), unknown, _text("B"), _face())
    known = tuple(part for part in message.contents if not isinstance(part, NonTextContent))
    assert known[:2] == (TextContent("A"), TextContent("B"))
    assert isinstance(known[2], ExpressionContent)
    expected_unknown = 0 if unknown == _scalar(45002, 7) + _bytes(47710, _text("fictional quote")) else 1
    assert sum(isinstance(part, NonTextContent) for part in message.contents) == expected_unknown
    assert message.relations == ()
    assert project_legacy_messages([message])[0].text == "AB"


def test_expression_identity_is_not_guessed_from_display_text() -> None:
    message = _parse(_scalar(45002, 6) + _bytes(47602, b"same label"),
                     _scalar(45002, 11) + _bytes(80900, b"same label"), _text("later"))
    assert message.contents == (TextContent("later"),)


def test_sticker_key_uses_identity_bytes_not_label_or_resource_url() -> None:
    messages, warnings = parse_qq_db_rich_messages(_payload(
        _body(_sticker(label="label A") + _bytes(45804, b"https://fictional.invalid/a")),
        _body(_sticker(label="label B") + _bytes(45804, b"https://fictional.invalid/b")),
        _body(_sticker(b"distinct-sticker", "label A")),
    ))
    assert warnings == ()
    keys = [message.contents[0].expression_key for message in messages]
    assert keys[0] == keys[1]
    assert keys[0] != keys[2]


def test_provider_import_legacy_and_expression_report_chain(tmp_path) -> None:
    database = tmp_path / "fictional.db"
    blobs = [
        _body(_text("A "), _face(), _text("B 😂"), _sticker()),
        _body(_face(), _face()),
        _body(_sticker()),
    ]
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE group_msg_table ("40001" INTEGER PRIMARY KEY, "40030" TEXT, "40033" TEXT, "40050" INTEGER, "40800" BLOB)')
        connection.executemany('INSERT INTO group_msg_table VALUES (?, ?, ?, ?, ?)', [
            (index, "fictional-room", "fictional-sender", 1760000000 + index, blob)
            for index, blob in enumerate(blobs, start=1)
        ])
    path = tmp_path / "fictional-payload.json"
    QQDatabaseProvider(database).materialize_group_payload("fictional-room", path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert [base64.b64decode(record["message_blob"]) for record in raw["records"]] == blobs
    outcome = ImportService().execute(ImportRequest(input_path=path, platform="qq"))
    assert outcome.result.warnings == ()
    assert outcome.processed_message_count == 3
    assert len(outcome.rich_messages) == len(outcome.messages) == 3
    assert [message.text for message in outcome.messages] == ["A B 😂", "", ""]
    report = ExpressionAnalyzer().analyze(outcome.messages, outcome.rich_messages)
    assert report.expression_message_count == 3
    assert report.expression_only_message_count == 2
    assert report.expression_occurrence_count == 6
    assert {item.kind: item.count for item in report.top_expressions} == {"platform_face": 3, "sticker": 2, "unicode": 1}
