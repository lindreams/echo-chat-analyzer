"""Share-safe visuals for already selected stories; no selection or analysis.

Relay/message objects stay local. Only explicit dates, counts, fixed side labels
and the existing bounded media targets cross the report boundary.
"""
from __future__ import annotations

from datetime import date, timedelta

from ..analysis.sticker_features import PrivateStickerFeatures
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
    for story_id in features.stories.featured_ids:
        story = candidates[story_id]
        findings = {}
        for field, position in story.findings:
            findings.setdefault(field, []).append(getattr(features, field)[position])
        # Retain the existing per-story target cap and acquisition union.
        images = tuple(sorted((materials[key] for key in story.media_keys if key in materials),
                              key=lambda item: (-item.count, item.asset_key))[:3])
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
                materials=picture(f.media_key),
                note="部分发送时间不明。" if h.send_count != h.dated_send_count else ""))

        for f in findings.get("shared_habits", ()):
            visuals.append(EchoStickerFinding("shared", "这张图，我们都反复用过。",
                points=tuple(EchoStickerMemoryPoint(labels[u.sender_id], value=u.send_count,
                    date_count=u.date_count, start_date=u.first_date, end_date=u.last_date) for u in f.members),
                materials=picture(f.media_key),
                note="部分发送时间不明。" if any(u.has_unknown_time for u in f.members) else ""))

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
            if any(t.send_count > 1 for t in f.turns):
                notes.append("每轮仅展示代表图，次数包含整轮发送。")
            if f.unknown_identity_count:
                notes.append(f"含 {f.unknown_identity_count} 次无法辨认素材。")
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
                materials=picture(f.media_key), note="先后出现，不代表谁带动了谁。"))

        for f in findings.get("styles", ()):
            visuals.append(EchoStickerFinding("style", f"同样取 {f.sample_size} 次，{labels[f.richer.sender_id]}的图样更丰富。",
                points=tuple(EchoStickerMemoryPoint(labels[u.sender_id], value=u.expected_unique_count,
                    total=f.sample_size) for u in (f.richer, f.concentrated)),
                note=f"按已有记录估算：从双方可辨认的表情发送中各随机取 {f.sample_size} 次，预计包含的平均种类数。"))

        # Choose a lead visual within a selected story without changing the
        # algorithm's story membership, ranking or featured IDs.
        lead_order = ("reunion", "relay", "trend", "adoption", "signature", "shared", "style")
        if visuals:
            lead = min(range(len(visuals)), key=lambda i: lead_order.index(visuals[i].kind))
            visuals.insert(0, visuals.pop(lead))
            memories.append(EchoStickerMemory(tuple(visuals), images))
    return tuple(memories)
