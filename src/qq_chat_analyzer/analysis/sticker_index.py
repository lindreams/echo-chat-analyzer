"""Private, per-run sticker facts. No source parsing, I/O or media selection."""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType

from ..rich_message import ExpressionContent, NonTextContent, RichMessage
from .stickers import StickerConversationReport, StickerData, StickerSend, aggregate_stickers
from .timestamps import to_chat_datetime, to_epoch_seconds


@dataclass(frozen=True, slots=True)
class DayCounts:
    """Sparse dated counts, with half-open ordinal-day range queries."""

    days: tuple[int, ...] = ()
    prefix: tuple[int, ...] = (0,)

    @classmethod
    def from_counts(cls, counts: Mapping[int, int]) -> DayCounts:
        days = tuple(sorted(counts))
        prefix = [0]
        for day in days:
            prefix.append(prefix[-1] + counts[day])
        return cls(days, tuple(prefix))

    @property
    def total(self) -> int:
        return self.prefix[-1]

    def count(self, start: int, end: int) -> int:
        return self.prefix[bisect_left(self.days, end)] - self.prefix[bisect_left(self.days, start)]

    def date_count(self, start: int, end: int) -> int:
        return bisect_left(self.days, end) - bisect_left(self.days, start)


@dataclass(frozen=True, slots=True)
class IndexedStickerMessage:
    ordinal: int
    source_position: int
    message: RichMessage = field(repr=False)
    epoch_seconds: int | None
    day: int | None
    sends: tuple[StickerSend, ...] = field(repr=False)
    barrier_before: bool
    barrier_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemberStickerDays:
    messages: DayCounts
    sticker_messages: DayCounts
    sends: DayCounts
    known_sends: DayCounts


@dataclass(frozen=True, slots=True)
class MaterialTimeline:
    sends: tuple[StickerSend, ...] = field(repr=False)
    dated: DayCounts
    has_unknown_time: bool
    chronological: bool


@dataclass(frozen=True, slots=True)
class StickerFactIndex:
    """Private facts only: never serialize this index or its Rich messages.

    An ordinal refers to the kept Rich sequence; source_position refers to the
    imported projection sequence. Neither is a cross-run message identity.
    Counts in DayCounts exclude undated occurrences, not unknown identities.
    """

    available: bool
    unavailable_reason: str | None = None
    report: StickerConversationReport | None = field(default=None, repr=False)
    messages: tuple[IndexedStickerMessage, ...] = field(default=(), repr=False)
    members: Mapping[str, MemberStickerDays] = field(default_factory=lambda: MappingProxyType({}), repr=False)
    materials: Mapping[tuple[str, str], MaterialTimeline] = field(default_factory=lambda: MappingProxyType({}), repr=False)
    side_members: tuple[str | None, str | None] = field(default=(None, None), repr=False)
    uncertain_sends: tuple[StickerSend, ...] = field(default=(), repr=False)
    uncertain_days: Mapping[tuple[str | None, str | None], DayCounts] = field(default_factory=lambda: MappingProxyType({}), repr=False)
    undated_uncertainties: frozenset[tuple[str | None, str | None]] = field(default_factory=frozenset, repr=False)
    uncertain_material_keys: frozenset[str] = field(default_factory=frozenset, repr=False)
    message_count: int = 0
    sticker_message_count: int = 0
    send_count: int = 0
    unknown_identity_count: int = 0
    unknown_sender_count: int = 0
    unattributed_send_count: int = 0
    first_day: int | None = None
    end_day: int | None = None  # Exclusive; includes text-only boundary days.
    source_positions_supplied: bool = False
    # Sorted filter-gap starts and cumulative maximum exclusive ends: overlap
    # queries are logarithmic, including gaps whose endpoints run backwards.
    gap_starts: tuple[int, ...] = field(default=(), repr=False)
    gap_max_ends: tuple[int, ...] = field(default=(), repr=False)

    def has_gap(self, start: int, end: int) -> bool:
        pos = bisect_left(self.gap_starts, end)
        return pos > 0 and self.gap_max_ends[pos-1] > start

    def has_uncertain_use(self, sender: str, key: str, start: int, end: int) -> bool:
        # Unknowns are indexed for uncertainty queries only, NEVER aggregated
        # into a fictitious material or assigned to a participant.
        for pair in ((sender, key), (sender, None), (None, key), (None, None)):
            if pair in self.undated_uncertainties:
                return True
            series = self.uncertain_days.get(pair)
            if series is not None and series.count(start, end):
                return True
        return False


