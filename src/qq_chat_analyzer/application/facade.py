"""One stable application entry point for user-facing callers.

This module is the seam a future GUI talks to. It exists so that a window,
a widget, or any other presentation-side caller never has to know that
providers, import services, export files, or analyzer internals exist.

Deliberate boundaries:

* No provider is constructed here. Every collaborator is injected, so tests
  can supply stubs and the desktop wiring stays in one place.
* No analysis happens here. ``AnalysisApplicationService`` owns that, and the
  presentation builder owns formatting. This layer only decides *which*
  collaborator runs and in *what* order.
* No statistics are recomputed. Numbers travel from the analysis reports into
  the dashboard view untouched.
* Intermediate export files are an implementation detail. Generated Echo HTML
  is the exception: its exact local path is retained for the desktop caller.

Everything that escapes this layer is either a plain view model or a
:class:`FacadeError` carrying a stable ``code`` and a user-safe message.
"""

from __future__ import annotations

import logging
import re
import shutil
import stat
import threading
from time import monotonic as _monotonic, perf_counter as _perf_counter
from tempfile import TemporaryDirectory
from collections.abc import Iterable, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol, runtime_checkable
from uuid import uuid4

from ..resources import resources_dir, user_data_dir
from .shutdown_models import ShutdownResult, ShutdownStatus, ShutdownStepResult
from ..analysis.timestamps import to_epoch_seconds
from ..presentation import (
    DashboardView,
    EchoReportView,
    build_dashboard_view,
    build_echo_report_view,
)
from ..presentation.expression_assets import expression_asset_data_uri
from ..presentation.share.builder import ShareCardData, build_share_card_data
from ..presentation.share.renderer import (
    ShareImageRenderError,
    render_share_html_to_png,
)
from ..presentation.share.template import build_share_card_html
from .analysis_phase import AnalysisPhase, PhaseCallback
from .dto import AnalysisRequestDTO, AnalysisResultDTO
from .errors import ApplicationServiceError
from .connection_models import ConnectionSnapshot
from .qq.qq_connection_manager import QQConnectionManager
from .qq.qq_connection_service import (
    QQConnectionService,
    QQConnectionStatus,
)
from .qq.qq_environment_config import QQEnvironmentConfig
from .qq.qq_setup_service import QQSetupStatus
from .echo_report_export import (
    ECHO_REPORT_HTML_NAME,
    _require_no_reparse_points,
    package_echo_report,
)
from .report_package_catalog import (
    ReportPackageCatalog,
    ReportPackageDeletionResult,
    ReportPackageListing,
    ReportStorageUsage,
)
from .report_package_metadata import build_report_metadata
from .update_check_service import UpdateChecker, UpdateCheckResult, UpdateCheckService
from .installable_update_service import (
    InstallableUpdater, InstallableUpdateResult, InstallableUpdateService, InstallHandoffResult,
)
from .wechat.wechat_connection_service import WeChatConnectionStatus
from .wechat.wechat_connection_progress import WeChatConnectionProgress
from .wechat.wechat_environment_config import WeChatEnvironmentConfig
from .wechat.wechat_export_import_service import WeChatExportImportRequest
from .wechat.wechat_setup_service import WeChatSetupStatus
from .scope_filter import AnalysisScope, AnalysisScopeMode, resolve_scope


_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.facade")
_ANALYSIS_OUTPUT_NAME = re.compile(r"chat-analyzer-output-[0-9a-f]{8}\Z")


class _RetainedReportDirectory:
    """Own one report directory while preserving its inherited ACL."""

    def __init__(self, parent: Path) -> None:
        _require_no_reparse_points(parent)
        self._parent = parent.resolve()
        while True:
            directory = self._parent / f"chat-analyzer-output-{uuid4().hex[:8]}"
            try:
                directory.mkdir()
            except FileExistsError:
                continue
            self.name = str(directory)
            break

    def cleanup(self) -> None:
        try:
            _remove_owned_analysis_output(Path(self.name), self._parent)
        except FileNotFoundError:
            pass
        except Exception:
            _LOGGER.exception("Analysis scratch could not be cleaned: %s", self.name)


def _remove_owned_analysis_output(directory: Path, root: Path) -> None:
    _require_no_reparse_points(root)
    if directory.parent != root or not _ANALYSIS_OUTPUT_NAME.fullmatch(directory.name):
        raise ValueError("Analysis scratch is outside its ownership boundary.")
    _require_no_reparse_points(directory)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("Analysis scratch is not a directory.")
    _require_safe_scratch_tree(directory)
    _require_no_reparse_points(directory)
    current = directory.lstat()
    if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
        raise ValueError("Analysis scratch changed during cleanup.")
    shutil.rmtree(directory)


def _require_safe_scratch_tree(directory: Path) -> None:
    for child in directory.iterdir():
        _require_no_reparse_points(child)
        if stat.S_ISDIR(child.lstat().st_mode):
            _require_safe_scratch_tree(child)


def _cleanup_stale_analysis_outputs(root: Path) -> None:
    """Recover only direct scratch children; cleanup must not prevent startup."""
    try:
        _require_no_reparse_points(root)
        root = root.resolve()
        if not root.exists():
            return
        candidates = [
            child for child in root.iterdir() if _ANALYSIS_OUTPUT_NAME.fullmatch(child.name)
        ]
        candidates.sort(key=lambda child: child.name)
    except Exception:
        _LOGGER.exception("Stale analysis scratch could not be enumerated: %s", root)
        return
    for directory in candidates:
        try:
            _remove_owned_analysis_output(directory, root)
        except Exception:
            _LOGGER.exception("Stale analysis scratch could not be cleaned: %s", directory)


def _report_progress(
    progress: Callable[[str], None] | None,
    message: str,
) -> None:
    """Publish a facade-owned analysis stage when a caller is listening."""
    if progress is not None:
        progress(message)


def _publish_phase(
    on_phase: PhaseCallback | None,
    phase: AnalysisPhase,
) -> None:
    """Publish one structured phase when a caller is listening.

    This is additive next to :func:`_report_progress`: the Chinese status text
    stays the human-facing channel, the phase enum is the machine-facing one.
    Any exception the callback raises propagates unchanged, so the caller that
    injected it owns that failure and the resources around it still unwind.
    """
    if on_phase is not None:
        on_phase(phase)


DEFAULT_TOP = 50
DEFAULT_PROFILE = "default"

_PROFILE_STOPWORD_FILES = {
    "default": "stopwords.txt",
    "topic": "stopwords_topic.txt",
    "culture": "stopwords_culture.txt",
}

#: Each ordered shutdown step gets its own bounded window.  A step that
#: overruns it is abandoned so the steps after it still run - in particular
#: QQ runtime termination - which keeps the whole shutdown protocol finite.
DEFAULT_SHUTDOWN_STEP_SECONDS = 10.0

_SHUTDOWN_STEP_THREAD_PREFIX = "echo-shutdown-step-"
_SHUTDOWN_STEP_DIRECT_DB = "direct_db_cleanup"
_SHUTDOWN_STEP_RETAINED_OUTPUT = "retained_output_cleanup"
_SHUTDOWN_STEP_QQ_RUNTIME = "qq_runtime_termination"

#: Extra window the Direct DB step gets on top of the bounded budget the
#: service declares for itself (drain window plus recover readiness budget).
#: Without it a normal bounded cleanup is abandoned, the runtime is stopped
#: underneath it, and the process exit kills it mid-recover.
_DIRECT_DB_STEP_MARGIN_SECONDS = 5.0

class ChatSource(str, Enum):
    """Every chat origin a caller may choose from."""

    QQ = "qq"
    WECHAT = "wechat"


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """One selectable conversation, normalised across every source."""

    source: ChatSource
    session_id: str
    display_name: str
    session_type: str = "other"
    message_count: int | None = None
    message_available: bool = True
    unavailable_reason: str | None = None
    last_message_time: int | None = None


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """One data source a caller may pick, plus whether it is usable."""

    source: ChatSource
    display_name: str
    available: bool
    description: str = ""


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    """Everything a caller may tune for one analysis run.

    ``scope_mode`` selects the analysis window. ``start_time`` and
    ``end_time`` are used for a custom range. Explicit legacy bounds are also
    treated as custom so existing callers retain their behavior.
    """

    start_time: Any = None
    end_time: Any = None
    scope_mode: AnalysisScopeMode = AnalysisScopeMode.ALL
    top: int = DEFAULT_TOP
    profile: str = DEFAULT_PROFILE
    output_directory: Path | None = None
    font_path: str | None = None

    def with_output_directory(self, directory: Path) -> "AnalysisConfig":
        """Return a copy that writes artifacts into ``directory``."""
        return replace(self, output_directory=directory)


