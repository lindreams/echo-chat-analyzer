"""Binding and lifecycle coverage for Direct DB self identity.

Every database, identity and message here is fictional.  The self identity is
carried by the generation ``manifest.json`` (``identity.value``) and validated
by the acquisition; the legacy ``self_identity.json`` sidecar is gone.
"""

from __future__ import annotations

import sqlite3
import json
from pathlib import Path

import pytest

from qq_chat_analyzer.application.import_request import ImportRequest
from qq_chat_analyzer.application.import_service import ImportService
from qq_chat_analyzer.application.qq.qq_direct_database_import_service import (
    QQDirectDatabaseImportService,
    QQDirectSnapshotInvalid,
    _validated_generation,
)

from qq_direct_db_testing import FakeSnapshotRuntime


from qq_db_test_data import (
    encode_varint as _varint,
    length_delimited_field as _field,
)


def _text_blob(text: str) -> bytes:
    segment = _varint((45002 << 3) | 0) + _varint(1) + _field(45101, text.encode("utf-8"))
    return _field(40800, segment)


@pytest.mark.parametrize('fault,guard', [
    ('unreadable', 'manifest_unreadable'), ('encoding', 'manifest_encoding_invalid'),
    ('generation', 'generation_mismatch'), ('identity', 'identity_value_invalid'),
    ('database', 'database_missing'), ('integrity', 'sqlite_integrity_failed'),
])
def test_generation_rejection_logs_a_fixed_reason_only(tmp_path, caplog, fault, guard):
    caplog.set_level('INFO', logger='qq_chat_analyzer.desktop.qq_direct_database')
    payload = {'schema_version': 1, 'generation_id': 'fictional-generation', 'state': 'ready',
               'database': 'snapshot.db', 'identity': {'namespace': 'qq_uin', 'value': '100000001'}}
    if fault == 'generation':
        payload['generation_id'] = 'PRIVATE_GENERATION'
    if fault == 'identity':
        payload['identity']['value'] = ''
    manifest = tmp_path / 'manifest.json'
    if fault != 'unreadable':
        manifest.write_text('PRIVATE_INVALID_JSON' if fault == 'encoding' else json.dumps(payload), encoding='utf-8')
    if fault != 'database':
        (tmp_path / 'snapshot.db').write_bytes(b'PRIVATE_NOT_SQLITE')
    with pytest.raises(QQDirectSnapshotInvalid):
        _validated_generation(tmp_path, 'fictional-generation')
    assert f'guard_code={guard}' in caplog.text
    assert 'PRIVATE_' not in caplog.text and str(tmp_path) not in caplog.text


def _create_snapshot(path: Path, self_uin: str, peer_uin: str) -> None:
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
        connection.executemany(
            '''INSERT INTO group_msg_table
                ("40001", "40027", "40030", "40033", "40050", "40800")
                VALUES (?, ?, ?, ?, ?, ?)''',
            [
                (101, "17", "fictional-group", self_uin, 1760000001, _text_blob("self group")),
                (102, "17", "fictional-group", peer_uin, 1760000002, _text_blob("peer group")),
            ],
        )
        connection.executemany(
            '''INSERT INTO c2c_msg_table
                ("40001", "40027", "40030", "40033", "40050", "40800")
                VALUES (?, ?, ?, ?, ?, ?)''',
            [
                (201, "17", "fictional-peer", self_uin, 1760000011, _text_blob("self private")),
                (202, "17", "fictional-peer", peer_uin, 1760000012, _text_blob("peer private")),
            ],
        )


def _import_self_flags(payload_path: Path) -> list[bool | None]:
    outcome = ImportService().execute(ImportRequest(input_path=payload_path))
    return [message.is_self for message in outcome.messages]


def _service(
    tmp_path: Path,
    snapshot_path: Path,
    identity_value: str | int,
) -> QQDirectDatabaseImportService:
    runtime = FakeSnapshotRuntime(
        tmp_path,
        snapshot_path=snapshot_path,
        identity_value=identity_value,
    )
    return QQDirectDatabaseImportService(runtime_client=runtime), runtime


def test_generation_manifest_binds_self_identity_to_snapshot(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "plaintext-qq.db"
    _create_snapshot(snapshot_path, "100000001", "100000002")
    service, _runtime = _service(tmp_path, snapshot_path, "100000001")

    with service.acquired_session("group:17") as acquisition:
        assert acquisition.self_uin == "100000001"
        assert _import_self_flags(acquisition.payload_path) == [True, False]


def test_private_self_and_peer_from_generation_manifest(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "plaintext-qq.db"
    _create_snapshot(snapshot_path, "100000001", "100000002")
    service, _runtime = _service(tmp_path, snapshot_path, "100000001")

    with service.acquired_session("private:17") as acquisition:
        assert _import_self_flags(acquisition.payload_path) == [True, False]


def test_stale_account_identity_is_not_paired(tmp_path: Path) -> None:
    snapshot_a = tmp_path / "plaintext-a.db"
    snapshot_b = tmp_path / "plaintext-b.db"

    # First acquisition: account A.
    _create_snapshot(snapshot_a, "100000001", "100000002")
    runtime = FakeSnapshotRuntime(
        tmp_path,
        snapshot_path=snapshot_a,
        identity_value="100000001",
    )
    service = QQDirectDatabaseImportService(runtime_client=runtime)

    with service.acquired_session("group:17") as acquisition:
        assert acquisition.self_uin == "100000001"

    # Second generation: account B replaces the snapshot and identity.
    # The previous identity must not linger.
    _create_snapshot(snapshot_b, "200000001", "200000002")
    runtime.snapshot_path = snapshot_b
    runtime.identity_value = "200000001"

    with service.acquired_session("group:17") as acquisition:
        assert acquisition.self_uin == "200000001"
        assert _import_self_flags(acquisition.payload_path) == [True, False]
