"""Source-neutral report models for extended chat analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .conversation_sessions import ConversationSessionReport
from .stickers import StickerConversationReport
from .sticker_features import PrivateStickerFeatures


UNKNOWN_CONVERSATION_NAME = "\u672a\u77e5\u4f1a\u8bdd"

INTERNAL_ID_SUFFIXES = ("@chatroom",)
INTERNAL_ID_PREFIXES = ("wxid_",)


def is_displayable_conversation_id(conversation_id: str | None) -> bool:
    """Return whether a raw conversation key is safe to show to a user.

    Internal handles such as ``wxid_abc`` or ``12345@chatroom`` carry no
    meaning for readers, so they are hidden behind a generic label.
    """
    if not conversation_id:
        return False

    candidate = conversation_id.strip()
    if not candidate:
        return False

    lowered = candidate.lower()
    if lowered.startswith(INTERNAL_ID_PREFIXES):
        return False
    if lowered.endswith(INTERNAL_ID_SUFFIXES):
        return False
    return True


@dataclass(frozen=True, slots=True)
class HourlyActivity:
    """Message count for one hour of the day."""

    hour: int
    count: int


@dataclass(frozen=True, slots=True)
class WeekdayActivity:
    """Message count for one weekday, where Monday is zero."""

    weekday: int
    count: int


@dataclass(frozen=True, slots=True)
class ActivityReport:
    """Temporal distribution of messages across hours and weekdays."""

    total_message_count: int
    dated_message_count: int
    hourly_counts: tuple[HourlyActivity, ...] = ()
    weekday_counts: tuple[WeekdayActivity, ...] = ()
    active_days: int = 0
    average_messages_per_active_day: float = 0.0


@dataclass(frozen=True, slots=True)
class ConsecutiveRunStats:
    """Per-speaker consecutive-sending statistics over kept message order."""

    run_count: int
    average_run_length: float
    median_run_length: float
    single_message_run_count: int
    multi_message_run_count: int


@dataclass(frozen=True, slots=True)
class ProfileWord:
    """One frequent word attributed to a single speaker."""

    word: str = field(repr=False)
    count: int


@dataclass(frozen=True, slots=True)
class UserProfile:
    """Combined activity and length profile for one speaker."""

    speaker: str = field(repr=False)
    message_count: int
    message_share_percent: float
    average_length: float
    max_length: int
    busiest_hour: int | None = None
    busiest_weekday: int | None = None
    top_words: tuple[ProfileWord, ...] = ()
    display_name: str | None = field(default=None, repr=False)
    hourly_counts: tuple[HourlyActivity, ...] = ()
    weekday_counts: tuple[WeekdayActivity, ...] = ()
    speaker_key: str | None = field(default=None, repr=False)
    remark: str | None = field(default=None, repr=False)
    nickname: str | None = field(default=None, repr=False)
    contextual_name: str | None = field(default=None, repr=False)
    median_length: float = 0.0
    consecutive_runs: ConsecutiveRunStats | None = None

    @property
    def resolved_display_name(self) -> str:
        """Return the friendly name, falling back to the raw speaker key."""
        return self.display_name or self.speaker


@dataclass(frozen=True, slots=True)
class UserProfileReport:
    """Per-speaker profiles ordered by message volume."""

    total_message_count: int
    speaker_count: int = 0
    profiles: tuple[UserProfile, ...] = ()


class DistinctiveWordAvailability(str, Enum):
    """Why a distinctive-word report is or is not displayable."""

    AVAILABLE = "available"
    NOT_GROUP = "not_group"
    INSUFFICIENT_MEMBERS = "insufficient_members"


@dataclass(frozen=True, slots=True)
class DistinctiveWord:
    """One member word ranked by smoothed log-odds z-score."""

    word: str = field(repr=False)
    count: int
    member_rate: float
    others_rate: float
    relative_ratio: float
    ranking_score: float


@dataclass(frozen=True, slots=True)
class MemberDistinctiveWords:
    """Distinctive words for one member who passed sample thresholds."""

    speaker_key: str = field(repr=False)
    tokenized_message_count: int
    token_count: int
    eligible_word_candidate_count: int
    words: tuple[DistinctiveWord, ...] = ()


@dataclass(frozen=True, slots=True)
class DistinctiveWordReport:
    """Source-neutral group distinctive-word analysis result."""

    conversation_type: str
    availability: DistinctiveWordAvailability
    eligible_member_count: int = 0
    members: tuple[MemberDistinctiveWords, ...] = ()

    @property
    def available(self) -> bool:
        return self.availability is DistinctiveWordAvailability.AVAILABLE


@dataclass(frozen=True, slots=True)
class PrivateSharedWord:
    """One word both private sides used, with normalized per-side statistics."""

    word: str = field(repr=False)
    speaker_a: str = field(repr=False)
    speaker_b: str = field(repr=False)
    count_a: int
    count_b: int
    total_tokens_a: int
    total_tokens_b: int
    rate_a: float
    rate_b: float
    common_strength: float
    preferred_speaker_key: str | None = field(repr=False)
    occurrence_support: int


@dataclass(frozen=True, slots=True)
class PrivateLanguageReport:
    """Private shared-word statistics derived from full sender tokens."""

    shared_words: tuple[PrivateSharedWord, ...] = ()


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    """Volume, span, and participation for one conversation."""

    conversation_id: str | None = field(repr=False)
    message_count: int
    speaker_count: int
    start_timestamp: int | None = None
    end_timestamp: int | None = None
    duration_seconds: int | None = None
    display_name: str | None = field(default=None, repr=False)

    @property
    def resolved_display_name(self) -> str:
        """Return the friendly name, hiding internal conversation keys.

        Falls back to `conversation_id` when it is human-readable, and to
        `UNKNOWN_CONVERSATION_NAME` when the key is an internal handle.
        """
        if self.display_name and self.display_name.strip():
            return self.display_name.strip()
        if is_displayable_conversation_id(self.conversation_id):
            return self.conversation_id.strip()
        return UNKNOWN_CONVERSATION_NAME


@dataclass(frozen=True, slots=True)
class ConversationReport:
    """Aggregate view of every conversation in one analysis run."""

    conversation_count: int
    conversations: tuple[ConversationSummary, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisReports:
    """Bundle of every extended report produced for one analysis run."""

    activity: ActivityReport | None = None
    user_profiles: UserProfileReport | None = None
    conversations: ConversationReport | None = None
    conversation_sessions: ConversationSessionReport | None = None
    distinctive_words: DistinctiveWordReport | None = None
    private_language: PrivateLanguageReport | None = None
    expression: ExpressionReport | None = None
    stickers: tuple[StickerConversationReport, ...] = ()
    # Private evidence only; Echo serializers consume the separate view model.
    private_stickers: PrivateStickerFeatures | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ExpressionNearbyWord:
    """One word that often appears in the same message as an expression."""

    word: str = field(repr=False)
    count: int


@dataclass(frozen=True, slots=True)
class ExpressionUsage:
    """One ranked expression occurrence with its display label."""

    expression_key: str
    display_text: str
    count: int
    kind: str
    with_text_message_count: int = 0
    text_only_message_count: int = 0
    nearby_words: tuple[ExpressionNearbyWord, ...] = ()


@dataclass(frozen=True, slots=True)
class ExpressionCombinationMember:
    """One side of an expression combination, kept source-neutral."""

    expression_key: str
    display_text: str


@dataclass(frozen=True, slots=True)
class ExpressionCombinationMemberCount:
    """How often one sender used an expression combination."""

    speaker_key: str = field(repr=False)
    count: int


@dataclass(frozen=True, slots=True)
class ExpressionCombinationUsage:
    """Two distinct expressions that appeared in the same message."""

    expressions: tuple[
        ExpressionCombinationMember,
        ExpressionCombinationMember,
    ]
    count: int
    member_counts: tuple[ExpressionCombinationMemberCount, ...] = ()


@dataclass(frozen=True, slots=True)
class MemberExpressionUsage:
    """Expression frequency and composition for one stable speaker."""

    speaker_key: str = field(repr=False)
    expression_occurrence_count: int
    expression_message_count: int
    expression_share_percent: float
    expression_only_message_count: int
    top_expressions: tuple[ExpressionUsage, ...] = ()


@dataclass(frozen=True, slots=True)
class ExpressionReport:
    """Frequency and composition of expressions in one analysis run."""

    expression_message_count: int
    expression_only_message_count: int
    expression_only_rate: float
    unique_expression_count: int
    expression_occurrence_count: int = 0
    total_message_count: int = 0
    top_expressions: tuple[ExpressionUsage, ...] = ()
    members: tuple[MemberExpressionUsage, ...] = ()
    top_combinations: tuple[ExpressionCombinationUsage, ...] = ()
