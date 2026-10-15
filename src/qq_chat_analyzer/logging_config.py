"""Application logging configuration shared by entry points."""

from __future__ import annotations

import logging
import re


DESKTOP_DIAGNOSTIC_LOGGERS = (
    "qq_chat_analyzer.providers.wechat_database_provider",
    "qq_chat_analyzer.desktop",
    "qq_chat_analyzer.diagnostics",
)

_SENSITIVE_FIELD_PATTERN = re.compile(
    r"(?i)(key|token|secret|database_path|helper_stderr|stderr)"
    r"\s*=\s*([^\s|]+(?:\s+[^|]+)?)"
)
_WINDOWS_USER_PATH_PATTERN = re.compile(r"(?i)([A-Z]:\\Users\\)[^\s|]+")
_HEX_KEY_PATTERN = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")


class SensitiveDataFilter(logging.Filter):
    """Remove secrets and exception details before records reach disk."""

    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        rendered = _HEX_KEY_PATTERN.sub("[REDACTED]", rendered)
        rendered = _WINDOWS_USER_PATH_PATTERN.sub(r"\1[REDACTED]", rendered)
        rendered = _SENSITIVE_FIELD_PATTERN.sub(
            lambda match: f"{match.group(1)}=[REDACTED]", rendered
        )
        record.msg = rendered
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        return True


def build_diagnostic_handler(path: object) -> logging.Handler:
    """Create the shared UTF-8, privacy-filtered Echo file handler."""
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    handler.addFilter(SensitiveDataFilter())
    return handler
