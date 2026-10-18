"""A6.3 coverage with fictional content only; no media resource access."""

import json
import sqlite3

import pytest

from test_qq_db_rich_contents import _body, _bytes, _face, _payload, _scalar, _text, _varint
from qq_chat_analyzer.application.dto import AnalysisRequestDTO, AnalysisStatus
from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
from qq_chat_analyzer.application.import_request import ImportRequest
from qq_chat_analyzer.application.import_service import ImportService
from qq_chat_analyzer.legacy_projection import project_legacy_messages
from qq_chat_analyzer.providers.qq_database_provider import QQDatabaseProvider
from qq_chat_analyzer.qq_db_adapter import (
    extract_qq_pic_media_facts,
    parse_qq_db_rich_messages,
)
from qq_chat_analyzer.rich_message import ExpressionContent, TextContent


def _nontext(kind):
    # Deliberately text-like metadata must never become author text or emoji.
    return (_scalar(45002, kind) + _bytes(45101, "metadata 😂".encode())
            + _bytes(45815, b"[image]")
            + _bytes(45804, b"https://fictional.invalid/resource"))


def _parse(*parts):
    messages, warnings = parse_qq_db_rich_messages(_payload(_body(*parts)))
    assert warnings == ()
    assert len(messages) == 1
    return messages[0]


@pytest.mark.parametrize("kind,label", [(2, "image"), (999, "unknown")])
def test_mixed_order_and_only_author_text(kind, label):
    from qq_chat_analyzer.rich_message import NonTextContent
    message = _parse(_text("first "), _nontext(kind), _text("last"))
    assert message.contents == (TextContent("first "), NonTextContent(label), TextContent("last"))
    assert message.message_type == "mixed"
    assert project_legacy_messages([message])[0].text == "first last"


def test_unknown_boundary_and_following_content():
    from qq_chat_analyzer.rich_message import NonTextContent
    message = _parse(_nontext(2), _bytes(49000, b"opaque"),
                     _scalar(45002, 999) + _varint((49000 << 3) | 5) + b"abcd",
                     _text("later"), _face())
    assert message.contents[:3] == (NonTextContent("image"), NonTextContent("unknown"), NonTextContent("unknown"))
    assert message.contents[3] == TextContent("later")
    assert isinstance(message.contents[4], ExpressionContent)


@pytest.mark.parametrize("with_text", [False, True])
def test_provider_import_and_real_report_exports(tmp_path, with_text):
    database = tmp_path / "fictional.db"
    blobs = [_body(_nontext(2)), _body(_nontext(2)),
             _body(_nontext(2), _nontext(2)), _body(_nontext(999))]
    if with_text:
        blobs.append(_body(_text("fictional conversation "), _nontext(2), _text("continues")))
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE group_msg_table ("40001" INTEGER PRIMARY KEY, "40030" TEXT, "40033" TEXT, "40050" INTEGER, "40800" BLOB)')
        connection.executemany('INSERT INTO group_msg_table VALUES (?, ?, ?, ?, ?)', [
            (index, "fictional-room", "fictional-sender", 1760000000 + index, blob)
            for index, blob in enumerate(blobs, 1)])
    path = tmp_path / "payload.json"
    QQDatabaseProvider(database).materialize_group_payload("fictional-room", path)
    outcome = ImportService().execute(ImportRequest(input_path=path, platform="qq"))
    assert len(outcome.rich_messages) == len(outcome.messages) == len(blobs)
    assert outcome.result.warnings == ()
    assert [m.message_type for m in outcome.messages[:4]] == ["image", "image", "image", "unknown"]
    assert [m.text for m in outcome.messages[:4]] == [""] * 4
    stopwords = tmp_path / "stopwords.txt"
    stopwords.write_text("", encoding="utf-8")
    output = tmp_path / "report"
    result = AnalysisApplicationService().execute(AnalysisRequestDTO(
        input_path=path, output_directory=output, stopwords_path=stopwords))
    assert result.status == AnalysisStatus.COMPLETED
    assert result.valid_text_count == int(with_text)
    assert result.reports.expression.expression_occurrence_count == 0
    assert result.reports.activity.total_message_count == len(blobs)
    assert not result.top_words if not with_text else result.top_words
    assert all("metadata" not in item.word and "resource" not in item.word for item in result.top_words)
    assert len(result.artifacts) == 2
    assert json.loads((output / "echo-report.json").read_text(encoding="utf-8"))
    assert (output / "echo-report.html").is_file()


