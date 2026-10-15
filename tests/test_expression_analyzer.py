"""Behavior tests for source-neutral expression frequency analysis."""

from __future__ import annotations

import sys
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


def test_platform_face_from_rich_message_counts_as_expression_only() -> None:
    message = _chat("", sender_id="fictional-a", message_id="m1")
    rich = _rich(
        "m1",
        faces=(
            ExpressionContent(
                expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                expression_key="358",
                display_text="/骰子",
            ),
        ),
    )

    report = ExpressionAnalyzer().analyze([message], rich_messages=[rich])

    assert report.expression_message_count == 1
    assert report.expression_only_message_count == 1
    assert report.expression_only_rate == 1.0
    assert report.top_expressions[0].kind == EXPRESSION_KIND_PLATFORM_FACE
    assert report.top_expressions[0].expression_key == "358"
    assert report.members[0].expression_only_message_count == 1


def test_mixed_text_and_face_message_is_not_expression_only() -> None:
    message = _chat("哈哈 😂 来了", sender_id="fictional-a", message_id="m1")
    rich = _rich(
        "m1",
        text="哈哈 😂 来了",
        faces=(
            ExpressionContent(
                expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                expression_key="66",
                display_text="[QQ表情 66]",
            ),
        ),
    )

    report = ExpressionAnalyzer().analyze([message], rich_messages=[rich])

    assert report.expression_message_count == 1
    assert report.expression_only_message_count == 0
    assert report.unique_expression_count == 2
    assert {item.expression_key for item in report.top_expressions} == {
        "😂",
        "66",
    }


def test_sticker_expressions_count_and_track_text_association() -> None:
    with_text = _chat("来一个", sender_id="fictional-a", message_id="sticker-with")
    rich_with_text = _rich(
        "sticker-with",
        text="来一个",
        faces=(
            ExpressionContent(
                expression_kind=EXPRESSION_KIND_STICKER,
                expression_key="sticker-a",
                display_text="[贴图]",
            ),
        ),
    )
    only = _chat("", sender_id="fictional-b", message_id="sticker-only")
    rich_only = _rich(
        "sticker-only",
        faces=(
            ExpressionContent(
                expression_kind=EXPRESSION_KIND_STICKER,
                expression_key="sticker-b",
                display_text="[贴图]",
            ),
        ),
    )

    report = ExpressionAnalyzer().analyze(
        [with_text, only],
        rich_messages=[rich_with_text, rich_only],
    )

    by_key = {item.expression_key: item for item in report.top_expressions}
    assert by_key["sticker-a"].with_text_message_count == 1
    assert by_key["sticker-a"].text_only_message_count == 0
    assert by_key["sticker-b"].with_text_message_count == 0
    assert by_key["sticker-b"].text_only_message_count == 1
    assert {item.kind for item in report.top_expressions} == {
        EXPRESSION_KIND_STICKER,
    }


def test_with_text_and_text_only_counts_cover_unicode_and_faces() -> None:
    mixed = _chat("哈哈 😀", sender_id="fictional-a", message_id="mixed")
    rich_mixed = _rich(
        "mixed",
        text="哈哈 😀",
        faces=(
            ExpressionContent(
                expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                expression_key="66",
                display_text="[QQ表情 66]",
            ),
        ),
    )
    face_only = _chat("", sender_id="fictional-b", message_id="face-only")
    rich_face_only = _rich(
        "face-only",
        faces=(
            ExpressionContent(
                expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                expression_key="1",
                display_text="[QQ表情 1]",
            ),
        ),
    )

    report = ExpressionAnalyzer().analyze(
        [mixed, face_only],
        rich_messages=[rich_mixed, rich_face_only],
    )

    by_key = {item.expression_key: item for item in report.top_expressions}
    assert by_key["😀"].with_text_message_count == 1
    assert by_key["66"].with_text_message_count == 1
    assert by_key["1"].text_only_message_count == 1


def test_official_bracket_emoji_without_text_counts_as_expression_only() -> None:
    message = _chat("[捂脸]", sender_id="fictional-a", message_id="bracket-only")
    rich = _rich(
        "bracket-only",
        text="[捂脸]",
        faces=(
            ExpressionContent(
                expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                expression_key="捂脸",
                display_text="[捂脸]",
            ),
        ),
    )

    report = ExpressionAnalyzer().analyze(
        [message],
        rich_messages=[rich],
    )

    assert report.expression_only_message_count == 1
    item = report.top_expressions[0]
    assert item.expression_key == "捂脸"
    assert item.text_only_message_count == 1
    assert item.with_text_message_count == 0


def test_mixed_bracket_emoji_with_text_counts_with_text() -> None:
    message = _chat("哈哈[捂脸]", sender_id="fictional-a", message_id="bracket-mixed")
    rich = _rich(
        "bracket-mixed",
        text="哈哈[捂脸]",
        faces=(
            ExpressionContent(
                expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                expression_key="捂脸",
                display_text="[捂脸]",
            ),
        ),
    )

    report = ExpressionAnalyzer().analyze(
        [message],
        rich_messages=[rich],
    )

    assert report.expression_only_message_count == 0
    item = report.top_expressions[0]
    assert item.with_text_message_count == 1
    assert item.text_only_message_count == 0


