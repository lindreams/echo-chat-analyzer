"""Fictional private QQ pokes require two agreeing UID representations."""

import base64
from dataclasses import replace
import json
import sqlite3
import importlib

import pytest

from qq_db_test_data import length_delimited_field as field, scalar_field, qq_db_payload, qq_db_record
from qq_chat_analyzer.qq_db_adapter import parse_qq_db_rich_messages
from test_rich_filtering_association import analyze
from qq_chat_analyzer.application.scope_filter import AnalysisScope
from qq_chat_analyzer.presentation.echo_serializer import echo_report_to_dict
from qq_chat_analyzer.analysis.timestamps import to_chat_datetime
from qq_chat_analyzer.filter_decisions import FilterDecision
from qq_chat_analyzer.filter_pipeline import FilterPipeline


OWNER, PEER = "100000001", "100000002"
OWNER_UID, PEER_UID = "u_fictional_owner", "u_fictional_peer"
STAMP = 1760000000


def poke_segment(*, incoming=False, json_value=None, uid_order=None, business=1061):
    parties = [PEER_UID, OWNER_UID] if incoming else [OWNER_UID, PEER_UID]
    encoded_json = json_value if json_value is not None else json.dumps({
        "items": [{"uid": parties[0]}, {"txt": "fictional action"}, {"uid": parties[1]}],
    }).encode()
    return (scalar_field(45002, 8) + scalar_field(48212, 1061)
            + b"".join(field(48210, field(1005, uid.encode())) for uid in (uid_order or parties))
            + field(48271, encoded_json) + scalar_field(48273, business))


def poke_row(message_id=101, *, incoming=False, timestamp=STAMP, segment=None):
    row = qq_db_record(message_id=str(message_id), sender_id="0", timestamp=timestamp)
    row["fields"].update({"40001": str(message_id), "40027": "fiction-partition"})
    row["source_meta"] = {"table": "c2c_msg_table"}
    row["message_blob"] = base64.b64encode(field(40800, segment if segment is not None else poke_segment(incoming=incoming))).decode()
    return row


def payload(rows):
    data = qq_db_payload(rows, session_type="private", session_id="fiction-session", self_uin=OWNER)
    data["query"]["internal_key"] = "fiction-partition"
    data["private_nudge_context"] = {
        "namespace": "qq_uin", "session_key": "fiction-partition",
        "conversation_id": "fiction-session", "owner_uin": OWNER, "owner_uid": OWNER_UID,
        "peer_uin": PEER, "peer_uid": PEER_UID, "peer_name": "Fictional friend",
    }
    return data


@pytest.mark.parametrize("incoming,message_id,sender_id", [
    (False, 101, "0"), (True, 102, "0"), (False, -103, "0"), (True, 104, None),
])
def test_poke_adapter_uses_confirmed_uid_pair_not_system_sender(incoming, message_id, sender_id):
    row = poke_row(message_id, incoming=incoming)
    row["fields"]["40033"] = sender_id
    messages, _ = parse_qq_db_rich_messages(payload([row]))
    assert len(messages) == 1
    message = messages[0]
    assert message.message_type == "nudge" and message.is_system
    assert message.is_self is (not incoming)
    assert message.sender.identity_id == (PEER if incoming else OWNER)
    assert message.relations[0].target_identity_id == (OWNER if incoming else PEER)
    assert message.contents == ()


