"""Application orchestration for one local chat analysis run."""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from ..analysis_diagnostics import timed_stage
from ..analysis.identity import is_chat_participant, stable_sender_key
from ..analysis.conversation_sessions import analyze_conversation_sessions
from ..analysis.analyzers import (
    ActivityAnalyzer,
    ConversationAnalyzer,
    DistinctiveWordAnalyzer,
    ExpressionAnalyzer,
    PrivateLanguageAnalyzer,
    UserProfileAnalyzer,
)
from ..analysis.analyzers.expression_analyzer import iter_emoji_clusters
from ..analysis.models import AnalysisReports, ExpressionReport
from ..analysis.private_nudges import PrivateNudges, analyze_private_nudges
from ..analysis.sticker_features import (
    PrivateStickerFeatures, analyze_private_stickers,
)
from ..analysis.sticker_index import build_sticker_fact_index
from ..analysis.stickers import (
    StickerConversationReport,
    StickerData,
    StickerMedia,
    aggregate_stickers,
    collect_sticker_sends,
    count_sticker_messages,
)
from ..presentation.builders import prepare_expression_report
from ..presentation.language_sources import build_language_sources
from ..presentation.stickers import assemble_sticker_assets, build_echo_stickers, sticker_report_targets
from ..analysis.group_stickers import GroupStickerFeatures, analyze_group_stickers
from ..analyzer import (
    WordSpeakerSummary,
    count_word_speakers,
    top_word_speaker_summary,
    top_words,
)
from ..cleaner import clean_text
from ..message import ChatMessage
from ..message_quality_filter import apply_message_quality_filter
from ..filter_pipeline import FilterPipeline
from ..rich_message import ExpressionContent, NonTextContent, RichMessage
from ..presentation import (
    EchoReportView,
    build_echo_report_view,
    export_echo_report_html,
    export_echo_report_json,
)
from ..smart_profile import run_smart_profile
from ..tokenizer import iter_expression_placeholders, load_stopwords, tokenize
from .dto import (
    AnalysisDiagnosticCounts,
    AnalysisRequestDTO,
    AnalysisResultDTO,
    AnalysisStatus,
    ArtifactDTO,
    WordFrequencyDTO,
)
from .errors import (
    ArtifactGenerationFailed,
    InputPathNotFound,
    InvalidAnalysisRequest,
    NoMessagesInScope,
)
from .import_request import ImportRequest
from .import_service import ImportService
from .scope_filter import AnalysisScopeMode, filter_messages
from .shutdown_models import ShutdownStatus
from .sticker_media import resolve_sticker_media
from .errors import ApplicationServiceError


class AnalysisServiceClosing(ApplicationServiceError):
    code = 'application_closing'
    public_message = 'Echo 正在关闭。'


_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.identity")

_ECHO_ARTIFACT_FILENAMES = {
    "echo_report_json": "echo-report.json",
    "echo_report_html": "echo-report.html",
}
_ECHO_ARTIFACTS = (
    ArtifactDTO(kind="echo_report_json", filename="echo-report.json"),
    ArtifactDTO(kind="echo_report_html", filename="echo-report.html"),
)


class LegacyArtifactWriter(Protocol):
    """Writes the legacy CLI artifacts for one completed analysis run.

    The desktop build injects nothing, so those artifacts (and the chart
    libraries that produce them) stay out of the packaged app entirely.
    """

    def __call__(
        self,
        *,
        output_directory: Path,
        ranked_words: list[tuple[str, int]],
        speaker_summaries: list[WordSpeakerSummary],
        speaker_frequency_rows: list[tuple[str, str, int]],
        font_path: str | None,
    ) -> tuple[ArtifactDTO, ...]: ...


@dataclass(slots=True)
class _AnalyzedMessages:
    valid_text_count: int
    tokens: list[str]
    sender_tokens: list[tuple[str, list[str]]]
    message_tokens: list[list[str]]


