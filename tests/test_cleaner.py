"""Behavioral tests for the future chat-text cleaner."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.cleaner import clean_text


def test_removes_image_placeholder() -> None:
    assert clean_text("开始[图片]继续") == "开始继续"


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        ("[回复消息] 收到", "收到"),
        ("[回复消息：这是一段虚构引用] 我同意", "我同意"),
    ],
)
def test_removes_reply_structure_text(raw_text: str, expected: str) -> None:
    assert clean_text(raw_text) == expected


def test_removes_nickname_mention() -> None:
    assert clean_text("@虚构用户乙 请查看资料") == "请查看资料"


def test_mention_cleaning_preserves_regular_text() -> None:
    assert clean_text("邮箱 a@b.com 正常") == (
        "邮箱 a@b.com 正常"
    )
    assert clean_text("今天@一下试试") == (
        "今天@一下试试"
    )
    assert clean_text("@张三 @李四 一起吃饭") == (
        "一起吃饭"
    )


def test_removes_control_characters_and_normalizes_whitespace_controls() -> None:
    assert clean_text("甲\x00乙\x07丙\n丁\t戊") == "甲乙丙 丁 戊"


def test_collapses_repeated_whitespace() -> None:
    assert clean_text("今天   学习\n\t Python") == "今天 学习 Python"


def test_preserves_normal_chinese_english_and_numbers() -> None:
    assert clean_text("中文 Python3 CS61B 2026") == "中文 Python3 CS61B 2026"


def test_wechat_clean_removes_internal_ids() -> None:
    assert clean_text("今天开会 wxid_test", platform="wechat") == "今天开会"
    assert clean_text(
        "内部 xa66c49rvh7212 hvly3bywwfbz22 记录",
        platform="wechat",
    ) == "内部 记录"


def test_wechat_clean_preserves_official_expression_markers() -> None:
    assert clean_text(
        "今天真的崩了[捂脸] [OK] 继续[旺柴]",
        platform="wechat",
    ) == "今天真的崩了[捂脸] [OK] 继续[旺柴]"


def test_wechat_clean_does_not_affect_other_platforms() -> None:
    assert clean_text("内部 wxid_test xa66c49rvh7212") == (
        "内部 wxid_test xa66c49rvh7212"
    )
    assert clean_text(
        "内部 wxid_test xa66c49rvh7212",
        platform="qq",
    ) == "内部 wxid_test xa66c49rvh7212"


def test_structural_only_text_cleans_to_empty_string() -> None:
    raw_text = "@全体成员 [图片] [回复消息]\u200b \x00"

    assert clean_text(raw_text) == ""