@pytest.mark.parametrize("change", [
    "no_context", "foreign_context", "wrong_owner", "same_uid", "same_uin", "group",
    "foreign_partition", "foreign_table", "missing_id", "conflicting_id", "invalid_time",
    "reversed_uid", "third_uid", "wrong_business", "duplicate_business", "duplicate_json_key",
    "mixed_content", "duplicate_actions",
])
def test_poke_adapter_rejects_unconfirmed_or_ambiguous_actions(change):
    data = payload([poke_row()])
    context, row = data["private_nudge_context"], data["records"][0]
    if change == "no_context": del data["private_nudge_context"]
    elif change == "foreign_context": context["session_key"] = "other-partition"
    elif change == "wrong_owner": context["owner_uin"] = "100000003"
    elif change == "same_uid": context["peer_uid"] = OWNER_UID
    elif change == "same_uin": context["peer_uin"] = OWNER
    elif change == "group": data["query"]["session_type"] = "group"
    elif change == "foreign_partition": row["fields"]["40027"] = "other-partition"
    elif change == "foreign_table": row["source_meta"]["table"] = "group_msg_table"
    elif change == "missing_id": row.pop("record_id")
    elif change == "conflicting_id": row["fields"]["40001"] = "102"
    elif change == "invalid_time": row["fields"]["40050"] = "not a time"
    else:
        segment = poke_segment()
        if change == "reversed_uid": segment = poke_segment(uid_order=[PEER_UID, OWNER_UID])
        elif change == "third_uid": segment = poke_segment(json_value=json.dumps({"items": [{"uid": OWNER_UID}, {"uid": PEER_UID}, {"uid": "u_fictional_other"}]}).encode())
        elif change == "wrong_business": segment = poke_segment(business=1062)
        elif change == "duplicate_business": segment += scalar_field(48273, 1061)
        elif change == "duplicate_json_key":
            segment = poke_segment(json_value=b'{"items":[],"items":' + json.dumps([
                {"uid": OWNER_UID}, {"uid": PEER_UID},
            ]).encode() + b'}')
        body = field(40800, segment)
        if change == "mixed_content": body += field(40800, scalar_field(45002, 1) + field(45101, b"authored"))
        elif change == "duplicate_actions": body += body
        row["message_blob"] = base64.b64encode(body).decode()
    messages, _ = parse_qq_db_rich_messages(data)
    assert not any(message.message_type == "nudge" for message in messages)


def test_qq_pokes_do_not_inflate_messages_or_bridge_conversation_rounds(tmp_path, monkeypatch, caplog):
    caplog.set_level("INFO")
    rows = [poke_row(101), poke_row(102, incoming=True, timestamp=STAMP + 1800), poke_row(103, timestamp=STAMP + 3600)]
    rows += [qq_db_record("虚构的午后一起散步", sender_id=OWNER, timestamp=STAMP),
             qq_db_record("虚构的傍晚一起吃饭", sender_id=PEER, timestamp=STAMP + 3600)]
    result, (kept, _) = analyze(tmp_path, monkeypatch, [payload(rows)])
    assert len(kept) == result.reports.activity.total_message_count == 2
    assert result.reports.conversation_sessions.session_count == 2
    nudges = result.reports.private_nudges
    assert (nudges.self_count, nudges.peer_count, nudges.source) == (2, 1, "qq")
    assert result.echo_report_view.private_nudges.source == "qq"
    serialized = json.dumps(echo_report_to_dict(result.echo_report_view)["private_nudges"])
    assert all(identity not in serialized for identity in (OWNER, PEER, OWNER_UID, PEER_UID))
    diagnostics = "\n".join(record.getMessage() for record in caplog.records
                            if record.name == "qq_chat_analyzer.qq.private_nudges")
    assert "accepted=3 identity_bound=True" in diagnostics
    assert all(identity not in diagnostics for identity in (OWNER, PEER, OWNER_UID, PEER_UID))


def test_qq_action_only_report_obeys_date_scope(tmp_path, monkeypatch):
    day = to_chat_datetime(STAMP).date()
    result, (kept, _) = analyze(tmp_path, monkeypatch, [payload([
        poke_row(101, timestamp=STAMP - 86400), poke_row(102, incoming=True),
    ])], AnalysisScope.custom(day, day))
    assert kept == []
    assert result.reports.activity.total_message_count == 0
    assert (result.reports.private_nudges.self_count, result.reports.private_nudges.peer_count) == (0, 1)


def test_qq_duplicate_conflicts_and_mixed_sources_do_not_produce_false_counts():
    from qq_chat_analyzer.analysis.private_nudges import analyze_private_nudges
    messages, _ = parse_qq_db_rich_messages(payload([poke_row(101), poke_row(102, incoming=True)]))
    counts = analyze_private_nudges([*messages, messages[0]])
    assert (counts.self_count, counts.peer_count) == (1, 1)
    counts = analyze_private_nudges([*messages, replace(messages[0], timestamp=STAMP + 1)])
    assert (counts.self_count, counts.peer_count) == (0, 1)
    assert analyze_private_nudges([*messages, replace(messages[0], source="wechat", conversation_id=PEER)]) is None