def test_nontext_outside_scope_cannot_unlock_empty_text_report(tmp_path):
    from datetime import datetime
    from qq_chat_analyzer.application.scope_filter import AnalysisScope
    path = tmp_path / "payload.json"
    payload = _payload(_body(_nontext(2)), _body(_text("")))
    payload["records"][0]["fields"]["40050"] -= 86400
    path.write_text(json.dumps(payload), encoding="utf-8")
    stopwords = tmp_path / "stopwords.txt"
    stopwords.write_text("", encoding="utf-8")
    result = AnalysisApplicationService().execute(AnalysisRequestDTO(
        input_path=path, output_directory=tmp_path / "report", stopwords_path=stopwords,
        scope=AnalysisScope.custom(datetime.fromtimestamp(1760000001).date(), datetime.fromtimestamp(1760000001).date())))
    assert result.status == AnalysisStatus.NO_VALID_TEXT
    assert result.artifacts == ()


def _media_pic_segment(
    *,
    segment_id: int = 8000000000000000001,
    md5: bytes = b"\xab" * 16,
    alternate: bytes | None = None,
    subtype: int = 1,
) -> bytes:
    segment = (
        _scalar(45002, 2)
        + _scalar(45001, segment_id)
        + _bytes(45503, b"fictional-file-uuid")
        + _bytes(45406, md5)
        + _scalar(45003, subtype)
    )
    if alternate is not None:
        segment += _bytes(45424, alternate)
    return segment


def test_pic_media_facts_expose_locators_without_private_values():
    payload = _payload(_body(_media_pic_segment()), session_type="private")
    record = payload["records"][0]
    record["record_id"] = "7000000000000000001"
    record["fields"].update({
        "40021": "u_fictionalpeer000000000000",
        "40033": "10002",
        "40050": 1760000001,
    })
    payload["self"] = {"namespace": "qq_uin", "value": "10001"}

    facts = extract_qq_pic_media_facts(payload, {"7000000000000000001"})

    assert len(facts) == 1
    fact = facts[0]
    assert fact.message_id == "7000000000000000001"
    assert fact.timestamp == 1760000001
    assert fact.peer_uid == "u_fictionalpeer000000000000"
    assert fact.conversation_type == "private"
    assert fact.is_self is False
    element = fact.elements[0]
    assert element.segment_id == "8000000000000000001"
    assert element.file_uuid == "fictional-file-uuid"
    assert element.content_md5 == "ab" * 16
    assert element.is_custom_sticker is True

    rendered = repr(fact) + repr(element)
    for private in (
        "7000000000000000001", "8000000000000000001", "ab" * 16,
        "fictional-file-uuid", "u_fictionalpeer",
    ):
        assert private not in rendered


def test_pic_media_facts_keep_digest_conflict_and_filter_unselected_records():
    conflict = _media_pic_segment(alternate=bytes.fromhex("cd" * 16))
    ordinary = _media_pic_segment(segment_id=8000000000000000002, subtype=0)
    payload = _payload(_body(conflict), _body(ordinary), session_type="private")
    payload["records"][0]["record_id"] = "7000000000000000002"
    payload["records"][1]["record_id"] = "7000000000000000003"

    facts = extract_qq_pic_media_facts(payload, {"7000000000000000002"})

    assert len(facts) == 1
    assert facts[0].message_id == "7000000000000000002"
    assert facts[0].elements[0].content_md5 is None
    assert facts[0].elements[0].is_custom_sticker is True
    assert extract_qq_pic_media_facts(
        payload, {"7000000000000000003"})[0].elements[0].is_custom_sticker is False
    assert extract_qq_pic_media_facts(payload, set()) == ()


@pytest.mark.parametrize("conflict", [False, True])
def test_group_pic_facts_keep_group_and_sender_separate(conflict):
    payload = _payload(_body(_media_pic_segment()), session_type="group")
    payload["query"]["session_object"] = "12345001"
    payload["records"][0]["fields"].update({
        "40021": "12345002" if conflict else "12345001", "40030": 12345001,
        "40020": "u_fictionalmember000000", "40033": "10002"})
    fact, = extract_qq_pic_media_facts(payload)
    assert fact.group_id == (None if conflict else "12345001")
    assert fact.sender_uin == "10002" and fact.sender_uid == "u_fictionalmember000000"
    assert fact.conversation_id == "12345001" and fact.peer_uid is None


@pytest.mark.parametrize("tag,value,field", [
    (45001, 123, "segment_id"), (45503, b"other-file-uuid", "file_uuid"),
])
def test_group_pic_repeated_locator_cannot_select_the_last_value(tag, value, field):
    duplicate = _scalar(tag, value) if isinstance(value, int) else _bytes(tag, value)
    payload = _payload(_body(_media_pic_segment() + duplicate), session_type="group")
    fact, = extract_qq_pic_media_facts(payload)
    assert getattr(fact.elements[0], field) is None
