"""Main-window About and maintenance pages: release checks and local paths.

The About page combines product, update and read-only maintenance information
in the main window's page stack. This
module renders Facade outcomes; UpdateInfo, cache and installation policy
belong to the application service. Only a downloaded result confirms success;
progress percentages never imply installation or restart. Install and data
facts are read-only here: showing a path never creates, changes or clears it.
"""

from __future__ import annotations

import math
import sys
import weakref
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget, QMessageBox,
)
from shiboken6 import isValid

from .. import version
from ..application.facade import (
    FacadeError, InstallableUpdateResult, InstallHandoffResult, UpdateCheckResult,
)
from ..resources import user_data_root
from .theme import (
    HOME_COLOR_PAPER, HOME_COLOR_TEXT, HOME_COLOR_LEAF, HOME_COLOR_MUTED, HOME_COLOR_ACCENT, HOME_QSS,
    COLOR_BORDER, COLOR_ERROR, REFRESH_SANS_FAMILY,
)
from .workers import submit


CHECK_FAILED_MESSAGE = "暂时无法检查更新，请稍后手动重试。"
DOWNLOAD_FAILED_MESSAGE = "暂时无法下载更新，请稍后手动重试。"
_UNSAFE_RELEASE_NOTE = "发布页面暂不可用，请稍后重试。"

# Install and maintenance facts. Velopack writes ``.portable`` into a Portable
# extraction, while a Setup install keeps the running binary in ``current/``
# under a root that owns ``Update.exe``; sys.frozen alone is never enough.
PORTABLE_MARKER_FILE_NAME = ".portable"
UPDATER_FILE_NAME = "Update.exe"
CURRENT_DIRECTORY_NAME = "current"
UNINSTALL_TEXT = "卸载 Echo"

# Maintenance facts never create, change or clear anything they merely report.
MAINTENANCE_TITLE = "安装与维护"
PROGRAM_TITLE_SETUP = "程序安装目录"
PROGRAM_TITLE_PORTABLE = "程序目录（便携版）"
PROGRAM_TITLE_DEVELOPMENT = "程序位置"
DATA_TITLE = "本地数据目录"
OPEN_DIRECTORY_TEXT = "打开目录"
PORTABLE_REMOVAL_NOTE = "便携版不需要卸载：删除解压出的 Echo 文件夹即可移除程序。"
DATA_FOOTER_NOTE = "卸载程序不会自动删除独立保存的本地数据。"
OPEN_PROGRAM_FAILED_MESSAGE = "无法打开程序目录，请在文件管理器中手动查看。"
OPEN_DATA_FAILED_MESSAGE = "无法打开本地数据目录，请在文件管理器中手动查看。"

# Shared rhythm for the functional sections, local to the About surface.
ABOUT_ACTION_ROW_HEIGHT = 76
ABOUT_SECTION_GAP = 16


def _add_rule(layout: QVBoxLayout) -> QFrame:
    rule = QFrame()
    rule.setObjectName("aboutRule")
    rule.setFixedHeight(1)
    layout.addWidget(rule)
    return rule


class InstallKind(Enum):
    """How this process was installed, from on-disk layout facts."""

    SETUP = "setup"
    PORTABLE = "portable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class InstallLocation:
    """The install classification and the directory representing the program."""

    kind: InstallKind
    program_dir: Path | None = None


def detect_install_location(executable: str | Path, *, frozen: bool) -> InstallLocation:
    """Classify the running copy without trusting ``sys.frozen`` on its own.

    Only a frozen process can be an installed or unpacked Echo. A Setup install
    must additionally prove a ``current/`` binary under a root that owns
    ``Update.exe``; every other frozen layout is the Portable distribution, so
    the dialog never claims an uninstall entry that does not exist.
    """
    if not frozen:
        return InstallLocation(InstallKind.UNKNOWN)
    program_dir = Path(executable).resolve().parent
    root = program_dir.parent
    if ((root / PORTABLE_MARKER_FILE_NAME).exists()
            or (program_dir / PORTABLE_MARKER_FILE_NAME).exists()):
        return InstallLocation(InstallKind.PORTABLE, program_dir)
    if (program_dir.name.lower() == CURRENT_DIRECTORY_NAME
            and (root / UPDATER_FILE_NAME).is_file()):
        return InstallLocation(InstallKind.SETUP, root)
    return InstallLocation(InstallKind.PORTABLE, program_dir)


