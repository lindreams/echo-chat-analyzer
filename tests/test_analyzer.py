"""Behavioral tests for token frequency analysis."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer import analyzer
from qq_chat_analyzer.analyzer import count_words, top_words


def test_counts_repeated_tokens() -> None:
    assert count_words(["数据", "分析", "数据", "数据"]) == {
        "数据": 3,
        "分析": 1,
    }


def test_counts_word_occurrences_for_each_sender() -> None:
    sender_tokens = [
        ("小青", ["数据", "Python"]),
        ("小白", ["数据", "分析"]),
        ("小青", ["数据"]),
    ]

    assert analyzer.count_word_speakers(sender_tokens) == {
        "数据": {"小青": 2, "小白": 1},
        "Python": {"小青": 1},
        "分析": {"小白": 1},
    }


def test_repeated_word_in_one_message_counts_every_occurrence() -> None:
    sender_tokens = [("小青", ["算法", "算法", "算法"])]

    assert analyzer.count_word_speakers(sender_tokens) == {
        "算法": {"小青": 3},
    }


def test_summary_calculates_percentage_to_two_decimal_places() -> None:
    counts = {
        "数据": {
            "小青": 2,
            "小白": 1,
        }
    }

    summaries = analyzer.top_word_speaker_summary(counts)

    assert summaries[0].top_speaker_share_percent == 66.67
