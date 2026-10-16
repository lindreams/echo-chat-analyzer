"""Direct DB QQ facade regression coverage using only fictional data."""

from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
from qq_chat_analyzer.application.facade import (
    AnalysisConfig,
    ChatAnalyzerFacade,
    ChatSource,
)
from qq_chat_analyzer.application.qq.qq_direct_database_import_service import (
    QQDirectDatabaseImportService,
)

from qq_direct_db_testing import FakeSnapshotRuntime


@pytest.mark.parametrize("fails", [False, True])
def test_qq_facade_conversion_diagnostics_preserve_results_and_errors(tmp_path, monkeypatch, caplog, fails):
    from qq_chat_analyzer.application import facade as module
    snapshot = tmp_path / "fictional.db"
    _create_plaintext_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot)
    facade = ChatAnalyzerFacade(qq_service=QQDirectDatabaseImportService(runtime_client=runtime))
    error = ValueError("PRIVATE_CONVERSION path account token")
    if fails:
        def convert(*args):
            raise error
        monkeypatch.setattr(module, "_to_session_info", convert)
    with caplog.at_level("INFO"):
        if fails:
            with pytest.raises(ValueError) as caught:
                facade.list_sessions(ChatSource.QQ)
            assert caught.value is error
        else:
            assert len(facade.list_sessions(ChatSource.QQ)) == 2
    log = "\n".join(r.getMessage() for r in caplog.records if "[qq sessions]" in r.getMessage())
    assert "stage=facade_convert outcome=started" in log
    assert f"stage=facade_convert outcome={'failed' if fails else 'success'}" in log
    assert "PRIVATE" not in log and str(tmp_path) not in log
    assert runtime.cleaned == ["gen-0001"]


def _varint(value: int) -> bytes:
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _field(field_number: int, value: bytes) -> bytes:
    return _varint((field_number << 3) | 2) + _varint(len(value)) + value


def _message_blob(text: str) -> bytes:
    segment = (
        _varint((45002 << 3) | 0)
        + _varint(1)
        + _field(45101, text.encode("utf-8"))
    )
    return _field(40800, segment)


def _create_plaintext_snapshot(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        for table_name in ("group_msg_table", "c2c_msg_table"):
            connection.execute(
                f'''CREATE TABLE {table_name} (
                    "40001" INTEGER PRIMARY KEY,
                    "40027" TEXT NOT NULL,
                    "40030" TEXT NOT NULL,
                    "40033" TEXT NOT NULL,
                    "40050" INTEGER NOT NULL,
                    "40800" BLOB NOT NULL
                )'''
            )
        connection.execute(
            '''INSERT INTO group_msg_table
                ("40001", "40027", "40030", "40033", "40050", "40800")
                VALUES (?, ?, ?, ?, ?, ?)''',
            (101, "group-partition", "fictional-group", "fictional-group-sender", 1760000001, _message_blob("fictional group message")),
        )
        connection.execute(
            '''INSERT INTO c2c_msg_table
                ("40001", "40027", "40030", "40033", "40050", "40800")
                VALUES (?, ?, ?, ?, ?, ?)''',
            (201, "private-partition", "fictional-peer", "fictional-private-sender", 1760000002, _message_blob("fictional private message")),
        )


def test_direct_db_group_and_private_sessions_reach_existing_echo_pipeline(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "plaintext-qq.db"
    _create_plaintext_snapshot(snapshot_path)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot_path)
    direct_service = QQDirectDatabaseImportService(runtime_client=runtime)
    facade = ChatAnalyzerFacade(
        qq_service=direct_service,
        analysis_service=AnalysisApplicationService(),
        stopwords_directory=Path(__file__).resolve().parents[1],
    )

    sessions = {item.session_type: item for item in facade.list_sessions(ChatSource.QQ)}
    assert set(sessions) == {"group", "private"}

    for session_type in ("group", "private"):
        outcome = facade.analyze_session(
            ChatSource.QQ,
            sessions[session_type].session_id,
            AnalysisConfig(output_directory=tmp_path / f"{session_type}-report"),
        )

        assert outcome.session is not None
        assert outcome.session.session_type == session_type
        assert outcome.result.processed_message_count > 0
        assert outcome.report_path is not None and outcome.report_path.is_file()
