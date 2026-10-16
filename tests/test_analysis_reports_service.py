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
    assert payload["schema_version"] == "echo-report.v0.7"


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
    assert all(
        not member["top_expressions"] for member in culture["members"]
    )
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
    assert metadata["analysis_revision"] == "echo-analysis.v6"


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


def test_content_report_failure_removes_partially_written_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
