"""About Echo, and an explicitly requested, worker-backed release check.

The dialog renders Facade outcomes. UpdateInfo, cache and installation policy
belong to the application service. Only a downloaded result confirms success;
progress percentages never imply installation or restart.
"""

from __future__ import annotations

import math
import weakref
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget, QMessageBox,
)
from shiboken6 import isValid

from .. import version
from ..application.facade import (
    FacadeError, InstallableUpdateResult, InstallHandoffResult, UpdateCheckResult,
)
from .theme import (
    HOME_COLOR_PAPER, HOME_COLOR_TEXT, HOME_COLOR_MUTED, HOME_COLOR_ACCENT,
    COLOR_BORDER, REFRESH_SANS_FAMILY, SERIF_FAMILY,
)
from .workers import submit


CHECK_FAILED_MESSAGE = "暂时无法检查更新，请稍后手动重试。"
DOWNLOAD_FAILED_MESSAGE = "暂时无法下载更新，请稍后手动重试。"
_UNSAFE_RELEASE_NOTE = "发布页面暂不可用，请稍后重试。"


class UpdatePhase(Enum):
    """Every state the About page can display.

    The first group mirrors the facade's check outcomes. The download group is
    owned by the update core and is only entered from its reports.
    """

    IDLE = "idle"
    CHECKING = "checking"
    UP_TO_DATE = "up_to_date"
    NO_RELEASE = "no_release"
    NO_UPDATE = "no_update"
    SKIPPED = "skipped"
    FAILED = "failed"
    UPDATE_AVAILABLE = "update_available"
    DOWNLOADING = "downloading"
    DOWNLOAD_COMPLETE = "download_complete"


_CHECK_PHASES = {
    "up_to_date": UpdatePhase.UP_TO_DATE,
    "no_release": UpdatePhase.NO_RELEASE,
    "skipped": UpdatePhase.SKIPPED,
}

# The download entry point stays in the layout while a download runs, but only
# these phases accept a click that submits one.
_DOWNLOAD_VISIBLE = (UpdatePhase.UPDATE_AVAILABLE, UpdatePhase.DOWNLOADING, UpdatePhase.FAILED)
_DOWNLOAD_READY = (UpdatePhase.UPDATE_AVAILABLE, UpdatePhase.FAILED)

# An update that is staged for the next restart is a terminal display state:
# re-checking would replace the only notice that a restart is pending, and the
# dialog must not replace it with release-page metadata.
_STAGED = (UpdatePhase.DOWNLOAD_COMPLETE,)


@dataclass(frozen=True, slots=True)
class UpdatePresentation:
    """What every widget shows for one phase."""

    text: str
    check_enabled: bool
    check_text: str
    show_release: bool = False
    show_download: bool = False
    download_enabled: bool = False
    download_text: str = "下载更新"
    show_progress: bool = False
    percent: int | None = None


