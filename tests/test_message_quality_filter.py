"""Tests for deterministic local message quality filtering."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.message import ChatMessage
from qq_chat_analyzer.message_quality_filter import (
    LONG_TEXT_THRESHOLD,
    apply_message_quality_filter,
)


def test_messages_at_least_100_characters_are_filtered() -> None:
    long_text = _long_text(LONG_TEXT_THRESHOLD)
    message = _message("虚构用户", long_text, 1_700_000_000)

    result = apply_message_quality_filter([message])

    assert len(long_text) == LONG_TEXT_THRESHOLD
    assert result.kept_messages == []
    assert result.filtered_messages == [message]
    assert len(result.reasons) == 1
    reason = result.reasons[0]
    assert reason.message is message
    assert reason.reason == "long_text_outlier"
    assert reason.metadata == {
        "length": LONG_TEXT_THRESHOLD,
        "threshold": LONG_TEXT_THRESHOLD,
    }


def test_single_character_repeat_spam_is_filtered() -> None:
    message = _message("虚构用户", "哈哈哈哈哈哈哈哈", 1_700_000_000)

    result = apply_message_quality_filter([message])

    assert result.kept_messages == []
    assert result.filtered_messages == [message]
    assert result.reasons[0].reason == "noise_single_character_repeat"


def test_long_sentence_repetition_is_filtered_without_losing_ordinary_emphasis() -> None:
    phrase = "明天终于可以带着小狗出去散步啦！"
    spam_text = phrase * 6
    assert len(phrase) > 12 and len(spam_text) < LONG_TEXT_THRESHOLD
    spam = _message("虚构用户", spam_text, 1_700_000_000)
    ordinary = [
        _message("虚构用户", phrase * 2, 1_700_000_120),
        _message("虚构用户", phrase * 3 + "还要带点零食", 1_700_000_240),
    ]
    messages = [spam, *ordinary]

    result = apply_message_quality_filter(messages)

    assert result.kept_messages == ordinary
    assert result.filtered_messages == [spam]
    assert result.reasons[0].reason == "noise_repeated_fragment"
    assert result.reasons[0].metadata["repeat_count"] == 6
    assert messages == [spam, *ordinary] and spam.text == spam_text


def test_same_text_burst_within_60_seconds_keeps_only_first() -> None:
    first = _message("虚构用户甲", "这句话被连续复制", 1_700_000_000)
    second = _message("虚构用户甲", "这句话被连续复制", 1_700_000_015)
    third = _message("虚构用户甲", "这句话被连续复制", 1_700_000_030)

    result = apply_message_quality_filter([first, second, third])

    assert result.kept_messages == [first]
    assert result.filtered_messages == [second, third]
    assert [reason.reason for reason in result.reasons] == [
        "noise_sender_burst_repeat",
        "noise_sender_burst_repeat",
    ]
    assert all(
        reason.metadata["repeat_count"] == 3 for reason in result.reasons
    )


def test_normal_chat_is_not_mis_filtered() -> None:
    messages = [
        _message("虚构用户甲", "今天天气不错，我们晚上一起吃饭吧", 1_700_000_000),
        _message("虚构用户甲", "哈哈哈", 1_700_000_010),
        _message("虚构用户乙", "😂😂", 1_700_000_020),
        _message("虚构用户乙", "好的，七点见", 1_700_000_030),
        _message("虚构用户甲", "明天见", 1_700_000_040),
    ]

    result = apply_message_quality_filter(messages)

    assert result.kept_messages == messages
    assert result.filtered_messages == []
    assert result.reasons == []


def test_copy_campaign_variants_are_filtered_without_excluding_the_sender() -> None:
    ordinary = _message("虚构用户甲", "今晚一起公园散步吧", 1_700_000_000)
    promotions = [
        _message("虚构用户甲", text, 1_700_000_060 + index * 120)
        for index, text in enumerate([
            "限时礼包来了！复制口令【星空福利AbCdEf】参与活动。",
            "wxid_fictional_peer:\n复制【星空礼包Q7w8E9】口令，免费奖励等你来拿！",
            "【虚构庆典】皮肤好礼，复制以下口令并粘贴：K9m2P4，和好友一起参与。",
            "限时奖励，复制兑换码：ABCDEF，前往活动页面使用。",
        ])
    ]
    messages = [promotions[0], ordinary, *promotions[1:]]

    result = apply_message_quality_filter(messages)

    assert result.kept_messages == [ordinary]
    assert result.filtered_messages == promotions
    assert {reason.reason for reason in result.reasons} == {"copy_promotion"}
    assert messages == [promotions[0], ordinary, *promotions[1:]]


def test_copy_promotion_requires_an_instruction_reward_and_structured_code() -> None:
    messages = [
        _message("虚构用户甲", text, 1_700_000_000 + index * 120)
        for index, text in enumerate([
            "那个限时礼包的口令怎么复制？",
            "限时礼包的口令 ABCDEF 怎么复制？我没看懂。",
            "昨天说的游戏皮肤和活动口令我都记得，复制那个按钮找不到了。",
            "测试数据，复制口令【虚构标识AbCdEf】，检查字符串是否一致。",
            "限时福利，欢迎来公园活动，报名编号 ABCDEF。",
            "口令：ABCDEF，是刚才那个免费礼包的吗？",
            "复制文件时提示口令错误，邮件发到 reward@example.com。",
        ])
    ]

    result = apply_message_quality_filter(messages)

    assert result.kept_messages == messages
    assert result.filtered_messages == []


def test_original_messages_are_never_removed_from_input() -> None:
    messages = [
        _message("虚构用户", "哈哈哈哈哈哈哈哈", 1_700_000_000),
        _message("虚构用户", "正常消息", 1_700_000_010),
    ]
    snapshot = list(messages)

    result = apply_message_quality_filter(messages)

    assert messages == snapshot
    assert len(messages) == 2
    assert set(result.kept_messages) | set(result.filtered_messages) == set(messages)


def test_interleaved_same_nickname_identities_are_never_a_burst() -> None:
    messages = [
        _message("同名用户", "复制内容", 1_700_000_000 + offset, sender_id=identity)
        for offset, identity in (
            (0, "u-a"),
            (10, "u-b"),
            (20, "u-a"),
            (30, "u-b"),
            (40, "u-a"),
            (50, "u-b"),
        )
    ]

    result = apply_message_quality_filter(messages)

    assert result.kept_messages == messages
    assert result.filtered_messages == []
    assert result.reasons == []


def test_consecutive_identities_each_keep_their_own_first_message() -> None:
    first_identity = [
        _message("同名用户", "复制内容", 1_700_000_000 + offset, sender_id="u-a")
        for offset in (0, 10, 20)
    ]
    second_identity = [
        _message("同名用户", "复制内容", 1_700_000_030 + offset, sender_id="u-b")
        for offset in (0, 10, 20)
    ]

    result = apply_message_quality_filter([*first_identity, *second_identity])

    assert result.kept_messages == [first_identity[0], second_identity[0]]
    assert result.filtered_messages == [
        *first_identity[1:],
        *second_identity[1:],
    ]


def test_renamed_identity_still_forms_one_burst() -> None:
    messages = [
        _message("旧昵称", "复制内容", 1_700_000_000, sender_id="u-renamed"),
        _message("旧昵称", "复制内容", 1_700_000_010, sender_id="u-renamed"),
        _message("新昵称", "复制内容", 1_700_000_020, sender_id="u-renamed"),
        _message("新昵称", "复制内容", 1_700_000_030, sender_id="u-renamed"),
    ]

    result = apply_message_quality_filter(messages)

    assert result.kept_messages == [messages[0]]
    assert result.filtered_messages == messages[1:]
    assert {reason.metadata["repeat_count"] for reason in result.reasons} == {4}


def test_unresolved_record_never_joins_a_resolved_identity_burst() -> None:
    unresolved = _message("同名用户", "复制内容", 1_700_000_000)
    resolved = [
        _message("同名用户", "复制内容", 1_700_000_010 + offset, sender_id="u-a")
        for offset in (0, 10, 20)
    ]

    result = apply_message_quality_filter([unresolved, *resolved])

    assert result.kept_messages == [unresolved, resolved[0]]
    assert result.filtered_messages == [resolved[1], resolved[2]]


def _long_text(length: int) -> str:
    base = (
        "本地聊天分析工具只在本机处理数据，不依赖任何网络服务，"
        "所有隐私信息都不会离开这台电脑，这是设计上最重要的原则。"
    )
    return (base * 3)[:length]


def _message(
    sender: str,
    text: str,
    timestamp: int,
    *,
    sender_id: str | None = None,
) -> ChatMessage:
    return ChatMessage(
        timestamp=timestamp,
        sender=sender,
        message_type="text",
        text=text,
        sender_id=sender_id,
    )
