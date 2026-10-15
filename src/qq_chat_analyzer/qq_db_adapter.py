"""Adapter for QQ DB text, expressions, group replies and mention facts.

This module only interprets an already-materialized raw payload.  It does not
open a QQ database or otherwise acquire source data.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .legacy_projection import project_legacy_messages
from .identity_names import first_identity_name, resolve_member_names
from .message import ChatMessage
from .qq_db_identity import QQ_DB_SELF_NAMESPACE, canonical_qq_uin
from .rich_message import (
    EXPRESSION_KIND_PLATFORM_FACE,
    EXPRESSION_KIND_STICKER,
    ExpressionContent,
    MentionRelation,
    NonTextContent,
    MessageRelation,
    ReplyRelation,
    RichContent,
    RichMessage,
    SenderIdentity,
    TextContent,
)


QQ_DB_JSON_FORMAT = "qq-db-json"
WARNING_QQ_DB_RECORD_SKIPPED = "qq_db_record_skipped"


def is_qq_db_export(path: str | Path) -> bool:
    """Return whether a file is a v0 QQ DB JSON payload."""
    return is_qq_db_payload(load_qq_db_json(path))


def load_qq_db_json(path: str | Path) -> dict[str, Any] | None:
    """Load an already-materialized QQ DB JSON payload, if valid JSON."""
    try:
        input_path = Path(path)
        with input_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def parse_qq_db_messages(
    payload: Mapping[str, Any] | None,
) -> tuple[list[ChatMessage], tuple[str, ...]]:
    """Project supported QQ DB records for legacy analysis consumers."""
    rich_messages, warnings = parse_qq_db_rich_messages(payload)
    return project_legacy_messages(rich_messages), warnings


def parse_qq_db_rich_messages(
    payload: Mapping[str, Any] | None,
) -> tuple[list[RichMessage], tuple[str, ...]]:
    """Interpret supported group/private content into source-neutral facts."""
    if not is_qq_db_payload(payload):
        return [], ()

    parsed_messages: list[RichMessage] = []
    skipped_record = False
    records = payload["records"]
    session_context = _session_context(payload)
    if session_context is None:
        return [], (WARNING_QQ_DB_RECORD_SKIPPED,) if records else ()
    self_uin = _self_uin(payload)
    query = payload["query"]
    reply_targets: dict[str, list[str | None]] = {}
    if session_context[0] == "group":
        for record in records:
            if not _record_in_session(record, query):
                continue
            sequence = _sequence_key(record["fields"].get("40003"))
            if sequence is not None:
                reply_targets.setdefault(sequence, []).append(
                    _stringify_identifier(record.get("record_id"))
                )
    for record in records:
        parsed_message = _parse_record(
            record,
            session_context,
            self_uin,
            reply_targets if _record_in_session(record, query) else {},
        )
        if parsed_message is None:
            skipped_record = True
        else:
            parsed_messages.append(parsed_message)

    warnings = (WARNING_QQ_DB_RECORD_SKIPPED,) if skipped_record else ()
    return parsed_messages, warnings


def is_qq_db_payload(payload: Mapping[str, Any] | None) -> bool:
    return (
        isinstance(payload, Mapping)
        and payload.get("format") == QQ_DB_JSON_FORMAT
        and payload.get("format_version") == 0
        and payload.get("source") == "qq"
        and payload.get("source_type") == QQ_DB_JSON_FORMAT
        and isinstance(payload.get("records"), list)
    )


def _parse_record(
    record: Any,
    session_context: tuple[str, str],
    self_uin: Any,
    reply_targets: dict[str, list[str | None]],
) -> RichMessage | None:
    if not isinstance(record, Mapping):
        return None
    fields = record.get("fields")
    if not isinstance(fields, Mapping):
        return None

    # These field numbers only describe the feasibility-supported Adapter v0
    # slice; they are not stable across QQ versions.
    sender_id = _stringify_identifier(fields.get("40033"))
    timestamp = fields.get("40050")
    if (
        sender_id is None
        or not isinstance(timestamp, (int, float, str))
        or isinstance(timestamp, bool)
    ):
        return None

    contents, relations, has_reply = _extract_semantics(record, reply_targets)
    if not contents and not relations and not has_reply:
        return None

    conversation_type, conversation_id = session_context
    sender_data = record.get("sender")
    if not isinstance(sender_data, Mapping):
        sender_data = {}
    remark = (
        first_identity_name(sender_data.get("remark"))
        if conversation_type == "private"
        else None
    )
    nickname = first_identity_name(sender_data.get("nickname"), sender_data.get("name"))
    contextual_name = first_identity_name(sender_data.get("groupCard"))
    is_self = _resolve_is_self(fields.get("40033"), self_uin)
    display_name, _, _ = resolve_member_names(
        remark=remark,
        contextual_name=contextual_name,
        nickname=nickname,
        safe_display_fallback=(
            first_identity_name(sender_data.get("displayName"))
            or ("我" if is_self else "未知成员")
        ),
        conversation_kind=conversation_type,
    )
    if conversation_type == "private" and canonical_qq_uin(fields.get("40033")) is None:
        # Preserve the record, but a zero-value sender cannot identify a person.
        # Do not let an incidental label become a fallback participant identity.
        sender_id = None
        display_name = ""
        remark = nickname = contextual_name = None
    return RichMessage(
        message_id=_stringify_identifier(record.get("record_id")),
        source="qq",
        source_type=QQ_DB_JSON_FORMAT,
        conversation_id=conversation_id,
        conversation_type=conversation_type,
        sender=SenderIdentity(
            identity_id=sender_id,
            display_name=display_name,
            remark=remark,
            nickname=nickname,
            contextual_name=contextual_name,
        ),
        timestamp=timestamp,
        message_type="reply" if has_reply else _content_message_type(contents),
        contents=contents,
        relations=relations,
        is_self=is_self,
    )


def _content_message_type(contents: tuple[RichContent, ...]) -> str:
    nontext = [part for part in contents if isinstance(part, NonTextContent)]
    if not nontext:
        return "text"
    if len(nontext) != len(contents) or len({part.kind for part in nontext}) > 1:
        return "mixed"
    return nontext[0].kind


def _self_uin(payload: Mapping[str, Any]) -> Any:
    """Return the payload's bound self value, or ``None`` when absent.

    The namespace must match the Direct DB ``qq_uin`` namespace exactly; a
    mismatched or missing context is treated as unknown rather than guessed.
    """
    self_context = payload.get("self")
    if not isinstance(self_context, Mapping):
        return None
    if self_context.get("namespace") != QQ_DB_SELF_NAMESPACE:
        return None
    return self_context.get("value")


def _resolve_is_self(sender_value: Any, self_uin: Any) -> bool | None:
    """Compare canonical sender (40033) against canonical self identity.

    ``None`` means the source cannot reliably judge the sender; it is never
    collapsed to peer (``False``).  A zero / NULL / invalid sender or an
    unreliable self identity both yield ``None``.
    """
    canonical_sender = canonical_qq_uin(sender_value)
    canonical_self = canonical_qq_uin(self_uin)
    if canonical_sender is None or canonical_self is None:
        return None
    return canonical_sender == canonical_self


def _session_context(payload: Mapping[str, Any]) -> tuple[str, str] | None:
    query = payload.get("query")
    if not isinstance(query, Mapping):
        return None
    session_type = query.get("session_type")
    if session_type not in {"group", "private"}:
        return None
    session_object = _nonzero_identifier(query.get("session_object"))
    if session_object is not None:
        return session_type, session_object
    internal_key = _stringify_identifier(query.get("internal_key"))
    if internal_key is None:
        return None
    return session_type, f"{session_type}:{internal_key}"


def _record_in_session(record: Any, query: Mapping[str, Any]) -> bool:
    if (
        not isinstance(record, Mapping)
        or not isinstance(record.get("fields"), Mapping)
    ):
        return False
    fields = record["fields"]
    source_meta = record.get("source_meta")
    if isinstance(source_meta, Mapping):
        table = source_meta.get("table")
        expected = (
            "group_msg_table"
            if query.get("session_type") == "group"
            else "c2c_msg_table"
        )
        if table is not None and table != expected:
            return False
    internal_key = _stringify_identifier(query.get("internal_key"))
    if internal_key is not None:
        return _stringify_identifier(fields.get("40027")) == internal_key
    session_object = _nonzero_identifier(query.get("session_object"))
    return (
        session_object is not None
        and _nonzero_identifier(fields.get("40030")) == session_object
    )


def _sequence_key(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        try:
            number = int(value)
        except ValueError:
            return None
        return str(number) if number > 0 else None
    return None


def _extract_semantics(
    record: Mapping[str, Any],
    reply_targets: dict[str, list[str | None]],
) -> tuple[tuple[RichContent, ...], tuple[MessageRelation, ...], bool]:
    if record.get("blob_encoding") != "base64":
        return (), (), False
    blob = record.get("message_blob")
    if not isinstance(blob, str):
        return (), (), False
    try:
        decoded = base64.b64decode(blob, validate=True)
    except (binascii.Error, ValueError):
        return (), (), False

    # These field numbers only describe the feasibility-supported Adapter v0
    # slice; they are not stable across QQ versions.
    contents: list[RichContent] = []
    relations: list[MessageRelation] = []
    has_reply = False
    expression_position = 0
    for field_number, wire_type, value in _protobuf_fields(decoded):
        if field_number != 40800 or wire_type != 2:
            continue
        fields = _protobuf_fields(value)
        values = {(tag, wire): data for tag, wire, data in fields}
        content_type = values.get((45002, 0))
        if content_type == 7:
            has_reply = True
            sequence = _sequence_key(values.get((47402, 0)))
            targets = reply_targets.get(sequence, []) if sequence is not None else []
            if len(targets) == 1 and targets[0] is not None:
                relations.append(ReplyRelation(target_message_id=targets[0]))
            continue
        mention_type = values.get((45102, 0))
        if (
            content_type == 1
            and isinstance(mention_type, int)
            and mention_type != 0
        ):
            # 45105 is an NT UID, not this adapter's QQ UIN namespace.
            # Preserve the mention occurrence without inventing a UIN target.
            relations.append(
                MentionRelation(
                    target_identity_id=None,
                    display_text=_utf8_text(values.get((45101, 2))),
                )
            )
            continue
        content = _content_from_segment(fields, expression_position)
        if content is not None:
            contents.append(content)
            if isinstance(content, ExpressionContent):
                expression_position += 1
    return tuple(contents), tuple(relations), has_reply


def _content_from_segment(
    fields: tuple[tuple[int, int, int | bytes], ...], expression_position: int,
) -> RichContent | None:
    values = {(tag, wire): value for tag, wire, value in fields}
    content_type = values.get((45002, 0))
    if content_type == 1:
        text = _utf8_text(values.get((45101, 2)))
        return TextContent(text) if text is not None else None
    if content_type == 2:
        return NonTextContent("image")
    if content_type == 6:
        face_index = values.get((47601, 0))
        if not isinstance(face_index, int):
            return None
        key = str(face_index)
        kind = EXPRESSION_KIND_PLATFORM_FACE
        label = _utf8_text(values.get((47602, 2)))
        fallback = f"[QQ表情 {key}]"
    elif content_type == 11:
        identity = values.get((45600, 2))
        if not isinstance(identity, bytes) or not identity:
            return None
        # Opaque content-derived identity, not a decoded QQ emoji ID or a
        # resource MD5. Keep its namespace separate from numeric QQ faces.
        key = "qq-marketface:sha256:" + hashlib.sha256(identity).hexdigest()
        kind = EXPRESSION_KIND_STICKER
        label = _utf8_text(values.get((80900, 2)))
        fallback = "[贴图]"
    else:
        # In particular, do not recurse into ReplyBlock quoted content or
        # interpret 80900 outside the MarketFace context.
        return NonTextContent("unknown")
    if not label:
        label = next(
            (text for tag, wire, value in fields
             if tag == 45815 and wire == 2 and (text := _utf8_text(value))),
            None,
        )
    return ExpressionContent(
        expression_kind=kind,
        expression_key=key,
        display_text=label or fallback,
        source="qq",
        position=expression_position,
    )


def _utf8_text(value: int | bytes | None) -> str | None:
    if not isinstance(value, bytes):
        return None
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _protobuf_fields(data: bytes) -> tuple[tuple[int, int, int | bytes], ...]:
    fields: list[tuple[int, int, int | bytes]] = []
    offset = 0
    while offset < len(data):
        tag = _read_varint(data, offset)
        if tag is None:
            return ()
        tag_value, offset = tag
        field_number = tag_value >> 3
        wire_type = tag_value & 0x07
        if field_number == 0:
            return ()
        if wire_type == 0:
            value = _read_varint(data, offset)
            if value is None:
                return ()
            scalar, offset = value
            fields.append((field_number, wire_type, scalar))
        elif wire_type in {1, 5}:
            # Fixed-width fields carry no semantics consumed by this adapter.
            # Skip only a complete value; never salvage a truncated container.
            end = offset + (8 if wire_type == 1 else 4)
            if end > len(data):
                return ()
            offset = end
        elif wire_type == 2:
            length = _read_varint(data, offset)
            if length is None:
                return ()
            size, offset = length
            end = offset + size
            if end > len(data):
                return ()
            fields.append((field_number, wire_type, data[offset:end]))
            offset = end
        else:
            return ()
    return tuple(fields)


def _read_varint(data: bytes, offset: int) -> tuple[int, int] | None:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            return None
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
    return None


def _nonzero_identifier(value: Any) -> str | None:
    identifier = _stringify_identifier(value)
    return identifier if identifier not in {None, "0"} else None


def _stringify_identifier(value: Any) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None
