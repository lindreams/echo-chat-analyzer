"""Fictional regressions for private QQ records without participant identity."""

from __future__ import annotations

import base64
import json

import pytest

from qq_db_test_data import length_delimited_field, qq_db_payload, qq_db_record, scalar_field
from qq_chat_analyzer.analysis.analyzers.user_profile_analyzer import UserProfileAnalyzer
from qq_chat_analyzer.application import AnalysisApplicationService, AnalysisRequestDTO
from qq_chat_analyzer.application.import_request import ImportRequest
from qq_chat_analyzer.application.import_service import ImportService
from qq_chat_analyzer.message import ChatMessage


def _analyze(tmp_path, *, sender=0, session_type="private", unknown_text=False, extra_peer=False,
             self_uin="100000001"):
    records = [
        qq_db_record(
            "unassignedword unassignedword reserve" if unknown_text else "",
            sender_id=sender, nickname="Unreliable fictional label",
            message_id="unknown", timestamp=1760000000,
            faces=((14, "/fictional-face"), (66, "/fictional-other-face")),
        ),
        *[
            qq_db_record(
                text, sender_id=identity, nickname=name,
                message_id=f"known-{index}", timestamp=1760000060 + index * 60,
            )
            for index, (identity, name, text) in enumerate([
                ("100000001", "Fictional Alice", "orchard meadow garden"),
                ("100000002", "Fictional Bob", "orchard telescope garden"),
                ("100000001", "Fictional Alice", "orchard harvest garden"),
                ("100000002", "Fictional Bob", "orchard galaxy garden"),
            ])
        ],
    ]
    if not unknown_text:
        # Zero-value nontext records need not be system messages or expressions.
        blob = base64.b64decode(records[0]["message_blob"])
        blob += length_delimited_field(40800, scalar_field(45002, 999))
        records[0]["message_blob"] = base64.b64encode(blob).decode("ascii")
    if extra_peer:
        records.append(qq_db_record(
            "third valid speaker", sender_id="100000003", nickname="Fictional Carol",
            message_id="third", timestamp=1760000400,
        ))
    payload = qq_db_payload(records, session_type=session_type, self_uin=self_uin)
    path = tmp_path / "fictional.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    stopwords = tmp_path / "fictional-stopwords.txt"
    stopwords.write_text("", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    imported = ImportService().execute(ImportRequest(input_path=path, platform="qq"))
    result = AnalysisApplicationService().execute(AnalysisRequestDTO(
        input_path=path, output_directory=output, stopwords_path=stopwords,
    ))
    return imported, result


@pytest.mark.parametrize("sender", [0, "0", " 0 "])
def test_zero_private_sender_preserves_message_without_creating_participant(tmp_path, sender):
    imported, result = _analyze(tmp_path, sender=sender)
    assert len(imported.messages) == len(imported.rich_messages) == 5
    unknown = imported.messages[0]
    assert unknown.sender_id is None
    assert unknown.sender == ""
    assert unknown.is_self is None
    assert not unknown.is_system
    assert len(imported.rich_messages[0].contents) == 3
    assert result.reports.activity.total_message_count == 5
    profiles = result.reports.user_profiles
    assert profiles.total_message_count == 5
    assert profiles.speaker_count == 2
    assert {p.speaker_key: p.message_count for p in profiles.profiles} == {
        "100000001": 2, "100000002": 2,
    }
    conversation = result.reports.conversations.conversations[0]
    assert conversation.message_count == 5
    assert conversation.speaker_count == 2
    sessions = result.reports.conversation_sessions.sessions
    assert len(sessions) == 1
    assert sessions[0].message_count == 5
    assert sessions[0].participant_count == 2
    assert sessions[0].initiator == "unknown"
    assert sessions[0].initiator_sender_key is None
    expression = result.reports.expression
    assert expression.expression_occurrence_count == 2
    assert len(expression.top_combinations) == 1
    assert expression.members == ()
    assert expression.top_combinations[0].member_counts == ()
    view = result.echo_report_view
    assert view.total_message_count == 5
    assert view.participant_count == 2
    assert sum(m.is_viewer for m in view.members) == 1
    assert view.language_profile.available
    assert len(view.language_profile.members) == 2
    assert all("orchard" in m.primary_words for m in view.language_profile.members)


def test_unknown_private_text_is_global_only_and_not_attributed_to_either_side(tmp_path):
    imported, result = _analyze(tmp_path, unknown_text=True)
    assert imported.messages[0].text == "unassignedword unassignedword reserve"
    assert result.valid_text_count == 5
    assert any(w.word == "unassignedword" and w.count == 2 for w in result.top_words)
    assert result.reports.user_profiles.speaker_count == 2
    assert all(
        w.word != "unassignedword"
        for p in result.reports.user_profiles.profiles for w in p.top_words
    )
    assert result.echo_report_view.language_profile.available
    assert all(
        {w.speaker_a, w.speaker_b} == {"100000001", "100000002"}
        for w in result.reports.private_language.shared_words
    )


def test_group_zero_sender_stays_unknown_without_member_attribution(tmp_path):
    imported, result = _analyze(tmp_path, session_type="group")
    assert len(imported.messages) == len(imported.rich_messages) == 5
    assert imported.messages[0].sender_id is None
    assert imported.messages[0].sender == ""
    assert imported.messages[0].is_self is None
    assert not imported.messages[0].is_system
    assert result.reports.activity.total_message_count == 5
    profiles = result.reports.user_profiles
    assert profiles.total_message_count == 5 and profiles.speaker_count == 2
    assert {profile.speaker_key: profile.message_count for profile in profiles.profiles} == {
        "100000001": 2, "100000002": 2,
    }
    conversation = result.reports.conversations.conversations[0]
    assert conversation.message_count == 5 and conversation.speaker_count == 2
    session = result.reports.conversation_sessions.sessions[0]
    assert session.message_count == 5 and session.participant_count == 2
    assert result.reports.expression.expression_occurrence_count == 2
    assert result.reports.expression.members == ()


def test_three_valid_private_senders_remain_unavailable_instead_of_selecting_top_two(tmp_path):
    _, result = _analyze(tmp_path, extra_peer=True)
    assert result.reports.activity.total_message_count == 6
    assert result.reports.user_profiles.speaker_count == 3
    assert result.echo_report_view.participant_count == 3
    assert not result.echo_report_view.language_profile.available


def test_missing_self_does_not_hide_identified_private_participants(tmp_path):
    imported, result = _analyze(tmp_path, self_uin=None)
    assert all(m.is_self is None for m in imported.messages)
    assert result.reports.user_profiles.speaker_count == 2
    assert result.echo_report_view.language_profile.available
    assert not any(m.is_viewer for m in result.echo_report_view.members)


def test_named_private_fallback_is_preserved_and_unknown_sender_breaks_runs():
    # A missing source ID alone does not invalidate a usable legacy sender name.
    messages = [
        ChatMessage(100, "Fictional Alice", "text", "orchard", conversation_type="private"),
        ChatMessage(101, "", "image", "", conversation_type="private"),
        ChatMessage(102, "Fictional Alice", "text", "meadow", conversation_type="private"),
        ChatMessage(103, "Fictional Bob", "text", "garden", conversation_type="private"),
    ]
    report = UserProfileAnalyzer().analyze(messages)
    assert report.total_message_count == 4
    assert report.speaker_count == 2
    alice = next(p for p in report.profiles if p.speaker == "Fictional Alice")
    assert alice.message_count == 2
    assert alice.consecutive_runs.run_count == 2
    assert alice.consecutive_runs.average_run_length == 1
