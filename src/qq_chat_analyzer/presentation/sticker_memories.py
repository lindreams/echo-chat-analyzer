"""Share-safe visuals for already selected stories; no selection or analysis.

Relay/message objects stay local. Only explicit dates, counts, fixed side labels
and the existing bounded media targets cross the report boundary.
"""
from __future__ import annotations

from datetime import date, timedelta

from ..analysis.sticker_features import PrivateStickerFeatures
from ..analysis.sticker_stories import select_additional_sticker_stories
from ..analysis.timestamps import to_chat_datetime
from .models import EchoStickerFinding, EchoStickerItem, EchoStickerMemory, EchoStickerMemoryPoint


RELAY_PREVIEW_TURNS = 12


def _last_day(exclusive: str) -> str:
    return (date.fromisoformat(exclusive)-timedelta(days=1)).isoformat()


def build_sticker_memories(
    features: PrivateStickerFeatures,
    materials: dict[str, EchoStickerItem],
    labels: dict[str, str],
) -> tuple[EchoStickerMemory, ...]:
    candidates = {s.story_id: s for s in features.stories.candidates}
    memories = []
    featured = features.stories.featured_ids
    if not featured:
        return ()
    selected = featured + tuple(s.story_id for s in select_additional_sticker_stories(features))
    for story_id in selected:
        story = candidates[story_id]
        compact = story_id not in featured
        findings = {}
        for field, position in story.findings:
            findings.setdefault(field, []).append(getattr(features, field)[position])
        # Ordinary findings share at most three images; compact stories need one.
        images = list(sorted((materials[key] for key in story.media_keys if key in materials),
                             key=lambda item: (-item.count, item.asset_key))[:1 if compact else 3])
        if not compact and findings.get("relays"):
            relay = max(findings["relays"], key=lambda f: (f.turn_count, f.self_send_count+f.peer_send_count))
            for turn in relay.turns[:RELAY_PREVIEW_TURNS]:
                representative = next((materials[s.media_key] for message in turn.messages
                    for s in message.sends if s.identity_key and s.media_key in materials), None)
                if representative is not None and all(i.media_key != representative.media_key for i in images):
                    images.append(representative)
        image_map = {item.media_key: item for item in images}

        def picture(key):
            return (image_map[key],) if key in image_map else ()

        visuals = []
        for f in findings.get("reunions", ()):
            side = labels[f.sender_id]
            visuals.append(EchoStickerFinding("reunion", f"隔了 {f.gap_days} 天，{side}又发了这张图。",
                points=(EchoStickerMemoryPoint(f"{side} · 上次记录", start_date=f.previous_date),
                        EchoStickerMemoryPoint(f"{side} · 再次使用", start_date=f.return_date)),
                materials=picture(f.media_key)))

        for f in findings.get("signatures", ()):
            h = f.habit
            visuals.append(EchoStickerFinding("signature", f"这张图，{labels[h.sender_id]}跨越 {h.span_days} 天在用。",
                points=(EchoStickerMemoryPoint(labels[h.sender_id], value=h.send_count,
                    date_count=h.date_count, start_date=h.first_date, end_date=h.last_date),),
                materials=picture(f.media_key)))

        for f in findings.get("shared_habits", ()):
            visuals.append(EchoStickerFinding("shared", "这张图，我们都反复用过。",
                points=tuple(EchoStickerMemoryPoint(labels[u.sender_id], value=u.send_count,
                    date_count=u.date_count, start_date=u.first_date, end_date=u.last_date) for u in f.members),
                materials=picture(f.media_key)))

        if findings.get("relays"):
            # Overlapping windows describe one event; never add their turns.
            f = max(findings["relays"], key=lambda f: (f.turn_count, f.self_send_count+f.peer_send_count))
            start, end = to_chat_datetime(f.start_epoch_seconds), to_chat_datetime(f.end_epoch_seconds)
            points = []
            for turn in f.turns[:RELAY_PREVIEW_TURNS]:
                representative = next((image_map[s.media_key] for message in turn.messages
                    for s in message.sends if s.identity_key and s.media_key in image_map), None)
                points.append(EchoStickerMemoryPoint(labels[turn.sender_id], value=turn.send_count,
                    materials=(representative,) if representative else ()))
            notes = []
            if f.turn_count > len(points):
                notes.append(f"图示前 {len(points)} 轮，共 {f.turn_count} 轮。")
            visuals.append(EchoStickerFinding("relay", f"你来我往，一连 {f.turn_count} 轮。",
                period=f"{start:%Y-%m-%d %H:%M:%S} — {end:%Y-%m-%d %H:%M:%S}",
                points=tuple(points), note="".join(notes)))

        # Retain the existing strongest comparison per side/direction rather
        # than all overlapping scans of the selected story.
        trends = {}
        for f in findings.get("trends", ()):
            key = f.sender_id, f.direction
            if key not in trends or abs(f.current.share-f.previous.share) > abs(trends[key].current.share-trends[key].previous.share):
                trends[key] = f
        for f in trends.values():
            visuals.append(EchoStickerFinding("trend",
                f"{labels[f.sender_id]}用这张图的占比，从 {f.previous.share:.0%} 到 {f.current.share:.0%}。",
                points=tuple(EchoStickerMemoryPoint(labels[f.sender_id], value=w.send_count,
                    total=w.known_send_count, start_date=w.start_date, end_date=_last_day(w.end_date))
                    for w in (f.previous, f.current)), materials=picture(f.media_key)))

        for f in findings.get("adoptions", ()):
            visuals.append(EchoStickerFinding("adoption", f"{labels[f.later_sender_id]}的首次可见使用，晚了 {f.lag_days} 天。",
                points=(EchoStickerMemoryPoint(labels[f.first_sender_id], start_date=f.first_date),
                        EchoStickerMemoryPoint(labels[f.later_sender_id], start_date=f.later_first_date)),
                materials=picture(f.media_key), note="同一张图，在你们之间留下了回音。"))

        for f in findings.get("styles", ()):
            visuals.append(EchoStickerFinding("style", f"同样 {f.sample_size} 次发送，{labels[f.richer.sender_id]}的图样更丰富。",
                points=tuple(EchoStickerMemoryPoint(labels[u.sender_id], value=u.expected_unique_count,
                    total=f.sample_size) for u in (f.richer, f.concentrated))))

        # Honor the shortlist's distinct lead even when a trend is attached as
        # context. Keep every associated fact and the existing image cap.
        lead_order = ("reunion", "relay", "trend", "adoption", "signature", "shared", "style")
        if visuals:
            lead_kind = {"reunions": "reunion", "relays": "relay", "trends": "trend",
                         "adoptions": "adoption", "signatures": "signature",
                         "shared_habits": "shared", "styles": "style"}.get(story.lead_finding)
            lead = min(range(len(visuals)), key=lambda i: (
                visuals[i].kind != lead_kind, lead_order.index(visuals[i].kind)))
            visuals.insert(0, visuals.pop(lead))
            memories.append(EchoStickerMemory(tuple(visuals), tuple(images), compact=compact))
    return tuple(memories)


