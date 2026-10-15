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


def test_echo_report_converts_to_stable_frontend_json_object() -> None:
    payload = echo_report_to_dict(_echo_view())

    assert payload == {
        "schema_version": "echo-report.v0.7",
        "title": "余音 Echo",
        "conversation": {
            "kind": "group",
            "name": "虚构讨论组",
            "time_span": "2 小时 0 分钟",
        },
        "overview": {
            "has_data": True,
            "total_message_count": 3,
            "participant_count": 2,
            "empty_description": "",
            "active_days": 0,
            "average_messages_per_active_day": 0.0,
        },
        "activity": {
            "hourly": [{"label": "09:00-09:59", "value": 3.0}],
            "weekday": [{"label": "周一", "value": 3.0}],
        },
        "conversation_sessions": None,
        "language_profile": {
            "mode": "group_distinctive",
            "available": True,
            "unavailable_reason": "",
            "shared_words": [],
            "side_preference_words": [],
            "members": [
                {
                    "speaker_key": "fictional-alice",
                    "display_name": "虚构 Alice",
                    "heading": "虚构 Alice",
                    "primary_words": ["风格词", "回声"],
                    "context_words": ["讨论", "项目"],
                    "expression_habits": None,
                },
            ],
        },
        "expression_culture": None,
        "members": [
            {
                "speaker_key": "fictional-alice",
                "display_name": "虚构 Alice",
                "primary_name": None,
                "secondary_name": None,
                "remark": None,
                "contextual_name": None,
                "is_viewer": True,
                "message_count": 2,
                "message_share_percent": 66.67,
                "average_length": 4.5,
                "max_length": 6,
                "active_period": "周一 09:00-09:59",
                "activity": {
                    "hourly": [
                        {"label": "09:00-09:59", "value": 2.0},
                    ],
                    "weekday": [{"label": "周一", "value": 2.0}],
                },
                "top_words": ["讨论", "项目"],
            },
        ],
    }


def test_echo_member_serializes_identity_skeleton() -> None:
    member = EchoMemberCard(
        speaker_key="10001",
        display_name="Alice",
        primary_name="Alice",
        is_viewer=False,
        message_count=1,
        message_share_percent=100.0,
        average_length=3.0,
        max_length=3,
        active_period="",
    )

    payload = echo_report_to_dict(
        EchoReportView(
            title="Echo Report",
            has_data=True,
            members=(member,),
        )
    )
    serialized = payload["members"][0]

    assert serialized["speaker_key"] == "10001"
    assert serialized["primary_name"] == "Alice"
    assert serialized["display_name"] == "Alice"
    assert serialized["secondary_name"] is None
    assert serialized["remark"] is None
    assert serialized["contextual_name"] is None
    assert serialized["is_viewer"] is False


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


