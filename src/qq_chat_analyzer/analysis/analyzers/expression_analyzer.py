"""Frequency and composition analysis for source-neutral expressions."""

from __future__ import annotations

import itertools
from collections import Counter
from collections.abc import Mapping, Sequence

from ...message import ChatMessage
from ...unicode_emoji import iter_emoji_clusters
from ...rich_message import (
    EXPRESSION_KIND_PLATFORM_FACE,
    EXPRESSION_KIND_STICKER,
    EXPRESSION_KIND_UNICODE,
    ExpressionContent,
    RichMessage,
    TextContent,
)
from ...tokenizer import iter_expression_placeholders, iter_text_tokens
from ..identity import is_chat_participant, stable_sender_key
from ..models import (
    ExpressionCombinationMember,
    ExpressionCombinationMemberCount,
    ExpressionCombinationUsage,
    ExpressionNearbyWord,
    ExpressionReport,
    ExpressionUsage,
    MemberExpressionUsage,
)


EXPRESSION_NEARBY_WORD_LIMIT = 3
EXPRESSION_NEARBY_WORD_MIN_COUNT = 2
# Count every unordered pair up to 64 distinct expressions (2,016 pairs).
# Above this budget omit the whole message from combination statistics rather
# than selecting an order-dependent prefix. Other expression counts are kept.
EXPRESSION_COMBINATION_MESSAGE_LIMIT = 64

_NEARBY_STOPWORDS = frozenset(
    {
        "啊",
        "吧",
        "把",
        "被",
        "不",
        "从",
        "到",
        "的",
        "都",
        "给",
        "和",
        "很",
        "会",
        "就",
        "来",
        "了",
        "吗",
        "呢",
        "能",
        "去",
        "让",
        "上",
        "是",
        "他",
        "她",
        "它",
        "下",
        "要",
        "也",
        "在",
        "这",
        "中",
        "那",
        "我",
        "你",
    }
)
_ENGLISH_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "furious",
        "have",
        "he",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "was",
        "we",
        "with",
        "you",
    }
)
_WXID_PREFIX = "w" + "xid"
_WX_PREFIX = "w" + "x_"
_GH_PREFIX = "g" + "h_"
_CHATROOM_MARKER = "@" + "chat" + "room"


