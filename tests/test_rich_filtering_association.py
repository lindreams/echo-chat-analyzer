"""Rich facts follow projected record instances, not source identifiers."""

from __future__ import annotations

import importlib
import json
from collections import Counter
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


@pytest.mark.parametrize("source", ["qq", "wechat"])
@pytest.mark.parametrize("stage", ["scope", "quality", "sender", "template"])
def test_filtered_duplicate_id_cannot_supply_rich_facts(tmp_path, monkeypatch, stage, source):
    kept_time = int(datetime(2026, 1, 2, 12).timestamp())

    def row(message_id, text, face, *, timestamp=kept_time, sender="fiction-human", image=False):
        if source == "qq":
            return qq_row(message_id, text, face, timestamp=timestamp, sender=sender, image=image)
        face_text = "[微笑]" if face == 14 else "[大哭]"
        authored = (text.replace(" 加入群聊", face_text + " 加入群聊")
                    if " 加入群聊" in text else text + face_text)
        result = wx_row(message_id, authored)
        result.update(create_time=timestamp, user_name=sender)
        return result

    rows = [row("duplicate", "Human authored 🐱", 14)]
    scope = None
    if stage == "scope":
        rows.append(row("duplicate", "Outside scope 🐶", 15, image=True,
                           timestamp=int(datetime(2025, 1, 2, 12).timestamp())))
        scope = AnalysisScope.custom(date(2026, 1, 2), date(2026, 1, 2))
    elif stage == "quality":
        rows.append(row("duplicate", "Filtered " + "z" * 110 + " 🐶", 15,
                           image=True))
    elif stage == "sender":
        rows.extend(row("duplicate", "固定签到播报 🐶", 15,
                        sender="fiction-robot", timestamp=kept_time + i * 120)
                    for i in range(10))
    else:
        rows.extend(row("duplicate", f"欢迎 虚构成员{member} 🐶 加入群聊", 15,
                        sender=f"fiction-welcome-{member}") for member in ("甲", "乙", "丙", "丁"))
    service = importlib.import_module("qq_chat_analyzer.application.analysis_service")
    original = service.run_smart_profile
    decisions = []

    def observe_profile(messages):
        filtered = original(messages)
        decisions.extend(filtered.applied_decisions)
        return filtered

    monkeypatch.setattr(service, "run_smart_profile", observe_profile)
    payload = qq_file(rows) if source == "qq" else wx_file(rows)
    result, (kept, analyzed) = analyze(tmp_path, monkeypatch, [payload], scope)
    if stage in {"sender", "template"}:
        assert any(item.target_type == stage and item.action == "ignore" for item in decisions)
    assert len(kept) == 1
    face_key = "14" if source == "qq" else "微笑"
    assert expression_counts(result) == {"🐱": 1, face_key: 1}
    assert voice_expressions(analyzed) == ["expression:🐱", f"expression:{face_key}"]
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


@pytest.mark.parametrize("source", ["qq", "wechat"])
def test_unicode_projection_tokens_and_expression_report_agree(tmp_path, monkeypatch, source):
    flag = "\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f"
    text = "orchard1️⃣meadow ⌚ ⏰ ⏳ 👍🏽 👨‍👩‍👧 🇨🇳 " + flag + " ❤ ★☆♪♫❶ ❤\ufe0e"
    if source == "qq":
        payload = qq_file([qq_row("unicode", text, 14)])
        face = "14"
    else:
        payload = wx_file([wx_row("unicode", text + "[Facepalm]")])
        face = "捂脸"
    result, (_, analyzed) = analyze(tmp_path, monkeypatch, [payload])
    expected = {key: 1 for key in ("1️⃣", "⌚", "⏰", "⏳", "👍🏽", "👨‍👩‍👧", "🇨🇳", flag, "❤", face)}
    assert expression_counts(result) == expected
    assert Counter(token.removeprefix("expression:") for token in voice_expressions(analyzed)) == expected
    assert analyzed.tokens == ["orchard", "meadow"]
    report = result.reports.expression
    assert report.expression_occurrence_count == 10
    assert report.expression_message_count == 1 and report.expression_only_message_count == 0
    assert report.members[0].expression_occurrence_count == 10


@pytest.mark.parametrize("source", ["qq", "wechat"])
@pytest.mark.parametrize("kind, status, expressions", [
    ("unicode", "expression_only", 1),
    ("official", "expression_only", 1),
    ("sticker", "expression_only", 1),
    ("word", "completed", 0),
    ("decoration", "no_tokens", 0),
])
def test_single_content_kind_keeps_report_status_contract(
    tmp_path, monkeypatch, source, kind, status, expressions,
):
    text = {"unicode": "⌚", "word": "orchard", "decoration": "★☆♪♫❶"}.get(kind, "")
    if source == "qq":
        if kind == "sticker":
            from test_qq_db_rich_contents import _sticker
            payload = _payload(_body(_sticker()))
        else:
            payload = qq_file([qq_row("boundary", text, 14 if kind == "official" else None)])
    else:
        if kind == "official":
            text = "[Facepalm]"
        payload = wx_file([wx_row("boundary", text, sticker=kind == "sticker")])
    result, (_, analyzed) = analyze(tmp_path, monkeypatch, [payload])
    assert result.status.value == status
    assert len(voice_expressions(analyzed)) == expressions
    if status == "no_tokens":
        assert result.artifacts == ()
    else:
        assert {item.kind for item in result.artifacts} == {"echo_report_json", "echo_report_html"}
        assert result.reports.expression.expression_occurrence_count == expressions