class FacadeError(Exception):
    """The single error type a caller outside this layer has to handle."""

    def __init__(
        self,
        code: str,
        public_message: str,
        *,
        source: ChatSource | None = None,
    ) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.source = source


class UnknownChatSource(FacadeError):
    """Raised when a caller asks for a source this layer cannot serve."""

    def __init__(self, source: Any) -> None:
        super().__init__(
            code="unknown_source",
            public_message=(
                "\u4e0d\u652f\u6301\u7684\u6570\u636e\u6765\u6e90"
                f"\uff1a{source}\u3002"
            ),
        )


class SourceUnavailable(FacadeError):
    """Raised when a source was requested but no service was wired for it."""

    def __init__(self, source: ChatSource) -> None:
        super().__init__(
            code="source_unavailable",
            public_message=_SOURCE_UNAVAILABLE_MESSAGES[source],
            source=source,
        )


_SOURCE_UNAVAILABLE_MESSAGES = {
    ChatSource.QQ: (
        "QQ \u6570\u636e\u6e90\u6682\u4e0d\u53ef\u7528\u3002"
    ),
    ChatSource.WECHAT: (
        "\u5fae\u4fe1\u6570\u636e\u6e90\u5c1a\u672a\u914d\u7f6e\u3002"
    ),
}

_SOURCE_DISPLAY_NAMES = {
    ChatSource.QQ: "QQ",
    ChatSource.WECHAT: "\u5fae\u4fe1",
}


@runtime_checkable
class SessionListingService(Protocol):
    """Shared shape of the two export services used for listing."""

    def list_sessions(self) -> list[Any]:  # pragma: no cover - contract only
        ...


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    """What one finished analysis hands back to a caller.

    ``view`` is what a GUI renders. ``result`` stays available for callers
    that need the privacy-safe DTO, and ``session`` records which
    conversation produced the view.
    """

    view: DashboardView
    result: AnalysisResultDTO
    source: ChatSource
    session: SessionInfo | None = None
    artifact_directory: Path | None = field(default=None, repr=False)
    report_path: Path | None = field(default=None, repr=False)
    report_directory: Path | None = field(default=None, repr=False)
    echo_report_view: EchoReportView | None = field(default=None, repr=False)
    report_generated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class _SessionExport:
    """Internal export path for one session."""

    payload_path: Path
    session: SessionInfo | None = None
    conversation_id: str | None = None


