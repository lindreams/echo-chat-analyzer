"""V1.1 private sticker discoveries; deterministic evidence, no story/UI or I/O.

All eligible candidates survive. Fields containing identities/occurrence refs
are private, in-process evidence, not a share-report serialization contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import heapq
from typing import Literal

from .sticker_index import DayCounts, StickerFactIndex
from .stickers import StickerHabit


RULE_VERSION = "private-stickers.v1.1-batch1"
ADOPTION_MIN_SENDS = 3
ADOPTION_MIN_DATES = 2
REUNION_MIN_GAP_DAYS = 28
REUNION_GAP_MULTIPLIER = 3
TREND_MIN_SENDS = 5


@dataclass(frozen=True, slots=True)
class StickerAdoption:
    identity_key: str = field(repr=False)
    media_key: str = field(repr=False)
    first_sender_id: str = field(repr=False)
    later_sender_id: str = field(repr=False)
    first_date: str
    later_first_date: str
    lag_days: int
    later_send_count: int
    later_date_count: int
    first_occurrence_id: str = field(repr=False)
    later_first_occurrence_id: str = field(repr=False)
    claim: str = "observed_order_only"


@dataclass(frozen=True, slots=True)
class StickerReunion:
    identity_key: str = field(repr=False)
    media_key: str = field(repr=False)
    sender_id: str = field(repr=False)
    previous_date: str
    return_date: str
    gap_days: int  # Date difference, NOT a count of full unused calendar days.
    previous_send_count: int
    previous_date_count: int
    previous_gap_median: float
    active_message_count: int
    active_date_count: int
    other_sticker_send_count: int
    other_sticker_date_count: int
    return_occurrence_id: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class StickerWindow:
    start_date: str
    end_date: str  # Exclusive, as are all range queries in this module.
    send_count: int
    date_count: int
    known_send_count: int
    known_date_count: int

    @property
    def share(self) -> float:
        return self.send_count / self.known_send_count if self.known_send_count else 0.0


@dataclass(frozen=True, slots=True)
class StickerTrend:
    identity_key: str = field(repr=False)
    media_key: str = field(repr=False)
    sender_id: str = field(repr=False)
    direction: Literal["rise", "fade"]
    window_days: int
    previous: StickerWindow
    current: StickerWindow
    earlier_send_count: int
    earlier_span_days: int


@dataclass(frozen=True, slots=True)
class StickerSignatureEvidence:
    habit: StickerHabit = field(repr=False)
    media_key: str = field(repr=False)
    frequency_rank: int
    overlaps_top3: bool
    long_term: bool
    story_eligible: bool
    is_selected_signature: bool


@dataclass(frozen=True, slots=True)
class PrivateStickerFeatures:
    available: bool
    unavailable_reason: str | None = None
    source: str | None = None
    conversation_id: str | None = field(default=None, repr=False)
    first_date: str | None = None
    end_date: str | None = None  # Exclusive observed-date boundary.
    adoptions: tuple[StickerAdoption, ...] = ()
    reunions: tuple[StickerReunion, ...] = ()
    trends: tuple[StickerTrend, ...] = ()
    signatures: tuple[StickerSignatureEvidence, ...] = ()
    qualifiers: tuple[str, ...] = (
        "filtered_observations_only", "history_may_be_truncated", "temporal_claims_use_known_dates",
    )
    rule_version: str = RULE_VERSION


def analyze_private_stickers(index: StickerFactIndex) -> PrivateStickerFeatures:
    """Analyze a shared fact index, independent of media success or UI limits."""
    if not index.available:
        return PrivateStickerFeatures(False, index.unavailable_reason)
    report = index.report
    qualifiers = ["filtered_observations_only", "history_may_be_truncated", "temporal_claims_use_known_dates"]
    if index.gap_starts:
        qualifiers.append("known_filter_gaps")
    if not index.source_positions_supplied:
        qualifiers.append("filter_gap_provenance_not_supplied")
    if index.uncertain_sends:
        qualifiers.append("unresolved_sticker_facts")
    return PrivateStickerFeatures(
        True, source=report.source, conversation_id=report.conversation_id,
        first_date=_iso(index.first_day), end_date=_iso(index.end_day),
        adoptions=_adoptions(index), reunions=_reunions(index),
        trends=_trends(index), signatures=_signatures(index), qualifiers=tuple(qualifiers),
    )


def _iso(day: int | None) -> str | None:
    return date.fromordinal(day).isoformat() if day is not None else None


def _adoptions(index: StickerFactIndex) -> tuple[StickerAdoption, ...]:
    own, other = index.side_members
    if own is None or other is None:
        return ()
    own_keys = {key for sender, key in index.materials if sender == own}
    other_keys = {key for sender, key in index.materials if sender == other}
    results = []
    for key in sorted(own_keys & other_keys):
        a, b = index.materials[own, key], index.materials[other, key]
        if a.has_unknown_time or b.has_unknown_time or not a.chronological or not b.chronological:
            continue
        if key in index.uncertain_material_keys:
            continue
        first, later = (a, b) if a.sends[0].epoch_seconds < b.sends[0].epoch_seconds else (b, a)
        left, right = first.dated.days[0], later.dated.days[0]
        if left == right or index.has_gap(left, right+1):
            continue
        if len(later.sends) < ADOPTION_MIN_SENDS or len(later.dated.days) < ADOPTION_MIN_DATES:
            continue
        src, dst = first.sends[0], later.sends[0]
        # The collector's occurrence ordinal was validated against the complete
        # kept sequence by the index. Do not repair conflicting source order.
        if int(src.occurrence_id.partition(":")[0]) >= int(dst.occurrence_id.partition(":")[0]):
            continue
        results.append(StickerAdoption(key, src.media_key, src.sender_id, dst.sender_id,
                                       src.chat_date, dst.chat_date, right-left,
                                       len(later.sends), len(later.dated.days), src.occurrence_id, dst.occurrence_id))
    return tuple(sorted(results, key=lambda f: (-f.later_date_count, -f.lag_days, f.identity_key)))


def _reunions(index: StickerFactIndex) -> tuple[StickerReunion, ...]:
    results = []
    for (sender, key), timeline in index.materials.items():
        if timeline.has_unknown_time or not timeline.chronological:
            continue
        days, prefix = timeline.dated.days, timeline.dated.prefix
        low, high = [], []  # Running median of PREVIOUS usage-day gaps only.
        first_by_day = {}
        for send in timeline.sends:
            first_by_day.setdefault(date.fromisoformat(send.chat_date).toordinal(), send)
        member = index.members[sender]
        for pos in range(1, len(days)):
            if pos >= 2:
                gap = days[pos-1]-days[pos-2]
                heapq.heappush(low, -gap)
                heapq.heappush(high, -heapq.heappop(low))
                if len(high) > len(low):
                    heapq.heappush(low, -heapq.heappop(high))
            if pos < 2 or prefix[pos] < 3:
                continue
            median = float(-low[0]) if len(low) > len(high) else (-low[0]+high[0])/2
            gap = days[pos]-days[pos-1]
            if gap < max(REUNION_MIN_GAP_DAYS, REUNION_GAP_MULTIPLIER*median):
                continue
            start, end = days[pos-1]+1, days[pos]  # Exclude both endpoint dates.
            if index.has_gap(start, end) or index.has_uncertain_use(sender, key, start, end):
                continue
            msgs = member.messages.count(start, end)
            msg_days = member.messages.date_count(start, end)
            others = member.known_sends.count(start, end)
            other_days = member.known_sends.date_count(start, end)
            if not ((msgs >= 20 and msg_days >= 3) or (others >= 3 and other_days >= 2)):
                continue
            returned = first_by_day[days[pos]]
            results.append(StickerReunion(key, returned.media_key, sender,
                                          _iso(days[pos-1]), _iso(days[pos]), gap, prefix[pos], pos, median,
                                          msgs, msg_days, others, other_days, returned.occurrence_id))
    return tuple(sorted(results, key=lambda f: (-f.gap_days, f.return_date, f.sender_id, f.identity_key)))


def _window(material: DayCounts, total: DayCounts, start: int, end: int) -> StickerWindow:
    return StickerWindow(_iso(start), _iso(end), material.count(start, end),
                         material.date_count(start, end), total.count(start, end), total.date_count(start, end))


def _trends(index: StickerFactIndex) -> tuple[StickerTrend, ...]:
    if index.first_day is None or index.end_day-index.first_day < 14:
        return ()
    first, end = index.first_day, index.end_day
    width = 30 if end-first >= 60 else 7
    stops = sorted({*range(first+2*width, end+1, 7), end})
    results = []
    for (sender, key), timeline in index.materials.items():
        if timeline.has_unknown_time:
            continue
        total = index.members[sender].known_sends
        for stop in stops:
            middle, start = stop-width, stop-2*width
            if index.has_gap(start, stop):
                continue
            before, after = _window(timeline.dated, total, start, middle), _window(timeline.dated, total, middle, stop)
            a, c = before.send_count, after.send_count
            p, q = before.share, after.share
            rise = (before.known_send_count >= 3 and c >= TREND_MIN_SENDS and after.date_count >= 2
                    and c >= 3*max(1, a) and (q >= 2*p if p else q >= .10))
            fade = (a >= TREND_MIN_SENDS and before.date_count >= 2 and c <= a/3
                    and after.known_send_count >= 5 and after.known_date_count >= 2 and p >= 2*q
                    and not index.has_uncertain_use(sender, key, middle, stop))
            if rise or fade:
                results.append(StickerTrend(key, timeline.sends[0].media_key, sender,
                                             "rise" if rise else "fade", width, before, after,
                                             timeline.dated.count(first, middle), middle-first))
    return tuple(sorted(results, key=lambda f: (-abs(f.current.send_count-f.previous.send_count),
                                               -date.fromisoformat(f.current.end_date).toordinal(),
                                               f.identity_key, f.sender_id, f.direction)))


def _signatures(index: StickerFactIndex) -> tuple[StickerSignatureEvidence, ...]:
    report = index.report
    results = []
    for sender in index.members:
        selected = report.signature(sender)
        ranks = {m.identity_key: (i, m.media_key) for i, (m, _) in enumerate(report.ranking(sender), 1)}
        for habit in report.habits:
            if habit.sender_id != sender or not habit.qualified:
                continue
            rank, media = ranks[habit.identity_key]
            results.append(StickerSignatureEvidence(habit, media, rank, rank <= 3,
                                                     habit.span_days >= 180, habit.span_days >= 180 or rank > 3,
                                                     selected is not None and selected.identity_key == habit.identity_key))
    return tuple(results)
