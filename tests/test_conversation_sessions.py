"""Behavior tests for source-neutral conversation session analysis."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.analysis.conversation_sessions import (  # noqa: E402
    DEFAULT_SESSION_THRESHOLD_SECONDS,
    analyze_conversation_sessions,
)
from qq_chat_analyzer.message import ChatMessage  # noqa: E402


BASE_TIMESTAMP = 1_704_067_200


def _message(
    offset_seconds: int | None,
    *,
    sender: str = "Fictional Alice",
    sender_id: str | None = "fictional-alice-id",
    conversation_type: str = "private",
    is_self: bool | None = True,
) -> ChatMessage:
    timestamp: int | str = (
        BASE_TIMESTAMP + offset_seconds
        if offset_seconds is not None
        else "invalid-time"
    )
    return ChatMessage(
        timestamp=timestamp,
        sender=sender,
        sender_id=sender_id,
        message_type="text",
        text="fictional message",
        platform="fictional",
        conversation_id="fictional-conversation",
        conversation_type=conversation_type,
        is_self=is_self,
    )


def test_gap_over_thirty_minutes_starts_new_session() -> None:
    report = analyze_conversation_sessions(
        (_message(0), _message(30 * 60 + 1))
    )

    assert report.session_count == 2
    assert tuple(item.message_count for item in report.sessions) == (1, 1)


def test_group_session_repr_hides_initiator_without_changing_statistics():
    from dataclasses import asdict

    report = analyze_conversation_sessions((
        _message(0, sender="fictional-private-name", sender_id="fictional-private-key",
                 conversation_type="group"),
    ))
    assert "fictional-private" not in repr(report)
    assert asdict(report)["sessions"][0]["initiator"] == "fictional-private-key"
    assert report.sessions[0].initiator_sender_key == "fictional-private-key"
    assert report.group_stats.top_initiator_sender_key == "fictional-private-key"
    assert report.group_stats.top_initiated_count == 1


def test_gap_exactly_thirty_minutes_stays_in_same_session() -> None:
    report = analyze_conversation_sessions((_message(0), _message(30 * 60)))

    assert report.session_count == 1
    assert report.sessions[0].duration_seconds == 30 * 60


def test_private_sessions_report_self_peer_and_unknown_initiators() -> None:
    report = analyze_conversation_sessions(
        (
            _message(0, is_self=True),
            _message(31 * 60, is_self=False),
            _message(62 * 60, is_self=None),
        )
    )

    assert tuple(item.initiator for item in report.sessions) == (
        "self",
        "peer",
        "unknown",
    )
    stats = report.private_stats
    assert stats is not None
    assert stats.self_initiated_count == 1
    assert stats.peer_initiated_count == 1
    assert stats.unknown_initiated_count == 1
    assert stats.self_to_peer_ratio == 1.0
    assert stats.self_initiated_share == 1 / 3
    assert stats.peer_initiated_share == 1 / 3
    assert stats.unknown_initiated_share == 1 / 3


def test_private_report_calculates_duration_and_message_aggregates() -> None:
    report = analyze_conversation_sessions(
        (
            _message(0),
            _message(10 * 60),
            _message(60 * 60, is_self=False),
            _message(80 * 60, is_self=True),
            _message(90 * 60, is_self=False),
        )
    )

    assert report.session_count == 2
    assert report.average_duration_seconds == 20 * 60
    assert report.median_duration_seconds == 20 * 60
    assert report.longest_duration_seconds == 30 * 60
    assert report.average_message_count == 2.5
    assert report.private_stats is not None
    assert report.private_stats.self_initiated_count == 1
    assert report.private_stats.peer_initiated_count == 1


def test_group_session_uses_stable_sender_identity_as_initiator() -> None:
    report = analyze_conversation_sessions(
        (
            _message(
                0,
                sender="Old Fictional Name",
                sender_id="stable-fictional-id",
                conversation_type="group",
                is_self=None,
            ),
            _message(
                10,
                sender="New Fictional Name",
                sender_id="stable-fictional-id",
                conversation_type="group",
                is_self=None,
            ),
        )
    )

    assert report.conversation_type == "group"
    assert report.sessions[0].initiator == "stable-fictional-id"
    assert report.sessions[0].initiator_sender_key == "stable-fictional-id"
    assert report.private_stats is None


def test_group_report_aggregates_self_and_top_initiator() -> None:
    report = analyze_conversation_sessions(
        (
            _message(
                0,
                sender="Fictional Alice",
                sender_id="fictional-alice-id",
                conversation_type="group",
                is_self=True,
            ),
            _message(
                31 * 60,
                sender="Fictional Alice Renamed",
                sender_id="fictional-alice-id",
                conversation_type="group",
                is_self=True,
            ),
            _message(
                62 * 60,
                sender="Fictional Bob",
                sender_id="fictional-bob-id",
                conversation_type="group",
                is_self=False,
            ),
        )
    )

    stats = report.group_stats
    assert stats is not None
    assert stats.self_initiated_count == 2
    assert stats.self_initiated_share == 2 / 3
    assert stats.top_initiator_sender_key == "fictional-alice-id"
    assert stats.top_initiated_count == 2
    assert stats.top_initiated_share == 2 / 3


def test_group_self_initiator_stats_require_reliable_identity() -> None:
    report = analyze_conversation_sessions(
        (
            _message(0, conversation_type="group", is_self=None),
            _message(31 * 60, conversation_type="group", is_self=None),
        )
    )

    stats = report.group_stats
    assert stats is not None
    assert stats.self_initiated_count is None
    assert stats.self_initiated_share is None
# === Group conversation session records ===


# === Private conversation session v1 ===


def _private_pair(offset_seconds, *, self_message: bool) -> ChatMessage:
    """One private message from the self/peer side with a distinct sender key."""
    if self_message:
        return _message(
            offset_seconds,
            is_self=True,
            sender="Fictional Self",
            sender_id="fictional-self-id",
        )
    return _message(
        offset_seconds,
        is_self=False,
        sender="Fictional Peer",
        sender_id="fictional-peer-id",
    )


def test_private_reply_timing_medians_for_both_directions() -> None:
    """Reply latency is the initiator's first valid message to the other side."""
    report = analyze_conversation_sessions(
        (
            _private_pair(0, self_message=True),
            _private_pair(60, self_message=False),
            _private_pair(120, self_message=True),
            _private_pair(2000, self_message=False),
            _private_pair(2045, self_message=True),
            _private_pair(2090, self_message=False),
        )
    )

    assert report.conversation_type == "private"
    assert report.private_reply_timing is not None
    assert report.private_reply_timing.self_to_peer_median_seconds == 60.0
    assert report.private_reply_timing.peer_to_self_median_seconds == 45.0


def test_private_session_self_peer_message_counts() -> None:
    """Private sessions carry per-side counts, or None when identity is unreliable."""
    report = analyze_conversation_sessions(
        (
            _private_pair(0, self_message=True),
            _private_pair(10, self_message=True),
            _private_pair(20, self_message=False),
            _private_pair(30, self_message=False),
            _private_pair(40, self_message=True),
        )
    )
    session = report.sessions[0]
    assert session.self_message_count == 3
    assert session.peer_message_count == 2

    unreliable = analyze_conversation_sessions(
        (
            _private_pair(0, self_message=True),
            _message(10, is_self=None, sender_id="fictional-unknown-id"),
            _private_pair(20, self_message=False),
        )
    )
    assert unreliable.sessions[0].self_message_count is None
    assert unreliable.sessions[0].peer_message_count is None
