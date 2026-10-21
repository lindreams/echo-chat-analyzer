"""V1.1 private sticker discoveries; deterministic evidence, no UI or I/O.

All eligible candidates survive. Fields containing identities/occurrence refs
are private, in-process evidence, not a share-report serialization contract.
"""
from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
import heapq
from math import fsum
from typing import Literal

from .sticker_index import DayCounts, IndexedStickerMessage, StickerFactIndex
from .stickers import StickerHabit
from .sticker_stories import StickerStorySelection, select_sticker_stories
from .conversation_sessions import DEFAULT_SESSION_THRESHOLD_SECONDS


RULE_VERSION = "private-stickers.v1.1-batch2"
ADOPTION_MIN_SENDS = 3
ADOPTION_MIN_DATES = 2
REUNION_MIN_GAP_DAYS = 28
REUNION_GAP_MULTIPLIER = 3
TREND_MIN_SENDS = 5
SHARED_MIN_SENDS = 3
SHARED_MIN_DATES = 2
SHARED_MIN_SHARE = .10
RELAY_MIN_TURNS = 4
RELAY_MAX_GAP_SECONDS = 120
RELAY_MAX_SECONDS = 600
STYLE_MIN_SENDS = 10
STYLE_MIN_DATES = 2
STYLE_MAX_SAMPLE = 100
STYLE_MIN_RICHNESS_RATIO = 1.8
STYLE_MIN_RICHNESS_DIFFERENCE = 3
STYLE_MIN_D2_RATIO = 1.5


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
class StickerRelayTurn:
    # References to the existing index preserve ALL contents, including text.
    # Private local evidence only: never pass this to a report serializer.
    messages: tuple[IndexedStickerMessage, ...] = field(repr=False)
    send_count: int

    @property
    def sender_id(self) -> str:
        return self.messages[0].message.sender.identity_id

    @property
    def start_epoch_seconds(self) -> int:
        return self.messages[0].epoch_seconds

    @property
    def end_epoch_seconds(self) -> int:
        return self.messages[-1].epoch_seconds


@dataclass(frozen=True, slots=True)
class StickerRelayMaterial:
    identity_key: str = field(repr=False)
    media_key: str = field(repr=False)
    self_send_count: int
    peer_send_count: int
    occurrence_ids: tuple[str, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class StickerRelay:
    start_ordinal: int
    end_ordinal: int  # Exclusive, within this analysis run only.
    start_epoch_seconds: int
    end_epoch_seconds: int
    turns: tuple[StickerRelayTurn, ...] = field(repr=False)
    self_send_count: int
    peer_send_count: int
    materials: tuple[StickerRelayMaterial, ...] = field(repr=False)
    media_keys: tuple[str, ...] = field(repr=False)
    unknown_identity_count: int
    start_barrier_reasons: tuple[str, ...]
    end_barrier_reasons: tuple[str, ...]

    @property
    def turn_count(self) -> int:
        return len(self.turns)


@dataclass(frozen=True, slots=True)
class SharedStickerUse:
    sender_id: str = field(repr=False)
    send_count: int
    date_count: int
    known_send_count: int  # Includes reliable material sends with unknown dates.
    first_date: str | None
    last_date: str | None
    has_unknown_time: bool

    @property
    def share(self) -> float:
        return self.send_count / self.known_send_count


@dataclass(frozen=True, slots=True)
class SharedStickerHabit:
    identity_key: str = field(repr=False)
    media_key: str = field(repr=False)
    members: tuple[SharedStickerUse, SharedStickerUse]
    # Keep both stories and their exact link; selection is a later concern.
    adoption: StickerAdoption | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class StickerStyleMember:
    sender_id: str = field(repr=False)
    known_send_count: int
    unknown_identity_send_count: int
    date_count: int
    raw_unique_count: int
    expected_unique_count: float
    d2: float


@dataclass(frozen=True, slots=True)
class StickerStyleComparison:
    sample_size: int
    richer: StickerStyleMember
    concentrated: StickerStyleMember
    unattributed_send_count: int
    claim: str = "known_materials_only"
    min_richness_ratio: float = STYLE_MIN_RICHNESS_RATIO
    min_richness_difference: int = STYLE_MIN_RICHNESS_DIFFERENCE
    min_d2_ratio: float = STYLE_MIN_D2_RATIO


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
    relays: tuple[StickerRelay, ...] = ()
    shared_habits: tuple[SharedStickerHabit, ...] = ()
    styles: tuple[StickerStyleComparison, ...] = ()
    stories: StickerStorySelection = field(default_factory=StickerStorySelection, repr=False)


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
    # Reuse complete reliable timelines for K, never dated-only DayCounts.total.
    counts = {sender: {} for sender in index.members}
    for (sender, key), timeline in index.materials.items():
        counts[sender][key] = len(timeline.sends)
    adoptions = _adoptions(index)
    features = PrivateStickerFeatures(
        True, source=report.source, conversation_id=report.conversation_id,
        first_date=_iso(index.first_day), end_date=_iso(index.end_day),
        adoptions=adoptions, reunions=_reunions(index),
        trends=_trends(index), signatures=_signatures(index), qualifiers=tuple(qualifiers),
        relays=_relays(index), shared_habits=_shared_habits(index, counts, adoptions),
        styles=_styles(index, counts),
    )
    return replace(features, stories=select_sticker_stories(index, features))


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
        if not a.chronological or not b.chronological or not a.dated.days or not b.dated.days:
            continue
        # First *dated, attributable* observations. An undated send by the
        # already-first member cannot reverse direction; one by the later or
        # an unknown member can. Do not extrapolate actual historical adoption.
        a_first = next(s for s in a.sends if s.chat_date is not None)
        b_first = next(s for s in b.sends if s.chat_date is not None)
        first, later = (a, b) if a_first.epoch_seconds < b_first.epoch_seconds else (b, a)
        src, dst = (a_first, b_first) if first is a else (b_first, a_first)
        if any(s.identity_key in (None, key)
               and (s.sender_id not in index.members or s.sender_id == dst.sender_id)
               and (s.chat_date is None or s.epoch_seconds <= src.epoch_seconds)
               for s in index.uncertain_sends):
            continue
        left, right = first.dated.days[0], later.dated.days[0]
        if left == right or index.has_gap(left, right+1):
            continue
        if len(later.sends) < ADOPTION_MIN_SENDS or len(later.dated.days) < ADOPTION_MIN_DATES:
            continue
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
                    and c >= 3*max(1, a) and (q >= 2*p if p else q >= .10)
                    and not index.has_uncertain_use(sender, key, start, middle))
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


