"""Fail-closed QQ entry until automatic account acquisition is available.

The explicit single-group experiment is not a desktop connection workflow.
Do not invite a real login or expose its parameters as a product fallback.
"""
from __future__ import annotations

from threading import Event
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..application.facade import ChatSource
from .session_analysis_panel import SessionAnalysisPanel
from .workers import submit


class QQIndependentWorkspace(QWidget):
    analysis_started = Signal()
    analysis_succeeded = Signal(object)
    analysis_failed = Signal(str, str)
    analysis_phase_changed = Signal(object)
    status_changed = Signal(str)

    def __init__(self, facade: Any, parent=None, *, executor=None):
        super().__init__(parent)
        self._facade = facade
        self._closing = False
        self._cancel = Event()
        layout = QVBoxLayout(self)
        heading = QLabel('QQ · 本地独立读取')
        heading.setObjectName('workspaceTitle')
        layout.addWidget(heading)
        self._status = QLabel(
            'QQ 连接暂不可用：自动识别当前账号与安全准备数据尚未接通。'
            '请勿为此重新登录 QQ。已生成的报告可从「本地数据」打开。'
        )
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._status)
        self._session_panel = SessionAnalysisPanel(self)
        self._session_panel.configure(facade, ChatSource.QQ, executor or submit)
        self._session_panel.setEnabled(False)
        layout.addWidget(self._session_panel, 1)

    def cancel_connection(self):
        self._cancel.set()
        self._facade.cancel_qq_auth_flow(self._cancel)
        self.cancel_analysis()

    def cancel_analysis(self):
        self._session_panel.cancel_analysis()

    def select_source(self, _source):
        pass

    def refresh_connection_status(self, *, load_sessions_on_ready=False):
        # Navigation cannot turn an experimental single-group acquisition into
        # a product session list, even if another caller prepared that service.
        if not self._closing:
            self.status_changed.emit(self._status.text())
