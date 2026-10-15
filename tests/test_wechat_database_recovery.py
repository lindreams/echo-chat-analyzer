"""Focused tests for unique-readable WeChat account recovery.

All roots, accounts, keys, and message content in this file are fictional.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from qq_chat_analyzer.application.wechat.wechat_environment_config import (
    WeChatEnvironmentConfig,
    WeChatEnvironmentConfigLoader,
    WeChatEnvironmentConfigWriter,
)
from qq_chat_analyzer.application.wechat.wechat_provider_factory import (
    WeChatProviderFactory,
)
from qq_chat_analyzer.application.wechat.wechat_setup_service import WeChatSetupService
from qq_chat_analyzer.providers.wechat_database_provider import (
    DatabaseUnreadable,
    WeChatDatabaseProvider,
    message_table_name,
)


FICTIONAL_KEY = "c" * 64
FICTIONAL_CONTACT = "wxid_fictional_contact"
FICTIONAL_CHAT_TEXT = "fictional private message"
VERIFY_SQL = "SELECT count(*) FROM sqlite_master"


class _FakeCompleted:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def _success_result(rows: list[object] | None = None) -> str:
    actual_rows = rows if rows is not None else [{"count(*)": 1}]
    return json.dumps(
        {
            "ok": True,
            "columns": list(actual_rows[0]) if actual_rows else [],
            "rows": actual_rows,
            "row_count": len(actual_rows),
            "truncated": False,
        }
    )


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


def _schema_result() -> str:
    rows = [
        {"cid": 0, "name": "username", "type": "TEXT"},
        {"cid": 1, "name": "summary", "type": "TEXT"},
        {"cid": 2, "name": "last_timestamp", "type": "INTEGER"},
    ]
    return _success_result(rows)


def _make_account(parent: Path, name: str) -> Path:
    account = parent / name
    message_dir = account / "db_storage" / "message"
    message_dir.mkdir(parents=True, exist_ok=True)
    (message_dir / "session.db").write_bytes(f"fake-{name}".encode())
    (message_dir / "message_0.db").write_bytes(b"fake")
    (message_dir / "contact.db").write_bytes(b"fake")
    return account


def _session_db(root: Path) -> Path:
    return root / "db_storage" / "message" / "session.db"


def _command_database(command: list[str]) -> Path:
    return Path(command[command.index("--db") + 1])


def _command_sql(command: list[str]) -> str:
    return command[command.index("--sql") + 1]


def _owning_root(database: Path, roots: tuple[Path, ...]) -> Path | None:
    for root in roots:
        if database == root or root in database.parents:
            return root
    return None


class _MultiAccountRunner:
    def __init__(
        self,
        roots: tuple[Path, ...],
        readable_roots: set[Path],
        *,
        fail_second_readable_verify: bool = False,
        sensitive_error: str = "file is not a database",
    ) -> None:
        self.roots = roots
        self.readable_roots = readable_roots
        self.fail_second_readable_verify = fail_second_readable_verify
        self.sensitive_error = sensitive_error
        self.calls: list[tuple[Path, str, dict[str, str]]] = []
        self._readable_verify_calls = 0

    def __call__(self, command, timeout, environment):
        database = _command_database(command)
        sql = _command_sql(command)
        self.calls.append((database, sql, dict(environment)))
        if sql == VERIFY_SQL:
            root = _owning_root(database, self.roots)
            if root not in self.readable_roots:
                return _FakeCompleted(
                    stdout=_code_26_result(self.sensitive_error),
                    returncode=1,
                )
            self._readable_verify_calls += 1
            if (
                self.fail_second_readable_verify
                and self._readable_verify_calls >= 2
            ):
                return _FakeCompleted(
                    stdout=_code_26_result(self.sensitive_error),
                    returncode=1,
                )
            return _FakeCompleted(stdout=_success_result())

        if root := _owning_root(database, self.roots):
            if "PRAGMA table_info" in sql:
                return _FakeCompleted(stdout=_schema_result())
            if "FROM SessionTable" in sql:
                return _FakeCompleted(
                    stdout=_success_result(
                        [
                            {
                                "username": FICTIONAL_CONTACT,
                                "summary": "fictional summary",
                                "last_timestamp": 1,
                            }
                        ]
                    )
                )
            if "FROM sqlite_master" in sql and "LIKE 'Msg_%'" in sql:
                table = message_table_name(FICTIONAL_CONTACT)
                return _FakeCompleted(
                    stdout=_success_result([{"name": table}])
                )
            if "FROM contact" in sql:
                return _FakeCompleted(
                    stdout=_success_result(
                        [
                            {
                                "username": FICTIONAL_CONTACT,
                                "remark": "fictional contact",
                                "nick_name": None,
                            }
                        ]
                    )
                )
        raise AssertionError(f"unexpected query for {database.name}")


def _service_harness(
    tmp_path: Path,
    roots: tuple[Path, ...],
    runner: _MultiAccountRunner,
    *,
    saved_root: Path,
) -> tuple[
    WeChatSetupService,
    WeChatEnvironmentConfigLoader,
    WeChatProviderFactory,
]:
    runtime = tmp_path / "runtime"
    runtime.mkdir(exist_ok=True)
    helper = runtime / "wcdb_cli.exe"
    library = runtime / "WCDB.dll"
    helper.write_bytes(b"fake")
    library.write_bytes(b"fake")

    config_path = tmp_path / "config" / "wechat.json"
    loader = WeChatEnvironmentConfigLoader(config_path)
    writer = WeChatEnvironmentConfigWriter(config_path)
    writer.save(
        WeChatEnvironmentConfig(
            data_root=saved_root,
            db_key=FICTIONAL_KEY,
            wcdb_cli_path=helper,
            wcdb_dll_path=library,
        )
    )

    def build_provider(config: WeChatEnvironmentConfig) -> Any:
        return WeChatDatabaseProvider(
            data_root=config.data_root,
            db_key=config.db_key,
            wcdb_cli_path=config.wcdb_cli_path,
            wcdb_dll_path=config.wcdb_dll_path,
            timeout=10,
            runner=runner,
        )

    factory = WeChatProviderFactory(
        config_loader=loader,
        provider_builder=build_provider,
    )
    service = WeChatSetupService(
        config_loader=loader,
        config_writer=writer,
        provider_factory=factory,
        data_roots_detector=lambda: list(roots),
    )
    return service, loader, factory


def _verify_calls(runner: _MultiAccountRunner) -> list[tuple[Path, str]]:
    return [
        (database, sql)
        for database, sql, _environment in runner.calls
        if sql == VERIFY_SQL
    ]


def test_unique_readable_candidate_recovers_to_owning_account_root(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    parent = tmp_path / "fictional_wechat_root"
    account_a = _make_account(parent, "account_a")
    account_b = _make_account(parent, "account_b")
    account_c = _make_account(parent, "account_c")
    roots = (account_a, account_b, account_c)
    runner = _MultiAccountRunner(roots, {account_b})
    service, loader, _factory = _service_harness(
        tmp_path,
        roots,
        runner,
        saved_root=account_a,
    )

    with caplog.at_level("INFO"):
        assert service.verify_connection() is None

    assert _verify_calls(runner) == [
        (_session_db(account_a), VERIFY_SQL),
        (_session_db(account_a), VERIFY_SQL),
        (_session_db(account_b), VERIFY_SQL),
        (_session_db(account_c), VERIFY_SQL),
        (_session_db(account_b), VERIFY_SQL),
    ]
    assert loader.load().data_root == account_b
    logs = caplog.text
    assert "wechat.database.recovery unique_candidate=true" in logs
    assert "wechat.database.recovery verify_success=true" in logs
    assert "wechat.database.recovery persisted=true" in logs


def test_recovered_provider_reads_later_databases_from_same_account(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "fictional_wechat_root"
    account_a = _make_account(parent, "account_a")
    account_b = _make_account(parent, "account_b")
    account_c = _make_account(parent, "account_c")
    roots = (account_a, account_b, account_c)
    runner = _MultiAccountRunner(roots, {account_b})
    service, _loader, factory = _service_harness(
        tmp_path,
        roots,
        runner,
        saved_root=account_a,
    )

    assert service.verify_connection() is None
    runner.calls.clear()

    sessions = factory.create().list_sessions()

    assert [session.session_id for session in sessions] == [FICTIONAL_CONTACT]
    databases = {database for database, _sql, _environment in runner.calls}
    assert databases == {
        _session_db(account_b),
        account_b / "db_storage" / "message" / "message_0.db",
        account_b / "db_storage" / "message" / "contact.db",
    }


def test_all_candidates_unreadable_keeps_original_root(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "fictional_wechat_root"
    account_a = _make_account(parent, "account_a")
    account_b = _make_account(parent, "account_b")
    account_c = _make_account(parent, "account_c")
    roots = (account_a, account_b, account_c)
    runner = _MultiAccountRunner(roots, set())
    service, loader, _factory = _service_harness(
        tmp_path,
        roots,
        runner,
        saved_root=account_a,
    )

    with pytest.raises(DatabaseUnreadable):
        service.verify_connection()

    assert loader.load().data_root == account_a
    assert len(_verify_calls(runner)) == 4


def test_multiple_readable_candidates_do_not_auto_recover(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "fictional_wechat_root"
    account_a = _make_account(parent, "account_a")
    account_b = _make_account(parent, "account_b")
    account_c = _make_account(parent, "account_c")
    roots = (account_a, account_b, account_c)
    runner = _MultiAccountRunner(roots, {account_a, account_b})
    service, loader, _factory = _service_harness(
        tmp_path,
        roots,
        runner,
        saved_root=account_c,
    )

    with pytest.raises(DatabaseUnreadable):
        service.verify_connection()

    assert loader.load().data_root == account_c
    assert len(_verify_calls(runner)) == 4


def test_second_formal_verify_failure_does_not_persist_recovery(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    parent = tmp_path / "fictional_wechat_root"
    account_a = _make_account(parent, "account_a")
    account_b = _make_account(parent, "account_b")
    account_c = _make_account(parent, "account_c")
    roots = (account_a, account_b, account_c)
    runner = _MultiAccountRunner(
        roots,
        {account_b},
        fail_second_readable_verify=True,
    )
    service, loader, _factory = _service_harness(
        tmp_path,
        roots,
        runner,
        saved_root=account_a,
    )

    with caplog.at_level("INFO"):
        with pytest.raises(DatabaseUnreadable):
            service.verify_connection()

    assert loader.load().data_root == account_a
    assert len(_verify_calls(runner)) == 5
    assert "wechat.database.recovery unique_candidate=true" in caplog.text
    assert "wechat.database.recovery verify_success=false" in caplog.text
    assert "wechat.database.recovery persisted=true" not in caplog.text


def test_recovery_logs_do_not_expose_paths_accounts_or_key(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    parent = tmp_path / "fictional_wechat_root"
    account_a = _make_account(parent, "account_a")
    account_b = _make_account(parent, "account_b")
    account_c = _make_account(parent, "account_c")
    roots = (account_a, account_b, account_c)
    sensitive_error = (
        f"{_session_db(account_a)} {_session_db(account_b)} "
        f"{FICTIONAL_KEY} {VERIFY_SQL} {FICTIONAL_CHAT_TEXT}"
    )
    runner = _MultiAccountRunner(
        roots,
        {account_b},
        sensitive_error=sensitive_error,
    )
    service, _loader, _factory = _service_harness(
        tmp_path,
        roots,
        runner,
        saved_root=account_a,
    )

    with caplog.at_level("INFO"):
        assert service.verify_connection() is None

    logs = caplog.text
    assert str(parent) not in logs
    assert "account_a" not in logs
    assert "account_b" not in logs
    assert "account_c" not in logs
    assert FICTIONAL_KEY not in logs
    assert VERIFY_SQL not in logs
    assert FICTIONAL_CHAT_TEXT not in logs
