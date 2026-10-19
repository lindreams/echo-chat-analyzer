"""Production processing surface: typed stage text, native animation, cancel."""
from __future__ import annotations

import ctypes
import logging
import sys
from time import monotonic

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..application.facade import AnalysisPhase
from .processing_animation_widget import ProcessingAnimationWidget
from .theme import COLOR_ACCENT, COLOR_MUTED, COLOR_PAPER, COLOR_TEXT, REFRESH_SANS_FAMILY, SERIF_FAMILY


_COPY = {
    AnalysisPhase.READING: ("正在读取聊天记录", "正在从本机读取所选会话，请稍候。"),
    AnalysisPhase.ANALYZING_REPORT: ("正在分析与生成报告", "正在整理消息并生成分析报告，请稍候。"),
}
_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.processing")


def system_reduced_motion() -> bool:
    """Read Windows client-area animation preference, without changing it.

    SPI_GETCLIENTAREAANIMATION (0x1042) writes a Win32 BOOL (four bytes).
    https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-systemparametersinfow
    """
    if sys.platform != "win32":
        return False
    enabled = ctypes.c_int(1)
    try:
        success = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
    except (AttributeError, OSError):
        return False
    return bool(success) and not bool(enabled.value)


class ProcessingPage(QWidget):
    cancel_requested = Signal()

    def __init__(self, parent=None, *, reduced_motion: bool | None = None):
        super().__init__(parent)
        self.setObjectName("processingPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._running = False
        self._diagnostic_stage = "reading"
        self._last_pulse = monotonic()
        self._max_gap_ms = 0
        self._pulse_count = 0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(250)
        self._pulse_timer.timeout.connect(self._pulse)
        self.phase = AnalysisPhase.READING
        self.setStyleSheet(f"""
            QWidget#processingPage {{ background: {COLOR_PAPER}; }}
            QWidget#processingPage QLabel {{
                background: transparent; border: none; padding: 0;
                font-family: {REFRESH_SANS_FAMILY}; color: {COLOR_MUTED};
            }}
            QWidget#processingPage QLabel#processingTitle {{
                font-family: {SERIF_FAMILY}; font-size: 24px; color: {COLOR_TEXT};
            }}
            QWidget#processingPage QLabel#processingSubtitle {{ font-size: 13px; }}
            QWidget#processingPage QLabel#processingPrivacy {{ font-size: 12px; }}
            QWidget#processingPage QPushButton {{
                background: transparent; color: {COLOR_ACCENT}; border: 1px solid {COLOR_ACCENT};
                border-radius: 4px; padding: 9px 22px; font-size: 13px;
            }}
            QWidget#processingPage QPushButton:hover {{ background: #f2ede3; }}
            QWidget#processingPage QPushButton:focus {{ border: 2px solid {COLOR_ACCENT}; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 20)
        layout.setSpacing(14)
        self.animation = ProcessingAnimationWidget(
            self, reduced_motion=system_reduced_motion() if reduced_motion is None else reduced_motion)
        self.animation.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.animation.setMaximumSize(800, 460)
        self.animation.setMinimumSize(0, 150)
        layout.addWidget(self.animation, 1, Qt.AlignmentFlag.AlignHCenter)
        self.status_label = QLabel(_COPY[self.phase][0], self)
        self.status_label.setObjectName("processingTitle")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status_label)
        self.subtitle_label = QLabel(_COPY[self.phase][1], self)
        self.subtitle_label.setObjectName("processingSubtitle")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.subtitle_label)
        self.cancel_button = QPushButton("取消分析", self)
        self.cancel_button.setMinimumWidth(150)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        layout.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignHCenter)
        privacy = QLabel("聊天内容仅在本机处理", self)
        privacy.setObjectName("processingPrivacy")
        privacy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(privacy)
        self.animation.stop()

    def start(self) -> None:
        self._running = True
        self._diagnostic_stage = "reading"
        self._last_pulse = monotonic()
        self._max_gap_ms = self._pulse_count = 0
        self._pulse_timer.start()
        self.phase = AnalysisPhase.READING
        self.status_label.setText(_COPY[self.phase][0])
        self.subtitle_label.setText(_COPY[self.phase][1])
        self.animation.start()

    def set_phase(self, phase: object) -> None:
        if not self._running or not isinstance(phase, AnalysisPhase) or phase is self.phase:
            return
        self.phase = phase
        self._diagnostic_stage = "analysis" if phase is AnalysisPhase.ANALYZING_REPORT else "reading"
        self.status_label.setText(_COPY[phase][0])
        self.subtitle_label.setText(_COPY[phase][1])
        self.animation.set_phase(phase)

    def stop(self) -> None:
        if self._running:
            self._pulse()
            _LOGGER.info("[analysis-gui] stage=%s samples=%d max_gap_ms=%d",
                         self._diagnostic_stage, self._pulse_count, self._max_gap_ms)
        self._running = False
        self._pulse_timer.stop()
        self.animation.stop()

    def _pulse(self) -> None:
        """Measure actual event-loop gaps; never pump events to hide blocking."""
        now = monotonic()
        gap_ms = max(0, round((now - self._last_pulse) * 1000))
        self._last_pulse = now
        self._max_gap_ms = max(self._max_gap_ms, gap_ms)
        self._pulse_count += 1
        if gap_ms >= 1000:
            _LOGGER.info("[analysis-gui-stall] stage=%s gap_ms=%d", self._diagnostic_stage, gap_ms)

    def set_report_progress(self, message: str) -> None:
        if (self._running and self.phase is AnalysisPhase.ANALYZING_REPORT
                and (message in {"正在分析表情包...", "正在获取表情包素材...", "正在生成报告..."}
                     or message.startswith("正在获取表情包素材（"))):
            self.status_label.setText(message.rstrip("."))
            self._diagnostic_stage = ("media" if message.startswith("正在获取表情包素材") else
                                      "export" if message == "正在生成报告..." else "analysis")

    def set_reduced_motion(self, reduced: bool) -> None:
        self.animation.set_reduced_motion(reduced)

    def closeEvent(self, event):
        self.stop()
        self.animation.close()
        super().closeEvent(event)
