"""Behavioral tests for the future chat-text cleaner."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.cleaner import clean_text


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


@pytest.mark.parametrize(("text", "expected"), [
    ("好的@虚构小明\u2005明天开会", "好的 明天开会"),
    ("@虚构 张同学\u2005明天开会", "明天开会"),
    ("开会@虚构，张同学\u2005讨论", "开会 讨论"),
    ("@虚构甲\u2005@虚构 乙\u2005公园散步[捂脸]", "公园散步[捂脸]"),
    ("收到@虚构小明 明天开会", "收到 明天开会"),
    ("@虚构 张同学\u2005", ""),
    ("发给 person@example.com\u2005明天开会", "发给 person@example.com 明天开会"),
])
def test_wechat_clean_removes_complete_mentions_without_losing_body(text, expected):
    assert clean_text(text, platform="wechat") == expected