class ExpressionAnalyzer:
    """Count expression occurrences without interpreting emotion."""

    def analyze(
        self,
        messages: Sequence[ChatMessage],
        rich_messages: Sequence[RichMessage] = (),
        *,
        rich_by_instance: Mapping[int, RichMessage] | None = None,
    ) -> ExpressionReport:
        if rich_by_instance is None:
            # Compatibility for direct callers without projection pairs:
            # accept only unambiguous IDs, never choose among duplicates.
            legacy_ids = Counter(message.message_id for message in messages)
            rich_ids = Counter(message.message_id for message in rich_messages)
            rich_by_id = {
                message.message_id: message
                for message in rich_messages
                if message.message_id is not None
                and legacy_ids[message.message_id] == 1
                and rich_ids[message.message_id] == 1
            }
            rich_by_instance = {
                id(message): rich_by_id[message.message_id]
                for message in messages
                if message.message_id in rich_by_id
            }
        occurrences: Counter[str] = Counter()
        display_by_key: dict[str, str] = {}
        kind_by_key: dict[str, str] = {}
        with_text_counts: Counter[str] = Counter()
        text_only_counts: Counter[str] = Counter()
        nearby_word_counts: dict[str, Counter[str]] = {}
        combination_counts: Counter[tuple[str, str]] = Counter()
        combination_speaker_counts: dict[
            tuple[str, str],
            Counter[str],
        ] = {}
        member_occurrences: dict[str, Counter[str]] = {}
        member_with_text_counts: Counter[tuple[str, str]] = Counter()
        member_text_only_counts: Counter[tuple[str, str]] = Counter()
        member_nearby_word_counts: dict[tuple[str, str], Counter[str]] = {}
        member_message_counts: dict[str, int] = {}
        member_only_counts: dict[str, int] = {}
        expression_message_count = 0
        expression_only_message_count = 0
        total_message_count = len(messages)

        for message in messages:
            rich_message = rich_by_instance.get(id(message))
            text, face_expressions = self._message_expression_sources(
                message,
                rich_message,
            )
            unicode_items = list(iter_emoji_clusters(text))
            items = [
                (EXPRESSION_KIND_UNICODE, item, item)
                for item in unicode_items
            ]
            items.extend(
                (
                    expression.expression_kind,
                    expression.expression_key,
                    expression.display_text or "[表情]",
                )
                for expression in face_expressions
            )
            if not items:
                continue

            habit_items = [
                item
                for item in items
                if item[0] != EXPRESSION_KIND_STICKER
            ]
            expression_message_count += 1
            expression_only = self._is_expression_only_message(
                text,
                unicode_items,
                face_expressions,
            )
            if expression_only:
                expression_only_message_count += 1
            nearby_tokens = _nearby_tokens(
                text,
                displays=tuple(item[2] for item in habit_items),
            )
            for _, expression_key, _ in habit_items:
                nearby_word_counts.setdefault(
                    expression_key,
                    Counter(),
                ).update(nearby_tokens)
            speaker_key = stable_sender_key(message)
            distinct_keys = {expression_key for _, expression_key, _ in habit_items}
            combination_keys = (
                sorted(distinct_keys)
                if len(distinct_keys) <= EXPRESSION_COMBINATION_MESSAGE_LIMIT
                else ()
            )
            for pair in itertools.combinations(combination_keys, 2):
                combination_counts[pair] += 1
                if is_chat_participant(message):
                    combination_speaker_counts.setdefault(
                        pair,
                        Counter(),
                    )[speaker_key] += 1
            for expression_key in {key for _, key, _ in items}:
                if expression_only:
                    text_only_counts[expression_key] += 1
                else:
                    with_text_counts[expression_key] += 1

            for kind, expression_key, display_text in items:
                occurrences[expression_key] += 1
                display_by_key.setdefault(expression_key, display_text)
                kind_by_key.setdefault(expression_key, kind)
            if not is_chat_participant(message):
                continue
            speaker_counts = member_occurrences.setdefault(
                speaker_key,
                Counter(),
            )
            for _, expression_key, _ in items:
                speaker_counts[expression_key] += 1
            for expression_key in {key for _, key, _ in items}:
                if expression_only:
                    member_text_only_counts[speaker_key, expression_key] += 1
                else:
                    member_with_text_counts[speaker_key, expression_key] += 1
            for _, expression_key, _ in habit_items:
                member_nearby_word_counts.setdefault(
                    (speaker_key, expression_key), Counter(),
                ).update(nearby_tokens)
            member_message_counts[speaker_key] = (
                member_message_counts.get(speaker_key, 0) + 1
            )
            if expression_only:
                member_only_counts[speaker_key] = (
                    member_only_counts.get(speaker_key, 0) + 1
                )

        total_occurrences = sum(occurrences.values())
        # Keep ranked candidates complete: presentation filters stickers before
        # applying its own global/member limits and must be able to backfill.
        top_expressions = tuple(
            ExpressionUsage(
                expression_key=key,
                display_text=display_by_key[key],
                count=count,
                kind=kind_by_key[key],
                with_text_message_count=with_text_counts.get(key, 0),
                text_only_message_count=text_only_counts.get(key, 0),
                nearby_words=_nearby_words(
                    nearby_word_counts.get(key, Counter()),
                ),
            )
            for key, count in _sorted_counts(occurrences)
        )
        members = tuple(
            MemberExpressionUsage(
                speaker_key=speaker_key,
                expression_occurrence_count=sum(counts.values()),
                expression_message_count=member_message_counts[speaker_key],
                expression_share_percent=_percent(
                    sum(counts.values()),
                    total_occurrences,
                ),
                expression_only_message_count=member_only_counts.get(
                    speaker_key,
                    0,
                ),
                top_expressions=tuple(
                    ExpressionUsage(
                        expression_key=key,
                        display_text=display_by_key[key],
                        count=count,
                        kind=kind_by_key[key],
                        with_text_message_count=member_with_text_counts[speaker_key, key],
                        text_only_message_count=member_text_only_counts[speaker_key, key],
                        nearby_words=_nearby_words(
                            member_nearby_word_counts.get((speaker_key, key), Counter()),
                        ),
                    )
                    for key, count in _sorted_counts(counts)
                ),
            )
            for speaker_key, counts in member_occurrences.items()
        )
        members = tuple(
            sorted(
                members,
                key=lambda member: (
                    -member.expression_occurrence_count,
                    member.speaker_key,
                ),
            )
        )
        top_combinations = tuple(
            sorted(
                (
                    ExpressionCombinationUsage(
                        expressions=(
                            ExpressionCombinationMember(
                                expression_key=expression_a,
                                display_text=display_by_key.get(
                                    expression_a,
                                    "",
                                ),
                            ),
                            ExpressionCombinationMember(
                                expression_key=expression_b,
                                display_text=display_by_key.get(
                                    expression_b,
                                    "",
                                ),
                            ),
                        ),
                        count=count,
                        member_counts=tuple(
                            ExpressionCombinationMemberCount(
                                speaker_key=member_key,
                                count=member_count,
                            )
                            for member_key, member_count in _sorted_counts(
                                combination_speaker_counts.get(
                                    (expression_a, expression_b),
                                    Counter(),
                                )
                            )
                        ),
                    )
                    for (expression_a, expression_b), count in (
                        combination_counts.items()
                    )
                ),
                key=lambda item: (
                    -item.count,
                    item.expressions[0].expression_key,
                    item.expressions[1].expression_key,
                ),
            )
        )

        return ExpressionReport(
            expression_message_count=expression_message_count,
            expression_only_message_count=expression_only_message_count,
            expression_only_rate=_rate(
                expression_only_message_count,
                total_message_count,
            ),
            unique_expression_count=len(occurrences),
            expression_occurrence_count=total_occurrences,
            total_message_count=total_message_count,
            top_expressions=top_expressions,
            members=members,
            top_combinations=top_combinations,
        )

    @staticmethod
    def _message_expression_sources(
        message: ChatMessage,
        rich_message: RichMessage | None,
    ) -> tuple[str, tuple[ExpressionContent, ...]]:
        if rich_message is None:
            text = message.text
            expressions: tuple[ExpressionContent, ...] = ()
        else:
            text = "".join(
                content.text
                for content in rich_message.contents
                if isinstance(content, TextContent)
            )
            expressions = tuple(
                content
                for content in rich_message.contents
                if isinstance(content, ExpressionContent)
            )
        placeholders = tuple(
            ExpressionContent(
                expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
                expression_key=placeholder,
                display_text=placeholder,
                source=message.platform,
                position=position,
            )
            for position, placeholder in enumerate(
                iter_expression_placeholders(text)
            )
        )
        return text, (*expressions, *placeholders)

    @staticmethod
    def _is_expression_only_message(
        text: str,
        unicode_items: list[str],
        face_expressions: tuple[ExpressionContent, ...],
    ) -> bool:
        if face_expressions:
            # Unicode expressions in authored text are not ordinary wording.
            # Remove longer clusters before their base emoji (e.g. 👍🏽 / 👍).
            for item in sorted(set(unicode_items), key=len, reverse=True):
                text = text.replace(item, "")
            compact = "".join(text.split())
            if not compact:
                return True
            placeholders = "".join(
                expression.display_text
                or f"[{expression.expression_key}]"
                for expression in face_expressions
            )
            return bool(placeholders) and compact == "".join(
                placeholders.split()
            )
        if not unicode_items:
            return False
        compact = "".join(text.split())
        return bool(compact) and "".join(unicode_items) == compact


