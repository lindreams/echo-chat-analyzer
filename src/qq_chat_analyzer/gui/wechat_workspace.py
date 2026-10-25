"""WeChat workspace: connection, setup guide, and session analysis."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..application.facade import (
    ChatSource,
    FacadeError,
    WeChatConnectionProgress,
    WeChatEnvironmentConfig,
)
from ..resources import default_wechat_login_guide_path
from .progress_track import ConnectionProgressTrack
from .session_analysis_panel import SessionAnalysisPanel, SessionConnectionBar
from .theme import (
    WECHAT_GUIDE_STYLE as GUIDE_STYLE,
    WECHAT_GUIDE_STYLE_EMPHASIS as GUIDE_STYLE_EMPHASIS,
    WECHAT_STATUS_STYLE,
    WECHAT_SETUP_QSS,
)
from .wechat_setup_dialog import WeChatSetupDialog
from .workers import submit


_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.wechat_workspace")

_WECHAT_CONNECT_LABEL = "连接微信"
_CANCEL_CONNECTION_LABEL = "取消连接"
_RESTART_CONNECTION_LABEL = "重新开始"
_WECHAT_SETUP_LABEL = "微信环境设置..."
_WECHAT_STATUS_DISCONNECTED = "微信未连接"
_WECHAT_STATUS_CONNECTING = "正在准备微信连接"
_WECHAT_STATUS_CONNECTED = "微信已连接。"
_WECHAT_CONNECTING = _WECHAT_STATUS_CONNECTING
_WECHAT_CONNECT_FAILED = "微信连接未成功"
_WECHAT_DISCONNECT_LABEL = "退出连接"
_WECHAT_DISCONNECTING = "正在退出微信连接..."
_WECHAT_DISCONNECT_FAILED = "微信退出连接失败"
_WECHAT_CONNECT_RETRY_HINT = (
    "请完全关闭并重新打开微信，保持在登录界面后返回 Echo 重试连接。"
)
_WECHAT_GUIDE_STATUS = "微信连接准备中。"
_WECHAT_GUIDE_KEY = _WECHAT_STATUS_CONNECTING
_WECHAT_GUIDE_WARNING = (
    "请按 Echo 的当前提示操作；等待 Echo 提示可以登录后，再登录。"
)
_WECHAT_READY_FOR_LOGIN = "现在可以登录微信。"
_WECHAT_READY_WARNING = "请在微信登录界面完成登录，Echo 会自动继续连接。"
_WECHAT_CREDENTIAL_RECEIVED = "正在连接微信"
_WECHAT_PROGRESS_STATUS = {
    WeChatConnectionProgress.PREPARING: _WECHAT_STATUS_CONNECTING,
    WeChatConnectionProgress.WAITING_FOR_WECHAT_EXIT: "请完全关闭微信",
    WeChatConnectionProgress.WAITING_FOR_WECHAT_START: "现在请打开微信",
    WeChatConnectionProgress.READY_FOR_LOGIN: "现在可以登录微信了",
    WeChatConnectionProgress.CREDENTIAL_RECEIVED: _WECHAT_CREDENTIAL_RECEIVED,
}
_WECHAT_PROGRESS_INSTRUCTIONS = {
    WeChatConnectionProgress.PREPARING: "正在检查微信连接状态，请稍候。",
    WeChatConnectionProgress.WAITING_FOR_WECHAT_EXIT: "请完全关闭微信。",
    WeChatConnectionProgress.WAITING_FOR_WECHAT_START: "现在请打开微信，但先不要登录。",
    WeChatConnectionProgress.READY_FOR_LOGIN: _WECHAT_READY_FOR_LOGIN,
    WeChatConnectionProgress.CREDENTIAL_RECEIVED: "已获取微信连接信息，正在继续连接……",
}
_WECHAT_PROGRESS_EXPLANATIONS = {
    WeChatConnectionProgress.PREPARING:
        "暂时不需要操作微信，Echo 检查完成后会告诉你下一步怎么做。",
    WeChatConnectionProgress.WAITING_FOR_WECHAT_EXIT: (
        "关闭微信窗口后，如果微信仍在后台运行，\n"
        "请在任务栏右下角找到微信图标并完全关闭微信。\n\n"
        "完全关闭后不用点击 Echo 中的任何按钮，Echo 会自动继续。"
    ),
    WeChatConnectionProgress.WAITING_FOR_WECHAT_START: (
        "打开微信后，请停留在登录界面。\n"
        "如果看到“进入微信”或登录按钮，先不要点击。\n\n"
        "Echo 检测到微信后，会自动告诉你什么时候可以登录。\n"
        "不需要返回 Echo 点击下一步。"
    ),
    WeChatConnectionProgress.READY_FOR_LOGIN: (
        "请按照右侧示意图，在微信中点击“进入微信”完成登录。"
    ),
    WeChatConnectionProgress.CREDENTIAL_RECEIVED: "请稍候，无需操作。",
}
# The guided setup's five stages, in the order the user meets them.
_WECHAT_STAGES = ("准备", "关闭微信", "打开微信", "登录", "连接")
_WECHAT_PROGRESS_STAGE = {
    WeChatConnectionProgress.PREPARING: 0,
    WeChatConnectionProgress.WAITING_FOR_WECHAT_EXIT: 1,
    WeChatConnectionProgress.WAITING_FOR_WECHAT_START: 2,
    WeChatConnectionProgress.READY_FOR_LOGIN: 3,
    WeChatConnectionProgress.CREDENTIAL_RECEIVED: 4,
}
_WECHAT_GUIDE_NOTE = (
    "聊天数据仅在本机读取，不上传、不保存额外副本。"
)
_WECHAT_GUIDE_DIRECTORY_MISSING = (
    "如未在常用位置找到微信数据位置，请按以下步骤获取微信数据目录："
)
_WECHAT_GUIDE_DIRECTORY_NOTE = (
    "1. 进入微信：设置 → 存储位置 → 更改；\n"
    "2. 右键 xwechat_files，选择 复制地址；\n"
    "3. 完全关闭微信，并重新打开微信，使微信回到登录界面；\n"
    "4. 返回 Echo，将复制的地址直接粘贴到上方输入框；\n"
    "5. 点击 Save；\n"
    "6. Save 后 Echo 会开始准备连接，请暂时不要登录；\n"
    "7. 等待 Echo 提示可以登录后，再从微信登录界面登录。"
)
_WECHAT_DETECTED = "✓ 已检测到微信数据位置，无需手动选择路径。"
_WECHAT_NOT_DETECTED = "未在常用位置找到微信数据位置。"
_WECHAT_MULTIPLE_DETECTED = (
    "检测到多个微信聊天记录位置，请选择其中一个。"
)
_WECHAT_READING_DATABASE = "正在读取微信数据库..."
_WECHAT_LOADING_SESSIONS = "正在加载微信会话..."
_WECHAT_WAITING_LOGIN = "等待微信登录"
_WECHAT_DATABASE_FAILED = "微信数据库读取失败"
_WECHAT_SESSIONS_FAILED = "微信会话加载失败"
# Raised by the provider when the captured key cannot open the selected
# session.db: never a plain query failure, because the user has to act on it.
_WECHAT_DATABASE_UNREADABLE_CODE = "wechat_database_unreadable"
_WECHAT_INTERNAL_TERMS = (
    "db_key",
    "dbkey",
    "hook",
    "runtime",
    "dll",
    "wcdb",
    "密钥",
)
_WECHAT_GUIDE_IMAGE_WIDTH = 200
_WECHAT_GUIDE_IMAGE_HEIGHT = 275
_WECHAT_SETUP_REPAIR_CODES = {
    "wechat_environment_missing",
    "wechat_invalid_environment",
    "wechat_database_unreadable",
    "database_not_found",
    "wechat_database_error",
    "wcdb_helper_not_found",
    "wcdb_library_not_found",
}
_CONNECTED_PREFIX = "\U0001F7E2 "
_DISCONNECTED_PREFIX = "\U0001F534 "
_CONNECTION_STATUS_LOADING = "正在检测 {source} 连接状态..."
_SESSION_CONNECTING_TITLE = "正在连接数据源..."
_SESSION_READING_TITLE = "正在读取聊天数据..."


class _WeChatProgressTrack(ConnectionProgressTrack):
    """The guided setup's own five-stage trail, in the shared Echo language."""

    STAGES = _WECHAT_STAGES


