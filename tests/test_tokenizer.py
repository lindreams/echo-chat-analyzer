"""Behavioral tests for jieba tokenization and stopword filtering."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.tokenizer import tokenize
from qq_chat_analyzer.wechat_official_emojis import WECHAT_EMOJI_ALIASES


def test_tokenizes_chinese_text_with_jieba() -> None:
    assert tokenize("我喜欢数据分析") == ["喜欢", "数据分析"]


def test_filters_trimmed_stopwords_and_ignores_blank_lines(
    tmp_path: Path,
) -> None:
    stopwords_path = tmp_path / "stopwords.txt"
    stopwords_path.write_text("  我  \n\n喜欢\n", encoding="utf-8")

    assert tokenize("我喜欢数据分析", str(stopwords_path)) == ["数据分析"]
