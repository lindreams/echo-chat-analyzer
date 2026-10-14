"""RED-GREEN coverage for the Python snapshot runtime client (Phase 2A).

These tests drive ``QQDirectSnapshotRuntimeClient`` against an injected HTTP
transport, so no real NapCat bridge or QQ data is touched.  Every identity,
generation id and response body is fictional.

The client is deliberately narrow: it may only invoke ``EchoSnapshotApi``
``acquire`` / ``cleanup`` / ``recover`` over a localhost ``/rpc`` bridge, and it
never accepts an absolute database path from the runtime.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from pathlib import Path

import pytest
import qq_chat_analyzer.providers.qq_direct_snapshot_runtime as snapshot_runtime

from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import (
    QQDirectSnapshotRuntimeClient,
    QQSnapshotCleanupFailed,
    QQSnapshotInvalidGenerationId,
    QQSnapshotRuntimeFailure,
    QQSnapshotRuntimeInvalidResponse,
    QQSnapshotRuntimeNotReady,
    QQSnapshotRuntimeUnavailable,
    _urllib_transport,
    validate_generation_id,
)


def _envelope(result: object, *, ok: bool = True) -> str:
    return json.dumps({"id": 1, "ok": ok, "result": result})


def _rpc_error(message: str) -> str:
    return json.dumps({"id": 1, "ok": False, "error": message})


def _acquire_result(generation_id: str, *, ok: bool = True, status: str = "ready") -> dict:
    if not ok:
        return {"ok": False, "code": "decrypt_failed", "status": "failed"}
    return {"ok": True, "generation_id": generation_id, "status": status}


class _FakeTransport:
    """Captures one RPC call and returns a canned response."""

    def __init__(self, status: int = 200, body: str = "", error: Exception | None = None) -> None:
        self.status = status
        self.body = body
        self.error = error
        self.calls: list[tuple[str, bytes, int]] = []

    def __call__(self, url: str, body: bytes, timeout: int) -> tuple[int, str]:
        self.calls.append((url, body, timeout))
        if self.error is not None:
            raise self.error
        return self.status, self.body


class _SequenceTransport:
    """Return fictional acquire responses in order and track overlapping calls."""

    def __init__(self, results: list[dict]) -> None:
        self.results = iter(results)
        self.calls = 0
        self.active = 0
        self.max_active = 0

    def __call__(self, url: str, body: bytes, timeout: float) -> tuple[int, str]:
        assert json.loads(body) == {"method": "EchoSnapshotApi.acquire", "params": [], "boot_id": "b" * 64}
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            self.calls += 1
            return 200, _envelope(next(self.results))
        finally:
            self.active -= 1


def _client(transport, *, base_url: str = "http://127.0.0.1:40654", root: Path | None = None) -> QQDirectSnapshotRuntimeClient:
    return QQDirectSnapshotRuntimeClient(
        base_url=base_url,
        snapshot_root=root or Path("."),
        transport=transport,
        boot_id="b" * 64,  # Business-operation fixtures start with a verified binding.
    )


# ------------------------------------------------------------------ acquire

@pytest.mark.parametrize("status,body,category,error_type", [
    (401, _rpc_error("fictional-secret"), "auth_rejected", snapshot_runtime.QQSnapshotRuntimeUnauthorized),
    (409, _rpc_error("worker_generation_mismatch"), "worker_generation_changed", snapshot_runtime.QQSnapshotWorkerGenerationChanged),
    (409, _rpc_error("runtime_identity_mismatch"), "runtime_identity_mismatch", QQSnapshotRuntimeInvalidResponse),
    (400, _rpc_error("invalid_method"), "rpc_method_missing", QQSnapshotRuntimeInvalidResponse),
    (200, "fictional-secret raw account=12345678 C:/private/qq", "invalid_response", QQSnapshotRuntimeInvalidResponse),
    (200, _rpc_error("fictional-secret raw account=12345678 C:/private/qq"), "rpc_operation_failed", QQSnapshotRuntimeFailure),
    (200, _envelope({"ok": False, "code": "recover_failed", "private": "fictional-secret"}), "recover_failed", QQSnapshotRuntimeFailure),
    (200, _envelope({"ok": False, "code": "fictional-secret raw account=12345678 C:/private/qq"}), "operation_failed", QQSnapshotRuntimeFailure),
])
def test_recover_diagnostics_classify_rpc_failures_without_payloads(tmp_path, caplog, status, body, category, error_type):
    caplog.set_level("INFO")
    transport = _FakeTransport(status, body)
    client = QQDirectSnapshotRuntimeClient("http://127.0.0.1:40655", snapshot_root=tmp_path,
        boot_id="b" * 64, credential=SimpleNamespace(credential=lambda: "c" * 64), transport=transport)
    with pytest.raises(error_type):
        client.recover(deadline=time.monotonic() + 5)
    assert len(transport.calls) == 1
    assert "stage=recover_rpc outcome=started" in caplog.text
    assert "stage=recover_rpc outcome=failed" in caplog.text
    assert "elapsed_ms=" in caplog.text
    assert f"failure_code={category}" in caplog.text
    assert f"http_status={status}" in caplog.text
    for value in ("fictional-secret", "12345678", "C:/private", str(tmp_path), "b" * 64, "c" * 64, body):
        assert value not in caplog.text


def test_recover_diagnostics_success_and_unreachable(tmp_path, caplog):
    caplog.set_level("INFO")
    _client(_FakeTransport(body=_envelope({"ok": True})), root=tmp_path).recover()
    assert "stage=recover_rpc outcome=success" in caplog.text
    caplog.clear()
    with pytest.raises(QQSnapshotRuntimeUnavailable):
        _client(_FakeTransport(error=OSError("fictional-secret C:/private/qq")), root=tmp_path).recover()
    assert "stage=recover_rpc outcome=failed failure_code=runtime_unavailable" in caplog.text
    assert "fictional-secret" not in caplog.text
    assert "C:/private" not in caplog.text


def test_acquire_success_returns_and_logs_validated_generation_id(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = _FakeTransport(body=_envelope(_acquire_result("gen-1234")))
    client = _client(transport, root=tmp_path)

    with caplog.at_level(
        "INFO",
        logger="qq_chat_analyzer.desktop.qq_direct_snapshot",
    ):
        assert client.acquire() == "gen-1234"

    assert "outcome=ready" in caplog.text
    assert "generation_id=gen-1234" in caplog.text
    assert transport.calls[0][0] == "http://127.0.0.1:40654/rpc"
    request = json.loads(transport.calls[0][1].decode("utf-8"))
    assert request == {"method": "EchoSnapshotApi.acquire", "params": [], "boot_id": "b" * 64}


def test_group_member_lookup_uses_fixed_napcat_api_over_local_rpc(tmp_path: Path) -> None:
    members = {"result": {"infos": {"fictional-member": {
        "uin": "fictional-member", "cardName": "Fictional Card", "nick": "Fictional Nick"
    }}}}
    transport = _FakeTransport(body=_envelope(members))
    client = _client(transport, root=tmp_path)

    assert client.get_group_member_all("fictional-group") == members
    assert transport.calls[0][0] == "http://127.0.0.1:40654/rpc"
    assert json.loads(transport.calls[0][1].decode("utf-8")) == {
        "method": "GroupApi.getGroupMemberAll",
        "params": ["fictional-group"],
        "boot_id": "b" * 64,
    }


def test_acquire_timeout_covers_sequential_passphrase_and_identity_waits(tmp_path: Path) -> None:
    transport = _FakeTransport(body=_envelope(_acquire_result("gen-late")))
    original_transport = transport.__call__

    def delayed_runtime(url: str, body: bytes, timeout: float) -> tuple[int, str]:
        # The helper may wait 30 s for a passphrase and then 30 s for identity.
        if timeout <= 60:
            raise TimeoutError()
        return original_transport(url, body, timeout)

    client = _client(delayed_runtime, root=tmp_path)

    assert client.acquire() == "gen-late"
    assert transport.calls[0][2] > 60


def test_acquire_runtime_failure_maps_to_stable_error(tmp_path: Path) -> None:
    transport = _FakeTransport(body=_envelope(_acquire_result("", ok=False)))
    client = _client(transport, root=tmp_path)

    with pytest.raises(QQSnapshotRuntimeFailure):
        client.acquire()


def test_acquire_retries_snapshot_unstable_then_succeeds_serially(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    delays: list[float] = []
    monkeypatch.setattr(snapshot_runtime.time, "sleep", delays.append)
    transport = _SequenceTransport([
        {"ok": False, "code": "snapshot_unstable", "status": "failed"},
        _acquire_result("gen-retried"),
    ])

    with caplog.at_level("INFO", logger="qq_chat_analyzer.desktop.qq_direct_snapshot"):
        assert _client(transport, root=tmp_path).acquire() == "gen-retried"

    assert transport.calls == 2
    assert transport.max_active == 1
    assert len(delays) == 1 and 0 < delays[0] <= 1
    assert "attempt=1 max_attempts=6 failure_code=snapshot_unstable" in caplog.text


def test_acquire_outlasts_a_write_burst_that_exceeds_the_first_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capture fails closed while the source is written; that is transient.

    Every attempt re-reads the whole source, so on a large database a few
    attempts can expire before QQ's post-login write burst ends. The retry
    budget must cover that burst instead of reporting a permanent failure.
    """
    delays: list[float] = []
    monkeypatch.setattr(snapshot_runtime.time, "sleep", delays.append)
    transport = _SequenceTransport([
        {"ok": False, "code": "snapshot_unstable", "status": "failed"}
        for _ in range(4)
    ] + [_acquire_result("gen-after-burst")])

    assert _client(transport, root=tmp_path).acquire() == "gen-after-burst"
    assert transport.calls == 5
    assert transport.max_active == 1
    assert len(delays) == 4