def build_sticker_fact_index(
    data: StickerData, messages: Sequence[RichMessage], *,
    reports: tuple[StickerConversationReport, ...] | None = None,
    source_positions: Sequence[int] | None = None,
) -> StickerFactIndex:
    """Index exactly the ordered, formally filtered sequence behind ``data``.

    Supply original import positions to preserve filter / missing-Rich gaps.
    Missing provenance is not evidence of complete source history. A mismatched
    data/sequence is a caller error, never repaired by IDs or recollection.
    Existing aggregation remains the owner of members, materials and habits.
    """
    messages = tuple(messages)
    scopes = {(m.source, m.conversation_type, m.conversation_id) for m in messages}
    if len(scopes) != 1 or not messages or messages[0].conversation_type != "private" or not messages[0].conversation_id:
        return StickerFactIndex(False, "not_single_private_conversation")
    positions = tuple(range(len(messages))) if source_positions is None else tuple(source_positions)
    if len(positions) != len(messages) or any(type(p) is not int or p < 0 for p in positions) or any(a >= b for a, b in zip(positions, positions[1:])):
        raise ValueError("source positions must match ordered kept messages")
    by_message = _associate_occurrences(data.sends, messages)
    reports = aggregate_stickers(data, messages) if reports is None else reports
    if len(reports) != 1 or (reports[0].source, reports[0].conversation_type, reports[0].conversation_id) != next(iter(scopes)) or reports[0].total_send_count != len(data.sends) or reports[0].message_count != len(messages):
        raise ValueError("sticker report does not match message scope")
    report = reports[0]
    markers = defaultdict(set)
    for m in messages:
        if m.sender.identity_id:
            markers[m.sender.identity_id].add(m.is_self)
    if any(len(values) > 1 for values in markers.values()):
        return StickerFactIndex(False, "conflicting_private_identity")
    sides = tuple(tuple(m.sender_id for m in report.members if m.is_self is own) for own in (True, False))
    if any(len(side) > 1 for side in sides):
        return StickerFactIndex(False, "ambiguous_private_members")
    side_members = tuple(side[0] if side else None for side in sides)
    reliable = set(side_members) - {None}
    daily = {sender: [Counter() for _ in range(4)] for sender in reliable}
    material_sends = defaultdict(list)
    material_days = defaultdict(Counter)
    uncertain = []
    uncertain_days = defaultdict(Counter)
    undated_uncertainties = set()
    indexed = []
    days = []
    gaps = []
    previous_epoch = None
    for i, m in enumerate(messages):
        moment = to_chat_datetime(m.timestamp)
        # A numeric epoch outside datetime's calendar range is not usable time.
        # Preserve the collector's raw facts; only this index's usable time is None.
        epoch = to_epoch_seconds(m.timestamp) if moment is not None else None
        day = moment.date().toordinal() if moment else None
        if day is not None:
            days.append(day)
        reasons = []
        if positions[i] != (positions[i-1]+1 if i else 0):
            reasons.append("filtered_or_unpaired_gap")
            if indexed:  # A left-truncated scope is not an interior gap.
                gaps.append((indexed[-1].day, day))
        if epoch is None:
            reasons.append("unknown_time")
        elif previous_epoch is not None and epoch <= previous_epoch:
            reasons.append("tied_or_reversed_time")
        if m.sender.identity_id not in reliable:
            reasons.append("unknown_side")
        ss = tuple(by_message[i])
        indexed.append(IndexedStickerMessage(i, positions[i], m, epoch, day, ss, bool(reasons), tuple(reasons)))
        sender = m.sender.identity_id
        if sender in reliable and day is not None:
            daily[sender][0][day] += 1
            if ss:
                daily[sender][1][day] += 1
            daily[sender][2][day] += len(ss)
            daily[sender][3][day] += sum(bool(s.identity_key) for s in ss)
        for s in ss:
            if sender in reliable and s.identity_key:
                material_sends[sender, s.identity_key].append(s)
                if day is not None:
                    material_days[sender, s.identity_key][day] += 1
            if sender not in reliable or not s.identity_key or day is None:
                # A reliable sender with unknown self context cannot silently
                # become the other participant in absence-sensitive claims.
                uncertain.append(s)
                pair = (sender if sender in reliable else None, s.identity_key or None)
                if day is None:
                    undated_uncertainties.add(pair)
                else:
                    uncertain_days[pair][day] += 1
        previous_epoch = epoch
    first, end = (min(days), max(days)+1) if days else (None, None)
    gap_ranges = sorted((min(a, b) if a is not None and b is not None else first,
                         max(a, b)+1 if a is not None and b is not None else end)
                        for a, b in gaps) if days else []
    max_ends = []
    for _, stop in gap_ranges:
        max_ends.append(max(stop, max_ends[-1]) if max_ends else stop)
    materials = {}
    for pair, ss in material_sends.items():
        epochs = [s.epoch_seconds for s in ss if s.epoch_seconds is not None]
        materials[pair] = MaterialTimeline(
            tuple(ss), DayCounts.from_counts(material_days[pair]),
            any(s.epoch_seconds is None or s.chat_date is None for s in ss),
            all(a <= b for a, b in zip(epochs, epochs[1:])),
        )
    return StickerFactIndex(
        available=True, report=report, messages=tuple(indexed),
        members=MappingProxyType({sender: MemberStickerDays(*(DayCounts.from_counts(c) for c in counts))
                                  for sender, counts in sorted(daily.items())}),
        materials=MappingProxyType(dict(sorted(materials.items()))), side_members=side_members,
        uncertain_sends=tuple(uncertain), message_count=len(messages),
        uncertain_days=MappingProxyType({pair: DayCounts.from_counts(c) for pair, c in uncertain_days.items()}),
        undated_uncertainties=frozenset(undated_uncertainties),
        uncertain_material_keys=frozenset(s.identity_key for s in uncertain if s.identity_key),
        sticker_message_count=sum(bool(ss) for ss in by_message), send_count=len(data.sends),
        unknown_identity_count=report.unknown_identity_count,
        unknown_sender_count=report.unknown_sender_count,
        unattributed_send_count=sum(len(ss) for m, ss in zip(messages, by_message) if m.sender.identity_id not in reliable),
        first_day=first, end_day=end, source_positions_supplied=source_positions is not None,
        gap_starts=tuple(start for start, _ in gap_ranges), gap_max_ends=tuple(max_ends),
    )


