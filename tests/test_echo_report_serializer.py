"""Contract tests for the Echo Report JSON output layer."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.analysis import models as analysis_models  # noqa: E402
from qq_chat_analyzer.presentation import (
    ChartPoint,
    EchoExpressionCulture,
    EchoExpressionCombination,
    EchoExpressionCombinationMember,
    EchoExpressionItem,
    EchoLanguageMember,
    EchoLanguageProfile,
    EchoMemberExpression,
    EchoMemberCard,
    EchoReportView,
    build_echo_report_view,
    echo_report_to_dict,
    export_echo_report_html,
)


@pytest.mark.parametrize("kind", ["private", "group"])
def test_report_media_targets_cover_top_ten_and_outside_signature_once(kind):
    from qq_chat_analyzer.analysis.stickers import (
        StickerConversationReport, StickerMaterialUsage, StickerParticipant, StickerHabit,
    )
    from qq_chat_analyzer.presentation.stickers import sticker_report_targets

    report = StickerConversationReport(
        "qq", "fiction-room", kind, 100, 200, 0, 0,
        members=(StickerParticipant("a", True, 50, 100), StickerParticipant("b", False, 50, 100)),
        materials=tuple(StickerMaterialUsage(f"key-{i:02}", f"media-{i:02}", 24 - i,
                                           (("a", 24 - i), ("b", 24 - i))) for i in range(12)),
        habits=(StickerHabit("a", "key-11", 4, 4, 4, 35, 4, .2,
                             "2025-01-01", "2025-02-05", ()),),
    )
    view = build_echo_report_view(analysis_models.AnalysisReports(stickers=(report,)), conversation_kind=kind)
    assert all(member.unique_material_count == 12 for member in view.stickers.members)
    targets = sticker_report_targets(view.stickers)
    assert {t.media_key for t in targets} == {f"media-{i:02}" for i in (*range(10), 11)}
    assert len(targets) == len({t.asset_key for t in targets}) == 11
    serialized = json.dumps(echo_report_to_dict(view))
    assert "media-" not in serialized and "key-" not in serialized


def test_group_report_budget_reaches_global_leaders_before_member_long_tail():
    from qq_chat_analyzer.presentation.models import EchoStickers, EchoStickerItem, EchoStickerMember
    from qq_chat_analyzer.presentation.stickers import sticker_report_targets

    def item(key):
        return EchoStickerItem(label=key, asset_key=key, media_key=key, count=1)
    chapter = EchoStickers(available=True, conversation_kind="group",
        total_top_materials=tuple(item(f"global-{i}") for i in range(10)),
        members=tuple(EchoStickerMember(label=f"member-{i}",
                      top_materials=tuple(item(f"member-{i}-{j}") for j in range(10))) for i in range(4)))
    first_batch = sticker_report_targets(chapter)[:32]
    assert {f"global-{i}" for i in range(10)} <= {target.media_key for target in first_batch}
    assert len(sticker_report_targets(chapter)) == 50


@pytest.mark.parametrize("kind,senders,limit", [
    ("private", 2, 10), ("group", 1, 10), ("group", 9, 10),
    ("group", 10, 5), ("group", 99, 5), ("group", 100, 3),
])
def test_member_top_limit_uses_scoped_sticker_senders_and_bounds_media_targets(kind, senders, limit):
    from qq_chat_analyzer.analysis.stickers import (
        StickerConversationReport, StickerMaterialUsage, StickerParticipant, StickerHabit,
    )
    from qq_chat_analyzer.presentation.stickers import sticker_report_targets

    # Inactive conversation members must not move the 9/10 or 99/100 boundary.
    members = tuple(StickerParticipant(f"m{i:03}", i == 0, 200, 184) for i in range(senders))
    if kind == "group":
        members += tuple(StickerParticipant(f"idle-{i}", None, 1, 0) for i in range(110))
    materials = tuple(StickerMaterialUsage(f"own-{i:03}-{rank:02}", f"own-{i:03}-{rank:02}",
                                           20 - rank, ((f"m{i:03}", 20 - rank),))
                      for i in range(senders) for rank in range(12))
    materials += tuple(StickerMaterialUsage(f"shared-{rank}", f"shared-{rank}", senders,
                                            tuple((f"m{i:03}", 1) for i in range(senders)))
                       for rank in range(10))
    report = StickerConversationReport(
        "qq", "fiction-room", kind, senders * 200, senders * 184, 0, 0,
        members=members, materials=materials,
        habits=(StickerHabit("m000", "own-000-11", 9, 9, 4, 35, 4, .2,
                             "2025-01-01", "2025-02-05", ()),),
    )
    chapter = build_echo_report_view(analysis_models.AnalysisReports(stickers=(report,)),
                                     conversation_kind=kind).stickers
    active = [member for member in chapter.members if member.send_count > 0]
    assert len(active) == senders
    assert all([item.count for item in member.top_materials] == list(range(20, 20 - limit, -1))
               for member in active)
    assert all(member.unique_material_count == 22 and member.send_count == 184 for member in active)
    assert chapter.unique_material_count == senders * 12 + 10
    assert len(chapter.total_top_materials) == (10 if kind == "group" else 0)
    assert len(chapter.shared_materials) == (10 if senders > 1 else 0)
    expected = {f"own-{i:03}-{rank:02}" for i in range(senders) for rank in range(limit)}
    if senders > 1:
        expected.update(f"shared-{rank}" for rank in range(10))
    expected.add("own-000-11")  # Preserve the existing separate signature contract.
    targets = sticker_report_targets(chapter)
    assert {item.media_key for item in targets} == expected
    assert len(targets) == len(expected) == len(chapter.assets)
    assert {asset.key for asset in chapter.assets} == {item.asset_key for item in targets}


@pytest.mark.parametrize("encoded_format,verified_format,mime", [
    ("GIF", "GIF", "image/gif"),
    ("PNG", "APNG", "image/png"),
    ("WEBP", "WebP", "image/webp"),
])
def test_verified_animations_retain_original_and_preview_bytes_in_html(
    tmp_path, encoded_format, verified_format, mime,
):
    import base64
    import hashlib
    from qq_chat_analyzer.analysis.stickers import StickerConversationReport, StickerMaterialUsage, StickerParticipant
    from qq_chat_analyzer.application.sticker_media import verify_fetched_media
    from test_sticker_data import image_bytes

    raw = image_bytes(encoded_format, animated=True)
    media = tuple(verify_fetched_media(raw, media_key=key, expected_md5=digest) for key, digest in (
        ("original", hashlib.md5(raw).hexdigest()), ("preview", "0" * 32)))
    assert [item.status for item in media] == ["available", "preview"]
    assert all(item.format == verified_format and item.frame_count == 2
               and item.animation_preserved for item in media)
    report = StickerConversationReport(
        "qq", "fiction-room", "group", 2, 2, 0, 0,
        members=(StickerParticipant("a", True, 2, 2),),
        materials=tuple(StickerMaterialUsage(key, key, 1, (("a", 1),))
                        for key in ("original", "preview")),
    )
    view = build_echo_report_view(analysis_models.AnalysisReports(stickers=(report,)),
                                  conversation_kind="group", sticker_media=media)
    assets = echo_report_to_dict(view)["stickers"]["assets"]
    assert [item["status"] for item in assets.values()] == ["available", "preview"]
    html = export_echo_report_html(view, tmp_path / "animations.html").read_text(encoding="utf-8")
    for asset in assets.values():
        prefix, encoded = asset["data_uri"].split(",", 1)
        assert prefix == f"data:{mime};base64"
        assert base64.b64decode(encoded, validate=True) == raw
        assert asset["data_uri"] in html


def test_sticker_asset_budget_keeps_counts_and_explains_unavailable_images(monkeypatch):
    from dataclasses import replace
    from qq_chat_analyzer.analysis.stickers import StickerConversationReport, StickerMaterialUsage, StickerParticipant, StickerMedia
    from qq_chat_analyzer.application.sticker_media import verify_fetched_media
    from qq_chat_analyzer.presentation import stickers as module
    from test_sticker_data import image_bytes

    raw = image_bytes("PNG")
    import hashlib
    original = verify_fetched_media(raw, media_key="0", expected_md5=hashlib.md5(raw).hexdigest())
    preview = verify_fetched_media(raw, media_key="1", expected_md5="0" * 32)
    report = StickerConversationReport("qq", "fiction-room", "group", 9, 9, 0, 0,
        members=(StickerParticipant("a", True, 3, 3), StickerParticipant("b", False, 6, 6)),
        materials=tuple(StickerMaterialUsage(str(i), str(i), 2 if i < 3 else 1,
                         (("a", 1), ("b", 1)) if i < 3 else (("b", 1),)) for i in range(6)))
    monkeypatch.setattr(module, "REPORT_STICKER_BYTE_BUDGET", len(raw) * 2)
    view = build_echo_report_view(analysis_models.AnalysisReports(stickers=(report,)), conversation_kind="group",
        sticker_media=(original, preview, replace(original, media_key="2"),
                       StickerMedia("4", "missing", "no_digest_name_match"),
                       StickerMedia("5", "failed", "message_mapping_unconfirmed")))
    chapter = echo_report_to_dict(view)["stickers"]
    assert chapter["total_send_count"] == 9 and chapter["unique_material_count"] == 6
    assert [a["status"] for a in chapter["assets"].values()] == [
        "available", "preview", "limited", "not_requested", "missing", "failed"]
    assert list(chapter["assets"].values())[2]["reason"] == "report_asset_budget"
    assert sum(bool(a["data_uri"]) for a in chapter["assets"].values()) == 2
    assert all(not a["data_uri"] for a in list(chapter["assets"].values())[2:])


def test_sticker_chapter_ranks_counts_and_limits_shared_exclusive_candidates():
    from dataclasses import replace
    from qq_chat_analyzer.analysis.stickers import (
        StickerConversationReport, StickerMaterialUsage, StickerParticipant,
    )

    report = StickerConversationReport(
        source="qq", conversation_id="fiction-room", conversation_type="private",
        message_count=20, total_send_count=18, unknown_identity_count=2, unknown_sender_count=1,
        members=(StickerParticipant("a", True, 10, 9), StickerParticipant("b", False, 10, 8)),
        materials=(
            StickerMaterialUsage("shared", "shared", 5, (("a", 2), ("b", 3))),
            StickerMaterialUsage("mine", "mine", 4, (("a", 4),)),
            StickerMaterialUsage("theirs", "theirs", 4, (("b", 4),)),
            StickerMaterialUsage("uncertain", "uncertain", 2, (("a", 1),), 1),
            StickerMaterialUsage("once", "once", 1, (("a", 1),)),
        ),
    )
    view = build_echo_report_view(analysis_models.AnalysisReports(stickers=(report,)), conversation_kind="private")
    chapter = echo_report_to_dict(view)["stickers"]
    assert chapter["available"] is True
    assert (chapter["total_send_count"], chapter["unique_material_count"]) == (18, 5)
    assert chapter["unattributed_send_count"] == 1
    mine, theirs = chapter["members"]
    assert (mine["unique_material_count"], theirs["unique_material_count"]) == (4, 2)
    assert (mine["send_count"], mine["per_hundred_messages"]) == (9, 90.0)
    assert [item["count"] for item in mine["top_materials"]] == [4, 2, 1, 1]
    assert [item["count"] for item in theirs["top_materials"]] == [4, 3]
    assert chapter["shared_material_count"] == 1
    assert chapter["shared_materials"] == []  # Too few for a useful shared leaderboard.
    assert [m["exclusive_material_count"] for m in chapter["members"]] == [2, 1]
    assert mine["signature"] is None
    disjoint = replace(report, materials=report.materials[1:3])
    disjoint_view = build_echo_report_view(analysis_models.AnalysisReports(stickers=(disjoint,)), conversation_kind="private")
    assert echo_report_to_dict(disjoint_view)["stickers"]["shared_material_count"] == 0
    assert echo_report_to_dict(disjoint_view)["stickers"]["shared_materials"] == []
    serialized = json.dumps(chapter)
    assert "uncertain" not in serialized and "fiction-room" not in serialized
    assert len(chapter["assets"]) == 5
    assert all(a["status"] == "not_requested" and not a["data_uri"] for a in chapter["assets"].values())
    # A single occurrence remains eligible; zero denominator is serialized as null.
    tiny = replace(report, total_send_count=1, members=(StickerParticipant("a", True, 0, 1),),
                   materials=(StickerMaterialUsage("one", "one", 1, (("a", 1),)),))
    tiny_view = build_echo_report_view(analysis_models.AnalysisReports(stickers=(tiny,)), conversation_kind="private")
    payload = echo_report_to_dict(tiny_view)["stickers"]
    assert payload["members"][0]["per_hundred_messages"] is None
    assert payload["members"][0]["top_materials"][0]["count"] == 1
    assert payload["shared_materials"] == []
    assert payload["members"][0]["exclusive_material_count"] is None
    assert echo_report_to_dict(build_echo_report_view(conversation_kind="private", reports=None))["stickers"]["total_send_count"] == 0
    assert echo_report_to_dict(build_echo_report_view(analysis_models.AnalysisReports(stickers=(report,)), conversation_kind="group"))["stickers"]["available"] is False
    assert echo_report_to_dict(build_echo_report_view(analysis_models.AnalysisReports(stickers=(report, replace(report, source="wechat"))), conversation_kind="private"))["stickers"]["available"] is False


def test_sticker_member_names_only_disambiguate_missing_and_duplicate_nicknames():
    from qq_chat_analyzer.analysis.stickers import StickerConversationReport, StickerParticipant
    from qq_chat_analyzer.presentation.stickers import build_echo_stickers

    ids = tuple(f"fictional-source-{i}" for i in range(7))
    report = StickerConversationReport(
        "qq", "fiction-room", "group", 70, 7, 7, 0,
        members=tuple(StickerParticipant(sender, i == 0, 10, 1) for i, sender in enumerate(ids)),
    )
    chapter = build_echo_stickers((report,), (), conversation_kind="group", member_names={
        ids[0]: "小满", ids[1]: "同名", ids[2]: "同名", ids[3]: "同名（1）",
        ids[4]: "", ids[5]: ids[5], ids[6]: "未命名成员（1）",
    })
    labels = [member.label for member in chapter.members]
    assert labels == ["小满", "同名（2）", "同名（3）", "同名（1）",
                      "未命名成员（2）", "未命名成员（3）", "未命名成员（1）"]
    assert len(set(labels)) == len(labels)
    assert not any(sender in label for sender in ids for label in labels)
    assert all(member.unique_material_count == 0 for member in chapter.members)


def test_activity_analysis_preserves_report_distribution_and_density_contract(tmp_path):
    from qq_chat_analyzer.analysis.analyzers import ActivityAnalyzer
    from qq_chat_analyzer.message import ChatMessage

    messages = [
        ChatMessage(timestamp=value, sender="Fictional-Alice", message_type="text",
                    text="fictional", platform="fictional")
        for value in ("2024-01-01 08:00:00", "2024-01-01 08:30:00", "invalid")
    ]
    view = build_echo_report_view(analysis_models.AnalysisReports(
        activity=ActivityAnalyzer().analyze(messages),
    ))
    payload = echo_report_to_dict(view)
    assert payload["schema_version"] == "echo-report.v0.8"
    assert payload["overview"] == {
        "has_data": True, "total_message_count": 3, "participant_count": 0,
        "empty_description": "", "active_days": 1,
        "average_messages_per_active_day": 3.0,
    }
    assert set(payload["activity"]) == {"hourly", "weekday"}
    assert len(payload["activity"]["hourly"]) == 24
    assert len(payload["activity"]["weekday"]) == 7
    assert payload["activity"]["hourly"][8] == {"label": "08:00-08:59", "value": 2.0}
    assert payload["activity"]["weekday"][0] == {"label": "周一", "value": 2.0}
    output = export_echo_report_html(view, tmp_path / "echo-report.html")
    match = re.search(r"window\.ECHO_DATA = (\{.*?\});", output.read_text(encoding="utf-8"), re.S)
    assert match is not None
    assert json.loads(match.group(1)) == payload



def _echo_view() -> EchoReportView:
    return EchoReportView(
        title="余音 Echo",
        has_data=True,
        conversation_kind="group",
        conversation_name="虚构讨论组",
        time_span="2 小时 0 分钟",
        total_message_count=3,
        participant_count=2,
        hourly_activity=(ChartPoint(label="09:00-09:59", value=3.0),),
        weekday_activity=(ChartPoint(label="周一", value=3.0),),
        language_profile=EchoLanguageProfile(
            mode="group_distinctive",
            available=True,
            members=(
                EchoLanguageMember(
                    speaker_key="fictional-alice",
                    display_name="虚构 Alice",
                    heading="虚构 Alice",
                    primary_words=("风格词", "回声"),
                    context_words=("讨论", "项目"),
                ),
            ),
        ),
        members=(
            EchoMemberCard(
                speaker_key="fictional-alice",
                display_name="虚构 Alice",
                is_viewer=True,
                message_count=2,
                message_share_percent=66.67,
                average_length=4.5,
                max_length=6,
                active_period="周一 09:00-09:59",
                hourly_activity=(
                    ChartPoint(label="09:00-09:59", value=2.0),
                ),
                weekday_activity=(ChartPoint(label="周一", value=2.0),),
                top_words=("讨论", "项目"),
            ),
        ),
    )


def test_echo_report_html_is_self_contained_with_real_data(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "echo-report.html"

    result_path = export_echo_report_html(_echo_view(), output_path)

    assert result_path == output_path
    html = output_path.read_text(encoding="utf-8")
    assert "window.ECHO_DATA" in html
    assert "window.ECHO_ASSETS" in html
    assert "虚构讨论组" in html
    assert "虚构 Alice" in html
    assert "data:image/png;base64," in html
    assert "fetch(" not in html
    assert "frontend/echo_report" not in html
    assert "assets/branding" not in html
    assert 'href="style.css"' not in html
    assert 'src="app.js"' not in html
    assert 'id="voices-intro"' in html
    assert '"mode":"group_distinctive"' in html


def test_echo_report_html_escapes_injected_user_text(tmp_path: Path) -> None:
    view = EchoReportView(
        title="余音 Echo",
        has_data=True,
        conversation_kind="group",
        conversation_name='<script>alert("x")</script>&"\'余音',
        time_span="1 天",
        total_message_count=1,
        participant_count=1,
        hourly_activity=(ChartPoint(label="09:00-09:59", value=1.0),),
        weekday_activity=(ChartPoint(label="周一", value=1.0),),
        members=(
            EchoMemberCard(
                speaker_key="fictional-alice",
                display_name="</script><b>x</b>",
                is_viewer=False,
                message_count=1,
                message_share_percent=100.0,
                average_length=1.0,
                max_length=1,
                active_period="09:00-09:59",
            ),
        ),
    )

    output_path = tmp_path / "echo-report.html"
    export_echo_report_html(view, output_path)
    html = output_path.read_text(encoding="utf-8")

    match = re.search(
        r"window\.ECHO_DATA = (\{.*?\});",
        html,
        flags=re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))
    assert payload["conversation"]["name"] == (
        '<script>alert("x")</script>&"\'余音'
    )
    assert payload["members"][0]["display_name"] == "</script><b>x</b>"
    assert html.count("</script>") == 2
    assert "<\\/script>" in html


def test_echo_report_html_inlines_expression_assets_without_local_paths(
    tmp_path: Path,
) -> None:
    culture = EchoExpressionCulture(
        available=True,
        expression_message_count=3,
        expression_only_message_count=1,
        expression_only_rate=0.33,
        unique_expression_count=1,
        top_expressions=(
            EchoExpressionItem(
                expression_key="捂脸",
                display_text="[捂脸]",
                count=3,
                kind="platform_face",
                with_text_message_count=2,
                text_only_message_count=1,
                asset_key="wechat:捂脸",
            ),
        ),
    )
    output_path = tmp_path / "echo-report.html"

    export_echo_report_html(
        EchoReportView(
            title="Echo Report",
            has_data=True,
            expression_culture=culture,
        ),
        output_path,
    )

    html = output_path.read_text(encoding="utf-8")
    assert "window.ECHO_ASSETS" in html
    assert "wechat:捂脸" in html
    assert "data:image/png;base64," in html
    assert "D:" not in html
    assert "references" not in html


@pytest.mark.parametrize("key, expected", [
    ("⌚", "⌚"), ("1️⃣", "1️⃣"), ("★", "表情"), ("❤\ufe0e", "表情"),
])
def test_expression_token_fallback_uses_the_same_unicode_contract(key, expected):
    view = EchoReportView(title="Fictional Echo", language_profile=EchoLanguageProfile(
        mode="private_common", available=True,
        members=(EchoLanguageMember("fictional-a", "Fictional A", "A", ("expression:" + key,)),),
    ))
    payload = echo_report_to_dict(view)
    assert payload["language_profile"]["members"][0]["primary_words"] == [{"text": expected}]


#: A throwaway payload; tests only assert it round-trips through base64.
_FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfake-minimal-png"
