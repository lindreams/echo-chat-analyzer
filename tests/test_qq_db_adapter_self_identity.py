"""RED-GREEN coverage for bounded is_self on the QQ Direct DB adapter.

All identities and message bodies are fictional.
"""

from __future__ import annotations

import base64

from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages


from qq_db_test_data import (
    encode_varint as _varint,
    length_delimited_field as _field,
)


def _text_blob(text: str) -> str:
    segment = _varint((45002 << 3) | 0) + _varint(1) + _field(45101, text.encode("utf-8"))
    return base64.b64encode(_field(40800, segment)).decode("ascii")


def _record(sender: object, text: str = "fictional text") -> dict:
    return {
        "record_id": "fictional-record",
        "fields": {"40033": sender, "40050": 1760000000},
        "message_blob": _text_blob(text),
        "blob_encoding": "base64",
    }


def _payload(session_type: str, self_uin: object, *records: dict) -> dict:
    payload = {
        "format": "qq-db-json",
        "format_version": 0,
        "source": "qq",
        "source_type": "qq-db-json",
        "query": {
            "requested_session": "fictional-key",
            "session_type": session_type,
            "internal_key": "fictional-key",
            "session_object": "fictional-object",
            "time_range": None,
        },
        "records": list(records),
    }
    if self_uin is not None:
        payload["self"] = {"namespace": "qq_uin", "value": self_uin}
    return payload


def _is_self_values(payload: dict) -> list[bool | None]:
    rich_messages, _warnings = parse_qq_db_rich_messages(payload)
    return [message.is_self for message in rich_messages]


def test_group_self_and_peer() -> None:
    payload = _payload(
        "group",
        "100000001",
        _record("100000001"),
        _record("100000002"),
    )
    assert _is_self_values(payload) == [True, False]


def test_private_self_and_peer() -> None:
    payload = _payload(
        "private",
        "100000001",
        _record("100000001"),
        _record("100000002"),
    )
    assert _is_self_values(payload) == [True, False]


def test_zero_sender_is_unknown_not_peer() -> None:
    payload = _payload("group", "100000001", _record(0), _record("0"))
    assert _is_self_values(payload) == [None, None]


def test_missing_sender_with_content_stays_unknown_through_import(tmp_path) -> None:
    import json
    from qq_chat_analyzer.application.import_request import ImportRequest
    from qq_chat_analyzer.application.import_service import ImportService

    records = [_record(None), _record(""), _record("  "), _record(0)]
    missing = _record(None)
    del missing["fields"]["40033"]
    records.append(missing)
    for record in records:
        record["sender"] = {"nickname": "Incidental fictional label"}
    for kind in ("group", "private"):
        path = tmp_path / (kind + ".json")
        path.write_text(json.dumps(_payload(kind, "100000001", *records)), encoding="utf-8")
        outcome = ImportService().execute(ImportRequest(input_path=path, platform="qq"))
        assert len(outcome.messages) == len(outcome.rich_messages) == len(records)
        for rich, legacy in zip(outcome.rich_messages, outcome.messages):
            assert rich.sender.identity_id is legacy.sender_id is None
            assert rich.sender.display_name == legacy.sender == ""
            assert rich.is_self is legacy.is_self is None
            assert legacy.text == "fictional text"


def test_unknown_sender_does_not_make_invalid_records_acceptable() -> None:
    from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages_with_media_facts

    invalid_blob = _record(None)
    invalid_blob["message_blob"] = "not base64!"
    no_content = _record(None)
    no_content["message_blob"] = ""
    invalid_time = _record(None)
    invalid_time["fields"]["40050"] = None
    reasons = []
    messages, warnings, _ = parse_qq_db_rich_messages_with_media_facts(
        _payload("group", "100000001", invalid_blob, no_content, invalid_time, _record({"id": "100000002"})),
        on_record=lambda record, message, reason, diagnostics: reasons.append(reason),
    )
    assert messages == []
    assert warnings == ("qq_db_record_skipped",)
    assert reasons == ["invalid_blob", "no_supported_semantics", "invalid_timestamp_type", "invalid_sender_type"]


def test_missing_sender_with_only_opaque_content_remains_unresolved() -> None:
    from qq_db_test_data import scalar_field
    record = _record(None)
    record["message_blob"] = base64.b64encode(_field(40800, scalar_field(45002, 8))).decode("ascii")
    messages, warnings = parse_qq_db_rich_messages(_payload("group", "100000001", record))
    assert messages == []
    assert warnings == ("qq_db_record_skipped",)


def test_unreliable_self_identity_yields_none() -> None:
    # A zero / empty self identity is not a reliable self, so even a sender
    # that equals "0" must not be treated as self or peer.
    for self_uin in (0, "0", "", None):
        payload = _payload("group", self_uin, _record("100000001"))
        assert _is_self_values(payload) == [None]


def test_wrong_self_namespace_yields_none() -> None:
    payload = _payload("group", "100000001", _record("100000001"))
    payload["self"]["namespace"] = "qq_uid"
    assert _is_self_values(payload) == [None]
