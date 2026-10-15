"""Rich facts follow projected record instances, not source identifiers."""

from __future__ import annotations

import importlib
import json
from datetime import date, datetime

import pytest

from chat_input_test_data import detailed_payload

from qq_chat_analyzer.application import AnalysisRequestDTO, ImportRequest, ImportService
from qq_chat_analyzer.application.scope_filter import AnalysisScope
from qq_chat_analyzer.analysis.models import AnalysisReports
from qq_chat_analyzer.analysis.analyzers import ExpressionAnalyzer
from test_qq_db_rich_contents import _body, _face, _payload, _scalar, _text


def qq_row(message_id, text="", face=None, *, image=False,
           timestamp=1760000000, sender="fiction-human"):
    segments = []
    if text:
        segments.append(_text(text))
    if face is not None:
        segments.append(_face(face))
    if image:
        segments.append(_scalar(45002, 2))
    record = _payload(_body(*segments))["records"][0]
    record["record_id"] = message_id
    record["fields"]["40050"] = timestamp
    record["fields"]["40033"] = sender
    return record


def qq_file(rows, session="fiction-room"):
    payload = _payload()
    payload["query"]["session_object"] = session
    payload["records"] = rows
    return payload


def wx_row(local_id=None, text="", *, sticker=False):
    return {
        "server_id": None, "local_id": local_id,
        "local_type": 47 if sticker else 1,
        "create_time": 1760000000, "user_name": "fiction-human",
        "message_content": (
            '<msg><emoji md5="fiction-sticker"/></msg>' if sticker else text
        ),
    }


def wx_file(rows, session="fiction-wx"):
    return {
        "source": "wechat-db",
        "conversation": {"username": session, "session_type": "group"},
        "messages": rows,
    }


def analyze(tmp_path, monkeypatch, payloads, scope=None):
    input_path = tmp_path / "input"
    input_path.mkdir()
    for index, payload in enumerate(payloads):
        (input_path / f"{index}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8",
        )
    stopwords = tmp_path / "stopwords.txt"
    stopwords.write_text("", encoding="utf-8")
    service = importlib.import_module("qq_chat_analyzer.application.analysis_service")
    original = service._analyze_kept_messages
    observed = []

    def capture(messages, *args, **kwargs):
        result = original(messages, *args, **kwargs)
        observed.append((messages, result))
        return result

    monkeypatch.setattr(service, "_analyze_kept_messages", capture)
    result = service.AnalysisApplicationService().execute(AnalysisRequestDTO(
        input_path=input_path, output_directory=tmp_path / "output",
        stopwords_path=stopwords, scope=scope or AnalysisScope.all(),
    ))
    assert len(observed) == 1
    return result, observed[0]


def expression_counts(result):
    assert result.reports is not None
    return {
        usage.expression_key: usage.count
        for usage in result.reports.expression.top_expressions
    }


def voice_expressions(analyzed):
    return [token for _, tokens in analyzed.sender_tokens for token in tokens
            if token.startswith("expression:")]


@pytest.mark.parametrize("stage", ["scope", "quality"])
def test_filtered_duplicate_id_cannot_supply_rich_facts(tmp_path, monkeypatch, stage):
    kept_time = int(datetime(2026, 1, 2, 12).timestamp())
    rows = [qq_row("duplicate", "Human authored 🐱", 14, timestamp=kept_time)]
    scope = None
    if stage == "scope":
        rows.append(qq_row("duplicate", "Outside scope 🐶", 15, image=True,
                           timestamp=int(datetime(2025, 1, 2, 12).timestamp())))
        scope = AnalysisScope.custom(date(2026, 1, 2), date(2026, 1, 2))
    elif stage == "quality":
        rows.append(qq_row("duplicate", "Filtered " + "z" * 110 + " 🐶", 15,
                           image=True))
    else:
        rows.extend(qq_row(f"robot-{i}", "Daily fictional robot result 123", 15,
                           sender="fiction-robot") for i in range(8))
        rows[-1]["record_id"] = "duplicate"
    result, (kept, analyzed) = analyze(tmp_path, monkeypatch, [qq_file(rows)], scope)
    assert len(kept) == 1
    assert expression_counts(result) == {"🐱": 1, "14": 1}
    assert voice_expressions(analyzed) == ["expression:🐱", "expression:14"]
    assert "Human" in analyzed.tokens and "Filtered" not in analyzed.tokens