@pytest.mark.parametrize("ignored", [OWNER, PEER])
def test_qq_pokes_cannot_restore_excluded_actor_or_target(tmp_path, monkeypatch, ignored):
    service = importlib.import_module("qq_chat_analyzer.application.analysis_service")
    decision = FilterDecision(ignored, "sender", "ignore", 1, "fiction", "manual")

    def filter_sender(messages):
        assert all(message.message_type != "nudge" for message in messages)
        return FilterPipeline().apply_filter_decisions(messages, [decision])

    monkeypatch.setattr(service, "run_smart_profile", filter_sender)
    result, _ = analyze(tmp_path, monkeypatch, [payload([
        poke_row(101), poke_row(102, incoming=True),
        qq_db_record("虚构的普通消息", sender_id=ignored, timestamp=STAMP),
    ])])
    assert result.reports is None or result.reports.private_nudges is None


def identity_metadata():
    return {"self_info": {"uin": OWNER, "uid": OWNER_UID},
            "friends": [{"uin": PEER, "uid": PEER_UID, "remark": "Fictional friend"}]}


@pytest.mark.parametrize("change", ["valid", "session_uid", "other_owner", "duplicate_peer", "uid_collision", "missing_peer", "peer_conflict"])
def test_private_identity_binding_requires_unique_same_account_metadata(change):
    from qq_chat_analyzer.application.qq import qq_direct_database_import_service as source
    from qq_chat_analyzer.providers.qq_database_provider import QQSession
    from types import SimpleNamespace

    data = identity_metadata()
    if change == "other_owner": data["self_info"]["uin"] = "100000003"
    elif change == "duplicate_peer": data["friends"] *= 2
    elif change == "uid_collision": data["friends"].append({"uin": "100000003", "uid": PEER_UID})
    elif change == "missing_peer": data["friends"] = []
    elif change == "peer_conflict": data["friends"].append({"uin": "100000003", "uid": "u_fictional_other"})
    client = SimpleNamespace(get_private_identity_metadata=lambda **kwargs: data)
    session = QQSession("fiction-partition", "fiction-session", "Fictional", "private", peer_uin=PEER)
    if change == "session_uid":
        session = QQSession("fiction-partition", PEER_UID, "Fictional", "private")
    elif change == "peer_conflict":
        session = QQSession("fiction-partition", "u_fictional_other", "Fictional", "private", peer_uin=PEER)
    context = source._private_nudge_identity_context(client, session, OWNER)
    if change in {"valid", "session_uid"}:
        assert context == payload([])["private_nudge_context"] | {"conversation_id": session.conversation_id}
    else:
        assert context is None


def test_private_acquisition_attaches_bound_context_after_releasing_snapshot(tmp_path):
    from qq_chat_analyzer.application.qq.qq_direct_database_import_service import QQDirectDatabaseImportService
    from qq_direct_db_testing import FakeSnapshotRuntime
    from test_qq_direct_analyze_single_generation import _create_snapshot

    database = tmp_path / "fiction.db"
    _create_snapshot(database)
    with sqlite3.connect(database) as connection:
        connection.execute('DELETE FROM c2c_msg_table')
        connection.execute('INSERT INTO c2c_msg_table VALUES (?, ?, ?, ?, ?, ?)',
                           (201, "fiction-partition", "fiction-session", PEER, STAMP,
                            field(40800, scalar_field(45002, 1) + field(45101, b"fictional"))))
        connection.execute('INSERT INTO c2c_msg_table VALUES (?, ?, ?, ?, ?, ?)',
                           (101, "fiction-partition", "fiction-session", "0", STAMP + 1,
                            field(40800, poke_segment())))
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=database, identity_value=OWNER)

    def metadata(**kwargs):
        assert runtime.cleaned == runtime.acquired
        return identity_metadata()

    runtime.get_private_identity_metadata = metadata
    service = QQDirectDatabaseImportService(runtime_client=runtime)
    service.start()
    with service.acquired_session("private:fiction-partition") as acquired:
        data = json.loads(acquired.payload_path.read_text(encoding="utf-8"))
        assert data["private_nudge_context"] == payload([])["private_nudge_context"]
        messages, _ = parse_qq_db_rich_messages(data)
        assert [message.is_self for message in messages if message.message_type == "nudge"] == [True]
        scratch = acquired.payload_path
    assert not scratch.exists()
    assert len(runtime.acquired) == 1 and runtime.acquired == runtime.cleaned