@dataclass(frozen=True, slots=True)
class MaintenanceView:
    """What the install/maintenance page shows. Pure data, no side effects."""

    program_dir: Path | None
    data_dir: Path | None
    program_title: str
    portable_note: str = ""
    show_open_program: bool = False
    show_open_data: bool = False
    show_uninstall: bool = False


def install_maintenance_view(
    kind: InstallKind, *, program_dir: Path | None, data_dir: Path | None,
) -> MaintenanceView:
    """Map one install identity to the rows and actions the page offers."""
    if kind is InstallKind.SETUP and program_dir is not None:
        return MaintenanceView(
            program_dir=program_dir, data_dir=data_dir,
            program_title=PROGRAM_TITLE_SETUP,
            show_open_program=True, show_open_data=data_dir is not None,
            show_uninstall=True)
    if kind is InstallKind.PORTABLE and program_dir is not None:
        return MaintenanceView(
            program_dir=program_dir, data_dir=data_dir,
            program_title=PROGRAM_TITLE_PORTABLE, portable_note=PORTABLE_REMOVAL_NOTE,
            show_open_program=True, show_open_data=data_dir is not None)
    return MaintenanceView(
        program_dir=None, data_dir=data_dir, program_title=PROGRAM_TITLE_DEVELOPMENT,
        show_open_data=data_dir is not None)


def _current_maintenance_view() -> MaintenanceView:
    """Resolve this process's facts; a convenience area must never raise."""
    try:
        location = detect_install_location(
            sys.executable, frozen=getattr(sys, "frozen", False) is True)
    except Exception:
        location = InstallLocation(InstallKind.UNKNOWN)
    try:
        data_dir: Path | None = user_data_root()
    except Exception:
        data_dir = None
    return install_maintenance_view(
        location.kind, program_dir=location.program_dir, data_dir=data_dir)


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
        text = "更新已下载完成。Echo 将关闭、安装更新并自动重启。仅支持未连接、无分析任务时安装。"
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


def _echo_page_stylesheet() -> str:
    """Reuse Home's fonts and palette, scoped to the single About surface."""
    return HOME_QSS.replace("echoHome", "echoAbout") + f"""
        QWidget#echoAbout QLabel, QWidget#echoAbout QPushButton {{
            font-family: {REFRESH_SANS_FAMILY}; font-size: 15px;
        }}
        QWidget#echoAbout QLabel#aboutTitle {{
            font-family: {REFRESH_SANS_FAMILY}; font-size: 32px; font-weight: 500;
        }}
        QWidget#echoAbout QLabel#aboutSecondary {{ color: {HOME_COLOR_MUTED}; }}
        QWidget#echoAbout QLabel#updateSection, QWidget#echoAbout QLabel#maintenanceSection {{
            font-size: 20px; font-weight: 500;
        }}
        QWidget#echoAbout QLabel#aboutError {{ color: {COLOR_ERROR}; }}
        QWidget#echoAbout QPushButton {{
            border: 1px solid {COLOR_BORDER}; padding: 8px 20px;
            min-height: 24px; text-decoration: none;
        }}
        QWidget#echoAbout QPushButton:hover, QWidget#echoAbout QPushButton:focus {{
            border-color: {HOME_COLOR_ACCENT}; text-decoration: none;
        }}
        QWidget#echoAbout QPushButton:disabled {{
            color: {HOME_COLOR_MUTED}; border-color: {COLOR_BORDER};
        }}
        QWidget#echoAbout QPushButton#aboutBack {{
            border: none; padding: 6px 0; font-size: 13px;
        }}
        QWidget#echoAbout QFrame#aboutRule {{ background: {COLOR_BORDER}; }}
        QWidget#echoAbout QProgressBar {{
            border: 1px solid {COLOR_BORDER}; border-radius: 0;
            background: {HOME_COLOR_PAPER};
        }}
        QWidget#echoAbout QProgressBar::chunk {{ background: {HOME_COLOR_ACCENT}; }}
    """




