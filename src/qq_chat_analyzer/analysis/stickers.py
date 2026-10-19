"""Confirmed sticker facts and scoped aggregation; no media acquisition."""
from __future__ import annotations

from collections.abc import Iterable
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

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


@dataclass(frozen=True, slots=True)
class StickerParticipant:
    sender_id: str = field(repr=False)
    is_self: bool | None
    message_count: int
    send_count: int

    @property
    def per_hundred_messages(self) -> float | None:
        return 100 * self.send_count / self.message_count if self.message_count else None


@dataclass(frozen=True, slots=True)
class StickerMaterialUsage:
    identity_key: str = field(repr=False)
    media_key: str = field(repr=False)
    count: int
    member_counts: tuple[tuple[str, int], ...] = field(repr=False)
    unknown_sender_count: int = 0

    @property
    def reliable_member_count(self) -> int:
        return len(self.member_counts)


# Experimental conjunction, not a score. Keep all calibration in one place.
SIGNATURE_MIN_SENDS = 4
SIGNATURE_MIN_DATES = 4
SIGNATURE_MIN_SPAN_DAYS = 28
SIGNATURE_MIN_WEEKS = 4
SIGNATURE_MIN_SHARE = 0.10


@dataclass(frozen=True, slots=True)
class StickerHabit:
    sender_id: str = field(repr=False)
    identity_key: str = field(repr=False)
    send_count: int
    dated_send_count: int
    date_count: int
    span_days: int
    week_count: int
    share: float
    first_date: str | None
    last_date: str | None
    rejection_reasons: tuple[str, ...]

    @property
    def qualified(self) -> bool:
        return not self.rejection_reasons


@dataclass(frozen=True, slots=True)
class StickerConversationReport:
    source: str
    conversation_id: str | None = field(repr=False)
    conversation_type: str
    message_count: int
    total_send_count: int
    unknown_identity_count: int
    unknown_sender_count: int
    members: tuple[StickerParticipant, ...] = ()
    materials: tuple[StickerMaterialUsage, ...] = ()
    habits: tuple[StickerHabit, ...] = ()

    def ranking(self, sender_id: str | None = None) -> tuple[tuple[StickerMaterialUsage, int], ...]:
        """Complete frequency order; ties use reliable opaque material identity."""
        return _rank_materials((item, item.count if sender_id is None else
                                dict(item.member_counts).get(sender_id, 0))
                               for item in self.materials)

    def shared_ranking(self, sender_ids: tuple[str, ...] = ()) -> tuple[tuple[StickerMaterialUsage, int], ...]:
        """Sum actual reliable member sends, excluding unknown senders."""
        sender_ids = tuple(dict.fromkeys(sender_ids))
        rows = []
        for item in self.materials:
            counts = dict(item.member_counts)
            if sender_ids:
                if len(sender_ids) < 2 or not all(counts.get(sender) for sender in sender_ids):
                    continue
                count = sum(counts[sender] for sender in sender_ids)
            else:
                if item.reliable_member_count < 2:
                    continue
                count = sum(counts.values())
            rows.append((item, count))
        return _rank_materials(rows)

    def signature(self, sender_id: str) -> StickerHabit | None:
        candidates = [h for h in self.habits if h.sender_id == sender_id and h.qualified]
        # Prefer repeated dates, then weeks, span, sends and share; no weighted score.
        return min(candidates, key=lambda h: (-h.date_count, -h.week_count, -h.span_days,
                                             -h.send_count, -h.share, h.identity_key), default=None)

    def exclusive_material_count(self, sender_id: str | None = None) -> int:
        return sum(item.reliable_member_count == 1 and not item.unknown_sender_count and
                   (sender_id is None or item.member_counts[0][0] == sender_id)
                   for item in self.materials)


def _rank_materials(rows):
    return tuple(sorted((row for row in rows if row[1] > 0),
                        key=lambda row: (-row[1], row[0].identity_key)))


