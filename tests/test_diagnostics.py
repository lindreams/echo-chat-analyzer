"""Privacy and path tests for the shared Echo diagnostic log."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from qq_chat_analyzer import diagnostics


def test_frozen_log_uses_local_app_data_without_creating_install_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "Echo" / "Echo.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    expected_root = tmp_path / "local-app-data" / "LocalChatAnalyzer"
    assert diagnostics.runtime_root() == expected_root
    assert diagnostics.log_path() == expected_root / "logs" / "echo.log"
    assert not expected_root.exists()
    assert not executable.parent.exists()


def test_sensitive_filter_redacts_key_paths_and_helper_stderr() -> None:
    secret_key = "ab12" * 16
    database_path = r"C:\Users\Fictional\Documents\xwechat_files\session.db"
    helper_stderr = "native helper failed for fictional account"
    record = logging.LogRecord(
        name="qq_chat_analyzer.diagnostics.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="key=%s database_path=%s helper_stderr=%s token=%s",
        args=(secret_key, database_path, helper_stderr, "fictional-token"),
        exc_info=None,
    )

    diagnostics.SensitiveDataFilter().filter(record)
    text = record.getMessage()

    assert secret_key not in text
    assert database_path not in text
    assert helper_stderr not in text
    assert "fictional-token" not in text
    assert "[REDACTED]" in text


def test_sensitive_filter_removes_exception_message() -> None:
    try:
        raise RuntimeError("fictional secret exception detail")
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="qq_chat_analyzer.diagnostics.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="wechat.import.failed",
        args=(),
        exc_info=exc_info,
    )

    diagnostics.SensitiveDataFilter().filter(record)

    assert record.exc_info is None
    assert record.exc_text is None
    assert "fictional secret exception detail" not in record.getMessage()