def _author_turns(index: StickerFactIndex) -> Iterator[StickerRelayTurn]:
    messages = []
    for message in index.messages:
        sender = message.message.sender.identity_id
        if messages and (message.barrier_before or sender != messages[-1].message.sender.identity_id
                         or (message.epoch_seconds is not None
                             and message.epoch_seconds-messages[-1].epoch_seconds > DEFAULT_SESSION_THRESHOLD_SECONDS)):
            yield StickerRelayTurn(tuple(messages), sum(len(m.sends) for m in messages))
            messages = []
        if sender in index.members and message.epoch_seconds is not None:
            messages.append(message)
    if messages:
        yield StickerRelayTurn(tuple(messages), sum(len(m.sends) for m in messages))


def _relay_evidence(index: StickerFactIndex, turns: tuple[StickerRelayTurn, ...]) -> StickerRelay:
    sends = [s for turn in turns for m in turn.messages for s in m.sends]
    own, peer = index.side_members
    materials = {}
    for send in sends:
        if send.identity_key:
            materials.setdefault(send.identity_key, []).append(send)
    start, end = turns[0].messages[0].ordinal, turns[-1].messages[-1].ordinal+1
    return StickerRelay(
        start, end, turns[0].start_epoch_seconds, turns[-1].end_epoch_seconds, turns,
        sum(s.sender_id == own for s in sends), sum(s.sender_id == peer for s in sends),
        tuple(StickerRelayMaterial(key, ss[0].media_key,
                                  sum(s.sender_id == own for s in ss), sum(s.sender_id == peer for s in ss),
                                  tuple(s.occurrence_id for s in ss)) for key, ss in sorted(materials.items())),
        tuple(dict.fromkeys(s.media_key for s in sends)), sum(not s.identity_key for s in sends),
        index.messages[start].barrier_reasons,
        index.messages[end].barrier_reasons if end < len(index.messages) else (),
    )


