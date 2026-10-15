"""Focused diagnostics for probing known WeChat session databases.

Every path, key, account, and message fragment in this file is fictional.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qq_chat_analyzer.application.wechat.wechat_setup_service import WeChatSetupService
from qq_chat_analyzer.application.wechat.wechat_environment_config import (
    WeChatEnvironmentConfig,
)
from qq_chat_analyzer.providers.wechat_database_provider import (
    DatabaseUnreadable,
    WeChatDatabaseProvider,
)


FICTIONAL_KEY = "b" * 64
FICTIONAL_ACCOUNT = "wxid_probe_owner"
FICTIONAL_CHAT_TEXT = "fictional private chat text"
VERIFY_SQL = "SELECT count(*) FROM sqlite_master"


class _FakeCompleted:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def _code_26_result(message: str = "file is not a database") -> str:
    return json.dumps(
        {
            "ok": False,
            "stage": "prepare",
            "error": "prepare failed",
            "wcdb_error_code": 26,
            "wcdb_error_ext_code": 1032,
            "wcdb_error_message": message,
        }
    )


def _make_root(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    message_dir = root / FICTIONAL_ACCOUNT / "db_storage" / "message"
    message_dir.mkdir(parents=True, exist_ok=True)
    (message_dir / "session.db").write_bytes(f"fake-{name}".encode())
    (message_dir / "message_0.db").write_bytes(b"fake")
    return root


def _session_db(root: Path) -> Path:
    return root / FICTIONAL_ACCOUNT / "db_storage" / "message" / "session.db"


def _provider(
    tmp_path: Path,
    root: Path,
    runner,
) -> WeChatDatabaseProvider:
    helper = tmp_path / "wcdb_cli.exe"
    library = tmp_path / "WCDB.dll"
    helper.write_bytes(b"fake")
    library.write_bytes(b"fake")
    return WeChatDatabaseProvider(
        data_root=root,
        db_key=FICTIONAL_KEY,
        wcdb_cli_path=helper,
        wcdb_dll_path=library,
        timeout=10,
        runner=runner,
    )


class _Factory:
    def __init__(self, provider: object) -> None:
        self.provider = provider
        self.creates = 0

    def create(self) -> object:
        self.creates += 1
        return self.provider

    def invalidate(self) -> None:
        pass


def test_probe_logs_are_anonymous(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    saved = _make_root(tmp_path, "saved_secret_root")
    detected = _make_root(tmp_path, "detected_secret_root")
    sensitive_message = (
        f"{_session_db(saved)} {_session_db(detected)} "
        f"{FICTIONAL_KEY} {VERIFY_SQL} {FICTIONAL_CHAT_TEXT}"
    )

    def runner(command, timeout, environment):
        return _FakeCompleted(
            stdout=_code_26_result(sensitive_message),
            returncode=1,
        )

    provider = _provider(tmp_path, saved, runner)
    service = WeChatSetupService(
        provider_factory=_Factory(provider),
        data_roots_detector=lambda: [detected],
    )

    with caplog.at_level(
        "INFO",
        logger="qq_chat_analyzer.providers.wechat_database_provider",
    ):
        with pytest.raises(DatabaseUnreadable):
            service.verify_connection()

    logs = caplog.text
    assert str(saved) not in logs
    assert str(detected) not in logs
    assert FICTIONAL_ACCOUNT not in logs
    assert FICTIONAL_KEY not in logs
    assert VERIFY_SQL not in logs
    assert FICTIONAL_CHAT_TEXT not in logs