def _sticker_habits(sends: list[StickerSend]) -> tuple[StickerHabit, ...]:
    groups = defaultdict(list)
    denominators = Counter()
    for send in sends:
        if send.sender_id and send.identity_key:
            groups[send.sender_id, send.identity_key].append(send)
            denominators[send.sender_id] += 1
    habits = []
    for (sender, key), group in sorted(groups.items()):
        days = []
        for send in group:
            try:
                days.append(date.fromisoformat(send.chat_date))
            except (TypeError, ValueError):
                pass
        dates = set(days)
        span = (max(dates) - min(dates)).days if dates else 0
        weeks = len({day.isocalendar()[:2] for day in dates})
        share = len(group) / denominators[sender]
        reasons = tuple(name for name, value, minimum in (
            ("N", len(group), SIGNATURE_MIN_SENDS), ("D", len(dates), SIGNATURE_MIN_DATES),
            ("S", span, SIGNATURE_MIN_SPAN_DAYS), ("W", weeks, SIGNATURE_MIN_WEEKS),
            ("P", share, SIGNATURE_MIN_SHARE),
        ) if value < minimum)
        habits.append(StickerHabit(sender, key, len(group), len(days), len(dates), span,
                                   weeks, share, min(dates).isoformat() if dates else None,
                                   max(dates).isoformat() if dates else None, reasons))
    return tuple(habits)


def aggregate_stickers(
    data: StickerData, messages: Iterable[RichMessage],
) -> tuple[StickerConversationReport, ...]:
    """Aggregate exactly one filtered Rich scope, retaining every send.

    Materials and participants are local to (source, conversation type, ID).
    Missing conversation IDs cannot establish a shared identity namespace.
    Unknown material/sender identities contribute totals without becoming a
    shared 'unknown' bucket. All participants remain available to consumers;
    the private report's two-side selection belongs to presentation.
    """
    message_groups = defaultdict(list)
    send_groups = defaultdict(list)
    for message in messages:
        message_groups[(message.source, message.conversation_type, message.conversation_id)].append(message)
    for send in data.sends:
        send_groups[(send.source, send.conversation_type, send.conversation_id)].append(send)
    reports = []
    for scope in dict.fromkeys((*message_groups, *send_groups)):
        source, conversation_type, conversation_id = scope
        scoped_messages, sends = message_groups[scope], send_groups[scope]
        message_counts = Counter()
        send_counts = Counter()
        markers = defaultdict(set)
        material_groups = defaultdict(list)
        if conversation_id:
            for message in scoped_messages:
                sender = message.sender.identity_id
                if sender:
                    message_counts[sender] += 1
                    markers[sender].add(message.is_self)
            for send in sends:
                if send.sender_id:
                    send_counts[send.sender_id] += 1
                    markers[send.sender_id].add(send.is_self)
                if send.identity_key:
                    material_groups[send.identity_key].append(send)
        materials = tuple(
            StickerMaterialUsage(
                identity_key=key, media_key=group[0].media_key, count=len(group),
                member_counts=tuple(sorted(Counter(s.sender_id for s in group if s.sender_id).items())),
                unknown_sender_count=sum(not s.sender_id for s in group),
            )
            for key, group in material_groups.items()
        )
        reports.append(StickerConversationReport(
            source=source, conversation_id=conversation_id, conversation_type=conversation_type,
            message_count=len(scoped_messages), total_send_count=len(sends),
            unknown_identity_count=sum(not s.identity_key or not conversation_id for s in sends),
            unknown_sender_count=sum(not s.sender_id or not conversation_id for s in sends),
            members=tuple(StickerParticipant(
                sender_id=sender, is_self=next(iter(values)) if len(values) == 1 else None,
                message_count=message_counts[sender], send_count=send_counts[sender],
            ) for sender, values in markers.items()),
            materials=materials,
            habits=_sticker_habits(sends) if conversation_id else (),
        ))
    return tuple(reports)


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
