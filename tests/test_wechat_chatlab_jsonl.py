"""Behavioral tests for the CipherTalk chatlab JSONL WeChat export."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.application import ImportRequest, ImportService


CHATLAB_TEXT_TYPE = 0
CHATLAB_REPLY_TYPE = 25
CHATLAB_IMAGE_TYPE = 1
CHATLAB_PAT_TYPE = 7


def _header_line() -> dict[str, object]:
    return {
        "_type": "header",
        "chatlab": {
            "version": "0.0.2",
            "exportedAt": 1785905292,
            "generator": "CipherTalk",
        },
        "meta": {
            "name": "Fictional Group",
            "platform": "wechat",
            "type": "group",
            "ownerId": "wxid_fictional_owner",
            "groupId": "fictional-chatroom",
        },
    }


def _member_line() -> dict[str, object]:
    return {
        "_type": "member",
        "platformId": "wxid_fictional_sender",
        "accountName": "Fictional Alice",
        "avatar": "",
    }


def _message_line(
    message_type: int = CHATLAB_TEXT_TYPE,
    content: str = "Hello from chatlab",
    sender: str = "wxid_fictional_sender",
    account_name: str = "Fictional Alice",
    timestamp: int = 1753412807,
    message_id: str = "fictional-chatlab-message-001",
) -> dict[str, object]:
    return {
        "_type": "message",
        "sender": sender,
        "accountName": account_name,
        "timestamp": timestamp,
        "type": message_type,
        "content": content,
        "platformMessageId": message_id,
    }


def _write_chatlab_jsonl(path: Path, lines: list[object]) -> None:
    rendered = []
    for line in lines:
        if isinstance(line, str):
            rendered.append(line)
        else:
            rendered.append(json.dumps(line, ensure_ascii=False))
    path.write_text("\n".join(rendered) + "\n", encoding="utf-8")


def _default_export(path: Path) -> None:
    _write_chatlab_jsonl(
        path,
        [_header_line(), _member_line(), _message_line()],
    )


def test_chatlab_type_twenty_five_is_parsed_as_reply(tmp_path: Path) -> None:
    export_path = tmp_path / "chatlab.jsonl"
    _write_chatlab_jsonl(
        export_path,
        [
            _header_line(),
            _message_line(
                message_type=CHATLAB_REPLY_TYPE,
                content="Quoted answer",
            ),
        ],
    )

    parsed = ImportService().execute(ImportRequest(input_path=export_path)).messages

    assert len(parsed) == 1
    assert parsed[0].message_type == "reply"
    assert parsed[0].text == "Quoted answer"


def test_chatlab_malformed_line_does_not_drop_other_messages(
    tmp_path: Path,
) -> None:
    export_path = tmp_path / "chatlab.jsonl"
    _write_chatlab_jsonl(
        export_path,
        [
            _header_line(),
            _message_line(content="Before broken line"),
            "{not valid json",
            _message_line(content="After broken line"),
        ],
    )

    parsed = ImportService().execute(ImportRequest(input_path=export_path)).messages

    assert [message.text for message in parsed] == [
        "Before broken line",
        "After broken line",
    ]


def test_import_service_routes_chatlab_jsonl_to_wechat(tmp_path: Path) -> None:
    export_path = tmp_path / "chatlab.jsonl"
    _default_export(export_path)

    outcome = ImportService().execute(ImportRequest(input_path=export_path))

    assert outcome.result.platform == "wechat"
    assert outcome.result.message_count == 1
