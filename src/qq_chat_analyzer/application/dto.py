"""Privacy-safe data transfer objects for application use cases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from ..analysis.models import AnalysisReports
from ..analysis.stickers import StickerData
from ..presentation.models import EchoReportView
from .scope_filter import AnalysisScope


_EMPTY_NAMES: Mapping[str, str] = MappingProxyType({})


class AnalysisStatus(str, Enum):
    """Outcome states for a completed analysis use case."""

    COMPLETED = "completed"
    NO_VALID_TEXT = "no_valid_text"
    NO_TOKENS = "no_tokens"
    EXPRESSION_ONLY = "expression_only"


@dataclass(frozen=True, slots=True)
class AnalysisRequestDTO:
    """In-process command for one local analysis run."""

    input_path: Path = field(repr=False)
    output_directory: Path = field(repr=False)
    stopwords_path: Path = field(repr=False)
    font_path: str | None = field(default=None, repr=False)
    top: int = 50
    scope: AnalysisScope = field(
        default_factory=AnalysisScope.all,
        repr=False,
    )
    speaker_names: Mapping[str, str] = field(
        default=_EMPTY_NAMES,
        repr=False,
    )
    conversation_names: Mapping[str, str] = field(
        default=_EMPTY_NAMES,
        repr=False,
    )
    conversation_kind: str = "unknown"
    viewer_speaker_key: str | None = field(default=None, repr=False)
    sticker_media_roots: tuple[Path, ...] = field(default=(), repr=False)
    # QQ generation prepares its view first, then writes once after media recovery.
    export_echo_report: bool = True


@dataclass(frozen=True, slots=True)
class WordFrequencyDTO:
    """One aggregate word-frequency result."""

    word: str
    count: int


@dataclass(frozen=True, slots=True)
class ArtifactDTO:
    """Public descriptor for one locally generated artifact."""

    kind: str
    filename: str


@dataclass(frozen=True, slots=True)
class AnalysisDiagnosticCounts:
    """Privacy-safe message counts captured at analysis stage boundaries."""

    raw_message_count: int | None = None
    imported_message_count: int | None = None
    scope_message_count: int | None = None
    filtered_message_count: int | None = None
    analyzed_message_count: int | None = None


@dataclass(frozen=True, slots=True)
class AnalysisResultDTO:
    """Privacy-safe result returned by the analysis use case."""

    status: AnalysisStatus
    processed_message_count: int
    valid_text_count: int
    diagnostic_counts: AnalysisDiagnosticCounts | None = None
    top_words: tuple[WordFrequencyDTO, ...] = ()
    artifacts: tuple[ArtifactDTO, ...] = ()
    reports: AnalysisReports = field(
        default_factory=AnalysisReports,
        repr=False,
    )
    echo_report_view: EchoReportView | None = field(default=None, repr=False)
    stickers: StickerData = field(default_factory=StickerData, repr=False)
