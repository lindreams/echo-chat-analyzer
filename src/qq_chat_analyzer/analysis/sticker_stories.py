"""Deterministic private story associations and bounded local replay references.

This is a presentation shortlist, never a replacement for algorithm candidates.
References and IDs are scoped to one analysis run. No media reads or text export.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from itertools import groupby
from typing import TYPE_CHECKING, Literal

from .sticker_index import IndexedStickerMessage, StickerFactIndex
from .conversation_sessions import DEFAULT_SESSION_THRESHOLD_SECONDS

if TYPE_CHECKING:
    from .sticker_features import PrivateStickerFeatures, StickerRelay


@dataclass(frozen=True, slots=True)
class StickerMoment:
    event_id: str
    relay_indices: tuple[int, ...]
    core_start: int
    core_end: int  # All sequence ranges are half-open.
    context_start: int
    context_end: int
    messages: tuple[IndexedStickerMessage, ...] = field(repr=False)
    dense_exchange: bool
    shared_identity_keys: tuple[str, ...] = field(repr=False)
    qualifiers: tuple[str, ...]

    @property
    def experiment_eligible(self) -> bool:
        return self.dense_exchange or bool(self.shared_identity_keys)


@dataclass(frozen=True, slots=True)
class StickerStory:
    story_id: str
    kind: Literal["material", "interaction", "style"]
    identity_keys: tuple[str, ...] = field(repr=False)
    sender_ids: tuple[str, ...] = field(repr=False)
    start_date: str | None
    end_date: str | None  # Exclusive event anchor, not the full historical evidence.
    findings: tuple[tuple[str, int], ...]  # Field name + index in original features.
    media_keys: tuple[str, ...] = field(repr=False)
    event_ids: tuple[str, ...] = ()
    interest_level: int = 0
    strength: float = 0  # Dimensionless, bounded salience within an interest level.
    interest_reasons: tuple[str, ...] = ()
    timeline: tuple[tuple[str, str, str, int], ...] = ()  # Start/end, field, candidate index.
    lead_finding: str = ""  # Editorial lead; full associated evidence stays intact.


@dataclass(frozen=True, slots=True)
class StickerStorySelection:
    candidates: tuple[StickerStory, ...] = ()
    featured_ids: tuple[str, ...] = ()
    moments: tuple[StickerMoment, ...] = field(default=(), repr=False)
    rule_version: str = "private-sticker-stories.v3"
    diagnostic_counts: tuple[tuple[str, int], ...] = field(default=(), repr=False, compare=False)


def _next_day(value: str) -> str:
    return date.fromordinal(date.fromisoformat(value).toordinal()+1).isoformat()


def _strength(value: float, reference: float) -> float:
    """Relative to the finding's editorial threshold, bounded below one.

    Raw days, turns and share changes stay in the original evidence. This is
    an editorial tie-break, not a scientific or relationship score.
    """
    return value/(value+reference)


def _near(a: StickerStory, b: StickerStory, index: StickerFactIndex) -> bool:
    if not (set(a.identity_keys) & set(b.identity_keys) and set(a.sender_ids) & set(b.sender_ids)):
        return False
    if None in (a.start_date, a.end_date, b.start_date, b.end_date):
        return False
    start, end = min(a.start_date, b.start_date), max(a.end_date, b.end_date)
    days = lambda s: date.fromisoformat(s).toordinal()
    # Bounded event anchors prevent transitive chains and whole-history habits
    # from bridging independent events years apart. Seven days is association,
    # not proof of propagation or a reconstructed conversation.
    return (days(end)-days(start) <= 90
            and days(max(a.start_date, b.start_date))-days(min(a.end_date, b.end_date)) <= 7
            and not index.has_gap(days(start), days(end)))


def _join(a: StickerStory, b: StickerStory, *, context: bool = False) -> StickerStory:
    return replace(a,
        sender_ids=tuple(sorted(set(a.sender_ids+b.sender_ids))),
        # Habits/signatures are contextual evidence, never widen event anchors.
        start_date=a.start_date if context else min(a.start_date, b.start_date),
        end_date=a.end_date if context else max(a.end_date, b.end_date),
        findings=tuple(sorted(set(a.findings+b.findings))),
        media_keys=tuple(sorted(set(a.media_keys+b.media_keys))),
        event_ids=tuple(sorted(set(a.event_ids+b.event_ids))),
        timeline=tuple(sorted(set(a.timeline+b.timeline))),
        # Context of a lower interest level cannot inflate a stronger event.
        interest_level=max(a.interest_level, b.interest_level),
        strength=max((a.interest_level, a.strength), (b.interest_level, b.strength))[1],
        interest_reasons=tuple(sorted(set(a.interest_reasons+b.interest_reasons))))


def select_sticker_stories(index: StickerFactIndex, features: PrivateStickerFeatures) -> StickerStorySelection:
    """Keep every reference; select at most three stories by concrete contrast.

    Levels are transparent editorial heuristics, not significance or relationship
    scores. There is no algorithm quota, media availability input or causal claim.
    """
    stories: list[StickerStory] = []
    material_positions: dict[str, list[int]] = {}

    def append_material(story: StickerStory) -> None:
        material_positions.setdefault(story.identity_keys[0], []).append(len(stories))
        stories.append(story)

    def material(name, i, key, media, senders, start, end, level, strength, reason):
        return StickerStory("", "material", (key,), tuple(senders), start, end,
                            ((name, i),), (media,), interest_level=level,
                            strength=strength, interest_reasons=(reason,),
                            timeline=((start, end, name, i),) if name in ("adoptions", "reunions", "trends") else ())

    anchors = []
    for i, f in enumerate(features.adoptions):
        anchors.append(material("adoptions", i, f.identity_key, f.media_key,
            (f.first_sender_id, f.later_sender_id), f.later_first_date, _next_day(f.later_first_date),
            2 if f.lag_days >= 28 and f.later_date_count >= 3 else 1,
            _strength(f.lag_days, 28), f"observed_adoption_lag_days:{f.lag_days}"))
    for i, f in enumerate(features.reunions):
        anchors.append(material("reunions", i, f.identity_key, f.media_key, (f.sender_id,),
            f.return_date, _next_day(f.return_date), 3 if f.gap_days >= 180 else 1,
            _strength(f.gap_days, 180), f"return_gap_days:{f.gap_days}"))
    for i, f in enumerate(features.trends):
        difference = abs(f.current.share-f.previous.share)
        anchors.append(material("trends", i, f.identity_key, f.media_key, (f.sender_id,),
            f.current.start_date, f.current.end_date, 3 if difference >= .5 else 1,
            _strength(difference, .5), f"{f.direction}_share_change:{difference:.3f}"))
    for story in sorted(anchors, key=lambda s: (s.start_date, s.findings)):
        matches = [i for i in material_positions.get(story.identity_keys[0], ()) if _near(stories[i], story, index)]
        if matches:
            # Only one bounded group receives this fact, never bridge two groups.
            pos = min(matches, key=lambda i: (abs(date.fromisoformat(stories[i].start_date).toordinal()
                                                 -date.fromisoformat(story.start_date).toordinal()), i))
            stories[pos] = _join(stories[pos], story)
        else:
            append_material(story)

    contexts = []
    for i, f in enumerate(features.shared_habits):
        dated = [u for u in f.members if u.first_date and u.last_date]
        contexts.append(material("shared_habits", i, f.identity_key, f.media_key,
            tuple(u.sender_id for u in f.members), min((u.first_date for u in dated), default=None),
            _next_day(max(u.last_date for u in dated)) if dated else None,
            1,
            _strength(min(u.date_count for u in f.members), 3), "repeated_shared_use"))
    for i, f in enumerate(features.signatures):
        h = f.habit
        contexts.append(material("signatures", i, h.identity_key, f.media_key, (h.sender_id,),
            h.first_date, _next_day(h.last_date) if h.last_date else None,
            (3 if h.span_days >= 365 else 1) if f.story_eligible else 0,
            _strength(h.span_days, 365), "long_term_signature" if f.long_term else "ordinary_signature_context"))
    for story in contexts:
        matches = [i for i in material_positions.get(story.identity_keys[0], ())
                   if set(stories[i].sender_ids) & set(story.sender_ids)]
        if story.findings[0][0] == "shared_habits":
            habit = features.shared_habits[story.findings[0][1]]
            if habit.adoption is not None:
                linked = ("adoptions", features.adoptions.index(habit.adoption))
                preferred = [i for i in matches if linked in stories[i].findings]
                matches = preferred or matches
        if matches:
            # Whole-history evidence describes usage, not event simultaneity.
            # Attach once to the nearest last observed use, without merging groups.
            pos = min(matches, key=lambda i: (abs(date.fromisoformat(stories[i].end_date).toordinal()
                                                  -date.fromisoformat(story.end_date).toordinal())
                                              if stories[i].end_date and story.end_date else 10**9, i))
            stories[pos] = _join(stories[pos], story, context=True)
        else:
            append_material(story)

    moments = _moments(index, features.relays)
    for moment in moments:
        relay = features.relays[moment.relay_indices[0]]
        first, last = index.messages[moment.core_start], index.messages[moment.core_end-1]
        start, end = date.fromordinal(first.day).isoformat(), date.fromordinal(last.day+1).isoformat()
        level = 3 if relay.turn_count >= 12 else 2 if relay.turn_count >= 8 or moment.shared_identity_keys else 1
        interaction = StickerStory("", "interaction", tuple(sorted(m.identity_key for m in relay.materials)),
            tuple(sorted(set(t.sender_id for t in relay.turns))), start, end,
            tuple(("relays", i) for i in moment.relay_indices),
            tuple(dict.fromkeys(k for i in moment.relay_indices for k in features.relays[i].media_keys)),
            (moment.event_id,), level, _strength(relay.turn_count, 12), (f"alternating_turns:{relay.turn_count}",),
            tuple((start, end, "relays", i) for i in moment.relay_indices))
        possible = sorted({i for key in interaction.identity_keys for i in material_positions.get(key, ())})
        matches = [i for i in possible if _near(stories[i], interaction, index)]
        if matches:
            # Multi-material exchanges link once; they do not collapse unrelated
            # material histories into one event merely because they share a relay.
            pos = max(matches, key=lambda i: (stories[i].interest_level, stories[i].strength, -i))
            stories[pos] = _join(stories[pos], interaction)
        else:
            stories.append(interaction)
    for i, f in enumerate(features.styles):
        ratio = f.richer.expected_unique_count/f.concentrated.expected_unique_count
        stories.append(StickerStory("", "style", (), (f.richer.sender_id, f.concentrated.sender_id),
            features.first_date, features.end_date, (("styles", i),), (),
            interest_level=2 if ratio >= 3 else 1, strength=_strength(ratio, 3),
            interest_reasons=(f"equal_volume_richness_ratio:{ratio:.3f}",)))
    candidates = tuple(replace(s, story_id=f"story:{i}") for i, s in enumerate(stories))
    selected, repeats, capped = _select_independent_stories(candidates, features, limit=3)
    leads = {s.story_id: s.lead_finding for s in selected}
    candidates = tuple(replace(s, lead_finding=leads.get(s.story_id, "")) for s in candidates)
    return StickerStorySelection(candidates, tuple(s.story_id for s in selected), moments, diagnostic_counts=(
        ("stories.ranked", sum(s.interest_level > 0 for s in candidates)),
        ("stories.reject_repeat", repeats),
        ("stories.reject_cap", capped),
    ))


def select_additional_sticker_stories(features: PrivateStickerFeatures) -> tuple[StickerStory, ...]:
    """Keep strong independent extras and one example of each missing kind.

    The three featured stories stay unchanged. Qualified ordinary discoveries
    can fill a missing kind in the compact section; repeats and ordinary extras
    of an already displayed kind remain excluded.
    """
    selection = features.stories
    featured = tuple(s for s in selection.candidates if s.story_id in selection.featured_ids)
    candidates = tuple(s for s in selection.candidates
                       if s.story_id not in selection.featured_ids and s.interest_level >= 2)
    selected, _, _ = _select_independent_stories(candidates, features, limit=None, previous=featured)
    covered = {name for story in featured+selected for name, _ in story.findings}
    ordinary = tuple(s for s in selection.candidates
                     if s.story_id not in selection.featured_ids and s.interest_level == 1)
    remaining, _, _ = _select_independent_stories(
        ordinary, features, limit=None, previous=featured+selected)
    extras = list(selected)
    for story in remaining:
        kinds = {name for name, _ in story.findings}
        if kinds-covered:
            extras.append(story)
            covered.update(kinds)
    return tuple(extras)


def _select_independent_stories(
    candidates: tuple[StickerStory, ...], features: PrivateStickerFeatures, *,
    limit: int | None, previous: tuple[StickerStory, ...] = (),
) -> tuple[tuple[StickerStory, ...], int, int]:
    ranked = sorted((s for s in candidates if s.interest_level > 0),
                    key=lambda s: (-s.interest_level, -s.strength, -len(s.findings), s.story_id))

    def patterns(story):
        result = set()
        for name, i in story.findings:
            f = getattr(features, name)[i]
            if name == "signatures":
                if f.story_eligible:
                    result.add((name, f.habit.sender_id))
            elif name == "adoptions":
                result.add((name, f.later_sender_id, f.first_date, f.later_first_date))
            elif name == "trends":
                result.add((name, f.sender_id, f.direction, f.current.start_date, f.current.end_date))
            elif name == "reunions":
                result.add((name, f.sender_id, f.previous_date, f.return_date))
            elif name == "relays":
                result.update((name, event) for event in story.event_ids)
            else:
                result.add((name,))
        return result

    def repeated(a, b):
        if a[0] != b[0]:
            return False
        if a[0] == "trends":
            # Overlapping scans of the same directional episode remain one
            # narrative even when they concern different materials.
            return a[:-2] == b[:-2] and max(a[-2], b[-2]) < min(a[-1], b[-1])
        if a[0] in ("adoptions", "reunions"):
            # Both observations must be near: the same member's events months
            # apart, or a ten-day and a seven-month interval, are not repeats.
            return a[:-2] == b[:-2] and all(
                abs(date.fromisoformat(x).toordinal()-date.fromisoformat(y).toordinal()) <= 7
                for x, y in zip(a[-2:], b[-2:]))
        return a == b

    def novel_patterns(ps, seen):
        return {p for p in ps if not any(repeated(p, old) for old in seen)}

    # Prefer a different kind of discovery after the strongest story. A new
    # material alone does not make the same adoption/trend narrative novel.
    # Distinct relay events and the other member's habits can still fill space
    # when no new kind remains. Never manufacture a quota or raise the cap.
    selected = []
    seen = {p for story in previous for p in patterns(story)}
    rejected_repeats = 0
    remaining = [(s, patterns(s)) for s in ranked]
    lead_order = ("reunions", "relays", "shared_habits", "adoptions", "signatures", "styles", "trends")
    while remaining and (limit is None or len(selected) < limit):
        covered = {p[0] for p in seen}
        fresh = [(s, ps) for s, ps in remaining if novel_patterns(ps, seen)]
        rejected_repeats += len(remaining)-len(fresh)
        remaining = fresh
        if not remaining:
            break
        pos = next((i for i, (_, ps) in enumerate(remaining) if any(p[0] not in covered for p in ps)), 0)
        story, ps = remaining.pop(pos)
        novel = {p[0] for p in novel_patterns(ps, seen)}
        selected.append(replace(story, lead_finding=next(n for n in lead_order if n in (novel-covered or novel))))
        seen.update(ps)
    repeated_after_cap = sum(not novel_patterns(ps, seen) for _, ps in remaining)
    return (tuple(selected),
            rejected_repeats+repeated_after_cap, len(remaining)-repeated_after_cap)


def _moments(index: StickerFactIndex, relays: tuple[StickerRelay, ...]) -> tuple[StickerMoment, ...]:
    # Associate overlapping windows by intervals, retaining a bounded strongest
    # representative rather than fabricating an arbitrarily long highlight.
    groups: list[list[int]] = []
    ends: list[int] = []
    for i in sorted(range(len(relays)), key=lambda i: (relays[i].start_ordinal, i)):
        relay = relays[i]
        if groups and relay.start_ordinal < ends[-1]:
            groups[-1].append(i)
            ends[-1] = max(ends[-1], relay.end_ordinal)
        else:
            groups.append([i])
            ends.append(relay.end_ordinal)
    results = []
    for group in groups:
        group.sort()  # Original relay order already prioritizes round count.
        r = relays[group[0]]
        sticker_rows = [m for t in r.turns for m in t.messages if m.sends]
        start, end = sticker_rows[0].ordinal, sticker_rows[-1].ordinal+1
        core = index.messages[start:end]
        shared = tuple(sorted(m.identity_key for m in r.materials
            if min(m.self_send_count, m.peer_send_count) >= 2
            and sum(1 for _ in groupby(t.sender_id for t in r.turns
                    if any(s.identity_key == m.identity_key for row in t.messages for s in row.sends))) >= 4))
        dense = (r.self_send_count+r.peer_send_count >= 8 and min(r.self_send_count, r.peer_send_count) >= 2
                 and core[-1].epoch_seconds-core[0].epoch_seconds <= 300
                 and len(sticker_rows)*2 >= len(core))
        # All relay events stay available. Flags identify which also meet the
        # V1.1 moment experiments; a plain four-turn relay is not a high moment.
        left, right, qualifiers = _context(index, start, end)
        if len(group) > 1:
            qualifiers += ("bounded_representative_of_overlapping_relays",)
        results.append(StickerMoment(f"interaction:{r.start_ordinal}:{r.end_ordinal}", tuple(group), start, end,
            left, right, index.messages[left:right], dense, shared, qualifiers))
    return tuple(sorted(results, key=lambda m: m.relay_indices[0]))


def _context(index: StickerFactIndex, start: int, end: int) -> tuple[int, int, tuple[str, ...]]:
    rows = index.messages
    qualifiers = {"imported_filtered_slice_only", "source_may_omit_message_types"}

    def crossing(left: int, right: int) -> bool:
        a, b = rows[left], rows[right]
        reasons = set(b.barrier_reasons)
        for row in (a, b):
            if row.message.sender.identity_id not in index.side_members or row.message.is_self is None:
                reasons.add("unknown_side")
            if row.epoch_seconds is None:
                reasons.add("unknown_time")
        if reasons:
            qualifiers.update(f"context_barrier:{reason}" for reason in reasons)
            return False
        if b.epoch_seconds-a.epoch_seconds > DEFAULT_SESSION_THRESHOLD_SECONDS:
            qualifiers.add("context_time_gap")
            return False
        return True

    # Complete the edge author rounds, then add one neighboring round. A soft
    # budget rejects a whole extra round; it never truncates the relay core.
    left, right = start, end
    for direction in (-1, 1):
        edge = left if direction == -1 else right-1
        author = rows[edge].message.sender.identity_id
        extra_author = None
        proposed = edge
        while 0 <= proposed+direction < len(rows):
            neighbor = proposed+direction
            if not crossing(min(proposed, neighbor), max(proposed, neighbor)):
                break
            sender = rows[neighbor].message.sender.identity_id
            if extra_author is not None and sender != extra_author:
                break
            if sender != author:
                extra_author = sender
            if abs(neighbor-edge) > 60:
                qualifiers.add("context_message_budget")
                proposed = edge  # Keep core, omit the incomplete context round.
                break
            proposed = neighbor
        if direction == -1:
            left = proposed
        else:
            right = proposed+1
    if left == 0 or right == len(rows):
        qualifiers.add("import_boundary")
    return left, right, tuple(sorted(qualifiers))
