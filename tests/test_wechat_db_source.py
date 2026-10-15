"""Behavioral tests for the WeChat database source (WCDB provider chain).

All fixtures are fictional. No real WeChat data, key, or account appears here.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
import zstandard as zstd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer import wechat_db_adapter
from qq_chat_analyzer.application import ImportRequest, ImportService
from qq_chat_analyzer.application.import_service import WECHAT_DB_FORMAT
from qq_chat_analyzer.legacy_projection import project_legacy_message
from qq_chat_analyzer.rich_message import (
    EXPRESSION_KIND_PLATFORM_FACE,
    ExpressionContent,
    TextContent,
)
from qq_chat_analyzer.providers.wechat_database_provider import (
    DatabaseNotFound,
    DatabaseUnreadable,
    KeyUnavailable,
    QueryFailed,
    WeChatDatabaseProvider,
    message_table_name,
    _sanitize_wcdb_message,
)
from qq_chat_analyzer.providers import wechat_database_provider


TEXT_LOCAL_TYPE = 1
IMAGE_LOCAL_TYPE = 3
STICKER_LOCAL_TYPE = 47
FICTIONAL_KEY = "a" * 64
FICTIONAL_SESSION = "wxid_fictional_room@chatroom"


def _db_row(
    message_content: str = "\u4f60\u597d\uff0c\u4eca\u5929\u5929\u6c14\u4e0d\u9519",
    local_type: object = TEXT_LOCAL_TYPE,
    create_time: object = 1753412807,
    user_name: object = "wxid_fictional_sender",
    server_id: object = 900001,
    local_id: object = 11,
) -> dict[str, object]:
    return {
        "local_id": local_id,
        "server_id": server_id,
        "local_type": local_type,
        "create_time": create_time,
        "message_content": message_content,
        "user_name": user_name,
    }


def _write_db_export(
    path: Path,
    rows: list[object],
    username: str = FICTIONAL_SESSION,
) -> None:
    document = {
        "source": "wechat-db",
        "conversation": {"username": username},
        "messages": rows,
    }
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def _bracket_expression(export: Path, text: str) -> ExpressionContent:
    """Return the single expression content parsed from a fictional text row."""
    _write_db_export(export, [_db_row(message_content=text)])
    contents = wechat_db_adapter.parse_rich_messages(
        wechat_db_adapter.load_messages(export)
    )[0].contents
    assert contents[0] == TextContent(text=text)
    assert len(contents) == 2
    return contents[1]


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


def test_wcdb_subprocess_hides_console_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def run(command, **options):
        calls.append((command, options))
        return _FakeCompleted()

    monkeypatch.setattr(wechat_database_provider.os, "name", "nt")
    monkeypatch.setattr(
        wechat_database_provider.subprocess,
        "CREATE_NO_WINDOW",
        0x08000000,
        raising=False,
    )
    monkeypatch.setattr(wechat_database_provider.subprocess, "run", run)

    command = ["wcdb_cli.exe", "--wcdb", "WCDB.dll"]
    wechat_database_provider._run_subprocess(command, 30, {"WX_DB_KEY": "x"})

    assert calls[0][0] == command
    assert calls[0][1]["creationflags"] == 0x08000000
    assert calls[0][1]["timeout"] == 30
    assert calls[0][1]["env"] == {"WX_DB_KEY": "x"}


def test_wcdb_subprocess_omits_windows_creation_flags_on_non_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def run(command, **options):
        calls.append((command, options))
        return _FakeCompleted()

    monkeypatch.setattr(wechat_database_provider.os, "name", "posix")
    monkeypatch.setattr(wechat_database_provider.subprocess, "run", run)

    command = ["wcdb_cli.exe", "--wcdb", "WCDB.dll"]
    wechat_database_provider._run_subprocess(command, 30, {"WX_DB_KEY": "x"})

    assert calls[0][0] == command
    assert "creationflags" not in calls[0][1]


def _helper_result(rows: list[object], columns: list[str] | None = None) -> str:
    return json.dumps(
        {
            "ok": True,
            "columns": columns or ["local_id"],
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
    return _helper_result(
        pragma_rows,
        columns=["cid", "name", "type", "notnull", "dflt_value", "pk"],
    )


def _make_data_root(
    tmp_path: Path,
    table: str | None = None,
    account_name: str = "wxid_owner",
) -> Path:
    """Build a fictional WeChat data directory layout."""
    storage = tmp_path / "xwechat_files" / account_name / "db_storage"
    message_dir = storage / "message"
    message_dir.mkdir(parents=True, exist_ok=True)
    (message_dir / "session.db").write_bytes(b"fake")
    (message_dir / "message_0.db").write_bytes(b"fake")
    return tmp_path / "xwechat_files"


def _provider(
    tmp_path: Path,
    runner,
    account_name: str = "wxid_owner",
) -> WeChatDatabaseProvider:
    helper = tmp_path / "wcdb_cli.exe"
    helper.write_bytes(b"fake")
    library = tmp_path / "WCDB.dll"
    library.write_bytes(b"fake")
    return WeChatDatabaseProvider(
        data_root=_make_data_root(tmp_path, account_name=account_name),
        db_key=FICTIONAL_KEY,
        wcdb_cli_path=helper,
        wcdb_dll_path=library,
        runner=runner,
    )


# ------------------------------------------------------------------ adapter


def _counting_session_provider(tmp_path, shards, usernames, faults=None, native_cli=None):
    """Execute provider SQL on fictional SQLite DBs at the helper boundary."""
    queries = []
    faults = faults or {}

    def runner(command, timeout, environment):
        sql = command[command.index("--sql") + 1]
        database = Path(command[command.index("--db") + 1])
        queries.append((database.name, sql))
        assert "message_content" not in sql
        if native_cli is not None:
            command = list(command)
            command[0] = str(native_cli)
            command[command.index("--wcdb") + 1] = str(native_cli.with_name("WCDB.dll"))
            command.append("--no-cipher")
            return subprocess.run(
                command, timeout=timeout, env=environment, capture_output=True,
                text=True, encoding="utf-8",
            )
        fault = faults.get(database.name)
        if (fault == "inventory" and "sqlite_master" in sql) or (
            fault == "count" and "COUNT(*)" in sql
        ):
            return _FakeCompleted(stdout=json.dumps({"ok": False}))
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.row_factory = sqlite3.Row
            rows = [dict(row) for row in connection.execute(sql)]
        if "COUNT(*)" in sql:
            if fault == "omit":
                rows = rows[1:]
            elif fault == "invalid":
                rows[0]["message_count"] = -1
            elif fault == "duplicate":
                rows.append(rows[0])
        return _FakeCompleted(stdout=_helper_result(rows))

    provider = _provider(tmp_path, runner)
    directory = tmp_path / "xwechat_files" / "wxid_owner" / "db_storage" / "message"
    for database in directory.glob("*.db"):
        database.unlink()  # Only this helper's fictional placeholders.
    with closing(sqlite3.connect(directory / "session.db")) as connection, connection:
        connection.execute("CREATE TABLE SessionTable (username TEXT, last_timestamp INTEGER)")
        connection.executemany(
            "INSERT INTO SessionTable VALUES (?, ?)",
            [(username, 100 + index) for index, username in enumerate(usernames)],
        )
    for index, tables in enumerate(shards):
        with closing(sqlite3.connect(directory / f"message_{index}.db")) as connection, connection:
            for username, count in tables.items():
                table = message_table_name(username)
                connection.execute(f'CREATE TABLE "{table}" (local_type INTEGER)')
                connection.executemany(
                    f'INSERT INTO "{table}" VALUES (?)',
                    [(1 if row % 2 else 3,) for row in range(count)],
                )
    return provider, queries


def test_session_counts_sum_shards_include_all_types_and_reach_facade(tmp_path):
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, ChatSource
    from qq_chat_analyzer.application.wechat.wechat_export_import_service import WeChatExportImportService

    provider, queries = _counting_session_provider(
        tmp_path,
        [{"wxid_alpha": 3, "wxid_empty": 0}, {"wxid_alpha": 4, "wxid_beta": 2}, {}],
        ["wxid_alpha", "wxid_empty", "wxid_beta", "wxid_missing"],
    )
    facade = ChatAnalyzerFacade(wechat_service=WeChatExportImportService(provider=provider))
    sessions = facade.list_sessions(ChatSource.WECHAT)
    by_id = {session.session_id: session for session in sessions}
    assert by_id["wxid_alpha"].message_count == 7
    assert by_id["wxid_beta"].message_count == 2
    assert by_id["wxid_empty"].message_count == 0
    assert by_id["wxid_empty"].message_available is True
    assert by_id["wxid_missing"].message_count is None
    assert by_id["wxid_missing"].message_available is False
    assert by_id["wxid_alpha"].last_message_time == 100
    assert len([sql for _, sql in queries if "sqlite_master" in sql]) == 3
    assert len([sql for _, sql in queries if "COUNT(*)" in sql]) == 2


@pytest.mark.parametrize("fault", ["inventory", "count", "omit", "invalid", "duplicate"])
def test_session_counts_never_publish_partial_or_invalid_totals(tmp_path, fault):
    provider, _ = _counting_session_provider(
        tmp_path, [{"wxid_alpha": 3}, {"wxid_alpha": 4}], ["wxid_alpha"],
        faults={"message_1.db": fault},
    )
    session = provider.list_sessions()[0]
    assert session.message_count is None
    assert session.message_available is True


def test_session_counts_batch_many_tables_without_per_session_processes(tmp_path):
    usernames = [f"wxid_fictional_{index}" for index in range(205)]
    provider, queries = _counting_session_provider(
        tmp_path, [dict.fromkeys(usernames, 2), dict.fromkeys(usernames, 3)], usernames,
    )
    sessions = provider.list_sessions(limit=300)
    assert len(sessions) == 205
    assert all(session.message_count == 5 for session in sessions)
    count_sql = [sql for _, sql in queries if "COUNT(*)" in sql]
    assert len(count_sql) <= 6
    assert all(len(sql) < 20000 for sql in count_sql)


def test_session_counts_failure_does_not_discard_unaffected_counts(tmp_path):
    provider, _ = _counting_session_provider(
        tmp_path, [{"wxid_alpha": 3}, {"wxid_beta": 4}], ["wxid_alpha", "wxid_beta"],
        faults={"message_1.db": "count"},
    )
    by_id = {session.session_id: session for session in provider.list_sessions()}
    assert by_id["wxid_alpha"].message_count == 3
    assert by_id["wxid_beta"].message_count is None


@pytest.mark.slow_integration
def test_session_counts_native_wcdb_batches_and_shards(tmp_path):
    configured = os.environ.get("ECHO_NATIVE_WCDB_CLI_PATH")
    if not configured:
        pytest.skip("ECHO_NATIVE_WCDB_CLI_PATH is required for native counting")
    native_cli = Path(configured)
    assert native_cli.is_file() and native_cli.with_name("WCDB.dll").is_file()
    usernames = [f"wxid_fictional_{index}" for index in range(205)]
    provider, queries = _counting_session_provider(
        tmp_path, [dict.fromkeys(usernames, 2), dict.fromkeys(usernames, 3)],
        usernames, native_cli=native_cli,
    )
    sessions = provider.list_sessions(limit=300)
    assert len(sessions) == 205
    assert all(session.message_count == 5 for session in sessions)
    assert len([sql for _, sql in queries if "COUNT(*)" in sql]) <= 6


def test_text_row_becomes_rich_message_then_projects_to_legacy(
    tmp_path: Path,
) -> None:
    export = tmp_path / "session.json"
    row = _db_row()
    row["sender_name"] = "Fictional Alice"
    _write_db_export(export, [row])

    rich_messages = wechat_db_adapter.parse_rich_messages(
        wechat_db_adapter.load_messages(export)
    )

    assert len(rich_messages) == 1
    rich_message = rich_messages[0]
    assert rich_message.source == "wechat"
    assert rich_message.message_id == "900001"
    assert rich_message.conversation_id == FICTIONAL_SESSION
    assert rich_message.sender.identity_id == "wxid_fictional_sender"
    assert rich_message.sender.display_name == "Fictional Alice"
    assert rich_message.timestamp == 1753412807
    assert rich_message.message_type == "text"
    assert rich_message.contents == (
        TextContent(text="\u4f60\u597d\uff0c\u4eca\u5929\u5929\u6c14\u4e0d\u9519"),
    )
    assert rich_message.relations == ()
    assert rich_message.recall_state is None

    legacy_message = project_legacy_message(rich_message)
    assert legacy_message.sender == "Fictional Alice"
    assert legacy_message.text == "\u4f60\u597d\uff0c\u4eca\u5929\u5929\u6c14\u4e0d\u9519"
    assert legacy_message.timestamp == 1753412807


def test_text_row_with_official_bracket_emoji_splits_expression_content(
    tmp_path: Path,
) -> None:
    export = tmp_path / "session.json"
    text = "哈哈[捂脸]来了[旺柴]"
    _write_db_export(export, [_db_row(message_content=text)])

    rich_messages = wechat_db_adapter.parse_rich_messages(
        wechat_db_adapter.load_messages(export)
    )

    assert len(rich_messages) == 1
    assert rich_messages[0].contents == (
        TextContent(text=text),
        ExpressionContent(
            expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
            expression_key="捂脸",
            display_text="[捂脸]",
            source="wechat",
            position=0,
            text_before="哈哈",
            text_after="来了",
        ),
        ExpressionContent(
            expression_kind=EXPRESSION_KIND_PLATFORM_FACE,
            expression_key="旺柴",
            display_text="[旺柴]",
            source="wechat",
            position=1,
            text_before="来了",
            text_after="",
        ),
    )
    legacy = project_legacy_message(rich_messages[0])
    assert legacy.text == text


def test_text_row_keeps_unknown_bracket_text_as_plain_text(
    tmp_path: Path,
) -> None:
    export = tmp_path / "session.json"
    text = "今天[某个自定义词]继续"
    _write_db_export(export, [_db_row(message_content=text)])

    rich_messages = wechat_db_adapter.parse_rich_messages(
        wechat_db_adapter.load_messages(export)
    )

    assert rich_messages[0].contents == (TextContent(text=text),)


def test_english_alias_is_normalized_to_the_chinese_official_expression(
    tmp_path: Path,
) -> None:
    expression = _bracket_expression(tmp_path / "session.json", "哈哈[Facepalm]来了")

    assert expression.expression_kind == EXPRESSION_KIND_PLATFORM_FACE
    assert expression.expression_key == "捂脸"
    assert expression.source == "wechat"
    assert expression.text_before == "哈哈"
    assert expression.text_after == "来了"


def test_text_row_becomes_chat_message_with_mapped_fields(tmp_path: Path) -> None:
    export = tmp_path / "session.json"
    _write_db_export(export, [_db_row()])

    messages = wechat_db_adapter.parse_messages(
        wechat_db_adapter.load_messages(export)
    )

    assert len(messages) == 1
    message = messages[0]
    assert message.timestamp == 1753412807
    assert message.sender == "wxid_fictional_sender"
    assert message.sender_id == "wxid_fictional_sender"
    assert message.text == "\u4f60\u597d\uff0c\u4eca\u5929\u5929\u6c14\u4e0d\u9519"
    assert message.platform == "wechat"
    assert message.conversation_id == FICTIONAL_SESSION
    assert message.message_type == "text"
    assert message.source_type == TEXT_LOCAL_TYPE
    assert message.message_id == "900001"
    assert message.is_system is False
    assert message.recalled is False


def test_db_row_uses_resolved_sender_name(tmp_path: Path) -> None:
    export = tmp_path / "session.json"
    row = _db_row()
    row["sender_name"] = "\u5907\u6ce8\u540d"
    _write_db_export(export, [row])

    messages = wechat_db_adapter.parse_messages(
        wechat_db_adapter.load_messages(export)
    )

    assert messages[0].sender == "\u5907\u6ce8\u540d"
    assert messages[0].sender_id == "wxid_fictional_sender"


def test_non_text_local_types_are_skipped(tmp_path: Path) -> None:
    export = tmp_path / "session.json"
    _write_db_export(
        export,
        [_db_row(local_type=IMAGE_LOCAL_TYPE), _db_row(local_type=49)],
    )

    messages = wechat_db_adapter.parse_messages(
        wechat_db_adapter.load_messages(export)
    )

    assert messages == []


def test_sticker_row_becomes_rich_expression_and_legacy_message(
    tmp_path: Path,
) -> None:
    export = tmp_path / "session.json"
    row = _db_row(
        local_type=STICKER_LOCAL_TYPE,
        server_id=900047,
        message_content=(
            '<msg><emoji md5="fictionalmd5abcdef" '
            'cdnurl="fictional-cdn-url"/></msg>'
        ),
    )
    row["sender_name"] = "Fictional Alice"
    _write_db_export(export, [row])

    rich_messages = wechat_db_adapter.parse_rich_messages(
        wechat_db_adapter.load_messages(export)
    )

    assert len(rich_messages) == 1
    rich_message = rich_messages[0]
    assert rich_message.message_type == "sticker"
    assert rich_message.contents == (
        ExpressionContent(
            expression_kind="sticker",
            expression_key="fictionalmd5abcdef",
            display_text="[贴图]",
            source="wechat",
            position=0,
        ),
    )
    legacy = project_legacy_message(rich_message)
    assert legacy.text == ""
    assert legacy.message_type == "sticker"


def test_sticker_row_falls_back_to_message_id_without_md5(tmp_path: Path) -> None:
    export = tmp_path / "session.json"
    row = _db_row(
        local_type=STICKER_LOCAL_TYPE,
        server_id=900048,
        message_content="not-valid-xml",
    )
    _write_db_export(export, [row])

    rich_messages = wechat_db_adapter.parse_rich_messages(
        wechat_db_adapter.load_messages(export)
    )

    assert rich_messages[0].contents == (
        ExpressionContent(
            expression_kind="sticker",
            expression_key="900048",
            display_text="[贴图]",
            source="wechat",
            position=0,
        ),
    )


def test_sticker_row_decodes_zstd_compressed_content(tmp_path: Path) -> None:
    export = tmp_path / "session.json"
    xml = '<msg><emoji md5="compressedmd5"/></msg>'.encode("utf-8")
    compressed = zstd.ZstdCompressor().compress(xml)
    row = _db_row(
        local_type=STICKER_LOCAL_TYPE,
        server_id=900049,
        message_content=compressed.hex(),
    )
    row["WCDB_CT_message_content"] = 4
    _write_db_export(export, [row])

    rich_messages = wechat_db_adapter.parse_rich_messages(
        wechat_db_adapter.load_messages(export)
    )

    assert rich_messages[0].contents[0].expression_key == "compressedmd5"


def test_import_service_carries_wechat_sticker_rich_messages(
    tmp_path: Path,
) -> None:
    export = tmp_path / "session.json"
    row = _db_row(
        local_type=STICKER_LOCAL_TYPE,
        server_id=900050,
        message_content='<msg><emoji md5="importedsticker"/></msg>',
    )
    _write_db_export(export, [row])

    outcome = ImportService().execute(ImportRequest(input_path=export))

    assert len(outcome.rich_messages) == 1
    assert outcome.rich_messages[0].source == "wechat"
    assert outcome.rich_messages[0].contents[0].expression_key == "importedsticker"
    assert outcome.messages[0].text == ""
    assert outcome.messages[0].message_type == "sticker"


@pytest.mark.parametrize(
    "row",
    [
        _db_row(create_time=None),
        _db_row(create_time=True),
        _db_row(message_content=None),
        _db_row(user_name=None),
        _db_row(user_name="   "),
        _db_row(local_type="text"),
        _db_row(local_type=True),
        "not-a-mapping",
        None,
    ],
)
def test_malformed_rows_are_isolated(row: object) -> None:
    assert wechat_db_adapter.parse_message(row) is None


def test_malformed_rows_do_not_drop_valid_neighbours(tmp_path: Path) -> None:
    export = tmp_path / "session.json"
    _write_db_export(export, [_db_row(create_time=None), _db_row(), "junk"])

    messages = wechat_db_adapter.parse_messages(
        wechat_db_adapter.load_messages(export)
    )

    assert len(messages) == 1


def test_row_username_takes_precedence_over_conversation(tmp_path: Path) -> None:
    export = tmp_path / "session.json"
    row = _db_row()
    row["username"] = "wxid_explicit_conversation"
    _write_db_export(export, [row])

    messages = wechat_db_adapter.parse_messages(
        wechat_db_adapter.load_messages(export)
    )

    assert messages[0].conversation_id == "wxid_explicit_conversation"


# ----------------------------------------------------------------- provider


def test_list_sessions_returns_privacy_safe_descriptors(tmp_path: Path) -> None:
    rows = [
        {"username": FICTIONAL_SESSION, "last_timestamp": 1753412900},
        {"username": "wxid_friend", "last_timestamp": 1753412800},
        {"username": "   ", "last_timestamp": 1},
        "junk",
    ]

    def runner(command, timeout, environment):
        sql = " ".join(command)
        if "PRAGMA table_info" in sql:
            return _FakeCompleted(
                stdout=_schema_result(["username", "summary", "last_timestamp"])
            )
        if "SessionTable" in sql:
            return _FakeCompleted(stdout=_helper_result(rows))
        if "sqlite_master" in sql:
            return _FakeCompleted(
                stdout=_helper_result([], columns=["name"])
            )
        raise AssertionError(f"unexpected query: {sql}")

    sessions = _provider(tmp_path, runner).list_sessions()

    assert [session.session_id for session in sessions] == [
        FICTIONAL_SESSION,
        "wxid_friend",
    ]
    assert [session.session_type for session in sessions] == [
        "group",
        "private",
    ]
    assert [getattr(session, "last_timestamp", None) for session in sessions] == [
        1753412900, 1753412800,
    ]


@pytest.mark.parametrize("timestamp, expected", [
    (1753412900, 1753412900), ("1753412900000", 1753412900),
    (None, None), ("invalid", None), (True, None),
])
def test_session_metadata_reaches_facade_without_message_queries(tmp_path, timestamp, expected):
    from qq_chat_analyzer.application.facade import ChatSource, _to_session_info

    def runner(command, timeout, environment):
        sql = command[command.index("--sql") + 1]
        if sql.startswith("PRAGMA table_info"):
            return _FakeCompleted(stdout=_schema_result(["username", "last_timestamp"]))
        if "FROM SessionTable" in sql:
            return _FakeCompleted(stdout=_helper_result([
                {"username": FICTIONAL_SESSION, "last_timestamp": timestamp},
            ]))
        if "sqlite_master" in sql:
            return _FakeCompleted(stdout=_helper_result([]))
        raise AssertionError(f"Unexpected query (must not scan messages): {sql}")

    raw = _provider(tmp_path, runner).list_sessions()[0]
    session = _to_session_info(ChatSource.WECHAT, raw)
    assert session.last_message_time == expected
    assert session.message_count is None


def test_list_sessions_marks_missing_msg_tables_unavailable(
    tmp_path: Path,
) -> None:
    available_session = "wxid_has_messages"
    missing_session = "wxid_no_messages"
    available_table = message_table_name(available_session)
    session_rows = [
        {"username": available_session, "last_timestamp": 1753412900},
        {"username": missing_session, "last_timestamp": 1753412800},
    ]

    def runner(command, timeout, environment):
        sql = " ".join(command)
        if "PRAGMA table_info" in sql:
            return _FakeCompleted(
                stdout=_schema_result(["username", "summary", "last_timestamp"])
            )
        if "SessionTable" in sql:
            return _FakeCompleted(stdout=_helper_result(session_rows))
        if "sqlite_master" in sql:
            return _FakeCompleted(
                stdout=_helper_result(
                    [{"name": available_table}],
                    columns=["name"],
                )
            )
        raise AssertionError(f"unexpected query: {sql}")

    sessions = _provider(tmp_path, runner).list_sessions()

    assert len(sessions) == 2
    assert sessions[0].message_available is True
    assert sessions[0].unavailable_reason is None
    assert sessions[1].message_available is False
    assert sessions[1].unavailable_reason


def test_list_sessions_resolves_contact_display_names(tmp_path: Path) -> None:
    private_session = "wxid_friend"
    no_contact_session = "wxid_no_contact"
    group_session = "room@chatroom"
    session_rows = [
        {"username": private_session, "last_timestamp": 1753412900},
        {"username": no_contact_session, "last_timestamp": 1753412800},
        {"username": group_session, "last_timestamp": 1753412700},
    ]
    contact_rows = [
        {
            "username": private_session,
            "remark": "\u5907\u6ce8\u540d",
            "nick_name": "\u6635\u79f0",
        },
        {
            "username": group_session,
            "remark": "",
            "nick_name": "\u7fa4\u804a\u540d",
        },
    ]

    def runner(command, timeout, environment):
        sql = " ".join(command)
        if "PRAGMA table_info" in sql:
            return _FakeCompleted(
                stdout=_schema_result(["username", "summary", "last_timestamp"])
            )
        if "SessionTable" in sql:
            return _FakeCompleted(stdout=_helper_result(session_rows))
        if "FROM contact" in sql:
            return _FakeCompleted(
                stdout=_helper_result(
                    contact_rows,
                    columns=["username", "remark", "nick_name"],
                )
            )
        if "sqlite_master" in sql:
            return _FakeCompleted(
                stdout=_helper_result([], columns=["name"])
            )
        raise AssertionError(f"unexpected query: {sql}")

    provider = _provider(tmp_path, runner)
    contact_dir = (
        tmp_path
        / "xwechat_files"
        / "wxid_owner"
        / "db_storage"
        / "contact"
    )
    contact_dir.mkdir(parents=True, exist_ok=True)
    (contact_dir / "contact.db").write_bytes(b"fake")

    sessions = provider.list_sessions()

    assert [session.display_name for session in sessions] == [
        "\u5907\u6ce8\u540d",
        no_contact_session,
        "\u7fa4\u804a\u540d",
    ]


def test_list_sessions_filters_official_and_system_sessions(
    tmp_path: Path,
) -> None:
    private_session = "wxid_friend"
    group_session = "room@chatroom"
    session_rows = [
        {"username": private_session, "last_timestamp": 1753412900},
        {"username": group_session, "last_timestamp": 1753412800},
        {"username": "gh_official", "last_timestamp": 1753412700},
        {"username": "notify", "last_timestamp": 1753412600},
        {"username": "unknown-system-account", "last_timestamp": 1753412500},
    ]

    def runner(command, timeout, environment):
        sql = " ".join(command)
        if "PRAGMA table_info" in sql:
            return _FakeCompleted(
                stdout=_schema_result(["username", "summary", "last_timestamp"])
            )
        if "SessionTable" in sql:
            return _FakeCompleted(stdout=_helper_result(session_rows))
        if "sqlite_master" in sql:
            return _FakeCompleted(
                stdout=_helper_result([], columns=["name"])
            )
        raise AssertionError(f"unexpected query: {sql}")

    sessions = _provider(tmp_path, runner).list_sessions()

    assert [session.session_id for session in sessions] == [
        private_session,
        group_session,
    ]
    assert [session.session_type for session in sessions] == [
        "private",
        "group",
    ]


def test_export_session_json_writes_provider_document(tmp_path: Path) -> None:
    table = message_table_name(FICTIONAL_SESSION)
    seen_sql: list[str] = []

    def runner(command, timeout, environment):
        sql = command[command.index("--sql") + 1]
        seen_sql.append(sql)
        assert environment["WX_DB_KEY"] == FICTIONAL_KEY
        if "sqlite_master" in sql:
            return _FakeCompleted(stdout=_helper_result([{"name": table}]))
        return _FakeCompleted(stdout=_helper_result([_db_row()]))

    provider = _provider(tmp_path, runner)
    output = tmp_path / "out" / "session.json"

    result = provider.export_session_json(FICTIONAL_SESSION, output)

    assert result == output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["source"] == "wechat-db"
    assert payload["conversation"]["username"] == FICTIONAL_SESSION
    assert len(payload["messages"]) == 1
    message_sql = seen_sql[-1]
    assert table in message_sql
    assert "(m.local_type & 0xFFFFFFFF) IN (1, 47)" in message_sql
    assert "WCDB_CT_message_content" in message_sql
    assert "Name2Id" in message_sql


def test_export_session_json_resolves_sender_display_names(
    tmp_path: Path,
) -> None:
    table = message_table_name(FICTIONAL_SESSION)
    sender = "wxid_fictional_sender"
    contact_rows = [
        {
            "username": sender,
            "remark": "\u5907\u6ce8\u540d",
            "nick_name": "\u6635\u79f0",
        }
    ]

    def runner(command, timeout, environment):
        sql = command[command.index("--sql") + 1]
        if "FROM contact" in sql:
            return _FakeCompleted(
                stdout=_helper_result(
                    contact_rows,
                    columns=["username", "remark", "nick_name"],
                )
            )
        if "sqlite_master" in sql:
            return _FakeCompleted(stdout=_helper_result([{"name": table}]))
        return _FakeCompleted(stdout=_helper_result([_db_row(user_name=sender)]))

    provider = _provider(tmp_path, runner)
    contact_dir = (
        tmp_path
        / "xwechat_files"
        / "wxid_owner"
        / "db_storage"
        / "contact"
    )
    contact_dir.mkdir(parents=True, exist_ok=True)
    (contact_dir / "contact.db").write_bytes(b"fake")
    output = tmp_path / "out" / "session.json"

    provider.export_session_json(FICTIONAL_SESSION, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["messages"][0]["sender_name"] == "\u5907\u6ce8\u540d"


def test_export_session_json_writes_self_username_from_account_dir(
    tmp_path: Path,
) -> None:
    table = message_table_name(FICTIONAL_SESSION)

    def runner(command, timeout, environment):
        sql = command[command.index("--sql") + 1]
        if "FROM contact" in sql:
            return _FakeCompleted(stdout=_helper_result([]))
        if "sqlite_master" in sql:
            return _FakeCompleted(stdout=_helper_result([{"name": table}]))
        return _FakeCompleted(stdout=_helper_result([_db_row()]))

    provider = _provider(tmp_path, runner)
    output = tmp_path / "out" / "session.json"

    provider.export_session_json(FICTIONAL_SESSION, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["conversation"]["self_username"] == "wxid_owner"


def test_resolve_self_username_canonicalizes_account_directory_suffix(
    tmp_path: Path,
) -> None:
    base_identity = "wxid_fictional_owner"
    account_directory = f"{base_identity}_a1b2c3d4"
    table = message_table_name(FICTIONAL_SESSION)

    def runner(command, timeout, environment):
        sql = command[command.index("--sql") + 1]
        if "FROM contact" in sql:
            return _FakeCompleted(
                stdout=_helper_result(
                    [{"username": base_identity}],
                    columns=["username"],
                )
            )
        if "sqlite_master" in sql:
            return _FakeCompleted(stdout=_helper_result([{"name": table}]))
        return _FakeCompleted(
            stdout=_helper_result([_db_row(user_name=base_identity)])
        )

    provider = _provider(
        tmp_path,
        runner,
        account_name=account_directory,
    )
    contact_dir = (
        tmp_path
        / "xwechat_files"
        / account_directory
        / "db_storage"
        / "contact"
    )
    contact_dir.mkdir(parents=True, exist_ok=True)
    (contact_dir / "contact.db").write_bytes(b"fake")

    assert provider._resolve_self_username() == base_identity

    output = tmp_path / "out" / "session.json"
    provider.export_session_json(FICTIONAL_SESSION, output)
    outcome = ImportService().execute(ImportRequest(input_path=output))

    assert outcome.messages[0].sender_id == base_identity
    assert outcome.messages[0].is_self is True


def test_resolve_self_username_keeps_unconfirmed_hex_ending_username(
    tmp_path: Path,
) -> None:
    legal_identity = "wxid_fictional_feed"

    def runner(command, timeout, environment):
        sql = command[command.index("--sql") + 1]
        if "FROM contact" in sql:
            return _FakeCompleted(
                stdout=_helper_result(
                    [{"username": legal_identity}],
                    columns=["username"],
                )
            )
        return _FakeCompleted(stdout=_helper_result([]))

    provider = _provider(
        tmp_path,
        runner,
        account_name=legal_identity,
    )
    contact_dir = (
        tmp_path
        / "xwechat_files"
        / legal_identity
        / "db_storage"
        / "contact"
    )
    contact_dir.mkdir(parents=True, exist_ok=True)
    (contact_dir / "contact.db").write_bytes(b"fake")

    assert provider._resolve_self_username() == legal_identity


def test_exported_self_username_marks_db_messages(tmp_path: Path) -> None:
    table = message_table_name(FICTIONAL_SESSION)

    def runner(command, timeout, environment):
        sql = command[command.index("--sql") + 1]
        if "FROM contact" in sql:
            return _FakeCompleted(stdout=_helper_result([]))
        if "sqlite_master" in sql:
            return _FakeCompleted(stdout=_helper_result([{"name": table}]))
        return _FakeCompleted(
            stdout=_helper_result(
                [
                    _db_row(user_name="wxid_owner", message_content="mine"),
                    _db_row(
                        user_name="wxid_fictional_sender",
                        message_content="theirs",
                    ),
                ]
            )
        )

    provider = _provider(tmp_path, runner)
    output = tmp_path / "out" / "session.json"
    provider.export_session_json(FICTIONAL_SESSION, output)

    outcome = ImportService().execute(ImportRequest(input_path=output))

    assert [message.is_self for message in outcome.messages] == [True, False]


def test_time_window_is_pushed_into_the_query(tmp_path: Path) -> None:
    table = message_table_name(FICTIONAL_SESSION)
    seen_sql: list[str] = []

    def runner(command, timeout, environment):
        sql = command[command.index("--sql") + 1]
        seen_sql.append(sql)
        if "sqlite_master" in sql:
            return _FakeCompleted(stdout=_helper_result([{"name": table}]))
        return _FakeCompleted(stdout=_helper_result([]))

    provider = _provider(tmp_path, runner)
    provider.read_session_rows(
        FICTIONAL_SESSION,
        start_time=1753400000,
        end_time=1753500000,
    )

    message_sql = seen_sql[-1]
    assert "create_time >= 1753400000" in message_sql
    assert "create_time <= 1753500000" in message_sql


def test_key_is_never_placed_on_the_command_line(tmp_path: Path) -> None:
    captured: list[list[str]] = []

    def runner(command, timeout, environment):
        captured.append(list(command))
        sql = " ".join(command)
        if "PRAGMA table_info" in sql:
            return _FakeCompleted(
                stdout=_schema_result(["username", "summary", "last_timestamp"])
            )
        return _FakeCompleted(stdout=_helper_result([]))

    _provider(tmp_path, runner).list_sessions()

    assert FICTIONAL_KEY not in " ".join(captured[0])


def test_missing_key_raises_key_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WX_DB_KEY", raising=False)
    helper = tmp_path / "wcdb_cli.exe"
    helper.write_bytes(b"fake")
    library = tmp_path / "WCDB.dll"
    library.write_bytes(b"fake")
    provider = WeChatDatabaseProvider(
        data_root=_make_data_root(tmp_path),
        db_key=None,
        wcdb_cli_path=helper,
        wcdb_dll_path=library,
        runner=lambda *args: _FakeCompleted(stdout=_helper_result([])),
    )

    with pytest.raises(KeyUnavailable):
        provider.list_sessions()


def test_database_discovery_logs_success_without_paths(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _provider(
        tmp_path,
        lambda *args: _FakeCompleted(stdout=_helper_result([])),
    )

    with caplog.at_level(
        "INFO",
        logger="qq_chat_analyzer.providers.wechat_database_provider",
    ):
        session_db = provider._session_db_path()

    assert session_db.is_file()
    assert "wechat.database.discovery success=true" in caplog.text
    assert str(tmp_path) not in caplog.text


def test_database_discovery_logs_failure_without_paths(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = WeChatDatabaseProvider(
        data_root=tmp_path / "absent",
        db_key=FICTIONAL_KEY,
    )

    with caplog.at_level(
        "INFO",
        logger="qq_chat_analyzer.providers.wechat_database_provider",
    ):
        with pytest.raises(DatabaseNotFound):
            provider._session_db_path()

    assert "wechat.database.discovery success=false" in caplog.text
    assert str(tmp_path) not in caplog.text


def test_query_failure_logs_safe_wcdb_diagnostics(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_key = FICTIONAL_KEY

    def failing(command, timeout, environment):
        assert environment["WX_DB_KEY"] == secret_key
        sql = " ".join(command)
        if "PRAGMA table_info" in sql:
            return _FakeCompleted(
                stdout=_schema_result(["username", "summary", "last_timestamp"])
            )
        return _FakeCompleted(
            stdout=json.dumps(
                {
                    "ok": False,
                    "stage": "open",
                    "error": f"cipher open failed {secret_key}",
                }
            ),
            stderr=f"native stderr: open failed {secret_key}",
            returncode=17,
        )

    provider = _provider(tmp_path, failing)

    with caplog.at_level(
        "INFO",
        logger="qq_chat_analyzer.providers.wechat_database_provider",
    ):
        with pytest.raises(QueryFailed):
            provider.list_sessions()

    logs = caplog.text
    assert "wechat.wcdb.failed" in logs
    assert "database_type=session" in logs
    assert "database_file=" not in logs
    assert "database_path=" not in logs
    assert "query_stage=session_list" in logs
    assert "wcdb_stage=open" in logs
    assert "returncode=17" in logs
    assert "stderr=" not in logs
    assert "helper_error=" not in logs
    assert "error_type=QueryFailed" in logs
    assert secret_key not in logs
    assert "WX_DB_KEY" not in logs


def test_query_runner_exception_logs_original_error_type_without_key(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def crashing(command, timeout, environment):
        sql = " ".join(command)
        if "PRAGMA table_info" in sql:
            return _FakeCompleted(
                stdout=_schema_result(["username", "summary", "last_timestamp"])
            )
        raise RuntimeError(FICTIONAL_KEY)

    with caplog.at_level(
        "INFO",
        logger="qq_chat_analyzer.providers.wechat_database_provider",
    ):
        with pytest.raises(QueryFailed):
            _provider(tmp_path, crashing).list_sessions()

    assert "original_error_type=RuntimeError" in caplog.text
    assert "query_stage=session_list" in caplog.text
    assert FICTIONAL_KEY not in caplog.text


# ----------------------------------------------------------- import service


def test_import_service_routes_db_export_to_the_db_adapter(tmp_path: Path) -> None:
    export = tmp_path / "session.json"
    _write_db_export(export, [_db_row(), _db_row(local_type=IMAGE_LOCAL_TYPE)])

    outcome = ImportService().execute(ImportRequest(input_path=export))

    assert outcome.result.platform == "wechat"
    assert outcome.result.format == WECHAT_DB_FORMAT
    assert outcome.result.message_count == 1
    assert outcome.result.valid_text_count == 1
    assert outcome.messages[0].platform == "wechat"
    assert outcome.messages[0].conversation_id == FICTIONAL_SESSION


def test_db_export_does_not_leak_into_qq_detection(tmp_path: Path) -> None:
    export = tmp_path / "session.json"
    _write_db_export(export, [_db_row()])

    outcome = ImportService().execute(
        ImportRequest(input_path=export, platform="qq")
    )

    assert outcome.result.message_count == 0


# ------------------------------------------------- schema / diagnostic contracts


def test_sanitize_wcdb_message_redacts_path_key_and_sql() -> None:
    db_path = Path("C:/Users/Fake/AppData/secret/session.db")
    key = "a" * 64
    sql = "SELECT secret FROM SessionTable"
    raw = (
        f"cannot open {db_path} with sql {sql} and key {key} "
        "and some user data here"
    )
    cleaned = _sanitize_wcdb_message(raw, db_path, key, sql)
    assert str(db_path) not in cleaned
    assert key not in cleaned
    assert sql not in cleaned
    assert "user data here" in cleaned


def test_query_failure_logs_wcdb_error_code_and_message(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_key = FICTIONAL_KEY
    db_path = _make_data_root(tmp_path) / "wxid_owner" / "db_storage" / "message" / "session.db"

    def failing(command, timeout, environment):
        assert environment["WX_DB_KEY"] == secret_key
        sql = " ".join(command)
        if "PRAGMA table_info" in sql:
            return _FakeCompleted(
                stdout=_schema_result(["username", "summary", "last_timestamp"])
            )
        return _FakeCompleted(
            stdout=json.dumps(
                {
                    "ok": False,
                    "stage": "prepare",
                    "error": "prepare failed",
                    "wcdb_error_code": 26,
                    "wcdb_error_ext_code": 1032,
                    "wcdb_error_message": (
                        f"file is not a database at {db_path} "
                        f"using key {secret_key}"
                    ),
                }
            ),
            returncode=1,
        )

    provider = _provider(tmp_path, failing)

    with caplog.at_level(
        "INFO",
        logger="qq_chat_analyzer.providers.wechat_database_provider",
    ):
        with pytest.raises(QueryFailed):
            provider.list_sessions()

    logs = caplog.text
    assert "wechat.wcdb.failed" in logs
    assert "database_type=session" in logs
    assert "query_stage=session_list" in logs
    assert "wcdb_stage=prepare" in logs
    assert "returncode=1" in logs
    assert "wcdb_error_code=26" in logs
    assert "wcdb_error_message=" in logs
    assert "file is not a database" in logs
    assert str(db_path) not in logs
    assert secret_key not in logs
    assert "error_type=QueryFailed" in logs


# ------------------------------------------------- key/database verification


def _verify_runner(
    captured: list[list[str]] | None = None,
    *,
    rows: list[object] | None = None,
):
    def runner(command, timeout, environment):
        if captured is not None:
            captured.append(list(command))
        return _FakeCompleted(
            stdout=_helper_result(
                rows if rows is not None else [{"count(*)": 1}]
            )
        )

    return runner


def _fictional_session_db(tmp_path: Path) -> Path:
    return (
        _make_data_root(tmp_path)
        / "wxid_owner"
        / "db_storage"
        / "message"
        / "session.db"
    )


def test_verify_readable_uses_a_minimal_read_only_query(tmp_path: Path) -> None:
    captured: list[list[str]] = []

    _provider(tmp_path, _verify_runner(captured)).verify_readable()

    assert captured, "verification must reuse the existing wcdb query path"
    command = captured[0]
    sql = command[command.index("--sql") + 1]
    assert "sqlite_master" in sql
    assert "SessionTable" not in sql
    assert "Msg_" not in sql
    assert "message" not in sql.lower()
    assert command[command.index("--db") + 1].endswith("session.db")


def test_verify_readable_keeps_the_key_off_the_command_line(
    tmp_path: Path,
) -> None:
    captured: list[list[str]] = []
    seen: list[dict[str, str]] = []

    def runner(command, timeout, environment):
        captured.append(list(command))
        seen.append(dict(environment))
        return _FakeCompleted(stdout=_helper_result([{"count(*)": 1}]))

    _provider(tmp_path, runner).verify_readable()

    assert seen[0]["WX_DB_KEY"] == FICTIONAL_KEY
    assert all(FICTIONAL_KEY not in part for part in captured[0])


def test_verify_readable_raises_unreadable_when_the_key_cannot_open_the_db(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_key = FICTIONAL_KEY
    session_db = _fictional_session_db(tmp_path)

    def failing(command, timeout, environment):
        assert environment["WX_DB_KEY"] == secret_key
        return _FakeCompleted(
            stdout=json.dumps(
                {
                    "ok": False,
                    "stage": "prepare",
                    "error": "prepare failed",
                    "wcdb_error_code": 26,
                    "wcdb_error_ext_code": 1032,
                    "wcdb_error_message": (
                        f"file is not a database at {session_db} "
                        f"using key {secret_key}"
                    ),
                }
            ),
            returncode=1,
        )

    with caplog.at_level(
        "INFO",
        logger="qq_chat_analyzer.providers.wechat_database_provider",
    ):
        with pytest.raises(DatabaseUnreadable) as failure:
            _provider(tmp_path, failing).verify_readable()

    assert failure.value.code == "wechat_database_unreadable"
    assert failure.value.code != QueryFailed.code

    logs = caplog.text
    assert "wechat.database.verify success=false" in logs
    assert "wcdb_error_code=26" in logs
    assert str(session_db) not in logs
    assert secret_key not in logs


def test_verify_readable_fails_closed_when_no_row_is_returned(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(
        "INFO",
        logger="qq_chat_analyzer.providers.wechat_database_provider",
    ):
        with pytest.raises(DatabaseUnreadable):
            _provider(tmp_path, _verify_runner(rows=[])).verify_readable()

    assert "wechat.database.verify success=false" in caplog.text
    assert "error_type=EmptyResult" in caplog.text


def test_verify_readable_logs_only_safe_status(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session_db = _fictional_session_db(tmp_path)

    with caplog.at_level(
        "INFO",
        logger="qq_chat_analyzer.providers.wechat_database_provider",
    ):
        _provider(tmp_path, _verify_runner()).verify_readable()

    logs = caplog.text
    assert "wechat.database.verify success=true" in logs
    assert session_db.name not in logs
    assert str(session_db) not in logs
    assert "wxid_owner" not in logs
    assert FICTIONAL_KEY not in logs
    assert "sqlite_master" not in logs
    assert "SELECT" not in logs


def test_verify_readable_reports_a_missing_database(tmp_path: Path) -> None:
    helper = tmp_path / "wcdb_cli.exe"
    helper.write_bytes(b"fake")
    library = tmp_path / "WCDB.dll"
    library.write_bytes(b"fake")
    provider = WeChatDatabaseProvider(
        data_root=tmp_path / "fictional_empty_root",
        db_key=FICTIONAL_KEY,
        wcdb_cli_path=helper,
        wcdb_dll_path=library,
        runner=_verify_runner(),
    )

    with pytest.raises(DatabaseNotFound):
        provider.verify_readable()


# ============================================================
# Multi-shard / rollover test helpers
# ============================================================

_ROLLOVER_TABLE = "Msg_0_fictional_rollover_session"
FICTIONAL_SESSION_FOR_ROLLOVER = "fictional_rollover_session"


def _multi_shard_data_root(tmp_path):
    root = tmp_path / "wechat_multi_shard"
    # _iter_db_directories uses rglob("db_storage") for exact match
    # Create multiple db_storage dirs at different depths
    db_dir_0 = root / "MicroMsg" / "db_storage"
    db_dir_0.mkdir(parents=True)
    (db_dir_0 / "message_0.db").write_bytes(b"fake db")
    # For a second shard, put db_storage in a sibling account dir
    db_dir_1 = root / "other_account" / "MicroMsg" / "db_storage"
    db_dir_1.mkdir(parents=True)
    (db_dir_1 / "message_0.db").write_bytes(b"fake db")
    return root

def _multi_shard_provider(tmp_path, runner):
    helper = tmp_path / "wcdb_cli.exe"
    helper.write_bytes(b"fake")
    library = tmp_path / "WCDB.dll"
    library.write_bytes(b"fake")
    return WeChatDatabaseProvider(
        data_root=_multi_shard_data_root(tmp_path),
        db_key=FICTIONAL_KEY,
        wcdb_cli_path=helper,
        wcdb_dll_path=library,
        runner=runner,
    )


def _make_runner_for_rollover(old_rows, new_rows):
    call_log = []

    def runner(command, timeout, environment):
        sql_index = command.index("--sql") if "--sql" in command else -1
        sql = command[sql_index + 1] if sql_index >= 0 else ""
        db_index = command.index("--db") if "--db" in command else -1
        db_path = command[db_index + 1] if db_index >= 0 else ""

        # Handle table existence checks from _table_exists (sqlite_master query)
        if "sqlite_master" in sql and "Msg_" in sql:
            call_log.append(("table_exists", db_path))
            # Return the rollover table so _find_all_message_dbs considers this shard valid
            return _FakeCompleted(stdout=_helper_result([{"name": _ROLLOVER_TABLE}]))

        # Handle message queries: the SQL contains "FROM Msg_" pattern
        if "FROM Msg_" in sql or "FROM " in sql and "create_time" in sql:
            call_log.append(("message_query", db_path))
            if "other_account" not in db_path:
                return _FakeCompleted(stdout=_helper_result(old_rows))
            else:
                return _FakeCompleted(stdout=_helper_result(new_rows))

        return _FakeCompleted(stdout=_helper_result([]))

    return runner, call_log

def test_read_session_rows_queries_all_shards_with_matching_table(tmp_path):
    old_rows = [
        _db_row(create_time=100, local_id=1),
        _db_row(create_time=101, local_id=2),
        _db_row(create_time=102, local_id=3),
    ]
    new_rows = [
        _db_row(create_time=200, local_id=4),
        _db_row(create_time=201, local_id=5),
        _db_row(create_time=202, local_id=6),
    ]

    runner, call_log = _make_runner_for_rollover(old_rows, new_rows)
    provider = _multi_shard_provider(tmp_path, runner)
    rows = provider.read_session_rows(FICTIONAL_SESSION_FOR_ROLLOVER)

    message_queries = [c for c in call_log if c[0] == "message_query"]
    assert len(message_queries) >= 2, (
        "Expected at least 2 message queries, got %d. Call log: %s" % (len(message_queries), call_log)
    )
    assert len(rows) == 6, "Expected 6 rows from both shards, got %d" % len(rows)
    times = [r["create_time"] for r in rows]
    assert times == sorted(times), "Rows should be globally sorted by create_time ASC, got %s" % times
    assert min(times) == 100
    assert max(times) == 202


def test_read_session_rows_respects_global_limit_across_shards(tmp_path):
    old_rows = [
        _db_row(create_time=100, local_id=1),
        _db_row(create_time=101, local_id=2),
        _db_row(create_time=102, local_id=3),
    ]
    new_rows = [
        _db_row(create_time=200, local_id=4),
        _db_row(create_time=201, local_id=5),
        _db_row(create_time=202, local_id=6),
    ]

    runner, _ = _make_runner_for_rollover(old_rows, new_rows)
    provider = _multi_shard_provider(tmp_path, runner)
    rows = provider.read_session_rows(FICTIONAL_SESSION_FOR_ROLLOVER, limit=4)

    assert len(rows) == 4, "Expected 4 rows with global limit=4, got %d" % len(rows)
    times = [r["create_time"] for r in rows]
    assert times == sorted(times)
    assert times == [100, 101, 102, 200]


def test_read_session_rows_respects_time_scope_across_shards(tmp_path):
    old_rows = [
        _db_row(create_time=50, local_id=1),
        _db_row(create_time=100, local_id=2),
    ]
    new_rows = [
        _db_row(create_time=200, local_id=3),
        _db_row(create_time=500, local_id=4),
    ]

    captured_sqls = []

    def runner(command, timeout, environment):
        sql_index = command.index("--sql") if "--sql" in command else -1
        sql = command[sql_index + 1] if sql_index >= 0 else ""
        db_index = command.index("--db") if "--db" in command else -1
        db_path = command[db_index + 1] if db_index >= 0 else ""

        if "sqlite_master" in sql and "Msg_" in sql:
            return _FakeCompleted(stdout=_helper_result([{"name": _ROLLOVER_TABLE}]))

        if "FROM Msg_" in sql:
            captured_sqls.append(sql)
            shard_rows = old_rows if "other_account" not in db_path else new_rows
            return _FakeCompleted(stdout=_helper_result(shard_rows))

        return _FakeCompleted(stdout=_helper_result([]))

    provider = _multi_shard_provider(tmp_path, runner)
    rows = provider.read_session_rows(
        FICTIONAL_SESSION_FOR_ROLLOVER,
        start_time=90,
        end_time=210,
    )

    assert len(rows) == 4, "Mock returns all rows, got %d" % len(rows)
    assert len(captured_sqls) == 2, "Expected 2 SQL queries, got %d" % len(captured_sqls)
    for sql in captured_sqls:
        assert "create_time >= 90" in sql, "SQL missing start_time: %s" % sql
        assert "create_time <= 210" in sql, "SQL missing end_time: %s" % sql


def test_read_session_rows_default_limit_is_unlimited(tmp_path):
    all_rows = [
        _db_row(create_time=100 + index, local_id=index + 1)
        for index in range(100_001)
    ]
    runner, _ = _make_runner_for_rollover(all_rows, [])
    provider = _multi_shard_provider(tmp_path, runner)

    rows = provider.read_session_rows(FICTIONAL_SESSION_FOR_ROLLOVER)

    assert len(rows) == 100_001


def test_export_session_json_default_limit_is_unlimited(tmp_path):
    all_rows = [
        _db_row(create_time=100 + index, local_id=index + 1)
        for index in range(100_001)
    ]
    runner, _ = _make_runner_for_rollover(all_rows, [])
    provider = _multi_shard_provider(tmp_path, runner)
    output_path = tmp_path / "export.json"

    provider.export_session_json(FICTIONAL_SESSION_FOR_ROLLOVER, output_path)

    exported = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(exported["messages"]) == 100_001