class MaintenanceSection(QWidget):
    """Read-only locations and actions inside the single About page.

    Read-only facts: showing a path never creates, changes or clears it, and a
    convenience action that fails reports here without escaping the window.
    """

    def __init__(self, view: MaintenanceView, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view = view
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ABOUT_SECTION_GAP)
        title = QLabel(MAINTENANCE_TITLE)
        title.setObjectName("maintenanceSection")
        layout.addWidget(title)
        rows = QWidget(self)
        rows_layout = QVBoxLayout(rows)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(0)
        layout.addWidget(rows)

        self.program_heading = QLabel(view.program_title)
        self.program_heading.setObjectName("aboutSection")
        self.open_program_button = QPushButton(OPEN_DIRECTORY_TEXT)
        self.open_program_button.setObjectName("openProgramDir")
        self.open_program_button.clicked.connect(self._open_program_directory)
        self._add_row(rows_layout, self.program_heading, self.open_program_button)
        _add_rule(rows_layout).setVisible(view.show_open_program)

        self.data_heading = QLabel(DATA_TITLE)
        self.data_heading.setObjectName("aboutSection")
        self.open_data_button = QPushButton(OPEN_DIRECTORY_TEXT)
        self.open_data_button.setObjectName("openDataDir")
        self.open_data_button.clicked.connect(self._open_data_directory)
        self._add_row(rows_layout, self.data_heading, self.open_data_button)
        _add_rule(rows_layout).setVisible(view.show_open_data)

        self.uninstall_button = QPushButton(UNINSTALL_TEXT)
        self.uninstall_button.setObjectName("uninstallEcho")
        self.uninstall_button.setEnabled(False)
        self.uninstall_button.setToolTip("当前安装身份或卸载器未通过验证。")
        uninstall_row = QWidget(self)
        uninstall_row.setMinimumHeight(ABOUT_ACTION_ROW_HEIGHT)
        uninstall_layout = QHBoxLayout(uninstall_row)
        uninstall_layout.setContentsMargins(0, 0, 0, 0)
        uninstall_layout.setSpacing(24)
        uninstall_info = QVBoxLayout()
        uninstall_info.setSpacing(6)
        uninstall_info.setAlignment(Qt.AlignVCenter)
        uninstall_title = QLabel(UNINSTALL_TEXT)
        uninstall_title.setObjectName("aboutSection")
        uninstall_info.addWidget(uninstall_title)
        self.footer_note = QLabel(DATA_FOOTER_NOTE)
        self.footer_note.setObjectName("aboutSecondary")
        self.footer_note.setWordWrap(True)
        uninstall_info.addWidget(self.footer_note)
        uninstall_layout.addLayout(uninstall_info, 1)
        uninstall_layout.addWidget(self.uninstall_button, alignment=Qt.AlignVCenter)
        rows_layout.addWidget(uninstall_row)
        uninstall_row.setVisible(view.show_uninstall)
        _add_rule(rows_layout).setVisible(view.show_uninstall)

        self.portable_note = QLabel(view.portable_note)
        self.portable_note.setObjectName("aboutSecondary")
        self.portable_note.setWordWrap(True)
        layout.addWidget(self.portable_note)

        self.status_label = QLabel()
        self.status_label.setObjectName("aboutError")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        if not view.show_uninstall:
            # Portable/development still explain data retention without an
            # uninstall action row or an invisible parent holding the note.
            uninstall_info.removeWidget(self.footer_note)
            layout.addWidget(self.footer_note)

        # The real path stays in the tooltip: the page never prints it.
        if view.program_dir is not None:
            self.open_program_button.setToolTip(str(view.program_dir))
        if view.data_dir is not None:
            self.open_data_button.setToolTip(str(view.data_dir))

        for widget, shown in (
            (self.program_heading, view.show_open_program),
            (self.open_program_button, view.show_open_program),
            (self.data_heading, view.show_open_data),
            (self.open_data_button, view.show_open_data),
            (self.uninstall_button, view.show_uninstall),
            (self.portable_note, bool(view.portable_note)),
        ):
            widget.setVisible(shown)
        self.status_label.setVisible(False)

    @staticmethod
    def _add_row(layout: QVBoxLayout, heading: QLabel, button: QPushButton) -> None:
        row = QHBoxLayout()
        row.setSpacing(24)
        heading.setFixedHeight(ABOUT_ACTION_ROW_HEIGHT)
        row.addWidget(heading, 1)
        row.addWidget(button, alignment=Qt.AlignVCenter)
        layout.addLayout(row)

    def _open_program_directory(self) -> None:
        if self._view.program_dir is None:
            return
        self._reveal_path(self._view.program_dir, OPEN_PROGRAM_FAILED_MESSAGE)

    def _open_data_directory(self) -> None:
        if self._view.data_dir is None:
            return
        self._reveal_path(self._view.data_dir, OPEN_DATA_FAILED_MESSAGE)

    def _reveal_path(self, path: Path, failure_message: str) -> None:
        try:
            opened = bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
        except Exception:
            opened = False
        self._report(not opened, failure_message)

    def _report(self, failed: bool, message: str) -> None:
        """A convenience action must never break the window it belongs to."""
        self.status_label.setText(message if failed else "")
        self.status_label.setVisible(failed)


