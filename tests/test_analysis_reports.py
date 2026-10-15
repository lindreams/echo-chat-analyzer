"""Behavior tests for the Analysis Core v2 report analyzers."""

from __future__ import annotations

import dataclasses
import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _models():
    return importlib.import_module("qq_chat_analyzer.analysis.models")


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
    assert report.busiest_hour == 20


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


def test_message_length_analyzer_reports_global_and_speaker_stats() -> None:
    messages = (
        _message(sender="Fictional-Alice", text="12345"),
        _message(sender="Fictional-Alice", text="123"),
        _message(sender="Fictional-Bob", text="1234567890"),
    )

    report = _analyzers().MessageLengthAnalyzer().analyze(messages)

    assert report.message_count == 3
    assert report.average_length == 6.0
    assert report.max_length == 10
    by_speaker = {
        entry.speaker: entry for entry in report.speaker_lengths
    }
    assert by_speaker["Fictional-Alice"].average_length == 4.0
    assert by_speaker["Fictional-Alice"].max_length == 5
    assert by_speaker["Fictional-Bob"].average_length == 10.0
    assert sum(bucket.count for bucket in report.buckets) == 3


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
