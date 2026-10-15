"""Credential plumbing of the two local bridge RPC clients, over real HTTP.

A recording loopback server stands in for the NapCat bridge, so these tests
observe exactly what leaves the process: which requests are sent at all, and
which headers they carry.  Fictional values only; nothing is persisted.
"""
from __future__ import annotations

import json
import re
import threading
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from qq_chat_analyzer.application.qq.qq_runtime_session import QQRuntimeSession
from qq_chat_analyzer.providers import napcat_qq_provider as provider_module
from qq_chat_analyzer.providers import qq_direct_snapshot_runtime as snapshot_module

STATUS_RESULT = {
    "boot_id": "b" * 64,
    "bridge_ready": True,
    "qq_online": True,
    "self_info": {"uin": "", "uid": "", "nickname": ""},
    "database_api_ready": True,
    "passphrase_ready": True,
    "snapshot_api_ready": True,
}
RECOVERED_RESULT = {"ok": True, "status": "recovered"}
ACQUIRED_RESULT = {"ok": True, "status": "ready", "generation_id": "fictional-generation"}


class _Recorder:
    """Collect the requests a client actually sends."""

    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.status = 200
        self.result: object = []
        self.auth_capability = True
        self.redirect: str | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_Recorder":
        recorder = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                recorder.requests.append({"path": self.path,
                                          "authorization": self.headers.get("authorization"), "body": b""})
                self.send_response(200)
                self.send_header("content-length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
                length = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(length) if length else b""
                recorder.requests.append(
                    {
                        "path": self.path,
                        "authorization": self.headers.get("authorization"),
                        "body": body,
                    }
                )
                if recorder.redirect:
                    self.send_response(302)
                    self.send_header("location", recorder.redirect)
                    self.send_header("content-length", "0")
                    self.end_headers()
                    return
                result = recorder.result
                if json.loads(body)["method"] == "Core.status" and recorder.auth_capability:
                    result = {**STATUS_RESULT, "rpc_auth": "bearer-v1"}
                    if self.path != "/rpc":
                        result["runtime_id"] = self.path.rsplit("/", 1)[-1]
                encoded = json.dumps({"ok": True, "result": result}).encode("utf-8")
                self.send_response(recorder.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *args: object) -> None:  # keep the suite quiet
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def paths(self) -> list[object]:
        return [request["path"] for request in self.requests]

    def authorizations(self) -> list[object]:
        return [request["authorization"] for request in self.requests]

    def methods(self) -> list[object]:
        return [
            json.loads(request["body"].decode("utf-8"))["method"]  # type: ignore[union-attr]
            for request in self.requests
        ]


def _session() -> tuple[QQRuntimeSession, str]:
    """A real session plus its current credential (fictional, in memory)."""
    session = QQRuntimeSession()
    return session, session.begin_launch()


def _snapshot_client(recorder: _Recorder, **kwargs: object):
    return snapshot_module.QQDirectSnapshotRuntimeClient(
        recorder.base_url, snapshot_root=Path("fictional-root"), timeout=5, **kwargs
    )


# ------------------------------------------------------------------ provider


def test_provider_authenticates_every_request_it_sends():
    session, token = _session()
    with _Recorder() as recorder:
        recorder.result = STATUS_RESULT
        provider = provider_module.NapCatQQProvider(recorder.base_url, credential=session)
        provider.status()
        recorder.result = []
        provider.list_friends()
        provider.list_groups()
    assert recorder.paths() == ["/rpc", "/rpc", "/rpc"]
    assert recorder.authorizations() == [f"Bearer {token}"] * 3
    assert recorder.methods() == [
        "Core.status",
        "EchoMetadata.listFriends",
        "EchoMetadata.listGroups",
    ]


def test_bound_provider_cannot_adopt_a_new_launch_credential():
    """D1 requires explicit new binding after a launch change."""
    session, first = _session()
    with _Recorder() as recorder:
        recorder.result = STATUS_RESULT
        provider = provider_module.NapCatQQProvider(recorder.base_url, credential=session)
        provider.status()
        second = session.begin_launch()
        with pytest.raises(provider_module.NapCatQQWorkerGenerationChanged):
            provider.status()
        provider_module.NapCatQQProvider(recorder.base_url, credential=session).status()
    assert second != first
    assert recorder.authorizations() == [f"Bearer {first}", f"Bearer {second}"]


def test_provider_without_a_credential_never_sends_a_request():
    with _Recorder() as recorder:
        provider = provider_module.NapCatQQProvider(recorder.base_url)
        with pytest.raises(provider_module.NapCatQQError):
            provider.status()
    assert recorder.requests == []


def test_provider_with_a_retired_credential_never_sends_a_request():
    session, token = _session()
    session.retire(token)
    with _Recorder() as recorder:
        provider = provider_module.NapCatQQProvider(recorder.base_url, credential=session)
        with pytest.raises(provider_module.NapCatQQError):
            provider.list_friends()
    assert recorder.requests == []


def test_provider_maps_unauthorized_to_its_own_error_type_and_does_not_retry():
    session, token = _session()
    with _Recorder() as recorder:
        recorder.status = 401
        provider = provider_module.NapCatQQProvider(recorder.base_url, credential=session)
        with pytest.raises(provider_module.NapCatQQAuthRejected) as error:
            provider.status()
    assert error.value.code == "napcat_qq_auth_rejected"
    assert token not in str(error.value)
    assert recorder.base_url not in str(error.value)
    # No retry, no fallback to an unauthenticated request.
    assert len(recorder.requests) == 1


# ------------------------------------------------------------- snapshot client


def test_snapshot_client_authenticates_every_request_it_sends():
    session, token = _session()
    with _Recorder() as recorder:
        recorder.result = RECOVERED_RESULT
        client = _snapshot_client(recorder, credential=session)
        client.recover()
        client.cleanup("fictional-generation")
    assert recorder.paths() == ["/rpc", "/rpc", "/rpc"]
    assert recorder.authorizations() == [f"Bearer {token}"] * 3
    assert recorder.methods() == ["Core.status", "EchoSnapshotApi.recover", "EchoSnapshotApi.cleanup"]


def test_snapshot_client_without_a_credential_never_sends_a_request():
    with _Recorder() as recorder:
        client = _snapshot_client(recorder)
        with pytest.raises(snapshot_module.QQSnapshotRuntimeError):
            client.recover()
    assert recorder.requests == []


def test_snapshot_client_keeps_the_managed_route_and_authentication_together():
    runtime_id = "a" * 64
    session, token = _session()
    with _Recorder() as recorder:
        recorder.result = ACQUIRED_RESULT
        client = _snapshot_client(recorder, credential=session, runtime_id=runtime_id)
        client.acquire()
    assert recorder.paths() == [f"/rpc/{runtime_id}"] * 2
    assert recorder.authorizations() == [f"Bearer {token}"] * 2


def test_credential_values_are_never_part_of_a_public_message():
    session, token = _session()
    with _Recorder() as recorder:
        recorder.status = 401
        provider = provider_module.NapCatQQProvider(recorder.base_url, credential=session)
        with pytest.raises(provider_module.NapCatQQError) as error:
            provider.status()
    message = getattr(error.value, "public_message", "")
    assert token not in message
    assert not re.search(r"[0-9a-f]{32,}", message)
    assert recorder.base_url not in message


@pytest.mark.parametrize("via_provider", [False, True])
def test_old_snapshot_client_cannot_mutate_a_relaunched_runtime(via_provider):
    session, first = _session()
    with _Recorder() as recorder:
        recorder.result = RECOVERED_RESULT
        client = (provider_module.NapCatQQProvider(recorder.base_url, credential=session)
                  .snapshot_client(Path("fictional-root")) if via_provider
                  else _snapshot_client(recorder, credential=session, runtime_id="a" * 64))
        session.begin_launch()
        with pytest.raises(snapshot_module.QQSnapshotRuntimeError):
            client.cleanup("old-generation")
    assert recorder.requests == []


def test_snapshot_client_created_without_a_live_launch_cannot_adopt_a_future_one():
    session = QQRuntimeSession()
    with _Recorder() as recorder:
        client = _snapshot_client(recorder, credential=session, runtime_id="a" * 64)
        session.begin_launch()
        with pytest.raises(snapshot_module.QQSnapshotRuntimeUnavailable):
            client.recover()
    assert recorder.requests == []


def test_snapshot_transport_rejects_localhost_prefix_impersonation(monkeypatch):
    monkeypatch.setattr(snapshot_module.urllib.request, "urlopen",
                        lambda *a, **kw: pytest.fail("non-loopback request escaped"))
    with pytest.raises(snapshot_module.QQSnapshotRuntimeUnavailable):
        snapshot_module._urllib_transport("http://localhost.invalid:80/rpc", b"{}", 1,
                                         credential="a" * 64)


def test_old_custom_plugin_is_not_accepted_as_authenticated():
    session, _ = _session()
    with _Recorder() as recorder:
        recorder.auth_capability = False
        recorder.result = STATUS_RESULT  # Legacy status has no auth capability.
        provider = provider_module.NapCatQQProvider(recorder.base_url, credential=session)
        with pytest.raises(provider_module.NapCatQQAuthRejected):
            provider.status()


def test_old_custom_snapshot_plugin_cannot_run_mutating_rpc():
    session, _ = _session()
    with _Recorder() as recorder:
        recorder.auth_capability = False
        recorder.result = STATUS_RESULT
        client = _snapshot_client(recorder, credential=session)
        with pytest.raises(snapshot_module.QQSnapshotRuntimeUnauthorized):
            client.recover()
    assert recorder.methods() == ["Core.status"]


def test_snapshot_transport_never_forwards_credentials_on_redirect():
    session, _ = _session()
    with _Recorder() as source, _Recorder() as target:
        source.redirect = target.base_url + "/rpc"
        client = _snapshot_client(source, credential=session, runtime_id="a" * 64)
        with pytest.raises(snapshot_module.QQSnapshotRuntimeError):
            client.recover()
    assert target.requests == []


def test_shutdown_drain_cannot_recover_a_new_runtime(monkeypatch, tmp_path):
    from qq_chat_analyzer.application.qq.qq_direct_database_import_service import (
        QQDirectDatabaseImportService, QQDirectDatabaseRecoveryFailed,
    )
    session, _ = _session()
    with _Recorder() as recorder:
        recorder.result = RECOVERED_RESULT
        loader = SimpleNamespace(
            load_or_default=lambda: SimpleNamespace(napcat_bridge_url=recorder.base_url, runtime_mode="custom"),
            runtime_paths=lambda: SimpleNamespace(snapshot_root=tmp_path),
        )
        service = QQDirectDatabaseImportService(config_loader=loader, bridge_credential=session)
        service.start()
        recorder.requests.clear()
        def drain():
            session.begin_launch()
            return True
        monkeypatch.setattr(service, "_drain_acquisitions", drain)
        with pytest.raises(QQDirectDatabaseRecoveryFailed):
            service.shutdown()
    assert recorder.requests == []


@pytest.mark.parametrize("token", ["fictional-secret\n", "a" * 63, "a" * 64 + "\n"])
def test_malformed_credential_is_refused_locally(token):
    source = SimpleNamespace(credential=lambda: token)
    with _Recorder() as recorder:
        client = _snapshot_client(recorder, credential=source, runtime_id="a" * 64)
        with pytest.raises(snapshot_module.QQSnapshotRuntimeUnavailable) as error:
            client.recover()
        assert token not in str(error.value)
    assert recorder.requests == []
