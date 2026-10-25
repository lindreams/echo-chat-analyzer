"""Observed group sticker discoveries, before media recovery or presentation.

Identities and message references are local evidence. Share reports consume an
explicit view projection; never serialize these dataclasses or the fact index.
Thresholds are editorial filters, not statistical significance or social scores.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from statistics import median
import json
import logging

from ..rich_message import ReplyRelation
from .sticker_features import (
    SharedStickerUse, StickerStyleComparison, StickerStyleMember, StickerWindow,
    expected_sticker_richness, STYLE_MIN_KNOWN_SHARE,
)
from .sticker_index import DayCounts, StickerFactIndex
from .stickers import StickerHabit


@dataclass(frozen=True, slots=True)
class GroupStickerTurn:
    sender_id: str = field(repr=False)
    send_count: int
    epoch_seconds: int
    end_epoch_seconds: int


@dataclass(frozen=True, slots=True)
class GroupStickerRelay:
    identity_key: str = field(repr=False)
    media_key: str = field(repr=False)
    turns: tuple[GroupStickerTurn, ...] = field(repr=False)
    member_count: int


@dataclass(frozen=True, slots=True)
class GroupStickerTrend:
    identity_key: str = field(repr=False)
    media_key: str = field(repr=False)
    direction: str
    previous: StickerWindow
    current: StickerWindow
    previous_members: int
    current_members: int
    previous_active_members: int
    current_active_members: int


@dataclass(frozen=True, slots=True)
class GroupStickerReunion:
    identity_key: str = field(repr=False)
    media_key: str = field(repr=False)
    previous_date: str
    return_date: str
    gap_days: int
    previous_member_count: int
    return_member_count: int
    active_date_count: int
    other_send_count: int


@dataclass(frozen=True, slots=True)
class GroupStickerSignature:
    habit: StickerHabit = field(repr=False)
    media_key: str = field(repr=False)
    other_send_count: int
    other_known_send_count: int
    relative_share: float  # Add-one smoothed comparison, never infinity.


@dataclass(frozen=True, slots=True)
class GroupSharedSticker:
    identity_key: str = field(repr=False)
    media_key: str = field(repr=False)
    members: tuple[SharedStickerUse, ...] = field(repr=False)
    active_member_count: int


@dataclass(frozen=True, slots=True)
class GroupStickerAdoption:
    identity_key: str = field(repr=False)
    media_key: str = field(repr=False)
    members: tuple[SharedStickerUse, ...] = field(repr=False)
    claim: str = "observed_order_only"


@dataclass(frozen=True, slots=True)
class GroupStickerReply:
    identity_key: str = field(repr=False)
    media_key: str = field(repr=False)
    sender_id: str = field(repr=False)
    target_sender_id: str = field(repr=False)
    chat_date: str


@dataclass(frozen=True, slots=True)
class GroupStickerStory:
    findings: tuple[tuple[str, int], ...]
    media_keys: tuple[str, ...] = field(repr=False)
    compact: bool = False


@dataclass(frozen=True, slots=True)
class GroupStickerFeatures:
    available: bool
    unavailable_reason: str | None = None
    source: str | None = None
    conversation_id: str | None = field(default=None, repr=False)
    relays: tuple[GroupStickerRelay, ...] = ()
    trends: tuple[GroupStickerTrend, ...] = ()
    reunions: tuple[GroupStickerReunion, ...] = ()
    signatures: tuple[GroupStickerSignature, ...] = ()
    shared_habits: tuple[GroupSharedSticker, ...] = ()
    adoptions: tuple[GroupStickerAdoption, ...] = ()
    styles: tuple[StickerStyleComparison, ...] = ()
    replies: tuple[GroupStickerReply, ...] = ()
    stories: tuple[GroupStickerStory, ...] = ()
    diagnostic_counts: tuple[tuple[str, int], ...] = field(default=(), repr=False)
    qualifiers: tuple[str, ...] = ("filtered_observations_only", "history_may_be_truncated",
                                  "known_materials_only", "observed_order_only")


def analyze_group_stickers(index: StickerFactIndex) -> GroupStickerFeatures:
    audit = Counter()
    if not index.available or index.report is None or index.report.conversation_type != "group":
        audit["analysis.unavailable"] = 1
        _log_audit(audit)
        return GroupStickerFeatures(False, "not_single_group_conversation", diagnostic_counts=tuple(audit.items()))
    audit.update({
        "input.members": len(index.members), "input.sends": index.send_count,
        "input.messages": index.message_count, "input.materials": len(index.report.materials),
        "input.span_days": index.end_day-index.first_day if index.first_day is not None else 0,
        "input.unknown_time_messages": sum(m.epoch_seconds is None for m in index.messages),
        "input.uncertain_sends": len(index.uncertain_sends),
        "input.filter_gaps": len(index.gap_starts),
        "input.sticker_count_gaps": len(index.sticker_gap_starts or ()),
        "input.positions_supplied": int(index.source_positions_supplied),
    })
    by_key = defaultdict(list)
    for (sender, key), timeline in index.materials.items():
        by_key[key].append((sender, timeline))
    totals = Counter()
    for days in index.members.values():
        totals.update(dict(zip(days.known_sends.days,
                               (b-a for a, b in zip(days.known_sends.prefix, days.known_sends.prefix[1:])))))
    total_days = DayCounts.from_counts(totals)
    usage = {}
    material_days = {}
    known_totals = Counter()
    for (sender, _), timeline in index.materials.items():
        known_totals[sender] += len(timeline.sends)
    for key, timelines in by_key.items():
        counts = Counter()
        uses = []
        for sender, t in timelines:
            counts.update(dict(zip(t.dated.days, (b-a for a, b in zip(t.dated.prefix, t.dated.prefix[1:])))))
            known = known_totals[sender]
            uses.append(SharedStickerUse(sender, len(t.sends), len(t.dated.days), known,
                _day(t.dated.days[0]) if t.dated.days else None,
                _day(t.dated.days[-1]) if t.dated.days else None, t.has_unknown_time))
        usage[key] = tuple(uses)
        material_days[key] = DayCounts.from_counts(counts)
    fields = dict(
        relays=_relays(index, audit), trends=_trends(index, by_key, material_days, total_days, audit),
        reunions=_reunions(index, by_key, material_days, total_days, audit),
        signatures=_signatures(index, audit), shared_habits=_shared(index, usage, by_key, audit),
        adoptions=_adoptions(index, usage, by_key, audit), styles=_styles(index, audit), replies=_replies(index, audit),
    )
    stories = _stories(fields)
    for name, findings in fields.items():
        audit[name+".qualified"] = len(findings)
        audit[name+".selected_stories"] = sum(any(n == name for n, _ in s.findings) for s in stories)
    audit["stories.selected"] = len(stories)
    audit["stories.findings"] = sum(len(s.findings) for s in stories)
    _log_audit(audit)
    return GroupStickerFeatures(True, source=index.report.source, conversation_id=index.report.conversation_id,
                                stories=stories, diagnostic_counts=tuple(sorted(audit.items())), **fields)


def _log_audit(audit):
    # Literal keys and integer counts only; never log evidence or caller values.
    logging.getLogger("qq_chat_analyzer.desktop.analysis_diagnostics").info(
        "[group-sticker-counts] %s", json.dumps(dict(sorted(audit.items())), sort_keys=True))


def _day(ordinal: int) -> str:
    return date.fromordinal(ordinal).isoformat()


def _media(timelines) -> str:
    return timelines[0][1].sends[0].media_key


def _uncertain(index, timelines, key, start, end):
    # Group absence includes every member, even someone who has no known use
    # of this particular material. Unknown identity could conceal such a use.
    return (any(t.has_unknown_time or not t.chronological for _, t in timelines)
            or any(k in {None, key} for _, k in index.undated_uncertainties)
            or any(k in {None, key} and days.count(start, end)
                   for (_, k), days in index.uncertain_days.items()))


def _relays(index, audit):
    # Collapse consecutive same-author messages before examining material runs.
    # Unknowns, text-only turns, ties and original projection gaps break a run.
    if not index.source_positions_supplied:
        audit["relays.unavailable_provenance"] += 1
        return ()
    turns = []
    current = []
    for m in index.messages:
        if current and (m.barrier_before or m.message.sender.identity_id != current[-1].message.sender.identity_id
                        or m.epoch_seconds-current[-1].epoch_seconds > 120):
            turns.append(current)
            current = []
        if m.epoch_seconds is not None and m.message.sender.identity_id in index.members:
            current.append(m)
    if current:
        turns.append(current)
    audit["relays.author_turns"] = len(turns)
    active = {}
    best = {}

    def keep(key, run):
        audit["relays.raw_windows"] += 1
        if len(run) >= 4 and len({t.sender_id for t in run}) >= 3:
            f = GroupStickerRelay(key, media[key], tuple(run), len({t.sender_id for t in run}))
            if key not in best or len(f.turns) > len(best[key].turns):
                best[key] = f
        else:
            audit["relays.reject_turns_or_members"] += 1

    media = {}
    last_ordinal = -1
    for turn in turns:
        start, end = turn[0], turn[-1]
        sends = [s for m in turn for s in m.sends]
        counts = Counter(s.identity_key for s in sends if s.identity_key)
        for s in sends:
            if s.identity_key:
                media[s.identity_key] = s.media_key
        barrier = (start.barrier_before or start.ordinal != last_ordinal+1
                   or any(not s.identity_key for s in sends))
        last_ordinal = end.ordinal
        if end.epoch_seconds-start.epoch_seconds > 600:
            audit["relays.reject_long_turn"] += 1
            for key, run in active.items():
                keep(key, run)
            active.clear()
            continue
        for key in tuple(active):
            run = active[key]
            if (barrier or key not in counts or start.epoch_seconds-run[-1].end_epoch_seconds > 120
                    or start.epoch_seconds <= run[-1].end_epoch_seconds):
                keep(key, run)
                del active[key]
        if not sends or any(not s.identity_key for s in sends):
            continue
        for key, count in counts.items():
            run = active.setdefault(key, deque())
            # Save the previous maximal bounded window before sliding.
            if run and end.epoch_seconds-run[0].epoch_seconds > 600:
                keep(key, run)
            while run and end.epoch_seconds-run[0].epoch_seconds > 600:
                run.popleft()
            run.append(GroupStickerTurn(start.message.sender.identity_id, count,
                                         start.epoch_seconds, end.epoch_seconds))
    for key, run in active.items():
        keep(key, run)
    return tuple(sorted(best.values(), key=lambda f: (-len(f.turns), f.identity_key)))


def _trends(index, by_key, series, total, audit):
    if index.first_day is None:
        audit["trends.unavailable_dates"] += 1
        return ()
    first, end = index.first_day, index.end_day
    if end-first < 56:
        audit["trends.reject_short_scope"] += 1
        return ()
    stops = sorted(set(range(first+56, end+1, 28)) | ({end} if end-first >= 56 else set()))
    best = {}
    for key, days in series.items():
        ts = by_key[key]
        for stop in stops:
            audit["trends.raw_windows"] += 1
            start, mid = stop-56, stop-28
            if index.has_gap(start, stop, sticker_counts_only=True):
                audit["trends.reject_filter_gap"] += 1
                continue
            if _uncertain(index, ts, key, start, stop):
                audit["trends.reject_uncertain"] += 1
                continue
            windows = tuple(StickerWindow(_day(a), _day(b), days.count(a, b), days.date_count(a, b),
                total.count(a, b), total.date_count(a, b)) for a, b in ((start, mid), (mid, stop)))
            p, q = windows
            members = tuple(sum(t.dated.count(a, b) > 0 for _, t in ts) for a, b in ((start, mid), (mid, stop)))
            active = tuple(sum(t.sends.count(a, b) > 0 for t in index.members.values())
                           for a, b in ((start, mid), (mid, stop)))
            rise = (p.known_send_count >= 10 and q.send_count >= 5 and q.date_count >= 2
                    and members[1] >= 2 and q.share >= 3*p.share and q.share-p.share >= .10)
            fade = (q.known_send_count >= 10 and p.send_count >= 5 and p.date_count >= 2
                    and members[0] >= 2 and p.share >= 3*q.share and p.share-q.share >= .10)
            if min(active) < 2 or not (rise or fade):
                audit["trends.reject_counts_or_contrast"] += 1
                continue
            f = GroupStickerTrend(key, _media(ts), "rise" if rise else "fade", p, q, *members, *active)
            pair = key, f.direction
            if pair not in best or abs(q.share-p.share) > abs(best[pair].current.share-best[pair].previous.share):
                best[pair] = f
    return tuple(sorted(best.values(), key=lambda f: (-abs(f.current.share-f.previous.share), f.identity_key)))


def _reunions(index, by_key, series, total, audit):
    results = []
    if not index.source_positions_supplied:
        audit["reunions.unavailable_provenance"] += 1
        return ()
    for key, days in series.items():
        ts = by_key[key]
        best = None
        for i in range(2, len(days.days)):
            audit["reunions.raw_gaps"] += 1
            left, right = days.days[i-1:i+1]
            gap = right-left
            if gap < 28:
                audit["reunions.reject_short_gap"] += 1
                continue
            old = days.days[:i]
            old_members = sum(t.dated.count(old[0], left+1) > 0 for _, t in ts)
            if (gap < 3*median(b-a for a, b in zip(old, old[1:]))
                    or old_members < 2 or len(old) < 3 or days.count(old[0], left+1) < 5):
                audit["reunions.reject_history_or_contrast"] += 1
                continue
            if index.has_gap(left, right+1, sticker_counts_only=True):
                audit["reunions.reject_filter_gap"] += 1
                continue
            if _uncertain(index, ts, key, left+1, right):
                audit["reunions.reject_uncertain"] += 1
                continue
            other = total.count(left+1, right)
            active_dates = total.date_count(left+1, right)
            if other < 10 or active_dates < 3:
                audit["reunions.reject_inactive_interval"] += 1
                continue
            f = GroupStickerReunion(key, _media(ts), _day(left), _day(right), gap, old_members,
                sum(t.dated.count(right, right+1) > 0 for _, t in ts), active_dates, other)
            if best is None or gap > best.gap_days:
                best = f
        if best:
            results.append(best)
    return tuple(sorted(results, key=lambda f: (-f.gap_days, f.identity_key)))


def _signatures(index, audit):
    counts = Counter()
    totals = Counter()
    for (sender, key), t in index.materials.items():
        counts[key] += len(t.sends)
        totals[sender] += len(t.sends)
    all_known = sum(totals.values())
    results = []
    for h in index.report.habits:
        audit["signatures.raw_habits"] += 1
        if not h.qualified:
            audit["signatures.reject_persistence"] += 1
            continue
        if len(totals.keys()-{h.sender_id}) < 2:
            audit["signatures.reject_other_members"] += 1
            continue
        own_total = totals[h.sender_id]
        other_total = all_known-own_total
        other_count = counts[h.identity_key]-h.send_count
        if other_total < 10 or own_total < 4:
            audit["signatures.reject_sample"] += 1
            continue
        # Unknown identities cannot establish rarity on other members' side.
        unknown = index.send_count-index.unknown_sender_count-all_known
        if unknown > .20*other_total or index.unknown_sender_count > .20*index.send_count:
            audit["signatures.reject_unknown_coverage"] += 1
            continue
        ratio = ((h.send_count+1)/(own_total+2))/((other_count+1)/(other_total+2))
        if ratio >= 3:
            results.append(GroupStickerSignature(h, index.materials[h.sender_id, h.identity_key].sends[0].media_key,
                                                 other_count, other_total, ratio))
        else:
            audit["signatures.reject_relative_preference"] += 1
    return tuple(sorted(results, key=lambda f: (-f.relative_share, -f.habit.date_count, f.habit.sender_id, f.habit.identity_key)))


def _shared(index, usage, by_key, audit):
    qualified = {(h.sender_id, h.identity_key) for h in index.report.habits if h.qualified}
    results = []
    for key, uses in usage.items():
        audit["shared_habits.raw_materials"] += 1
        members = tuple(u for u in uses if (u.sender_id, key) in qualified)
        if len(members) < 3:
            audit["shared_habits.reject_members"] += 1
            continue
        start = min(date.fromisoformat(u.first_date).toordinal() for u in members)
        end = max(date.fromisoformat(u.last_date).toordinal() for u in members)+1
        active = sum(v.sends.count(start, end) > 0 for v in index.members.values())
        results.append(GroupSharedSticker(key, _media(by_key[key]), members, active))
    return tuple(sorted(results, key=lambda f: (-len(f.members), f.identity_key)))


def _adoptions(index, usage, by_key, audit):
    if not index.source_positions_supplied or index.first_day is None:
        audit["adoptions.unavailable_dates_or_provenance"] += 1
        return ()
    results = []
    for key, uses in usage.items():
        audit["adoptions.raw_materials"] += 1
        members = tuple(sorted((u for u in uses if u.send_count >= 3 and u.date_count >= 2 and u.share >= .10
                                and not u.has_unknown_time), key=lambda u: (u.first_date, u.sender_id)))
        if len(members) < 3 or len({u.first_date for u in members}) < 2:
            audit["adoptions.reject_repetition_or_members"] += 1
            continue
        end = date.fromisoformat(members[-1].first_date).toordinal()+1
        if index.has_gap(index.first_day, end, sticker_counts_only=True):
            audit["adoptions.reject_filter_gap"] += 1
            continue
        if any(index.has_uncertain_use(u.sender_id, key, index.first_day,
            date.fromisoformat(u.first_date).toordinal()+1) for u in members):
            audit["adoptions.reject_uncertain"] += 1
            continue
        timelines = by_key[key]
        if any(not t.chronological for _, t in timelines):
            audit["adoptions.reject_order"] += 1
            continue
        # Do not sort source inversions into an apparent adoption order.
        firsts = [m for m in index.messages if any(s.identity_key == key for s in m.sends)]
        seen = set()
        epochs = []
        for m in firsts:
            sender = m.message.sender.identity_id
            if sender not in seen:
                seen.add(sender)
                epochs.append(m.epoch_seconds)
        if any(t is None for t in epochs) or any(a > b for a, b in zip(epochs, epochs[1:])):
            audit["adoptions.reject_order"] += 1
            continue
        results.append(GroupStickerAdoption(key, _media(timelines), members))
    return tuple(sorted(results, key=lambda f: (-len(f.members), f.identity_key)))


def _styles(index, audit):
    counts = defaultdict(list)
    for (sender, _), timeline in index.materials.items():
        counts[sender].append(len(timeline.sends))
    eligible = {s: cs for s, cs in counts.items() if sum(cs) >= 10 and len(index.members[s].known_sends.days) >= 2}
    audit["styles.raw_members"] = len(counts)
    audit["styles.reject_sample_or_dates"] = len(counts)-len(eligible)
    unknowns = Counter(s.sender_id for s in index.uncertain_sends if not s.identity_key)
    covered = {s: cs for s, cs in eligible.items()
               if sum(cs)/(sum(cs)+unknowns[s]) >= STYLE_MIN_KNOWN_SHARE}
    audit["styles.reject_material_coverage"] = len(eligible)-len(covered)
    eligible = covered
    if len(eligible) < 2:
        audit["styles.reject_member_count"] += 1
        return ()
    if (index.send_count-index.unattributed_send_count)/index.send_count < STYLE_MIN_KNOWN_SHARE:
        audit["styles.reject_sender_coverage"] += 1
        return ()
    sample = min(100, min(map(sum, eligible.values())))
    audit["styles.sample_size"] = sample
    members = []
    for sender, cs in eligible.items():
        n = sum(cs)
        members.append(StickerStyleMember(sender, n, unknowns[sender], len(index.members[sender].known_sends.days),
            len(cs), expected_sticker_richness(cs, sample), 1/sum((c/n)**2 for c in cs)))
    members.sort(key=lambda m: (m.expected_unique_count, m.sender_id))
    low, high = members[0], members[-1]
    if (high.expected_unique_count < 1.8*low.expected_unique_count
            or high.expected_unique_count-low.expected_unique_count < 3 or high.d2 < 1.5*low.d2):
        audit["styles.reject_contrast"] += 1
        return ()
    return (StickerStyleComparison(sample, high, low, index.unattributed_send_count),)


def _replies(index, audit):
    if index.report.source != "qq":
        audit["replies.unavailable_source"] += 1
        return ()
    targets = defaultdict(list)
    for m in index.messages:
        if m.message.message_id:
            targets[m.message.message_id].append(m)
    results = []
    for m in index.messages:
        sender = m.message.sender.identity_id
        links = [r for r in m.message.relations if isinstance(r, ReplyRelation)]
        if links:
            audit["replies.raw_messages"] += 1
        if len(links) != 1 or sender not in index.members or m.day is None:
            if links:
                audit["replies.reject_relation_member_or_time"] += 1
            continue
        matches = targets.get(links[0].target_message_id, ())
        if len(matches) != 1:
            audit["replies.reject_missing_or_ambiguous_target"] += 1
            continue
        target = matches[0]
        other = target.message.sender.identity_id
        if (other not in index.members or sender == other or target.ordinal >= m.ordinal
                or target.epoch_seconds is None or m.epoch_seconds <= target.epoch_seconds):
            audit["replies.reject_target_member_or_order"] += 1
            continue
        seen = set()
        for send in m.sends:
            if send.identity_key and send.identity_key not in seen:
                seen.add(send.identity_key)
                results.append(GroupStickerReply(send.identity_key, send.media_key, sender, other, _day(m.day)))
    return tuple(results)


def _stories(fields):
    # One bounded story per material: persistent facts accompany its event.
    # Selection uses evidence only. Missing images never change qualification.
    groups = {}
    for name in ("relays", "reunions", "trends", "signatures", "shared_habits", "adoptions", "replies", "styles"):
        for i, f in enumerate(fields[name]):
            key = f.habit.identity_key if name == "signatures" else getattr(f, "identity_key", None)
            group = groups.setdefault(key, [])
            if sum(n == name for n, _ in group) < (3 if name == "signatures" else 1):
                group.append((name, i))

    def priority(key):
        findings = groups[key]
        kinds = {name for name, _ in findings}
        level = 2 if len(kinds) > 1 else 1
        # Reuse the private story's striking-event thresholds. Supporting facts
        # add context, but repeated findings of one kind do not add interest.
        for name, i in findings:
            f = fields[name][i]
            if name == "relays":
                level = max(level, 3 if len(f.turns) >= 12 else 2 if len(f.turns) >= 8 else 1)
            elif (name == "reunions" and f.gap_days >= 180
                  or name == "trends" and abs(f.current.share-f.previous.share) >= .5
                  or name == "signatures" and f.habit.span_days >= 365):
                level = 3
        return -level, -len(kinds), key or ""

    ordered = sorted(groups, key=priority)
    # Give each qualified category a place before filling the material tail.
    selected = []
    covered = set()
    for key in ordered:
        findings = groups[key]
        kinds = {name for name, _ in findings}
        if kinds-covered:
            selected.append(key)
            covered.update(kinds)
    selected.extend(key for key in ordered if key not in selected)
    stories = []
    for key in selected[:9]:
        findings = groups[key]
        media = tuple(dict.fromkeys(fields[name][i].media_key for name, i in findings if name != "styles"))
        stories.append(GroupStickerStory(tuple(findings), media, len(stories) >= 3))
    return tuple(stories)
