"""Fictional regression cases for Direct DB identity display semantics."""

from __future__ import annotations

import base64
import json
import sqlite3
from types import SimpleNamespace

import pytest

from qq_chat_analyzer.providers.qq_database_provider import QQDatabaseProvider
from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages
from qq_chat_analyzer.application.qq.qq_direct_database_import_service import (
    QQDirectDatabaseImportService,
    _group_member_data,
    _identity_coverage_counts,
    _attach_sender_names,
    _log_group_member_shape,
)
from qq_chat_analyzer.providers.qq_database_provider import QQSession
from test_qq_db_import_integration import _synthetic_text_message_blob


def test_zero_partition_is_not_a_user_session(tmp_path) -> None:
    database = tmp_path / "fictional.db"
    with sqlite3.connect(database) as connection:
        for table in ("group_msg_table", "c2c_msg_table"):
            connection.execute(
                f'CREATE TABLE {table} ("40027" TEXT, "40030" TEXT, '
                '"40050" INTEGER)'
            )
        connection.executemany(
            'INSERT INTO c2c_msg_table VALUES (?, ?, ?)',
            [("0", "0", 1)] * 82 + [("valid-key", "valid-peer", 2)],
        )
    sessions = QQDatabaseProvider(database).list_sessions()
    assert [(session.internal_key, session.message_count) for session in sessions] == [
        ("valid-key", 1)
    ]


def test_group_member_names_use_info_uin_not_serialized_map_key(tmp_path) -> None:
    response = json.loads(json.dumps({
        "result": {"infos": {
            9001: {"uin": 123456789, "cardName": "Fictional Card", "nick": "Fictional Nick"},
            "opaque-member-key": {"uin": "234567890", "cardName": "", "nick": "Fictional Nick Only"},
            "no-name-key": {"uin": "345678901", "cardName": "", "nick": ""},
        }}
    }))

    result = _group_member_data(response)

    assert result["names"] == {
        "123456789": "Fictional Card",
        "234567890": "Fictional Nick Only",
    }
    assert result["uins"] == {"123456789", "234567890", "345678901"}
    assert _identity_coverage_counts(
        {"123456789", "234567890", "345678901", "456789012"}, result
    ) == {
        "distinct_sender_count": 4,
        "rpc_member_count": 3,
        "matched_sender_count": 3,
        "unmatched_sender_count": 1,
        "matched_with_card_count": 1,
        "matched_without_card_with_nick_count": 1,
        "matched_without_card_or_nick_count": 1,
        "rpc_member_with_card_count": 1,
        "rpc_member_with_nick_count": 2,
    }

    payload_path = tmp_path / "fictional-group-payload.json"
    payload_path.write_text(json.dumps({
        "records": [{"fields": {"40033": "123456789"}}]
    }), encoding="utf-8")
    _attach_sender_names(payload_path, json.loads(payload_path.read_text(encoding="utf-8")), result["names"], "fictional-self")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["records"][0]["sender"] == {"displayName": "Fictional Card"}


def test_private_peer_is_the_only_non_self_sender(tmp_path) -> None:
    database = tmp_path / "fictional.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            'CREATE TABLE group_msg_table ("40027" TEXT, "40030" TEXT, '
            '"40033" TEXT, "40050" INTEGER)'
        )
        connection.execute(
            'CREATE TABLE c2c_msg_table ("40027" TEXT, "40030" TEXT, '
            '"40033" TEXT, "40050" INTEGER)'
        )
        connection.executemany(
            'INSERT INTO c2c_msg_table VALUES (?, ?, ?, ?)',
            [
                ("partition", "self", "self", 1),
                ("partition", "peer", "peer", 2),
            ],
        )
    session = QQDatabaseProvider(database).list_sessions(self_uin="self")[0]
    assert session.peer_uin == "peer"
