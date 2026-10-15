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


#: A throwaway payload; tests only assert it round-trips through base64.
_FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfake-minimal-png"
