"""Lossless confirmed sticker sends; no database, filesystem or ranking logic."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..rich_message import ExpressionContent, RichMessage
from .timestamps import to_chat_datetime, to_epoch_seconds


@dataclass(frozen=True, slots=True)
class StickerSend:
    """One content occurrence, keyed only within this analysis result.

    identity_key=None explicitly forbids material aggregation. An opaque QQ
    key groups equal source bytes, without claiming a decoded resource hash.
    """

    occurrence_id: str
    source: str
    conversation_id: str | None = field(repr=False)
    conversation_type: str
    sender_id: str | None = field(repr=False)
    message_id: str | None = field(repr=False)
    content_index: int
    timestamp: int | float | str = field(repr=False)
    epoch_seconds: int | None
    chat_date: str | None
    classification_basis: str
    identity_basis: str
    identity_key: str | None = field(repr=False)
    media_key: str = field(repr=False)
    content_md5: str | None = field(repr=False)
    local_paths: tuple[str, ...] = field(default=(), repr=False)


@dataclass(frozen=True, slots=True)
class StickerMedia:
    """One verified original or an explicit failure, never a display fallback.

    Immutable original_bytes outlive temporary payloads and external cache
    changes. No copies are written to disk. Consumers must check status before
    using bytes; verified_reference is provenance at read time, not a promise
    that an external file remains unchanged.
    """

    media_key: str = field(repr=False)
    status: str
    reason: str | None = None
    verified_reference: str | None = field(default=None, repr=False)
    sha256: str | None = field(default=None, repr=False)
    format: str | None = None
    frame_count: int | None = None
    animation_preserved: bool | None = None
    byte_count: int | None = None
    original_bytes: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class StickerData:
    """Private in-process data channel; excluded from report serialization."""

    sends: tuple[StickerSend, ...] = field(default=(), repr=False)
    media: tuple[StickerMedia, ...] = field(default=(), repr=False)


def collect_sticker_sends(messages: Iterable[RichMessage]) -> tuple[StickerSend, ...]:
    """Collect only source-confirmed evidence from the already filtered Rich chain."""
    sends = []
    for message_index, message in enumerate(messages):
        moment = to_chat_datetime(message.timestamp)
        for content_index, part in enumerate(message.contents):
            if not isinstance(part, ExpressionContent) or part.sticker is None:
                continue
            evidence = part.sticker
            occurrence_id = f"{message_index}:{content_index}"
            sends.append(StickerSend(
                occurrence_id=occurrence_id, source=message.source,
                conversation_id=message.conversation_id,
                conversation_type=message.conversation_type,
                sender_id=message.sender.identity_id, message_id=message.message_id,
                content_index=content_index, timestamp=message.timestamp,
                epoch_seconds=to_epoch_seconds(message.timestamp),
                chat_date=moment.date().isoformat() if moment else None,
                classification_basis=evidence.classification_basis,
                identity_basis=evidence.identity_basis,
                identity_key=evidence.identity_key,
                media_key=evidence.identity_key or f"unresolved:{occurrence_id}",
                content_md5=evidence.content_md5, local_paths=evidence.local_paths,
            ))
    return tuple(sends)
