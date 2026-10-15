"""Fictional restart transport: no QQ files or credentials."""
import json
from types import SimpleNamespace

import pytest

from qq_chat_analyzer.providers.napcat_qq_provider import NapCatQQProvider, NapCatQQError
from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import QQDirectSnapshotRuntimeClient, QQSnapshotRuntimeError


class Worker:
    def __init__(self):
        self.boot = "b" * 64
        self.calls = []
        self.operations = []

    def transport(self, url, body, timeout):
        request = json.loads(body)
        self.calls.append(request)
        method = request["method"]
        if (method != "Core.status" or "boot_id" in request) and request.get("boot_id") != self.boot:
            return 409, json.dumps({"ok": False, "error": "worker_generation_mismatch"})
        if method == "Core.status":
            result = {"rpc_auth": "bearer-v1", "boot_id": self.boot,
                      "bridge_ready": True, "qq_online": True, "self_info": {},
                      "database_api_ready": True, "passphrase_ready": True, "snapshot_api_ready": True}
        else:
            self.operations.append(request)
            result = [] if method.startswith("EchoMetadata") else {
                "ok": True, "status": "ready", "generation_id": "fictional-generation"}
        return 200, json.dumps({"ok": True, "result": result})


def make(worker, tmp_path, kind):
    credential = SimpleNamespace(credential=lambda: "c" * 64)
    if kind == "provider":
        return NapCatQQProvider(transport=worker.transport, credential=credential)
    return QQDirectSnapshotRuntimeClient("http://127.0.0.1:40655", snapshot_root=tmp_path,
                                         transport=worker.transport, credential=credential)


@pytest.mark.parametrize("kind", ["provider", "snapshot"])
def test_bound_client_rejects_restart_and_new_client_explicitly_binds(tmp_path, kind):
    worker = Worker()
    client = make(worker, tmp_path, kind)
    operate = client.list_friends if kind == "provider" else client.recover
    operate()
    assert worker.operations[-1]["boot_id"] == "b" * 64
    worker.boot = "d" * 64
    worker.operations.clear()
    with pytest.raises((NapCatQQError, QQSnapshotRuntimeError)) as error:
        operate()
    assert error.value.code.endswith("worker_generation_changed")
    assert worker.operations == []
    calls = len(worker.calls)
    with pytest.raises((NapCatQQError, QQSnapshotRuntimeError)):
        operate()
    assert len(worker.calls) == calls
    fresh = make(worker, tmp_path, kind)
    (fresh.list_friends if kind == "provider" else fresh.recover)()
    assert worker.operations[-1]["boot_id"] == "d" * 64


@pytest.mark.parametrize("operation", ["acquire", "cleanup", "recover", "get_group_member_all"])
def test_stale_snapshot_never_operates_on_new_worker(tmp_path, operation):
    worker = Worker()
    client = make(worker, tmp_path, "snapshot")
    client.recover()
    worker.boot = "d" * 64
    worker.operations.clear()
    args = ["fictional-generation"] if operation == "cleanup" else ["45678901"] if operation == "get_group_member_all" else []
    with pytest.raises(QQSnapshotRuntimeError) as error:
        getattr(client, operation)(*args)
    assert error.value.code == "qq_snapshot_worker_generation_changed"
    assert worker.operations == []
    assert len(worker.calls) == 3  # discovery, recover, one refused request; no replay


@pytest.mark.parametrize("kind", ["provider", "snapshot"])
@pytest.mark.parametrize("boot", [None, True, "F" * 64])
def test_invalid_status_generation_fails_closed(tmp_path, kind, boot):
    worker = Worker()
    worker.boot = boot
    client = make(worker, tmp_path, kind)
    with pytest.raises((NapCatQQError, QQSnapshotRuntimeError)):
        (client.list_friends if kind == "provider" else client.recover)()
    assert worker.operations == []


def test_malformed_status_does_not_establish_provider_binding():
    calls = []
    def transport(url, body, timeout):
        method = json.loads(body)["method"]
        calls.append(method)
        result = {"rpc_auth": "bearer-v1", "boot_id": "b" * 64} if method == "Core.status" else []
        return 200, json.dumps({"ok": True, "result": result})
    client = NapCatQQProvider(transport=transport, credential=SimpleNamespace(credential=lambda: "c" * 64))
    for _ in range(2):
        with pytest.raises(NapCatQQError):
            client.list_friends()
    assert calls == ["Core.status", "Core.status"]


def test_snapshot_created_from_bound_provider_keeps_old_boot(tmp_path):
    worker = Worker()
    provider = make(worker, tmp_path, "provider")
    provider.status()
    worker.boot = "d" * 64
    client = provider.snapshot_client(tmp_path)
    with pytest.raises(QQSnapshotRuntimeError) as error:
        client.recover()
    assert error.value.code == "qq_snapshot_worker_generation_changed"
    assert [call["method"] for call in worker.calls] == ["Core.status", "EchoSnapshotApi.recover"]
    assert worker.operations == []


def test_restart_during_unstable_retry_never_replays_into_new_worker(tmp_path, monkeypatch):
    from qq_chat_analyzer.providers import qq_direct_snapshot_runtime as runtime
    worker = Worker()
    original = worker.transport
    def unstable(url, body, timeout):
        status, result = original(url, body, timeout)
        if status == 200 and json.loads(body)["method"] == "EchoSnapshotApi.acquire":
            worker.boot = "d" * 64
            return 200, json.dumps({"ok": True, "result": {
                "ok": False, "status": "failed", "code": "snapshot_unstable"}})
        return status, result
    worker.transport = unstable
    monkeypatch.setattr(runtime.time, "sleep", lambda seconds: None)
    client = make(worker, tmp_path, "snapshot")
    with pytest.raises(QQSnapshotRuntimeError) as error:
        client.acquire()
    assert error.value.code == "qq_snapshot_worker_generation_changed"
    assert len(worker.operations) == 1  # Only the first operation reached the old Worker.
    assert len(worker.calls) == 3
    assert all(call.get("boot_id") == "b" * 64 for call in worker.calls[1:])
