"""Behavior tests for the private shared-word language analyzer."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.analysis.analyzers import PrivateLanguageAnalyzer  # noqa: E402


def _analyze(
    sender_tokens: tuple[tuple[str, list[str]], ...],
    *,
    conversation_type: str = "private",
):
    return PrivateLanguageAnalyzer().analyze(
        sender_tokens,
        conversation_type=conversation_type,
    )


def test_private_shared_words_count_totals_and_rates() -> None:
    report = _analyze(
        (
            ("fictional-a", ["x"] * 10 + ["y"] * 5 + ["z"]),
            ("fictional-b", ["x"] * 5 + ["y"] * 2 + ["w"] * 2),
        )
    )

    words = {entry.word: entry for entry in report.shared_words}
    assert set(words) == {"x", "y"}
    assert "z" not in words
    assert "w" not in words

    x = words["x"]
    assert (x.count_a, x.count_b) == (10, 5)
    assert (x.total_tokens_a, x.total_tokens_b) == (16, 9)
    assert (x.rate_a, x.rate_b) == (10 / 16, 5 / 9)
    assert x.common_strength == min(10 / 16, 5 / 9)
    assert x.occurrence_support == 5

    y = words["y"]
    assert (y.count_a, y.count_b) == (5, 2)
    assert (y.total_tokens_a, y.total_tokens_b) == (16, 9)
    assert (y.rate_a, y.rate_b) == (5 / 16, 2 / 9)


def test_private_side_preference_uses_normalized_rate() -> None:
    report = _analyze(
        (
            ("fictional-a", ["word"] * 8 + ["other"] * 92),
            ("fictional-b", ["word"] * 5 + ["other"] * 5),
        )
    )

    entry = next(item for item in report.shared_words if item.word == "word")
    assert entry.rate_a == 8 / 100
    assert entry.rate_b == 5 / 10
    assert entry.preferred_speaker_key == "fictional-b"


def test_private_language_non_private_returns_empty_report() -> None:
    report = _analyze(
        (
            ("fictional-a", ["word"]),
            ("fictional-b", ["word"]),
        ),
        conversation_type="group",
    )

    assert report.shared_words == ()
