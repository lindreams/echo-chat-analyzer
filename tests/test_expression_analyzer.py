"""Behavior tests for source-neutral expression frequency analysis."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.analysis.analyzers.expression_analyzer import (
    EXPRESSION_KIND_PLATFORM_FACE,
    EXPRESSION_KIND_STICKER,
    EXPRESSION_KIND_UNICODE,
    ExpressionAnalyzer,
    iter_emoji_clusters,
)
from qq_chat_analyzer.legacy_projection import project_legacy_messages
from qq_chat_analyzer.message import ChatMessage
from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages
from qq_db_test_data import qq_db_payload, qq_db_record
from qq_chat_analyzer.rich_message import (
    ExpressionContent,
    RichMessage,
    SenderIdentity,
    TextContent,
)


def _chat(
    text: str,
    *,
    sender_id: str = "fictional-user-1",
    message_id: str = "fictional-message-1",
) -> ChatMessage:
    return ChatMessage(
        timestamp=1,
        sender="Fictional Alice",
        message_type="text",
        text=text,
        platform="qq",
        sender_id=sender_id,
        message_id=message_id,
        conversation_type="group",
    )


def _rich(
    message_id: str,
    *,
    text: str = "",
    faces: tuple[ExpressionContent, ...] = (),
) -> RichMessage:
    contents: list[object] = []
    if text:
        contents.append(TextContent(text=text))
    contents.extend(faces)
    return RichMessage(
        message_id=message_id,
        source="qq",
        conversation_id="fictional-group",
        sender=SenderIdentity(
            identity_id="fictional-user-1",
            display_name="Fictional Alice",
        ),
        timestamp=1,
        message_type="text",
        contents=tuple(contents),
        conversation_type="group",
    )


def test_unicode_emoji_clusters_are_counted_and_attributed() -> None:
    messages = [
        _chat("今天 😀 😀 加油", sender_id="fictional-a", message_id="m1"),
        _chat(
            "👍🏽 和 👨‍👩‍👧 和 🇨🇳",
            sender_id="fictional-b",
            message_id="m2",
        ),
    ]

    report = ExpressionAnalyzer().analyze(messages)

    assert report.expression_message_count == 2
    assert report.expression_occurrence_count == 5
    assert report.unique_expression_count == 4
    assert {item.expression_key for item in report.top_expressions} == {
        "😀",
        "👍🏽",
        "👨‍👩‍👧",
        "🇨🇳",
    }
    assert all(item.kind == EXPRESSION_KIND_UNICODE for item in report.top_expressions)
    assert report.members[0].speaker_key == "fictional-b"
    assert report.members[0].expression_occurrence_count == 3


def test_reply_auto_mention_emoji_does_not_contaminate_sender_expression_stats() -> None:
    record = qq_db_record(" \u4f9d\u65e7\U0001f602", sender_id="fictional-user-alice", nickname="Alice",
                          mention="@Fictional Bob\U0001f410", reply_sequence=42)
    rich_messages, warnings = parse_qq_db_rich_messages(qq_db_payload([record]))
    report = ExpressionAnalyzer().analyze(
        project_legacy_messages(rich_messages),
        rich_messages=rich_messages,
    )

    assert warnings == ()
    assert report.expression_occurrence_count == 1
    assert {item.expression_key for item in report.top_expressions} == {"😂"}
    assert len(report.members) == 1
    alice = report.members[0]
    assert alice.speaker_key == "fictional-user-alice"
    assert alice.expression_occurrence_count == 1
    assert {item.expression_key for item in alice.top_expressions} == {"😂"}


def test_nearby_words_filter_wxid_and_english_stopwords() -> None:
    messages = [
        _chat(
            "the wxid_abc i23op8icohil22 h8n91rnx7l22 furious "
            "12345678901234567890 哈哈 ok[捂脸]",
            sender_id="fictional-a",
            message_id="m-wxid",
        )
    ]
    rich_messages = [
        _rich(
            "m-wxid",
            text=(
                "the wxid_abc i23op8icohil22 h8n91rnx7l22 furious "
                "12345678901234567890 哈哈 ok "
            ) * 2 + "[捂脸]",
            faces=(
                ExpressionContent(
                    expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                    expression_key="捂脸",
                    display_text="[捂脸]",
                ),
            ),
        )
    ]

    report = ExpressionAnalyzer().analyze(
        messages,
        rich_messages=rich_messages,
    )

    words = [word.word for word in report.top_expressions[0].nearby_words]
    assert "哈哈" in words
    assert "ok" in words
    assert all(
        word not in words
        for word in ("the", "wxid_abc", "12345678901234567890")
    )
    assert "i23op8icohil22" not in words
    assert "h8n91rnx7l22" not in words
    assert "furious" not in words


def test_over_budget_message_does_not_count_a_biased_prefix_of_pairs() -> None:
    faces = tuple(
        ExpressionContent(
            expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
            expression_key=f"fictional-face-{index:02d}",
        )
        for index in range(65)
    )
    report = ExpressionAnalyzer().analyze(
        [_chat("", message_id="over-budget")],
        [_rich("over-budget", faces=faces)],
    )

    assert report.top_combinations == ()
    assert report.expression_message_count == 1
    assert report.expression_occurrence_count == 65
    assert report.unique_expression_count == 65


@pytest.mark.parametrize("kind", [
    EXPRESSION_KIND_UNICODE, EXPRESSION_KIND_PLATFORM_FACE, EXPRESSION_KIND_STICKER,
])
def test_expression_message_counts_deduplicate_repeated_occurrences(kind: str) -> None:
    key = "😀" if kind == EXPRESSION_KIND_UNICODE else "fictional-expression"
    messages = []
    rich_messages = []
    for index, (text, repetitions) in enumerate((("garden ", 2), ("comet ", 1), ("", 3))):
        message_id = f"fictional-count-{index}"
        if kind == EXPRESSION_KIND_UNICODE:
            text += key * repetitions
            faces = ()
        else:
            faces = (ExpressionContent(
                expression_kind=kind, expression_key=key, display_text="[表情]",
            ),) * repetitions
        messages.append(_chat(text, message_id=message_id))
        rich_messages.append(_rich(message_id, text=text, faces=faces))

    report = ExpressionAnalyzer().analyze(messages, rich_messages)

    item = report.top_expressions[0]
    assert item.count == 6
    assert item.with_text_message_count == 2
    assert item.text_only_message_count == 1
    assert report.expression_message_count == 3
    assert report.expression_occurrence_count == 6
    assert report.members[0].expression_occurrence_count == 6


def test_rich_message_matching_falls_back_per_message_id() -> None:
    messages = [
        _chat("", sender_id="fictional-a", message_id="with-face"),
        _chat("晚安 😴", sender_id="fictional-b", message_id="text-only"),
    ]
    rich = _rich(
        "with-face",
        faces=(
            ExpressionContent(
                expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                expression_key="7",
                display_text="[QQ表情 7]",
            ),
        ),
    )

    report = ExpressionAnalyzer().analyze(messages, rich_messages=[rich])

    assert report.expression_message_count == 2
    assert {item.expression_key for item in report.top_expressions} == {
        "7",
        "😴",
    }
    assert report.members[0].expression_occurrence_count == 1
    assert report.members[1].expression_occurrence_count == 1


@pytest.mark.parametrize("text, expected", [
    ("★ ☆ ♪ ♫ ❶ 1 # *", []),
    ("⌚ ⏰ ⏳", ["⌚", "⏰", "⏳"]),
    ("1️⃣#️⃣*️⃣ 2\u20e3", ["1️⃣", "#️⃣", "*️⃣", "2\u20e3"]),
    ("❤ ♥ ❤️ ♥️ ❤\ufe0e ♥\ufe0e", ["❤", "♥", "❤️", "♥️"]),
    ("⌚\ufe0e ⌚\ufe0f ☀\ufe0e ☀️", ["⌚\ufe0f", "☀️"]),
    ("👍🏽👨‍👩‍👧🇨🇳", ["👍🏽", "👨‍👩‍👧", "🇨🇳"]),
    ("\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f",
     ["\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f"]),
    ("\U0001faeb", ["\U0001faeb"]),  # Unicode / Emoji 18.0 cracking face
    ("\U0001f02c\U0001fa00", []),  # unassigned / chess, inside old broad ranges
])
def test_unicode_18_sequences_and_chat_presentation_policy(text, expected):
    assert list(iter_emoji_clusters(text)) == expected


def test_decorations_do_not_change_expression_totals_or_expression_only_classification():
    report = ExpressionAnalyzer().analyze([
        _chat("★☆♪♫❶", message_id="decorations"),
        _chat("★😀", message_id="mixed"),
    ])
    assert report.expression_occurrence_count == 1
    assert report.expression_message_count == 1
    assert report.expression_only_message_count == 0
    assert [item.expression_key for item in report.top_expressions] == ["😀"]


def test_member_expression_context_is_local_while_unknown_sender_stays_global():
    messages = [
        _chat("orchard orchard 😀😀", sender_id="fictional-a", message_id="a1"),
        _chat("😀😀😀", sender_id="fictional-a", message_id="a2"),
        _chat("telescope telescope 😀", sender_id="fictional-b", message_id="b1"),
        _chat("telescope telescope 😀", sender_id="fictional-b", message_id="b2"),
        _chat("😀", sender_id="fictional-b", message_id="b3"),
        _chat("😀", sender_id="fictional-b", message_id="b4"),
        _chat("meadow meadow 😀", sender_id=None, message_id="unknown"),
    ]
    messages[-1] = replace(messages[-1], sender="", conversation_type="private")
    report = ExpressionAnalyzer().analyze(messages)
    global_item = report.top_expressions[0]
    assert (global_item.count, global_item.with_text_message_count,
            global_item.text_only_message_count) == (10, 4, 3)
    assert {word.word for word in global_item.nearby_words} == {
        "orchard", "telescope", "meadow",
    }
    members = {member.speaker_key: member for member in report.members}
    assert set(members) == {"fictional-a", "fictional-b"}
    a, b = (members[key].top_expressions[0] for key in ("fictional-a", "fictional-b"))
    assert (a.count, a.with_text_message_count, a.text_only_message_count) == (5, 1, 1)
    assert (b.count, b.with_text_message_count, b.text_only_message_count) == (4, 2, 2)
    # Nearby-word weighting remains per occurrence, within each member's messages.
    assert [(word.word, word.count) for word in a.nearby_words] == [("orchard", 4)]
    assert [(word.word, word.count) for word in b.nearby_words] == [("telescope", 4)]
    from qq_chat_analyzer.application.analysis_service import _build_reports
    from qq_chat_analyzer.presentation import build_echo_report_view, echo_report_to_dict
    view = build_echo_report_view(_build_reports(messages, [], expression_report=report))
    serialized = echo_report_to_dict(view)["expression_culture"]
    entries = {member["speaker_key"]: member["top_expressions"][0]
               for member in serialized["members"]}
    assert set(entries) == {"fictional-a", "fictional-b"}
    assert entries["fictional-a"]["with_text_message_count"] == 1
    assert entries["fictional-a"]["text_only_message_count"] == 1
    assert entries["fictional-a"]["nearby_words"] == ["orchard"]
    assert entries["fictional-b"]["with_text_message_count"] == 2
    assert entries["fictional-b"]["text_only_message_count"] == 2
    assert entries["fictional-b"]["nearby_words"] == ["telescope"]
