"""Behavior tests for the ImportService foundation."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.application import (
    ImportOutcome,
    ImportRequest,
    ImportResult,
    ImportService,
)
from qq_chat_analyzer.application.errors import InputPathNotFound, NoSupportedInput
from qq_chat_analyzer.message import ChatMessage
from qq_db_test_data import qq_db_payload, qq_db_record


WECHAT_TEXT_TYPE = "\u6587\u672c\u6d88\u606f"


def _write_wechat_json(path: Path) -> None:
    payload = {
        "exportInfo": {
            "version": "0.0.2",
            "exportedAt": 1785895813,
            "generator": "CipherTalk",
            "format": "detailed-json",
        },
        "session": {
            "wxid": "fictional-chatroom",
            "nickname": "Fictional Group",
            "platform": "wechat",
            "isGroup": True,
        },
        "messages": [
            {
                "localId": 1,
                "platformMessageId": "fictional-wechat-message-001",
                "createTime": 1783223281,
                "type": WECHAT_TEXT_TYPE,
                "content": "Hello from WeChat",
                "senderUsername": "wxid_fictional_sender",
                "senderDisplayName": "Fictional Alice",
            },
            {
                "localId": 2,
                "platformMessageId": "fictional-wechat-message-002",
                "createTime": 1783223285,
                "type": WECHAT_TEXT_TYPE,
                "content": "Hello again from WeChat",
                "senderUsername": "wxid_fictional_sender",
                "senderDisplayName": "Fictional Alice",
            },
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_wechat_detailed_json_import_returns_result_and_messages(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "wechat.json"
    _write_wechat_json(input_path)

    outcome = ImportService().execute(
        ImportRequest(input_path=input_path, platform="wechat")
    )

    assert outcome.result == ImportResult(
        platform="wechat",
        message_count=2,
        valid_text_count=2,
        format="detailed-json",
    )
    assert [message.text for message in outcome.messages] == [
        "Hello from WeChat",
        "Hello again from WeChat",
    ]


def test_corrupt_json_returns_warning_and_empty_result(tmp_path: Path) -> None:
    input_path = tmp_path / "broken.json"
    input_path.write_text("{not valid json", encoding="utf-8")

    outcome = ImportService().execute(
        ImportRequest(input_path=input_path, platform="qq")
    )

    assert outcome.result.message_count == 0
    assert outcome.processed_message_count == 0
    assert outcome.result.valid_text_count == 0
    assert outcome.result.warnings
    assert outcome.messages == ()


def _write_qq_json(path: Path) -> None:
    text = qq_db_record("Hello from QQ DB")
    nontext = qq_db_record(message_id="fictional-nontext")
    # An uninterpretable record is counted as raw input, but never as text.
    path.write_text(json.dumps(qq_db_payload([text, nontext])), encoding="utf-8")


def test_qq_db_auto_detection_carries_rich_messages(tmp_path):
    path = tmp_path / "qq-db.json"
    _write_qq_json(path)
    outcome = ImportService().execute(ImportRequest(path))
    assert outcome.result.platform == "qq"
    assert outcome.result.format == "qq-db-json"
    assert len(outcome.rich_messages) == len(outcome.messages) == 1


@pytest.mark.parametrize("kind", ["qq", "detailed", "db", "cli", "jsonl"])
@pytest.mark.parametrize("hinted", [False, True])
def test_import_reads_a_valid_file_once_without_caching_stale_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, hinted: bool,
) -> None:
    path = tmp_path / ("chat.jsonl" if kind == "jsonl" else "chat.json")
    if kind == "qq":
        _write_qq_json(path)
    elif kind == "detailed":
        _write_wechat_json(path)
    elif kind == "db":
        path.write_text(json.dumps({
            "source": "wechat-db", "conversation": {"username": "fictional-room@chatroom"},
            "messages": [{"local_id": 1, "create_time": 1704099600, "local_type": 1,
                          "message_content": "fictional text", "user_name": "fictional-user"}],
        }), encoding="utf-8")
    elif kind == "cli":
        path.write_text(json.dumps([{"createTime": 1704099600, "type": 1,
                                    "content": "fictional text", "senderUsername": "fictional-user"}]), encoding="utf-8")
    else:
        path.write_text(json.dumps({"_type": "message", "timestamp": 1704099600,
                                    "sender": "fictional-user", "type": 0, "content": "fictional text"}) + "\n", encoding="utf-8")
    original_open = Path.open
    reads = []

    def record_open(candidate, mode="r", *args, **kwargs):
        if candidate == path and "r" in mode:
            reads.append(candidate)
        return original_open(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", record_open)
    platform = "qq" if kind == "qq" else "wechat"
    request = ImportRequest(path, platform=platform if hinted else None)
    service = ImportService()
    outcome = service.execute(request)
    assert outcome.result.platform == platform
    assert outcome.result.message_count > 0
    assert len(reads) == 1

    path.write_text("corrupted input", encoding="utf-8")
    assert service.execute(request).result.message_count == 0


@pytest.mark.parametrize("indent", [None, 2])
def test_qq_db_jsonl_suffix_keeps_json_document_validation(tmp_path: Path, indent: int | None) -> None:
    path = tmp_path / "fictional-qq.jsonl"
    document = json.dumps(qq_db_payload([qq_db_record("fictional text")]), indent=indent)
    path.write_text(document, encoding="utf-8")
    request = ImportRequest(path)
    assert ImportService().execute(request).result.message_count == 1
    path.write_text(document + "\ncorrupted trailing input", encoding="utf-8")
    outcome = ImportService().execute(request)
    assert outcome.result.message_count == 0
    assert outcome.result.warnings == ("unsupported_format",)


def test_qq_detection_does_not_inspect_unrelated_wechat_shaped_fields(tmp_path: Path) -> None:
    path = tmp_path / "fictional-qq.json"
    payload = qq_db_payload([qq_db_record("fictional text")])
    payload["messages"] = [{"type": []}]
    path.write_text(json.dumps(payload), encoding="utf-8")
    outcome = ImportService().execute(ImportRequest(path))
    assert outcome.result.platform == "qq"
    assert outcome.result.message_count == 1
