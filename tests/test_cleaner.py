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
