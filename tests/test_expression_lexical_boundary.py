"""BUG-08: expressions must not affect lexical words or their denominators."""

from __future__ import annotations

import json

import pytest

from test_analysis_reports_service import _application_module, _request
from test_qq_db_rich_contents import _body, _bytes, _face, _payload, _scalar, _sticker, _text


_LEXICAL_TEXTS = (
    "orchard orchard meadow harvest",
    "astronomy astronomy telescope galaxy",
    "ocean ocean coral marine",
)
_LEXICAL_WORDS = {word for text in _LEXICAL_TEXTS for word in text.split()}
_EMOJIS = "😀😂🥰😎🤔😭😡👍👏🙏🎉❤️" * 3


def _fictional_payload(source, conversation_type, expression_heavy, include_unicode=True):
    sender_count = 3 if conversation_type == "group" else 2
    unicode_text = _EMOJIS if include_unicode else ""
    if source == "qq":
        blobs = []
        for index in range(120):
            text = _LEXICAL_TEXTS[index % sender_count]
            if conversation_type == "private":
                text += " garden"
            parts = [_text(text + (unicode_text if expression_heavy else ""))]
            if expression_heavy:
                parts.extend((
                    _face(label="Facepalm"),
                    _sticker(label="Facepalm"),
                    _scalar(45002, 11) + _bytes(45600, b"fictional-fallback"),
                ))
            blobs.append(_body(*parts))
        payload = _payload(*blobs, session_type=conversation_type)
        for index, record in enumerate(payload["records"]):
            record["fields"]["40033"] = f"fictional-sender-{index % sender_count}"
        return payload

    rows = []
    for index in range(120):
        text = _LEXICAL_TEXTS[index % sender_count]
        if conversation_type == "private":
            text += " garden"
        contents = [(1, text + ("[捂脸]" + unicode_text if expression_heavy else ""))]
        if expression_heavy:
            contents.extend((
                (47, '<msg><emoji md5="fictional-sticker"/></msg>'),
                (47, '<msg><emoji md5="fictional-other-sticker"/></msg>'),
            ))
        for kind, content in contents:
            rows.append({
                "local_id": len(rows) + 1, "server_id": 9000 + len(rows),
                "create_time": 1704099600 + len(rows) * 60,
                "local_type": kind, "message_content": content,
                "user_name": f"wxid_fictional_{index % sender_count}",
            })
    return {"source": "wechat-db", "conversation": {
        "username": "fictional@chatroom" if conversation_type == "group" else "wxid_fictional_0",
        "session_type": conversation_type, "self_username": "wxid_fictional_1",
    }, "messages": rows}


def _lexical_pair(tmp_path, source, conversation_type, include_unicode=True):
    """Compare identical lexical input with and without abundant expressions."""
    results = []
    for expression_heavy in (False, True):
        directory = tmp_path / ("heavy" if expression_heavy else "text")
        directory.mkdir()
        (directory / "private-output").mkdir()
        path = directory / "fictional.json"
        path.write_text(json.dumps(_fictional_payload(
            source, conversation_type, expression_heavy, include_unicode,
        ), ensure_ascii=False), encoding="utf-8")
        app = _application_module()
        result = app.AnalysisApplicationService().execute(_request(app, directory, path))
        assert result.status is app.AnalysisStatus.COMPLETED
        results.append(result)
    return results


@pytest.mark.parametrize("source", ["qq", "wechat"])
def test_source_expressions_keep_exact_counts_without_display_text_leaks(tmp_path, source):
    baseline, heavy = _lexical_pair(tmp_path, source, "group", include_unicode=False)
    assert baseline.reports.expression.expression_occurrence_count == 0
    expression = heavy.reports.expression
    assert expression.expression_occurrence_count == 360
    assert {item.kind for item in expression.top_expressions} == {"platform_face", "sticker"}
    assert sum(item.count for item in expression.top_expressions if item.kind == "sticker") == 240
    assert sum(item.count for item in expression.top_expressions if item.kind == "platform_face") == 120
    assert heavy.top_words == baseline.top_words
    assert all(word.word in _LEXICAL_WORDS for word in heavy.top_words)


def test_sender_specific_expressions_cannot_displace_real_distinctive_words():
    from qq_chat_analyzer.application.analysis_service import _build_reports

    lexical = [
        (f"fictional-{sender}", [f"lexical-{sender}-{word}" for word in range(5)])
        for sender in range(3) for _ in range(40)
    ]
    mixed = [
        (sender, words + [f"expression:{sender}-sticker-{index}" for index in range(12)] * 20)
        for sender, words in lexical
    ]
    baseline = _build_reports([], lexical, conversation_type="group").distinctive_words
    heavy = _build_reports([], mixed, conversation_type="group").distinctive_words
    assert all(len(member.words) == 5 for member in baseline.members)
    assert [{word.word for word in member.words} for member in heavy.members] == [
        {word.word for word in member.words} for member in baseline.members
    ]
