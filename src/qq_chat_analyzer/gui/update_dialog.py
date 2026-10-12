"""About Echo and an explicitly requested, worker-backed release check."""

from __future__ import annotations

import weakref
from typing import Any
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from shiboken6 import isValid

from .. import version
from .theme import (
    HOME_COLOR_PAPER, HOME_COLOR_TEXT, HOME_COLOR_MUTED, HOME_COLOR_ACCENT,
    COLOR_BORDER, REFRESH_SANS_FAMILY, SERIF_FAMILY,
)
from .workers import submit


class UpdateDialog(QDialog):
    """Present facade outcomes without changing update policy or downloading."""

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
        self._closed = False
        self._checking = False
        self._release_url: str | None = None
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
        self.status_label = QLabel("点击检查更新，查询 GitHub 上的正式发布。")
        self.status_label.setTextFormat(Qt.PlainText)
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(40)
        layout.addWidget(self.status_label)
        actions = QHBoxLayout()
        self.release_button = QPushButton("查看发布页面 ↗")
        self.release_button.setObjectName("releaseLink")
        self.release_button.setCursor(Qt.PointingHandCursor)
        self.release_button.hide()
        self.release_button.clicked.connect(self._open_release)
        actions.addWidget(self.release_button)
        actions.addStretch(1)
        self.check_button = QPushButton("检查更新")
        self.check_button.clicked.connect(self._check)
        actions.addWidget(self.check_button)
        layout.addLayout(actions)

    def _mark_closed(self, _result: int) -> None:
        self._closed = True

    def _check(self) -> None:
        if self._closed or self._checking:
            return
        self._checking = True
        self.check_button.setEnabled(False)
        self.check_button.setText("正在检查…")
        self.status_label.setText("正在查询正式发布…")
        self._release_url = None
        self.release_button.hide()
        reference = weakref.ref(self)

        def success(result: Any) -> None:
            dialog = reference()
            if dialog is not None and isValid(dialog) and not dialog._closed:
                dialog._show_result(result)

        def error(_code: str, message: str) -> None:
            dialog = reference()
            if dialog is not None and isValid(dialog) and not dialog._closed:
                dialog._ready()
                dialog.status_label.setText(message)

        facade = self._facade
        try:
            self._executor(lambda: facade.check_for_updates(manual=True),
                           on_success=success, on_error=error)
        except Exception:
            error("submit_failed", "暂时无法检查更新，请稍后手动重试。")

    def _ready(self) -> None:
        self._checking = False
        self.check_button.setEnabled(True)
        self.check_button.setText("检查更新")

    def _show_result(self, result: Any) -> None:
        self._ready()
        messages = {
            "up_to_date": "当前已是最新版本。",
            "no_release": "暂无正式发布，请稍后再检查。",
            "skipped": "本次检查未执行，请稍后重试。",
            "unavailable": result.public_message or "暂时无法检查更新，请稍后手动重试。",
        }
        if result.status == "update_available":
            self.status_label.setText(f"发现新版本  {result.latest_version or '未知版本'}")
            if _safe_release_url(result.release_url):
                self._release_url = result.release_url
                self.release_button.show()
            else:
                self.status_label.setText(self.status_label.text() + "\n发布页面暂不可用，请稍后重试。")
        else:
            self.status_label.setText(messages.get(result.status, messages["unavailable"]))

    def _open_release(self) -> None:
        if self._closed or not _safe_release_url(self._release_url):
            return
        try:
            opened = QDesktopServices.openUrl(QUrl(self._release_url))
        except Exception:
            opened = False
        if not opened:
            self.status_label.setText("无法打开浏览器，请稍后重试查看发布页面。")


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