def build_group_sticker_memories(features, materials, labels) -> tuple[EchoStickerMemory, ...]:
    """Project selected group evidence through the same private-story view model."""
    memories = []
    for story in features.stories:
        images = tuple(materials[k] for k in story.media_keys if k in materials)[:1 if story.compact else 3]
        image_map = {item.media_key: item for item in images}

        def picture(key):
            return (image_map[key],) if key in image_map else ()

        visuals = []
        for name, i in story.findings:
            f = getattr(features, name)[i]
            if name == "relays":
                start = to_chat_datetime(f.turns[0].epoch_seconds)
                end = to_chat_datetime(f.turns[-1].end_epoch_seconds)
                visuals.append(EchoStickerFinding("relay", f"{f.member_count} 位成员，用同一张图接了 {len(f.turns)} 轮。",
                    period=f"{start:%Y-%m-%d %H:%M:%S} — {end:%Y-%m-%d %H:%M:%S}",
                    points=tuple(EchoStickerMemoryPoint(labels[t.sender_id], value=t.send_count,
                        materials=picture(f.media_key)) for t in f.turns[:RELAY_PREVIEW_TURNS]),
                    note=f"展示前 {RELAY_PREVIEW_TURNS} 轮。" if len(f.turns) > RELAY_PREVIEW_TURNS else ""))
            elif name == "trends":
                visuals.append(EchoStickerFinding("trend",
                    f"这张图在群里的使用占比，从 {f.previous.share:.0%} 到 {f.current.share:.0%}。",
                    points=tuple(EchoStickerMemoryPoint("群内可辨认表情", value=w.send_count,
                        total=w.known_send_count, start_date=w.start_date, end_date=_last_day(w.end_date))
                        for w in (f.previous, f.current)), materials=picture(f.media_key)))
            elif name == "reunions":
                visuals.append(EchoStickerFinding("reunion", f"隔了 {f.gap_days} 天，群里又出现了这张旧图。",
                    points=(EchoStickerMemoryPoint("上次可见使用", start_date=f.previous_date),
                            EchoStickerMemoryPoint("再次可见使用", start_date=f.return_date)),
                    materials=picture(f.media_key)))
            elif name == "signatures":
                h = f.habit
                visuals.append(EchoStickerFinding("signature", f"{labels[h.sender_id]}的长期偏爱：这张图更常出现在自己的发送里。",
                    points=(EchoStickerMemoryPoint(labels[h.sender_id], value=h.send_count, date_count=h.date_count,
                        start_date=h.first_date, end_date=h.last_date),), materials=picture(f.media_key)))
            elif name == "shared_habits":
                visuals.append(EchoStickerFinding("shared", f"这张图，{len(f.members)} 位成员都用成了长期习惯。",
                    points=tuple(EchoStickerMemoryPoint(labels[u.sender_id], value=u.send_count,
                        date_count=u.date_count, start_date=u.first_date, end_date=u.last_date) for u in f.members[:6]),
                    materials=picture(f.media_key), note="展示前 6 位成员。" if len(f.members) > 6 else ""))
            elif name == "adoptions":
                visuals.append(EchoStickerFinding("adoption", f"后来，至少 {len(f.members)} 位成员都反复用过这张图。",
                    points=tuple(EchoStickerMemoryPoint(labels[u.sender_id], start_date=u.first_date)
                                 for u in f.members[:6]), materials=picture(f.media_key),
                    note="展示前 6 位成员。" if len(f.members) > 6 else ""))
            elif name == "styles":
                visuals.append(EchoStickerFinding("style", f"同样 {f.sample_size} 次发送，两位成员的表情图样丰富度不同。",
                    points=tuple(EchoStickerMemoryPoint(labels[u.sender_id], value=u.expected_unique_count,
                        total=f.sample_size) for u in (f.richer, f.concentrated))))
            elif name == "replies":
                visuals.append(EchoStickerFinding("reply", f"{labels[f.sender_id]}明确回复了{labels[f.target_sender_id]}，并发出这张图。",
                    period=f.chat_date, materials=picture(f.media_key)))
        if visuals:
            memories.append(EchoStickerMemory(tuple(visuals), images, compact=story.compact))
    return tuple(memories)
