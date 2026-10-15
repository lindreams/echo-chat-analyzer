"""Behavior tests for the Echo share-card builder and HTML template."""

from __future__ import annotations

import importlib
import json
import re


def _models():
    return importlib.import_module("qq_chat_analyzer.presentation.models")


def _share():
    return importlib.import_module("qq_chat_analyzer.presentation.share")


def _private_view():
    models = _models()
    return models.EchoReportView(
        title="Echo Report",
        has_data=True,
        conversation_kind="private",
        conversation_name="你和 TA",
        time_span="302 天",
        total_message_count=8438,
        participant_count=2,
        hourly_activity=(
            models.ChartPoint("16:00-16:59", 12.0),
            models.ChartPoint("17:00-17:59", 8.0),
        ),
        weekday_activity=(
            models.ChartPoint("周二", 15.0),
            models.ChartPoint("周三", 6.0),
        ),
        members=(
            models.EchoMemberCard(
                speaker_key="u1",
                display_name="Alice",
                is_viewer=True,
                message_count=4200,
                message_share_percent=50.0,
                average_length=6.0,
                max_length=20,
                active_period="",
            ),
            models.EchoMemberCard(
                speaker_key="u2",
                display_name="Bob",
                is_viewer=False,
                message_count=4238,
                message_share_percent=50.0,
                average_length=7.0,
                max_length=22,
                active_period="",
            ),
        ),
        conversation_sessions=models.EchoConversationSessions(
            threshold_seconds=1800,
            session_count=811,
            average_duration_seconds=1200.0,
            median_duration_seconds=900.0,
            longest_duration_seconds=7380,
            average_message_count=10.4,
        ),
        language_profile=models.EchoLanguageProfile(
            mode="private_common",
            available=True,
            members=(
                models.EchoLanguageMember(
                    speaker_key="u1",
                    display_name="Alice",
                    heading="你常说",
                    primary_words=("确实", "懂了", "哈哈"),
                ),
                models.EchoLanguageMember(
                    speaker_key="u2",
                    display_name="Bob",
                    heading="TA 常说",
                    primary_words=("笑死", "可以", "嗯嗯"),
                ),
            ),
        ),
        expression_culture=models.EchoExpressionCulture(
            available=True,
            expression_message_count=120,
            expression_only_message_count=40,
            unique_expression_count=9,
            top_expressions=(
                models.EchoExpressionItem(
                    expression_key="😂",
                    display_text="😂",
                    count=30,
                    kind="emoji",
                    nearby_words=("哈哈哈",),
                ),
                models.EchoExpressionItem(
                    expression_key="👍",
                    display_text="👍",
                    count=22,
                    kind="emoji",
                    nearby_words=("确实",),
                ),
                models.EchoExpressionItem(
                    expression_key="😭",
                    display_text="😭",
                    count=18,
                    kind="emoji",
                    nearby_words=("笑死",),
                ),
            ),
        ),
    )


def test_private_share_card_uses_human_readable_fields() -> None:
    data = _share().build_share_card_data(_private_view())

    assert data.has_data is True
    assert data.conversation_label == "私聊"
    assert data.conversation_name == "你 & Bob"
    assert data.message_count_display == "8,438"
    assert data.time_span_display == "302 天"
    assert data.sessions is not None
    assert data.sessions.headline == "你们一共聊了 811 轮"
    assert data.sessions.average_value == "10.4 条消息"
    assert data.sessions.longest_value == "2 小时 3 分钟"
    assert data.rhythm is not None
    assert data.rhythm.hour_value == "下午四点左右"
    assert data.rhythm.weekday_value == "周二"


def test_share_html_payload_assignment_preserves_window_property() -> None:
    html = _share().build_share_card_html(
        _share().ShareCardData(
            has_data=True,
            message_count_display="8,438",
            time_span_display="302 天",
        )
    )

    assignment = re.search(r"window\.__SHARE_DATA__ = (.+);", html)

    assert assignment is not None, "payload replacement corrupted the window property"
    payload = json.loads(assignment.group(1))
    assert payload["data"]["message_count_display"] == "8,438"
    assert payload["data"]["time_span_display"] == "302 天"