def update_presentation(
    phase: UpdatePhase,
    *,
    latest_version: str | None = None,
    message: str | None = None,
    note: str | None = None,
    percent: float | None = None,
    release_available: bool = False,
    release_open_failed: bool = False,
    download_available: bool = False,
) -> UpdatePresentation:
    """Map one phase to the widgets' state.

    Pure by design: no widget, no network and no update action happens here, so
    the full state table is testable offline. ``download_available`` is false
    until an update core is wired in; the dialog then simply does not offer the
    download entry point instead of pretending one exists.
    """
    text = {
        UpdatePhase.IDLE: "点击检查更新，查询 GitHub 上的正式发布。",
        UpdatePhase.CHECKING: "正在查询正式发布…",
        UpdatePhase.UP_TO_DATE: "当前已是最新版本。",
        UpdatePhase.NO_RELEASE: "暂无正式发布，请稍后再检查。",
        UpdatePhase.NO_UPDATE: "暂未发现可安装更新。",
        UpdatePhase.SKIPPED: "本次检查未执行，请稍后重试。",
    }.get(phase, CHECK_FAILED_MESSAGE)
    shown_percent: int | None = None
    if phase is UpdatePhase.FAILED:
        text = message or CHECK_FAILED_MESSAGE
    elif phase is UpdatePhase.UPDATE_AVAILABLE:
        text = ("无法打开浏览器，请稍后重试查看发布页面。" if release_open_failed
                else f"发现新版本  {latest_version or '未知版本'}")
    elif phase is UpdatePhase.DOWNLOADING:
        shown_percent = _bounded_percent(percent)
        text = ("正在下载更新…" if shown_percent is None
                else f"正在下载更新…  {shown_percent}%")
    elif phase is UpdatePhase.DOWNLOAD_COMPLETE:
        text = "更新已下载完成。仅支持未连接、无分析任务时安装并重启。"
    if note:
        text = f"{text}\n{note}"
    busy = phase in (UpdatePhase.CHECKING, UpdatePhase.DOWNLOADING)
    return UpdatePresentation(
        text=text,
        check_enabled=not busy and phase not in _STAGED,
        check_text="正在检查…" if phase is UpdatePhase.CHECKING else "检查更新",
        show_release=phase is UpdatePhase.UPDATE_AVAILABLE and release_available,
        show_download=download_available and phase in _DOWNLOAD_VISIBLE,
        download_enabled=download_available and phase in _DOWNLOAD_READY,
        download_text="正在下载…" if phase is UpdatePhase.DOWNLOADING else "下载更新",
        show_progress=busy,
        percent=shown_percent,
    )


