"""Behavior tests for the Analysis Core v2 report analyzers."""

from __future__ import annotations

import dataclasses
import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _models():
    return importlib.import_module("qq_chat_analyzer.analysis.models")


def test_user_profile_repr_hides_identity_and_words_without_changing_payload():
    models = _models()
    identities = dict(speaker="fictional-private-speaker", speaker_key="fictional-private-key",
                      display_name="fictional-private-display", remark="fictional-private-remark",
                      nickname="fictional-private-nickname", contextual_name="fictional-private-context")
    profile = models.UserProfile(
        **identities, message_count=3, message_share_percent=100, average_length=4, max_length=5,
        top_words=(models.ProfileWord("fictional-private-word", 2),),
    )
    reports = models.AnalysisReports(user_profiles=models.UserProfileReport(3, 1, (profile,)))
    assert "fictional-private" not in repr(reports)
    assert "fictional-private" not in repr(profile.top_words[0])
    payload = dataclasses.asdict(profile)
    assert {key: payload[key] for key in identities} == identities
    assert payload["top_words"] == ({"word": "fictional-private-word", "count": 2},)
    assert profile.resolved_display_name == identities["display_name"]
    assert profile.message_count == 3


@pytest.mark.parametrize("name, values", [
    ("MemberDistinctiveWords", dict(speaker_key="fictional-private-key", tokenized_message_count=2,
                                    token_count=3, eligible_word_candidate_count=1)),
    ("PrivateSharedWord", dict(word="fictional-private-word", speaker_a="fictional-private-a",
                               speaker_b="fictional-private-b", preferred_speaker_key="fictional-private-a",
                               count_a=2, count_b=3, total_tokens_a=4, total_tokens_b=5,
                               rate_a=.5, rate_b=.6, common_strength=.5, occurrence_support=5)),
    ("ConversationSummary", dict(conversation_id="fictional-private-room", display_name="fictional-private-name",
                                 message_count=3, speaker_count=2)),
    ("ExpressionCombinationMemberCount", dict(speaker_key="fictional-private-key", count=2)),
    ("MemberExpressionUsage", dict(speaker_key="fictional-private-key", expression_occurrence_count=2,
                                   expression_message_count=2, expression_share_percent=100,
                                   expression_only_message_count=1)),
    ("DistinctiveWord", dict(word="fictional-private-word", count=2, member_rate=.5,
                             others_rate=.1, relative_ratio=5, ranking_score=1)),
    ("ExpressionNearbyWord", dict(word="fictional-private-word", count=2)),
])
def test_adjacent_core_report_repr_hides_identity_and_retains_fields(name, values):
    model = getattr(_models(), name)(**values)
    assert "fictional-private" not in repr(model)
    assert {key: dataclasses.asdict(model)[key] for key in values} == values


def _analyzers():
    return importlib.import_module("qq_chat_analyzer.analysis.analyzers")


def _chat_message():
    return importlib.import_module("qq_chat_analyzer.message").ChatMessage


def _epoch(
    year: int = 2024,
    month: int = 1,
    day: int = 1,
    hour: int = 0,
    minute: int = 0,
) -> int:
    return int(
        datetime(
            year,
            month,
            day,
            hour,
            minute,
            tzinfo=timezone(timedelta(hours=8)),
        ).timestamp()
    )


def _message(
    *,
    timestamp: int | float | str = 0,
    sender: str = "Fictional-Alice",
    text: str = "fictional text",
    conversation_id: str | None = "fictional-room-1",
):
    return _chat_message()(
        timestamp=timestamp,
        sender=sender,
        message_type="text",
        text=text,
        platform="fictional",
        conversation_id=conversation_id,
    )


def test_activity_analyzer_counts_epoch_in_beijing_local_hour() -> None:
    beijing_evening = int(
        datetime(
            2024,
            1,
            1,
            20,
            30,
            tzinfo=timezone(timedelta(hours=8)),
        ).timestamp()
    )

    report = _analyzers().ActivityAnalyzer().analyze(
        (_message(timestamp=beijing_evening),)
    )

    hourly = {entry.hour: entry.count for entry in report.hourly_counts}
    assert hourly[20] == 1
    assert hourly[12] == 0


def test_activity_analyzer_active_days_multiple_days_and_density() -> None:
    report = _analyzers().ActivityAnalyzer().analyze(
        (
            _message(timestamp=_epoch(day=1, hour=8)),
            _message(timestamp=_epoch(day=2, hour=8)),
            _message(timestamp=_epoch(day=2, hour=9)),
            _message(timestamp=_epoch(day=3, hour=20)),
            _message(timestamp=_epoch(day=3, hour=21)),
            _message(timestamp=_epoch(day=3, hour=22)),
        )
    )

    assert report.active_days == 3
    assert report.average_messages_per_active_day == 2.0


@pytest.mark.parametrize(
    "timestamps, dated, days, density, hours, weekdays",
    [
        ((), 0, 0, 0.0, [], []),
        ((0, "invalid"), 0, 0, 0.0, [], []),
        ((_epoch(day=1, hour=8), _epoch(day=1, hour=8),
          _epoch(day=2, hour=20), "invalid"),
         3, 2, 2.0, [(8, 2), (20, 1)], [(0, 2), (1, 1)]),
    ],
    ids=["empty", "undated", "mixed-dates-density-includes-undated"],
)
def test_activity_counts_and_density_preserve_undated_messages(
    timestamps, dated, days, density, hours, weekdays,
) -> None:
    report = _analyzers().ActivityAnalyzer().analyze(
        [_message(timestamp=value) for value in timestamps]
    )
    assert report.total_message_count == len(timestamps)
    assert report.dated_message_count == dated
    assert report.active_days == days
    assert report.average_messages_per_active_day == density
    assert len(report.hourly_counts) == 24
    assert len(report.weekday_counts) == 7
    assert [(p.hour, p.count) for p in report.hourly_counts if p.count] == hours
    assert [(p.weekday, p.count) for p in report.weekday_counts if p.count] == weekdays


