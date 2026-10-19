"""Bounded sticker views selected from complete scoped analysis results."""
from __future__ import annotations

import base64

from ..analysis.stickers import StickerConversationReport, StickerMaterialUsage, StickerMedia, StickerHabit
from .models import EchoStickerAsset, EchoStickerItem, EchoStickerMember, EchoStickers, EchoStickerSignature


TOP_MATERIAL_LIMIT = 10
SHARED_RANKING_MIN_MATERIALS = 3  # Experimental UI rule; does not alter aggregate counts.


def build_echo_stickers(
    reports: tuple[StickerConversationReport, ...],
    media: tuple[StickerMedia, ...],
    *,
    conversation_kind: str,
    member_names: dict[str, str] | None = None,
) -> EchoStickers:
    if conversation_kind not in {"private", "group"}:
        return EchoStickers(available=False)
    if not reports:
        return EchoStickers(available=True, conversation_kind=conversation_kind,
                            members=(EchoStickerMember("我"), EchoStickerMember("TA")) if conversation_kind == "private" else ())
    if len(reports) != 1 or reports[0].conversation_type != conversation_kind or not reports[0].conversation_id:
        return EchoStickers(available=False, unavailable_reason="当前数据无法限定为同一会话。")
    report, = reports
    # Never combine multiple participants into one private side. A source must
    # reliably establish both sender identity and self marker for attribution.
    private = conversation_kind == "private"
    sides = []
    if private:
        for own in (True, False):
            candidates = [member for member in report.members if member.is_self is own]
            sides.append(candidates[0] if len(candidates) == 1 else None)
        member_labels = ["我", "TA"]
    else:
        # All reliable IDs remain distinct, including members without self markers.
        sides = sorted(report.members, key=lambda member: (-bool(report.signature(member.sender_id)),
                                                         -member.send_count, member.sender_id))
        aliases = {member.sender_id: f"成员 {index:02d}" for index, member in
                   enumerate(sorted(report.members, key=lambda member: member.sender_id), 1)}
        self_members = [member for member in sides if member.is_self is True]
        member_labels = []
        for member in sides:
            name = (member_names or {}).get(member.sender_id)
            label = aliases[member.sender_id]
            if name and name != member.sender_id:
                label = f"{name} · {label}"
            if member.is_self is True and len(self_members) == 1:
                label = "我"
            member_labels.append(label)
    labels = {item.identity_key: f"素材 {index:02d}" for index, item in
              enumerate(sorted(report.materials, key=lambda item: item.identity_key), 1)}
    asset_keys = {key: f"sticker:{index}" for index, key in enumerate(labels, 1)}
    selected_media = {}

    def item_view(item: StickerMaterialUsage, count: int, *, shared: bool = False, habit: StickerHabit | None = None) -> EchoStickerItem:
        key = asset_keys[item.identity_key]
        selected_media[key] = item.media_key
        counts = dict(item.member_counts)
        return EchoStickerItem(
            label=labels[item.identity_key], asset_key=key, count=count,
            side_counts=tuple(counts.get(side.sender_id, 0) for side in sides) if shared and private else (),
            reliable_member_count=item.reliable_member_count, unknown_sender_count=item.unknown_sender_count,
            signature=EchoStickerSignature(
                habit.send_count, habit.dated_send_count, habit.date_count, habit.span_days,
                habit.week_count, habit.share, habit.first_date, habit.last_date,
            ) if habit else None,
        )

    members = []
    for label, side in zip(member_labels, sides):
        if side is None:
            members.append(EchoStickerMember(label))
            continue
        ranked = report.ranking(side.sender_id)
        signature = report.signature(side.sender_id)
        exclusive_count = report.exclusive_material_count(side.sender_id) if not private or all(sides) else None
        def personal_item(item, count):
            return item_view(item, count, habit=signature if signature and signature.identity_key == item.identity_key else None)
        signature_view = next((personal_item(item, count) for item, count in ranked
                               if signature and item.identity_key == signature.identity_key), None)
        members.append(EchoStickerMember(
            label=label, send_count=side.send_count, message_count=side.message_count,
            per_hundred_messages=side.per_hundred_messages,
            top_materials=tuple(personal_item(item, count) for item, count in ranked[:TOP_MATERIAL_LIMIT]),
            exclusive_material_count=exclusive_count,
            signature=signature_view,
        ))
    shared = report.shared_ranking(tuple(side.sender_id for side in sides)) if private and all(sides) else (
        report.shared_ranking() if not private else ())
    shared_views = tuple(
        item_view(item, count, shared=True) for item, count in shared[:TOP_MATERIAL_LIMIT]
    ) if len(shared) >= SHARED_RANKING_MIN_MATERIALS else ()
    total_views = tuple(item_view(item, count) for item, count in report.ranking()[:TOP_MATERIAL_LIMIT]) if not private else ()
    assets = []
    by_key = {item.media_key: item for item in media}
    # Bound exported bytes, independently of statistical eligibility. Media
    # failures and images omitted by this size budget leave counts intact.
    remaining_bytes = 16 * 1024 * 1024
    mime_types = {
        "PNG": "image/png", "APNG": "image/png", "JPEG": "image/jpeg",
        "GIF": "image/gif", "WEBP": "image/webp",
    }
    for key, media_key in selected_media.items():
        original = by_key.get(media_key)
        if original is None or original.status not in {"available", "preview"}:
            continue
        raw, mime = original.original_bytes, mime_types.get(original.format)
        if not raw or not mime or len(raw) > remaining_bytes:
            continue
        remaining_bytes -= len(raw)
        assets.append(EchoStickerAsset(
            key, f"data:{mime};base64," + base64.b64encode(raw).decode("ascii"), original.status,
        ))
    return EchoStickers(
        available=True, total_send_count=report.total_send_count,
        unique_material_count=len(report.materials), unknown_identity_count=report.unknown_identity_count,
        unattributed_send_count=report.total_send_count - sum(side.send_count for side in sides if side),
        covered_message_count=report.message_count, members=tuple(members),
        shared_material_count=None if private and not all(sides) and report.total_send_count else len(shared),
        shared_materials=shared_views, assets=tuple(assets),
        conversation_kind=conversation_kind, total_top_materials=total_views,
        exclusive_material_count=report.exclusive_material_count(),
        per_hundred_messages=100 * report.total_send_count / report.message_count if report.message_count else None,
        shared_ranking_min_materials=SHARED_RANKING_MIN_MATERIALS,
    )
