"""Confirmation and input controls hosted by an existing desktop page."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .theme import (
    COLOR_BORDER, COLOR_FAINT, HOME_COLOR_ACCENT, HOME_COLOR_LEAF, HOME_COLOR_MUTED,
    HOME_COLOR_PAPER, HOME_COLOR_TEXT, REFRESH_SANS_FAMILY,
)


class InlinePrompt(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inlinePrompt")
        self.setStyleSheet(f"""
            QFrame#inlinePrompt {{ background: {HOME_COLOR_PAPER}; }}
            QWidget#inlinePromptBody {{ background: transparent; }}
            QLabel#inlinePromptTitle {{
                font-family: {REFRESH_SANS_FAMILY}; font-size: 18px;
                font-weight: 600; color: {HOME_COLOR_TEXT};
            }}
            QLabel#inlinePromptDetail {{ color: {HOME_COLOR_MUTED}; }}
            QFrame#inlinePrompt QLineEdit, QFrame#inlinePrompt QComboBox {{
                color: {HOME_COLOR_TEXT}; background: {HOME_COLOR_LEAF};
                border: 1px solid {COLOR_BORDER}; padding: 8px;
            }}
            QFrame#inlinePrompt QLineEdit:focus, QFrame#inlinePrompt QComboBox:focus {{
                border-color: {HOME_COLOR_ACCENT};
            }}
            QFrame#inlinePrompt QPushButton:disabled {{ color: {COLOR_FAINT}; }}
        """)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._body = None
        self._on_cancel = None
        shortcut = QShortcut(QKeySequence("Escape"), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.cancel)
        self.hide()

    @property
    def pending(self):
        return self._body is not None

    def present(self, title, detail, actions, *, on_cancel, content=None):
        self.dismiss()
        body = QWidget(self)
        body.setObjectName("inlinePromptBody")
        self._body = body
        self._on_cancel = on_cancel
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        for name, text in (("inlinePromptTitle", title), ("inlinePromptDetail", detail)):
            if text:
                label = QLabel(text)
                label.setObjectName(name)
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setWordWrap(True)
                layout.addWidget(label)
        if content is not None:
            layout.addWidget(content, stretch=1)

        def choose(action):
            if self._body is body:
                self.dismiss()
                action()

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("取消")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(lambda: choose(on_cancel))
        row.addWidget(cancel)
        buttons = []
        for label, action in actions:
            button = QPushButton(label)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, action=action: choose(action))
            row.addWidget(button)
            buttons.append(button)
        layout.addLayout(row)
        self._layout.addWidget(body)
        self.show()
        cancel.setFocus()
        return buttons

    def cancel(self):
        if self.pending:
            callback = self._on_cancel
            self.dismiss()
            callback()

    def dismiss(self):
        self.hide()
        if self._body is not None:
            self._layout.removeWidget(self._body)
            self._body.hide()
            self._body.deleteLater()
            self._body = None
        self._on_cancel = None

    def request_path(self, title, detail, action, on_path, *, on_cancel, placeholder):
        edit = QLineEdit()
        edit.setAccessibleName(title)
        edit.setPlaceholderText(placeholder)

        def path_text():
            return edit.text().strip().strip('"').strip()

        (button,) = self.present(
            title, detail, [(action, lambda: on_path(path_text()))],
            on_cancel=on_cancel, content=edit,
        )
        button.setEnabled(False)
        edit.textChanged.connect(lambda: button.setEnabled(Path(path_text()).is_absolute()))
        edit.setFocus()
        return edit
