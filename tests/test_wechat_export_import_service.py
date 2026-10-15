"""End-to-end tests for the WeChat provider -> adapter -> ChatMessage seam.

No real WeChat database is opened. The provider is a stub that writes a
fictional export document, mirroring test_qq_export_import_service.py.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.application import (
    ApplicationServiceError,
    ImportService,
    WeChatExportFileMissing,
    WeChatExportImportRequest,
    WeChatExportImportService,
    WeChatExportProvider,
    WeChatExportUnavailable,
)
from qq_chat_analyzer.application.import_service import WECHAT_DB_FORMAT
from qq_chat_analyzer.providers.wechat_database_provider import (
    DatabaseNotFound,
    KeyUnavailable,
    WeChatSession,
)


FICTIONAL_SESSION = "wxid_fictional_room@chatroom"
TEXT_LOCAL_TYPE = 1
IMAGE_LOCAL_TYPE = 3


# --------------------------------------------------------------------- fixtures


def _db_row(
    message_content: str = "Fictional wechat line",
    local_type: int = TEXT_LOCAL_TYPE,
    create_time: int = 1753412807,
    user_name: str = "wxid_fictional_sender",
    server_id: int = 900001,
) -> dict:
    return {
        "local_id": 11,
        "server_id": server_id,
        "local_type": local_type,
        "create_time": create_time,
        "message_content": message_content,
        "user_name": user_name,
    }


def _write_fake_export(path: Path, rows: list | None = None) -> Path:
    """Write a fictional WeChat database export document."""
    document = {
        "source": "wechat-db",
        "conversation": {"username": FICTIONAL_SESSION},
        "messages": rows
        if rows is not None
        else [
            _db_row(message_content="Fictional wechat line", server_id=900001),
            _db_row(message_content="Second fictional line", server_id=900002),
            _db_row(local_type=IMAGE_LOCAL_TYPE, server_id=900003),
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


class _StubProvider:
    """Stand-in for WeChatDatabaseProvider that never touches a database."""

    def __init__(
        self,
        rows: list | None = None,
        result: object = "write",
        error: Exception | None = None,
        sessions: list | None = None,
    ) -> None:
        self._rows = rows
        self._result = result
        self._error = error
        self._sessions = sessions or []
        self.calls: list[dict] = []

    def list_sessions(self) -> list:
        if self._error is not None:
            raise self._error
        return self._sessions

    def export_session_json(
        self,
        session_id,
        output_path,
        start_time=None,
        end_time=None,
    ):
        self.calls.append(
            {
                "session_id": session_id,
                "output_path": output_path,
                "start_time": start_time,
                "end_time": end_time,
            }
        )
        if self._error is not None:
            raise self._error
        if self._result == "write":
            return _write_fake_export(Path(output_path), self._rows)
        return self._result


def _request(tmp_path: Path, **kwargs) -> WeChatExportImportRequest:
    return WeChatExportImportRequest(
        session_id=kwargs.pop("session_id", FICTIONAL_SESSION),
        output_path=kwargs.pop("output_path", tmp_path / "export.json"),
        **kwargs,
    )


# ------------------------------------------------------------------- contract


# -------------------------------------------------------------------- execute


def test_execute_exports_then_imports_into_chat_messages(tmp_path: Path) -> None:
    provider = _StubProvider()
    service = WeChatExportImportService(provider)

    outcome = service.execute(_request(tmp_path))

    assert outcome.result.platform == "wechat"
    assert outcome.result.format == WECHAT_DB_FORMAT
    assert outcome.result.message_count == 2
    assert outcome.result.valid_text_count == 2
    assert [message.text for message in outcome.messages] == [
        "Fictional wechat line",
        "Second fictional line",
    ]
    assert {message.platform for message in outcome.messages} == {"wechat"}
    assert {message.conversation_id for message in outcome.messages} == {
        FICTIONAL_SESSION
    }


def test_execute_logs_import_failure_without_exception_message(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _FailingImportService(ImportService):
        def execute(self, request):
            raise RuntimeError("fictional secret import detail")

    service = WeChatExportImportService(
        _StubProvider(),
        _FailingImportService(),
    )

    with caplog.at_level(
        logging.WARNING,
        logger="qq_chat_analyzer.desktop.wechat_export_import_service",
    ):
        with pytest.raises(RuntimeError):
            service.execute(_request(tmp_path))

    assert "wechat.import.failed error_type=RuntimeError" in caplog.text
    assert "fictional secret import detail" not in caplog.text


# ---------------------------------------------------------------- export_only


# -------------------------------------------------------------- list_sessions