def test_user_profile_analyzer_reports_shares_for_multiple_users() -> None:
    messages = (
        _message(sender="Fictional-Alice", text="1234", timestamp=_epoch(hour=8)),
        _message(sender="Fictional-Alice", text="12", timestamp=_epoch(hour=8)),
        _message(sender="Fictional-Alice", text="12", timestamp=_epoch(hour=9)),
        _message(sender="Fictional-Bob", text="123456", timestamp=_epoch(hour=22)),
    )

    report = _analyzers().UserProfileAnalyzer().analyze(messages)

    assert report.total_message_count == 4
    profiles = {profile.speaker: profile for profile in report.profiles}
    assert report.profiles[0].speaker == "Fictional-Alice"
    assert profiles["Fictional-Alice"].message_count == 3
    assert profiles["Fictional-Alice"].message_share_percent == 75.0
    assert profiles["Fictional-Alice"].busiest_hour == 8
    assert profiles["Fictional-Bob"].message_share_percent == 25.0
    assert profiles["Fictional-Bob"].average_length == 6.0


def test_user_profile_exposes_hourly_and_weekday_distributions() -> None:
    messages = (
        _message(timestamp=_epoch(hour=9)),
        _message(timestamp=_epoch(hour=10)),
    )

    profile = _analyzers().UserProfileAnalyzer().analyze(messages).profiles[0]

    assert len(profile.hourly_counts) == 24
    assert sum(entry.count for entry in profile.hourly_counts) == 2
    assert len(profile.weekday_counts) == 7
    assert sum(entry.count for entry in profile.weekday_counts) == 2
    assert isinstance(profile.hourly_counts[0], _models().HourlyActivity)
    assert isinstance(profile.weekday_counts[0], _models().WeekdayActivity)


def test_user_profile_median_length_odd_and_even_independent() -> None:
    messages = (
        _message(sender="Fictional-Alice", text="123"),
        _message(sender="Fictional-Alice", text="12345"),
        _message(sender="Fictional-Alice", text="1234567"),
        _message(sender="Fictional-Bob", text="12"),
        _message(sender="Fictional-Bob", text="1234"),
    )

    report = _analyzers().UserProfileAnalyzer().analyze(messages)
    profiles = {profile.speaker: profile for profile in report.profiles}

    assert profiles["Fictional-Alice"].median_length == 5.0
    assert profiles["Fictional-Bob"].median_length == 3.0
    assert profiles["Fictional-Alice"].average_length == 5.0
    assert profiles["Fictional-Bob"].average_length == 3.0


def test_user_profile_consecutive_runs_aaa_bba() -> None:
    messages = (
        _message(sender="Fictional-Alice", text="1"),
        _message(sender="Fictional-Alice", text="2"),
        _message(sender="Fictional-Alice", text="3"),
        _message(sender="Fictional-Bob", text="4"),
        _message(sender="Fictional-Bob", text="5"),
        _message(sender="Fictional-Alice", text="6"),
    )

    report = _analyzers().UserProfileAnalyzer().analyze(messages)
    profiles = {profile.speaker: profile for profile in report.profiles}
    alice_runs = profiles["Fictional-Alice"].consecutive_runs
    bob_runs = profiles["Fictional-Bob"].consecutive_runs

    assert alice_runs is not None
    assert bob_runs is not None
    assert (alice_runs.run_count, alice_runs.average_run_length) == (2, 2.0)
    assert alice_runs.median_run_length == 2.0
    assert alice_runs.single_message_run_count == 1
    assert alice_runs.multi_message_run_count == 1
    assert (bob_runs.run_count, bob_runs.average_run_length) == (1, 2.0)
    assert bob_runs.median_run_length == 2.0
    assert bob_runs.single_message_run_count == 0
    assert bob_runs.multi_message_run_count == 1


def test_conversation_analyzer_reports_span_and_speakers_per_conversation() -> None:
    start = _epoch(hour=8)
    end = _epoch(hour=10)
    messages = (
        _message(
            conversation_id="fictional-room-1",
            sender="Fictional-Alice",
            timestamp=start,
        ),
        _message(
            conversation_id="fictional-room-1",
            sender="Fictional-Bob",
            timestamp=end,
        ),
        _message(
            conversation_id="fictional-room-2",
            sender="Fictional-Alice",
            timestamp=start,
        ),
    )

    report = _analyzers().ConversationAnalyzer().analyze(messages)

    assert report.conversation_count == 2
    conversations = {
        entry.conversation_id: entry for entry in report.conversations
    }
    room_one = conversations["fictional-room-1"]
    assert room_one.message_count == 2
    assert room_one.speaker_count == 2
    assert room_one.start_timestamp == start
    assert room_one.end_timestamp == end
    assert room_one.duration_seconds == 7200
    assert conversations["fictional-room-2"].duration_seconds == 0


def test_conversation_analyzer_ignores_zero_timestamp_for_span() -> None:
    start = _epoch(hour=9)
    messages = (
        _message(timestamp=0),
        _message(timestamp=start),
    )

    report = _analyzers().ConversationAnalyzer().analyze(messages)

    conversation = report.conversations[0]
    assert conversation.start_timestamp == start
    assert conversation.end_timestamp == start
    assert conversation.duration_seconds == 0