def test_expression_culture_serializes_display_ready_fields_only() -> None:
    culture = EchoExpressionCulture(
        available=True,
        expression_message_count=9,
        expression_only_message_count=2,
        expression_only_rate=0.22,
        unique_expression_count=4,
        top_expressions=(
            EchoExpressionItem(
                expression_key="😀",
                display_text="😀",
                count=5,
                kind="unicode",
                with_text_message_count=4,
                text_only_message_count=1,
            ),
            EchoExpressionItem(
                expression_key="358",
                display_text="/骰子",
                count=2,
                kind="platform_face",
                with_text_message_count=2,
                text_only_message_count=0,
            ),
            EchoExpressionItem(
                expression_key="捂脸",
                display_text="[捂脸]",
                count=3,
                kind="platform_face",
                with_text_message_count=2,
                text_only_message_count=1,
                asset_key="wechat:捂脸",
                nearby_words=("挂科", "今天"),
            ),
        ),
        members=(
            EchoMemberExpression(
                speaker_key="fictional-alice",
                display_name="虚构 Alice",
                expression_occurrence_count=5,
                expression_message_count=4,
                expression_share_percent=55.6,
                expression_only_message_count=1,
                top_expressions=(
                    EchoExpressionItem(
                        expression_key="😀",
                        display_text="😀",
                        count=4,
                        kind="unicode",
                        with_text_message_count=3,
                        text_only_message_count=1,
                    ),
                ),
            ),
        ),
        top_combinations=(
            EchoExpressionCombination(
                asset_keys=("wechat:捂脸", "wechat:旺柴"),
                count=3,
                common_members=(
                    EchoExpressionCombinationMember(
                        display_name="虚构离黎",
                        count=2,
                        share_percent=66.7,
                    ),
                ),
            ),
        ),
    )

    payload = echo_report_to_dict(
        EchoReportView(
            title="Echo Report",
            has_data=True,
            expression_culture=culture,
        )
    )
    data = payload["expression_culture"]

    assert data["expression_message_count"] == 9
    assert data["expression_only_rate"] == 0.22
    assert data["top_expressions"][0]["display_text"] == "😀"
    assert data["top_expressions"][1]["kind"] == "platform_face"
    assert data["top_expressions"][0]["with_text_message_count"] == 4
    assert data["top_expressions"][0]["text_only_message_count"] == 1
    assert data["top_expressions"][2]["asset_key"] == "wechat:捂脸"
    assert data["top_expressions"][2]["nearby_words"] == ["挂科", "今天"]
    assert data["top_combinations"][0] == {
        "asset_keys": ["wechat:捂脸", "wechat:旺柴"],
        "labels": [],
        "count": 3,
        "common_members": [
            {
                "display_name": "虚构离黎",
                "count": 2,
                "share_percent": 66.7,
            }
        ],
    }
    assert data["members"][0]["top_expressions"][0]["with_text_message_count"] == 3
    assert data["members"][0]["display_name"] == "虚构 Alice"
    serialized = json.dumps(data, ensure_ascii=False)
    assert "expression_key" not in serialized
    assert "face_type" not in serialized
    assert "internal-sticker-md5" not in serialized
    assert "md5" not in serialized
    assert "source" not in serialized
    assert "text_before" not in serialized
    assert "text_after" not in serialized
    assert "D:" not in serialized
    assert "references" not in serialized


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


#: A throwaway payload; tests only assert it round-trips through base64.
_FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfake-minimal-png"


def _expression_view(
    expression_key: str,
    display_text: str,
    expression_source: str | None,
) -> EchoReportView:
    usage = analysis_models.ExpressionUsage(
        expression_key=expression_key,
        display_text=display_text,
        count=3,
        kind="platform_face",
    )
    report = analysis_models.ExpressionReport(
        expression_message_count=3,
        expression_only_message_count=1,
        expression_only_rate=0.33,
        unique_expression_count=1,
        top_expressions=(usage,),
        members=(
            analysis_models.MemberExpressionUsage(
                speaker_key="fictional-member",
                expression_occurrence_count=3,
                expression_message_count=3,
                expression_share_percent=100.0,
                expression_only_message_count=1,
                top_expressions=(usage,),
            ),
        ),
    )
    try:
        return build_echo_report_view(
            analysis_models.AnalysisReports(expression=report),
            conversation_kind="group",
            expression_source=expression_source,
        )
    except TypeError:
        pytest.fail("builder cannot express an explicit expression source")


def test_wechat_666_is_not_hijacked_by_bundled_qq_666(
    qq_asset_root: Path,
) -> None:
    # A bundled QQ 666.png must never steal the WeChat emoji named "666".
    (qq_asset_root / "666.png").write_bytes(_FAKE_PNG_BYTES)

    view = _expression_view("666", "[666]", "wechat")
    item = view.expression_culture.top_expressions[0]

    assert item.asset_key == "wechat:666"
    assert item.display_text == "666"


def test_unknown_source_never_resolves_expression_assets(
    qq_asset_root: Path,
) -> None:
    (qq_asset_root / "666.png").write_bytes(_FAKE_PNG_BYTES)

    view = _expression_view("666", "/666", None)
    item = view.expression_culture.top_expressions[0]

    assert item.asset_key is None
    assert item.display_text == "/666"
