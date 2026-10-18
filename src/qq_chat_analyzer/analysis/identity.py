"""Shared identity-key helpers for the analysis core."""

from __future__ import annotations

from ..message import ChatMessage


def stable_sender_key(message: ChatMessage) -> str:
    """Return the stable sender identity key, falling back to display text."""
    sender_id = message.sender_id
    if isinstance(sender_id, str) and sender_id.strip():
        return sender_id.strip()
    return message.sender


def is_chat_participant(message: ChatMessage) -> bool:
    """Count only senders with a stable ID or a usable fallback name."""
    return bool(stable_sender_key(message).strip())
