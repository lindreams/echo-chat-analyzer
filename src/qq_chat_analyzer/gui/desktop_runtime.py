"""Desktop startup hardening: logging and global exception handling.

This module keeps the desktop entry point safe on machines without a Python
environment: startup failures and analysis errors are written to the shared
user-data log (``%LOCALAPPDATA%\\LocalChatAnalyzer\\logs\\echo.log`` when frozen,
``Echo/logs/echo.log`` from a source checkout) and users only ever see a safe
message, never a traceback.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import traceback
from datetime import datetime
from typing import Any

from ..diagnostics import configure_diagnostics


LOGGER_NAME = "qq_chat_analyzer.desktop"

STARTUP_FAILED_MESSAGE = (
    "\u5e94\u7528\u542f\u52a8\u5931\u8d25\uff0c\u8be6\u60c5\u5df2\u5199\u5165"
    "\u65e5\u5fd7\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"
)
#: Used when the diagnostic log could not be created, so no log claim is made.
STARTUP_FAILED_NO_LOG_MESSAGE = (
    "\u5e94\u7528\u542f\u52a8\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"
)
UNEXPECTED_ERROR_MESSAGE = (
    "\u7a0b\u5e8f\u51fa\u73b0\u672a\u9884\u671f\u9519\u8bef\uff0c"
    "\u8be6\u60c5\u5df2\u5199\u5165\u65e5\u5fd7\u3002"
)


def configure_logging() -> logging.Logger:
    """Configure a minimal file logger and return the desktop logger."""
    configure_diagnostics()
    return logging.getLogger(LOGGER_NAME)


def install_global_exception_handler() -> None:
    """Route uncaught exceptions to the log and a safe user message."""
    sys.excepthook = _handle_uncaught_exception


def _handle_uncaught_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: Any,
) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    logger.error(
        "Uncaught %s: %s\n%s",
        exc_type.__name__,
        exc_value,
        "".join(
            traceback.format_exception(exc_type, exc_value, exc_traceback)
        ),
    )
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance()
        if app is not None:
            QMessageBox.critical(None, "\u9519\u8bef", UNEXPECTED_ERROR_MESSAGE)
    except Exception:
        pass


def log_startup(version: str) -> None:
    """Record one startup line with version and timestamp."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.info(
        "Echo started version=%s python=%s sqlite_version=%s platform=%s at %s",
        version,
        sys.version.split()[0],
        sqlite3.sqlite_version,
        sys.platform,
        datetime.now().isoformat(timespec="seconds"),
    )
