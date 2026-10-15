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


def test_analysis_logs_each_timing_stage_without_private_content(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
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

    result = application.AnalysisApplicationService().execute(
        _request(application, tmp_path, input_path)
    )

    assert result.status is application.AnalysisStatus.COMPLETED
    timing_lines = [
        record.message for record in caplog.records
        if record.message.startswith("[analysis-timing]")
    ]
    expected = {
        "import", "scope_filter", "smart_profile", "message_quality_filter",
        "text_analysis", "ExpressionAnalyzer.preflight", "word_ranking",
        "report_build", "word_speaker_analysis", "artifact_export", "total",
        "ActivityAnalyzer", "MessageLengthAnalyzer", "UserProfileAnalyzer",
        "ConversationAnalyzer", "MessageCompositionAnalyzer",
        "conversation_sessions", "DistinctiveWordAnalyzer",
        "PrivateLanguageAnalyzer", "ExpressionAnalyzer.report",
        "robot_detector", "template_detector", "interactive_bot_detector",
        "decision_engine", "filter_pipeline",
    }
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
    assert reports.message_length is not None
    assert reports.message_length.message_count == 3
    assert reports.user_profiles is not None
    assert reports.user_profiles.speaker_count == 2
    assert reports.conversations is not None
    assert reports.conversations.conversation_count == 1
    assert reports.message_composition is not None
    assert reports.message_composition.total_count == 3
    assert _text_category_count(reports.message_composition) == 3
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


def _text_category_count(report) -> int:
    for item in report.categories:
        if item.category == "文本":
            return item.count
    return 0


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
    pool = [chr(0x1F300 + index) for index in range(200)]
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


def test_sticker_only_chat_returns_expression_only_with_echo_artifacts(
    tmp_path: Path,
) -> None:
    application = _application_module()
    input_path = tmp_path / "sticker-only.json"
    output_directory = tmp_path / "private-output"
    output_directory.mkdir()
    _write_wechat_db_sticker_export(input_path)

    result = application.AnalysisApplicationService().execute(
        _request(application, tmp_path, input_path)
    )

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
