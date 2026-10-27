"""User profile analysis combining volume, length, and activity."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from statistics import median

from ..models import (
    ConsecutiveRunStats,
    HourlyActivity,
    ProfileWord,
    UserProfile,
    UserProfileReport,
    WeekdayActivity,
)
from ..peaks import DAYS_PER_WEEK, HOURS_PER_DAY, busiest_index
from ..identity import is_chat_participant, stable_sender_key
from ..timestamps import to_chat_datetime
from ...analyzer import top_words
from ...cleaner import clean_text
from ...message import ChatMessage


class UserProfileAnalyzer:
    """Combine existing signals into one profile per speaker."""

    def analyze(
        self,
        messages: Sequence[ChatMessage],
        sender_tokens: Iterable[tuple[str, Iterable[str]]] | None = None,
        top_words_per_user: int = 10,
        speaker_names: Mapping[str, str] | None = None,
        *,
        weekday_calendar_days: Sequence[int] = (),
    ) -> UserProfileReport:
        """Return per-speaker profiles ordered by message volume.

        Tokens are never recomputed here; callers pass already-tokenized
        ``sender_tokens`` so tokenization stays owned by the tokenizer.

        ``speaker_names`` optionally maps a raw sender key to a friendly
        name. Names come from the caller so this analyzer stays independent
        of any chat source.

        ``weekday_calendar_days`` is the conversation's shared observation
        window; it must not be replaced by each speaker's active dates.
        """
        stats: dict[str, _SpeakerStats] = {}
        runs: dict[str, list[int]] = {}
        current_run_key: str | None = None
        current_run_length = 0

        for message in messages:
            speaker_key = stable_sender_key(message)
            if current_run_key == speaker_key:
                current_run_length += 1
            else:
                if current_run_key is not None and current_run_length:
                    runs.setdefault(current_run_key, []).append(
                        current_run_length
                    )
                current_run_key = speaker_key
                current_run_length = 1
            if not is_chat_participant(message):
                continue
            speaker_stats = stats.setdefault(speaker_key, _SpeakerStats())
            speaker_stats.add(message)
        if current_run_key is not None and current_run_length:
            runs.setdefault(current_run_key, []).append(current_run_length)

        total_message_count = len(messages)
        speaker_words = _speaker_top_words(sender_tokens, top_words_per_user)
        profiles = [
            UserProfile(
                speaker=speaker_stats.speaker or speaker,
                speaker_key=speaker_stats.speaker_key or speaker,
                message_count=speaker_stats.message_count,
                first_seen_order=first_seen_order,
                message_share_percent=_share_percent(
                    speaker_stats.message_count,
                    total_message_count,
                ),
                average_length=speaker_stats.average_length(),
                median_length=speaker_stats.median_length(),
                max_length=speaker_stats.max_length,
                busiest_hour=busiest_index(speaker_stats.hourly_counts),
                busiest_weekday=busiest_index(speaker_stats.weekday_counts),
                top_words=speaker_words.get(speaker, ()),
                display_name=_speaker_display_name(speaker, speaker_names),
                hourly_counts=tuple(
                    HourlyActivity(hour=hour, count=count)
                    for hour, count in enumerate(speaker_stats.hourly_counts)
                ),
                weekday_counts=tuple(
                    WeekdayActivity(
                        weekday=weekday, count=count,
                        calendar_days=(
                            weekday_calendar_days[weekday]
                            if len(weekday_calendar_days) == DAYS_PER_WEEK else 0
                        ),
                    )
                    for weekday, count in enumerate(
                        speaker_stats.weekday_counts
                    )
                ),
                remark=speaker_stats.remark,
                nickname=speaker_stats.nickname,
                contextual_name=speaker_stats.contextual_name,
                consecutive_runs=(
                    _consecutive_run_stats(runs[speaker])
                    if runs.get(speaker)
                    else None
                ),
            )
            for first_seen_order, (speaker, speaker_stats) in enumerate(stats.items())
        ]
        profiles.sort(key=lambda profile: -profile.message_count)

        return UserProfileReport(
            total_message_count=total_message_count,
            speaker_count=len(profiles),
            profiles=tuple(profiles),
        )


class _SpeakerStats:
    """Mutable accumulator for one speaker."""

    __slots__ = (
        "message_count",
        "hourly_counts",
        "weekday_counts",
        "text_lengths",
        "max_length",
        "speaker",
        "speaker_key",
        "remark",
        "nickname",
        "contextual_name",
    )

    def __init__(self) -> None:
        self.message_count = 0
        self.hourly_counts = [0] * HOURS_PER_DAY
        self.weekday_counts = [0] * DAYS_PER_WEEK
        self.text_lengths: list[int] = []
        self.max_length = 0
        self.speaker: str | None = None
        self.speaker_key: str | None = None
        self.remark: str | None = None
        self.nickname: str | None = None
        self.contextual_name: str | None = None

    def add(self, message: ChatMessage) -> None:
        self.message_count += 1
        if self.speaker is None:
            self.speaker = message.sender
        if self.speaker_key is None:
            self.speaker_key = stable_sender_key(message)
        self.remark = _merge_identity_field(self.remark, message.sender_remark)
        self.nickname = _merge_identity_field(
            self.nickname,
            message.sender_nickname,
        )
        self.contextual_name = _merge_identity_field(
            self.contextual_name,
            message.sender_contextual_name,
        )

        length = len(clean_text(message.text, platform=message.platform))
        if length > 0:
            self.text_lengths.append(length)
            self.max_length = max(self.max_length, length)

        moment = to_chat_datetime(message.timestamp)
        if moment is not None:
            self.hourly_counts[moment.hour] += 1
            self.weekday_counts[moment.weekday()] += 1

    def average_length(self) -> float:
        if not self.text_lengths:
            return 0.0
        return round(sum(self.text_lengths) / len(self.text_lengths), 2)

    def median_length(self) -> float:
        if not self.text_lengths:
            return 0.0
        return float(median(self.text_lengths))


def _share_percent(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total * 100, 2)


def _merge_identity_field(current: str | None, candidate: str | None) -> str | None:
    """Keep the first non-empty identity value seen for one profile."""
    if isinstance(candidate, str) and candidate.strip():
        value = candidate.strip()
        if not current:
            return value
    return current


def _speaker_top_words(
    sender_tokens: Iterable[tuple[str, Iterable[str]]] | None,
    top_words_per_user: int,
) -> dict[str, tuple[ProfileWord, ...]]:
    if sender_tokens is None or top_words_per_user <= 0:
        return {}

    token_lists: dict[str, list[str]] = {}
    for sender, tokens in sender_tokens:
        token_lists.setdefault(sender, []).extend(tokens)

    return {
        sender: tuple(
            ProfileWord(word=word, count=count)
            for word, count in top_words(tokens, top_words_per_user)
        )
        for sender, tokens in token_lists.items()
    }


def _speaker_display_name(
    speaker: str,
    speaker_names: Mapping[str, str] | None,
) -> str | None:
    """Look up a friendly name for one speaker key."""
    if not speaker_names:
        return None
    name = speaker_names.get(speaker)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _consecutive_run_stats(runs: list[int]) -> ConsecutiveRunStats:
    """Aggregate one speaker's consecutive-sender runs deterministically."""
    run_count = len(runs)
    if run_count == 0:
        return ConsecutiveRunStats(
            run_count=0,
            average_run_length=0.0,
            median_run_length=0.0,
            single_message_run_count=0,
            multi_message_run_count=0,
        )
    single_message_count = sum(1 for length in runs if length == 1)
    return ConsecutiveRunStats(
        run_count=run_count,
        average_run_length=round(sum(runs) / run_count, 2),
        median_run_length=float(median(runs)),
        single_message_run_count=single_message_count,
        multi_message_run_count=run_count - single_message_count,
    )
