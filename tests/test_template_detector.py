"""Tests for repeated message template candidate detection."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.detectors.template_detector import (
    detect_template_candidates,
)
from qq_chat_analyzer.message import ChatMessage


def test_structurally_identical_fortune_messages_share_fingerprint() -> None:
    user_names = [
        "虚构甲",
        "虚构乙",
        "虚构丙",
        "虚构丁",
        "虚构戊",
        "虚构己",
        "虚构庚",
        "虚构辛",
        "虚构壬",
        "虚构癸",
    ]
    messages = [
        _message(
            "虚构运势助手",
            (
                f"@{user_name} 综合指数：{40 + index}.5 "
                f"财运指数：{60 + index}"
            ),
            index,
        )
        for index, user_name in enumerate(user_names)
    ]

    candidates = detect_template_candidates(messages)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.target == (
        "@{user} 综合指数：{number} 财运指数：{number}"
    )
    assert candidate.candidate_type == "repeated_template"
    assert candidate.metadata["fingerprint"] == candidate.target
    assert candidate.metadata["occurrence_count"] == 10
    assert candidate.metadata["variable_count"] == 3
    assert candidate.metadata["variable_counts"] == {
        "user": 1,
        "number": 2,
    }
    assert candidate.metadata["static_character_count"] == 8
    assert candidate.metadata["unique_sender_count"] == 1
    assert candidate.metadata["top_sender_ratio"] == 1.0


def test_shared_keywords_with_different_structures_are_not_templates() -> None:
    messages = [
        _message("虚构用户甲", "我觉得新生指南第1段很清楚", 0),
        _message("虚构用户乙", "新生指南第2段我还没看", 1),
        _message("虚构用户丙", "刚看完新生指南3，内容不少", 2),
        _message("虚构用户丁", "有人讨论新生指南第4部分吗", 3),
    ]

    assert detect_template_candidates(messages) == []


def _message(sender: str, text: str, timestamp: int) -> ChatMessage:
    return ChatMessage(
        timestamp=timestamp,
        sender=sender,
        message_type="text",
        text=text,
    )
