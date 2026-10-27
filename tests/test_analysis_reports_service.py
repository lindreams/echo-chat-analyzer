"""Integration tests for extended reports on the analysis service."""

from __future__ import annotations

import importlib
import json
from qq_db_test_data import qq_db_payload, qq_db_record
from chat_input_test_data import detailed_payload
import re
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _application_module():
    return importlib.import_module("qq_chat_analyzer.application")


def _write_fictional_chat(path: Path, messages: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(detailed_payload(messages), ensure_ascii=False),
        encoding="utf-8",
    )


def _raw_message(
    timestamp: int,
    nickname: str,
    text: str,
    message_type: str = "text",
) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "sender": {"nickname": nickname},
        "type": message_type,
        "content": {"text": text},
    }


def _write_wechat_db_sticker_export(path: Path) -> None:
    payload = {
        "source": "wechat-db",
        "conversation": {
            "username": "wxid_fictional_room@chatroom",
            "session_type": "group",
        },
        "messages": [
            {
                "local_id": 1,
                "server_id": 9001,
                "local_type": 47,
                "create_time": 1704099600,
                "message_content": '<msg><emoji md5="stickeronly"/></msg>',
                "user_name": "wxid_fictional_sender",
            },
            {
                "local_id": 2,
                "server_id": 9002,
                "local_type": 47,
                "create_time": 1704099660,
                "message_content": '<msg><emoji md5="stickeronly"/></msg>',
                "user_name": "wxid_fictional_sender",
            },
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_private_qq_db_expression_export(path: Path) -> None:
    records = [qq_db_record(sender_id=str(index), nickname=name,
                           message_id=f"fictional-private-{index}", timestamp=1704099600 + index * 60,
                           stickers=(("market-facepalm", "Facepalm"),))
               for index, name in enumerate(("Fictional Alice", "Fictional Bob"), start=1)]
    path.write_text(json.dumps(qq_db_payload(records, session_type="private"), ensure_ascii=False), encoding="utf-8")


def _request(application, tmp_path: Path, input_path: Path):
    stopwords_path = tmp_path / "private-stopwords.txt"
    stopwords_path.write_text("", encoding="utf-8")
    return application.AnalysisRequestDTO(
        input_path=input_path,
        output_directory=tmp_path / "private-output",
        stopwords_path=stopwords_path,
        font_path=None,
        top=5,
    )


@pytest.mark.parametrize("source", ["qq", "wechat"])
def test_language_originals_reach_export_with_exact_tokens_and_filtered_scope(tmp_path, source, caplog):
    from dataclasses import replace
    from datetime import date
    from qq_chat_analyzer.application.scope_filter import AnalysisScope

    application = _application_module()
    path = tmp_path / "fictional-originals.json"
    (tmp_path / "private-output").mkdir()
    texts = [
        "orchard outside_scope_secret", "orchard orchard fresh meadow",
        "orchard today garden", "限时礼包！复制口令【星空福利AbCdEf】参与活动。 orchard filtered_secret",
        "an orchard picnic tonight", "orchard orchard weekend", "pineapple is a different word",
        "orchard今天终于等到放假啦" * 5,
    ]
    if source == "qq":
        records = [qq_db_record(text, sender_id="100000001" if i % 2 else "100000002",
            nickname="Fictional A" if i % 2 else "Fictional B", message_id="same-id",
            timestamp=1704099600 + i * 60 if i else 1704013200) for i, text in enumerate(texts)]
        payload = qq_db_payload(records, session_type="private", self_uin="100000001")
    else:
        payload = {"source": "wechat-db", "conversation": {
            "username": "wxid_fictional_peer", "session_type": "private", "self_username": "wxid_fictional_self",
        }, "messages": [{"local_id": i, "server_id": 9000, "local_type": 1,
            "create_time": 1704099600 + i * 60 if i else 1704013200,
            "message_content": text, "user_name": "wxid_fictional_self" if i % 2 else "wxid_fictional_peer",
            "sender_name": "Fictional A" if i % 2 else "Fictional B",
        } for i, text in enumerate(texts)]}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    request = replace(_request(application, tmp_path, path),
        scope=AnalysisScope.custom(date(2024, 1, 1), date(2024, 1, 1)))
    result = application.AnalysisApplicationService().execute(request)
    assert result.status is application.AnalysisStatus.COMPLETED
    exported = json.loads((tmp_path / "private-output" / "echo-report.json").read_text(encoding="utf-8"))
    assert "language_sources" in exported
    sources = exported["language_sources"]
    terms = [t for t in sources["terms"] if t["word"] == "orchard"]
    combined = next(t for t in terms if t["member_index"] is None)
    assert combined["occurrence_count"] == 6
    assert len(combined["message_refs"]) == 4
    by_ref = {m["ref"]: m for m in sources["messages"]}
    assert [by_ref[ref]["text"] for ref in combined["message_refs"]] == [texts[i] for i in (1, 2, 4, 5)]
    assert not by_ref[combined["message_refs"][1]]["after_refs"]
    serialized = json.dumps(sources, ensure_ascii=False)
    assert "outside_scope_secret" not in serialized and "filtered_secret" not in serialized
    assert "今天终于等到放假啦" not in serialized
    assert "wxid_fictional" not in serialized and "same-id" not in serialized
    html = (tmp_path / "private-output" / "echo-report.html").read_text(encoding="utf-8")
    assert "orchard orchard fresh meadow" in html
    assert "outside_scope_secret" not in html and "filtered_secret" not in html
    assert "今天终于等到放假啦" not in html
    assert not any(text in caplog.text for text in texts)


def test_member_first_seen_order_survives_volume_sorting_and_report_projection():
    from qq_chat_analyzer.message import ChatMessage
    from qq_chat_analyzer.application.analysis_service import _build_reports
    from qq_chat_analyzer.presentation import build_echo_report_view, echo_report_to_dict

    messages = [ChatMessage(timestamp=1700000000 + index, sender=sender,
        sender_id=sender, message_type="text", text="虚构的普通发言")
        for index, sender in enumerate(("fictional-a", "fictional-c", "fictional-b",
                                        "fictional-b", "fictional-a", "fictional-b"))]
    payload = echo_report_to_dict(build_echo_report_view(_build_reports(messages, [])))
    assert [member["speaker_key"] for member in payload["members"]] == [
        "fictional-b", "fictional-a", "fictional-c"]
    assert {member["speaker_key"]: member.get("first_seen_order")
            for member in payload["members"]} == {
        "fictional-a": 0, "fictional-c": 1, "fictional-b": 2}


def test_private_stickers_reach_actual_json_and_html_from_filtered_rich_chain(tmp_path):
    application = _application_module()
    path = tmp_path / "fictional-stickers.json"
    records = [
        qq_db_record(sender_id=sender, message_id=f"fiction-{index}",
                     timestamp=1760000000 + index * 60,
                     stickers=tuple((key, "untrusted-label") for key in keys))
        for index, (sender, keys) in enumerate([
            ("100000001", ("shared", "shared", "mine")),
            ("100000001", ("mine",)), ("100000001", ("once",)),
            ("100000002", ("shared", "theirs")),
            ("100000002", ("theirs",)),
        ])
    ]
    path.write_text(json.dumps(qq_db_payload(records, session_type="private", self_uin="100000001")), encoding="utf-8")
    result = application.AnalysisApplicationService().execute(_request(application, tmp_path, path))
    payload = json.loads((tmp_path / "private-output/echo-report.json").read_text(encoding="utf-8"))
    chapter = payload["stickers"]
    assert (chapter["total_send_count"], chapter["unique_material_count"]) == (8, 4)
    assert [(m["send_count"], m["message_count"]) for m in chapter["members"]] == [(5, 3), (3, 2)]
    assert [m["per_hundred_messages"] for m in chapter["members"]] == pytest.approx([500 / 3, 150])
    assert [[x["count"] for x in m["top_materials"]] for m in chapter["members"]] == [[2, 2, 1], [2, 1]]
    assert chapter["shared_material_count"] == 1 and chapter["shared_materials"] == []
    assert [m["exclusive_material_count"] for m in chapter["members"]] == [2, 1]
    assert len(chapter["assets"]) == 4
    assert all(a["status"] == "unsupported" and not a["data_uri"] for a in chapter["assets"].values())
    assert result.reports.stickers[0].total_send_count == 8
    source = (tmp_path / "private-output/echo-report.html").read_text(encoding="utf-8")
    match = re.search(r"window\.ECHO_DATA = (\{.*?\});", source, re.S)
    assert json.loads(match.group(1))["stickers"] == chapter
    assert "untrusted-label" not in json.dumps(chapter)


@pytest.mark.parametrize("kind", ["private", "group"])
def test_sticker_complete_rankings_and_signatures_reach_exported_artifacts(tmp_path, kind):
    from datetime import datetime, timedelta, timezone
    application = _application_module()
    records = []
    dates = ("2024-12-29", "2025-01-05", "2025-01-12", "2025-02-02")
    # Identical private boards are legitimate. A third member changes only group boards.
    for member in ("100000001", "100000002"):
        for index in range(12):
            for occurrence in range(12 - index):
                day = dates[occurrence % 4] if index == 3 else dates[0]
                records.append(qq_db_record(sender_id=member, message_id=f"fiction-{len(records)}",
                    timestamp=int(datetime.fromisoformat(day).replace(tzinfo=timezone(timedelta(hours=8))).timestamp()),
                    stickers=((f"material-{index:02d}", "fictional"),)))
    if kind == "group":
        records.append(qq_db_record(sender_id="100000003", message_id="solo",
                                    stickers=tuple(("solo", "fictional") for _ in range(50))))
        records.append(qq_db_record(sender_id="0", message_id="unknown",
                                    stickers=tuple(("material-00", "fictional") for _ in range(30))))
    path = tmp_path / "fictional.json"
    path.write_text(json.dumps(qq_db_payload(records, session_type=kind, self_uin="100000001")), encoding="utf-8")
    result = application.AnalysisApplicationService().execute(_request(application, tmp_path, path))
    raw, = result.reports.stickers
    chapter = json.loads((tmp_path / "private-output/echo-report.json").read_text(encoding="utf-8"))["stickers"]
    assert chapter["available"] and chapter["shared_material_count"] == 12
    assert [x["count"] for x in chapter["shared_materials"]] == (list(range(24, 4, -2)) if kind == "group" else [])
    mine, peer = chapter["members"][:2]
    limit = 10 if kind == "group" else 5
    assert [x["count"] for x in mine["top_materials"]] == list(range(12, 12-limit, -1))
    assert mine["top_materials"] == peer["top_materials"]
    assert mine["signature"]["count"] == 9  # Rank four, not the single-day Top 1.
    assert mine["signature"]["signature"]["week_count"] == 4
    assert [x["count"] for x in mine["top_materials"]] == [n for _, n in raw.ranking("100000001")][:limit]
    assert len(raw.ranking("100000001")) == len(raw.shared_ranking()) == 12
    if kind == "group":
        assert [x["count"] for x in chapter["total_top_materials"][:2]] == [54, 50]
        assert chapter["total_top_materials"][0]["unknown_sender_count"] == 30
        assert chapter["total_top_materials"][0]["reliable_member_count"] == 2
        assert chapter["unattributed_send_count"] == 30
        solo = chapter["members"][2]
        assert (solo["send_count"], solo["message_count"], solo["per_hundred_messages"]) == (50, 1, 5000)
        assert solo["signature"] is None
    else:
        assert chapter["shared_materials"] == []  # Complete shared statistics remain in raw.
    source = (tmp_path / "private-output/echo-report.html").read_text(encoding="utf-8")
    embedded = json.loads(re.search(r"window\.ECHO_DATA = (\{.*?\});", source, re.S).group(1))
    assert embedded["stickers"] == chapter


@pytest.mark.parametrize("legacy_outputs", [False, True])
def test_analysis_logs_each_timing_stage_without_private_content(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
    legacy_outputs: bool,
) -> None:
    application = _application_module()
    input_path = tmp_path / "fictional-chat.json"
    (tmp_path / "private-output").mkdir()
    _write_fictional_chat(input_path, [
        _raw_message(1704099600, "Fictional-Alice", "Python 数据分析 很有趣"),
        _raw_message(1704099500, "Fictional-Bob", "fictional long text " * 10),
        _raw_message(1704099660, "Fictional-Bob", "Python 项目 讨论"),
        _raw_message(1704099720, "Fictional-Carol", "Python 项目 讨论 很好"),
    ])
    caplog.set_level("INFO")

    result = application.AnalysisApplicationService(
        legacy_word_artifacts=(lambda **kwargs: ()) if legacy_outputs else None,
    ).execute(
        _request(application, tmp_path, input_path)
    )

    assert result.status is application.AnalysisStatus.COMPLETED
    timing_lines = [
        record.message for record in caplog.records
        if record.message.startswith("[analysis-timing]")
    ]
    expected = {
        "import", "scope_filter", "smart_profile", "message_quality_filter",
        "text_analysis", "ExpressionAnalyzer.preflight", "word_ranking", "sticker_data",
        "report_build", "artifact_export", "total",
        "sticker_media_resolve", "sticker_aggregation", "group_sticker_features", "report_view_assets",
        "report_json_export", "report_html_export",
        "ActivityAnalyzer", "UserProfileAnalyzer",
        "ConversationAnalyzer",
        "conversation_sessions", "DistinctiveWordAnalyzer",
        "PrivateLanguageAnalyzer", "ExpressionAnalyzer.report",
        "robot_detector", "template_detector",
        "decision_engine", "filter_pipeline",
    }
    if legacy_outputs:
        expected.add("word_speaker_analysis")
    actual = {re.search(r"stage=([^ ]+)", line).group(1) for line in timing_lines}
    assert actual == expected
    assert all(re.search(r"elapsed_ms=\d+", line) for line in timing_lines)
    assert all("Fictional-" not in line for line in timing_lines)
    assert all(re.fullmatch(r"\[analysis-timing\] stage=[A-Za-z_.]+ elapsed_ms=\d+", line)
               for line in timing_lines)


def test_execute_attaches_every_report_to_the_result(tmp_path: Path) -> None:
    application = _application_module()
    input_path = tmp_path / "fictional-chat.json"
    output_directory = tmp_path / "private-output"
    output_directory.mkdir()
    _write_fictional_chat(
        input_path,
        [
            _raw_message(1704099600, "Fictional-Alice", "Python 数据分析 很有趣"),
            _raw_message(1704103200, "Fictional-Alice", "Python 项目 讨论"),
            _raw_message(1704106800, "Fictional-Bob", "Python 项目 讨论 很好"),
        ],
    )

    result = application.AnalysisApplicationService().execute(
        _request(application, tmp_path, input_path)
    )
    reports = result.reports

    assert result.status is application.AnalysisStatus.COMPLETED
    assert reports.activity is not None
    assert reports.activity.total_message_count == 3
    assert len(reports.activity.hourly_counts) == 24
    assert reports.user_profiles is not None
    assert reports.user_profiles.speaker_count == 2
    assert reports.conversations is not None
    assert reports.conversations.conversation_count == 1
    assert reports.conversation_sessions is not None
    assert reports.conversation_sessions.session_count == 3


def test_distinctive_report_reuses_pipeline_tokens_and_stable_sender_keys(
    tmp_path: Path,
) -> None:
    service_module = importlib.import_module(
        "qq_chat_analyzer.application.analysis_service"
    )
    message_module = importlib.import_module("qq_chat_analyzer.message")
    stopwords_path = tmp_path / "private-stopwords.txt"
    stopwords_path.write_text("", encoding="utf-8")
    messages = []
    for member_index, sender_id in enumerate(("stable-a", "stable-b", "stable-c")):
        for message_index in range(30):
            messages.append(
                message_module.ChatMessage(
                    timestamp=1704099600 + message_index,
                    sender=f"Alias-{member_index}-{message_index % 2}",
                    sender_id=sender_id,
                    message_type="text",
                    text=(
                        f"common common common signature{member_index} "
                        f"signature{member_index} support{member_index} "
                        f"third{member_index}"
                    ),
                    conversation_type="group",
                )
            )

    analyzed = service_module._analyze_kept_messages(messages, stopwords_path)
    reports = service_module._build_reports(
        messages,
        analyzed.sender_tokens,
        conversation_type="group",
    )

    assert reports.distinctive_words is not None
    assert reports.distinctive_words.available is True
    assert {member.speaker_key for member in reports.distinctive_words.members} == {
        "stable-a",
        "stable-b",
        "stable-c",
    }


def test_weekday_period_excludes_out_of_scope_and_cleaned_records(tmp_path):
    from dataclasses import replace
    from datetime import date

    application = _application_module()
    path = tmp_path / "fictional-period.json"
    # All are Beijing dates; the long first message is removed by quality filtering.
    _write_fictional_chat(path, [
        _raw_message(1704099600, "Fictional-Alice", "甲" * 101),  # Jan 1
        _raw_message(1704618000, "Fictional-Alice", "周末一起讨论项目"),  # Jan 7
        _raw_message(1704704400, "Fictional-Bob", "周一继续研究数据"),  # Jan 8
        _raw_message(1705309200, "Fictional-Bob", "范围之外的消息"),  # Jan 15
    ])
    request = replace(_request(application, tmp_path, path),
                      scope=application.AnalysisScope.custom(date(2024, 1, 1), date(2024, 1, 8)))
    result = application.AnalysisApplicationService().execute(request)
    activity = result.reports.activity
    assert activity.calendar_day_count == 2
    assert activity.total_message_count == 2
    assert activity.weekday_counts[0].average_per_day == 1
    assert activity.weekday_counts[6].average_per_day == 1
    payload = json.loads((request.output_directory / "echo-report.json").read_text(encoding="utf-8"))
    assert payload["activity"]["calendar_day_count"] == 2
    assert payload["activity"]["weekday_daily_average"][0] == {"label": "周一", "value": 1}
    assert all(m["activity"]["weekday_daily_average"] for m in payload["members"])


def test_execute_generates_echo_report_json_artifact(tmp_path: Path) -> None:
    application = _application_module()
    input_path = tmp_path / "fictional-chat.json"
    output_directory = tmp_path / "private-output"
    output_directory.mkdir()
    _write_fictional_chat(
        input_path,
        [
            _raw_message(1704099600, "Fictional-Alice", "Python 数据分析 很有趣"),
            _raw_message(1704103200, "Fictional-Alice", "Python 项目 讨论"),
            _raw_message(1704106800, "Fictional-Bob", "Python 项目 讨论 很好"),
        ],
    )

    result = application.AnalysisApplicationService().execute(
        _request(application, tmp_path, input_path)
    )

    assert result.status is application.AnalysisStatus.COMPLETED
    assert ("echo_report_json", "echo-report.json") in {
        (artifact.kind, artifact.filename) for artifact in result.artifacts
    }
    report_path = output_directory / "echo-report.json"
    assert report_path.is_file()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "echo-report.v0.13"


def test_report_boundary_does_not_retain_full_expression_candidates() -> None:
    import gc
    import random
    import tracemalloc
    from qq_chat_analyzer.analysis.analyzers import ExpressionAnalyzer
    from qq_chat_analyzer.message import ChatMessage
    from qq_chat_analyzer.application.analysis_service import _build_reports
    from qq_chat_analyzer.analysis.models import AnalysisReports
    from qq_chat_analyzer.presentation import build_echo_report_view

    randomizer = random.Random(71)
    # Use actual Unicode data, not a block range containing non-emoji symbols.
    from qq_chat_analyzer.unicode_emoji import _SEQUENCES
    pool = sorted(item for item in _SEQUENCES if len(item) == 1)[:200]
    messages = [
        ChatMessage(
            timestamp=1704099600 + index,
            sender=f"Fictional {index % 100}",
            sender_id=f"fictional-{index % 100}",
            message_id=f"fictional-message-{index}",
            message_type="text", platform="qq",
            text="".join(randomizer.sample(pool, 8)),
        )
        for index in range(1000)
    ]
    gc.collect()
    tracemalloc.start()
    try:
        candidates = ExpressionAnalyzer().analyze(messages)
        original_prefix = candidates.top_expressions[:10]
        expected_culture = build_echo_report_view(
            AnalysisReports(expression=candidates), expression_source="qq",
        ).expression_culture
        expression = _build_reports(messages, [], expression_report=candidates).expression
        # The selection boundary must not mutate a report held by another caller.
        assert len(candidates.top_expressions) == 200
        assert len(candidates.top_combinations) > 1000
        del candidates
        gc.collect()
        retained_bytes, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    # Final reports retain a fixed prefix plus visible top-N per ranking,
    # rather than thousands of per-member candidates and expression pairs.
    assert retained_bytes < 1024 * 1024
    assert len(expression.top_expressions) <= 15
    assert all(len(member.top_expressions) <= 6 for member in expression.members)
    assert len(expression.top_combinations) <= 6
    assert expression.top_expressions[:10] == original_prefix
    assert build_echo_report_view(
        AnalysisReports(expression=expression), expression_source="qq",
    ).expression_culture == expected_culture
    assert expression.expression_occurrence_count == 8000
    assert expression.expression_message_count == 1000
    assert expression.unique_expression_count == 200
    assert sum(member.expression_occurrence_count for member in expression.members) == 8000


@pytest.mark.parametrize("source", ["qq", "wechat"])
def test_sticker_rank_prefix_does_not_starve_official_expression_display(source):
    from qq_chat_analyzer.analysis.analyzers import ExpressionAnalyzer
    from qq_chat_analyzer.application.analysis_service import _build_reports
    from qq_chat_analyzer.legacy_projection import project_legacy_messages
    from qq_chat_analyzer.presentation import build_echo_report_view
    from qq_chat_analyzer.presentation.echo_serializer import echo_report_to_dict
    from qq_chat_analyzer.rich_message import RichMessage, ExpressionContent, SenderIdentity

    # More leading stickers than either retained raw prefix; official entries
    # must be selected from the complete ranking before candidates are trimmed.
    faces = ("14", "1", "2", "3", "4") if source == "qq" else ("微笑", "捂脸", "大哭", "呲牙", "害羞")
    contents = tuple(
        ExpressionContent("sticker", f"fictional-sticker-{index}", "[贴图]")
        for index in range(12) for _ in range(10)
    ) + tuple(
        ExpressionContent("platform_face", key, f"[{key}]")
        for key in faces for _ in range(2)
    )
    rich = [RichMessage("fictional-ranking", source, "fictional-room",
                        SenderIdentity("fictional-a", "Fictional A"), 1, "text", contents)]
    messages = project_legacy_messages(rich)
    candidates = ExpressionAnalyzer().analyze(messages, rich)
    reports = _build_reports(messages, [], expression_report=candidates, expression_source=source)
    bounded = reports.expression
    for field in ("expression_occurrence_count", "expression_message_count", "unique_expression_count",
                  "expression_only_message_count", "expression_only_rate", "total_message_count"):
        assert getattr(bounded, field) == getattr(candidates, field)
    assert candidates.expression_occurrence_count == 130
    assert len(candidates.top_expressions) == 17
    assert len(bounded.top_expressions) == 15
    view = build_echo_report_view(reports, expression_source=source)
    assert {item.expression_key for item in view.expression_culture.top_expressions} == set(faces)
    assert len(view.expression_culture.members[0].top_expressions) == 3
    payload = echo_report_to_dict(view)["expression_culture"]
    assert payload["unique_expression_count"] == 17
    assert payload["members"][0]["expression_occurrence_count"] == 130
    assert all(item["kind"] == "platform_face" for item in payload["top_expressions"])
    assert "fictional-sticker" not in json.dumps(payload)


def test_expression_member_cards_omit_stickers_and_nonrecurring_expressions():
    from qq_chat_analyzer.analysis.analyzers import ExpressionAnalyzer
    from qq_chat_analyzer.application.analysis_service import _build_reports
    from qq_chat_analyzer.legacy_projection import project_legacy_messages
    from qq_chat_analyzer.presentation import build_echo_report_view, echo_report_to_dict
    from qq_chat_analyzer.rich_message import RichMessage, ExpressionContent, SenderIdentity

    rich = [RichMessage(f"fictional-{index}", "qq", "fictional-room",
        SenderIdentity(f"fictional-{index}", f"Fictional {index}"), index, "text", contents)
        for index, contents in enumerate((
            (ExpressionContent("platform_face", "14", "[微笑]"),) * 2,
            (ExpressionContent("sticker", "fictional-sticker", "[贴图]"),) * 2,
            (ExpressionContent("platform_face", "1", "[撇嘴]"),),
        ))]
    messages = project_legacy_messages(rich)
    reports = _build_reports(messages, [], expression_source="qq",
                             expression_report=ExpressionAnalyzer().analyze(messages, rich))
    culture = echo_report_to_dict(build_echo_report_view(
        reports, conversation_kind="group", expression_source="qq"))["expression_culture"]

    assert len(reports.expression.members) == 3
    assert culture["expression_message_count"] == reports.expression.expression_message_count
    assert [member["speaker_key"] for member in culture["members"]] == ["fictional-0"]


def test_sticker_only_chat_returns_expression_only_with_echo_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qq_chat_analyzer.analysis.analyzers import ExpressionAnalyzer
    original_analyze = ExpressionAnalyzer.analyze
    analyzed_reports = []

    def record_analysis(self, *args, **kwargs):
        report = original_analyze(self, *args, **kwargs)
        analyzed_reports.append(report)
        return report

    monkeypatch.setattr(ExpressionAnalyzer, "analyze", record_analysis)
    application = _application_module()
    input_path = tmp_path / "sticker-only.json"
    output_directory = tmp_path / "private-output"
    output_directory.mkdir()
    _write_wechat_db_sticker_export(input_path)

    result = application.AnalysisApplicationService().execute(
        _request(application, tmp_path, input_path)
    )

    assert len(analyzed_reports) == 1
    assert result.status is application.AnalysisStatus.EXPRESSION_ONLY
    assert result.valid_text_count == 0
    assert result.reports.expression is not None
    assert result.reports.expression.expression_message_count == 2
    assert {artifact.kind for artifact in result.artifacts} == {
        "echo_report_json",
        "echo_report_html",
    }
    assert (output_directory / "wordcloud.png").exists() is False
    payload = json.loads(
        (output_directory / "echo-report.json").read_text(encoding="utf-8")
    )
    assert payload["expression_culture"]["expression_message_count"] == 2
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "stickeronly" not in serialized
    assert "md5" not in serialized
    assert "expression_key" not in serialized
    culture = payload["expression_culture"]
    assert culture["top_expressions"] == []
    assert culture["members"] == []
    assert culture["available"] is False
    assert "微信自定义表情" not in serialized


def test_new_report_metadata_records_corrected_expression_semantics(tmp_path):
    from datetime import datetime, timezone
    from qq_chat_analyzer.application.report_package_metadata import build_report_metadata
    from qq_chat_analyzer.application.scope_filter import AnalysisScope

    app = _application_module()
    path = tmp_path / "fictional-stickers.json"
    _write_wechat_db_sticker_export(path)
    result = app.AnalysisApplicationService().execute(_request(app, tmp_path, path))
    metadata = build_report_metadata(
        result=result, source="wechat", scope=AnalysisScope.all(),
        generated_at=datetime(2026, 10, 16, tzinfo=timezone.utc),
    )
    assert metadata["analysis_revision"] == "echo-analysis.v13"


@pytest.mark.parametrize("source", ["wechat", "qq"])
def test_private_expression_tokens_do_not_reenter_language_profile(tmp_path: Path, source: str) -> None:
    application = _application_module()
    input_path = tmp_path / "fictional-private-expressions.json"
    (tmp_path / "private-output").mkdir()
    if source == "qq":
        _write_private_qq_db_expression_export(input_path)
    else:
        rows = []
        for sender in ("wxid_fictional_self", "wxid_fictional_peer"):
            for kind, text in (
                (1, "公园散步[表情]"), (1, "表情"),
                (1, "[Facepalm]😂"), (47, '<msg><emoji md5="fictional-sticker"/></msg>'),
            ):
                rows.append({
                    "local_id": len(rows) + 1,
                    "server_id": 9000 + len(rows),
                    "create_time": 1704099600 + len(rows) * 60,
                    "local_type": kind, "message_content": text, "user_name": sender,
                })
        input_path.write_text(json.dumps({
            "source": "wechat-db",
            "conversation": {"username": "wxid_fictional_peer", "session_type": "private", "self_username": "wxid_fictional_self"},
            "messages": rows,
        }, ensure_ascii=False), encoding="utf-8")

    result = application.AnalysisApplicationService().execute(_request(application, tmp_path, input_path))
    assert result.status in {application.AnalysisStatus.COMPLETED, application.AnalysisStatus.EXPRESSION_ONLY}
    assert result.reports.expression.expression_occurrence_count > 0
    assert all(word.word != "表情" and not word.word.startswith("expression:") for word in result.top_words)
    profile = result.echo_report_view.language_profile
    assert profile.available
    assert all(not word.startswith("expression:") for member in profile.members for word in member.primary_words)
    assert all(not word.word.startswith("expression:") for word in (*profile.shared_words, *profile.side_preference_words))
    payload = json.loads((tmp_path / "private-output" / "echo-report.json").read_text(encoding="utf-8"))
    assert payload["expression_culture"] is not None
    assert '"表情"' not in json.dumps(payload["language_profile"], ensure_ascii=False)


@pytest.mark.parametrize("conversation_kind", ["private", "group"])
def test_wechat_mentions_do_not_enter_exported_language_profile(tmp_path, conversation_kind):
    application = _application_module()
    path = tmp_path / "fictional-mentions.json"
    (tmp_path / "private-output").mkdir()
    rows = [{
        "local_id": index + 1, "server_id": 9000 + index,
        "create_time": 1704099600 + index * 60, "local_type": 1,
        "message_content": text,
        "user_name": "wxid_fictional_self" if index % 2 else "wxid_fictional_peer",
    } for index, text in enumerate([
        "公园散步@银河 宇宙\u2005周末开会",
        "@银河 宇宙\u2005公园散步 周末开会",
        "下次@银河 宇宙\u2005公园散步聊聊音乐",
        "天气不错@银河 宇宙\u2005公园散步拍照",
    ])]
    path.write_text(json.dumps({
        "source": "wechat-db",
        "conversation": {"username": "wxid_fictional_peer" if conversation_kind == "private"
                         else "wxid_fictional_room@chatroom",
                         "session_type": conversation_kind, "self_username": "wxid_fictional_self"},
        "messages": rows,
    }, ensure_ascii=False), encoding="utf-8")
    result = application.AnalysisApplicationService().execute(_request(application, tmp_path, path))
    words = {item.word for item in result.top_words}
    assert "公园" in words and "散步" in words
    assert not words & {"银河", "宇宙"}
    payload = json.loads((tmp_path / "private-output" / "echo-report.json").read_text(encoding="utf-8"))
    profile = payload["language_profile"]
    assert "公园" in json.dumps(payload["members"], ensure_ascii=False)
    if conversation_kind == "private":
        assert profile["available"]
        assert "公园" in json.dumps(profile, ensure_ascii=False)
        assert [member["expression_habits"]["median_length"] for member in profile["members"]] == [10, 10]
    assert all(name not in json.dumps(profile, ensure_ascii=False) for name in ("银河", "宇宙"))


def test_copy_campaigns_do_not_enter_exported_language_profile(tmp_path, caplog):
    caplog.set_level('INFO', logger='qq_chat_analyzer.desktop.identity')
    application = _application_module()
    path = tmp_path / "fictional-campaigns.json"
    (tmp_path / "private-output").mkdir()
    texts = [
        "公园散步 周末一起去拍照",
        "公园散步 这次想去看看花",
        "公园散步 记得带上相机",
        "公园散步 拍完照片一起吃饭",
        "限时礼包！复制口令【星空福利AbCdEf】参与活动。",
        "复制【星空礼包Q7w8E9】口令，免费奖励等你来拿！",
        "皮肤好礼，复制以下口令并粘贴：K9m2P4，和好友一起参与。",
        "限时奖励，复制兑换码：ABCDEF，前往活动页面使用。",
    ]
    rows = [{
        "local_id": index + 1, "server_id": 9000 + index,
        "create_time": 1704099600 + index * 120, "local_type": 1,
        "message_content": text,
        "user_name": "wxid_fictional_self" if index % 2 else "wxid_fictional_peer",
    } for index, text in enumerate(texts)]
    path.write_text(json.dumps({
        "source": "wechat-db",
        "conversation": {"username": "wxid_fictional_peer", "session_type": "private",
                         "self_username": "wxid_fictional_self"},
        "messages": rows,
    }, ensure_ascii=False), encoding="utf-8")

    result = application.AnalysisApplicationService().execute(_request(application, tmp_path, path))

    assert result.status is application.AnalysisStatus.COMPLETED
    assert result.diagnostic_counts.filtered_message_count == 4
    assert '[analysis] counts raw=8 imported=8 scoped=8 filtered=4' in caplog.text
    assert 'status=completed' in caplog.text
    assert 'wxid_fictional_' not in caplog.text
    payload = json.loads((tmp_path / "private-output" / "echo-report.json").read_text(encoding="utf-8"))
    profile = payload["language_profile"]
    assert profile["available"]
    assert "公园" in json.dumps(profile, ensure_ascii=False)
    assert all(word not in json.dumps(profile, ensure_ascii=False)
               for word in ("口令", "礼包", "限时", "复制", "兑换码"))


def test_content_report_failure_removes_partially_written_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level('INFO', logger='qq_chat_analyzer.desktop.analysis_diagnostics')
    application = _application_module()
    service_module = importlib.import_module(
        "qq_chat_analyzer.application.analysis_service"
    )
    input_path = tmp_path / "partial-report.json"
    output_directory = tmp_path / "private-output"
    output_directory.mkdir()
    _write_wechat_db_sticker_export(input_path)

    def partially_export(request, *args, **kwargs):
        (request.output_directory / "echo-report.json").write_text("{}")
        (request.output_directory / "echo-report.html").write_text("partial")
        raise OSError("fictional export failure")

    monkeypatch.setattr(service_module, "_export_echo_artifacts", partially_export)
    with pytest.raises(application.ArtifactGenerationFailed):
        service_module.AnalysisApplicationService().execute(
            _request(application, tmp_path, input_path)
        )

    assert not (output_directory / "echo-report.json").exists()
    assert not (output_directory / "echo-report.html").exists()
    assert '[analysis-stage] stage=artifact_export outcome=failed failure_code=io_error' in caplog.text
    assert 'fictional export failure' not in caplog.text
