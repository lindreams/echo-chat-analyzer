"""Behavior tests for source-neutral distinctive-word analysis."""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _analysis():
    return importlib.import_module("qq_chat_analyzer.analysis")


def _eligible_records(
    speaker: str,
    distinctive: str,
    *,
    common_count: int = 90,
    distinctive_count: int = 18,
) -> list[tuple[str, list[str]]]:
    """Build 30 tokenized messages and at least three candidate words."""
    tokens = (
        ["共同词"] * common_count
        + [distinctive] * distinctive_count
        + [f"{distinctive}-二"] * 6
        + [f"{distinctive}-三"] * 3
    )
    records = [(speaker, []) for _ in range(30)]
    for index, token in enumerate(tokens):
        records[index % len(records)][1].append(token)
    return records


def _three_eligible_members():
    return (
        _eligible_records("member-a", "偏好甲")
        + _eligible_records("member-b", "偏好乙")
        + _eligible_records("member-c", "偏好丙")
    )


def _member(report, speaker_key: str):
    return next(
        member
        for member in report.members
        if member.speaker_key == speaker_key
    )


def test_distinctive_words_rank_personal_preference_above_group_common_word() -> None:
    analysis = _analysis()

    report = analysis.DistinctiveWordAnalyzer().analyze(
        _three_eligible_members(),
        conversation_type="group",
    )

    assert report.available is True
    member = _member(report, "member-a")
    words = [item.word for item in member.words]
    assert words[0] == "偏好甲"
    assert words.index("偏好甲") < words.index("共同词")


def test_repeated_stable_sender_key_aggregates_into_one_member() -> None:
    analysis = _analysis()
    records = _three_eligible_members()
    # The first member arrives in many records under the same source-neutral key.
    assert sum(speaker == "member-a" for speaker, _ in records) == 30

    report = analysis.DistinctiveWordAnalyzer().analyze(
        records,
        conversation_type="group",
    )

    member = _member(report, "member-a")
    assert member.tokenized_message_count == 30
    assert len([item for item in report.members if item.speaker_key == "member-a"]) == 1