class ChatAnalyzerFacade:
    """Coordinate sources, analysis, and presentation behind one surface."""

    def __init__(
        self,
        *,
        qq_service: Any = None,
        qq_connection_service: Any = None,
        qq_setup_service: Any = None,
        qq_connection_manager: Any = None,
        qq_auth_bridge: Any = None,
        qq_process_registry: Any = None,
        qq_runtime_session: Any = None,
        wechat_service: Any = None,
        wechat_connection_service: Any = None,
        wechat_setup_service: Any = None,
        source_builders: (
            dict[ChatSource, Callable[[], Any]] | None
        ) = None,
        analysis_service: Any = None,
        presentation_builder: Any = None,
        report_package_catalog: Any = None,
        update_check_service: UpdateChecker | None = None,
        installable_update_service: InstallableUpdater | None = None,
        stopwords_directory: Path | None = None,
        shutdown_step_seconds: float = DEFAULT_SHUTDOWN_STEP_SECONDS,
    ) -> None:
        self._services: dict[ChatSource, Any] = {
            ChatSource.QQ: qq_service,
            ChatSource.WECHAT: wechat_service,
        }
        self._qq_connection_service = qq_connection_service
        self._qq_setup_service = qq_setup_service
        self._qq_connection_manager = qq_connection_manager
        self._qq_auth_bridge = qq_auth_bridge
        self._qq_process_registry = qq_process_registry
        self._qq_runtime_session = qq_runtime_session
        self._wechat_connection_service_value = wechat_connection_service
        self._wechat_setup_service_value = wechat_setup_service
        self._source_builders = dict(source_builders or {})
        self._built_sources: dict[ChatSource, Any] = {}
        self._analysis_service = analysis_service
        self._presentation_builder = presentation_builder
        self._report_package_catalog = report_package_catalog or ReportPackageCatalog()
        self._update_check_service = (
            update_check_service if update_check_service is not None else UpdateCheckService()
        )
        self._installable_update_service = (
            installable_update_service if installable_update_service is not None
            else InstallableUpdateService()
        )
        self._stopwords_directory = stopwords_directory or resources_dir()
        self._retained_output_directory: _RetainedReportDirectory | None = None
        self._scratch_recovery_done = False
        self._shutdown_step_seconds = shutdown_step_seconds
        self._shutdown_lock = threading.Lock()
        self._shutdown_result: ShutdownResult | None = None
        self._sources_closing = threading.Event()
        self._source_publication_lock = threading.Lock()

    def check_for_updates(self, *, manual: bool = False) -> UpdateCheckResult:
        """Check on a worker; construction/startup never initiates a request."""
        try:
            return self._update_check_service.check(manual=manual)
        except Exception as exc:
            raise FacadeError(
                code="update_check_failed",
                public_message="暂时无法检查更新，请稍后手动重试。",
            ) from exc

    def check_installable_update(self) -> InstallableUpdateResult:
        """Worker-only Velopack feed check, separate from release-page checks."""
        try:
            return self._installable_update_service.check()
        except Exception as exc:
            raise FacadeError(code="installable_update_check_failed",
                              public_message="暂时无法检查可安装更新，请稍后重试。") from exc

    def download_update(
        self, *, progress: Callable[[int], None] | None = None,
    ) -> InstallableUpdateResult:
        """Worker-only download. Callbacks must marshal into the GUI thread."""
        try:
            return self._installable_update_service.download(progress=progress)
        except Exception as exc:
            raise FacadeError(code="update_download_failed",
                              public_message="更新下载未完成，请稍后重试。") from exc

    def get_update_status(self) -> InstallableUpdateResult:
        """Read an immutable in-memory snapshot; never grants apply permission."""
        try:
            return self._installable_update_service.get_status()
        except Exception as exc:
            raise FacadeError(code="update_status_failed",
                              public_message="暂时无法读取更新状态。") from exc

    def prepare_update_install(self) -> InstallHandoffResult:
        """Worker-only preparation; 0.2.0 supports never-connected idle sessions only.

        This read-only preflight is advisory, not a replacement for final owner
        evidence. It neither shuts down resources nor starts an installer.
        """
        from .source_bundle_builder import SourceBundleBuilder
        from .analysis_service import AnalysisApplicationService
        used = bool(self._built_sources) or any(value is not None for value in (
            *self._services.values(), self._qq_connection_service, self._qq_setup_service,
            self._qq_connection_manager, self._qq_auth_bridge,
            self._wechat_connection_service_value, self._wechat_setup_service_value))
        if (used or self._sources_closing.is_set()
                or any(type(builder) is not SourceBundleBuilder or not builder.is_unused
                       for builder in self._source_builders.values())
                or (self._analysis_service is not None and
                    (type(self._analysis_service) is not AnalysisApplicationService or not self._analysis_service.is_idle))):
            raise FacadeError(code='update_idle_required', public_message=
                '当前仅支持未连接且没有分析任务的空闲安装。请先完成任务、断开连接并正常退出，再重新打开 Echo 安装更新。')
        try:
            return self._installable_update_service.prepare_install()
        except Exception as exc:
            raise FacadeError(code='update_prepare_failed', public_message='更新包复验失败，请重新检查并下载。') from exc

    def handoff_update_install(self, token: str, result: ShutdownResult) -> InstallHandoffResult:
        """Existing desktop exit owner calls this AFTER its final protocol result.

        Final GUI evidence must contain the exact cached resource-owner result;
        caller-supplied SUCCESS values cannot stand in for a real shutdown.
        """
        if (not isinstance(result, ShutdownResult) or not result.can_apply_update
                or self._shutdown_result is None
                or tuple(step for step in result.steps if step.name != 'gui_workers')
                   != self._shutdown_result.steps):
            return InstallHandoffResult('denied', public_message='安全退出证据不完整，更新未安装。')
        return self._installable_update_service.handoff(token, result)

    @property
    def _wechat_connection_service(self) -> Any:
        if self._wechat_connection_service_value is None:
            bundle = self._source_bundle(ChatSource.WECHAT)
            self._wechat_connection_service_value = getattr(
                bundle,
                "connection",
                None,
            )
        return self._wechat_connection_service_value

    @property
    def _wechat_setup_service(self) -> Any:
        if self._wechat_setup_service_value is None:
            bundle = self._source_bundle(ChatSource.WECHAT)
            self._wechat_setup_service_value = getattr(bundle, "setup", None)
        return self._wechat_setup_service_value

    # ------------------------------------------------------------- discovery

    def list_sources(self) -> tuple[SourceInfo, ...]:
        """Describe every source, flagging which ones are wired up."""
        return tuple(
            SourceInfo(
                source=source,
                display_name=_SOURCE_DISPLAY_NAMES[source],
                available=self._is_available(source),
                description=(
                    ""
                    if self._is_available(source)
                    else _SOURCE_UNAVAILABLE_MESSAGES[source]
                ),
            )
            for source in ChatSource
        )

    def list_sessions(self, source: ChatSource) -> list[SessionInfo]:
        """Return the conversations one source offers, normalised."""
        chat_source = _coerce_source(source)
        service = self._require_service(chat_source)
        with _translated_errors(chat_source):
            if chat_source is ChatSource.QQ:
                raw_sessions = service.list_sessions()
            else:
                raw_sessions = service.list_sessions()

        return [
            _to_session_info(chat_source, raw_session)
            for raw_session in raw_sessions or ()
        ]


    def get_connection_status(
        self,
        source: ChatSource,
    ) -> QQConnectionStatus | WeChatConnectionStatus:
        """Return the user-facing connection state for one source."""
        chat_source = _coerce_source(source)
        service = self._require_connection_service(chat_source)
        with _translated_errors(chat_source):
            return service.check_status()

    def get_qq_setup_status(self) -> QQSetupStatus:
        """Report whether the QQ environment config is usable."""
        service = self._require_qq_setup_service()
        with _translated_errors(ChatSource.QQ):
            return service.check_setup()

    def get_qq_environment_config(self) -> QQEnvironmentConfig:
        """Return the effective QQ environment config for prefill.

        The GUI uses this only to prefill the setup dialog, never to read or
        write the configuration itself.
        """
        service = self._require_qq_setup_service()
        with _translated_errors(ChatSource.QQ):
            return service.get_environment_config()

    def setup_qq_environment(self, config: QQEnvironmentConfig) -> Any:
        """Save a QQ environment config and re-check the connection."""
        service = self._require_qq_setup_service()
        with _translated_errors(ChatSource.QQ):
            return service.save_environment(config)

    def set_qq_install_path(self, path: str | Path) -> Any:
        """Persist a user-selected QQ.exe path as the first discovery source.

        The GUI uses this only after automatic discovery failed; the next
        connect attempt will prefer the saved path.
        """
        candidate = Path(path)
        if not candidate.is_file():
            raise FacadeError(
                code="qq_install_path_invalid",
                public_message="请选择有效的 QQ.exe 文件。",
            )
        service = self._require_qq_setup_service()
        with _translated_errors(ChatSource.QQ):
            config = service.get_environment_config()
            if config is None:
                config = QQEnvironmentConfig()
            return service.save_environment(
                replace(config, qq_install_path=candidate, qq_install_path_explicit=True)
            )

    def get_qq_runtime_status(self) -> Any:
        """Return the current QQ runtime lifecycle status."""
        service = self._require_qq_setup_service()
        with _translated_errors(ChatSource.QQ):
            return service.get_runtime_status()

    def start_qq_runtime(self) -> Any:
        """Start the configured QQ runtime and wait until ready."""
        service = self._require_qq_setup_service()
        with _translated_errors(ChatSource.QQ):
            return service.start_runtime()

    def get_qq_connection_snapshot(self) -> ConnectionSnapshot:
        """Report the QQ connection lifecycle without starting anything.

        This is what the GUI shows when a user selects QQ. The manager never
        raises, so an unreachable service becomes a snapshot rather than an
        error the page has to interpret.
        """
        return self._require_qq_connection_manager().get_snapshot()

    def connect_qq(self) -> ConnectionSnapshot:
        """Connect QQ through the single authorization runtime path.

        Redirected to :meth:`start_qq_auth_flow` so the Echo NapCat launcher
        owns login and its process tree.
        """
        return self.start_qq_auth_flow()

    def start_qq_auth_flow(
        self,
        progress: Callable[[str], None] | None = None,
        *,
        cancel_event: threading.Event | None = None,
    ) -> ConnectionSnapshot:
        """Start QQ authorization and return the resulting lifecycle state.

        The GUI calls this instead of a raw connect: the auth bridge starts
        the runtime's own login flow and the caller keeps polling
        :meth:`get_qq_connection_snapshot` until it reports ``CONNECTED``.
        """
        bridge = self._require_qq_auth_bridge()
        if cancel_event is None or not cancel_event.is_set():
            with _translated_errors(ChatSource.QQ):
                service = self._qq_service_if_present()
                prepare = getattr(service, "prepare_reconnect", None)
                connection = self._optional_qq_connection_service()
                reconnect = getattr(connection, "reconnect", None)
                # Only the two in-memory resets share admission's lock. The
                # runtime login flow below deliberately runs outside it.
                with ExitStack() as resets:
                    guard = getattr(service, "reconnect_guard", None)
                    if callable(guard):
                        resets.enter_context(guard())
                    if callable(prepare):
                        prepare()
                    if callable(reconnect):
                        reconnect()
        if cancel_event is None:
            return bridge.start_auth_flow(progress=progress)
        return bridge.start_auth_flow(progress=progress, cancel_event=cancel_event)

    def cancel_qq_auth_flow(self, cancel_event: threading.Event) -> None:
        """Clean the cancelled QQ attempt off the GUI thread, without touching a newer one."""
        self._require_qq_auth_bridge().cancel_auth_flow(cancel_event)

    def is_qq_qrcode_ready(self) -> bool:
        """Return whether the QQ login QR belongs to the current session."""
        return self._require_qq_auth_bridge().is_qrcode_ready()

    def get_qq_qrcode_path(self) -> Path | None:
        """Return the auth bridge's fresh QR path without deriving GUI paths."""
        return self._require_qq_auth_bridge().get_qrcode_path()

    def shutdown_qq_runtime(self) -> None:
        """Stop only QQ processes LCA started.

        This is the application exit hook: the registry records the
        NapCat launcher PIDs LCA created, so a user's own QQ client is never touched.
        Cleanup is best-effort and never raises.
        """
        registry = self._require_qq_process_registry()
        try:
            registry.terminate_all()
        except Exception:
            pass

    def disconnect_qq(self) -> ConnectionSnapshot:
        """Log out the current QQ account and stop LCA-owned runtime sessions.

        The runtime files and stored QQ configuration are preserved; only the
        active login session is stopped so a different account can scan a
        fresh QR code.
        """
        return self._require_qq_auth_bridge().disconnect()

    def disconnect_wechat(self) -> WeChatConnectionStatus | None:
        """Log out the current WeChat account without deleting local data.

        The database key is released from the stored environment and the
        provider cache is dropped; the data root and database files stay
        untouched.
        """
        service = self._require_setup_service()
        with _translated_errors(ChatSource.WECHAT):
            return service.disconnect()

    def get_wechat_setup_status(self) -> WeChatSetupStatus:
        """Report whether the WeChat environment config is usable."""
        from .source_bundle_builder import SourceBundleBuilder
        builder = self._source_builders.get(ChatSource.WECHAT)
        if (self._wechat_setup_service_value is None
                and ChatSource.WECHAT not in self._built_sources
                and type(builder) is SourceBundleBuilder and builder.has_setup_reader):
            with _translated_errors(ChatSource.WECHAT):
                return builder.read_setup_status()
        service = self._require_setup_service()
        with _translated_errors(ChatSource.WECHAT):
            return service.check_setup()

    def detect_wechat_data_root(self) -> Path | None:
        """Best-effort detect the local WeChat data directory.

        The GUI uses this to prefill the setup dialog and to start the
        one-click connect flow. The detected directory is handed back as a
        config value; the GUI never probes the filesystem itself.
        """
        service = self._require_setup_service()
        with _translated_errors(ChatSource.WECHAT):
            return service.detect_wechat_data_root()

    def detect_wechat_data_roots(self) -> list[Path]:
        """Return every valid WeChat data directory detected locally.

        When several accounts or storage locations exist, the caller shows
        the list and lets the user choose; the application layer never picks
        one automatically.
        """
        service = self._require_setup_service()
        with _translated_errors(ChatSource.WECHAT):
            return service.detect_wechat_data_roots()

    def setup_wechat_environment(
        self,
        config: WeChatEnvironmentConfig,
    ) -> WeChatConnectionStatus | None:
        """Save a WeChat environment config and re-check the connection.

        The GUI hands the collected settings here instead of writing the
        config file itself, so persistence and provider refresh stay in
        the application layer.
        """
        service = self._require_setup_service()
        with _translated_errors(ChatSource.WECHAT):
            return service.save_environment(config)

    def verify_wechat_database(self) -> None:
        """Verify the current key can read the selected WeChat database.

        The GUI calls this immediately before loading sessions. A key that
        cannot open a structurally valid ``session.db`` becomes
        ``wechat_database_unreadable`` instead of a generic read failure, so
        the caller can return the user to the data-location flow. No chat
        content is read.
        """
        service = self._require_setup_service()
        with _translated_errors(ChatSource.WECHAT):
            return service.verify_connection()

    def acquire_wechat_db_key(
        self,
        progress: Callable[[WeChatConnectionProgress], None] | None = None,
        *, cancel_event: threading.Event | None = None,
    ) -> str | None:
        """Acquire and persist the WeChat database key for the connect flow.

        Saving the data root deliberately no longer does this, because the
        key can only be captured while WeChat is at a login moment. The
        connect flow calls this second step explicitly. ``progress`` is
        relayed unchanged; only READY_FOR_LOGIN permits a login prompt.
        """
        service = self._require_setup_service()
        _LOGGER.info(
            "[wechat facade] acquire_wechat_db_key progress=%s",
            progress is not None,
        )
        with _translated_errors(ChatSource.WECHAT):
            options = {"cancel_event": cancel_event} if cancel_event is not None else {}
            return service.acquire_db_key(progress=progress, **options)

    def cancel_wechat_connection(self, cancel_event: threading.Event) -> None:
        """Signal the exact attempt, including queued work, without GUI waits.

        The event reaches the key owner through acquire, so cancellation never
        builds a source or accidentally signals a newer connection attempt.
        """
        cancel_event.set()

    def get_session_message_range(
        self,
        source: ChatSource,
        session_id: str,
    ) -> tuple[int, int] | None:
        """Return earliest and latest message timestamps for one session."""
        chat_source = _coerce_source(source)
        service = self._require_service(chat_source)
        try:
            if chat_source is ChatSource.QQ:
                range_method = getattr(service, "get_session_message_range", None)
                if range_method is None:
                    return None
                raw_session = next(
                    (
                        candidate for candidate in (service.list_sessions() or ())
                        if getattr(candidate, "session_id", None) == session_id
                        or getattr(candidate, "group_code", None) == session_id
                    ),
                    None,
                )
                if _first_string(raw_session, "session_type") == "private":
                    return range_method(
                        session_id,
                        chat_type=1,
                        peer_uin=_first_string(raw_session, "peer_uin") or None,
                        session_name=_first_string(
                            raw_session,
                            "display_name",
                        ) or None,
                    )
                return range_method(session_id)
            provider_factory = getattr(service, "provider", None)
            if provider_factory is None:
                return None
            rows = provider_factory().read_session_rows(session_id)
        except Exception:
            return None
        epochs = [
            value
            for row in rows
            if isinstance(row, Mapping)
            for value in (to_epoch_seconds(row.get("create_time")),)
            if value is not None
        ]
        if not epochs:
            return None
        return min(epochs), max(epochs)

    def list_report_packages(self) -> ReportPackageListing:
        """List published package summaries and unreadable package issues."""
        try:
            return self._report_package_catalog.list_reports()
        except Exception as exc:
            _LOGGER.exception("Report package catalog could not be read.")
            raise FacadeError(
                code="report_list_failed",
                public_message="无法读取 Echo 本地报告，请稍后重试。",
            ) from exc

    def get_report_storage_usage(self) -> ReportStorageUsage:
        """Report owned package count and recorded size for later display."""
        try:
            return self._report_package_catalog.storage_usage()
        except Exception as exc:
            _LOGGER.exception("Report package storage usage could not be read.")
            raise FacadeError(
                code="report_usage_failed",
                public_message="无法统计 Echo 本地报告占用空间，请稍后重试。",
            ) from exc

    def get_report_package_html_path(self, package_name: str) -> Path:
        """Return a safely located historical report for the GUI opener."""
        try:
            return self._report_package_catalog.resolve_html_path(package_name)
        except Exception as exc:
            _LOGGER.exception("Report package HTML could not be located.")
            raise FacadeError(
                code="report_open_failed",
                public_message="这份 Echo 报告已损坏或缺少报告文件。",
            ) from exc

    def delete_report_package(self, package_name: str) -> None:
        """Delete a single complete package through the ownership boundary."""
        try:
            self._report_package_catalog.delete_package(package_name)
        except Exception as exc:
            _LOGGER.exception("Report package could not be deleted.")
            raise FacadeError(
                code="report_delete_failed",
                public_message="这份 Echo 报告未能删除，请稍后重试。",
            ) from exc

    def delete_report_packages(self, package_names: Iterable[str]) -> ReportPackageDeletionResult:
        """Delete exactly the selected report packages, reporting each outcome.

        The caller owns the selection: nothing outside it is rescanned or
        removed, so reports published while the batch runs stay on disk.
        Per-package failures come back inside the result instead of aborting the
        batch; only an unusable selection or storage boundary raises.
        """
        try:
            return self._report_package_catalog.delete_packages(package_names)
        except Exception as exc:
            _LOGGER.exception("Selected report packages could not be deleted.")
            raise FacadeError(
                code="report_delete_failed",
                public_message="所选 Echo 报告未能删除，请稍后重试。",
            ) from exc

    def clear_report_packages(self) -> None:
        """Delete complete owned packages; surface any partial failure."""
        try:
            self._report_package_catalog.clear_all()
        except Exception as exc:
            _LOGGER.exception("Report packages could not all be deleted.")
            raise FacadeError(
                code="report_clear_failed",
                public_message="部分 Echo 报告未能删除，请稍后重试。",
            ) from exc

    # -------------------------------------------------------------- analysis

    def analyze_session(
        self,
        source: ChatSource,
        session_id: str,
        config: AnalysisConfig | None = None,
        progress: Callable[[str], None] | None = None,
        *,
        speaker_names: Mapping[str, str] | None = None,
        viewer_speaker_key: str | None = None,
        on_phase: PhaseCallback | None = None,
    ) -> AnalysisOutcome:
        """Export one conversation, analyze it, and return a view.

        QQ Direct DB acquisition owns its payload until analysis completes.
        WeChat exports use the facade scratch directory.

        ``progress`` keeps carrying the human-facing Chinese status text;
        ``on_phase`` additionally receives :class:`AnalysisPhase.READING`
        before the source is acquired and
        :class:`AnalysisPhase.ANALYZING_REPORT` once acquisition succeeded.
        """
        chat_source = _coerce_source(source)
        resolved_config = config or AnalysisConfig()
        resolved_scope = self._resolve_scope(resolved_config, chat_source)
        _report_progress(progress, "正在准备分析...")
        _publish_phase(on_phase, AnalysisPhase.READING)
        _report_progress(progress, "正在读取聊天记录...")
        service = self._require_service(chat_source)
        if chat_source is ChatSource.QQ:
            # Direct DB: one acquisition owns both the payload and the session
            # descriptor. Listing sessions here would acquire a second
            # generation, so the descriptor is resolved from the acquisition.
            return self._analyze_direct_db_qq_session(
                service,
                session_id,
                resolved_config,
                resolved_scope,
                speaker_names=speaker_names,
                viewer_speaker_key=viewer_speaker_key,
                progress=progress,
                on_phase=on_phase,
            )
        if chat_source in (ChatSource.QQ, ChatSource.WECHAT):
            raw_session = next(
                (
                    candidate for candidate in (service.list_sessions() or ())
                    if getattr(candidate, "session_id", None) == session_id
                    or getattr(candidate, "group_code", None) == session_id
                ),
                None,
            )
            session = (
                _to_session_info(chat_source, raw_session)
                if raw_session is not None
                else SessionInfo(
                    source=chat_source,
                    session_id=session_id,
                    display_name=session_id,
                )
            )
            conversation_names = {session_id: session.display_name}
            conversation_kind = (
                session.session_type
                if session.session_type in ("private", "group")
                else "unknown"
            )
        else:
            session = SessionInfo(
                source=chat_source,
                session_id=session_id,
                display_name=session_id,
            )
            conversation_names = None
            conversation_kind = "unknown"

        with TemporaryDirectory(prefix="chat-analyzer-export-") as scratch:
            scratch_directory = Path(scratch)
            with self._session_export_context(
                chat_source,
                service,
                session_id,
                resolved_config,
                scratch_directory,
                raw_session=(
                    raw_session if chat_source is ChatSource.QQ else None
                ),
                scope=resolved_scope,
                progress=progress,
                on_phase=on_phase,
            ) as session_export:
                return self._analyze_path(
                    session_export.payload_path,
                    resolved_config,
                    source=chat_source,
                    session=session,
                    scope=resolved_scope,
                    speaker_names=speaker_names,
                    conversation_names=conversation_names,
                    conversation_kind=conversation_kind,
                    viewer_speaker_key=viewer_speaker_key,
                    progress=progress,
                )

    def _analyze_direct_db_qq_session(
        self,
        service: Any,
        session_id: str,
        config: AnalysisConfig,
        scope: AnalysisScope,
        *,
        speaker_names: Mapping[str, str] | None = None,
        viewer_speaker_key: str | None = None,
        progress: Callable[[str], None] | None = None,
        on_phase: PhaseCallback | None = None,
    ) -> AnalysisOutcome:
        """Run one Direct DB QQ analysis from a single generation acquisition.

        The session descriptor (display name, type) comes from the same
        acquisition that materialized the payload, so this path never calls
        the public ``list_sessions`` before analyzing.
        """
        started_at = _perf_counter()
        with TemporaryDirectory(prefix="chat-analyzer-export-") as scratch:
            scratch_directory = Path(scratch)
            with self._session_export_context(
                ChatSource.QQ,
                service,
                session_id,
                config,
                scratch_directory,
                raw_session=None,
                scope=scope,
                progress=progress,
                on_phase=on_phase,
            ) as session_export:
                acquired_at = _perf_counter()
                _LOGGER.info(
                    "[analysis-timing] stage=facade_acquisition elapsed_ms=%d",
                    max(0, round((acquired_at - started_at) * 1000)),
                )
                session = session_export.session or SessionInfo(
                    source=ChatSource.QQ,
                    session_id=session_id,
                    display_name=session_id,
                )
                conversation_names = {
                    session_export.conversation_id or session_id: session.display_name
                }
                conversation_kind = (
                    session.session_type
                    if session.session_type in ("private", "group")
                    else "unknown"
                )
                analysis_started_at = _perf_counter()
                completed = False
                try:
                    result = self._analyze_path(
                        session_export.payload_path,
                        config,
                        source=ChatSource.QQ,
                        session=session,
                        scope=scope,
                        speaker_names=speaker_names,
                        conversation_names=conversation_names,
                        conversation_kind=conversation_kind,
                        viewer_speaker_key=viewer_speaker_key,
                        progress=progress,
                        direct_db_diagnostics=True,
                    )
                    completed = True
                    return result
                finally:
                    _LOGGER.info(
                        "[analysis-timing] stage=facade_analysis elapsed_ms=%d status=%s",
                        max(0, round((_perf_counter() - analysis_started_at) * 1000)),
                        "ok" if completed else "failed",
                    )

    def generate_share_image(
        self,
        outcome: AnalysisOutcome,
        output_directory: Path | None = None,
    ) -> Path:
        """Render one shareable Echo overview card from a completed analysis."""
        view = self._echo_view_for_outcome(outcome)
        _LOGGER.info(
            "[facade] generate_share_image called view=%s "
            "report_directory=%s",
            view is not None,
            getattr(outcome, "report_directory", None),
        )
        if view is None:
            raise FacadeError(
                code="share_image_unavailable",
                public_message="没有可生成分享图片的分析结果。",
            )
        data = build_share_card_data(view)
        html = build_share_card_html(data, _share_assets(data))
        target_directory = (
            Path(output_directory)
            if output_directory is not None
            else (
                outcome.report_directory
                or outcome.artifact_directory
                or (user_data_dir() / "reports")
            )
        )
        target_directory.mkdir(parents=True, exist_ok=True)
        image_path = target_directory / "echo-share.png"
        try:
            render_share_html_to_png(html, image_path)
        except ShareImageRenderError as error:
            raise FacadeError(
                code="share_image_generation_failed",
                public_message="分享图片生成失败，请稍后重试。",
            ) from error
        _LOGGER.info("[facade] share image written path=%s", image_path)
        return image_path

    # ------------------------------------------------------------- internals

    def _analyze_path(
        self,
        input_path: Path,
        config: AnalysisConfig,
        *,
        source: ChatSource,
        session: SessionInfo | None,
        scope: AnalysisScope,
        speaker_names: Mapping[str, str] | None = None,
        conversation_names: Mapping[str, str] | None = None,
        conversation_kind: str = "unknown",
        viewer_speaker_key: str | None = None,
        progress: Callable[[str], None] | None = None,
        direct_db_diagnostics: bool = False,
    ) -> AnalysisOutcome:
        """Run analysis then presentation for one local path."""
        analysis_service = self._require_analysis_service()

        if config.output_directory is None and not self._scratch_recovery_done:
            _cleanup_stale_analysis_outputs(user_data_dir() / "transient")
            self._scratch_recovery_done = True
        output_directory, temporary_output = _create_output_directory(config)
        try:
            request = AnalysisRequestDTO(
                input_path=input_path,
                output_directory=output_directory,
                stopwords_path=self._stopwords_path(config.profile),
                font_path=config.font_path,
                top=config.top,
                scope=scope,
                speaker_names=speaker_names or {},
                conversation_names=conversation_names or {},
                conversation_kind=conversation_kind,
                viewer_speaker_key=viewer_speaker_key,
            )
            with _translated_errors(source):
                _report_progress(progress, "正在处理消息...")
                _report_progress(progress, "正在分析聊天内容...")
                core_started_at = _perf_counter()
                core_completed = False
                try:
                    result = analysis_service.execute(request)
                    core_completed = True
                finally:
                    if direct_db_diagnostics:
                        _LOGGER.info(
                            "[analysis-timing] stage=facade_core_analysis "
                            "elapsed_ms=%d status=%s",
                            max(0, round((_perf_counter() - core_started_at) * 1000)),
                            "ok" if core_completed else "failed",
                        )

            _report_progress(progress, "正在生成报告...")
            view = self._build_view(result)
            report_generated_at = datetime.now(timezone.utc)
            report_path = _generated_echo_report_path(result, output_directory)
            echo_report_view = getattr(result, "echo_report_view", None)
            report_directory = None
            if report_path is not None:
                try:
                    metadata = build_report_metadata(
                        result=result,
                        source=source.value,
                        scope=scope,
                        generated_at=report_generated_at,
                    )
                    report_directory = package_echo_report(
                        output_directory,
                        reports_root=self._report_package_catalog.reports_root,
                        metadata=metadata,
                        now=report_generated_at.astimezone(),
                    )
                    report_path = report_directory / ECHO_REPORT_HTML_NAME
                except Exception:
                    _LOGGER.warning(
                        "Analysis completed but the Echo report could not be "
                        "packaged; keeping the generated report in place.",
                        exc_info=True,
                    )
            _LOGGER.info(
                "[facade] analysis outcome ready report_path=%s "
                "report_directory=%s echo_view=%s",
                report_path,
                report_directory,
                echo_report_view is not None,
            )
            if temporary_output is not None and report_path is None:
                temporary_output.cleanup()
                temporary_output = None

            outcome = AnalysisOutcome(
                view=view,
                result=result,
                source=source,
                session=session,
                artifact_directory=(
                    output_directory if report_path is not None else None
                ),
                report_path=report_path,
                report_directory=report_directory,
                echo_report_view=echo_report_view,
                report_generated_at=report_generated_at,
            )
            _report_progress(progress, "分析完成")
            self._replace_retained_output(temporary_output)
        except BaseException:
            if temporary_output is not None:
                temporary_output.cleanup()
            raise
        return outcome

    def _replace_retained_output(
        self,
        temporary_output: _RetainedReportDirectory | None,
    ) -> None:
        """Keep only the latest successful scratch report alive."""
        previous = self._retained_output_directory
        self._retained_output_directory = temporary_output
        if previous is not None and previous is not temporary_output:
            previous.cleanup()

    def shutdown(self) -> ShutdownResult:
        """Return the same conservative resource evidence on repeated shutdown."""
        with self._shutdown_lock:
            if self._shutdown_result is None:
                self._shutdown_result = self._shutdown_with_result()
            return self._shutdown_result

    def _shutdown_with_result(self) -> ShutdownResult:
        """Release transient artifacts and stop LCA-owned QQ runtime processes.

        Order is deliberate: attempt Direct DB plaintext cleanup/recovery
        before stopping NapCat / the QQ runtime. Failure or timeout remains
        explicit in the result; returning alone does not prove plaintext was
        removed. Every step is bounded and exception-safe, so neither a failure
        nor a hung cleanup in one step can skip the steps after it - in
        particular QQ runtime termination.  Repeated calls are harmless: the
        Direct DB service refuses a second shutdown, and terminated PIDs are
        forgotten by the process registry.
        """
        started_at = _monotonic()
        with self._source_publication_lock:
            self._sources_closing.set()
        source_result = self._run_shutdown_step(
            'source_lifecycle', self._shutdown_source_lifecycle,
            window=self._source_lifecycle_step_window(),
        )
        _LOGGER.info("QQ shutdown requested")
        results = [self._run_shutdown_step(
            _SHUTDOWN_STEP_DIRECT_DB,
            self._shutdown_qq_direct_db_service,
            window=self._direct_db_step_window(),
        ), self._run_shutdown_step(
            _SHUTDOWN_STEP_RETAINED_OUTPUT,
            self._release_retained_output,
        ), self._run_shutdown_step(
            _SHUTDOWN_STEP_QQ_RUNTIME,
            self._shutdown_runtime_and_credential,
        )]
        results.append(source_result)
        _LOGGER.info(
            "QQ shutdown finished elapsed=%.2fs",
            _monotonic() - started_at,
        )
        return ShutdownResult(tuple(results))

    def _shutdown_source_lifecycle(self) -> ShutdownStatus:
        from .source_bundle_builder import SourceBundleBuilder
        from .analysis_service import AnalysisApplicationService

        builder_statuses = [builder.shutdown() if type(builder) is SourceBundleBuilder
                            else ShutdownStatus.UNKNOWN
                            for builder in self._source_builders.values()]
        analysis_status = (ShutdownStatus.SUCCESS if self._analysis_service is None
                           else self._analysis_service.shutdown()
                           if type(self._analysis_service) is AnalysisApplicationService
                           else ShutdownStatus.UNKNOWN)
        # Services currently expose no complete lifecycle/quiescence contract.
        # Even a successful recover RPC cannot prove every helper/read is gone.
        # Unpublished builders can already own resources or be in-flight.
        # Unknown analysis implementations likewise have no ownership proof.
        used_sources = bool(self._built_sources) or any(
            value is not None for value in (
                *self._services.values(), self._qq_connection_service,
                self._qq_setup_service, self._qq_connection_manager,
                self._qq_auth_bridge, self._wechat_connection_service_value,
                self._wechat_setup_service_value,
            )
        )
        setup = self._wechat_setup_service_value
        if setup is None:
            setup = getattr(self._built_sources.get(ChatSource.WECHAT), 'setup', None)
        if setup is not None:
            shutdown = getattr(setup, 'shutdown', None)
            if callable(shutdown):
                status = shutdown()
                if status in (ShutdownStatus.FAILED, ShutdownStatus.TIMED_OUT):
                    return status
        return (ShutdownStatus.UNKNOWN if used_sources
                or any(status is not ShutdownStatus.SUCCESS for status in (*builder_statuses, analysis_status))
                else ShutdownStatus.SUCCESS)

    def _source_lifecycle_step_window(self) -> float:
        # Key-owner drain is 3s; include a 1s scheduling margin, while keeping
        # the existing desktop exit window large enough for QQ's later steps.
        return min(self._shutdown_step_seconds, 4.0)

    def _shutdown_runtime_and_credential(self) -> ShutdownStatus:
        from .qq.qq_process_registry import QQProcessRegistry

        registry = self._require_qq_process_registry()
        if type(registry) is QQProcessRegistry:
            try:
                runtime_status = registry.shutdown()
            finally:
                credential_status = self._retire_qq_bridge_credential()
            return ShutdownResult((ShutdownStepResult('runtime', runtime_status),
                                   ShutdownStepResult('credential', credential_status))).status
        recorded = getattr(registry, 'recorded', None)
        try:
            registry.terminate_all()
        finally:
            credential_status = self._retire_qq_bridge_credential()
        if not callable(recorded):
            return (ShutdownStatus.FAILED if credential_status is ShutdownStatus.FAILED
                    else ShutdownStatus.UNKNOWN)
        if recorded():
            return ShutdownStatus.FAILED
        if credential_status is not ShutdownStatus.SUCCESS:
            return credential_status
        # A duck-typed empty inventory is not a proven ownership contract.
        return ShutdownStatus.UNKNOWN

    def _retire_qq_bridge_credential(self) -> ShutdownStatus:
        """Drop the credential of the QQ runtime Echo just stopped.

        Deliberately last: the plaintext recovery step above still needs it, and
        once the runtime is gone a value minted for it must not be able to reach
        whatever might answer on the port later.
        """
        session = self._qq_runtime_session
        from .qq.qq_runtime_session import QQRuntimeSession
        if type(session) is QQRuntimeSession:
            return session.shutdown()
        if session is None:
            from .qq.qq_runtime_session import default_qq_runtime_session
            session = default_qq_runtime_session()
        retire = getattr(session, "retire", None)
        credential = getattr(session, "credential", None)
        if not callable(retire):
            return ShutdownStatus.UNKNOWN
        credential_before = credential() if callable(credential) else None
        retire()
        if not callable(credential):
            return ShutdownStatus.UNKNOWN
        if credential() is not None:
            return ShutdownStatus.FAILED
        # Retirement clears the session's process reference, without waiting
        # for its exit. An injected owner has no complete lifecycle contract.
        if self._qq_runtime_session is not None or credential_before is not None:
            return ShutdownStatus.UNKNOWN
        return ShutdownStatus.SUCCESS

    def _direct_db_step_window(self) -> float:
        """Return the bounded window the Direct DB cleanup step gets.

        The service knows its own bounded worst case - the drain window plus the
        recover readiness budget - and this step window is that budget plus a
        margin.  A normal bounded cleanup therefore finishes and reports,
        instead of being abandoned and then killed by the process exit while it
        is still recovering orphan plaintext.
        """
        service = self._qq_service_if_present()
        budget = getattr(service, "shutdown_budget_seconds", None)
        if (
            isinstance(budget, bool)
            or not isinstance(budget, (int, float))
            or budget <= 0
        ):
            return self._shutdown_step_seconds
        return max(
            self._shutdown_step_seconds,
            float(budget) + _DIRECT_DB_STEP_MARGIN_SECONDS,
        )

    def _release_retained_output(self) -> ShutdownStatus:
        """Drop the last retained scratch report directory, if any."""
        previous = self._retained_output_directory
        self._replace_retained_output(None)
        if previous is None:
            return ShutdownStatus.SUCCESS
        # cleanup() logs and swallows filesystem failures; verify its effect.
        try:
            Path(previous.name).lstat()
        except FileNotFoundError:
            return ShutdownStatus.SUCCESS
        return ShutdownStatus.FAILED

    def _run_shutdown_step(
        self,
        label: str,
        step: Callable[[], Any],
        *,
        window: float | None = None,
    ) -> ShutdownStepResult:
        """Run one shutdown step inside its own bounded window.

        The step runs on a throwaway daemon thread so a cleanup that never
        returns - a wedged runtime RPC, a stuck process kill - is abandoned
        instead of holding the whole protocol, and with it the desktop process
        exit, hostage.  The window is finite by design, and start, outcome and
        elapsed time are logged so a real run is diagnosable.
        """
        budget = self._shutdown_step_seconds if window is None else window
        finished = threading.Event()
        started_at = _monotonic()
        outcome = ShutdownStatus.UNKNOWN

        def _run() -> None:
            nonlocal outcome
            try:
                returned = step()
                if isinstance(returned, ShutdownStatus):
                    outcome = returned
            except BaseException:
                outcome = ShutdownStatus.FAILED
                _LOGGER.warning(
                    "QQ shutdown step failed step=%s",
                    label,
                    exc_info=True,
                )
            finally:
                finished.set()

        thread = threading.Thread(
            target=_run,
            name=f"{_SHUTDOWN_STEP_THREAD_PREFIX}{label}",
            daemon=True,
        )
        _LOGGER.info(
            "QQ shutdown step started step=%s window=%.2fs",
            label,
            budget,
        )
        thread.start()
        if not finished.wait(budget):
            _LOGGER.warning(
                "QQ shutdown step exceeded %.1fs and was abandoned step=%s",
                budget,
                label,
            )
            return ShutdownStepResult(label, ShutdownStatus.TIMED_OUT)
        _LOGGER.info(
            "QQ shutdown step finished step=%s elapsed=%.2fs",
            label,
            _monotonic() - started_at,
        )
        return ShutdownStepResult(label, outcome)

    def _shutdown_qq_direct_db_service(self) -> ShutdownStatus:
        """Recover plaintext and consume only owned, explicit cleanup evidence."""
        service = self._qq_service_if_present()
        if service is None:
            return ShutdownStatus.SUCCESS
        shutdown = getattr(service, "shutdown", None)
        if callable(shutdown):
            try:
                status = shutdown()
                from .qq.qq_direct_database_import_service import QQDirectDatabaseImportService
                # Only the owned implementation proves acquisition admission,
                # drain and recover. A duck-typed return is not ownership proof.
                if (type(service) is QQDirectDatabaseImportService
                        and isinstance(status, ShutdownStatus)):
                    return status
            except Exception:
                _LOGGER.warning(
                    "QQ Direct DB plaintext cleanup did not complete during "
                    "shutdown."
                )
                raise
        return ShutdownStatus.UNKNOWN

    def _qq_service_if_present(self) -> Any:
        """Return the QQ service without building it for the first time.

        A never-built QQ service has never acquired a generation, so there is
        nothing to clean up; forcing its construction here would be a side
        effect the shutdown path must not have.
        """
        service = self._services.get(ChatSource.QQ)
        if service is not None:
            return service
        bundle = self._built_sources.get(ChatSource.QQ)
        if bundle is not None:
            return getattr(bundle, "service", None)
        return None

    def _build_view(self, result: AnalysisResultDTO) -> DashboardView:
        """Hand the reports to the presentation layer without touching them."""
        reports = getattr(result, "reports", None)
        top_words = getattr(result, "top_words", ()) or ()

        if self._presentation_builder is not None:
            return self._presentation_builder.build(
                reports,
                top_words=top_words,
            )
        return build_dashboard_view(reports, top_words=top_words)

    @staticmethod
    def _echo_view_for_outcome(outcome: AnalysisOutcome) -> EchoReportView | None:
        """Reuse the view already built for Echo artifacts when available."""
        view = getattr(outcome, "echo_report_view", None)
        if view is not None:
            return view
        reports = getattr(getattr(outcome, "result", None), "reports", None)
        if reports is None:
            return None
        session = getattr(outcome, "session", None)
        conversation_kind = getattr(session, "session_type", None)
        if conversation_kind not in ("private", "group"):
            conversation_kind = "unknown"
        return build_echo_report_view(
            reports,
            conversation_kind=conversation_kind,
        )

    @contextmanager
    def _session_export_context(
        self,
        source: ChatSource,
        service: Any,
        session_id: str,
        config: AnalysisConfig,
        scratch_directory: Path,
        *,
        raw_session: Any = None,
        scope: AnalysisScope | None = None,
        progress: Callable[[str], None] | None = None,
        on_phase: PhaseCallback | None = None,
    ) -> Iterator[_SessionExport]:
        """Yield an export while preserving source-specific ownership.

        Acquisition receives inclusive epoch-second scope bounds. The final
        scope filter re-checks every imported message. QQ payload ownership
        spans the consumer, and acquisition failures become FacadeError.

        ``ANALYZING_REPORT`` is published here, not by the caller, because only
        this context knows that the source acquisition really succeeded: for QQ
        while the acquisition context is still open, for WeChat once
        ``export_only`` has returned a payload. A failed acquisition therefore
        never publishes it.
        """
        if source is ChatSource.QQ:
            start_seconds, end_seconds = _scope_export_window_seconds(scope)
            with ExitStack() as ownership:
                with _translated_errors(source):
                    acquisition = ownership.enter_context(
                        service.acquired_session(
                            session_id,
                            start_time=start_seconds,
                            end_time=end_seconds,
                        )
                    )
                _publish_phase(on_phase, AnalysisPhase.ANALYZING_REPORT)
                raw_session = getattr(acquisition, "session", None)
                yield _SessionExport(
                    payload_path=Path(acquisition.payload_path),
                    conversation_id=getattr(raw_session, "conversation_id", None),
                    session=(
                        _to_session_info(source, raw_session)
                        if raw_session is not None
                        else None
                    ),
                )
            return

        with _translated_errors(source):
            payload_path = Path(
                service.export_only(
                    WeChatExportImportRequest(
                        session_id=session_id,
                        output_path=(
                            scratch_directory / "wechat_export.json"
                        ),
                        start_time=_scope_export_window_seconds(scope)[0],
                        end_time=_scope_export_window_seconds(scope)[1],
                    )
                )
            )
        # The phase callback belongs to the caller, not to the source, so a
        # failure in it stays a caller failure instead of becoming a source
        # error. No source resource is held at this point.
        _publish_phase(on_phase, AnalysisPhase.ANALYZING_REPORT)
        with _translated_errors(source):
            yield _SessionExport(payload_path=payload_path)

    @staticmethod
    def _resolve_scope(
        config: AnalysisConfig,
        source: ChatSource,
    ) -> AnalysisScope:
        with _translated_errors(source):
            return resolve_scope(
                config.scope_mode,
                start_time=config.start_time,
                end_time=config.end_time,
            )

    def _stopwords_path(self, profile: str) -> Path:
        filename = _PROFILE_STOPWORD_FILES.get(
            profile,
            _PROFILE_STOPWORD_FILES[DEFAULT_PROFILE],
        )
        return self._stopwords_directory / filename

    def _is_available(self, source: ChatSource) -> bool:
        return (
            self._services.get(source) is not None
            or source in self._source_builders
        )

    def _require_service(self, source: ChatSource) -> Any:
        service = self._services.get(source)
        if service is None:
            bundle = self._source_bundle(source)
            service = getattr(bundle, "service", None)
        if service is None:
            raise SourceUnavailable(source)
        return service

    def _require_connection_service(self, source: ChatSource) -> Any:
        if source is ChatSource.QQ:
            service = self._qq_connection_service
        elif source is ChatSource.WECHAT:
            service = self._wechat_connection_service
        else:
            raise UnknownChatSource(source)
        if service is None:
            bundle = self._source_bundle(source)
            service = getattr(bundle, "connection", None)
        if service is None:
            raise SourceUnavailable(source)
        return service

    def _require_qq_connection_manager(self) -> Any:
        """Return the QQ connection manager, building it on first use.

        The manager is composed from the services this facade already holds,
        so a caller that injected stubs keeps getting those stubs.
        """
        if self._qq_connection_manager is None:
            self._qq_connection_manager = QQConnectionManager(
                setup_service=self._optional_qq_setup_service(),
                connection_service=self._optional_qq_connection_service(),
            )
        return self._qq_connection_manager

    def _require_qq_auth_bridge(self) -> Any:
        """Return the QQ auth bridge, composing it from injected services."""
        if self._qq_auth_bridge is None:
            from .qq.qq_auth_bridge import QQAuthBridge
            from .qq.qq_auth_bridge import (
                terminate_bundled_runtime_sessions,
            )

            self._qq_auth_bridge = QQAuthBridge(
                setup_service=self._optional_qq_setup_service(),
                connection_service=self._optional_qq_connection_service(),
                manager=self._require_qq_connection_manager(),
                process_registry=self._require_qq_process_registry(),
                credential=self._qq_runtime_session,
                # A new auth session must not keep sharing the QR cache with
                # a runtime left over from an earlier Echo instance.
                runtime_cleaner=terminate_bundled_runtime_sessions,
            )
        return self._qq_auth_bridge

    def _require_qq_process_registry(self) -> Any:
        """Return the shared QQ process registry for this application."""
        if self._qq_process_registry is None:
            from .qq.qq_process_registry import (
                default_qq_process_registry,
            )

            self._qq_process_registry = default_qq_process_registry()
        return self._qq_process_registry

    def _optional_qq_setup_service(self) -> Any:
        try:
            return self._require_qq_setup_service()
        except SourceUnavailable:
            return None

    def _optional_qq_connection_service(self) -> Any:
        try:
            return self._require_connection_service(ChatSource.QQ)
        except (SourceUnavailable, UnknownChatSource):
            return None

    def _require_qq_setup_service(self) -> Any:
        service = self._qq_setup_service
        if service is None:
            bundle = self._source_bundle(ChatSource.QQ)
            service = getattr(bundle, "setup", None)
        if service is None:
            raise SourceUnavailable(ChatSource.QQ)
        return service

    def _require_setup_service(self) -> Any:
        if self._sources_closing.is_set():
            raise FacadeError(code="application_closing", public_message="Echo 正在关闭。")
        service = self._wechat_setup_service
        if self._sources_closing.is_set():
            raise FacadeError(code="application_closing", public_message="Echo 正在关闭。")
        if service is None:
            bundle = self._source_bundle(ChatSource.WECHAT)
            service = getattr(bundle, "setup", None)
        if service is None:
            raise SourceUnavailable(ChatSource.WECHAT)
        return service

    def _source_bundle(self, source: ChatSource) -> Any:
        """Build and cache one source's services on first access."""
        if source not in self._built_sources:
            builder = self._source_builders.get(source)
            if builder is None:
                raise SourceUnavailable(source)
            if source is ChatSource.WECHAT and self._sources_closing.is_set():
                raise FacadeError(code="application_closing", public_message="Echo 正在关闭。")
            bundle = builder()
            if source is ChatSource.WECHAT:
                # Never hold this short publication lock while building/draining.
                # Close takes the same boundary before its ownership snapshot.
                with self._source_publication_lock:
                    closing = self._sources_closing.is_set()
                    if not closing:
                        self._built_sources[source] = bundle
                if closing:
                    shutdown = getattr(getattr(bundle, "setup", None), "shutdown", None)
                    if callable(shutdown):
                        shutdown()
                    raise FacadeError(code="application_closing", public_message="Echo 正在关闭。")
            else:
                self._built_sources[source] = bundle
        return self._built_sources[source]

    def _require_analysis_service(self) -> Any:
        if self._analysis_service is None:
            raise FacadeError(
                code="analysis_service_unavailable",
                public_message="分析服务不可用。",
            )
        return self._analysis_service


