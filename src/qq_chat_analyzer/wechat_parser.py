"""Parse CipherTalk WeChat detailed JSON and chatlab JSONL exports."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .message import ChatMessage


TEXT_MESSAGE_TYPE = "\u6587\u672c\u6d88\u606f"
REPLY_MESSAGE_TYPE = "\u5f15\u7528\u6d88\u606f"
WECHAT_PLATFORM = "wechat"
DETAILED_JSON_FORMAT = "detailed-json"

SUPPORTED_MESSAGE_TYPES = frozenset(
    {TEXT_MESSAGE_TYPE, REPLY_MESSAGE_TYPE}
)
_NORMALIZED_MESSAGE_TYPES = {
    TEXT_MESSAGE_TYPE: "text",
    REPLY_MESSAGE_TYPE: "reply",
}

CHATLAB_TEXT_TYPE = 0
CHATLAB_REPLY_TYPE = 25
CHATLAB_JSONL_SUFFIX = ".jsonl"
_CHATLAB_MESSAGE_LINE = "message"
_CHATLAB_HEADER_LINE = "header"
_NORMALIZED_CHATLAB_TYPES = {
    CHATLAB_TEXT_TYPE: "text",
    CHATLAB_REPLY_TYPE: "reply",
}

def parse_messages(
    raw_messages: Iterable[Any],
    conversation_id: str | None = None,
    conversation_type: str = "unknown",
) -> list[ChatMessage]:
    """Normalize supported WeChat messages while isolating malformed entries."""
    parsed_messages: list[ChatMessage] = []

    try:
        iterator = iter(raw_messages)
    except TypeError:
        return parsed_messages

    for raw_message in iterator:
        parsed_message = _parse_message(
            raw_message,
            conversation_id=conversation_id,
            conversation_type=conversation_type,
        )
        if parsed_message is not None:
            parsed_messages.append(parsed_message)

    return parsed_messages


def load_chatlab_records(path: str | Path) -> list[Mapping[str, Any]]:
    try:
        input_path = Path(path)
    except TypeError:
        return []

    records: list[Mapping[str, Any]] = []
    try:
        with input_path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, Mapping):
                    records.append(record)
    except (OSError, UnicodeDecodeError):
        return records

    return records


def is_chatlab_records(records: Iterable[Mapping[str, Any]]) -> bool:
    """Recognize loaded chatlab records without reopening the file."""
    for record in records:
        line_type = record.get("_type")
        if line_type == _CHATLAB_HEADER_LINE:
            meta = record.get("meta")
            if (
                isinstance(meta, Mapping)
                and meta.get("platform") == WECHAT_PLATFORM
            ):
                return True
        if line_type == _CHATLAB_MESSAGE_LINE:
            return True
    return False


def is_detailed_payload(payload: Mapping[str, Any]) -> bool:
    session = payload.get("session")
    if isinstance(session, Mapping) and session.get("platform") == WECHAT_PLATFORM:
        return True

    export_info = payload.get("exportInfo")
    if (
        isinstance(export_info, Mapping)
        and export_info.get("format") == DETAILED_JSON_FORMAT
    ):
        return True

    messages = payload.get("messages")
    if not isinstance(messages, list):
        return False

    for message in messages[:50]:
        if not isinstance(message, Mapping):
            continue
        if message.get("type") in SUPPORTED_MESSAGE_TYPES:
            return True
        if "senderDisplayName" in message and "createTime" in message:
            return True

    return False


def _parse_message(
    raw_message: Any,
    conversation_id: str | None = None,
    conversation_type: str = "unknown",
) -> ChatMessage | None:
    if not isinstance(raw_message, Mapping):
        return None

    if raw_message.get("_type") == _CHATLAB_MESSAGE_LINE:
        return _parse_chatlab_message(
            raw_message,
            conversation_id=conversation_id,
            conversation_type=conversation_type,
        )

    source_type = raw_message.get("type")
    message_type = _NORMALIZED_MESSAGE_TYPES.get(source_type)
    if message_type is None:
        return None

    timestamp = raw_message.get("createTime")
    if not isinstance(timestamp, (int, float, str)):
        return None

    sender = raw_message.get("senderDisplayName")
    if not isinstance(sender, str) or not sender.strip():
        sender = raw_message.get("senderUsername")
    if not isinstance(sender, str) or not sender.strip():
        return None

    text = raw_message.get("content")
    if not isinstance(text, str):
        return None

    return ChatMessage(
        timestamp=timestamp,
        sender=sender,
        message_type=message_type,
        text=text,
        platform=WECHAT_PLATFORM,
        source_type=source_type,
        message_id=raw_message.get("platformMessageId"),
        sender_id=raw_message.get("senderUsername"),
        conversation_id=conversation_id,
        conversation_type=conversation_type,
        is_self=_is_send_flag(raw_message),
        is_system=False,
        recalled=False,
    )


def _parse_chatlab_message(
    raw_message,
    conversation_id: str | None = None,
    conversation_type: str = "unknown",
):
    source_type = raw_message.get("type")
    if isinstance(source_type, bool) or not isinstance(source_type, int):
        return None

    message_type = _NORMALIZED_CHATLAB_TYPES.get(source_type)
    if message_type is None:
        return None

    timestamp = raw_message.get("timestamp")
    if not isinstance(timestamp, (int, float, str)):
        return None

    sender = raw_message.get("accountName")
    if not isinstance(sender, str) or not sender.strip():
        sender = raw_message.get("sender")
    if not isinstance(sender, str) or not sender.strip():
        return None

    text_value = raw_message.get("content")
    if not isinstance(text_value, str):
        return None

    return ChatMessage(
        timestamp=timestamp,
        sender=sender,
        message_type=message_type,
        text=text_value,
        platform=WECHAT_PLATFORM,
        source_type=source_type,
        message_id=raw_message.get("platformMessageId"),
        sender_id=raw_message.get("sender"),
        conversation_id=conversation_id,
        conversation_type=conversation_type,
        is_self=_is_send_flag(raw_message),
        is_system=False,
        recalled=False,
    )


def detailed_conversation_context(
    payload: Mapping[str, Any],
) -> tuple[str | None, str]:
    session = payload.get("session")
    if not isinstance(session, Mapping):
        return None, "unknown"

    conversation_id = _first_text(
        session,
        "username",
        "wxid",
        "sessionId",
        "conversationId",
        "id",
    )
    session_type = _first_text(session, "type", "sessionType")
    if isinstance(session.get("isGroup"), bool):
        session_type = "group" if session["isGroup"] else "private"
    return conversation_id, _normalize_conversation_type(session_type)


def chatlab_conversation_context(
    records: list[Mapping[str, Any]],
) -> tuple[str | None, str]:
    for record in records:
        if record.get("_type") != _CHATLAB_HEADER_LINE:
            continue
        meta = record.get("meta")
        if not isinstance(meta, Mapping):
            continue
        conversation_id = _first_text(
            meta,
            "groupId",
            "chatId",
            "sessionId",
            "conversationId",
            "id",
        )
        session_type = _first_text(meta, "type", "sessionType")
        if isinstance(meta.get("isGroup"), bool):
            session_type = "group" if meta["isGroup"] else "private"
        return conversation_id, _normalize_conversation_type(session_type)
    return None, "unknown"


def _normalize_conversation_type(raw_type: str | None) -> str:
    if not raw_type:
        return "unknown"
    normalized = raw_type.strip().lower()
    if normalized in {"private", "group"}:
        return normalized
    return "unknown"


def _first_text(data: Mapping[Any, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_send_flag(raw_message: Mapping[Any, Any]) -> bool | None:
    value = raw_message.get("isSend")
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
    return None