def test_acquire_stops_after_the_attempt_budget_is_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    monkeypatch.setattr(snapshot_runtime.time, "sleep", delays.append)
    transport = _SequenceTransport([
        {"ok": False, "code": "snapshot_unstable", "status": "failed"}
        for _ in range(6)
    ])

    with pytest.raises(QQSnapshotRuntimeFailure) as captured:
        _client(transport, root=tmp_path).acquire()

    assert captured.value.code == "qq_snapshot_runtime_failure"
    assert captured.value.public_message == QQSnapshotRuntimeFailure.public_message
    assert transport.calls == 6
    assert transport.max_active == 1
    assert len(delays) == 5 and all(0 < delay <= 1 for delay in delays)


@pytest.mark.parametrize("failure_code", ["decrypt_failed", "identity_missing"])
def test_acquire_does_not_retry_other_runtime_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_code: str,
) -> None:
    delays: list[float] = []
    monkeypatch.setattr(snapshot_runtime.time, "sleep", delays.append)
    transport = _SequenceTransport([
        {"ok": False, "code": failure_code, "status": "failed"},
        _acquire_result("must-not-be-used"),
    ])

    with pytest.raises(QQSnapshotRuntimeFailure):
        _client(transport, root=tmp_path).acquire()

    assert transport.calls == 1
    assert delays == []


