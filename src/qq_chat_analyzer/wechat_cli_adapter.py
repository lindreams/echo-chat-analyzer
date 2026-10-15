"""Adapt CipherTalk CLI (``miyu``) export output into ChatMessage objects.

``miyu export <session> --output file.json`` writes a *bare JSON array* of
``MessageRow`` records, unlike the CipherTalk desktop ``detailed-json`` export
which wraps messages in an object. Rather than synthesizing a fake
``detailed-json`` payload, this module converts CLI rows straight into
:class:`~qq_chat_analyzer.message.ChatMessage`.

A CLI row looks like::

    {
      "localId": 1, "serverId": 2, "createTime": 1753412807, "sortSeq": 3,
      "direction": "in" | "out" | "unknown",
      "senderUsername": "wxid_...", "type": 1, "content": "text"
    }
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .message import ChatMessage


WECHAT_PLATFORM = "wechat"
CLI_JSON_FORMAT = "cli-json"

_TEXT_TYPE = "text"
_REPLY_TYPE = "reply"

# CipherTalk CLI reports ``type`` as either a numeric WeChat message type or a
# normalized string. Only text-bearing kinds are analyzable; everything else
# (image, voice, video, file, system) is skipped, matching wechat_parser.
_NUMERIC_MESSAGE_TYPES = {
    1: _TEXT_TYPE,
}
_STRING_MESSAGE_TYPES = {
    "text": _TEXT_TYPE,
    "reply": _REPLY_TYPE,
    "quote": _REPLY_TYPE,
    "\u6587\u672c\u6d88\u606f": _TEXT_TYPE,
    "\u5f15\u7528\u6d88\u606f": _REPLY_TYPE,
}

# The CLI omits display names, so fall back to a direction-derived label the
# same way the upstream Markdown renderer does.
_OUTGOING_SENDER = "\u6211"
_INCOMING_SENDER = "\u5bf9\u65b9"

_DIRECTION_OUT = "out"
_DIRECTION_IN = "in"

_DETECTION_SAMPLE_SIZE = 50


def is_cli_export(path: str | Path) -> bool:
    """Return whether ``path`` is a CipherTalk CLI JSON export."""
    payload = _load_json_array(path)
    if payload is None:
        return False
    return is_cli_payload(payload)


def load_messages(path: str | Path) -> list[Any]:
    """Load raw CLI rows from a ``miyu export`` JSON file."""
    payload = _load_json_array(path)
    if payload is None or not is_cli_payload(payload):
        return []
    return payload


def parse_messages(
    raw_messages: Iterable[Any],
    conversation_id: str | None = None,
    conversation_type: str = "unknown",
) -> list[ChatMessage]:
    """Normalize supported CLI rows, isolating malformed entries."""
    parsed_messages: list[ChatMessage] = []

    try:
        iterator = iter(raw_messages)
    except TypeError:
        return parsed_messages

    for raw_message in iterator:
        parsed_message = parse_message(
            raw_message,
            conversation_id=conversation_id,
            conversation_type=conversation_type,
        )
        if parsed_message is not None:
            parsed_messages.append(parsed_message)

    return parsed_messages


def parse_message(
    raw_message: Any,
    conversation_id: str | None = None,
    conversation_type: str = "unknown",
) -> ChatMessage | None:
    """Convert a single CLI row into a ChatMessage, or ``None`` if unusable."""
    if not isinstance(raw_message, Mapping):
        return None

    source_type = raw_message.get("type")
    message_type = _normalize_message_type(source_type)
    if message_type is None:
        return None

    timestamp = raw_message.get("createTime")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float, str)):
        return None

    text = raw_message.get("content")
    if not isinstance(text, str):
        return None

    sender_id = raw_message.get("senderUsername")
    if not isinstance(sender_id, str) or not sender_id.strip():
        sender_id = None

    direction = raw_message.get("direction")
    sender = sender_id or _sender_from_direction(direction)
    if sender is None:
        return None
    resolved_conversation_id = _clean_string(
        raw_message.get("sessionId")
        or raw_message.get("conversationId")
        or raw_message.get("session_id")
        or raw_message.get("conversation_id")
    ) or conversation_id
    resolved_conversation_type = _normalize_conversation_type(
        raw_message.get("sessionType")
        or raw_message.get("conversationType")
        or conversation_type
    )
    is_self = _is_self_from_direction(direction)

    return ChatMessage(
        timestamp=timestamp,
        sender=sender,
        message_type=message_type,
        text=text,
        platform=WECHAT_PLATFORM,
        source_type=source_type,
        message_id=_stringify_message_id(raw_message.get("serverId")),
        sender_id=sender_id,
        conversation_id=resolved_conversation_id,
        conversation_type=resolved_conversation_type,
        is_self=is_self,
        is_system=False,
        recalled=False,
    )


def _normalize_message_type(source_type: Any) -> str | None:
    if isinstance(source_type, bool):
        return None
    if isinstance(source_type, int):
        return _NUMERIC_MESSAGE_TYPES.get(source_type)
    if isinstance(source_type, str):
        return _STRING_MESSAGE_TYPES.get(source_type.strip().lower()) or (
            _STRING_MESSAGE_TYPES.get(source_type.strip())
        )
    return None


def _sender_from_direction(direction: Any) -> str | None:
    if direction == _DIRECTION_OUT:
        return _OUTGOING_SENDER
    if direction == _DIRECTION_IN:
        return _INCOMING_SENDER
    return None


def _is_self_from_direction(direction: Any) -> bool | None:
    if direction == _DIRECTION_OUT:
        return True
    if direction == _DIRECTION_IN:
        return False
    return None


def _normalize_conversation_type(raw_type: Any) -> str:
    if not isinstance(raw_type, str):
        return "unknown"
    normalized = raw_type.strip().lower()
    if normalized in {"private", "group"}:
        return normalized
    return "unknown"


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _stringify_message_id(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, str)):
        text = str(value).strip()
        return text or None
    return None


def _load_json_array(path: str | Path) -> list[Any] | None:
    try:
        input_path = Path(path)
    except TypeError:
        return None

    if input_path.suffix.lower() != ".json":
        return None

    try:
        with input_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    return payload if isinstance(payload, list) else None


def is_cli_payload(payload: list[Any]) -> bool:
    if not payload:
        return False

    for row in payload[:_DETECTION_SAMPLE_SIZE]:
        if not isinstance(row, Mapping):
            continue
        if "content" not in row:
            continue
        if "direction" in row:
            return True
        if "senderUsername" in row and "createTime" in row:
            return True

    return False
