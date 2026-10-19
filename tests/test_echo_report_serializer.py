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
    assert chapter["assets"] == {}
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
