"""Tests for the Smart Profile orchestration layer."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer import smart_profile
from qq_chat_analyzer.message import ChatMessage
from qq_chat_analyzer.smart_profile import run_smart_profile


def test_robot_candidate_flows_through_decision_engine_and_pipeline() -> None:
    robot_messages = [
        _message("虚构签到助手", "固定签到播报", index)
        for index in range(10)
    ]
    ordinary_message = _message(
        "虚构普通用户",
        "今天讨论本地测试",
        10,
    )

    result = run_smart_profile([*robot_messages, ordinary_message])

    assert result.kept_messages == [ordinary_message]
    assert result.filtered_messages == robot_messages
    assert len(result.applied_decisions) == 1
    assert result.applied_decisions[0].target_type == "sender"
    assert result.applied_decisions[0].action == "ignore"


def test_welcome_template_flows_through_decision_engine_and_pipeline() -> None:
    welcome_messages = [
        _message(
            "虚构欢迎助手",
            f"欢迎 虚构成员{member} 加入群聊",
            index,
        )
        for index, member in enumerate(("甲", "乙", "丙", "丁"))
    ]
    ordinary_message = _message(
        "虚构普通用户",
        "开始讨论课程安排",
        4,
    )

    result = run_smart_profile([*welcome_messages, ordinary_message])

    assert result.kept_messages == [ordinary_message]
    assert result.filtered_messages == welcome_messages
    assert len(result.applied_decisions) == 1
    assert result.applied_decisions[0].target_type == "template"
    assert result.applied_decisions[0].action == "ignore"


def test_repeated_template_review_does_not_filter_ordinary_messages() -> None:
    low_frequency_messages = [
        _message(
            "虚构查询助手",
            f"查询结果：虚构记录{index}",
            index,
        )
        for index in range(3)
    ]
    ordinary_message = _message(
        "虚构普通用户",
        "今天讨论本地测试方案",
        3,
    )

    result = run_smart_profile([*low_frequency_messages, ordinary_message])

    assert result.kept_messages == [*low_frequency_messages, ordinary_message]
    assert result.filtered_messages == []
    assert result.applied_decisions == []


def test_interactive_detection_is_explicit_and_does_not_run_during_default_filtering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qq_chat_analyzer.detectors import detect_interactive_bot_candidates
    from qq_chat_analyzer.decision_engine import create_filter_decisions

    messages = _interactive_messages(mention_count=20)
    interactive_candidates = detect_interactive_bot_candidates(messages)
    assert len(interactive_candidates) == 1
    assert interactive_candidates[0].target == "虚构交互助手"
    assert interactive_candidates[0].metadata == {
        "source_kind": "interactive_bot",
        "metrics": {
            "mention_count": 20,
            "response_count": 20,
            "response_rate": 1.0,
            "unique_trigger_source_count": 20,
            "response_template_score": 0.05,
        },
    }
    assert create_filter_decisions(interactive_candidates)[0].action == "review"

    def unexpected_detection(*args):
        pytest.fail("review-only interactive detection must stay off the default hot path")

    from qq_chat_analyzer import detectors
    monkeypatch.setattr(detectors, "detect_interactive_bot_candidates", unexpected_detection)
    monkeypatch.setattr(smart_profile, "detect_interactive_bot_candidates", unexpected_detection, raising=False)
    result = run_smart_profile(messages)
    assert result.applied_decisions == []
    assert result.filtered_messages == []
    assert result.kept_messages == messages


def _interactive_messages(
    *,
    mention_count: int,
    start_timestamp: int = 1_700_000_000,
) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for index in range(mention_count):
        timestamp = start_timestamp + index * 10
        response_suffix = chr(0x4E00 + index)
        messages.extend(
            [
                _message(
                    f"虚构提问者{index}",
                    "@虚构交互助手 虚构查询",
                    timestamp,
                ),
                _message(
                    "虚构交互助手",
                    f"虚构动态响应{response_suffix}",
                    timestamp + 1,
                ),
            ]
        )
    return messages


def test_literal_placeholder_template_does_not_widen_filtering() -> None:
    spam_messages = [
        _message("虚构刷屏者", f"模板是 {{variable}} 请替换{number}", index)
        for index, number in enumerate((99, 88, 77, 66))
    ]
    normal_messages = [
        _message("虚构成员甲", "模板是 X 请替换55", 10),
        _message("虚构成员乙", "模板是 YYY 请替换44", 11),
    ]

    result = run_smart_profile([*spam_messages, *normal_messages])

    assert result.filtered_messages == spam_messages
    assert result.kept_messages == normal_messages
    assert result.applied_decisions[0].target_type == "template"
    assert result.applied_decisions[0].action == "ignore"


def _message(sender: str, text: str, timestamp: int) -> ChatMessage:
    return ChatMessage(
        timestamp=timestamp,
        sender=sender,
        message_type="text",
        text=text,
    )


@pytest.mark.parametrize("script_name", ["profile_report", "debug_automation_profile"])
@pytest.mark.parametrize("mode", ["interactive", "robot"])
def test_diagnostic_detects_once_and_keeps_interactive_decisions_explicit(
    tmp_path, monkeypatch, capsys, script_name, mode,
):
    import importlib
    import json

    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "scripts"))
    script = importlib.import_module(script_name)
    messages = _interactive_messages(mention_count=20)
    # Distinct requests isolate interactive evidence from repeated templates.
    from dataclasses import replace
    messages = [replace(m, text=m.text + chr(0x4E00 + i)) if i % 2 == 0 else m
                for i, m in enumerate(messages)]
    if mode == "robot":
        messages = [_message("虚构签到助手", "固定签到播报", i) for i in range(10)]
        messages.append(_message("虚构普通用户", "今天讨论本地测试", 10))
    interactive_count, decision_count, filtered, kept = (
        (1, 0, 0, 40) if mode == "interactive" else (0, 1, 10, 1)
    )
    source = tmp_path / "fictional-private-export.json"
    source.write_text(json.dumps({
        "exportInfo": {"format": "detailed-json"},
        "session": {"wxid": "fictional-room", "isGroup": True},
        "messages": [{"createTime": m.timestamp, "type": "文本消息",
                      "content": m.text, "senderUsername": m.sender,
                      "senderDisplayName": m.sender} for m in messages],
    }, ensure_ascii=False), encoding="utf-8")
    calls = {"robot": 0, "template": 0, "interactive": 0}

    def count_detector(name, detector):
        def detect(values):
            calls[name] += 1
            return detector(values)
        return detect

    for name, attribute in (("robot", "detect_robot_candidates"),
                            ("template", "detect_template_candidates"),
                            ("interactive", "detect_interactive_bot_candidates")):
        detector = count_detector(name, getattr(script, attribute))
        monkeypatch.setattr(script, attribute, detector)
        if hasattr(smart_profile, attribute):
            monkeypatch.setattr(smart_profile, attribute, detector)

    assert script.main([str(source)]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert calls == {"robot": 1, "template": 1, "interactive": 1}
    if script_name == "profile_report":
        assert f"interactive_bot candidate 数量: {interactive_count}" in output.out
        assert f"automation_source review 数量: {interactive_count}" in output.out
        assert f"FilterDecision 数量: {decision_count}" in output.out
        assert f"ignore 数量: {decision_count}" in output.out
        assert "review 数量: 0" in output.out
        assert f"filtered_messages 数量: {filtered}" in output.out
        assert f"kept_messages 数量: {kept}" in output.out
    else:
        assert f"交互机器人候选数量: {interactive_count}" in output.out
        assert f"人工审核数量: {interactive_count}" in output.out
        assert f"过滤消息数量: {filtered}" in output.out
        assert f"保留消息数量: {kept}" in output.out
    for secret in (str(source), "fictional-room", "虚构交互助手", "虚构动态响应",
                   "虚构签到助手", "固定签到播报", "今天讨论本地测试"):
        assert secret not in output.out + output.err