def _bounded_percent(value: object) -> int | None:
    """Clamp a reported percentage; unusable values stay indeterminate."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return int(min(100.0, max(0.0, float(value))))


class UpdateDialog(QDialog):
    """Present Facade outcomes and request only user-confirmed preparation."""

    install_requested = Signal(object)

    def __init__(self, facade: Any, parent: QWidget | None = None,
                 *, executor: Any = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("关于余音")
        self.setWindowModality(Qt.WindowModal)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMinimumWidth(420)
        self.resize(460, 330)
        self._facade = facade
        self._executor = executor or submit
        self._core_result: InstallableUpdateResult | None = None
        self._local_operation = False
        self._closed = False
        self._phase = UpdatePhase.IDLE
        self._latest_version: str | None = None
        self._message: str | None = None
        self._note: str | None = None
        self._percent: int | None = None
        self._release_url: str | None = None
        self._open_failed = False
        self._generation = 0
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(150)
        self._status_timer.timeout.connect(self._restore_status)
        self.finished.connect(self._mark_closed)
        self.setObjectName("echoAbout")
        self.setStyleSheet(f"""
            QDialog#echoAbout {{ background: {HOME_COLOR_PAPER}; }}
            QDialog#echoAbout QLabel, QDialog#echoAbout QPushButton {{
                font-family: {REFRESH_SANS_FAMILY}; font-size: 13px;
                color: {HOME_COLOR_TEXT}; background: transparent;
            }}
            QDialog#echoAbout QLabel#aboutTitle {{ font-family: {SERIF_FAMILY}; font-size: 32px; }}
            QDialog#echoAbout QLabel#aboutSecondary {{ color: {HOME_COLOR_MUTED}; }}
            QDialog#echoAbout QPushButton {{ border: 1px solid {COLOR_BORDER}; padding: 8px 14px; }}
            QDialog#echoAbout QPushButton:hover, QDialog#echoAbout QPushButton:focus {{
                border-color: {HOME_COLOR_ACCENT}; color: {HOME_COLOR_ACCENT};
            }}
            QDialog#echoAbout QPushButton:disabled {{ color: {HOME_COLOR_MUTED}; }}
            QDialog#echoAbout QPushButton#releaseLink {{ border: none; color: {HOME_COLOR_ACCENT}; }}
            QDialog#echoAbout QProgressBar {{
                border: 1px solid {COLOR_BORDER}; border-radius: 3px;
                background: {HOME_COLOR_PAPER};
            }}
            QDialog#echoAbout QProgressBar::chunk {{
                background: {HOME_COLOR_ACCENT}; border-radius: 3px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(14)
        title = QLabel("余音 Echo")
        title.setObjectName("aboutTitle")
        layout.addWidget(title)
        self.version_label = QLabel(f"当前版本  {version.APP_VERSION}")
        self.version_label.setObjectName("aboutSecondary")
        self.version_label.setTextFormat(Qt.PlainText)
        layout.addWidget(self.version_label)
        description = QLabel("把聊天记录，整理成可以慢慢回看的报告。\n本地读取 · 不上传聊天数据")
        description.setObjectName("aboutSecondary")
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addStretch(1)
        self.status_label = QLabel()
        self.status_label.setTextFormat(Qt.PlainText)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(40)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("updateProgress")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)
        actions = QHBoxLayout()
        self.release_button = QPushButton("查看发布页面 ↗")
        self.release_button.setObjectName("releaseLink")
        self.release_button.setCursor(Qt.PointingHandCursor)
        self.release_button.clicked.connect(self._open_release)
        actions.addWidget(self.release_button)
        actions.addStretch(1)
        # Only meaningful once a core can actually download; hidden until then.
        self.download_button = QPushButton("下载更新")
        self.download_button.setObjectName("downloadUpdate")
        self.download_button.clicked.connect(self._start_download)
        actions.addWidget(self.download_button)
        self.install_button = QPushButton('安装并重启')
        self.install_button.setObjectName('installUpdate')
        self.install_button.clicked.connect(self._start_install)
        actions.addWidget(self.install_button)
        self.check_button = QPushButton("检查更新")
        self.check_button.clicked.connect(self._check)
        actions.addWidget(self.check_button)
        layout.addLayout(actions)
        self._render()
        self._restore_status()

    def _mark_closed(self, _result: int) -> None:
        self._closed = True
        self._generation += 1
        self._status_timer.stop()

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self._restore_status()

    def _restore_status(self) -> None:
        """Observe memory-only Facade state, including another dialog's worker."""
        if self._closed or self._local_operation:
            return
        getter = getattr(self._facade, 'get_update_status', None)
        if getter is None:
            return  # retain compatibility with release-only facade clients
        try:
            result = getter()
        except FacadeError as error:
            self._fail(error.public_message)
            return
        except Exception:
            self._fail(CHECK_FAILED_MESSAGE)
            return
        if not isinstance(result, InstallableUpdateResult):
            return
        changed = result != self._core_result
        self._core_result = result
        if result.status in ('unsupported', 'unconfigured'):
            self._status_timer.stop()
            self._render()
            return
        self._status_timer.start()
        if changed:
            self._show_installable_result(result)

    def _render(self) -> None:
        """Apply the phase table. The only place that writes to widgets."""
        view = update_presentation(
            self._phase,
            latest_version=self._latest_version,
            message=self._message,
            note=self._note,
            percent=self._percent,
            release_available=_safe_release_url(self._release_url),
            release_open_failed=self._open_failed,
            download_available=self._can_download(),
        )
        self.status_label.setText(view.text)
        self.check_button.setEnabled(view.check_enabled)
        self.check_button.setText(view.check_text)
        self.release_button.setVisible(view.show_release)
        self.download_button.setVisible(view.show_download)
        self.download_button.setEnabled(view.download_enabled)
        self.download_button.setText(view.download_text)
        installable = (self._core_result is not None and self._core_result.status == 'downloaded'
                       and callable(getattr(self._facade, 'prepare_update_install', None)))
        self.install_button.setVisible(installable)
        self.install_button.setEnabled(installable and not self._local_operation)
        self.progress_bar.setVisible(view.show_progress)
        if view.show_progress:
            if view.percent is None:
                self.progress_bar.setRange(0, 0)
            else:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(view.percent)

    def _begin(self, phase: UpdatePhase) -> int:
        """Enter ``phase`` and return the generation that owns its callbacks.

        Bumping the generation retires every callback still queued for an older
        attempt, so a late report cannot overwrite a newer state.
        """
        self._generation += 1
        self._phase = phase
        self._message = None
        self._note = None
        self._percent = None
        self._open_failed = False
        return self._generation

    def _can_download(self) -> bool:
        result = self._core_result
        return result is not None and (
            result.status in ('available', 'downloading')
            or (result.status == 'failed' and result.error_code == 'download_failed'
                and result.target_version is not None))

    def _callbacks(
        self, generation: int, deliver: Callable[["UpdateDialog", Any], None],
    ) -> tuple[Callable[[Any], None], Callable[[str, str], None], Callable[[Any], None]]:
        """Return callbacks that drop anything a stale or closed dialog should not show.

        The worker relays these back onto the GUI thread; the dialog itself may
        already be closed or deleted by then.
        """
        reference = weakref.ref(self)

        def live() -> "UpdateDialog | None":
            dialog = reference()
            if dialog is None or not isValid(dialog) or dialog._closed:
                return None
            return dialog if dialog._generation == generation else None

        def success(result: Any) -> None:
            dialog = live()
            if dialog is not None:
                dialog._generation += 1  # retire all callbacks of this attempt
                dialog._local_operation = False
                deliver(dialog, result)

        def error(_code: str, message: str) -> None:
            dialog = live()
            if dialog is not None:
                dialog._generation += 1
                dialog._local_operation = False
                dialog._fail(message)

        def progress(report: Any) -> None:
            dialog = live()
            if dialog is not None:
                dialog._apply_progress(report)

        return success, error, progress

    def _check(self) -> None:
        if (self._closed
                or self._phase in (UpdatePhase.CHECKING, UpdatePhase.DOWNLOADING)
                or self._phase in _STAGED):
            return
        generation = self._begin(UpdatePhase.CHECKING)
        self._local_operation = True
        self._release_url = None
        self._render()
        success, error, _progress = self._callbacks(
            generation, lambda dialog, result: dialog._show_result(result))
        facade = self._facade
        def check() -> InstallableUpdateResult | UpdateCheckResult:
            checker = getattr(facade, 'check_installable_update', None)
            if checker is not None:
                result = checker()
                if result.status not in ('unsupported', 'unconfigured'):
                    return result
            return facade.check_for_updates(manual=True)
        try:
            self._executor(check,
                           on_success=success, on_error=error)
        except Exception:
            error("submit_failed", CHECK_FAILED_MESSAGE)

    def _fail(self, message: str) -> None:
        """Show an outcome that produced no usable result."""
        self._message = message
        self._note = None
        self._percent = None
        self._open_failed = False
        self._phase = UpdatePhase.FAILED
        self._render()

    def _show_result(self, result: Any) -> None:
        """Present one facade outcome. Whatever it says replaces the old state."""
        if isinstance(result, InstallableUpdateResult):
            self._show_installable_result(result)
            return
        if not isinstance(result, UpdateCheckResult):
            self._fail(CHECK_FAILED_MESSAGE)
            return
        status = getattr(result, "status", None)
        self._message = None
        self._note = None
        self._latest_version = None
        self._release_url = None
        self._open_failed = False
        self._phase = _CHECK_PHASES.get(status, UpdatePhase.FAILED)
        if status == "update_available":
            self._phase = UpdatePhase.UPDATE_AVAILABLE
            self._latest_version = getattr(result, "latest_version", None)
            url = getattr(result, "release_url", None)
            if _safe_release_url(url):
                self._release_url = url
            else:
                self._note = _UNSAFE_RELEASE_NOTE
        elif self._phase is UpdatePhase.FAILED:
            self._message = getattr(result, "public_message", None) or CHECK_FAILED_MESSAGE
        # A release-page fallback must retire any old installable capability.
        # Refresh only the Facade's in-memory status, never perform SDK I/O here.
        self._restore_status()
        self._render()

    def _show_installable_result(self, result: InstallableUpdateResult) -> None:
        self._core_result = result
        self._release_url = None
        self._note = None
        self._open_failed = False
        self._message = result.public_message
        self._latest_version = result.target_version
        self._percent = result.progress if result.status == 'downloading' else None
        self._phase = {
            'idle': UpdatePhase.IDLE,
            'checking': UpdatePhase.CHECKING,
            'available': UpdatePhase.UPDATE_AVAILABLE,
            'no_update': UpdatePhase.NO_UPDATE,
            'downloading': UpdatePhase.DOWNLOADING,
            'downloaded': UpdatePhase.DOWNLOAD_COMPLETE,
        }.get(result.status, UpdatePhase.FAILED)
        if result.status == 'busy':
            # Another dialog owns the operation. Observe it instead of retrying.
            self._core_result = None
            self._restore_status()
            return
        if result.status in ('unsupported', 'unconfigured'):
            self._phase = UpdatePhase.IDLE
        if result.current_version:
            self.version_label.setText(f'当前版本  {result.current_version}')
        if result.status not in ('unsupported', 'unconfigured'):
            self._status_timer.start()
        self._render()

    def _start_download(self) -> None:
        """Adapt worker positional reporter to the Facade's keyword contract."""
        if (self._closed or not self._can_download()
                or self._phase not in _DOWNLOAD_READY):
            return
        generation = self._begin(UpdatePhase.DOWNLOADING)
        self._local_operation = True
        self._render()
        success, error, progress = self._callbacks(
            generation, lambda dialog, result: dialog._show_download_result(result))
        facade = self._facade
        try:
            self._executor(lambda report: facade.download_update(progress=report), on_success=success,
                           on_error=error, on_progress=progress)
        except Exception:
            error("download_submit_failed", DOWNLOAD_FAILED_MESSAGE)

    def _show_download_result(self, result: Any) -> None:
        """A worker returning normally may still carry a failure result."""
        if not isinstance(result, InstallableUpdateResult):
            self._fail(DOWNLOAD_FAILED_MESSAGE)
            return
        self._show_installable_result(result)

    def _start_install(self) -> None:
        if self._closed or self._local_operation or self._core_result is None or self._core_result.status != 'downloaded':
            return
        # Lock admission even while the confirmation's nested Qt event loop runs.
        self._local_operation = True
        self._render()
        confirmed = QMessageBox.question(self, '安装更新并重启？',
            '仅支持未连接、没有分析任务的空闲安装。\n确认后将正常退出 Echo、安装已下载更新并重新启动。',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirmed != QMessageBox.Yes or self._closed:
            self._local_operation = False
            if not self._closed:
                self._render()
            return
        self._generation += 1
        generation = self._generation
        reference = weakref.ref(self)

        def live():
            dialog = reference()
            return dialog if dialog is not None and isValid(dialog) and not dialog._closed and dialog._generation == generation else None

        def error(_code, message):
            dialog = live()
            if dialog is not None:
                dialog._generation += 1
                dialog._local_operation = False
                dialog._note = message
                dialog._render()

        def success(result):
            if not isinstance(result, InstallHandoffResult) or result.status != 'ready':
                error('prepare_failed', getattr(result, 'public_message', None) or '更新包复验失败，请重新检查并下载。')
                return
            # Run after the worker finished relay has retired. Closing inside
            # succeeded would leave that very relay as UNKNOWN gui_workers.
            def deliver():
                dialog = live()
                if dialog is not None:
                    dialog._generation += 1
                    dialog._local_operation = False
                    dialog.install_requested.emit(result)
                    if isValid(dialog) and not dialog._closed:
                        dialog._render()
            QTimer.singleShot(0, deliver)

        try:
            self._executor(self._facade.prepare_update_install, on_success=success, on_error=error)
        except Exception:
            error('prepare_submit_failed', '暂时无法复验更新，请重试。')

    def _apply_progress(self, report: Any) -> None:
        """Progress is only a percentage; completion requires a result."""
        if self._phase is not UpdatePhase.DOWNLOADING or type(report) is not int:
            return
        self._percent = max(self._percent or 0, min(99, max(0, report)))
        self._render()

    def _open_release(self) -> None:
        if self._closed or not _safe_release_url(self._release_url):
            return
        try:
            opened = QDesktopServices.openUrl(QUrl(self._release_url))
        except Exception:
            opened = False
        if not opened:
            self._open_failed = True
            self._render()


def _safe_release_url(url: object) -> bool:
    """Defend the browser boundary; never construct a URL from a version tag."""
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    prefix = "/lindreams/echo-chat-analyzer/releases/tag/"
    return (parsed.scheme == "https" and parsed.netloc == "github.com"
            and parsed.path.startswith(prefix) and bool(parsed.path[len(prefix):])
            and not parsed.query and not parsed.fragment)