class AnalysisApplicationService:
    """Coordinate one complete analysis use case without CLI behavior."""

    def __init__(
        self,
        *,
        legacy_word_artifacts: LegacyArtifactWriter | None = None,
    ) -> None:
        """Create the service; the desktop build injects no legacy writer."""
        self._legacy_word_artifacts = legacy_word_artifacts
        self._lifecycle_lock = threading.Lock()
        self._closing = False
        self._active = 0

    @property
    def is_idle(self) -> bool:
        with self._lifecycle_lock:
            return not self._closing and not self._active and self._legacy_word_artifacts is None

    def shutdown(self) -> ShutdownStatus:
        """Seal new analysis admission; do not wait for/certify active work."""
        with self._lifecycle_lock:
            self._closing = True
            return (ShutdownStatus.UNKNOWN if self._active or self._legacy_word_artifacts is not None
                    else ShutdownStatus.SUCCESS)

    def execute(self, request: AnalysisRequestDTO) -> AnalysisResultDTO:
        """Analyze supported local exports and return a privacy-safe result."""
        with self._lifecycle_lock:
            if self._closing:
                raise AnalysisServiceClosing()
            self._active += 1
        try:
            with timed_stage("total"):
                return self._execute(request)
        finally:
            with self._lifecycle_lock:
                self._active -= 1

    def export_sticker_report(
        self, result: AnalysisResultDTO, stickers: StickerData, output_directory: Path,
        *, cancelled=lambda: False,
    ) -> AnalysisResultDTO:
        """Reassemble retained display facts; never re-read or re-analyze a source."""
        with self._lifecycle_lock:
            if self._closing:
                raise AnalysisServiceClosing()
            self._active += 1
        try:
            view = result.echo_report_view
            original = result.stickers
            known_keys = {send.media_key for send in original.sends}
            if (view is None
                    or stickers.sends is not original.sends
                    or stickers.message_counts != original.message_counts
                    or any(item.media_key not in known_keys for item in stickers.media)
                    or len({item.media_key for item in stickers.media}) != len(stickers.media)):
                raise ValueError("invalid_sticker_report_data")
            with timed_stage("report_view_assets"):
                if view.stickers is not None:
                    view = replace(view, stickers=assemble_sticker_assets(view.stickers, stickers.media))
            _write_echo_view(view, output_directory, cancelled=cancelled)
            return replace(result, stickers=stickers, echo_report_view=view, artifacts=_ECHO_ARTIFACTS)
        finally:
            with self._lifecycle_lock:
                self._active -= 1

    def _execute(self, request: AnalysisRequestDTO) -> AnalysisResultDTO:
        _validate_request(request)
        with timed_stage("import"):
            outcome = ImportService().execute(
                ImportRequest(input_path=request.input_path)
            )
        _log_identity_diagnostics(outcome.messages)
        processed_message_count = outcome.processed_message_count
        parsed_messages = list(outcome.messages)
        with timed_stage("scope_filter"):
            scoped_messages = filter_messages(parsed_messages, request.scope)
        if (
            request.scope.mode is not AnalysisScopeMode.ALL
            and not scoped_messages
        ):
            raise NoMessagesInScope()
        if request.scope.mode is not AnalysisScopeMode.ALL:
            processed_message_count = len(scoped_messages)
        nudge_pairs = [(legacy, rich) for legacy, rich in outcome.rich_message_pairs
                       if rich.message_type == "nudge"]
        nudge_instances = {id(legacy) for legacy, _ in nudge_pairs}
        with timed_stage("smart_profile"):
            filtering_result = run_smart_profile(
                [message for message in scoped_messages if id(message) not in nudge_instances]
                if nudge_instances else scoped_messages
            )
        scoped_instances = (
            {id(message) for message in scoped_messages if id(message) in nudge_instances}
            if nudge_instances else set()
        )
        nudge_pairs = [(legacy, rich) for legacy, rich in nudge_pairs
                       if id(legacy) in scoped_instances]
        # Reuse sender exclusion semantics for both ends of an action. Templates
        # and lexical quality rules apply only to authored messages, not pats.
        sender_decisions = [decision for decision in filtering_result.applied_decisions
                            if decision.target_type == "sender" and decision.action == "ignore"]
        if nudge_pairs and sender_decisions:
            allowed_actors = {id(message) for message in FilterPipeline().apply_filter_decisions(
                [legacy for legacy, _ in nudge_pairs], sender_decisions,
            ).kept_messages}
            target_projections = [replace(legacy, sender_id=rich.relations[0].target_identity_id, sender="")
                                  for legacy, rich in nudge_pairs]
            allowed_targets = {id(message) for message in FilterPipeline().apply_filter_decisions(
                target_projections, sender_decisions,
            ).kept_messages}
            nudge_pairs = [(legacy, rich) for (legacy, rich), target in zip(nudge_pairs, target_projections)
                           if id(legacy) in allowed_actors and id(target) in allowed_targets]
        private_nudges = None
        if (nudge_pairs
                and _resolve_conversation_type(scoped_messages, request.conversation_kind) == "private"
                and all(message.platform == nudge_pairs[0][1].source
                        and message.conversation_id == nudge_pairs[0][1].conversation_id
                        for message in scoped_messages)):
            private_nudges = analyze_private_nudges(rich for _, rich in nudge_pairs)
        _LOGGER.info("[analysis] private_nudges scoped=%d eligible=%d self=%d peer=%d",
                     len(nudge_instances & scoped_instances), len(nudge_pairs),
                     private_nudges.self_count if private_nudges else 0,
                     private_nudges.peer_count if private_nudges else 0)
        with timed_stage("message_quality_filter"):
            quality_result = apply_message_quality_filter(
                filtering_result.kept_messages
            )
        kept_messages = quality_result.kept_messages
        import_positions = {id(message): pos for pos, message in enumerate(outcome.messages)}
        # Filters retain projection instances. The outcome keeps them alive,
        # so object identity cannot be reused during this analysis run.
        kept_instances = {id(message) for message in kept_messages}
        rich_by_instance = {
            id(legacy): rich
            for legacy, rich in outcome.rich_message_pairs
            if id(legacy) in kept_instances
        }
        with timed_stage("sticker_data"):
            # Both collectors must describe one message set: the kept messages
            # that still have Rich facts. Legacy-only messages stay uncounted
            # rather than being reported as covered denominator.
            sticker_scope = tuple(rich_by_instance.values())
            sticker_sends = collect_sticker_sends(sticker_scope)
            stickers = StickerData(
                sends=sticker_sends,
                message_counts=count_sticker_messages(sticker_scope),
            )
            # Aggregate once, and finish private discovery before ANY media I/O.
            # Positions describe removed/unpaired records without retaining their
            # content in the feature index or guessing by source message IDs.
            with timed_stage("sticker_aggregation"):
                sticker_reports = aggregate_stickers(stickers, sticker_scope)
            private_stickers = None
            group_stickers = None
            sticker_kind = _resolve_conversation_type(kept_messages, request.conversation_kind)
            if sticker_kind in {"private", "group"}:
                sticker_positions = tuple(import_positions[id(legacy)]
                                          for legacy, _ in outcome.rich_message_pairs if id(legacy) in kept_instances)
                # WeChat's native Type 1 declares text, unlike QQ's content-
                # derived message_type (which may omit malformed segments).
                # Pass existing typed rows as evidence, never inspect/export
                # their text or re-read the source. The index validates member,
                # scope, time and content types before clearing count gaps.
                non_sticker_messages = {
                    import_positions[id(legacy)]: rich
                    for legacy, rich in outcome.rich_message_pairs
                    if id(legacy) not in kept_instances and rich.source == "wechat"
                    and type(rich.source_type) is int and rich.source_type & 0xFFFFFFFF == 1
                    and rich.message_type == "text"
                }
                with timed_stage(f"{sticker_kind}_sticker_features"):
                    sticker_index = build_sticker_fact_index(
                        stickers, sticker_scope, reports=sticker_reports,
                        source_positions=sticker_positions,
                        non_sticker_messages=non_sticker_messages,
                        conversation_kind=sticker_kind,
                    )
                    if sticker_kind == "private":
                        private_stickers = analyze_private_stickers(sticker_index)
                    else:
                        group_stickers = analyze_group_stickers(sticker_index)
            with timed_stage("sticker_media_resolve"):
                media_sends = sticker_sends
                features = private_stickers if sticker_kind == "private" else group_stickers
                if features is not None and features.available and request.sticker_media_roots:
                    # Use the same display projection as the final report;
                    # explicit local roots must not recover the entire catalog.
                    selected = build_echo_stickers(sticker_reports, (), conversation_kind=sticker_kind,
                                                   private_features=private_stickers, group_features=group_stickers)
                    if any(member.send_count is not None for member in selected.members):
                        keys = {t.media_key for t in sticker_report_targets(selected)}
                        media_sends = tuple(s for s in sticker_sends if s.media_key in keys)
                sticker_media = resolve_sticker_media(media_sends, roots=request.sticker_media_roots)
            stickers = replace(stickers, media=sticker_media)
        diagnostic_counts = AnalysisDiagnosticCounts(
            raw_message_count=outcome.processed_message_count,
            imported_message_count=len(parsed_messages),
            scope_message_count=len(scoped_messages),
            filtered_message_count=len(kept_messages),
            analyzed_message_count=len(kept_messages),
        )
        with timed_stage("text_analysis"):
            analyzed = _analyze_kept_messages(
                kept_messages,
                request.stopwords_path,
                rich_by_instance,
            )
        with timed_stage("ExpressionAnalyzer.preflight"):
            expression_report = ExpressionAnalyzer().analyze(
                kept_messages,
                rich_by_instance=rich_by_instance,
            )
        has_expression_report = expression_report.expression_message_count > 0

        has_nontext = private_nudges is not None or any(
            any(isinstance(part, NonTextContent) for part in message.contents)
            for message in rich_by_instance.values()
        )
        ranked_words, status = _rank_words_and_select_status(
            analyzed,
            top=request.top,
            has_nontext=has_nontext,
            has_expression_report=has_expression_report,
        )
        _LOGGER.info(
            "[analysis] counts raw=%d imported=%d scoped=%d filtered=%d "
            "valid_text=%d tokens=%d expression_messages=%d status=%s",
            diagnostic_counts.raw_message_count, diagnostic_counts.imported_message_count,
            diagnostic_counts.scope_message_count, diagnostic_counts.filtered_message_count,
            analyzed.valid_text_count, len(analyzed.tokens), expression_report.expression_message_count,
            status.value,
        )
        if status in (AnalysisStatus.NO_VALID_TEXT, AnalysisStatus.NO_TOKENS):
            return AnalysisResultDTO(
                status=status,
                stickers=stickers,
                processed_message_count=processed_message_count,
                valid_text_count=analyzed.valid_text_count,
                diagnostic_counts=diagnostic_counts,
            )

        conversation_type = _resolve_conversation_type(
            kept_messages or [legacy for legacy, _ in nudge_pairs],
            request.conversation_kind,
        )
        try:
            with timed_stage("report_build"):
                reports = _build_reports(
                    kept_messages,
                    analyzed.sender_tokens,
                    speaker_names=request.speaker_names,
                    conversation_names=request.conversation_names,
                    conversation_type=conversation_type,
                    rich_by_instance=rich_by_instance,
                    expression_report=expression_report,
                    expression_source=outcome.result.platform,
                    stickers=stickers,
                    sticker_reports=sticker_reports,
                    private_stickers=private_stickers,
                    group_stickers=group_stickers,
                    private_nudges=private_nudges,
                )
            if ranked_words and self._legacy_word_artifacts is not None:
                with timed_stage("word_speaker_analysis"):
                    speaker_display_names = _speaker_display_names(reports)
                    word_sender_counts = count_word_speakers(
                        _text_sender_tokens(analyzed.sender_tokens)
                    )
                    speaker_summaries = _display_speaker_summaries(
                        top_word_speaker_summary(word_sender_counts),
                        speaker_display_names,
                    )
                    speaker_frequency_rows = [
                        (
                            summary.word,
                            speaker_display_names.get(sender, sender),
                            count,
                        )
                        for summary in speaker_summaries
                        for sender, count in sorted(
                            word_sender_counts[summary.word].items(),
                            key=lambda item: -item[1],
                        )
                    ]

            try:
                with timed_stage("artifact_export"):
                    legacy_artifacts = ()
                    if ranked_words and self._legacy_word_artifacts is not None:
                        legacy_artifacts = self._write_legacy_artifacts(
                            request,
                            ranked_words,
                            speaker_summaries,
                            speaker_frequency_rows,
                        )
                    echo_report_view = _export_echo_artifacts(
                        request,
                        reports,
                        viewer_speaker_key=_viewer_speaker_key(
                            kept_messages, request.viewer_speaker_key,
                        ),
                        conversation_kind=conversation_type,
                        expression_source=outcome.result.platform,
                        messages=kept_messages,
                        message_tokens=analyzed.message_tokens,
                        source_positions=[import_positions[id(message)] for message in kept_messages],
                        sticker_media=stickers.media,
                        write=request.export_echo_report,
                    )
            except (OSError, ValueError):
                raise ArtifactGenerationFailed() from None
        except Exception:
            if ranked_words:
                raise
            _LOGGER.warning(
                "content-only report generation failed",
                exc_info=True,
            )
            for filename in (
                _ECHO_ARTIFACT_FILENAMES["echo_report_json"],
                _ECHO_ARTIFACT_FILENAMES["echo_report_html"],
            ):
                try:
                    (request.output_directory / filename).unlink(missing_ok=True)
                except OSError:
                    pass
            raise

        _LOGGER.info(
            "[analysis] echo view prepared echo_view=%s conversation_type=%s exported=%s",
            echo_report_view is not None,
            conversation_type,
            request.export_echo_report,
        )
        return AnalysisResultDTO(
            status=status,
            processed_message_count=processed_message_count,
            valid_text_count=analyzed.valid_text_count,
            diagnostic_counts=diagnostic_counts,
            top_words=tuple(
                WordFrequencyDTO(word=word, count=count)
                for word, count in ranked_words
            ),
            artifacts=(*legacy_artifacts, *(_ECHO_ARTIFACTS if request.export_echo_report else ())),
            reports=reports,
            echo_report_view=echo_report_view,
            stickers=stickers,
        )

    def _write_legacy_artifacts(
        self,
        request: AnalysisRequestDTO,
        ranked_words: list[tuple[str, int]],
        speaker_summaries: list[WordSpeakerSummary],
        speaker_frequency_rows: list[tuple[str, str, int]],
    ) -> tuple[ArtifactDTO, ...]:
        """Write the legacy CLI artifacts, or nothing for the desktop build."""
        if self._legacy_word_artifacts is None:
            return ()
        return self._legacy_word_artifacts(
            output_directory=request.output_directory,
            ranked_words=ranked_words,
            speaker_summaries=speaker_summaries,
            speaker_frequency_rows=speaker_frequency_rows,
            font_path=request.font_path,
        )


