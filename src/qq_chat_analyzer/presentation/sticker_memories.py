"""Explicit share-safe projection of the existing selected private stories.

Never serialize the feature dataclasses: relays and moments hold chat bodies.
Selection, grouping and all numeric evidence remain owned by analysis.
"""
from __future__ import annotations

from datetime import date, timedelta

from ..analysis.sticker_features import PrivateStickerFeatures
from ..analysis.timestamps import to_chat_datetime
from .models import EchoStickerItem, EchoStickerMemory


def _last_day(exclusive: str) -> str:
    return (date.fromisoformat(exclusive)-timedelta(days=1)).isoformat()


def build_sticker_memories(
    features: PrivateStickerFeatures,
    materials: dict[str, EchoStickerItem],
    labels: dict[str, str],
) -> tuple[EchoStickerMemory, ...]:
    """Project only selected facts, using fixed side labels and existing assets."""
    candidates = {s.story_id: s for s in features.stories.candidates}
    memories = []
    for story_id in features.stories.featured_ids:
        story = candidates[story_id]
        findings = {}
        for field, position in story.findings:
            findings.setdefault(field, []).append(getattr(features, field)[position])
        details = []
        title = "这张图的几次回响"
        if "signatures" in findings:
            for f in findings["signatures"]:
                h = f.habit
                extra = f"；发送次数排第 {f.frequency_rank}，不在 Top 3" if not f.overlaps_top3 else ""
                details.append(f"招牌表情包 · {labels[h.sender_id]}共用过 {h.send_count} 次；可定时记录在 "
                    f"{h.first_date} 至 {h.last_date} 覆盖 {h.date_count} 个使用日，首末相隔 {h.span_days} 天{extra}。")
            title = "陪了很久的招牌"
        if "adoptions" in findings:
            for f in findings["adoptions"]:
                details.append(f"先后采用 · {labels[f.first_sender_id]}的首次可辨认使用在 {f.first_date}，"
                    f"{f.lag_days} 天后（{f.later_first_date}）看到{labels[f.later_sender_id]}使用；"
                    f"后者共用了 {f.later_send_count} 次、分布在 {f.later_date_count} 个使用日。先后不代表传播因果。")
            title = "从一个人先用，到两个人都用"
        if "reunions" in findings:
            for f in findings["reunions"]:
                details.append(f"旧爱重逢 · {labels[f.sender_id]}在 {f.return_date} 再次使用，"
                    f"距上次可辨认使用（{f.previous_date}）相隔 {f.gap_days} 天；"
                    f"此前已在 {f.previous_date_count} 个使用日用过 {f.previous_send_count} 次。")
            title = "隔了一阵，又见这张图"
        if "trends" in findings:
            # A story can link overlapping rolling windows. Show one strongest
            # comparison per side/direction, not a list of near-identical scans.
            trends = {}
            for f in findings["trends"]:
                key = f.sender_id, f.direction
                if key not in trends or abs(f.current.share-f.previous.share) > abs(trends[key].current.share-trends[key].previous.share):
                    trends[key] = f
            for f in trends.values():
                p, q = f.previous, f.current
                verb = "阶段走红" if f.direction == "rise" else "阶段性淡出"
                details.append(f"{verb} · {labels[f.sender_id]}在 {p.start_date} 至 {_last_day(p.end_date)} "
                    f"用了 {p.send_count} 次，{q.start_date} 至 {_last_day(q.end_date)} 用了 {q.send_count} 次；"
                    f"占同期已辨认表情包发送的 {p.share:.0%} → {q.share:.0%}。")
            if len(findings) == 1:
                title = "一张图的流行与退场"
        if "shared_habits" in findings:
            for f in findings["shared_habits"]:
                uses = "；".join(f"{labels[u.sender_id]}用了 {u.send_count} 次，可定时记录覆盖 {u.date_count} 个使用日"
                                + ("（部分发送时间不明）" if u.has_unknown_time else "")
                                for u in f.members)
                details.append(f"共同口头禅 · {uses}。这是双方反复使用的习惯。")
            if len(findings) == 1:
                title = "你们反复用的同一张图"
        if "relays" in findings:
            # Overlapping relay windows already share one event. Describe the
            # longest retained window, never add their turns together.
            f = max(findings["relays"], key=lambda f: (f.turn_count, f.self_send_count+f.peer_send_count))
            start, end = to_chat_datetime(f.start_epoch_seconds), to_chat_datetime(f.end_epoch_seconds)
            details.append(f"表情包接力 · {start:%Y-%m-%d %H:%M:%S} 至 {end:%Y-%m-%d %H:%M:%S}，"
                f"连续交替 {f.turn_count} 轮，我发了 {f.self_send_count} 次、TA 发了 {f.peer_send_count} 次。"
                "这里展示互动摘要，聊天原文留在本机。")
            if f.unknown_identity_count:
                details.append(f"其中 {f.unknown_identity_count} 次发送无法辨认素材，未归入任何一张图。")
            if len(findings) == 1:
                title = f"那次，你们接了 {f.turn_count} 轮"
        if "styles" in findings:
            for f in findings["styles"]:
                a, b = f.richer, f.concentrated
                details.append(f"拉齐到各发 {f.sample_size} 次，{labels[a.sender_id]}预计会用 "
                    f"{a.expected_unique_count:.1f} 种图，{labels[b.sender_id]}预计会用 {b.expected_unique_count:.1f} 种。")
                details.append("比较只覆盖已辨认的素材；这是等量抽样的预计种类，不是实际抽取结果，也不代表性格。")
            title = f"{labels[findings['styles'][0].richer.sender_id]}偏收藏家，{labels[findings['styles'][0].concentrated.sender_id]}更专一"
        if len(findings) > 1:
            title = "这张图的几次回响"
        period = f"{story.start_date} — {_last_day(story.end_date)}" if story.start_date and story.end_date else "本次记录中的发现"
        images = sorted((materials[key] for key in story.media_keys if key in materials),
                        key=lambda item: (-item.count, item.asset_key))[:3]
        if len(story.media_keys) > len(images):
            details.append("图片仅展示部分代表素材；摘要保留整段互动的实际发送次数。")
        memories.append(EchoStickerMemory(title, period, tuple(details), tuple(images)))
    return tuple(memories)