# ------------------------------------------------------------------ helpers


def _create_output_directory(
    config: AnalysisConfig,
) -> tuple[Path, _RetainedReportDirectory | None]:
    """Create an artifact directory and transfer scratch ownership upward."""
    if config.output_directory is not None:
        directory = Path(config.output_directory)
        directory.mkdir(parents=True, exist_ok=True)
        return directory, None

    transient_directory = user_data_dir() / "transient"
    _require_no_reparse_points(transient_directory)
    transient_directory.mkdir(parents=True, exist_ok=True)
    scratch = _RetainedReportDirectory(transient_directory)
    return Path(scratch.name), scratch


def _generated_echo_report_path(
    result: AnalysisResultDTO,
    output_directory: Path,
) -> Path | None:
    """Resolve the report descriptor produced by this exact analysis run."""
    for artifact in result.artifacts:
        if artifact.kind != "echo_report_html":
            continue
        candidate = (output_directory / artifact.filename).resolve()
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            return None
    return None


def _share_assets(data: ShareCardData) -> dict[str, str]:
    """Inline only the expression images referenced by the share card."""
    assets: dict[str, str] = {}
    expressions = data.expressions
    if expressions is None:
        return assets
    for combo in expressions.combos:
        for key in (combo.primary_asset_key, combo.secondary_asset_key):
            if not isinstance(key, str) or not key:
                continue
            data_uri = expression_asset_data_uri(key)
            if data_uri:
                assets[key] = data_uri
    return assets


