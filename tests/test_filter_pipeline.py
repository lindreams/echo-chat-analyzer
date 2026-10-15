"""Tests for applying filtering decisions to parsed messages."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.candidates import Candidate
from qq_chat_analyzer.decision_engine import create_filter_decisions
from qq_chat_analyzer.detectors import detect_template_candidates
from qq_chat_analyzer.filter_decisions import FilterDecision
from qq_chat_analyzer.filter_pipeline import FilterPipeline
from qq_chat_analyzer import filter_pipeline
from qq_chat_analyzer.message import ChatMessage


def test_sender_ignore_filters_matching_sender_messages() -> None:
    ignored_message = _message("虚构签到助手", "签到成功", 1)
    kept_message = _message("虚构普通用户", "今天讨论测试方案", 2)
    decision = _decision(
        target="虚构签到助手",
        target_type="sender",
        action="ignore",
    )

    result = FilterPipeline().apply_filter_decisions(
        [ignored_message, kept_message],
        [decision],
    )

    assert result.kept_messages == [kept_message]
    assert result.filtered_messages == [ignored_message]
    assert result.applied_decisions == [decision]


def test_template_ignore_filters_matching_template_messages() -> None:
    ignored_message = _message(
        "虚构欢迎助手",
        "欢迎   虚构新成员   加入群聊！",
        1,
    )
    kept_message = _message("虚构普通用户", "欢迎大家讨论新主题", 2)
    decision = _decision(
        target="欢迎 {variable} 加入群聊",
        target_type="template",
        action="ignore",
    )

    result = FilterPipeline().apply_filter_decisions(
        [ignored_message, kept_message],
        [decision],
    )

    assert result.kept_messages == [kept_message]
    assert result.filtered_messages == [ignored_message]
    assert result.applied_decisions == [decision]


@pytest.mark.parametrize(
    ("sender", "text", "template"),
    [
        pytest.param(
            "虚构运势助手",
            "综合指数:42.5 财运指数:68",
            "综合指数:{number} 财运指数:{number}",
            id="number",
        ),
        pytest.param(
            "虚构查询助手",
            "查询编号123456",
            "查询编号{id}",
            id="id",
        ),
        pytest.param(
            "虚构运势助手",
            "@虚构用户 今日运势:99",
            "@{user} 今日运势:{number}",
            id="user",
        ),
        pytest.param(
            "虚构查询助手",
            "详情:https://example.test/a/42，版本:3",
            "详情:{url}，版本:{number}",
            id="url",
        ),
    ],
)
def test_fingerprint_ignore_filters_matching_message(
    sender: str,
    text: str,
    template: str,
) -> None:
    ignored_message = _message(sender, text, 1)
    decision = _decision(
        target=template,
        target_type="template",
        action="ignore",
    )

    result = FilterPipeline().apply_filter_decisions(
        [ignored_message],
        [decision],
    )

    assert result.filtered_messages == [ignored_message]
    assert result.applied_decisions == [decision]


def test_number_fingerprint_does_not_match_long_integer_id() -> None:
    kept_message = _message(
        "虚构查询助手",
        "综合指数:123456",
        1,
    )
    decision = _decision(
        target="综合指数:{number}",
        target_type="template",
        action="ignore",
    )

    result = FilterPipeline().apply_filter_decisions(
        [kept_message],
        [decision],
    )

    assert result.kept_messages == [kept_message]
    assert result.filtered_messages == []
    assert result.applied_decisions == []


def test_review_decision_does_not_filter_messages() -> None:
    message = _message("虚构待复核用户", "这是一条虚构消息", 1)
    decision = _decision(
        target="虚构待复核用户",
        target_type="sender",
        action="review",
    )

    result = FilterPipeline().apply_filter_decisions(
        [message],
        [decision],
    )

    assert result.kept_messages == [message]
    assert result.filtered_messages == []
    assert result.applied_decisions == []


def test_automation_source_candidate_never_filters_sender_messages() -> None:
    first_message = _message(
        "虚构交互助手",
        "这是一条虚构自动响应",
        1,
    )
    second_message = _message(
        "虚构普通用户",
        "这是一条虚构普通消息",
        2,
    )
    decisions = create_filter_decisions(
        [
                Candidate(
                    target="虚构交互助手",
                    candidate_type="automation_source",
                    score=0.95,
                    metadata={
                        "source_kind": "interactive_bot",
                        "metrics": {
                            "mention_count": 100,
                            "response_rate": 0.95,
                            "unique_trigger_source_count": 20,
                            "concentrated_in_short_window": False,
                        },
                    },
                )
            ]
        )

    result = FilterPipeline().apply_filter_decisions(
        [first_message, second_message],
        decisions,
    )

    assert [decision.action for decision in decisions] == ["review"]
    assert result.kept_messages == [first_message, second_message]
    assert result.filtered_messages == []
    assert result.applied_decisions == []


def _message(sender: str, text: str, timestamp: int) -> ChatMessage:
    return ChatMessage(
        timestamp=timestamp,
        sender=sender,
        message_type="text",
        text=text,
    )


def _decision(
    target: str,
    target_type: str,
    action: str,
) -> FilterDecision:
    return FilterDecision(
        target=target,
        target_type=target_type,
        action=action,
        confidence=1.0,
        reason="synthetic_test_decision",
        source="user",
    )


def test_literal_placeholder_template_does_not_over_match() -> None:
    spam_messages = [
        _message("虚构刷屏者", f"模板是 {{variable}} 请替换{number}", index)
        for index, number in enumerate((99, 88, 77, 66))
    ]
    lookalike_messages = [
        _message("虚构成员甲", "模板是 X 请替换55", 10),
        _message("虚构成员乙", "模板是 YYY 请替换44", 11),
    ]
    messages = [*spam_messages, *lookalike_messages]
    decisions = create_filter_decisions(detect_template_candidates(messages))

    result = FilterPipeline().apply_filter_decisions(messages, decisions)

    assert result.filtered_messages == spam_messages
    assert result.kept_messages == lookalike_messages


def test_literal_placeholder_template_matches_its_own_messages() -> None:
    messages = [
        _message("虚构刷屏者", f"编号{{id}}的完成{number}", index)
        for index, number in enumerate((99, 88, 77, 66))
    ]
    decisions = create_filter_decisions(detect_template_candidates(messages))

    result = FilterPipeline().apply_filter_decisions(messages, decisions)

    assert result.filtered_messages == messages
    assert result.kept_messages == []
    assert len(result.applied_decisions) == 1