def _relays(index: StickerFactIndex) -> tuple[StickerRelay, ...]:
    # Without original positions we cannot establish that filtering left the
    # observed conversation contiguous. Counting habits needs no such claim.
    if not index.source_positions_supplied or None in index.side_members:
        return ()
    window = deque()
    results = []

    def emit():
        if len(window) >= RELAY_MIN_TURNS:
            results.append(_relay_evidence(index, tuple(window)))

    for turn in _author_turns(index):
        if window:
            previous = window[-1]
            gap = turn.start_epoch_seconds-previous.end_epoch_seconds
            if (not turn.send_count or turn.messages[0].barrier_before
                    or previous.messages[-1].ordinal+1 != turn.messages[0].ordinal
                    or turn.sender_id == previous.sender_id or not 0 < gap <= RELAY_MAX_GAP_SECONDS):
                emit()
                window.clear()
        if not turn.send_count:
            continue
        if window and turn.end_epoch_seconds-window[0].start_epoch_seconds > RELAY_MAX_SECONDS:
            # Emit the maximal window BEFORE advancing. Do not generate every
            # ABAB prefix, trim a turn, or discard distinct overlapping events.
            emit()
            while window and turn.end_epoch_seconds-window[0].start_epoch_seconds > RELAY_MAX_SECONDS:
                window.popleft()
        if turn.end_epoch_seconds-turn.start_epoch_seconds <= RELAY_MAX_SECONDS:
            window.append(turn)
    emit()
    return tuple(sorted(results, key=lambda r: (-r.turn_count, -min(r.self_send_count, r.peer_send_count),
                                                r.start_ordinal, r.end_ordinal)))


def _shared_habits(index: StickerFactIndex, counts: dict[str, dict[str, int]],
                   adoptions: tuple[StickerAdoption, ...]) -> tuple[SharedStickerHabit, ...]:
    own, peer = index.side_members
    if own is None or peer is None:
        return ()
    totals = {sender: sum(values.values()) for sender, values in counts.items()}
    adoption_by_key = {a.identity_key: a for a in adoptions}
    results = []
    for key in counts[own].keys() & counts[peer].keys():
        uses = []
        for sender in (own, peer):
            timeline = index.materials[sender, key]
            days = timeline.dated.days
            use = SharedStickerUse(sender, counts[sender][key], len(days), totals[sender],
                                   _iso(days[0]) if days else None, _iso(days[-1]) if days else None,
                                   timeline.has_unknown_time)
            if use.send_count < SHARED_MIN_SENDS or use.date_count < SHARED_MIN_DATES or use.share < SHARED_MIN_SHARE:
                break
            uses.append(use)
        if len(uses) == 2:
            results.append(SharedStickerHabit(key, index.materials[own, key].sends[0].media_key,
                                             tuple(uses), adoption_by_key.get(key)))
    return tuple(sorted(results, key=lambda h: (-min(u.date_count for u in h.members),
                                                -min(u.send_count for u in h.members), h.identity_key)))


def expected_sticker_richness(counts: Sequence[int], sample_size: int) -> float:
    """Exact finite-sample expectation, evaluated by short floating products.

    Sampling is without replacement from reliable observed sends. This neither
    estimates unseen materials nor simulates a random sample. Work: O(m * U).
    """
    total = sum(counts)
    if any(type(c) is not int or c <= 0 for c in counts) or not 0 <= sample_size <= total:
        raise ValueError("positive material counts and a sample within the population required")
    probabilities = []
    for count in counts:
        if total-count < sample_size:
            probabilities.append(1.0)
            continue
        absent = 1.0
        for j in range(sample_size):
            absent *= (total-count-j)/(total-j)
        probabilities.append(1-absent)
    return fsum(probabilities)


def _styles(index: StickerFactIndex, counts: dict[str, dict[str, int]]) -> tuple[StickerStyleComparison, ...]:
    if None in index.side_members:
        return ()
    totals = {sender: sum(values.values()) for sender, values in counts.items()}
    if any(totals[sender] < STYLE_MIN_SENDS or len(index.members[sender].known_sends.days) < STYLE_MIN_DATES
           for sender in index.side_members):
        return ()
    sample = min(STYLE_MAX_SAMPLE, *(totals[sender] for sender in index.side_members))
    unknowns = Counter(s.sender_id for s in index.uncertain_sends if not s.identity_key)
    members = []
    for sender in index.side_members:
        values = tuple(counts[sender].values())
        members.append(StickerStyleMember(sender, totals[sender], unknowns[sender],
                                         len(index.members[sender].known_sends.days), len(values),
                                         expected_sticker_richness(values, sample),
                                         totals[sender]**2/sum(n*n for n in values)))
    richer, concentrated = sorted(members, key=lambda m: -m.expected_unique_count)
    if (richer.expected_unique_count < STYLE_MIN_RICHNESS_RATIO*concentrated.expected_unique_count
            or richer.expected_unique_count-concentrated.expected_unique_count < STYLE_MIN_RICHNESS_DIFFERENCE
            or richer.d2 < STYLE_MIN_D2_RATIO*concentrated.d2):
        return ()
    return (StickerStyleComparison(sample, richer, concentrated, index.unattributed_send_count),)
