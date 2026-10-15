"""Behavior tests for the privacy-safe analysis application service."""

from __future__ import annotations

import dataclasses
import importlib
import json
from chat_input_test_data import detailed_payload
import sys
from datetime import date
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

def _application_module():
    return importlib.import_module("qq_chat_analyzer.application")


def _service_module():
    return importlib.import_module(
        "qq_chat_analyzer.application.analysis_service"
    )


def _write_fictional_chat(path: Path, messages: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(detailed_payload(messages), ensure_ascii=False),
        encoding="utf-8",
    )


def _request(
    application,
    tmp_path: Path,
    input_path: Path,
    *,
    stopwords: str = "",
    top: int = 5,
):
    stopwords_path = tmp_path / "private-stopwords.txt"
    stopwords_path.write_text(stopwords, encoding="utf-8")
    return application.AnalysisRequestDTO(
        input_path=input_path,
        output_directory=tmp_path / "private-output",
        stopwords_path=stopwords_path,
        font_path=None,
        top=top,
    )


def test_execute_returns_completed_privacy_safe_result_without_cli_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = _application_module()
    service_module = _service_module()
    input_path = tmp_path / "fictional-chat.json"
    output_directory = tmp_path / "private-output"
    stopwords_path = tmp_path / "private-stopwords.txt"
    private_senders = ("Fictional-Alice", "Fictional-Bob")
    _write_fictional_chat(
        input_path,
        [
            {
                "timestamp": 1,
                "sender": {"nickname": private_senders[0]},
                "type": "text",
                "content": {"text": "Python Python analytics"},
            },
            {
                "timestamp": 2,
                "sender": {"nickname": private_senders[1]},
                "type": "text",
                "content": {"text": "Python project"},
            },
        ],
    )
    stopwords_path.write_text("", encoding="utf-8")

    generated_filenames: list[str] = []

    def record_export(*args: object) -> None:
        generated_filenames.append(Path(str(args[-1])).name)

    monkeypatch.setattr(
        service_module,
        "export_echo_report_json",
        record_export,
    )
    monkeypatch.setattr(
        service_module,
        "export_echo_report_html",
        record_export,
    )

    tokenizer_module = importlib.import_module("qq_chat_analyzer.tokenizer")
    tokenizer_module.tokenize("warmup")
    capsys.readouterr()

    result = service_module.AnalysisApplicationService().execute(
        application.AnalysisRequestDTO(
            input_path=input_path,
            output_directory=output_directory,
            stopwords_path=stopwords_path,
            font_path=None,
            top=5,
        )
    )

    captured = capsys.readouterr()
    assert result.status is application.AnalysisStatus.COMPLETED
    assert result.processed_message_count == 2
    assert result.valid_text_count == 2
    assert result.diagnostic_counts == application.AnalysisDiagnosticCounts(
        raw_message_count=2,
        imported_message_count=2,
        scope_message_count=2,
        filtered_message_count=2,
        analyzed_message_count=2,
    )
    assert result.top_words[0] == application.WordFrequencyDTO(
        word="Python",
        count=3,
    )
    assert {(artifact.kind, artifact.filename) for artifact in result.artifacts} == {
        ("echo_report_json", "echo-report.json"),
        ("echo_report_html", "echo-report.html"),
    }
    assert set(generated_filenames) == {
        "echo-report.json",
        "echo-report.html",
    }
    assert captured.out == ""
    assert captured.err == ""
    result_repr = repr(result)
    assert str(tmp_path) not in result_repr
    for private_sender in private_senders:
        assert private_sender not in result_repr


def test_execute_rejects_missing_input_without_exposing_path(
    tmp_path: Path,
) -> None:
    application = _application_module()
    service_module = _service_module()
    missing_path = tmp_path / "private-missing-chat.json"

    with pytest.raises(application.InputPathNotFound) as captured:
        service_module.AnalysisApplicationService().execute(
            _request(application, tmp_path, missing_path)
        )

    assert str(missing_path) not in str(captured.value)


def test_execute_analyzes_only_messages_inside_the_scope(
    tmp_path: Path,
) -> None:
    application = _application_module()
    service_module = _service_module()
    input_path = tmp_path / "fictional-scoped-chat.json"
    _write_fictional_chat(
        input_path,
        [
            {
                "timestamp": "2026-01-31 23:59:59",
                "sender": {"nickname": "Fictional-Alice"},
                "type": "text",
                "content": {"text": "OutsideMarker"},
            },
            {
                "timestamp": "2026-02-01 12:00:00",
                "sender": {"nickname": "Fictional-Alice"},
                "type": "text",
                "content": {"text": "InsideMarker"},
            },
        ],
    )
    request = dataclasses.replace(
        _request(application, tmp_path, input_path),
        scope=application.AnalysisScope.custom(
            date(2026, 2, 1),
            date(2026, 2, 1),
        ),
    )

    result = service_module.AnalysisApplicationService().execute(request)

    assert result.status is application.AnalysisStatus.COMPLETED
    assert result.processed_message_count == 1
    assert result.valid_text_count == 1
    assert result.reports.activity.total_message_count == 1
    assert {word.word for word in result.top_words} == {"InsideMarker"}


def test_execute_stops_before_analysis_when_scope_has_no_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _application_module()
    service_module = _service_module()
    input_path = tmp_path / "fictional-out-of-scope-chat.json"
    _write_fictional_chat(
        input_path,
        [
            {
                "timestamp": "2025-01-01 12:00:00",
                "sender": {"nickname": "Fictional-Alice"},
                "type": "text",
                "content": {"text": "OutsideMarker"},
            }
        ],
    )

    def fail_if_analysis_starts(*args, **kwargs):
        raise AssertionError("analysis must not run for an empty scope")

    monkeypatch.setattr(
        service_module,
        "run_smart_profile",
        fail_if_analysis_starts,
    )
    request = dataclasses.replace(
        _request(application, tmp_path, input_path),
        scope=application.AnalysisScope.custom(
            date(2026, 1, 1),
            date(2026, 12, 31),
        ),
    )

    with pytest.raises(application.NoMessagesInScope) as captured:
        service_module.AnalysisApplicationService().execute(request)

    assert captured.value.public_message == "当前时间范围内没有可分析的聊天记录。"
    assert not request.output_directory.exists()
