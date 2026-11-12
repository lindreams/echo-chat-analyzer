"""Per-run sticker facts. No source parsing, I/O or media selection."""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType

from ..rich_message import ExpressionContent, NonTextContent, RichMessage, TextContent
from .stickers import StickerConversationReport, StickerData, StickerSend, aggregate_stickers
from .timestamps import to_chat_datetime, to_epoch_seconds


@dataclass(frozen=True, slots=True)
class DayCounts:
    """Sparse dated counts, with half-open ordinal-day range queries."""

    days: tuple[int, ...] = ()
    prefix: tuple[int, ...] = (0,)

    @classmethod
    def from_counts(cls, counts: Mapping[int, int]) -> DayCounts:
        # Counter += 0 on a text-only day must not create a sticker usage day.
        days = tuple(sorted(day for day, count in counts.items() if count > 0))
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
    """Local evidence only: never serialize this index or its Rich messages.

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
    sticker_gap_starts: tuple[int, ...] | None = field(default=None, repr=False)
    sticker_gap_max_ends: tuple[int, ...] = field(default=(), repr=False)

    def has_gap(self, start: int, end: int, *, sticker_counts_only: bool = False) -> bool:
        starts, ends = self.gap_starts, self.gap_max_ends
        if sticker_counts_only and self.sticker_gap_starts is not None:
            starts, ends = self.sticker_gap_starts, self.sticker_gap_max_ends
        pos = bisect_left(starts, end)
        return pos > 0 and ends[pos-1] > start

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
    non_sticker_messages: Mapping[int, RichMessage] | None = None,
    conversation_kind: str = "private",
) -> StickerFactIndex:
    """Index exactly the ordered, formally filtered sequence behind ``data``.

    Supply original import positions to preserve filter / missing-Rich gaps.
    Missing provenance is not evidence of complete source history. A mismatched
    data/sequence is a caller error, never repaired by IDs or recollection.
    Existing aggregation remains the owner of members, materials and habits.
    ``non_sticker_messages`` supplies already-parsed excluded rows whose source
    semantics PROVE text-only content, not merely absent collected stickers.
    Only types/metadata are inspected; excluded rows are never retained here.
    Such evidence can clear sticker-count gaps, never conversation barriers.
    """
    messages = tuple(messages)
    scopes = {(m.source, m.conversation_type, m.conversation_id) for m in messages}
    if conversation_kind not in {"private", "group"}:
        raise ValueError("unsupported sticker conversation kind")
    private = conversation_kind == "private"
    if len(scopes) != 1 or not messages or messages[0].conversation_type != conversation_kind or not messages[0].conversation_id:
        return StickerFactIndex(False, f"not_single_{conversation_kind}_conversation")
    positions = tuple(range(len(messages))) if source_positions is None else tuple(source_positions)
    if len(positions) != len(messages) or any(type(p) is not int or p < 0 for p in positions) or any(a >= b for a, b in zip(positions, positions[1:])):
        raise ValueError("source positions must match ordered kept messages")
    non_sticker_messages = non_sticker_messages or {}
    if non_sticker_messages:
        kept_positions = set(positions)
        if source_positions is None or any(
                type(p) is not int or p < 0 or p in kept_positions for p in non_sticker_messages):
            raise ValueError("excluded evidence requires distinct original source positions")
    reports = aggregate_stickers(data, messages) if reports is None else reports
    if len(reports) != 1 or (reports[0].source, reports[0].conversation_type, reports[0].conversation_id) != next(iter(scopes)) or reports[0].total_send_count != len(data.sends) or reports[0].message_count != len(messages):
        raise ValueError("sticker report does not match message scope")
    report = reports[0]
    unavailable_reason = None
    if private:
        markers = defaultdict(set)
        for m in messages:
            if m.sender.identity_id:
                markers[m.sender.identity_id].add(m.is_self)
        if any(len(values) > 1 for values in markers.values()):
            unavailable_reason = "conflicting_private_identity"
    sides = tuple(tuple(m.sender_id for m in report.members if m.is_self is own) for own in (True, False))
    ambiguous_private_members = private and any(len(side) > 1 for side in sides)
    if ambiguous_private_members and unavailable_reason is None:
        unavailable_reason = "ambiguous_private_members"
    side_members = (
        tuple(side[0] if len(side) == 1 else None for side in sides)
        if private
        else (None, None)
    )
    reliable = (set(side_members) - {None}) if private else {m.sender_id for m in report.members}
    daily = {sender: [Counter() for _ in range(4)] for sender in reliable}
    material_sends = defaultdict(list)
    material_days = defaultdict(Counter)
    uncertain = []
    uncertain_days = defaultdict(Counter)
    undated_uncertainties = set()
    indexed = []
    days = []
    gaps = []
    sticker_gaps = []
    previous_epoch = None
    send_position = 0
    sticker_message_count = 0
    unattributed_send_count = 0
    for i, m in enumerate(messages):
        moment = to_chat_datetime(m.timestamp)
        # A numeric epoch outside datetime's calendar range is not usable time.
        # Preserve the collector's raw facts; only this index's usable time is None.
        send_epoch = to_epoch_seconds(m.timestamp)
        epoch = send_epoch if moment is not None else None
        day = moment.date().toordinal() if moment else None
        if day is not None:
            days.append(day)
        reasons = []
        if positions[i] != (positions[i-1]+1 if i else 0):
            reasons.append("filtered_or_unpaired_gap")
            if indexed:  # A left-truncated scope is not an interior gap.
                gaps.append((indexed[-1].day, day))
                left = indexed[-1]
                # Every omitted position needs independent source proof. An
                # unpaired row, empty/unknown/mixed content, unreliable member
                # or time leaves the entire conservative gap intact.
                proven = left.epoch_seconds is not None and epoch is not None
                for p in range(positions[i-1]+1, positions[i]):
                    excluded = non_sticker_messages.get(p)
                    if excluded is None:
                        proven = False
                        break
                    t = to_epoch_seconds(excluded.timestamp) if to_chat_datetime(excluded.timestamp) else None
                    side = (side_members[0] if excluded.is_self is True else
                            side_members[1] if excluded.is_self is False else None)
                    if (not proven or t is None or not left.epoch_seconds <= t <= epoch
                            or (excluded.source, excluded.conversation_type, excluded.conversation_id) not in scopes
                            or not excluded.sender.identity_id
                            or (private and (type(excluded.is_self) is not bool
                                or (side is not None and excluded.sender.identity_id != side)
                                or (excluded.sender.identity_id in reliable and excluded.sender.identity_id != side)))
                            or not excluded.contents or not all(isinstance(c, TextContent) for c in excluded.contents)):
                        proven = False
                        break
                if not proven:
                    sticker_gaps.append((left.day, day))
        if epoch is None:
            reasons.append("unknown_time")
        elif previous_epoch is not None and epoch <= previous_epoch:
            reasons.append("tied_or_reversed_time")
        if m.sender.identity_id not in reliable:
            reasons.append("unknown_side")
        chat_date = moment.date().isoformat() if moment else None
        associated_sends = []
        for content_index, part in enumerate(m.contents):
            if not isinstance(part, (ExpressionContent, NonTextContent)) or part.sticker is None:
                continue
            if send_position >= len(data.sends):
                raise ValueError("missing sticker occurrence for message scope")
            send = data.sends[send_position]
            send_position += 1
            if (send.occurrence_id != f"{i}:{content_index}" or send.content_index != content_index
                    or (send.source, send.conversation_type, send.conversation_id) != (m.source, m.conversation_type, m.conversation_id)
                    or send.sender_id != m.sender.identity_id or send.is_self is not m.is_self
                    or (send.timestamp is not m.timestamp and send.timestamp != m.timestamp)
                    or send.chat_date != chat_date or send.epoch_seconds != send_epoch
                    or send.identity_key != part.sticker.identity_key):
                raise ValueError("sticker occurrence does not match ordered message scope")
            associated_sends.append(send)
        ss = tuple(associated_sends)
        sticker_message_count += bool(ss)
        indexed.append(IndexedStickerMessage(i, positions[i], m, epoch, day, ss, bool(reasons), tuple(reasons)))
        sender = m.sender.identity_id
        if sender not in reliable:
            unattributed_send_count += len(ss)
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
    if send_position != len(data.sends):
        raise ValueError("extra sticker occurrences outside message scope")
    if unavailable_reason is not None:
        return StickerFactIndex(False, unavailable_reason)
    first, end = (min(days), max(days)+1) if days else (None, None)
    def bounds(ranges):
        ordered = sorted((min(a, b) if a is not None and b is not None else first,
                          max(a, b)+1 if a is not None and b is not None else end)
                         for a, b in ranges) if days else []
        ends = []
        for _, stop in ordered:
            ends.append(max(stop, ends[-1]) if ends else stop)
        return tuple(start for start, _ in ordered), tuple(ends)

    gap_starts, gap_ends = bounds(gaps)
    sticker_starts, sticker_ends = bounds(sticker_gaps)
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
        sticker_message_count=sticker_message_count, send_count=len(data.sends),
        unknown_identity_count=report.unknown_identity_count,
        unknown_sender_count=report.unknown_sender_count,
        unattributed_send_count=unattributed_send_count,
        first_day=first, end_day=end, source_positions_supplied=source_positions is not None,
        gap_starts=gap_starts, gap_max_ends=gap_ends,
        sticker_gap_starts=sticker_starts, sticker_gap_max_ends=sticker_ends,
    )