def _rank_words_and_select_status(
    analyzed: _AnalyzedMessages,
    *,
    top: int,
    has_nontext: bool,
    has_expression_report: bool,
) -> tuple[list[tuple[str, int]], AnalysisStatus]:
    """Choose lexical, content-only, or empty output in priority order."""
    if not analyzed.tokens and has_nontext:
        status = (
            AnalysisStatus.EXPRESSION_ONLY
            if has_expression_report
            else AnalysisStatus.COMPLETED
        )
        return [], status
    if analyzed.valid_text_count == 0 and not has_expression_report:
        return [], AnalysisStatus.NO_VALID_TEXT
    if analyzed.tokens:
        with timed_stage("word_ranking"):
            ranked_words = top_words(analyzed.tokens, top)
        if ranked_words:
            return ranked_words, AnalysisStatus.COMPLETED
    if has_expression_report:
        return [], AnalysisStatus.EXPRESSION_ONLY
    return [], AnalysisStatus.NO_TOKENS


def _build_reports(
    messages: list[ChatMessage],
    sender_tokens: list[tuple[str, list[str]]],
    speaker_names: Mapping[str, str] | None = None,
    conversation_names: Mapping[str, str] | None = None,
    conversation_type: str = "unknown",
    rich_by_instance: Mapping[int, RichMessage] | None = None,
    expression_report: ExpressionReport | None = None,
    expression_source: str | None = None,
    stickers: StickerData | None = None,
    sticker_reports: tuple[StickerConversationReport, ...] | None = None,
    private_stickers: PrivateStickerFeatures | None = None,
    group_stickers: GroupStickerFeatures | None = None,
    private_nudges: PrivateNudges | None = None,
) -> AnalysisReports:
    """Run every extended analyzer over the messages kept for analysis.

    Display names are supplied by the caller and simply forwarded. The
    analysis core therefore stays unaware of QQ or WeChat naming rules, and
    omitting the mappings keeps the previous raw-identifier behavior.
    """
    # Lexical rankings and rates must exclude the separate expression channel.
    text_sender_tokens = _text_sender_tokens(sender_tokens)
    with timed_stage("ActivityAnalyzer"):
        activity = ActivityAnalyzer().analyze(messages)
    with timed_stage("UserProfileAnalyzer"):
        user_profiles = UserProfileAnalyzer().analyze(
            messages,
            sender_tokens=text_sender_tokens,
            speaker_names=speaker_names,
            weekday_calendar_days=tuple(point.calendar_days for point in activity.weekday_counts),
        )
    with timed_stage("ConversationAnalyzer"):
        conversations = ConversationAnalyzer().analyze(
            messages,
            conversation_names=conversation_names,
        )
    with timed_stage("conversation_sessions"):
        conversation_sessions = analyze_conversation_sessions(messages)
    with timed_stage("DistinctiveWordAnalyzer"):
        distinctive_words = DistinctiveWordAnalyzer().analyze(
            text_sender_tokens,
            conversation_type=conversation_type,
        )
    with timed_stage("PrivateLanguageAnalyzer"):
        private_language = PrivateLanguageAnalyzer().analyze(
            text_sender_tokens,
            conversation_type=conversation_type,
        )
    _LOGGER.info(
        "[analysis] language_samples group_availability=%s group_eligible_members=%d private_shared_words=%d",
        distinctive_words.availability.value, distinctive_words.eligible_member_count,
        len(private_language.shared_words),
    )
    with timed_stage("ExpressionAnalyzer.report"):
        expression = expression_report
        if expression is None:
            expression = ExpressionAnalyzer().analyze(
                messages,
                rich_by_instance=rich_by_instance,
            )
    if sticker_reports is None:
        with timed_stage("sticker_aggregation"):
            sticker_reports = aggregate_stickers(stickers or StickerData(), (rich_by_instance or {}).values())
    return AnalysisReports(
        activity=activity,
        user_profiles=user_profiles,
        conversations=conversations,
        conversation_sessions=conversation_sessions,
        distinctive_words=distinctive_words,
        private_language=private_language,
        stickers=sticker_reports,
        private_stickers=private_stickers,
        group_stickers=group_stickers,
        private_nudges=private_nudges,
        expression=prepare_expression_report(
            expression,
            expression_source=(
                expression_source
                if expression_source is not None
                else (messages[0].platform if messages else None)
            ),
        ),
    )