def _sorted_counts(counts: Counter[str]) -> list[tuple[str, int]]:
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _nearby_tokens(text: str, *, displays: tuple[str, ...]) -> list[str]:
    """Return simple jieba tokens from the message text around expressions."""
    cleaned = text
    for display in displays:
        if display:
            cleaned = cleaned.replace(display, " ")
    tokens: list[str] = []
    for token in iter_text_tokens(cleaned):
        token = token.strip()
        if (
            _is_word_like(token)
            and len(token) >= 2
            and not token.isdigit()
            and not token.isdecimal()
            and token not in _NEARBY_STOPWORDS
            and not _is_junk_nearby_token(token)
        ):
            tokens.append(token)
    return tokens


def _is_word_like(token: str) -> bool:
    if not token:
        return False
    if any("\u4e00" <= char <= "\u9fff" for char in token):
        return True
    return any(char.isalnum() for char in token)


def _is_junk_nearby_token(token: str) -> bool:
    lowered = token.lower()
    if lowered.startswith((_WXID_PREFIX, _WX_PREFIX, _GH_PREFIX)):
        return True
    if (
        _CHATROOM_MARKER in lowered
        or _CHATROOM_MARKER[1:] in lowered
    ):
        return True
    if lowered in _ENGLISH_STOPWORDS:
        return True
    digit_count = sum(char.isdigit() for char in token)
    if (
        len(token) >= 8
        and any(char.isdigit() for char in token)
        and any(char.isalpha() for char in token)
    ):
        return True
    if len(token) >= 6 and digit_count / len(token) > 0.5:
        return True
    return len(token) >= 24 and token.isalnum()


def _nearby_words(counts: Counter[str]) -> tuple[ExpressionNearbyWord, ...]:
    return tuple(
        ExpressionNearbyWord(word=word, count=count)
        for word, count in _sorted_counts(counts)[
            :EXPRESSION_NEARBY_WORD_LIMIT
        ]
        if count >= EXPRESSION_NEARBY_WORD_MIN_COUNT
    )


def _percent(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(part * 100.0 / total, 2)


def _rate(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(part / total, 4)
