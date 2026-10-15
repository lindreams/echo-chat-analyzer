"""RED-GREEN coverage for bounded is_self on the QQ Direct DB adapter.

All identities and message bodies are fictional.
"""

from __future__ import annotations

import base64

from qq_chat_analyzer.legacy_projection import project_legacy_messages
from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _field(field_number: int, value: bytes) -> bytes:
    return _varint((field_number << 3) | 2) + _varint(len(value)) + value


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


def test_null_sender_record_is_skipped_not_marked_peer() -> None:
    # A NULL sender cannot be interpreted at all; the record is skipped, so it
    # can never be mis-attributed to peer (False).
    payload = _payload("group", "100000001", _record(None))
    rich_messages, warnings = parse_qq_db_rich_messages(payload)
    assert rich_messages == []
    assert warnings == ("qq_db_record_skipped",)


def test_missing_self_context_yields_none() -> None:
    payload = _payload("group", None, _record("100000001"))
    assert _is_self_values(payload) == [None]


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