def _validate_request(request: AnalysisRequestDTO) -> None:
    if (
        not isinstance(request.top, int)
        or isinstance(request.top, bool)
        or request.top <= 0
    ):
        raise InvalidAnalysisRequest()
    if not request.input_path.exists():
        raise InputPathNotFound()


def _resolve_conversation_type(
    messages: list[ChatMessage],
    requested_type: str,
) -> str:
    """Use explicit application context, then unanimous message semantics."""
    if requested_type in {"group", "private"}:
        return requested_type
    message_types = {message.conversation_type for message in messages}
    if message_types == {"group"}:
        return "group"
    if message_types == {"private"}:
        return "private"
    return "unknown"


def _analyze_kept_messages(
    messages: list[ChatMessage],
    stopwords_path: Path,
    rich_by_instance: Mapping[int, RichMessage] | None = None,
) -> _AnalyzedMessages:
    valid_text_count = 0
    tokens: list[str] = []
    sender_tokens: list[tuple[str, list[str]]] = []
    per_message_tokens: list[list[str]] = []
    stopwords: set[str] | None = None

    for message in messages:
        cleaned_text = clean_text(message.text, platform=message.platform)
        message_tokens = []
        if cleaned_text:
            if stopwords is None:
                stopwords = load_stopwords(str(stopwords_path))
            message_tokens = tokenize(cleaned_text, stopwords=stopwords)
        if cleaned_text:
            valid_text_count += 1
        tokens.extend(message_tokens)
        per_message_tokens.append(message_tokens)
        expression_tokens = _expression_tokens(
            message,
            rich_by_instance or {},
        )
        combined_tokens = [*message_tokens, *expression_tokens]
        if combined_tokens and is_chat_participant(message):
            sender_tokens.append(
                (stable_sender_key(message), combined_tokens)
            )

    return _AnalyzedMessages(
        valid_text_count=valid_text_count,
        tokens=tokens,
        sender_tokens=sender_tokens,
        message_tokens=per_message_tokens,
    )