class UpdatePage(QWidget):
    """Present Facade outcomes and request only user-confirmed preparation."""

    install_requested = Signal(object)
    uninstall_requested = Signal()
    back_requested = Signal()

    def __init__(self, facade: Any, parent: QWidget | None = None,
                 *, executor: Any = None) -> None:
        super().__init__(parent)
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
        self._maintenance = _current_maintenance_view()
        self._generation = 0
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(150)
        self._status_timer.timeout.connect(self._restore_status)
        self.setObjectName("echoAbout")
        self.setAttribute(Qt.WA_StyledBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        surface = QWidget()
        self.scroll_area.setWidget(surface)
        outer.addWidget(self.scroll_area)
        column = QVBoxLayout(surface)
        column.setContentsMargins(32, 46, 32, 24)
        column.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        self.page_content = QWidget(self)
        self.page_content.setMinimumWidth(680)
        self.page_content.setMaximumWidth(920)
        self.page_content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        row.addWidget(self.page_content, 100)
        row.addStretch(1)
        column.addLayout(row)
        column.addStretch(2)
        layout = QVBoxLayout(self.page_content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        self.back_button = QPushButton("← 返回首页")
        self.back_button.setObjectName("aboutBack")
        self.back_button.setCursor(Qt.PointingHandCursor)
        self.back_button.clicked.connect(self.back_requested)
        layout.addWidget(self.back_button, alignment=Qt.AlignLeft)
        title = QLabel("关于余音")
        title.setObjectName("aboutTitle")
        product = QHBoxLayout()
        product.addWidget(title)
        product.addStretch(1)
        self.version_label = QLabel(f"当前版本  {version.APP_VERSION}")
        self.version_label.setObjectName("aboutSecondary")
        self.version_label.setTextFormat(Qt.PlainText)
        product.addWidget(self.version_label, alignment=Qt.AlignVCenter)
        layout.addLayout(product)
        description = QLabel("把聊天记录，整理成可以慢慢回看的报告。\n本地读取 · 不上传聊天数据")
        description.setObjectName("aboutSecondary")
        description.setWordWrap(True)
        layout.addWidget(description)
        _add_rule(layout)
        update_group = QWidget(self.page_content)
        update_layout = QVBoxLayout(update_group)
        update_layout.setContentsMargins(0, 0, 0, 0)
        update_layout.setSpacing(ABOUT_SECTION_GAP)
        layout.addWidget(update_group)
        update_title = QLabel("软件更新")
        update_title.setObjectName("updateSection")
        update_layout.addWidget(update_title)
        self.status_label = QLabel()
        self.status_label.setTextFormat(Qt.PlainText)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(ABOUT_ACTION_ROW_HEIGHT)
        update_rows = QWidget(update_group)
        update_rows_layout = QVBoxLayout(update_rows)
        update_rows_layout.setContentsMargins(0, 0, 0, 0)
        update_rows_layout.setSpacing(0)
        update_layout.addWidget(update_rows)
        update_row = QHBoxLayout()
        update_row.setSpacing(24)
        update_row.addWidget(self.status_label, 1)
        update_rows_layout.addLayout(update_row)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("updateProgress")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setRange(0, 0)
        update_rows_layout.addWidget(self.progress_bar)
        actions = QHBoxLayout()
        self.release_button = QPushButton("查看发布页面 ↗")
        self.release_button.setObjectName("releaseLink")
        self.release_button.setCursor(Qt.PointingHandCursor)
        self.release_button.clicked.connect(self._open_release)
        actions.addWidget(self.release_button)
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
        update_row.addLayout(actions)
        _add_rule(update_rows_layout)
        self.maintenance_section = MaintenanceSection(self._maintenance, self.page_content)
        layout.addWidget(self.maintenance_section)
        checker = getattr(self._facade, 'can_uninstall_setup', None)
        try:
            can_uninstall = self._maintenance.show_uninstall and callable(checker) and checker()
        except Exception:
            can_uninstall = False
        self.maintenance_section.uninstall_button.setEnabled(bool(can_uninstall))
        self.maintenance_section.uninstall_button.setToolTip(
            '卸载程序并保留本地报告与配置。' if can_uninstall else '当前安装身份或卸载器未通过验证。')
        self.maintenance_section.uninstall_button.clicked.connect(self.uninstall_requested.emit)
        # Polish the complete widget tree, as Home does. Applying scoped font
        # rules before adding/reparenting the content can retain generic fonts.
        self.setStyleSheet(_echo_page_stylesheet())
        self._render()
        self._restore_status()

    def closeEvent(self, event: Any) -> None:
        """Retire callbacks and polling only when the owner closes, not on navigation."""
        self._closed = True
        self._generation += 1
        self._status_timer.stop()
        super().closeEvent(event)

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
        self, generation: int, deliver: Callable[["UpdatePage", Any], None],
    ) -> tuple[Callable[[Any], None], Callable[[str, str], None], Callable[[Any], None]]:
        """Return callbacks that drop anything a stale or closed dialog should not show.

        The worker relays these back onto the GUI thread; the dialog itself may
        already be closed or deleted by then.
        """
        reference = weakref.ref(self)

        def live() -> "UpdatePage | None":
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
        confirmation = QMessageBox(QMessageBox.Question, '安装更新并重启？',
            'Echo 将关闭、安装更新并自动重启。\n安装前会清理当前业务；清理失败则取消安装。',
            QMessageBox.Yes | QMessageBox.No, self)
        # About's transparent child backgrounds otherwise inherit the system's
        # dark surface while retaining Echo's ink text. Own this dialog's colors.
        confirmation.setStyleSheet(f"""
            QMessageBox, QMessageBox QLabel {{
                background: {HOME_COLOR_PAPER}; color: {HOME_COLOR_TEXT};
                font-family: {REFRESH_SANS_FAMILY}; font-size: 15px;
            }}
            QMessageBox QPushButton {{
                background: {HOME_COLOR_PAPER}; color: {HOME_COLOR_TEXT};
                border: 1px solid {COLOR_BORDER}; padding: 8px 20px;
            }}
            QMessageBox QPushButton:hover, QMessageBox QPushButton:focus {{
                background: {HOME_COLOR_LEAF}; border-color: {HOME_COLOR_ACCENT};
            }}
        """)
        confirmation.button(QMessageBox.Yes).setText('安装并重启')
        confirmation.button(QMessageBox.No).setText('取消')
        confirmation.setDefaultButton(QMessageBox.No)
        confirmation.setEscapeButton(QMessageBox.No)
        confirmed = confirmation.exec()
        confirmation.deleteLater()
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
