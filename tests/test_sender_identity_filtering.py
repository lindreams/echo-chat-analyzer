"""RED/GREEN suite for sender identity isolation in Smart Profile filtering.

Every fixture below is fictional and constructed by hand. No real QQ/WeChat
account data, nickname, group id or message body appears in this file.

Regression target (P1): the automatic sender filter used to aggregate and match
by display name only, so a member whose nickname happens to be shared with an
automated sender was deleted together with it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.detectors.interactive_bot_detector import (
    detect_interactive_bot_candidates,
)
from qq_chat_analyzer.detectors.robot_detector import detect_robot_candidates
from qq_chat_analyzer.message import ChatMessage
from qq_chat_analyzer.smart_profile import run_smart_profile

from qq_db_test_data import qq_db_payload, qq_db_record


SHARED_NICKNAME = "虚构签到助手"
BOT_TEXT = "虚构固定播报"
MEMBER_TEXT = "今天讨论虚构测试方案"


# ------------------------------------------------------------ robot detector


def test_same_nickname_distinct_ids_keeps_normal_member() -> None:
    bot_messages = [
        _message(SHARED_NICKNAME, BOT_TEXT, index, sender_id="u-bot-1")
        for index in range(30)
    ]
    member_message = _message(
        SHARED_NICKNAME,
        MEMBER_TEXT,
        30,
        sender_id="u-member-1",
    )

    result = run_smart_profile([*bot_messages, member_message])

    assert result.kept_messages == [member_message]
    assert result.filtered_messages == bot_messages
    sender_decisions = [
        decision
        for decision in result.applied_decisions
        if decision.target_type == "sender"
    ]
    assert len(sender_decisions) == 1
    assert sender_decisions[0].target == SHARED_NICKNAME
    assert sender_decisions[0].metadata.get("sender_key") == "u-bot-1"


def test_same_id_renamed_nicknames_form_one_identity() -> None:
    messages = [
        _message("虚构播报助手甲", BOT_TEXT, index, sender_id="u-bot-2")
        for index in range(15)
    ]
    messages.extend(
        _message("虚构播报助手乙", BOT_TEXT, index + 100, sender_id="u-bot-2")
        for index in range(15)
    )
    member_message = _message(
        "虚构播报助手甲",
        MEMBER_TEXT,
        200,
        sender_id="u-member-2",
    )

    candidates = detect_robot_candidates([*messages, member_message])
    result = run_smart_profile([*messages, member_message])

    assert len(candidates) == 1
    assert candidates[0].target == "虚构播报助手甲"
    assert candidates[0].metadata.get("sender_key") == "u-bot-2"
    assert result.kept_messages == [member_message]
    assert result.filtered_messages == messages


# ---------------------------------------------------------- legacy / no id


def test_unresolved_id_record_sharing_nickname_is_preserved() -> None:
    bot_messages = [
        _message(SHARED_NICKNAME, BOT_TEXT, index, sender_id="u-bot-5")
        for index in range(30)
    ]
    legacy_member_message = _message(SHARED_NICKNAME, MEMBER_TEXT, 30)

    result = run_smart_profile([*bot_messages, legacy_member_message])

    assert result.kept_messages == [legacy_member_message]
    assert result.filtered_messages == bot_messages


# -------------------------------------------------------- interactive bot


def test_interactive_bot_evidence_is_kept_but_never_filters() -> None:
    messages: list[ChatMessage] = []
    for index in range(30):
        timestamp = 1_700_000_000 + index * 10
        messages.extend(
            [
                _message(
                    f"虚构提问者{index}",
                    f"@虚构交互助手 虚构查询{chr(0x4E00 + index)}",
                    timestamp,
                ),
                _message(
                    "虚构交互助手",
                    f"虚构响应{chr(0x4E00 + index)}",
                    timestamp + 1,
                    sender_id="u-bot-6",
                ),
            ]
        )
    member_message = _message(
        "虚构交互助手",
        MEMBER_TEXT,
        1_700_000_999,
        sender_id="u-member-6",
    )
    all_messages = [*messages, member_message]

    candidates = detect_interactive_bot_candidates(all_messages)
    result = run_smart_profile(all_messages)

    assert len(candidates) == 1
    assert candidates[0].target == "虚构交互助手"
    assert candidates[0].metadata["metrics"]["mention_count"] == 30
    assert candidates[0].metadata["metrics"]["response_rate"] == 1.0
    assert candidates[0].metadata.get("sender_key") == "u-bot-6"
    assert result.kept_messages == all_messages
    assert result.filtered_messages == []
    assert result.applied_decisions == []


def test_member_answering_before_the_bot_is_not_auto_deleted() -> None:
    """A member who answers every mention first must survive the run."""
    messages: list[ChatMessage] = []
    for index in range(30):
        timestamp = 1_700_000_000 + index * 10
        messages.extend(
            [
                _message(
                    f"虚构提问者{index}",
                    f"@虚构交互助手 虚构查询{chr(0x4E00 + index)}",
                    timestamp,
                ),
                _message(
                    "虚构交互助手",
                    f"虚构人工抢先回复{chr(0x4E00 + index)}",
                    timestamp + 1,
                    sender_id="u-human-7",
                ),
                _message(
                    "虚构交互助手",
                    f"虚构机器延迟响应{chr(0x4E00 + index)}",
                    timestamp + 2,
                    sender_id="u-bot-7",
                ),
            ]
        )
    all_messages = list(messages)

    candidates = detect_interactive_bot_candidates(all_messages)
    result = run_smart_profile(all_messages)

    assert len(candidates) == 1
    assert candidates[0].metadata["metrics"]["mention_count"] == 30
    assert result.kept_messages == all_messages
    assert result.filtered_messages == []
    assert result.applied_decisions == []


# ---------------------------------------------------------- source boundary


def test_qq_direct_db_projection_keeps_normal_member(tmp_path: Path) -> None:
    records = [
        qq_db_record(
            BOT_TEXT,
            sender_id="200000001",
            nickname=SHARED_NICKNAME,
            message_id=f"fictional-bot-{index}",
            timestamp=1_760_000_000 + index,
        )
        for index in range(30)
    ]
    records.append(
        qq_db_record(
            MEMBER_TEXT,
            sender_id="200000002",
            nickname=SHARED_NICKNAME,
            message_id="fictional-member-1",
            timestamp=1_760_000_100,
        )
    )
    messages = _qq_import(tmp_path, records)

    assert len(messages) == 31
    assert {message.sender for message in messages} == {SHARED_NICKNAME}

    result = run_smart_profile(messages)

    assert [message.text for message in result.kept_messages] == [MEMBER_TEXT]
    assert len(result.filtered_messages) == 30


def test_wechat_display_name_collision_keeps_normal_member(tmp_path: Path) -> None:
    rows = [
        _wechat_row(
            index,
            user_name="wxid_fictional_bot",
            sender_name=SHARED_NICKNAME,
            content=BOT_TEXT,
        )
        for index in range(30)
    ]
    rows.append(
        _wechat_row(
            30,
            user_name="wxid_fictional_member",
            sender_name=SHARED_NICKNAME,
            content=MEMBER_TEXT,
        )
    )
    messages = _wechat_import(tmp_path, rows)

    assert len(messages) == 31
    assert {message.sender for message in messages} == {SHARED_NICKNAME}

    result = run_smart_profile(messages)

    assert [message.text for message in result.kept_messages] == [MEMBER_TEXT]
    assert len(result.filtered_messages) == 30


# ------------------------------------------------------ full service report


def test_report_keeps_member_that_shares_bot_nickname(tmp_path: Path) -> None:
    """Acceptance: the member must survive import, filtering and reporting."""
    from qq_chat_analyzer.application import (
        AnalysisApplicationService,
        AnalysisRequestDTO,
        AnalysisStatus,
    )

    records = [
        qq_db_record(
            BOT_TEXT,
            sender_id="200000001",
            nickname=SHARED_NICKNAME,
            message_id=f"fictional-bot-{index}",
            timestamp=1_760_000_000 + index,
        )
        for index in range(30)
    ]
    records.extend(
        [
            qq_db_record(
                "今天讨论虚构测试方案",
                sender_id="200000002",
                nickname=SHARED_NICKNAME,
                message_id="fictional-member-1",
                timestamp=1_760_000_100,
            ),
            qq_db_record(
                "明天继续讨论虚构方案",
                sender_id="200000002",
                nickname=SHARED_NICKNAME,
                message_id="fictional-member-2",
                timestamp=1_760_000_101,
            ),
            qq_db_record(
                "虚构普通用户讨论本地测试",
                sender_id="200000003",
                nickname="虚构普通用户",
                message_id="fictional-other-1",
                timestamp=1_760_000_102,
            ),
        ]
    )
    input_path = tmp_path / "qq-direct-db.json"
    input_path.write_text(
        json.dumps(qq_db_payload(records), ensure_ascii=False),
        encoding="utf-8",
    )
    output_directory = tmp_path / "private-output"
    output_directory.mkdir()
    stopwords_path = tmp_path / "private-stopwords.txt"
    stopwords_path.write_text("", encoding="utf-8")

    result = AnalysisApplicationService().execute(
        AnalysisRequestDTO(
            input_path=input_path,
            output_directory=output_directory,
            stopwords_path=stopwords_path,
            font_path=None,
            top=5,
        )
    )

    assert result.status is AnalysisStatus.COMPLETED
    payload = json.loads(
        (output_directory / "echo-report.json").read_text(encoding="utf-8")
    )
    members = {member["speaker_key"]: member for member in payload["members"]}
    assert members["200000002"]["message_count"] == 2
    assert "200000001" not in members


@pytest.mark.parametrize(
    "decision_sender_key",
    [None, "  "],
)
def test_decision_without_identity_key_never_crosses_identities(
    decision_sender_key: str | None,
) -> None:
    from qq_chat_analyzer.filter_decisions import FilterDecision
    from qq_chat_analyzer.filter_pipeline import FilterPipeline

    unresolved_message = _message(SHARED_NICKNAME, BOT_TEXT, 1)
    resolved_message = _message(
        SHARED_NICKNAME,
        BOT_TEXT,
        2,
        sender_id="u-bot-7",
    )
    decision = FilterDecision(
        target=SHARED_NICKNAME,
        target_type="sender",
        action="ignore",
        confidence=1.0,
        reason="synthetic_test_decision",
        source="user",
        metadata={},
    )
    if decision_sender_key is not None:
        decision.metadata["sender_key"] = decision_sender_key

    result = FilterPipeline().apply_filter_decisions(
        [unresolved_message, resolved_message],
        [decision],
    )

    assert result.filtered_messages == [unresolved_message]
    assert result.kept_messages == [resolved_message]


# --------------------------------------------------------------- helpers


def _message(
    sender: str,
    text: str,
    timestamp: int,
    *,
    sender_id: str | None = None,
) -> ChatMessage:
    return ChatMessage(
        timestamp=timestamp,
        sender=sender,
        message_type="text",
        text=text,
        sender_id=sender_id,
        conversation_type="group",
    )


def _qq_import(tmp_path: Path, records: list[dict[str, object]]) -> list[ChatMessage]:
    from qq_chat_analyzer.application import ImportRequest, ImportService

    path = tmp_path / "qq-direct-db.json"
    path.write_text(
        json.dumps(qq_db_payload(records), ensure_ascii=False),
        encoding="utf-8",
    )
    outcome = ImportService().execute(
        ImportRequest(input_path=path, platform="qq")
    )
    return list(outcome.messages)


def _wechat_row(
    index: int,
    *,
    user_name: str,
    sender_name: str,
    content: str,
) -> dict[str, object]:
    return {
        "local_id": index + 1,
        "server_id": 900_100 + index,
        "local_type": 1,
        "create_time": 1_760_000_000 + index,
        "message_content": content,
        "user_name": user_name,
        "sender_name": sender_name,
    }


def _wechat_import(tmp_path: Path, rows: list[dict[str, object]]) -> list[ChatMessage]:
    from qq_chat_analyzer.application import ImportRequest, ImportService

    path = tmp_path / "wechat-db.json"
    path.write_text(
        json.dumps(
            {
                "source": "wechat-db",
                "conversation": {"username": "fictional-room@chatroom"},
                "messages": rows,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    outcome = ImportService().execute(
        ImportRequest(input_path=path, platform="wechat")
    )
    return list(outcome.messages)
