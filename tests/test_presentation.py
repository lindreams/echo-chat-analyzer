"""Behavior tests for the analysis presentation layer."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _presentation():
    return importlib.import_module("qq_chat_analyzer.presentation")


def _analysis_models():
    return importlib.import_module("qq_chat_analyzer.analysis.models")


def _hourly(counts: dict[int, int]):
    models = _analysis_models()
    return tuple(
        models.HourlyActivity(hour=hour, count=counts.get(hour, 0))
        for hour in range(24)
    )


def _weekday(counts: dict[int, int]):
    models = _analysis_models()
    return tuple(
        models.WeekdayActivity(weekday=weekday, count=counts.get(weekday, 0))
        for weekday in range(7)
    )


def _activity_report(
    *,
    total: int = 3,
    dated: int = 3,
    busiest_hour: int | None = 9,
    busiest_weekday: int | None = 0,
):
    models = _analysis_models()
    return models.ActivityReport(
        total_message_count=total,
        dated_message_count=dated,
        hourly_counts=_hourly({9: 2, 21: 1}),
        weekday_counts=_weekday({0: 3}),
        busiest_hour=busiest_hour,
        busiest_weekday=busiest_weekday,
    )


def _message_length_report():
    models = _analysis_models()
    return models.MessageLengthReport(
        message_count=3,
        average_length=6.0,
        max_length=10,
        buckets=(
            models.LengthBucket(lower_bound=0, upper_bound=10, count=2),
            models.LengthBucket(lower_bound=10, upper_bound=None, count=1),
        ),
        speaker_lengths=(
            models.SpeakerLength(
                speaker="Fictional-Alice",
                message_count=2,
                average_length=4.0,
                max_length=5,
            ),
        ),
    )


def _user_profile_report(profile_count: int = 2):
    models = _analysis_models()
    profiles = (
        models.UserProfile(
            speaker="Fictional-Alice",
            message_count=3,
            message_share_percent=75.0,
            average_length=4.0,
            max_length=5,
            busiest_hour=9,
            busiest_weekday=0,
            top_words=(
                models.ProfileWord(word="deck", count=2),
                models.ProfileWord(word="talk", count=1),
            ),
        ),
        models.UserProfile(
            speaker="Fictional-Bob",
            message_count=1,
            message_share_percent=25.0,
            average_length=6.0,
            max_length=6,
            busiest_hour=None,
            busiest_weekday=None,
        ),
    )[:profile_count]
    return models.UserProfileReport(
        total_message_count=sum(profile.message_count for profile in profiles),
        speaker_count=len(profiles),
        profiles=profiles,
    )


def _conversation_report(conversation_count: int = 2):
    models = _analysis_models()
    conversations = (
        models.ConversationSummary(
            conversation_id="fictional-room-1",
            message_count=2,
            speaker_count=2,
            start_timestamp=1704099600,
            end_timestamp=1704106800,
            duration_seconds=7200,
        ),
        models.ConversationSummary(
            conversation_id=None,
            message_count=1,
            speaker_count=1,
            duration_seconds=None,
        ),
    )[:conversation_count]
    return models.ConversationReport(
        conversation_count=len(conversations),
        conversations=conversations,
    )


def _full_reports():
    models = _analysis_models()
    return models.AnalysisReports(
        activity=_activity_report(),
        message_length=_message_length_report(),
        user_profiles=_user_profile_report(),
        conversations=_conversation_report(),
    )


def _profile_report(profile):
    models = _analysis_models()
    return models.AnalysisReports(
        user_profiles=models.UserProfileReport(
            total_message_count=profile.message_count,
            speaker_count=1,
            profiles=(profile,),
        )
    )


def _chart_by_key(view, key: str):
    for chart in view.charts:
        if chart.key == key:
            return chart
    raise AssertionError(f"chart {key} not found")


def _metric_by_key(view, key: str):
    for metric in view.summary_metrics:
        if metric.key == key:
            return metric
    raise AssertionError(f"metric {key} not found")


def test_echo_report_builder_reuses_reports_and_highlights_explicit_viewer() -> None:
    presentation = _presentation()

    view = presentation.EchoReportBuilder().build(
        _full_reports(),
        viewer_speaker_key="Fictional-Bob",
    )

    assert view.has_data is True
    assert view.total_message_count == 3
    assert view.participant_count == 2
    assert len(view.hourly_activity) == 24
    assert len(view.weekday_activity) == 7
    assert [card.speaker_key for card in view.members] == [
        "Fictional-Alice",
        "Fictional-Bob",
    ]
    alice, bob = view.members
    assert alice.is_viewer is False
    assert bob.is_viewer is True


def test_echo_report_builder_never_guesses_viewer_identity() -> None:
    presentation = _presentation()

    view = presentation.build_echo_report_view(_full_reports())

    assert all(not member.is_viewer for member in view.members)


def test_private_language_profile_reuses_each_user_top_words() -> None:
    presentation = _presentation()

    view = presentation.build_echo_report_view(
        _full_reports(),
        conversation_kind="private",
        viewer_speaker_key="Fictional-Bob",
    )

    assert view.language_profile is not None
    assert view.language_profile.mode == "private_common"
    assert view.language_profile.available is True
    voices = {member.speaker_key: member for member in view.language_profile.members}
    assert voices["Fictional-Alice"].heading == "TA 常说"
    assert voices["Fictional-Alice"].primary_words == ("deck",)
    assert voices["Fictional-Bob"].heading == "你常说"
    assert voices["Fictional-Bob"].primary_words == ()
    assert all(member.context_words == () for member in voices.values())


def test_private_language_profile_does_not_guess_you_or_ta_without_viewer() -> None:
    presentation = _presentation()

    view = presentation.build_echo_report_view(
        _full_reports(),
        conversation_kind="private",
    )

    assert view.language_profile is not None
    headings = [member.heading for member in view.language_profile.members]
    assert headings == ["Fictional-Alice 常说", "Fictional-Bob 常说"]
    assert "你常说" not in headings
    assert "TA 常说" not in headings


def test_private_language_profile_does_not_guess_when_viewer_key_is_unmatched() -> None:
    presentation = _presentation()

    view = presentation.build_echo_report_view(
        _full_reports(),
        conversation_kind="private",
        viewer_speaker_key="missing-stable-key",
    )

    assert view.language_profile is not None
    assert [member.heading for member in view.language_profile.members] == [
        "Fictional-Alice 常说",
        "Fictional-Bob 常说",
    ]


def test_echo_member_builder_carries_stable_identity_skeleton() -> None:
    presentation = _presentation()
    models = _analysis_models()
    message_module = importlib.import_module("qq_chat_analyzer.message")
    analyzer_module = importlib.import_module(
        "qq_chat_analyzer.analysis.analyzers.user_profile_analyzer"
    )
    report = analyzer_module.UserProfileAnalyzer().analyze(
        [
            message_module.ChatMessage(
                timestamp=1704099600,
                sender="Alice",
                message_type="text",
                text="hello",
                sender_id="10001",
            )
        ]
    )

    view = presentation.build_echo_report_view(
        models.AnalysisReports(user_profiles=report)
    )
    member = view.members[0]

    assert member.speaker_key == "10001"
    assert member.primary_name == "Alice"
    assert member.display_name == "Alice"
    assert member.secondary_name is None
    assert member.remark is None
    assert member.contextual_name is None
    assert member.is_viewer is False


def test_echo_member_resolves_group_remark_and_group_card() -> None:
    presentation = _presentation()
    models = _analysis_models()
    profile = models.UserProfile(
        speaker="Alice",
        speaker_key="10001",
        display_name="Alice",
        message_count=1,
        message_share_percent=100.0,
        average_length=3.0,
        max_length=3,
        remark="老王",
        nickname="Nickname",
        contextual_name="达拉崩吧",
    )

    member = presentation.build_echo_report_view(
        _profile_report(profile),
        conversation_kind="group",
    ).members[0]

    assert member.speaker_key == "10001"
    assert member.primary_name == "老王"
    assert member.secondary_name == "达拉崩吧"
    assert member.remark == "老王"
    assert member.contextual_name == "达拉崩吧"


def test_echo_member_resolves_private_remark_and_nickname() -> None:
    presentation = _presentation()
    models = _analysis_models()
    profile = models.UserProfile(
        speaker="Alice",
        speaker_key="10001",
        display_name="Alice",
        message_count=1,
        message_share_percent=100.0,
        average_length=3.0,
        max_length=3,
        remark="张三",
        nickname="ZhangSan",
    )

    member = presentation.build_echo_report_view(
        _profile_report(profile),
        conversation_kind="private",
    ).members[0]

    assert member.primary_name == "张三"
    assert member.secondary_name == "ZhangSan"
    assert member.contextual_name == "ZhangSan"


def test_echo_member_never_uses_internal_id_when_name_exists() -> None:
    presentation = _presentation()
    models = _analysis_models()
    profile = models.UserProfile(
        speaker="123456789",
        speaker_key="123456789",
        display_name="123456789",
        message_count=1,
        message_share_percent=100.0,
        average_length=3.0,
        max_length=3,
        remark="老王",
    )

    member = presentation.build_echo_report_view(
        _profile_report(profile)
    ).members[0]

    assert member.primary_name == "老王"
    assert member.speaker_key == "123456789"


def test_build_dashboard_view_reports_single_user() -> None:
    presentation = _presentation()
    models = _analysis_models()
    reports = models.AnalysisReports(
        activity=_activity_report(),
        user_profiles=_user_profile_report(profile_count=1),
    )

    view = presentation.build_dashboard_view(reports)

    assert len(view.user_cards) == 1
    card = view.user_cards[0]
    assert card.rank == 1
    assert card.sender == "Fictional-Alice"
    assert card.message_count == 3
    assert card.percentage == 75.0
    assert card.percentage_display == "75.0%"
    assert card.average_length_display == "4.0 \u5b57"
    assert card.top_words == ("deck", "talk")
    assert _metric_by_key(view, "speaker_count").value == "1"


def test_activity_report_converts_into_hourly_and_weekday_charts() -> None:
    presentation = _presentation()

    view = presentation.build_dashboard_view(_full_reports())
    hourly = _chart_by_key(view, "activity_hourly")
    weekday = _chart_by_key(view, "activity_weekday")

    assert hourly.kind is presentation.ChartKind.LINE
    assert len(hourly.series[0].points) == 24
    assert hourly.series[0].points[9].label == "09:00-09:59"
    assert hourly.series[0].points[9].value == 2.0
    assert weekday.kind is presentation.ChartKind.BAR
    assert len(weekday.series[0].points) == 7
    assert weekday.series[0].points[0].label == "\u5468\u4e00"
    assert weekday.series[0].points[0].value == 3.0
