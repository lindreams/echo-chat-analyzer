"""Tests for the Echo-side WCDB diagnostic runner launcher.

All fixtures are fictional. No real WeChat data, key, or account appears here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.providers import wechat_database_provider
from qq_chat_analyzer.providers.wechat_database_provider import WeChatDatabaseProvider
from qq_chat_analyzer.providers.wechat_wcdb_diagnostic import (
    DIAGNOSTIC_ENV_VARIABLE,
    KEY_ENVIRONMENT_VARIABLE,
    diagnostic_report_path,
    maybe_launch_wcdb_diagnostic,
    runner_script_path,
)


FICTIONAL_KEY = "a" * 64
FICTIONAL_SESSION = "wxid_fictional_room@chatroom"


class _FakeCompleted:
    def __init__(
        self,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
    ) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _helper_result(rows: list[object]) -> str:
    return json.dumps(
        {
            "ok": True,
            "columns": ["username", "summary", "last_timestamp"],
            "rows": rows,
            "row_count": len(rows),
            "truncated": False,
        }
    )


def _schema_result(columns: list[str]) -> str:
    pragma_rows = [
        {"cid": index, "name": name, "type": "TEXT", "notnull": 0, "dflt_value": None, "pk": 0}
        for index, name in enumerate(columns)
    ]
    return json.dumps(
        {
            "ok": True,
            "columns": ["cid", "name", "type", "notnull", "dflt_value", "pk"],
            "rows": pragma_rows,
            "row_count": len(pragma_rows),
            "truncated": False,
        }
    )


def _make_data_root(tmp_path: Path) -> Path:
    storage = tmp_path / "xwechat_files" / "wxid_owner" / "db_storage"
    message_dir = storage / "message"
    message_dir.mkdir(parents=True, exist_ok=True)
    (message_dir / "session.db").write_bytes(b"fake")
    return tmp_path / "xwechat_files"


def _provider(tmp_path: Path, runner, diagnostic_spawner) -> WeChatDatabaseProvider:
    helper = tmp_path / "wcdb_cli.exe"
    helper.write_bytes(b"fake")
    library = tmp_path / "WCDB.dll"
    library.write_bytes(b"fake")
    return WeChatDatabaseProvider(
        data_root=_make_data_root(tmp_path),
        db_key=FICTIONAL_KEY,
        wcdb_cli_path=helper,
        wcdb_dll_path=library,
        runner=runner,
        diagnostic_spawner=diagnostic_spawner,
    )


@pytest.fixture(autouse=True)
def _clean_diagnostic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DIAGNOSTIC_ENV_VARIABLE, raising=False)
    monkeypatch.delenv(KEY_ENVIRONMENT_VARIABLE, raising=False)


# ------------------------------------------------------------------ launcher


def test_gate_off_does_not_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def spawner(command, environment):
        calls.append((command, environment))

    script = tmp_path / "scripts" / "run_wechat_wcdb_diagnostic.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("# fake runner", encoding="utf-8")
    monkeypatch.delenv(DIAGNOSTIC_ENV_VARIABLE, raising=False)

    launched = maybe_launch_wcdb_diagnostic(
        tmp_path / "session.db",
        FICTIONAL_KEY,
        echo_dir=tmp_path,
        runner=spawner,
    )

    assert launched is False
    assert calls == []


def test_child_env_contains_key_and_never_command_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def spawner(command, environment):
        calls.append((command, environment))

    script = tmp_path / "scripts" / "run_wechat_wcdb_diagnostic.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("# fake runner", encoding="utf-8")
    monkeypatch.setenv(DIAGNOSTIC_ENV_VARIABLE, "1")

    launched = maybe_launch_wcdb_diagnostic(
        tmp_path / "session.db",
        FICTIONAL_KEY,
        echo_dir=tmp_path,
        runner=spawner,
    )

    assert launched is True
    command, environment = calls[0]
    assert environment[KEY_ENVIRONMENT_VARIABLE] == FICTIONAL_KEY
    assert FICTIONAL_KEY not in " ".join(command)
    for argument in command:
        assert FICTIONAL_KEY not in argument


def test_launcher_logs_do_not_contain_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    script = tmp_path / "scripts" / "run_wechat_wcdb_diagnostic.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("# fake runner", encoding="utf-8")
    monkeypatch.setenv(DIAGNOSTIC_ENV_VARIABLE, "1")

    def spawner(command, environment):
        raise OSError("boom")

    with caplog.at_level("DEBUG"):
        maybe_launch_wcdb_diagnostic(
            tmp_path / "session.db",
            FICTIONAL_KEY,
            echo_dir=tmp_path,
            runner=spawner,
        )

    assert FICTIONAL_KEY not in caplog.text


# ------------------------------------------------------------ provider flow


def test_provider_gate_on_launches_runner_with_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def runner(command, timeout, environment):
        sql = " ".join(command)
        if "PRAGMA table_info" in sql:
            return _FakeCompleted(stdout=_schema_result(["username", "summary", "last_timestamp"]))
        if "SessionTable" in sql:
            return _FakeCompleted(
                stdout=_helper_result(
                    [{"username": FICTIONAL_SESSION, "last_timestamp": 1}]
                )
            )
        if "sqlite_master" in sql:
            return _FakeCompleted(stdout=_helper_result([]))
        raise AssertionError(f"unexpected query: {sql}")

    calls: list[tuple[list[str], dict[str, str]]] = []

    def diagnostic_spawner(command, environment):
        calls.append((command, environment))

    monkeypatch.setenv(DIAGNOSTIC_ENV_VARIABLE, "1")
    session_db = tmp_path / "xwechat_files" / "wxid_owner" / "db_storage" / "message" / "session.db"

    provider = _provider(tmp_path, runner, diagnostic_spawner)
    provider.list_sessions()

    assert len(calls) == 1
    command, environment = calls[0]
    assert str(session_db) in command
    assert environment[KEY_ENVIRONMENT_VARIABLE] == FICTIONAL_KEY
    assert FICTIONAL_KEY not in " ".join(command)


def test_provider_spawner_failure_does_not_break_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def runner(command, timeout, environment):
        sql = " ".join(command)
        if "PRAGMA table_info" in sql:
            return _FakeCompleted(stdout=_schema_result(["username", "summary", "last_timestamp"]))
        if "SessionTable" in sql:
            return _FakeCompleted(
                stdout=_helper_result(
                    [{"username": FICTIONAL_SESSION, "last_timestamp": 1}]
                )
            )
        if "sqlite_master" in sql:
            return _FakeCompleted(stdout=_helper_result([]))
        raise AssertionError(f"unexpected query: {sql}")

    def diagnostic_spawner(command, environment):
        raise OSError("powershell missing")

    monkeypatch.setenv(DIAGNOSTIC_ENV_VARIABLE, "1")

    provider = _provider(tmp_path, runner, diagnostic_spawner)
    result = provider.list_sessions()

    assert len(result) == 1