def test_both_duplicate_ids_keep_their_own_expressions(tmp_path, monkeypatch):
    result, (kept, analyzed) = analyze(tmp_path, monkeypatch, [qq_file([
        qq_row("duplicate", "Fiction alpha", 14),
        qq_row("duplicate", "Fiction beta", 15, timestamp=1760000001),
    ])])
    assert len(kept) == 2
    assert expression_counts(result) == {"14": 1, "15": 1}
    assert voice_expressions(analyzed) == ["expression:14", "expression:15"]


@pytest.mark.parametrize("source", ["qq", "wechat"])
@pytest.mark.parametrize("missing", [False, True])
def test_missing_id_preserves_structured_expression(tmp_path, monkeypatch, source, missing):
    if source == "qq":
        row = qq_row(None, face=14)
        if missing:
            del row["record_id"]
        payload, key = qq_file([row]), "14"
    else:
        row = wx_row(sticker=True)
        if missing:
            del row["local_id"]
            del row["server_id"]
        payload, key = wx_file([row]), "fiction-sticker"
    result, (kept, analyzed) = analyze(tmp_path, monkeypatch, [payload])
    assert kept[0].message_id is None
    assert result.status.value == "expression_only"
    assert expression_counts(result) == {key: 1}
    assert voice_expressions(analyzed) == [f"expression:{key}"]


@pytest.mark.parametrize("message_id", [None, "duplicate"])
def test_filtered_composite_collision_does_not_enable_nontext_report(
    tmp_path, monkeypatch, message_id,
):
    result, (kept, _) = analyze(tmp_path, monkeypatch, [qq_file([
        qq_row(message_id, "."),
        qq_row(message_id, "Filtered " + "z" * 110, image=True),
    ])])
    assert len(kept) == 1 and kept[0].text == "."
    assert result.status.value == "no_tokens"
    assert result.reports == AnalysisReports()
    assert result.artifacts == ()


@pytest.mark.parametrize("source", ["qq"])
def test_same_id_across_files_and_sessions_does_not_cross_associate(
    tmp_path, monkeypatch, source,
):
    if source == "qq":
        payloads = [qq_file([qq_row("duplicate", "Human authored", 14)], "room-A"),
                    qq_file([qq_row("duplicate", "Filtered " + "z" * 110, 15)], "room-B")]
        expected = "14"
    else:
        payloads = [wx_file([wx_row(11, "Human authored [微笑]")], "room-A"),
                    wx_file([wx_row(11, "Filtered " + "z" * 110 + " [大哭]")], "room-B")]
        expected = "微笑"
    result, (kept, analyzed) = analyze(tmp_path, monkeypatch, payloads)
    assert len(kept) == 1
    assert expression_counts(result) == {expected: 1}
    assert voice_expressions(analyzed) == [f"expression:{expected}"]


def test_direct_expression_call_does_not_guess_among_duplicate_ids(tmp_path):
    path = tmp_path / "duplicate-projections.json"
    path.write_text(json.dumps(qq_file([
        qq_row("duplicate", face=14), qq_row("duplicate", face=15),
    ])), encoding="utf-8")
    outcome = ImportService().execute(ImportRequest(path))
    analyzer = ExpressionAnalyzer()
    fallback = analyzer.analyze(outcome.messages, outcome.rich_messages)
    assert fallback.expression_message_count == 0
    explicit = analyzer.analyze(
        outcome.messages,
        rich_by_instance={id(legacy): rich for legacy, rich in outcome.rich_message_pairs},
    )
    assert {usage.expression_key: usage.count
            for usage in explicit.top_expressions} == {"14": 1, "15": 1}