def _associate_occurrences(sends: tuple[StickerSend, ...], messages: tuple[RichMessage, ...]) -> list[list[StickerSend]]:
    """Validate the existing collector's per-content sequence, not message IDs."""
    by_message = [[] for _ in messages]
    position = 0
    for ordinal, message in enumerate(messages):
        moment = to_chat_datetime(message.timestamp)
        chat_date = moment.date().isoformat() if moment else None
        epoch = to_epoch_seconds(message.timestamp)
        for content_index, part in enumerate(message.contents):
            if not isinstance(part, (ExpressionContent, NonTextContent)) or part.sticker is None:
                continue
            if position >= len(sends):
                raise ValueError("missing sticker occurrence for message scope")
            send = sends[position]
            position += 1
            if (send.occurrence_id != f"{ordinal}:{content_index}" or send.content_index != content_index
                    or (send.source, send.conversation_type, send.conversation_id) != (message.source, message.conversation_type, message.conversation_id)
                    or send.sender_id != message.sender.identity_id or send.is_self is not message.is_self
                    or (send.timestamp is not message.timestamp and send.timestamp != message.timestamp)
                    or send.chat_date != chat_date or send.epoch_seconds != epoch
                    or send.identity_key != part.sticker.identity_key):
                raise ValueError("sticker occurrence does not match ordered message scope")
            by_message[ordinal].append(send)
    if position != len(sends):
        raise ValueError("extra sticker occurrences outside message scope")
    return by_message
