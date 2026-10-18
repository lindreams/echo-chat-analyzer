"""Lossless confirmed sticker sends; no database, filesystem or ranking logic."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..rich_message import ExpressionContent, NonTextContent, RichMessage
from .timestamps import to_chat_datetime, to_epoch_seconds


@dataclass(frozen=True, slots=True)
class StickerSend:
    """One content occurrence, keyed only within this analysis result.

    identity_key=None explicitly forbids material aggregation. An opaque QQ
    key groups equal source bytes, without claiming a decoded resource hash.
    is_self is the source's self marker, not a name or frequency inference.
    """

    occurrence_id: str
    source: str
    conversation_id: str | None = field(repr=False)
    conversation_type: str
    sender_id: str | None = field(repr=False)
    is_self: bool | None
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
    """One verified original, a distinct trusted preview, or an explicit failure.

    ``available`` is the digest-verified original. ``preview`` is content whose
    message and PIC element the kernel uniquely confirmed while its bytes do not
    match the message digest: displayable, never claimed as the original.
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
class StickerMessageCounts:
    """Message denominators for exactly the messages that produced the sends.

    Counts messages, not sticker contents: one message with several stickers
    contributes one message. ``unknown_messages`` covers senders whose source
    did not reliably say whether they were the local user.
    """

    self_messages: int = 0
    other_messages: int = 0
    unknown_messages: int = 0

    @property
    def total_messages(self) -> int:
        return self.self_messages + self.other_messages + self.unknown_messages


@dataclass(frozen=True, slots=True)
class StickerData:
    """Private in-process data channel; excluded from report serialization."""

    sends: tuple[StickerSend, ...] = field(default=(), repr=False)
    media: tuple[StickerMedia, ...] = field(default=(), repr=False)
    message_counts: StickerMessageCounts = field(default_factory=StickerMessageCounts)


def collect_sticker_sends(messages: Iterable[RichMessage]) -> tuple[StickerSend, ...]:
    """Collect only source-confirmed evidence from the already filtered Rich chain.

    A source may attach sticker evidence to a non-text image segment; the image
    remains a non-text fact for legacy statistics and is not reclassified here.
    """
    sends = []
    for message_index, message in enumerate(messages):
        moment = to_chat_datetime(message.timestamp)
        for content_index, part in enumerate(message.contents):
            if not isinstance(part, (ExpressionContent, NonTextContent)):
                continue
            evidence = part.sticker
            if evidence is None:
                continue
            occurrence_id = f"{message_index}:{content_index}"
            sends.append(StickerSend(
                occurrence_id=occurrence_id, source=message.source,
                conversation_id=message.conversation_id,
                conversation_type=message.conversation_type,
                sender_id=message.sender.identity_id, is_self=message.is_self,
                message_id=message.message_id,
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


def count_sticker_messages(messages: Iterable[RichMessage]) -> StickerMessageCounts:
    """Count each message once over the same scope that produced the sends.

    Pass the identical reusable message sequence to both collectors so the
    denominators and sends describe one filtered set. Unreliable or missing
    source self markers stay unknown; they are never inferred from names,
    frequency or participant count.
    """
    counts = [0, 0, 0]
    for message in messages:
        if message.is_self is True:
            counts[0] += 1
        elif message.is_self is False:
            counts[1] += 1
        else:
            counts[2] += 1
    return StickerMessageCounts(*counts)