def test_unicode_only_emoji_counts_as_text_only() -> None:
    report = ExpressionAnalyzer().analyze(
        [_chat("😀", sender_id="fictional-a", message_id="unicode-only")]
    )

    assert report.expression_only_message_count == 1
    assert report.top_expressions[0].text_only_message_count == 1
    assert report.top_expressions[0].with_text_message_count == 0


def test_nearby_words_require_repeated_occurrences() -> None:
    report = ExpressionAnalyzer().analyze([
        _chat("garden comet 😀", message_id="nearby-1"),
        _chat("garden 😀", message_id="nearby-2"),
    ])

    assert [(word.word, word.count) for word in report.top_expressions[0].nearby_words] == [
        ("garden", 2),
    ]
    assert report.members[0].top_expressions[0].nearby_words == report.top_expressions[0].nearby_words


def test_same_message_expression_combinations_are_counted() -> None:
    messages = [
        _chat("[捂脸][旺柴]", sender_id="fictional-a", message_id="m-combo-1"),
        _chat("[捂脸][旺柴]", sender_id="fictional-a", message_id="m-combo-2"),
        _chat("[捂脸][裂开]", sender_id="fictional-b", message_id="m-combo-3"),
    ]
    rich_messages = [
        _rich(
            "m-combo-1",
            faces=(
                ExpressionContent(
                    expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                    expression_key="捂脸",
                    display_text="[捂脸]",
                ),
                ExpressionContent(
                    expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                    expression_key="旺柴",
                    display_text="[旺柴]",
                ),
            ),
        ),
        _rich(
            "m-combo-2",
            faces=(
                ExpressionContent(
                    expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                    expression_key="捂脸",
                    display_text="[捂脸]",
                ),
                ExpressionContent(
                    expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                    expression_key="旺柴",
                    display_text="[旺柴]",
                ),
            ),
        ),
        _rich(
            "m-combo-3",
            faces=(
                ExpressionContent(
                    expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                    expression_key="捂脸",
                    display_text="[捂脸]",
                ),
                ExpressionContent(
                    expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                    expression_key="裂开",
                    display_text="[裂开]",
                ),
            ),
        ),
    ]

    report = ExpressionAnalyzer().analyze(
        messages,
        rich_messages=rich_messages,
    )

    assert report.top_combinations
    top = report.top_combinations[0]
    assert {member.expression_key for member in top.expressions} == {
        "捂脸",
        "旺柴",
    }
    assert top.count == 2
    assert {
        member.speaker_key: member.count
        for member in top.member_counts
    } == {"fictional-a": 2}


def test_nearby_words_filter_single_chars_digits_and_stopwords() -> None:
    messages = [
        _chat(
            "1 2 好 数字 2024 哈哈 来了 了[捂脸]",
            sender_id="fictional-a",
            message_id="m-clean",
        )
    ]
    rich_messages = [
        _rich(
            "m-clean",
            text="1 2 好 数字 2024 哈哈 来了 了 " * 2 + "[捂脸]",
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
    assert "数字" in words
    assert all(word not in words for word in ("1", "2", "好", "2024", "了"))


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


def test_expression_combinations_merge_reversed_order() -> None:
    report = ExpressionAnalyzer().analyze([
        _chat("😀👍😀", sender_id="fictional-a", message_id="forward"),
        _chat("👍😀", sender_id="fictional-b", message_id="reverse"),
    ])

    assert len(report.top_combinations) == 1
    combination = report.top_combinations[0]
    assert {item.expression_key for item in combination.expressions} == {"😀", "👍"}
    assert combination.count == 2
    assert {item.speaker_key: item.count for item in combination.member_counts} == {
        "fictional-a": 1,
        "fictional-b": 1,
    }


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


def test_sticker_does_not_enter_nearby_or_combinations() -> None:
    message = _chat("[贴图][捂脸]", sender_id="fictional-a", message_id="m-sticker")
    rich = _rich(
        "m-sticker",
        faces=(
            ExpressionContent(
                expression_kind=EXPRESSION_KIND_STICKER,
                expression_key="sticker-key",
                display_text="[贴图]",
            ),
            ExpressionContent(
                expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                expression_key="捂脸",
                display_text="[捂脸]",
            ),
        ),
    )

    report = ExpressionAnalyzer().analyze([message], rich_messages=[rich])

    assert report.top_combinations == ()
    by_key = {item.expression_key: item for item in report.top_expressions}
    assert by_key["捂脸"].nearby_words == ()


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


def test_report_is_empty_without_expressions() -> None:
    report = ExpressionAnalyzer().analyze(
        [_chat("普通文本", message_id="plain")]
    )

    assert report.expression_message_count == 0
    assert report.expression_only_message_count == 0
    assert report.unique_expression_count == 0
    assert report.top_expressions == ()
    assert report.members == ()
