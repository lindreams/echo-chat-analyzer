"""RED-GREEN coverage for the Direct DB snapshot lease (Phase 2A).

``QQDirectDatabaseImportService.list_sessions`` must acquire a fresh runtime
generation, validate its manifest and database, materialize session
descriptors into memory, and remove the generation before returning.  These
tests drive that lifecycle through a fake runtime client, so no real NapCat
bridge, passphrase or QQ data is involved.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from qq_chat_analyzer.application.qq.qq_direct_database_import_service import (
    QQDirectDatabaseImportService,
    QQDirectSnapshotAcquireFailed,
    QQDirectSnapshotCleanupFailed,
    QQDirectSnapshotInvalid,
)
from qq_chat_analyzer.providers.qq_database_provider import QQDatabaseProvider
from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import (
    QQSnapshotCleanupFailed,
    QQSnapshotRuntimeUnavailable,
)

from qq_direct_db_testing import FICTIONAL_UIN, FakeSnapshotRuntime


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _field(field_number: int, value: bytes) -> bytes:
    return _varint((field_number << 3) | 2) + _varint(len(value)) + value


def _text_blob(text: str) -> bytes:
    segment = _varint((45002 << 3) | 0) + _varint(1) + _field(45101, text.encode("utf-8"))
    return _field(40800, segment)


def _create_snapshot(path: Path) -> None:
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
            (101, "group-partition", "fictional-group", "fictional-sender", 1760000001, _text_blob("fictional group message")),
        )
        connection.execute(
            '''INSERT INTO c2c_msg_table
                ("40001", "40027", "40030", "40033", "40050", "40800")
                VALUES (?, ?, ?, ?, ?, ?)''',
            (201, "private-partition", "fictional-peer", "fictional-sender", 1760000002, _text_blob("fictional private message")),
        )


def _service(root: Path, runtime: FakeSnapshotRuntime) -> QQDirectDatabaseImportService:
    return QQDirectDatabaseImportService(runtime_client=runtime)


def _snapshot(root: Path) -> Path:
    return root / "source.db"


# ------------------------------------------------------------------ success


def test_acquire_success_and_valid_manifest_returns_sessions(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    _create_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot)
    service = _service(tmp_path, runtime)

    sessions = {session.session_type: session for session in service.list_sessions()}

    assert set(sessions) == {"group", "private"}
    assert sessions["group"].internal_key == "group-partition"
    assert sessions["private"].internal_key == "private-partition"


def test_list_sessions_cleans_up_generation_before_return(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    _create_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot)
    service = _service(tmp_path, runtime)

    service.list_sessions()

    assert runtime.acquired == ["gen-0001"]
    assert runtime.cleaned == ["gen-0001"]
    assert not runtime.generation_directory("gen-0001").exists()


# ------------------------------------------------------------------ acquire


def test_acquire_failure_never_reads_a_previous_generation(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    _create_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot, auto_write=False)
    runtime.write_generation("stale-gen")
    runtime.acquire_error = QQSnapshotRuntimeUnavailable()
    service = _service(tmp_path, runtime)

    with pytest.raises(QQDirectSnapshotAcquireFailed):
        service.list_sessions()

    # The stale generation was never read and never cleaned up.
    assert runtime.cleaned == []
    assert runtime.generation_directory("stale-gen").exists()


# ------------------------------------------------------------------ manifest


def test_generation_mismatch_fails_closed(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    _create_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot)
    runtime.manifest_overrides = {"generation_id": "someone-else"}
    service = _service(tmp_path, runtime)

    with pytest.raises(QQDirectSnapshotInvalid):
        service.list_sessions()

    assert runtime.cleaned == ["gen-0001"]


@pytest.mark.parametrize("schema_version", [0, 2, "1", None])
def test_wrong_schema_version_rejects(tmp_path: Path, schema_version) -> None:
    snapshot = _snapshot(tmp_path)
    _create_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot)
    runtime.manifest_overrides = {"schema_version": schema_version}
    service = _service(tmp_path, runtime)

    with pytest.raises(QQDirectSnapshotInvalid):
        service.list_sessions()


def test_manifest_non_ready_state_rejects(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    _create_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot)
    runtime.manifest_overrides = {"state": "building"}
    service = _service(tmp_path, runtime)

    with pytest.raises(QQDirectSnapshotInvalid):
        service.list_sessions()


@pytest.mark.parametrize(
    "identity",
    [
        None,
        {"namespace": "qq_uid", "value": FICTIONAL_UIN},
        {"namespace": "qq_uin", "value": "0"},
        {"namespace": "qq_uin", "value": ""},
        {"namespace": "qq_uin"},
        "not-a-dict",
    ],
)
def test_missing_or_invalid_identity_rejects(tmp_path: Path, identity) -> None:
    snapshot = _snapshot(tmp_path)
    _create_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot)
    runtime.manifest_overrides = {"identity": identity}
    service = _service(tmp_path, runtime)

    with pytest.raises(QQDirectSnapshotInvalid):
        service.list_sessions()


def test_missing_database_rejects(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    _create_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot)
    runtime.manifest_overrides = {"database": "missing.db"}
    service = _service(tmp_path, runtime)

    with pytest.raises(QQDirectSnapshotInvalid):
        service.list_sessions()


def test_traversal_database_name_rejects(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    _create_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot)
    runtime.manifest_overrides = {"database": "../outside.db"}
    service = _service(tmp_path, runtime)

    with pytest.raises(QQDirectSnapshotInvalid):
        service.list_sessions()


def test_unreadable_manifest_rejects(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    _create_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot)
    service = _service(tmp_path, runtime)
    runtime.acquire()
    (runtime.generation_directory("gen-0001") / "manifest.json").write_text(
        "not json",
        encoding="utf-8",
    )
    runtime.acquired.clear()
    runtime.cleaned.clear()
    runtime.acquire_result = "gen-0001"
    runtime.auto_write = False

    with pytest.raises(QQDirectSnapshotInvalid):
        service.list_sessions()


# ------------------------------------------------------------------ cleanup


def test_provider_exception_still_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    _create_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot)
    service = _service(tmp_path, runtime)

    def _raise(self, *args, **kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(QQDatabaseProvider, "list_sessions", _raise)

    with pytest.raises(RuntimeError, match="provider exploded"):
        service.list_sessions()

    assert runtime.cleaned == ["gen-0001"]
    assert not runtime.generation_directory("gen-0001").exists()


def test_cleanup_failure_raises_stable_privacy_safe_diagnostic(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    _create_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot)
    runtime.cleanup_error = QQSnapshotCleanupFailed()
    service = _service(tmp_path, runtime)

    with pytest.raises(QQDirectSnapshotCleanupFailed):
        service.list_sessions()

    assert runtime.cleaned == ["gen-0001"]


def test_error_does_not_leak_identity_value(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    _create_snapshot(snapshot)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=snapshot)
    runtime.identity_value = FICTIONAL_UIN
    runtime.manifest_overrides = {"state": "building"}
    service = _service(tmp_path, runtime)

    with pytest.raises(QQDirectSnapshotInvalid) as captured:
        service.list_sessions()

    assert FICTIONAL_UIN not in str(captured.value)
    assert FICTIONAL_UIN not in captured.value.public_message