def _expression_tokens(
    message: ChatMessage,
    rich_by_instance: Mapping[int, RichMessage],
) -> list[str]:
    """Return source-neutral expression tokens for the Voices pipeline."""
    tokens = [
        f"expression:{emoji}"
        for emoji in iter_emoji_clusters(message.text)
    ]
    tokens.extend(
        f"expression:{placeholder}"
        for placeholder in iter_expression_placeholders(message.text)
    )
    rich_message = rich_by_instance.get(id(message))
    if rich_message is not None:
        tokens.extend(
            f"expression:{content.expression_key}"
            for content in rich_message.contents
            if isinstance(content, ExpressionContent)
        )
    return tokens


def _text_sender_tokens(
    sender_tokens: list[tuple[str, list[str]]],
) -> list[tuple[str, list[str]]]:
    return [
        (
            speaker_key,
            [
                token
                for token in message_tokens
                if not token.startswith("expression:")
            ],
        )
        for speaker_key, message_tokens in sender_tokens
    ]


def _speaker_display_names(reports: AnalysisReports) -> dict[str, str]:
    """Map stable speaker keys to resolved display names for artifacts."""
    if reports.user_profiles is None:
        return {}
    return {
        profile.speaker_key or profile.speaker: profile.resolved_display_name
        for profile in reports.user_profiles.profiles
    }