def test_acquire_does_not_retry_unstable_code_without_failed_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    monkeypatch.setattr(snapshot_runtime.time, "sleep", delays.append)
    transport = _SequenceTransport([
        {"ok": False, "code": "snapshot_unstable", "status": "unknown"},
        _acquire_result("must-not-be-used"),
    ])

    with pytest.raises(QQSnapshotRuntimeFailure):
        _client(transport, root=tmp_path).acquire()

    assert transport.calls == 1
    assert delays == []


def test_acquire_stops_when_retry_returns_non_transient_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []
    monkeypatch.setattr(snapshot_runtime.time, "sleep", delays.append)
    transport = _SequenceTransport([
        {"ok": False, "code": "snapshot_unstable", "status": "failed"},
        {"ok": False, "code": "decrypt_failed", "status": "failed"},
        _acquire_result("must-not-be-used"),
    ])

    with pytest.raises(QQSnapshotRuntimeFailure):
        _client(transport, root=tmp_path).acquire()

    assert transport.calls == 2
    assert len(delays) == 1


@pytest.mark.parametrize(
    "failure_code",
    [
        "cleanup_failed",
        "passphrase_unavailable",
        "identity_missing",
        "decrypt_failed",
        "snapshot_unstable",
        "identity_changed",
        "manifest_failed",
        "publish_failed",
    ],
)
def test_acquire_logs_only_known_anonymous_failure_code(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    failure_code: str,
) -> None:
    transport = _FakeTransport(body=_envelope({
        "ok": False, "code": failure_code, "status": "failed",
        "message": "fictional private message /fictional/path",
    }))
    client = _client(transport, root=tmp_path)

    with caplog.at_level("INFO", logger="qq_chat_analyzer.desktop.qq_direct_snapshot"):
        with pytest.raises(QQSnapshotRuntimeFailure) as captured:
            client.acquire()

    assert captured.value.code == "qq_snapshot_runtime_failure"
    assert f"failure_code={failure_code}" in caplog.text
    assert "fictional private message" not in caplog.text
    assert "/fictional/path" not in caplog.text