def test_identity_metadata_rpc_stays_bound_and_shares_one_deadline(tmp_path, monkeypatch):
    from qq_chat_analyzer.providers import qq_direct_snapshot_runtime as runtime
    clock = [100.0]
    monkeypatch.setattr(runtime.time, "monotonic", lambda: clock[0])
    calls = []

    def transport(url, body, timeout):
        request = json.loads(body)
        calls.append((request, timeout))
        clock[0] += 1
        result = ({"self_info": identity_metadata()["self_info"], "boot_id": "b" * 64,
                   "runtime_id": "a" * 64, "rpc_auth": "bearer-v1"}
                  if request["method"] == "Core.status" else identity_metadata()["friends"])
        return 200, json.dumps({"ok": True, "result": result})

    client = runtime.QQDirectSnapshotRuntimeClient("http://127.0.0.1:12345", snapshot_root=tmp_path,
        runtime_id="a" * 64, boot_id="b" * 64, transport=transport)
    assert client.get_private_identity_metadata(timeout=5) == identity_metadata()
    assert [call[0]["method"] for call in calls] == ["Core.status", "EchoMetadata.listFriends"]
    assert [call[1] for call in calls] == [5, 4]
    assert all(call[0]["boot_id"] == "b" * 64 for call in calls)


@pytest.mark.parametrize("failure", ["boot", "runtime", "auth"])
def test_identity_metadata_never_fetches_friends_after_invalid_binding(tmp_path, failure):
    from qq_chat_analyzer.providers import qq_direct_snapshot_runtime as runtime
    calls = []
    status = {"self_info": identity_metadata()["self_info"], "boot_id": "b" * 64,
              "runtime_id": "a" * 64, "rpc_auth": "bearer-v1"}
    status[{"boot": "boot_id", "runtime": "runtime_id", "auth": "rpc_auth"}[failure]] = "c" * 64

    def transport(url, body, timeout):
        calls.append(json.loads(body))
        return 200, json.dumps({"ok": True, "result": status})

    client = runtime.QQDirectSnapshotRuntimeClient("http://127.0.0.1:12345", snapshot_root=tmp_path,
        runtime_id="a" * 64, boot_id="b" * 64, transport=transport)
    expected = runtime.QQSnapshotRuntimeUnauthorized if failure == "auth" else runtime.QQSnapshotWorkerGenerationChanged
    with pytest.raises(expected):
        client.get_private_identity_metadata(timeout=5)
    assert [call["method"] for call in calls] == ["Core.status"]


@pytest.mark.parametrize("generation_changed", [False, True])
def test_private_metadata_failure_does_not_leave_snapshot_or_payload(tmp_path, monkeypatch, generation_changed):
    from qq_chat_analyzer.application.qq import qq_direct_database_import_service as source
    from qq_chat_analyzer.application.qq.qq_direct_database_import_service import QQDirectSnapshotAcquireFailed
    from qq_chat_analyzer.application.qq.qq_provider_factory import QQReconnectRequired
    from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import QQSnapshotWorkerGenerationChanged, QQSnapshotRuntimeUnauthorized
    from test_qq_direct_analyze_single_generation import _service

    service, runtime, _ = _service(tmp_path)
    scratch_paths = []
    temporary_directory = source.TemporaryDirectory

    def capture_scratch(*args, **kwargs):
        kwargs["dir"] = tmp_path
        context = temporary_directory(*args, **kwargs)
        scratch_paths.append(source.Path(context.name))
        return context

    monkeypatch.setattr(source, "TemporaryDirectory", capture_scratch)

    def metadata(**kwargs):
        assert runtime.acquired == runtime.cleaned
        raise QQSnapshotWorkerGenerationChanged() if generation_changed else QQSnapshotRuntimeUnauthorized()

    runtime.get_private_identity_metadata = metadata
    service.start()
    with pytest.raises(QQReconnectRequired if generation_changed else QQDirectSnapshotAcquireFailed):
        with service.acquired_session("private:private-partition"):
            pytest.fail("invalid identity metadata must not yield an analysis payload")
    assert runtime.acquired == runtime.cleaned
    assert scratch_paths and all(not path.exists() for path in scratch_paths)