def _display_speaker_summaries(
    summaries: list[WordSpeakerSummary],
    speaker_display_names: Mapping[str, str],
) -> list[WordSpeakerSummary]:
    """Translate stable speaker keys into display names in summaries."""
    if not speaker_display_names:
        return summaries
    return [
        replace(
            summary,
            top_speaker=speaker_display_names.get(
                summary.top_speaker,
                summary.top_speaker,
            ),
        )
        for summary in summaries
    ]


def _viewer_speaker_key(
    messages: list[ChatMessage],
    explicit: str | None,
) -> str | None:
    """Resolve the Echo viewer key only from reliable self markers."""
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    for message in messages:
        if message.is_self is True:
            return stable_sender_key(message)
    return None


def _log_identity_diagnostics(messages: list[ChatMessage]) -> None:
    """Log anonymized identity acceptance state for one imported source."""
    if not messages:
        return
    source = messages[0].platform or "unknown"
    conversation_type = next(
        (
            message.conversation_type
            for message in messages
            if message.conversation_type in ("private", "group")
        ),
        "unknown",
    )
    self_resolved = any(
        message.is_self is True or message.is_self is False
        for message in messages
    )
    resolved_senders = sum(
        1
        for message in messages
        if isinstance(message.sender_id, str) and message.sender_id.strip()
    )
    if resolved_senders == len(messages):
        sender_coverage = "resolved"
    elif resolved_senders:
        sender_coverage = "partial"
    else:
        sender_coverage = "unknown"
    _LOGGER.info(
        "[identity] source=%s conversation_type=%s "
        "self_identity=%s sender_identity_coverage=%s",
        source,
        conversation_type,
        "resolved" if self_resolved else "unknown",
        sender_coverage,
    )