def test_acquire_unknown_failure_code_does_not_leak_payload(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = _FakeTransport(body=_envelope({
        "ok": False,
        "code": "private-code-987654 /fictional/path",
        "status": "failed",
        "message": "fictional private message",
    }))
    client = _client(transport, root=tmp_path)

    with caplog.at_level("INFO", logger="qq_chat_analyzer.desktop.qq_direct_snapshot"):
        with pytest.raises(QQSnapshotRuntimeFailure) as captured:
            client.acquire()

    assert captured.value.code == "qq_snapshot_runtime_failure"
    assert "failure_code=" not in caplog.text
    assert "private-code-987654" not in caplog.text
    assert "/fictional/path" not in caplog.text
    assert "fictional private message" not in caplog.text


def test_acquire_rpc_envelope_failure_maps_to_stable_error(tmp_path: Path) -> None:
    transport = _FakeTransport(body=_rpc_error("fictional boom"))
    client = _client(transport, root=tmp_path)

    with pytest.raises(QQSnapshotRuntimeFailure):
        client.acquire()


def test_acquire_malformed_response_maps_to_invalid_response(tmp_path: Path) -> None:
    transport = _FakeTransport(body="not json at all")
    client = _client(transport, root=tmp_path)

    with pytest.raises(QQSnapshotRuntimeInvalidResponse):
        client.acquire()


def test_acquire_http_error_maps_to_invalid_response(tmp_path: Path) -> None:
    transport = _FakeTransport(status=404, body="")
    client = _client(transport, root=tmp_path)

    with pytest.raises(QQSnapshotRuntimeInvalidResponse):
        client.acquire()


def test_acquire_connection_refused_maps_to_unavailable(tmp_path: Path) -> None:
    transport = _FakeTransport(error=ConnectionRefusedError("refused"))
    client = _client(transport, root=tmp_path)

    with pytest.raises(QQSnapshotRuntimeUnavailable):
        client.acquire()


def test_acquire_timeout_maps_to_unavailable(tmp_path: Path, caplog) -> None:
    transport = _FakeTransport(error=TimeoutError("timed out"))
    client = _client(transport, root=tmp_path)

    with caplog.at_level("INFO", logger="qq_chat_analyzer.desktop.qq_direct_snapshot"):
        with pytest.raises(QQSnapshotRuntimeUnavailable):
            client.acquire()

    assert "QQ snapshot acquire RPC started timeout=65.0s" in caplog.text
    assert "outcome=QQSnapshotRuntimeUnavailable" in caplog.text
    assert "timed out" not in caplog.text


def test_acquire_rejects_non_ready_status(tmp_path: Path) -> None:
    transport = _FakeTransport(body=_envelope(_acquire_result("gen-1", status="building")))
    client = _client(transport, root=tmp_path)

    with pytest.raises(QQSnapshotRuntimeFailure):
        client.acquire()


# ------------------------------------------------------- generation id safety


@pytest.mark.parametrize(
    "generation_id",
    ["", "   ", ".", "..", "../evil", "a/b", "a\\b", "gen\x00sneaky", 123, None, True],
)
def test_generation_id_traversal_or_invalid_is_rejected(generation_id) -> None:
    with pytest.raises(QQSnapshotInvalidGenerationId):
        validate_generation_id(generation_id)


def test_generation_id_is_normalized(tmp_path: Path) -> None:
    assert validate_generation_id("  gen-1  ") == "gen-1"


def test_generation_directory_rejects_traversal(tmp_path: Path) -> None:
    client = _client(_FakeTransport(), root=tmp_path)

    with pytest.raises(QQSnapshotInvalidGenerationId):
        client.generation_directory("../evil")


def test_generation_directory_is_under_known_root(tmp_path: Path) -> None:
    client = _client(_FakeTransport(), root=tmp_path)

    assert client.generation_directory("gen-7") == tmp_path / "generations" / "gen-7"


def test_acquire_rejects_traversal_generation_id_from_runtime(tmp_path: Path) -> None:
    transport = _FakeTransport(body=_envelope(_acquire_result("../evil")))
    client = _client(transport, root=tmp_path)

    with pytest.raises(QQSnapshotInvalidGenerationId):
        client.acquire()


# ------------------------------------------------------------------ cleanup


def test_cleanup_invokes_rpc_with_generation_id(tmp_path: Path) -> None:
    transport = _FakeTransport(body=_envelope({"ok": True, "status": "cleaned"}))
    client = _client(transport, root=tmp_path)

    assert client.cleanup("gen-1") is None
    request = json.loads(transport.calls[0][1].decode("utf-8"))
    assert request == {"method": "EchoSnapshotApi.cleanup", "params": ["gen-1"], "boot_id": "b" * 64}


def test_cleanup_generation_not_found_is_idempotent(tmp_path: Path) -> None:
    transport = _FakeTransport(
        body=_envelope({"ok": False, "code": "generation_not_found", "status": "failed"})
    )
    client = _client(transport, root=tmp_path)

    assert client.cleanup("gen-1") is None


def test_cleanup_failure_maps_to_stable_error(tmp_path: Path) -> None:
    transport = _FakeTransport(
        body=_envelope({"ok": False, "code": "cleanup_failed", "status": "failed"})
    )
    client = _client(transport, root=tmp_path)

    with pytest.raises(QQSnapshotCleanupFailed):
        client.cleanup("gen-1")


def test_cleanup_rejects_traversal_before_rpc(tmp_path: Path) -> None:
    transport = _FakeTransport(body=_envelope({"ok": True, "status": "cleaned"}))
    client = _client(transport, root=tmp_path)

    with pytest.raises(QQSnapshotInvalidGenerationId):
        client.cleanup("../evil")
    assert transport.calls == []


# ------------------------------------------------------------------ recover


def test_recover_invokes_rpc(tmp_path: Path) -> None:
    transport = _FakeTransport(body=_envelope({"ok": True, "status": "recovered"}))
    client = _client(transport, root=tmp_path)

    assert client.recover() is None
    request = json.loads(transport.calls[0][1].decode("utf-8"))
    assert request == {"method": "EchoSnapshotApi.recover", "params": [], "boot_id": "b" * 64}


def test_recover_waits_until_echo_snapshot_api_is_registered(tmp_path: Path) -> None:
    responses = iter(
        (
            _rpc_error("NapCatCore method not found: EchoSnapshotApi.recover"),
            _envelope({"ok": True, "status": "recovered"}),
        )
    )

    def transport(url: str, body: bytes, timeout: int) -> tuple[int, str]:
        return 200, next(responses)

    client = _client(transport, root=tmp_path)

    assert client.recover() is None


def test_recover_api_readiness_wait_is_bounded(monkeypatch, tmp_path: Path) -> None:
    transport = _FakeTransport(
        body=_rpc_error("NapCatCore method not found: EchoSnapshotApi.recover")
    )
    monkeypatch.setattr(snapshot_runtime, "RECOVER_READINESS_ATTEMPTS", 3)
    monkeypatch.setattr(snapshot_runtime.time, "sleep", lambda _seconds: None)
    client = _client(transport, root=tmp_path)

    with pytest.raises(QQSnapshotRuntimeNotReady):
        client.recover()

    assert len(transport.calls) == 3


def test_recover_does_not_retry_other_rpc_failures(
    monkeypatch,
    tmp_path: Path,
) -> None:
    transport = _FakeTransport(body=_rpc_error("fictional runtime failure"))
    monkeypatch.setattr(snapshot_runtime.time, "sleep", lambda _seconds: None)
    client = _client(transport, root=tmp_path)

    with pytest.raises(QQSnapshotRuntimeFailure):
        client.recover()

    assert len(transport.calls) == 1


def test_shutdown_recover_uses_remaining_deadline_for_one_rpc(monkeypatch, tmp_path: Path) -> None:
    now = [100.0]
    monkeypatch.setattr(snapshot_runtime.time, "monotonic", lambda: now[0])
    transport = _FakeTransport(
        body=_rpc_error("NapCatCore method not found: EchoSnapshotApi.recover")
    )
    client = QQDirectSnapshotRuntimeClient(
        "http://127.0.0.1:40654", snapshot_root=tmp_path,
        timeout=30, transport=transport,
        boot_id="b" * 64,
    )

    with pytest.raises(QQSnapshotRuntimeNotReady):
        client.recover(deadline=105.1)

    assert len(transport.calls) == 1
    assert transport.calls[0][2] == pytest.approx(5.1)


def test_shutdown_recover_does_not_rpc_after_deadline(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(snapshot_runtime.time, "monotonic", lambda: 106.0)
    transport = _FakeTransport(body=_envelope({"ok": True}))
    client = _client(transport, root=tmp_path)

    with pytest.raises(QQSnapshotRuntimeUnavailable):
        client.recover(deadline=105.1)

    assert transport.calls == []


def test_shutdown_recover_caps_timeout_at_configured_rpc_timeout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(snapshot_runtime.time, "monotonic", lambda: 100.0)
    transport = _FakeTransport(body=_envelope({"ok": True}))
    client = QQDirectSnapshotRuntimeClient(
        "http://127.0.0.1:40654", snapshot_root=tmp_path,
        timeout=2, transport=transport,
        boot_id="b" * 64,
    )

    client.recover(deadline=105.1)

    assert transport.calls[0][2] == 2


def test_shutdown_recover_rejects_response_after_total_deadline(monkeypatch, tmp_path: Path) -> None:
    now = [100.0]
    monkeypatch.setattr(snapshot_runtime.time, "monotonic", lambda: now[0])

    def delayed_transport(url: str, body: bytes, timeout: float) -> tuple[int, str]:
        now[0] = 106.0
        return 200, _envelope({"ok": True})

    client = QQDirectSnapshotRuntimeClient(
        "http://127.0.0.1:40654", snapshot_root=tmp_path,
        timeout=30, transport=delayed_transport,
        boot_id="b" * 64,
    )

    with pytest.raises(QQSnapshotRuntimeUnavailable):
        client.recover(deadline=105.1)


# ------------------------------------------------------------ privacy guards


def test_client_errors_never_embed_runtime_or_identity_text(tmp_path: Path) -> None:
    secret = "10086"
    transport = _FakeTransport(body=_rpc_error(f"boom {secret} /abs/path passphrase"))
    client = _client(transport, root=tmp_path)

    with pytest.raises(QQSnapshotRuntimeFailure) as captured:
        client.acquire()

    assert secret not in str(captured.value)
    assert secret not in captured.value.public_message
    assert "/abs/path" not in str(captured.value)
    assert "passphrase" not in str(captured.value)


def test_urllib_transport_rejects_non_localhost() -> None:
    with pytest.raises(QQSnapshotRuntimeUnavailable):
        _urllib_transport("http://evil.example/rpc", b"{}", 1)