class WeChatWorkspace(QWidget):
    """WeChat workspace: connection, setup guide, and session analysis.

    This workspace owns the WeChat connection and analysis lifecycle:
    status through ``get_connection_status(WECHAT)``, one-click
    connect through data-root detection plus environment/key acquisition,
    then session loading and analysis through the shared panel.
    """

    analysis_started = Signal()
    analysis_succeeded = Signal(object)
    analysis_failed = Signal(str, str)
    analysis_phase_changed = Signal(object)
    status_changed = Signal(str)

    def __init__(
        self,
        facade: Any,
        parent: QWidget | None = None,
        executor: Any = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("wechatWorkspace")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(WECHAT_SETUP_QSS)
        self._facade = facade
        self._executor = executor or submit
        self._wechat_connect_pending = False
        # True once this process captured a database key, so changing the data
        # directory retries verification without another WeChat login.
        self._wechat_key_captured = False
        self._wechat_login_progress = WeChatConnectionProgress.PREPARING
        self._connection_task: Any = None
        self._wechat_attempt_generation = 0
        self._connection_cancel_event: threading.Event | None = None
        self._wechat_guide_image_path = default_wechat_login_guide_path()
        self._sessions_loaded = False

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self._connection_surface = QFrame()
        self._connection_surface.setObjectName("wechatConnectionSurface")
        self._connection_layout = QVBoxLayout(self._connection_surface)
        self._connection_layout.setSpacing(24)
        main_layout.addWidget(self._connection_surface)

        # The five-stage trail replaces the top status line while the guided
        # setup runs; the status label keeps owning the other states.
        self._progress_track = _WeChatProgressTrack()
        self._progress_track.setVisible(False)
        self._connection_layout.addWidget(self._progress_track)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setVisible(False)
        self._status_label.setStyleSheet(WECHAT_STATUS_STYLE)

        self._wechat_connect_button = QPushButton(_WECHAT_CONNECT_LABEL)
        self._wechat_connect_button.setVisible(False)
        self._wechat_connect_button.clicked.connect(self.connect_wechat)
        self._wechat_connect_button.setMinimumHeight(34)

        self._wechat_disconnect_button = QPushButton(_WECHAT_DISCONNECT_LABEL)
        self._wechat_disconnect_button.setVisible(False)
        self._wechat_disconnect_button.clicked.connect(self.disconnect_wechat)
        self._wechat_disconnect_button.setMinimumHeight(34)
        self._connection_bar = SessionConnectionBar(
            self._status_label, self._wechat_disconnect_button,
        )
        self._connection_layout.addWidget(self._connection_bar)

        self._wechat_setup_button = QPushButton(_WECHAT_SETUP_LABEL)
        self._wechat_setup_button.setObjectName("wechatSettings")
        self._wechat_setup_button.setVisible(False)
        self._wechat_setup_button.clicked.connect(self.open_wechat_setup)
        self._wechat_setup_button.setMinimumHeight(34)

        self._wechat_guide_image_label = QLabel("")
        self._wechat_guide_image_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self._wechat_guide_image_label.setMaximumWidth(
            _WECHAT_GUIDE_IMAGE_WIDTH
        )
        self._wechat_guide_image_label.setVisible(False)

        self._wechat_guide_label = QLabel("")
        self._wechat_guide_label.setObjectName("wechatCurrentAction")
        self._wechat_guide_label.setWordWrap(True)
        self._wechat_guide_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self._wechat_guide_label.setVisible(False)
        self._wechat_guide_label.setStyleSheet(GUIDE_STYLE)

        self._wechat_guide_key_label = QLabel("")
        self._wechat_guide_key_label.setObjectName("wechatPrivacy")
        self._wechat_guide_key_label.setWordWrap(True)
        self._wechat_guide_key_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self._wechat_guide_key_label.setVisible(False)
        self._wechat_guide_key_label.setStyleSheet(GUIDE_STYLE_EMPHASIS)

        self._wechat_guide_note_label = QLabel("")
        self._wechat_guide_note_label.setWordWrap(True)
        self._wechat_guide_note_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self._wechat_guide_note_label.setVisible(False)
        self._wechat_guide_note_label.setStyleSheet(GUIDE_STYLE)

        self._wechat_guide_text_column = QVBoxLayout()
        self._wechat_guide_text_column.setSpacing(20)
        self._wechat_guide_text_column.addWidget(
            self._wechat_guide_label,
        )
        self._wechat_guide_text_column.addWidget(
            self._wechat_guide_note_label,
        )
        self._wechat_guide_text_column.addWidget(
            self._wechat_guide_key_label,
        )
        self._wechat_guide_text_column.addStretch(1)

        self._wechat_guide_row = QHBoxLayout()
        self._wechat_guide_row.setSpacing(32)
        self._wechat_guide_row.addLayout(
            self._wechat_guide_text_column,
            stretch=1,
        )
        self._wechat_guide_row.addWidget(
            self._wechat_guide_image_label,
            stretch=0,
            alignment=Qt.AlignmentFlag.AlignTop,
        )
        self._connection_layout.addLayout(self._wechat_guide_row)
        actions = QHBoxLayout()
        actions.setSpacing(16)
        actions.addWidget(self._wechat_connect_button)
        actions.addStretch(1)
        actions.addWidget(self._wechat_setup_button)
        self._connection_layout.addLayout(actions)
        for button in (self._wechat_connect_button, self._wechat_disconnect_button,
                       self._wechat_setup_button):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.setCursor(Qt.CursorShape.PointingHandCursor)

        self.session_panel = SessionAnalysisPanel()
        self.session_panel.setObjectName("wechatSessionPanel")
        self.session_panel.configure(
            facade,
            ChatSource.WECHAT,
            executor=self._executor,
        )
        main_layout.addWidget(self.session_panel, stretch=1)

        self.session_panel.analysis_started.connect(self._on_analysis_started)
        self.session_panel.analysis_succeeded.connect(self.analysis_succeeded.emit)
        self.session_panel.analysis_failed.connect(self.analysis_failed.emit)
        self.session_panel.analysis_phase_changed.connect(self.analysis_phase_changed.emit)
        self.session_panel.status_changed.connect(self._on_panel_status)
        self.session_panel.workspace_width_changed.connect(self._update_setup_spacing)

        self.session_panel.show_unconnected_placeholder()
        self._show_wechat_idle()
        self._update_setup_spacing()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_setup_spacing()

    def _update_setup_spacing(self) -> None:
        # Ready workspaces align the compact status row with the session panel.
        ready = self._sessions_loaded
        horizontal = max(24, (self.width() - self.session_panel.workspace_width_limit()) // 2) if ready else max(24, min(96, round(self.width() * 0.08)))
        vertical = 12 if ready else max(20, min(48, round(self.height() * 0.06)))
        self._connection_bar.set_compact(ready)
        self._connection_layout.setSpacing(0 if ready else 24)
        self._connection_layout.setContentsMargins(
            horizontal, vertical, horizontal, 0 if ready else 20,
        )

    # ---------------------------------------------------------------- public API

    def select_source(self, source: Any) -> None:
        """Configure the panel for WeChat and reset transient state."""
        if self._connection_task is not None:
            return
        self._wechat_attempt_generation += 1
        self.session_panel.configure(
            self._facade,
            ChatSource.WECHAT,
            executor=self._executor,
        )
        self._clear_sessions()
        self._set_stage(None)
        self._wechat_disconnect_button.setVisible(False)

    def _clear_sessions(self) -> None:
        self._sessions_loaded = False
        self.session_panel.cancel_analysis()
        self.session_panel.clear()

    def refresh_connection_status(
        self,
        *,
        load_sessions_on_ready: bool = False,
    ) -> None:
        """Ask the facade for WeChat's connection state and render it."""
        if self._connection_task is not None:
            return
        self._wechat_attempt_generation += 1
        generation = self._wechat_attempt_generation
        self._clear_sessions()
        self._status_label.setVisible(True)
        self._show_wechat_idle()
        self._status_label.setToolTip("")
        self.session_panel.show_unconnected_placeholder()
        if load_sessions_on_ready:
            self._executor(
                lambda: self._facade.get_connection_status(ChatSource.WECHAT)
                if generation == self._wechat_attempt_generation else None,
                on_success=lambda status: self._show_connection_status(
                    status,
                    load_sessions_on_ready,
                ) if generation == self._wechat_attempt_generation else None,
                on_error=lambda code, message: self._handle_connection_status_error(
                    code,
                    message,
                ) if generation == self._wechat_attempt_generation else None,
            )

    def _handle_connection_status_error(self, code: str, message: str) -> None:
        self._set_stage(None)
        self._status_label.setText(_DISCONNECTED_PREFIX + message)
        self._status_label.setToolTip("")
        self._status_label.setVisible(True)
        self.session_panel.show_disconnected_placeholder()
        self._wechat_connect_button.setVisible(True)
        self._wechat_setup_button.setVisible(True)
        self._wechat_disconnect_button.setVisible(False)
        self.session_panel.update_analyze_enabled()

    def _show_connection_status(
        self,
        status: Any,
        load_sessions_on_ready: bool,
        attempt_generation: int | None = None,
    ) -> None:
        """Render WeChat's connection status returned by the facade."""
        if (
            attempt_generation is not None
            and attempt_generation != self._wechat_attempt_generation
        ):
            return
        self._set_stage(None)
        available = bool(getattr(status, "available", False))
        prefix = _CONNECTED_PREFIX if available else _DISCONNECTED_PREFIX
        message = (
            _WECHAT_STATUS_CONNECTED
            if available
            else (_WECHAT_STATUS_DISCONNECTED if attempt_generation is None
                  else _wechat_unavailable_message(status))
        )
        action_hint = getattr(status, "action_hint", "") or ""
        self._status_label.setText(f"{prefix}{message}")
        self._status_label.setToolTip(action_hint)
        self._status_label.setVisible(True)

        needs_setup = not (
            getattr(status, "runtime_available", False)
            and getattr(status, "data_found", False)
        )
        self._wechat_setup_button.setVisible(not available and needs_setup)
        if available:
            self._hide_wechat_guide()
        elif attempt_generation is None:
            self._show_wechat_idle()
            if needs_setup:
                self._wechat_setup_button.setVisible(True)
        else:
            self._show_wechat_guide()
        self._wechat_connect_button.setText(_WECHAT_CONNECT_LABEL)
        self._wechat_connect_button.setVisible(not available)
        self._wechat_connect_button.setEnabled(True)
        self._wechat_disconnect_button.setVisible(available)
        self._wechat_disconnect_button.setEnabled(available)

        if load_sessions_on_ready:
            self.status_changed.emit(message)

        if available and load_sessions_on_ready:
            self._status_label.setText(_WECHAT_LOADING_SESSIONS)
            self.session_panel.show_reading_placeholder()
            self._load_sessions(attempt_generation=attempt_generation)
        elif not available:
            self.session_panel.show_disconnected_placeholder()

    # ---------------------------------------------------------------- guide

    def _set_stage(self, stage: int | None) -> None:
        """Move the five-stage trail, or hand the top line back to the status.

        ``None`` leaves the guided setup: the trail hides and the status label
        (owned by the caller) speaks again.
        """
        self._update_setup_spacing()
        if stage is None:
            self._progress_track.setVisible(False)
            return
        self._progress_track.set_stage(stage)
        self._progress_track.setVisible(True)
        self._status_label.setVisible(False)

    def _show_wechat_idle(self) -> None:
        """Present an invitation to connect, before any connection attempt."""
        self._set_stage(None)
        self._status_label.setText(_WECHAT_STATUS_DISCONNECTED)
        self._status_label.setVisible(True)
        self._wechat_guide_label.setText(_WECHAT_CONNECT_LABEL)
        self._wechat_guide_note_label.setText(
            "点击“连接微信”后，Echo 会一步一步提示你完成连接。"
        )
        self._wechat_guide_key_label.setText(_WECHAT_GUIDE_NOTE)
        for label in (self._wechat_guide_label, self._wechat_guide_note_label,
                      self._wechat_guide_key_label):
            label.setStyleSheet(GUIDE_STYLE)
            label.setVisible(True)
        self._hide_wechat_guide_image()
        self._wechat_connect_button.setVisible(True)
        try:
            configured = self._facade.get_wechat_setup_status().configured
        except Exception:
            configured = False
        self._wechat_setup_button.setVisible(not configured)

    def _show_wechat_guide(
        self,
        *,
        include_directory_help: bool = False,
        progress: WeChatConnectionProgress = WeChatConnectionProgress.PREPARING,
        current_step_only: bool = False,
    ) -> None:
        """Show the current connection action or the existing fallback guide."""
        if include_directory_help:
            self._set_stage(None)
            self._wechat_setup_button.setVisible(True)
            self._wechat_guide_label.setText(_WECHAT_GUIDE_DIRECTORY_MISSING)
            self._wechat_guide_note_label.setText(_WECHAT_GUIDE_DIRECTORY_NOTE)
            self._wechat_guide_note_label.setStyleSheet(GUIDE_STYLE_EMPHASIS)
            self._wechat_guide_key_label.clear()
            self._wechat_guide_key_label.setVisible(False)
        elif current_step_only:
            # One step at a time: no repeated privacy line under the step.
            self._wechat_setup_button.setVisible(False)
            self._wechat_guide_label.setText(_WECHAT_PROGRESS_INSTRUCTIONS[progress])
            self._wechat_guide_note_label.setText(_WECHAT_PROGRESS_EXPLANATIONS[progress])
            self._wechat_guide_note_label.setStyleSheet(GUIDE_STYLE)
            self._wechat_guide_key_label.clear()
            self._wechat_guide_key_label.setVisible(False)
        else:
            self._set_stage(None)
            ready = progress is WeChatConnectionProgress.READY_FOR_LOGIN
            self._wechat_guide_label.setText(
                "微信连接已准备好。" if ready else _WECHAT_GUIDE_STATUS
            )
            self._wechat_guide_note_label.setText(
                _WECHAT_PROGRESS_INSTRUCTIONS[progress]
            )
            self._wechat_guide_note_label.setStyleSheet(GUIDE_STYLE)
            self._wechat_guide_key_label.setText(
                _WECHAT_READY_WARNING if ready else _WECHAT_GUIDE_WARNING
            )
            self._wechat_guide_key_label.setStyleSheet(GUIDE_STYLE_EMPHASIS)
            self._wechat_guide_key_label.setVisible(True)
        self._wechat_guide_label.setVisible(True)
        self._wechat_guide_note_label.setVisible(True)

        if (
            not include_directory_help
            and progress is WeChatConnectionProgress.READY_FOR_LOGIN
        ):
            self._refresh_wechat_guide_image()
        else:
            self._hide_wechat_guide_image()

    def _refresh_wechat_guide_image(self) -> None:
        """Load the optional guide image without making connection depend on it."""
        if not self._wechat_guide_image_path.is_file():
            self._hide_wechat_guide_image()
            return
        try:
            pixmap = QPixmap(str(self._wechat_guide_image_path))
        except Exception:
            pixmap = QPixmap()
        if pixmap.isNull():
            self._hide_wechat_guide_image()
            return
        scaled = pixmap.scaled(
            _WECHAT_GUIDE_IMAGE_WIDTH,
            _WECHAT_GUIDE_IMAGE_HEIGHT,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._wechat_guide_image_label.setPixmap(scaled)
        self._wechat_guide_image_label.setVisible(True)

    def _hide_wechat_guide_image(self) -> None:
        self._wechat_guide_image_label.clear()
        self._wechat_guide_image_label.setVisible(False)

    def _hide_wechat_guide(self) -> None:
        self._wechat_guide_label.clear()
        self._wechat_guide_label.setVisible(False)
        self._wechat_guide_note_label.clear()
        self._wechat_guide_note_label.setVisible(False)
        self._wechat_guide_key_label.clear()
        self._wechat_guide_key_label.setVisible(False)
        self._hide_wechat_guide_image()

    # ---------------------------------------------------------------- connect

    def connect_wechat(
        self,
        detect_data_root: Any = None,
        detect_data_roots: Any = None,
    ) -> None:
        """Connect WeChat in one click, asking for a directory only if needed."""
        if self._connection_task is not None:
            self.cancel_connection()
            return

        self._wechat_attempt_generation += 1
        self._clear_sessions()
        self._set_stage(None)
        detect_roots = detect_data_roots or self._facade.detect_wechat_data_roots
        try:
            roots = [Path(value) for value in detect_roots() or ()]
        except Exception:
            roots = []

        self._wechat_connect_pending = True
        if len(roots) == 1:
            self._wechat_connect_pending = False
            self._status_label.setVisible(True)
            self._status_label.setText(_WECHAT_DETECTED)
            self._status_label.setToolTip("")
            self._start_wechat_connect(
                WeChatEnvironmentConfig(data_root=roots[0])
            )
            return

        self._status_label.setVisible(True)
        if len(roots) > 1:
            self._status_label.setText(_WECHAT_MULTIPLE_DETECTED)
            self.open_wechat_setup(data_roots=roots)
            return

        self._status_label.setText(_WECHAT_NOT_DETECTED)
        self._show_wechat_guide(include_directory_help=True)
        self.open_wechat_setup()

    def _start_wechat_connect(
        self,
        config: Any,
        *,
        reuse_key: bool = False,
    ) -> None:
        """Run save-then-key for one config, off the UI thread.

        ``reuse_key`` skips the key capture for a retry after the user picked
        another data directory: the key captured earlier in this process is
        still the current one, so no new WeChat login is needed.
        """
        self._wechat_attempt_generation += 1
        attempt_generation = self._wechat_attempt_generation
        self._clear_sessions()
        cancel_event = threading.Event()
        self._connection_cancel_event = cancel_event
        self._wechat_login_progress = WeChatConnectionProgress.PREPARING
        self._wechat_connect_button.setText(_CANCEL_CONNECTION_LABEL)
        self._wechat_connect_button.setEnabled(True)
        self._status_label.setText(_WECHAT_CONNECTING)
        self._status_label.setToolTip("")
        self._set_stage(_WECHAT_PROGRESS_STAGE[self._wechat_login_progress])
        self._show_wechat_guide(current_step_only=True)
        self.session_panel.show_connecting_placeholder()
        self.status_changed.emit(_WECHAT_CONNECTING)

        task = self._executor(
            lambda report: self._connect_wechat_operation(
                config,
                report,
                capture_key=not reuse_key,
                cancel_event=cancel_event,
            ),
            on_success=lambda status: (
                self._after_wechat_key_acquired(status, attempt_generation)
                if attempt_generation == self._wechat_attempt_generation
                else None
            ),
            on_error=lambda code, message: (
                self._handle_wechat_connect_error(code, message)
                if attempt_generation == self._wechat_attempt_generation
                else None
            ),
            on_progress=lambda progress: (
                self._handle_wechat_connect_progress(progress)
                if attempt_generation == self._wechat_attempt_generation
                else None
            ),
            on_finished=lambda: self._finish_wechat_connect(
                attempt_generation=attempt_generation,
            ),
        )
        self._connection_task = task

    def _connect_wechat_operation(
        self,
        config: Any,
        progress: Any = None,
        *,
        capture_key: bool = True,
        cancel_event: threading.Event | None = None,
    ) -> Any:
        """Save the directory, then acquire the key. Runs off the UI thread."""
        def check_cancelled():
            if cancel_event is not None and cancel_event.is_set():
                raise FacadeError(code="wechat_key_cancelled", public_message="微信连接已取消。")
        check_cancelled()
        self._facade.setup_wechat_environment(config)
        check_cancelled()
        if capture_key:
            self._facade.acquire_wechat_db_key(progress=progress, cancel_event=cancel_event)
        check_cancelled()
        if progress is not None:
            progress(_WECHAT_READING_DATABASE)
        return self._facade.get_connection_status(ChatSource.WECHAT)

    def _finish_wechat_connect(
        self,
        task: Any = None,
        attempt_generation: int | None = None,
    ) -> None:
        """Clean up after the WeChat connection attempt."""
        if (
            attempt_generation is not None
            and attempt_generation != self._wechat_attempt_generation
        ):
            return
        if task is not None and self._connection_task is not task:
            return
        self._connection_task = None
        self._wechat_connect_button.setEnabled(True)
        connected = (
            self._status_label.text().startswith(_CONNECTED_PREFIX)
            or self._status_label.text() == _WECHAT_LOADING_SESSIONS
        )
        self._wechat_connect_button.setVisible(not connected)

    def _after_wechat_key_acquired(
        self,
        status: Any,
        attempt_generation: int | None = None,
    ) -> None:
        if (
            attempt_generation is not None
            and attempt_generation != self._wechat_attempt_generation
        ):
            return
        self._wechat_key_captured = True
        self._show_connection_status(
            status,
            load_sessions_on_ready=True,
            attempt_generation=attempt_generation,
        )

    def _handle_wechat_connect_progress(
        self, progress: WeChatConnectionProgress | str,
    ) -> None:
        """Only an application readiness milestone can invite a login."""
        _LOGGER.debug("[wechat gui] received progress: %s", progress)
        if progress == _WECHAT_READING_DATABASE:
            self._status_label.setText(_WECHAT_READING_DATABASE)
            self._hide_wechat_guide()
            # Reading the database is the tail of the final "连接" stage.
            self._set_stage(
                _WECHAT_PROGRESS_STAGE[WeChatConnectionProgress.CREDENTIAL_RECEIVED]
            )
            self.session_panel.show_reading_placeholder()
            return
        if not isinstance(progress, WeChatConnectionProgress):
            return
        if self._wechat_login_progress is WeChatConnectionProgress.CREDENTIAL_RECEIVED:
            return

        self._wechat_login_progress = progress
        text = _WECHAT_PROGRESS_STATUS[progress]
        self._show_wechat_guide(progress=progress, current_step_only=True)
        self.session_panel.show_connecting_placeholder()
        self._set_stage(_WECHAT_PROGRESS_STAGE[progress])
        self._status_label.setText(text)
        self.status_changed.emit(text)

    def _handle_wechat_connect_error(self, code: str, message: str) -> None:
        """Show the classified application failure without flattening it."""
        self._set_stage(None)
        self._hide_wechat_guide()
        self._wechat_setup_button.setVisible(code in _WECHAT_SETUP_REPAIR_CODES)
        if code == _WECHAT_DATABASE_UNREADABLE_CODE:
            self._offer_wechat_directory_reselection(message)
            return
        detail = message or ""
        lowered = detail.lower()
        titles = {
            "wechat_environment_missing": "微信连接环境不完整",
            "wechat_not_running": "微信未启动",
            "wechat_waiting_login": "等待微信登录",
            "wechat_hook_failed": "无法获取微信登录密钥",
            "wechat_process_incompatible": "无法获取微信登录密钥",
            "wechat_key_not_captured": "无法获取微信登录密钥",
            "wechat_key_timeout": "等待微信登录超时",
            "wechat_key_unavailable": "无法获取微信登录密钥",
            "key_timeout": "等待微信登录超时",
            "database_not_found": _WECHAT_DATABASE_FAILED,
            "wechat_database_error": _WECHAT_DATABASE_FAILED,
            "wechat_invalid_environment": _WECHAT_DATABASE_FAILED,
            "query_failed": _WECHAT_DATABASE_FAILED,
            "wcdb_helper_not_found": _WECHAT_DATABASE_FAILED,
            "wcdb_library_not_found": _WECHAT_DATABASE_FAILED,
        }
        if code not in titles and any(
            term in lowered for term in _WECHAT_INTERNAL_TERMS
        ):
            detail = ""
        text = detail or _WECHAT_CONNECT_RETRY_HINT
        self._status_label.setText(
            _DISCONNECTED_PREFIX + titles.get(code, _WECHAT_CONNECT_FAILED)
        )
        self._status_label.setToolTip(text)
        self._status_label.setVisible(True)
        self.session_panel.show_disconnected_placeholder()
        self._set_restart_action()
        self.status_changed.emit(text)

    def _set_restart_action(self) -> None:
        self._wechat_connect_button.setText(_RESTART_CONNECTION_LABEL)
        self._wechat_connect_button.setEnabled(True)
        self._wechat_connect_button.setVisible(True)
        self._wechat_disconnect_button.setVisible(False)

    def disconnect_wechat(self) -> None:
        """Release the current WeChat connection and return to reconnect."""
        if self._connection_task is not None:
            self.cancel_connection()
            return
        _LOGGER.info("[wechat gui] disconnect_wechat requested")
        self._wechat_attempt_generation += 1
        generation = self._wechat_attempt_generation
        self._clear_sessions()
        self._wechat_disconnect_button.setEnabled(False)
        self._set_stage(None)
        self._status_label.setVisible(True)
        self._status_label.setText(_WECHAT_DISCONNECTING)
        self._status_label.setToolTip("")
        self._hide_wechat_guide()
        self.status_changed.emit(_WECHAT_DISCONNECTING)
        self._connection_task = self._executor(
            lambda: self._facade.disconnect_wechat()
            if generation == self._wechat_attempt_generation else None,
            on_success=lambda status: self._after_wechat_disconnect(status)
            if generation == self._wechat_attempt_generation else None,
            on_error=lambda code, message: self._handle_wechat_disconnect_error(
                code,
                message,
            ) if generation == self._wechat_attempt_generation else None,
            on_finished=lambda: self._finish_wechat_disconnect()
            if generation == self._wechat_attempt_generation else None,
        )

    def _after_wechat_disconnect(self, status: Any) -> None:
        # Disconnecting releases the stored key, so the next attempt must
        # capture a fresh one instead of reusing the process-local key.
        self._wechat_key_captured = False
        self._show_connection_status(status, False)

    def _finish_wechat_disconnect(self) -> None:
        self._connection_task = None
        self._wechat_disconnect_button.setEnabled(True)

    def _handle_wechat_disconnect_error(self, code: str, message: str) -> None:
        self._set_stage(None)
        self._status_label.setText(
            _DISCONNECTED_PREFIX + _WECHAT_DISCONNECT_FAILED
        )
        self._status_label.setToolTip(message)
        self._status_label.setVisible(True)
        self.session_panel.show_disconnected_placeholder()
        self._set_restart_action()
        self.status_changed.emit(message)

    def cancel_connection(self) -> None:
        """Cancel an in-flight WeChat connection."""
        self._wechat_attempt_generation += 1
        self._clear_sessions()
        if self._connection_cancel_event is not None:
            cancel = getattr(self._facade, "cancel_wechat_connection", None)
            if callable(cancel):
                cancel(self._connection_cancel_event)
            else:
                self._connection_cancel_event.set()
            self._connection_cancel_event = None
        if self._connection_task is not None:
            cancel = getattr(self._connection_task, "cancel", None)
            if callable(cancel):
                cancel()
        self._connection_task = None
        self._wechat_connect_pending = False
        self._set_stage(None)
        self._hide_wechat_guide()
        self._wechat_connect_button.setText(_WECHAT_CONNECT_LABEL)
        self._wechat_connect_button.setEnabled(True)
        self._wechat_disconnect_button.setVisible(False)
        self._status_label.setText("连接已取消，可以重新开始。")
        self._status_label.setVisible(True)
        self.status_changed.emit("连接已取消，可以重新开始。")

    def cancel_analysis(self) -> None:
        """Cancel the active analysis."""
        self.session_panel.cancel_analysis()

    # ---------------------------------------------------------------- sessions

    def _load_sessions(self, *, attempt_generation: int | None = None) -> None:
        generation = self._wechat_attempt_generation if attempt_generation is None else attempt_generation

        def is_current() -> bool:
            return generation == self._wechat_attempt_generation

        self._executor(
            lambda: self._load_verified_sessions() if is_current() else None,
            on_success=lambda sessions: (
                self._handle_sessions_loaded(sessions) if is_current() else None
            ),
            on_error=lambda code, message: (
                self._handle_session_error(code, message) if is_current() else None
            ),
        )

    def _load_verified_sessions(self) -> Any:
        """Verify the current key against the database, then list sessions.

        Runs off the UI thread. Verification comes first so a key that cannot
        open the selected ``session.db`` never reaches ``list_sessions``, and
        never ends as a plain read failure the user cannot act on.
        """
        self._facade.verify_wechat_database()
        return self._facade.list_sessions(ChatSource.WECHAT)

    def _handle_sessions_loaded(self, sessions: Any) -> None:
        self._sessions_loaded = True
        self._set_stage(None)
        self.session_panel.populate_sessions(sessions)
        self._status_label.setText(_CONNECTED_PREFIX + _WECHAT_STATUS_CONNECTED)
        self._status_label.setToolTip("")
        self._status_label.setVisible(True)
        self._hide_wechat_guide()
        self._wechat_connect_button.setVisible(False)
        self._wechat_setup_button.setVisible(False)
        self._wechat_disconnect_button.setVisible(True)
        self._update_setup_spacing()

    def _handle_session_error(self, code: str, message: str) -> None:
        self._sessions_loaded = False
        self._set_stage(None)
        self._wechat_setup_button.setVisible(code in _WECHAT_SETUP_REPAIR_CODES)
        if code == _WECHAT_DATABASE_UNREADABLE_CODE:
            self._offer_wechat_directory_reselection(message)
            return
        self.session_panel.show_disconnected_placeholder()
        database_codes = {
            "database_not_found",
            "key_unavailable",
            "query_failed",
            "wechat_database_error",
            "wcdb_helper_not_found",
            "wcdb_library_not_found",
        }
        title = (
            _WECHAT_DATABASE_FAILED
            if code in database_codes
            else _WECHAT_SESSIONS_FAILED
        )
        detail = message or _WECHAT_CONNECT_RETRY_HINT
        self._status_label.setText(_DISCONNECTED_PREFIX + title)
        self._status_label.setToolTip(detail)
        self._status_label.setVisible(True)
        self._set_restart_action()
        self.status_changed.emit(detail)

    def _offer_wechat_directory_reselection(self, detail: str) -> None:
        """Return the user to the WeChat data-location flow.

        Used when the captured key cannot read the selected database. The
        session list is deliberately not loaded. The user sees the actionable
        message and the setup dialog opens with everything available: every
        detected candidate when there are several, otherwise a free-text
        directory field that also accepts a pasted path Echo never detected.
        The key captured in this process is reused for the retry, so changing
        the directory does not require another WeChat login.
        """
        _LOGGER.info("wechat.database.verify recovery=directory_selection")
        self._sessions_loaded = False
        self._wechat_key_captured = True
        self._wechat_connect_pending = True
        text = (detail or "").strip() or _WECHAT_DATABASE_FAILED
        self._status_label.setVisible(True)
        self._status_label.setText(_DISCONNECTED_PREFIX + text)
        self._status_label.setToolTip(text)
        self.session_panel.show_disconnected_placeholder()
        self._show_wechat_guide(include_directory_help=True)
        self._set_restart_action()
        self.open_wechat_setup(data_roots=self._recovery_candidates())
        self.status_changed.emit(text)

    def _recovery_candidates(self) -> list[Path]:
        """Offer several candidates; ask for a manual path when there is one.

        A single candidate is not offered as a fixed combo box, so the user
        can always enter or paste a directory Echo did not detect.
        """
        try:
            detected = self._facade.detect_wechat_data_roots() or ()
        except Exception:
            return []
        candidates = [Path(value) for value in detected]
        return candidates if len(candidates) > 1 else []

    # ---------------------------------------------------------------- setup

    def open_wechat_setup(self, data_roots: Any = None) -> None:
        """Open the setup dialog, showing the current facade state.

        One workspace owns at most one live setup window: opening it again
        raises the existing window instead of stacking a second copy. A window
        the user closed opens normally afterwards, and the accepted signal of
        the reused window keeps saving through the same path.
        """
        existing = getattr(self, "_wechat_setup_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        try:
            setup_status = self._facade.get_wechat_setup_status()
        except Exception:
            setup_status = None
        try:
            detected_root = self._facade.detect_wechat_data_root()
        except Exception:
            detected_root = None
        self._wechat_setup_dialog = WeChatSetupDialog(
            self,
            setup_status=setup_status,
            data_root=detected_root,
            data_roots=data_roots,
        )
        self._wechat_setup_dialog.accepted.connect(
            self._save_wechat_environment_from_dialog
        )
        self._wechat_setup_dialog.show()

    def _save_wechat_environment_from_dialog(self) -> None:
        dialog = getattr(self, "_wechat_setup_dialog", None)
        if dialog is None:
            return
        pending = getattr(self, "_wechat_connect_pending", False)
        self._wechat_connect_pending = False
        if pending:
            self._start_wechat_connect(
                dialog.config(),
                reuse_key=self._wechat_key_captured,
            )
            return
        self.save_wechat_environment(dialog.config())

    def save_wechat_environment(self, config: Any) -> None:
        """Persist one WeChat environment through the facade."""
        self._set_stage(None)
        self._status_label.setVisible(True)
        self._status_label.setText("正在保存微信环境设置...")
        self._status_label.setToolTip("")
        self._executor(
            lambda: self._facade.setup_wechat_environment(config),
            on_success=lambda _status: self._after_wechat_environment_saved(),
            on_error=self._handle_setup_error,
        )

    def _after_wechat_environment_saved(self) -> None:
        self.refresh_connection_status(load_sessions_on_ready=True)

    def _handle_setup_error(self, code: str, message: str) -> None:
        self._set_stage(None)
        self._wechat_setup_button.setVisible(True)
        self._status_label.setText(
            _DISCONNECTED_PREFIX + "微信环境设置失败"
        )
        self._status_label.setToolTip(message)
        self._status_label.setVisible(True)
        self._set_restart_action()
        self.status_changed.emit(message)

    # ---------------------------------------------------------------- signals

    def _on_analysis_started(self) -> None:
        self.analysis_started.emit()

    def _on_panel_status(self, message: str) -> None:
        self.status_changed.emit(message)


def _wechat_unavailable_message(status: Any) -> str:
    if not bool(getattr(status, "runtime_available", False)):
        return "微信连接环境不存在"
    if not bool(getattr(status, "data_found", False)):
        return "微信数据库未就绪"
    if not bool(getattr(status, "db_key_available", False)):
        return _WECHAT_WAITING_LOGIN
    return getattr(status, "message", "") or _WECHAT_STATUS_DISCONNECTED