def _export_echo_artifacts(
    request: AnalysisRequestDTO,
    reports: AnalysisReports,
    *,
    viewer_speaker_key: str | None,
    conversation_kind: str,
    expression_source: str | None,
    messages: list[ChatMessage],
    message_tokens: list[list[str]],
    source_positions: list[int],
    sticker_media: tuple[StickerMedia, ...] = (),
    write: bool = True,
) -> EchoReportView:
    """Write the Echo JSON and self-contained HTML report artifacts."""
    output_directory = request.output_directory
    with timed_stage("report_view_assets"):
        view = build_echo_report_view(
            reports,
            viewer_speaker_key=viewer_speaker_key,
            conversation_kind=conversation_kind,
            expression_source=expression_source,
            sticker_media=sticker_media,
        )
        view = replace(view, language_sources=build_language_sources(
            view, messages, message_tokens, source_positions=source_positions,
        ))
    if write:
        _write_echo_view(view, output_directory)
    return view


def _write_echo_view(view: EchoReportView, output_directory: Path, *, cancelled=lambda: False) -> None:
    """Shared JSON/HTML export for analysis and explicitly enriched snapshots."""
    with timed_stage("report_json_export"):
        export_echo_report_json(
            view,
            str(output_directory / _ECHO_ARTIFACT_FILENAMES["echo_report_json"]),
            cancelled=cancelled,
        )
    with timed_stage("report_html_export"):
        export_echo_report_html(
            view,
            str(output_directory / _ECHO_ARTIFACT_FILENAMES["echo_report_html"]),
            cancelled=cancelled,
        )
    logging.getLogger("qq_chat_analyzer.desktop.analysis_diagnostics").info(
        "[sticker-export-counts] html_payload_memories=%d",
        len(view.stickers.memories) if view.stickers else 0,
    )