@contextmanager
def _translated_errors(source: ChatSource | None) -> Iterator[None]:
    """Convert every known collaborator failure into a :class:`FacadeError`."""
    try:
        yield
    except FacadeError:
        raise
    except ApplicationServiceError as error:
        raise FacadeError(
            code=getattr(error, "code", "application_error"),
            public_message=_provider_error_message(error),
            source=source,
        ) from error
    except Exception as error:
        raise FacadeError(
            code=_provider_error_code(error),
            public_message=_provider_error_message(error),
            source=source,
        ) from error


def _provider_error_code(error: Exception) -> str:
    """Prefer a provider's own stable code, else derive one from its class."""
    code = getattr(error, "code", None)
    if isinstance(code, str) and code.strip():
        return code
    return _snake_case(type(error).__name__)


def _provider_error_message(error: Exception) -> str:
    """Trust explicit public messages; never expose raw exception text."""
    message = getattr(error, "public_message", None)
    if isinstance(message, str) and message.strip():
        return message
    return "操作失败，请稍后重试。"


def _snake_case(name: str) -> str:
    characters: list[str] = []
    for index, character in enumerate(name):
        if character.isupper() and index > 0:
            characters.append("_")
        characters.append(character.lower())
    return "".join(characters)


def _scope_export_window_seconds(
    scope: AnalysisScope | None,
) -> tuple[int | None, int | None]:
    """Translate an inclusive calendar scope into QQ/WeChat epoch-second bounds.

    ``(None, None)`` means "no filter", which keeps the full-history export
    path unchanged for the ALL scope. The end bound is the last second
    (23:59:59) of the inclusive end date, matching WeChat second-precision
    m.create_time column.

    """
    if scope is None or scope.start_date is None or scope.end_date is None:
        return None, None
    try:
        start_seconds = _local_midnight_epoch_seconds(scope.start_date)
        end_exclusive_seconds = _local_midnight_epoch_seconds(
            scope.end_date + timedelta(days=1)
        )
    except (OverflowError, OSError, ValueError):
        return None, None
    end_inclusive_seconds = end_exclusive_seconds - 1
    return (start_seconds, end_inclusive_seconds)


