from __future__ import annotations

import json
from qq_db_test_data import qq_db_payload, qq_db_record
from pathlib import Path

import pytest

from qq_chat_analyzer.application import ImportRequest, ImportService


NO_MESSAGES_LOADED = "no_messages_loaded"
UNSUPPORTED_FORMAT = "unsupported_format"
PLATFORM_HINT_FORMAT_MISMATCH = "platform_hint_format_mismatch"


def write_empty_qq_json(path: Path):
    write_qq_json(path, [])


def write_wechat_json(path: Path):
    payload = {
        "exportInfo": {
            "version": "0.0.2",
            "generator": "CipherTalk",
            "format": "detailed-json",
        },
        "session": {
            "platform": "wechat",
            "isGroup": True,
        },
        "messages": [
            {
                "type": "文本消息",
                "content": "hello",
                "senderUsername": "wxid_test",
                "senderDisplayName": "Alice",
            }
        ],
    }

    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def write_unknown_json(path: Path):
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "records": [],
            }
        ),
        encoding="utf-8",
    )


def write_manifest(path: Path):
    path.write_text(
        json.dumps(
            {
                "metadata": {},
                "chatInfo": {},
                "statistics": {},
                "chunked": {},
            }
        ),
        encoding="utf-8",
    )


def write_avatars(path: Path):
    path.write_text(
        json.dumps(
            {
                "uid": "avatar"
            }
        ),
        encoding="utf-8",
    )


# ----------------------------
# warning privacy
# ----------------------------


def test_warning_does_not_contain_filename(tmp_path):
    path = tmp_path / "群聊_测试群_123456.json"
    write_empty_qq_json(path)

    result = ImportService().execute(
        ImportRequest(path, platform="qq")
    )

    for warning in result.result.warnings:
        assert "群聊" not in warning
        assert "测试群" not in warning
        assert "123456" not in warning
        assert path.name not in warning


# ----------------------------
# sidecar
# ----------------------------


def test_manifest_and_avatar_are_ignored(tmp_path):
    directory = tmp_path / "export"
    directory.mkdir()

    write_qq_json(directory / "chat.json")
    write_manifest(directory / "manifest.json")
    write_avatars(directory / "avatars.json")

    result = ImportService().execute(
        ImportRequest(directory)
    )

    assert result.result.message_count == 1
    assert result.result.warnings == ()


# ----------------------------
# unknown
# ----------------------------


def test_unknown_warning_hides_filename(tmp_path):
    path = tmp_path / "群聊_秘密群_123456.json"
    write_unknown_json(path)

    result = ImportService().execute(
        ImportRequest(path)
    )

    for warning in result.result.warnings:
        assert "秘密群" not in warning
        assert "123456" not in warning


# ----------------------------
# platform hint
# ----------------------------


# ----------------------------
# regression
# ----------------------------


# ----------------------------
# platform hint mismatch with parsable payload
# ----------------------------


def test_wechat_file_with_qq_hint_warns_mismatch(tmp_path):
    path = tmp_path / "wechat.json"
    write_wechat_json(path)

    result = ImportService().execute(
        ImportRequest(path, platform="qq")
    )

    assert result.result.platform == "qq"
    assert result.result.message_count == 0
    assert PLATFORM_HINT_FORMAT_MISMATCH in result.result.warnings


def test_qq_file_with_wechat_hint_warns_mismatch(tmp_path):
    path = tmp_path / "qq.json"
    write_qq_json(path)

    result = ImportService().execute(
        ImportRequest(path, platform="wechat")
    )

    assert result.result.platform == "wechat"
    assert result.result.message_count == 0
    assert PLATFORM_HINT_FORMAT_MISMATCH in result.result.warnings


def test_mismatch_warning_hides_filename(tmp_path):
    path = tmp_path / "\u7fa4\u804a_\u79d8\u5bc6\u7fa4123456.json"
    write_wechat_json(path)

    result = ImportService().execute(
        ImportRequest(path, platform="qq")
    )

    for warning in result.result.warnings:
        assert "\u79d8\u5bc6\u7fa4" not in warning
        assert "123456" not in warning
        assert path.name not in warning


def write_qq_json(path: Path, messages=None):
    records = [qq_db_record("hello", nickname="Alice")] if messages is None else messages
    path.write_text(json.dumps(qq_db_payload(records)), encoding="utf-8")
