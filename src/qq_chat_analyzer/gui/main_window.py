"""Main window hosting the home, workspace, processing, and local data pages."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QSizePolicy,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..resources import default_echo_icon_path
from .home_page import HomePage
from .update_dialog import UpdatePage
from .local_data_page import LocalDataPage
from .processing_page import ProcessingPage
from .qq_workspace import QQWorkspace
from .shutdown import ShutdownProtocol
from .theme import (
    STATUS_STYLE_BASE,
    STATUS_STYLE_ERROR,
    WINDOW_CLIENT_SEPARATOR_STYLE,
    WINDOW_TITLE_STYLE,
)
from .wechat_workspace import WeChatWorkspace
from .workers import shutdown as shutdown_workers
from .workers import submit
from .workers import is_idle as workers_idle
from ..application.facade import ChatSource, InstallHandoffResult


def _confirm_setup_uninstall(parent) -> str | None:
    dialog = QMessageBox(parent)
    dialog.setWindowTitle('卸载 Echo')
    dialog.setIcon(QMessageBox.Warning)
    dialog.setText('移除 Echo 程序和快捷方式，并选择如何处理本地数据。')
    dialog.setInformativeText(
        '两种选择都会清除已保存的数据库密钥、连接凭据、受管理的 QQ 工作副本、临时数据、日志和更新记录，包括已识别的旧版本残留。\n'
        '“清除”还会永久删除 Echo 内的报告和配置，无法撤销；另存文件和自定义 QQ／微信目录不受影响。\n'
        '本次打开后若已连接过 QQ／微信，请先关闭并重新打开 Echo，不连接来源再卸载。')
    keep = dialog.addButton('卸载，保留报告和普通设置', QMessageBox.AcceptRole)
    purge = dialog.addButton('卸载并清除 Echo 本地数据', QMessageBox.DestructiveRole)
    cancel = dialog.addButton(QMessageBox.Cancel)
    dialog.setDefaultButton(cancel)
    dialog.setEscapeButton(cancel)
    dialog.exec()
    return 'keep' if dialog.clickedButton() is keep else 'purge' if dialog.clickedButton() is purge else None


WINDOW_TITLE = "\u4f59\u97f3 Echo"
_HOME_LABEL = "\u9996\u9875"
_BACK_LABEL = "\u8fd4\u56de\u9009\u62e9"
_OPEN_ECHO_LABEL = "\u67e5\u770b Echo"
_OPEN_REPORT_DIRECTORY_LABEL = "\u6253\u5f00\u62a5\u544a\u6240\u5728\u76ee\u5f55"
_ERROR_TITLE = "\u5206\u6790\u5931\u8d25"
_PREPARING = "\u6b63\u5728\u51c6\u5907..."
_CANCEL_ANALYSIS = "\u53d6\u6d88\u5206\u6790"
_REPORT_DIRECTORY_OPEN_FAILED = "\u65e0\u6cd5\u6253\u5f00\u62a5\u544a\u76ee\u5f55\u3002"

# Report actions own this one-line feedback copy. Success and
# progress stay quiet (header line only); a failure is never silent: it also
# raises one modal warning named by the _FAILURE_TITLE_* constants below.
_ANALYSIS_CANCELLED = "分析已取消。"
_REPORT_SAVED = "报告已保存"
_REPORT_UNSAVED = "分析完成，报告暂未保存。"
_ANALYSIS_COMPLETED = "分析完成"
_OPEN_REPORT_FAILED = "无法打开 Echo 报告。"
_REPORT_MISSING = "报告文件不存在，可能已被移动或删除。"
_REPORT_DIRECTORY_MISSING = "报告目录不存在，可能已被移动或删除。"
_FAILURE_TITLE_OPEN_REPORT = "无法打开报告"
_FAILURE_TITLE_OPEN_DIRECTORY = "无法打开报告目录"

_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.main_window")

HOME_PAGE_INDEX = 0
QQ_WORKSPACE_INDEX = 1
WECHAT_WORKSPACE_INDEX = 2
PROCESSING_PAGE_INDEX = 3
LOCAL_DATA_PAGE_INDEX = 4


class MainWindow(QMainWindow):
    """Own the pages and route navigation signals between them."""

    def __init__(
        self,
        facade: Any,
        parent: QWidget | None = None,
        executor: Any = None,
        directory_opener: Any = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowIcon(QIcon(str(default_echo_icon_path())))
        self._facade = facade
        self._executor = executor or submit
        self.about_page: UpdatePage | None = None
        self._current_report_path: Path | None = None
        self._current_report_directory: Path | None = None
        self._auto_opened_outcome_key: tuple[int, str] | None = None
        self._report_opener = _open_report_path
        self._directory_opener = directory_opener or _open_directory_path
        self._active_source: str | None = None
        self._shutdown_protocol = ShutdownProtocol()
        self._update_install_token: str | None = None
        self._uninstall_active = False
        self._uninstall_token: str | None = None
        self._uninstall_timer = QTimer(self)
        self._uninstall_timer.setInterval(100)
        self._uninstall_timer.timeout.connect(self._poll_uninstall_shutdown)

        container = QWidget()
        layout = QVBoxLayout(container)
        self._page_layout = layout
        self._workspace_margins = layout.contentsMargins()
        self._workspace_spacing = layout.spacing()

        # Create pages (order matters for stack indices)
        self.home_page = HomePage()
        self.qq_workspace = QQWorkspace(facade, executor=executor)
        self.wechat_workspace = WeChatWorkspace(facade, executor=executor)
        self.processing_page = ProcessingPage()
        self.processing_status_label = self.processing_page.status_label
        self._cancel_analysis_button = self.processing_page.cancel_button
        self.processing_page.cancel_requested.connect(self.cancel_analysis)
        self.local_data_page = LocalDataPage(
            facade, executor=executor,
            report_opener=lambda path: self._report_opener(path),
        )

        # Header row
        header_layout = QHBoxLayout()
        self._home_button = QPushButton(_HOME_LABEL)
        self._home_button.clicked.connect(self.show_home_page)
        self._home_button.setVisible(False)
        header_layout.addWidget(self._home_button)
        self._title_label = QLabel(WINDOW_TITLE)
        self._title_label.setStyleSheet(WINDOW_TITLE_STYLE)
        header_layout.addWidget(self._title_label)
        header_layout.addStretch(1)
        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setVisible(False)
        self._status_label.setStyleSheet(STATUS_STYLE_BASE)
        header_layout.addWidget(self._status_label)
        layout.addLayout(header_layout)

        # Stacked pages
        self.stack = QStackedWidget()
        self.stack.addWidget(self.home_page)          # 0
        self.stack.addWidget(self.qq_workspace)        # 1
        self.stack.addWidget(self.wechat_workspace)    # 2
        self.stack.addWidget(self.processing_page)     # 3
        self.stack.addWidget(self.local_data_page)     # 4
        layout.addWidget(self.stack, stretch=1)

        self._open_echo_button = QPushButton(_OPEN_ECHO_LABEL)
        self._open_echo_button.setEnabled(False)
        self._open_echo_button.setVisible(False)
        self._open_echo_button.clicked.connect(self.open_echo_report)
        self._open_report_directory_button = QPushButton(
            _OPEN_REPORT_DIRECTORY_LABEL
        )
        self._open_report_directory_button.setEnabled(False)
        self._open_report_directory_button.setVisible(False)
        self._open_report_directory_button.clicked.connect(
            self.open_echo_report_directory
        )
        report_actions_layout = QHBoxLayout()
        report_actions_layout.addWidget(self._open_echo_button)
        report_actions_layout.addWidget(self._open_report_directory_button)
        report_actions_layout.addStretch(1)
        layout.addLayout(report_actions_layout)

        self._back_button = QPushButton(_BACK_LABEL)
        self._back_button.setVisible(False)
        self._back_button.clicked.connect(self._on_back_clicked)
        layout.addWidget(self._back_button)

        self.setCentralWidget(container)

        # Overlay the client edge without consuming any page layout space.
        # Window decorations, dragging, and resizing remain owned by Windows.
        self._client_separator = QFrame(container)
        self._client_separator.setObjectName("echoClientSeparator")
        self._client_separator.setStyleSheet(WINDOW_CLIENT_SEPARATOR_STYLE)
        self._client_separator.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.setMinimumSize(800, 600)
        self.resize(1200, 760)
        self.stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        # Home navigation
        self.home_page.navigate_requested.connect(self._on_navigate_requested)

        # Connect workspace signals
        self.qq_workspace.analysis_started.connect(lambda: self._start_workspace_analysis("qq"))
        self.qq_workspace.analysis_phase_changed.connect(lambda phase: self._handle_analysis_phase("qq", phase))
        self.qq_workspace.analysis_succeeded.connect(self.show_outcome)
        self.qq_workspace.analysis_failed.connect(self.show_error)
        self.qq_workspace.status_changed.connect(self.show_status)

        self.wechat_workspace.analysis_started.connect(lambda: self._start_workspace_analysis("wechat"))
        self.wechat_workspace.analysis_phase_changed.connect(lambda phase: self._handle_analysis_phase("wechat", phase))
        self.wechat_workspace.analysis_succeeded.connect(self.show_outcome)
        self.wechat_workspace.analysis_failed.connect(self.show_error)
        self.wechat_workspace.status_changed.connect(self.show_status)

        # Start at home
        self.stack.currentChanged.connect(self._sync_page_chrome)
        self.show_home_page()
        self._sync_page_chrome(HOME_PAGE_INDEX)

    # ---------------------------------------------------------------- navigation

    def _sync_page_chrome(self, index: int) -> None:
        """Home and About fill the window; workspaces retain their existing chrome."""
        is_brand_page = isinstance(self.stack.widget(index), (HomePage, UpdatePage))
        if index != PROCESSING_PAGE_INDEX:
            self.processing_page.stop()
        self._title_label.setVisible(not is_brand_page)
        if is_brand_page:
            self._home_button.setVisible(False)
            self._page_layout.setContentsMargins(0, 0, 0, 0)
            self._page_layout.setSpacing(0)
        else:
            self._page_layout.setContentsMargins(self._workspace_margins)
            self._page_layout.setSpacing(self._workspace_spacing)

    def show_home_page(self) -> None:
        """Navigate to the home page."""
        self.stack.setCurrentIndex(HOME_PAGE_INDEX)
        self._home_button.setVisible(False)
        self._back_button.setVisible(False)
        self._clear_echo_report_entry()

    def show_qq_workspace(self) -> None:
        """Navigate to the QQ workspace."""
        self.stack.setCurrentIndex(QQ_WORKSPACE_INDEX)
        self._home_button.setVisible(True)
        self._back_button.setVisible(False)
        self._clear_echo_report_entry()
        self.qq_workspace.refresh_connection_status(load_sessions_on_ready=True)

    def show_wechat_workspace(self) -> None:
        """Navigate to the WeChat workspace."""
        self.stack.setCurrentIndex(WECHAT_WORKSPACE_INDEX)
        self._home_button.setVisible(True)
        self._back_button.setVisible(False)
        self._clear_echo_report_entry()
        self.wechat_workspace.refresh_connection_status(load_sessions_on_ready=True)

    def show_local_data_page(self) -> None:
        """Navigate to the local data management page."""
        self.stack.setCurrentIndex(LOCAL_DATA_PAGE_INDEX)
        self._home_button.setVisible(True)
        self._back_button.setVisible(False)
        self._clear_echo_report_entry()
        self.local_data_page.refresh()

    def show_processing_page(self) -> None:
        """Isolate one active analysis from all selection controls."""
        self.processing_page.start()
        self.stack.setCurrentIndex(PROCESSING_PAGE_INDEX)
        self._home_button.setVisible(False)
        self._back_button.setVisible(False)
        self._clear_echo_report_entry()
        self._cancel_analysis_button.setVisible(True)

    def _start_workspace_analysis(self, source: str) -> None:
        self._active_source = source
        self.show_processing_page()

    def _handle_analysis_phase(self, source: str, phase: object) -> None:
        if source == self._active_source and self.stack.currentIndex() == PROCESSING_PAGE_INDEX:
            self.processing_page.set_phase(phase)

    def _on_navigate_requested(self, intent: str) -> None:
        """Handle home page navigation signals."""
        if intent == "qq":
            self.navigate_to_qq()
        elif intent == "wechat":
            self.navigate_to_wechat()
        elif intent == "local_data":
            self.show_local_data_page()
        elif intent == "about":
            self.show_about_page()

    def show_about_page(self) -> None:
        """Navigate offline; keep one update owner for the window's lifetime."""
        if self.about_page is None:
            self.about_page = UpdatePage(self._facade, self.stack, executor=self._executor)
            self.stack.addWidget(self.about_page)
            self.about_page.back_requested.connect(self.show_home_page)
            self.about_page.install_requested.connect(self.request_update_install)
            self.about_page.uninstall_requested.connect(self.request_setup_uninstall)
        self.stack.setCurrentWidget(self.about_page)
        self._home_button.setVisible(False)
        self._back_button.setVisible(False)
        self._clear_echo_report_entry()

    def request_setup_uninstall(self) -> None:
        """One confirmation, then the existing shutdown owner; no forced exit."""
        if (self._uninstall_active or self._shutdown_protocol.started
                or self._update_install_token is not None or self.about_page is None):
            return
        button = self.about_page.maintenance_section.uninstall_button
        self._uninstall_active = True
        button.setEnabled(False)
        try:
            if not self._facade.can_uninstall_setup():
                QMessageBox.warning(self, '无法卸载 Echo', '当前安装身份或卸载器无效，无法卸载。')
                return
            if not workers_idle() or self.about_page._local_operation:
                QMessageBox.warning(self, '暂不能卸载 Echo', '请等待后台任务完成，再重试卸载。')
                return
            cleanup_mode = _confirm_setup_uninstall(self)
            if cleanup_mode is None:
                return
            # A modal dialog runs a nested event loop: check work again.
            if not workers_idle() or self.about_page._local_operation:
                QMessageBox.warning(self, '暂不能卸载 Echo', '请等待后台任务完成，再重试卸载。')
                return
            prepared = self._facade.prepare_setup_uninstall(cleanup_mode)
            if prepared.status != 'ready' or not prepared.token:
                QMessageBox.warning(self, '无法卸载 Echo', prepared.public_message or '当前无法准备卸载。')
                return
            self._uninstall_token = prepared.token
            self.centralWidget().setEnabled(False)
            self.about_page.maintenance_section._report(True, '正在安全退出，准备卸载…')
            self._uninstall_started_at = time.monotonic()
            self.begin_shutdown()
            self._uninstall_timer.start()
        except Exception as error:
            from ..application.facade import FacadeError
            message = error.public_message if isinstance(error, FacadeError) else '无法准备卸载，请稍后重试。'
            QMessageBox.warning(self, '无法卸载 Echo', message)
        finally:
            if self._uninstall_token is None:
                self._uninstall_active = False
                try:
                    button.setEnabled(self._facade.can_uninstall_setup())
                except Exception:
                    button.setEnabled(False)

    def _poll_uninstall_shutdown(self) -> None:
        if not self._shutdown_protocol.finished:
            if time.monotonic() - self._uninstall_started_at < self._shutdown_protocol.wait_seconds:
                return
            self._uninstall_timer.stop()
            self._uninstall_token = None
            self._uninstall_failed('安全退出超时，未启动卸载。')
            return
        self._uninstall_timer.stop()
        token, self._uninstall_token = self._uninstall_token, None
        try:
            result = self._facade.handoff_setup_uninstall(token, self._shutdown_protocol.result)
            if result.status == 'started':
                self.close()
                return
            message = result.public_message or '未取得完整安全退出证据，未启动卸载。'
        except Exception as error:
            from ..application.facade import FacadeError
            message = error.public_message if isinstance(error, FacadeError) else '卸载交接失败，未确认卸载。'
        self._uninstall_failed(message)

    def _uninstall_failed(self, message: str) -> None:
        # Resource owners have stopped. Keep the surface disabled; the window
        # close control remains available, but stopped services cannot restart.
        self.about_page.maintenance_section._report(True, message)
        QMessageBox.warning(self, 'Echo 卸载未完成', message + '\nEcho 已停止后台服务，请关闭并重新打开后重试。')

    def request_update_install(self, prepared: InstallHandoffResult) -> None:
        """GUI-thread, user-confirmed intent only. Normal close owns cleanup."""
        if (self._uninstall_active or self._shutdown_protocol.started or self._update_install_token is not None
                or not isinstance(prepared, InstallHandoffResult)
                or prepared.status != 'ready' or not prepared.token):
            return
        if not workers_idle():
            QMessageBox.warning(self, '暂不能安装更新', '请等待后台任务完成，再重试安装。')
            return
        self._update_install_token = prepared.token
        self.close()

    def finish_update_handoff(self) -> InstallHandoffResult | None:
        """Entry point only, after the same ShutdownProtocol has completed."""
        token, self._update_install_token = self._update_install_token, None
        if token is None:
            return None
        result = self._shutdown_protocol.result
        if not self._shutdown_protocol.finished or not result.can_apply_update:
            return InstallHandoffResult('denied', public_message='未取得完整安全退出证据，更新未安装。')
        return self._facade.handoff_update_install(token, result)

    def navigate_to_qq(self) -> None:
        """Navigate to the QQ workspace."""
        self._active_source = "qq"
        self.qq_workspace.select_source(_qq_source())
        self.show_qq_workspace()

    def navigate_to_wechat(self) -> None:
        """Navigate to the WeChat workspace."""
        self._active_source = "wechat"
        self.wechat_workspace.select_source(_wechat_source())
        self.show_wechat_workspace()

    def _on_back_clicked(self) -> None:
        """Return to the workspace the user came from, else the home page."""
        self._show_active_workspace_or_home()

    def _show_active_workspace_or_home(self) -> None:
        """Return to the active workspace, or the home page when none is active."""
        if self._active_source == "qq":
            self.show_qq_workspace()
        elif self._active_source == "wechat":
            self.show_wechat_workspace()
        else:
            self.show_home_page()

    # ---------------------------------------------------------------- analysis lifecycle

    def cancel_analysis(self) -> None:
        """Cancel the active analysis."""
        self.processing_page.stop()
        self.qq_workspace.cancel_analysis()
        self.wechat_workspace.cancel_analysis()
        # Cancellation returns to the existing selection; entering the source
        # through show_*_workspace would probe readiness and reload sessions.
        if self._active_source == "qq":
            self.stack.setCurrentIndex(QQ_WORKSPACE_INDEX)
        elif self._active_source == "wechat":
            self.stack.setCurrentIndex(WECHAT_WORKSPACE_INDEX)
        else:
            self.show_home_page()
        self._home_button.setVisible(self._active_source in ("qq", "wechat"))
        self._back_button.setVisible(False)
        self._set_status_message(_ANALYSIS_CANCELLED)


    def show_status(self, message: str) -> None:
        """Preserve legacy string status; typed phases own the processing copy.

        Each workspace shows its own connection copy on the page, so this line
        keeps the legacy text without claiming the visible feedback line. While
        a report feedback line is on screen it owns the header: a later
        connection status must neither overwrite it nor duplicate the
        connection copy up here.
        """
        self.processing_page.set_report_progress(message)
        if self._status_label.isVisibleTo(self):
            return
        self._status_label.setText(message)

    def show_outcome(self, outcome: Any) -> None:
        """Finish one analysis, open Echo, and return to the active workspace."""
        self.processing_page.stop()
        _LOGGER.info(
            "[gui] show_outcome report_path=%s report_directory=%s",
            getattr(outcome, "report_path", None),
            getattr(outcome, "report_directory", None),
        )
        self._set_echo_report_path(
            getattr(outcome, "report_path", None),
            getattr(outcome, "report_directory", None),
        )
        retention_warning = getattr(outcome, "retention_warning", "")
        if getattr(outcome, "report_directory", None) is not None:
            self._set_status_message(retention_warning or _REPORT_SAVED)
        elif getattr(outcome, "report_path", None) is not None:
            self._set_status_message(_REPORT_UNSAVED)
        else:
            self._set_status_message(_ANALYSIS_COMPLETED)
        view = getattr(outcome, "echo_report_view", None)
        chapter = getattr(view, "stickers", None)
        if getattr(outcome, "source", None) is ChatSource.QQ and chapter and chapter.assets:
            from collections import Counter
            counts = Counter(asset.status for asset in chapter.assets)
            shown = counts["available"] + counts["preview"]
            self._set_status_message(
                f"{self._status_label.text()} · 表情包图片 {shown}/{len(chapter.assets)}（发送统计已保留）")
        outcome_key = (
            id(outcome),
            str(getattr(outcome, "report_path", "")),
        )
        if (
            self._current_report_path is not None
            and self._auto_opened_outcome_key != outcome_key
        ):
            _LOGGER.info("[gui] show_outcome opening echo report once")
            self._auto_opened_outcome_key = outcome_key
            self.open_echo_report()
        if retention_warning and self._status_label.text() != retention_warning:
            self._status_label.setText(f"{retention_warning}\n{self._status_label.text()}")
        self._return_to_workspace_after_success()

    def _return_to_workspace_after_success(self) -> None:
        """Return to the active workspace without clearing the Echo entry."""
        self._home_button.setVisible(True)
        self._back_button.setVisible(False)
        if self._active_source == "qq":
            self.stack.setCurrentIndex(QQ_WORKSPACE_INDEX)
        elif self._active_source == "wechat":
            self.stack.setCurrentIndex(WECHAT_WORKSPACE_INDEX)
        else:
            self.stack.setCurrentIndex(HOME_PAGE_INDEX)

    # ---------------------------------------------------------------- status feedback

    def _set_status_message(self, message: str, *, failed: bool = False) -> None:
        """Show one non-modal status line; an empty message hides it again.

        Success and progress copy stays on this quiet header line. Failures use
        the highlighted variant and are announced by :meth:`_announce_failure`
        as well, so a failed click is never silent.
        """
        self._status_label.setStyleSheet(
            STATUS_STYLE_ERROR if failed else STATUS_STYLE_BASE
        )
        self._status_label.setText(message)
        self._status_label.setVisible(bool(message))

    def _announce_failure(self, title: str, message: str) -> None:
        """Make one failed user action unmissable: status line plus one dialog."""
        self._set_status_message(message, failed=True)
        QMessageBox.warning(self, title, message)

    # ---------------------------------------------------------------- echo report

    def open_echo_report(self) -> None:
        """Open the report from the latest successful outcome."""
        report_path = self._current_report_path
        _LOGGER.info("[gui] open_echo_report path=%s", report_path)
        if report_path is None:
            self._clear_echo_report_entry()
            return
        if not _is_file(report_path):
            # The entry was offered but its report is gone: drop the stale
            # entry and tell the user instead of returning silently.
            self._clear_echo_report_entry()
            self._announce_failure(_FAILURE_TITLE_OPEN_REPORT, _REPORT_MISSING)
            return
        try:
            opened = self._report_opener(report_path)
        except Exception:
            opened = False
        if opened is False:
            self._announce_failure(_FAILURE_TITLE_OPEN_REPORT, _OPEN_REPORT_FAILED)

    def open_echo_report_directory(self) -> None:
        """Open the directory containing the latest successful report."""
        directory = self._current_report_directory
        if directory is None:
            self._clear_echo_report_entry()
            return
        if not _is_directory(directory):
            # Same rule as the report itself: a stale entry is reported, not
            # silently swallowed.
            self._clear_echo_report_entry()
            self._announce_failure(
                _FAILURE_TITLE_OPEN_DIRECTORY, _REPORT_DIRECTORY_MISSING
            )
            return
        try:
            opened = self._directory_opener(directory)
        except Exception:
            opened = False
        if opened is False:
            self._announce_failure(
                _FAILURE_TITLE_OPEN_DIRECTORY, _REPORT_DIRECTORY_OPEN_FAILED
            )

    def _set_echo_report_path(
        self,
        report_path: Any,
        report_directory: Any = None,
    ) -> None:
        try:
            candidate = Path(report_path).resolve()
        except (OSError, TypeError, ValueError):
            self._clear_echo_report_entry()
            return
        available = _is_file(candidate)
        self._current_report_path = candidate if available else None
        directory = None
        if available:
            if report_directory is not None:
                try:
                    directory = Path(report_directory).resolve()
                except (OSError, TypeError, ValueError):
                    directory = None
                if directory is not None and not _is_directory(directory):
                    directory = None
            if directory is None:
                directory = candidate.parent
        self._current_report_directory = directory
        self._open_echo_button.setEnabled(available)
        self._open_echo_button.setVisible(available)
        directory_available = directory is not None
        self._open_report_directory_button.setEnabled(directory_available)
        self._open_report_directory_button.setVisible(directory_available)

    def _clear_echo_report_entry(self) -> None:
        self._current_report_path = None
        self._current_report_directory = None
        self._auto_opened_outcome_key = None
        self._open_echo_button.setEnabled(False)
        self._open_echo_button.setVisible(False)
        self._open_report_directory_button.setEnabled(False)
        self._open_report_directory_button.setVisible(False)
        # Leaving the report surface clears its one-line feedback too, so a
        # stale action message never follows the user to another page.
        self._set_status_message("")

    # ---------------------------------------------------------------- error handling

    def show_error(self, code: str, message: str) -> None:
        """Show a user-safe message. Never a traceback."""
        self.processing_page.stop()
        if self.stack.currentIndex() == PROCESSING_PAGE_INDEX:
            self._show_active_workspace_or_home()
        self._set_status_message(message, failed=True)
        QMessageBox.warning(self, _ERROR_TITLE, message)

    # ---------------------------------------------------------------- lifecycle

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._client_separator.setGeometry(0, 0, self.centralWidget().width(), 1)
        self._client_separator.raise_()

    def closeEvent(self, event: Any) -> None:
        """Close quickly; one bounded protocol owns the owned-process cleanup.

        ``facade.shutdown`` owns the exit ordering: it cleans the Direct DB
        plaintext snapshot (recovering any orphan generation) before it stops
        NapCat / the QQ runtime. The GUI thread must not wait for that work -
        the window has to disappear at once - and it must not start a second,
        racing cleanup either. So the work runs on the window's single-flight
        shutdown protocol, and the desktop entry point waits on that same
        protocol before the process is allowed to leave.
        """
        self._uninstall_timer.stop()
        if self.about_page is not None:
            self.about_page.close()
        self.processing_page.close()
        self.qq_workspace.cancel_analysis()
        self.wechat_workspace.cancel_analysis()
        self.begin_shutdown()
        super().closeEvent(event)
        _quit_application()

    def begin_shutdown(self) -> bool:
        """Start the single-flight shutdown protocol; later calls are ignored."""
        if self._shutdown_protocol.started:
            return False
        self.wechat_workspace.cancel_connection()
        workers_idle = shutdown_workers()
        shutdown = getattr(self._facade, "shutdown", None)

        def owner():
            from ..application.facade import ShutdownResult, ShutdownStatus, ShutdownStepResult

            result = shutdown() if callable(shutdown) else None
            if not isinstance(result, ShutdownResult) or not result.steps:
                result = ShutdownResult((
                    ShutdownStepResult('facade', ShutdownStatus.UNKNOWN),
                ))
            return ShutdownResult(result.steps + (
                ShutdownStepResult('gui_workers', ShutdownStatus.SUCCESS
                                   if workers_idle is True
                                   else ShutdownStatus.UNKNOWN),
            ))

        return self._shutdown_protocol.begin(owner)

    def await_shutdown(self, timeout: float | None = None) -> bool:
        """Wait, bounded, for the started shutdown protocol to finish."""
        return self._shutdown_protocol.wait(timeout)

    @property
    def shutdown_protocol(self) -> ShutdownProtocol:
        """Return the protocol the desktop entry point waits on."""
        return self._shutdown_protocol


def _quit_application() -> None:
    """End the Qt event loop deterministically after the main window closes."""
    app = QApplication.instance()
    if app is not None:
        app.quit()


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _is_directory(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _open_local_path(path: Path) -> bool:
    """Open one local file or directory with the operating system."""
    resolved_path = path.resolve()
    if os.name == "nt":
        os.startfile(str(resolved_path))
        return True
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved_path)))


def _open_report_path(path: Path) -> bool:
    """Open one local HTML file with the operating system browser."""
    return _open_local_path(path)


def _open_directory_path(path: Path) -> bool:
    """Open one local directory in the operating system file manager."""
    return _open_local_path(path)


def _qq_source() -> Any:
    """Return the ChatSource.QQ value without importing the facade module."""
    from ..application.facade import ChatSource

    return ChatSource.QQ


def _wechat_source() -> Any:
    """Return the ChatSource.WECHAT value without importing the facade module."""
    from ..application.facade import ChatSource

    return ChatSource.WECHAT