def _local_midnight_epoch_seconds(value: date) -> int:

    """Return the local-time midnight of one calendar date in epoch seconds."""
    return int(datetime.combine(value, time.min).timestamp())


def _coerce_source(source: Any) -> ChatSource:
    """Accept a :class:`ChatSource` or its string value."""
    if isinstance(source, ChatSource):
        return source
    try:
        return ChatSource(source)
    except (ValueError, TypeError):
        raise UnknownChatSource(source) from None


def _to_session_info(source: ChatSource, raw_session: Any) -> SessionInfo:
    """Normalise one provider session or group into :class:`SessionInfo`.

    QQ groups expose ``group_code``/``group_name``/``message_count`` while
    WeChat sessions expose ``session_id``/``display_name``/``message_count``.
    Both collapse into the same shape here so a caller never branches on the
    source when rendering a list.
    """
    if source is ChatSource.QQ:
        session_id = _first_string(raw_session, "group_code", "session_id")
        display_name = _first_string(
            raw_session,
            "group_name",
            "display_name",
        )
        session_type = _first_string(raw_session, "session_type") or "group"
    else:
        session_id = _first_string(raw_session, "session_id", "group_code")
        display_name = _first_string(
            raw_session,
            "display_name",
            "group_name",
        )
        session_type = _first_string(raw_session, "session_type") or "other"

    return SessionInfo(
        source=source,
        session_id=session_id,
        display_name=(
            display_name
            or ("\u672a\u77e5\u7fa4\u804a" if source is ChatSource.QQ else session_id)
        ),
        session_type=session_type,
        message_count=_first_int(raw_session, "message_count"),
        last_message_time=_first_epoch(
            raw_session,
            "last_message_time",
            "last_timestamp",
        ),
        message_available=bool(
            getattr(raw_session, "message_available", True)
        ),
        unavailable_reason=getattr(raw_session, "unavailable_reason", None),
    )


def _first_string(raw_session: Any, *names: str) -> str:
    for name in names:
        value = getattr(raw_session, name, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _first_int(raw_session: Any, *names: str) -> int | None:
    for name in names:
        value = getattr(raw_session, name, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _first_epoch(raw_session: Any, *names: str) -> int | None:
    for name in names:
        value = getattr(raw_session, name, None)
        if value is None:
            continue
        epoch = to_epoch_seconds(value)
        if epoch is not None:
            return epoch
    return None
