"""RED/GREEN suite for Release Slice 1A identity semantics.

Every fixture below is fictional. No real QQ/WeChat account data appears here.
"""

from __future__ import annotations

import importlib
import json
from qq_db_test_data import qq_db_payload, qq_db_record
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer.legacy_projection import project_legacy_message
from qq_chat_analyzer.message import ChatMessage
from qq_chat_analyzer.rich_message import RichMessage, SenderIdentity, TextContent


def _message(
    sender: str,
    *,
    sender_id: str | None = None,
    conversation_id: str | None = None,
    conversation_type: str = "unknown",
    is_self: bool | None = None,
    text: str = "hello",
) -> ChatMessage:
    return ChatMessage(
        timestamp=1,
        sender=sender,
        message_type="text",
        text=text,
        sender_id=sender_id,
        conversation_id=conversation_id,
        conversation_type=conversation_type,
        is_self=is_self,
    )


def _user_profile_analyzer():
    return importlib.import_module(
        "qq_chat_analyzer.analysis.analyzers.user_profile_analyzer"
    ).UserProfileAnalyzer()


def _conversation_analyzer():
    return importlib.import_module(
        "qq_chat_analyzer.analysis.analyzers.conversation_analyzer"
    ).ConversationAnalyzer()


def _write_wechat_db(
    path: Path,
    username: str,
    rows: list[object],
    *,
    self_username: str | None = None,
) -> None:
    conversation: dict[str, object] = {"username": username}
    if self_username is not None:
        conversation["self_username"] = self_username
    path.write_text(
        json.dumps(
            {"source": "wechat-db", "conversation": conversation, "messages": rows},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _db_row(username: str, content: str = "fictional db text") -> dict[str, object]:
    return {
        "local_id": 1,
        "server_id": 900001,
        "local_type": 1,
        "create_time": 1753412807,
        "message_content": content,
        "user_name": username,
    }


def _write_detailed_wechat(
    path: Path,
    *,
    session_id: str,
    is_group: bool,
    messages: list[dict[str, object]],
) -> None:
    path.write_text(
        json.dumps(
            {
                "exportInfo": {"format": "detailed-json"},
                "session": {
                    "wxid": session_id,
                    "platform": "wechat",
                    "isGroup": is_group,
                },
                "messages": messages,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _detailed_message(
    username: str,
    display_name: str,
    *,
    is_send: int,
) -> dict[str, object]:
    return {
        "localId": 1,
        "platformMessageId": "fictional-message-001",
        "createTime": 1783223281,
        "type": "文本消息",
        "localType": 1,
        "content": "fictional detailed text",
        "isSend": is_send,
        "senderUsername": username,
        "senderDisplayName": display_name,
    }


def _import_outcome(input_path: Path, platform: str):
    application = importlib.import_module("qq_chat_analyzer.application")
    return application.ImportService().execute(
        application.ImportRequest(input_path=input_path, platform=platform)
    )


# ------------------------------------------------------------------ model


# ------------------------------------------------------ stable aggregation


def test_user_profiles_merge_same_stable_id_across_renames() -> None:
    messages = [
        _message("Fictional Alice", sender_id="u-fictional-1", text="hello"),
        _message("Fictional Alice Renamed", sender_id="u-fictional-1", text="world"),
    ]

    report = _user_profile_analyzer().analyze(messages)

    assert len(report.profiles) == 1
    profile = report.profiles[0]
    assert profile.speaker_key == "u-fictional-1"
    assert profile.message_count == 2


def test_user_profiles_keep_same_display_name_with_distinct_ids() -> None:
    messages = [
        _message("Fictional Alice", sender_id="u-fictional-1"),
        _message("Fictional Alice", sender_id="u-fictional-2"),
    ]

    report = _user_profile_analyzer().analyze(messages)

    assert len(report.profiles) == 2
    assert {profile.speaker_key for profile in report.profiles} == {
        "u-fictional-1",
        "u-fictional-2",
    }


def test_conversation_analyzer_counts_stable_participants() -> None:
    messages = [
        _message("Fictional Alice", sender_id="u-1", conversation_id="room-1"),
        _message("Fictional Alice Renamed", sender_id="u-1", conversation_id="room-1"),
        _message("Fictional Alice Renamed", sender_id="u-2", conversation_id="room-1"),
        _message("Fictional Alice", sender_id="u-3", conversation_id="room-1"),
    ]

    summary = _conversation_analyzer().analyze(messages).conversations[0]

    assert summary.speaker_count == 3


def test_word_speaker_tokens_use_stable_sender_key(tmp_path: Path) -> None:
    analysis_service = importlib.import_module(
        "qq_chat_analyzer.application.analysis_service"
    )
    stopwords_path = tmp_path / "empty-stopwords.txt"
    stopwords_path.write_text("", encoding="utf-8")
    messages = [
        _message("Fictional Alice", sender_id="u-1", text="hello"),
        _message("Fictional Alice Renamed", sender_id="u-1", text="world"),
    ]

    analyzed = analysis_service._analyze_kept_messages(messages, stopwords_path)

    assert {sender for sender, _tokens in analyzed.sender_tokens} == {"u-1"}


# -------------------------------------------------------------- QQ wiring


def _qq_import(tmp_path, records, **context):
    path = tmp_path / "qq-db.json"
    path.write_text(json.dumps(qq_db_payload(records, **context)), encoding="utf-8")
    return _import_outcome(path, "qq")


def test_qq_missing_conversation_context_does_not_invent_identity(tmp_path):
    outcome = _qq_import(tmp_path, [qq_db_record("fictional text")], session_type=None)
    assert outcome.messages == ()
    assert outcome.result.warnings == ("qq_db_record_skipped",)


def test_qq_db_self_identity_canonicalizes_numeric_sender(tmp_path):
    outcome = _qq_import(tmp_path, [
        qq_db_record("mine", sender_id=100000001),
        qq_db_record("theirs", sender_id=100000002),
    ], self_uin="100000001")
    assert [message.is_self for message in outcome.messages] == [True, False]


# ----------------------------------------------------------- WeChat wiring


def test_wechat_db_private_and_group_conversation_types(
    tmp_path: Path,
) -> None:
    private_path = tmp_path / "wechat-private.json"
    _write_wechat_db(
        private_path,
        "wxid_fictional_friend",
        [_db_row("wxid_fictional_friend")],
    )
    group_path = tmp_path / "wechat-group.json"
    _write_wechat_db(
        group_path,
        "fictional-room@chatroom",
        [_db_row("wxid_fictional_member")],
    )

    private_outcome = _import_outcome(private_path, "wechat")
    group_outcome = _import_outcome(group_path, "wechat")

    assert private_outcome.messages[0].conversation_type == "private"
    assert group_outcome.messages[0].conversation_type == "group"


def test_wechat_db_self_identity_uses_conversation_self_username(
    tmp_path: Path,
) -> None:
    known_path = tmp_path / "wechat-known-self.json"
    _write_wechat_db(
        known_path,
        "wxid_fictional_friend",
        [
            _db_row("wxid_fictional_me", content="mine"),
            _db_row("wxid_fictional_peer", content="theirs"),
        ],
        self_username="wxid_fictional_me",
    )
    unknown_path = tmp_path / "wechat-unknown-self.json"
    _write_wechat_db(
        unknown_path,
        "wxid_fictional_friend",
        [_db_row("wxid_fictional_sender")],
    )

    known_outcome = _import_outcome(known_path, "wechat")
    unknown_outcome = _import_outcome(unknown_path, "wechat")

    assert [message.is_self for message in known_outcome.messages] == [True, False]
    assert unknown_outcome.messages[0].is_self is None


# ---------------------------------------------------------------- Echo


def test_identity_diagnostics_log_is_anonymized(caplog) -> None:
    analysis_service = importlib.import_module(
        "qq_chat_analyzer.application.analysis_service"
    )
    messages = [
        ChatMessage(
            timestamp=1,
            sender="Fictional Alice",
            message_type="text",
            text="secret fictional body",
            platform="qq",
            sender_id="u-fictional-self",
            conversation_id="fictional-room",
            conversation_type="private",
            is_self=True,
        )
    ]

    with caplog.at_level(
        "INFO",
        logger="qq_chat_analyzer.desktop.identity",
    ):
        analysis_service._log_identity_diagnostics(messages)

    assert (
        "[identity] source=qq conversation_type=private "
        "self_identity=resolved sender_identity_coverage=resolved"
        in caplog.text
    )
    for secret in (
        "u-fictional-self",
        "fictional-room",
        "Fictional Alice",
        "secret fictional body",
    ):
        assert secret not in caplog.text


def test_echo_report_html_hides_raw_speaker_key(tmp_path: Path) -> None:
    presentation = importlib.import_module("qq_chat_analyzer.presentation")
    view = presentation.EchoReportView(
        title="Echo Report",
        has_data=True,
        members=(
            presentation.EchoMemberCard(
                speaker_key="internal-id-123",
                display_name="Fictional Alice",
                is_viewer=False,
                message_count=1,
                message_share_percent=100.0,
                average_length=3.0,
                max_length=3,
                active_period="",
            ),
        ),
    )
    html_path = tmp_path / "echo-report.html"
    json_path = tmp_path / "echo-report.json"

    presentation.export_echo_report_html(view, html_path)
    presentation.export_echo_report_json(view, json_path)

    html = html_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    match = re.search(
        r"window\.ECHO_DATA = (\{.*?\});",
        html,
        flags=re.DOTALL,
    )
    assert match is not None
    assert "internal-id-123" in match.group(1)
    rendered_without_data = html.replace(match.group(0), "")
    assert "internal-id-123" not in rendered_without_data
    assert payload["members"][0]["speaker_key"] == "internal-id-123"


def test_analysis_service_echo_artifact_uses_kind_and_viewer(
    tmp_path: Path,
) -> None:
    application = importlib.import_module("qq_chat_analyzer.application")
    input_path = tmp_path / "wechat-detailed.json"
    _write_detailed_wechat(
        input_path,
        session_id="wxid_fictional_friend",
        is_group=False,
        messages=[
            _detailed_message("wxid_fictional_me", "Fictional Me", is_send=1),
            _detailed_message("wxid_fictional_peer", "Fictional Peer", is_send=0),
        ],
    )
    output_directory = tmp_path / "private-output"
    output_directory.mkdir()
    stopwords_path = tmp_path / "private-stopwords.txt"
    stopwords_path.write_text("", encoding="utf-8")
    request = application.AnalysisRequestDTO(
        input_path=input_path,
        output_directory=output_directory,
        stopwords_path=stopwords_path,
        font_path=None,
        top=5,
        conversation_kind="private",
        viewer_speaker_key="wxid_fictional_me",
    )

    result = application.AnalysisApplicationService().execute(request)

    assert result.status is application.AnalysisStatus.COMPLETED
    payload = json.loads(
        (output_directory / "echo-report.json").read_text(encoding="utf-8")
    )
    assert payload["conversation"]["kind"] == "private"
    members = {member["speaker_key"]: member for member in payload["members"]}
    assert members["wxid_fictional_me"]["is_viewer"] is True
    assert members["wxid_fictional_peer"]["is_viewer"] is False
