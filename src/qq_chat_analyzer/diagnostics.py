"""Shared privacy-first diagnostics for the Echo desktop application."""

from __future__ import annotations

import logging
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator

from .resources import user_data_root
from .version import APP_VERSION
from .logging_config import (
    DESKTOP_DIAGNOSTIC_LOGGERS,
    SensitiveDataFilter,
    build_diagnostic_handler,
)


LOGGER_NAME = "qq_chat_analyzer.diagnostics"
LOG_FILENAME = "echo.log"


def log_qq_session_event(
    logger: logging.Logger, stage: str, outcome: str, *,
    elapsed_ms: int = 0, failure_code: str = "none",
) -> None:
    """Emit caller-owned fixed fields only; diagnostics never own control flow.

    Callers must pass literal stages/outcomes/categories, never exception text,
    server codes, request payloads or user identifiers.
    """
    try:
        logger.info(
            "[qq sessions] stage=%s outcome=%s elapsed_ms=%d failure_code=%s",
            stage, outcome, elapsed_ms, failure_code,
        )
    except Exception:
        pass


@contextmanager
def qq_session_stage(logger: logging.Logger, stage: str) -> Iterator[None]:
    """Observe a bounded session-loading phase without changing its exception."""
    started = time.perf_counter()
    log_qq_session_event(logger, stage, "started")
    try:
        yield
    except Exception as error:
        category = (
            "sqlite_error" if isinstance(error, sqlite3.DatabaseError) else
            "io_error" if isinstance(error, OSError) else "operation_failed"
        )
        log_qq_session_event(
            logger, stage, "failed",
            elapsed_ms=int((time.perf_counter() - started) * 1000), failure_code=category,
        )
        raise
    else:
        log_qq_session_event(
            logger, stage, "success", elapsed_ms=int((time.perf_counter() - started) * 1000),
        )


def runtime_root() -> Path:
    """Calculate writable Frozen data root, or the predictable development root."""
    if getattr(sys, "frozen", False):
        return user_data_root()
    return Path(__file__).resolve().parents[2] / "Echo"


def log_path() -> Path:
    """Return the shared Echo log path."""
    return runtime_root() / "logs" / LOG_FILENAME


def configure_diagnostics() -> logging.Logger:
    """Configure one idempotent logger and share its handler with diagnostics."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = next(
        (
            handler
            for handler in logger.handlers
            if isinstance(handler, logging.FileHandler)
            and Path(handler.baseFilename).resolve() == path.resolve()
        ),
        None,
    )
    if existing is None:
        logger.addHandler(build_diagnostic_handler(path))
        logger.info(
            "[runtime] echo_version=%s frozen=%s python_version=%d.%d.%d windows_build=%d",
            APP_VERSION, bool(getattr(sys, "frozen", False)), *sys.version_info[:3],
            sys.getwindowsversion().build if sys.platform == "win32" else 0,
        )
    handlers = tuple(logger.handlers)
    for logger_name in DESKTOP_DIAGNOSTIC_LOGGERS:
        target = logging.getLogger(logger_name)
        target.setLevel(logging.INFO)
        for handler in handlers:
            if handler not in target.handlers:
                target.addHandler(handler)
    return logger


__all__ = [
    "LOGGER_NAME",
    "LOG_FILENAME",
    "SensitiveDataFilter",
    "configure_diagnostics",
    "log_path",
    "log_qq_session_event",
    "qq_session_stage",
    "runtime_root",
]
