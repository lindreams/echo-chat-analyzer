"""Application generation boundaries, using only fictional transports."""
import json
from types import SimpleNamespace

import pytest

from qq_chat_analyzer.application.qq.qq_provider_factory import QQProviderFactory
from qq_chat_analyzer.application.qq.qq_connection_service import QQConnectionService
from qq_chat_analyzer.application.qq.qq_connection_manager import QQConnectionManager
from qq_chat_analyzer.application.qq.qq_direct_database_import_service import QQDirectDatabaseImportService
from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, ChatSource
from qq_chat_analyzer.providers.napcat_qq_provider import NapCatQQProvider
from qq_chat_analyzer.application.errors import ApplicationServiceError
from test_qq_worker_generation import Worker


def connection(tmp_path, monkeypatch):
    worker = Worker()
    original = worker.transport
    def transport(url, body, timeout):
        status, text = original(url, body, timeout)
        value = json.loads(text)
        if status == 200 and json.loads(body)["method"] == "Core.status":
            value["result"]["self_info"] = {"uin": "12345678"}
        return status, json.dumps(value)
    from qq_chat_analyzer.providers import qq_direct_snapshot_runtime as runtime
    monkeypatch.setattr(runtime, "_urllib_transport", lambda url, body, timeout, **kwargs: transport(url, body, timeout))
    credential = SimpleNamespace(credential=lambda: "c" * 64)
    config = SimpleNamespace(napcat_bridge_url="http://127.0.0.1:40655", runtime_mode="custom")
    loader = SimpleNamespace(load_or_default=lambda: config,
                             runtime_paths=lambda: SimpleNamespace(snapshot_root=tmp_path))
    factory = QQProviderFactory(config_loader=loader, bridge_credential=credential,
        provider_builder=lambda config, **kwargs: NapCatQQProvider(config.napcat_bridge_url,
                                                                 transport=transport, **kwargs))
    service = QQDirectDatabaseImportService(config_loader=loader, provider_factory=factory,
                                          bridge_credential=credential)
    return worker, factory, service


def test_snapshot_binding_is_cached_per_application_connection(tmp_path, monkeypatch):
    worker, factory, service = connection(tmp_path, monkeypatch)
    assert service._require_runtime_client() is service._require_runtime_client()


@pytest.mark.parametrize("fault,stage,category,public_code", [
    ("auth", "provider_status", "auth_rejected", "qq_direct_database_recovery_failed"),
    ("unavailable", "provider_status", "provider_error", "qq_direct_database_not_ready"),
    ("generation", "provider_status", "worker_generation_changed", "qq_reconnect_required"),
    ("identity", "provider_status", "runtime_identity_mismatch", "qq_direct_database_unavailable"),
    ("builder", "snapshot_client", "invalid_response", "qq_snapshot_runtime_invalid_response"),
    ("recover", "startup_recover", "operation_failed", "qq_direct_database_recovery_failed"),
])
def test_startup_diagnostics_preserve_mapping_and_identify_phase(tmp_path, monkeypatch, caplog, fault, stage, category, public_code):
    import time
    from qq_chat_analyzer.providers.napcat_qq_provider import NapCatQQAuthRejected, NapCatQQError, NapCatQQWorkerGenerationChanged
    from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import QQSnapshotRuntimeFailure, QQSnapshotRuntimeInvalidResponse
    worker, factory, service = connection(tmp_path, monkeypatch)
    provider = factory.create()
    private = "fictional-secret account=12345678 C:/private/qq"
    if fault in {"auth", "unavailable", "generation"}:
        error = {"auth": NapCatQQAuthRejected, "unavailable": NapCatQQError, "generation": NapCatQQWorkerGenerationChanged}[fault]()
        error.args = (private,)
        def status(**kwargs):
            raise error
        monkeypatch.setattr(provider, "status", status)
    elif fault == "identity":
        monkeypatch.setattr(provider, "status", lambda **kw: SimpleNamespace(runtime_id="a" * 64))
    elif fault == "builder":
        def builder(root):
            raise QQSnapshotRuntimeInvalidResponse(private, code=private)
        monkeypatch.setattr(provider, "snapshot_client", builder)
    else:
        def recover(**kw):
            raise QQSnapshotRuntimeFailure(private, code=private)
        monkeypatch.setattr(provider, "snapshot_client", lambda root: SimpleNamespace(recover=recover))
    caplog.set_level("INFO")
    with pytest.raises(Exception) as result:
        if fault == "unavailable":
            service._require_runtime_client(deadline=time.monotonic() + 5)
        else:
            service.start()
    if fault != "builder":
        assert result.value.code == public_code
    else:
        assert isinstance(result.value, QQSnapshotRuntimeInvalidResponse)
    assert f"stage={stage} outcome=failed failure_code={category}" in caplog.text
    assert "stage=provider_status outcome=started" in caplog.text
    if fault in {"builder", "recover"}:
        assert "stage=provider_status outcome=success" in caplog.text
    if fault == "recover":
        assert "stage=snapshot_client outcome=success" in caplog.text
        assert "stage=startup_recover outcome=started" in caplog.text
    for value in (private, "12345678", "C:/private", str(tmp_path), "a" * 64, "c" * 64):
        assert value not in caplog.text


def test_session_failure_diagnostics_connect_service_and_recover_rpc(tmp_path, monkeypatch, caplog):
    worker, factory, service = connection(tmp_path, monkeypatch)
    provider = factory.create()
    original = provider._transport
    def transport(url, body, timeout):
        if json.loads(body)["method"] == "EchoSnapshotApi.recover":
            return 200, json.dumps({"ok": True, "result": {"ok": False, "code": "recover_failed",
                "private": "fictional-secret account=12345678 C:/private/qq"}})
        return original(url, body, timeout)
    monkeypatch.setattr(provider, "_transport", transport)
    caplog.set_level("INFO")
    with pytest.raises(ApplicationServiceError) as error:
        service.list_sessions()
    assert error.value.code == "qq_direct_database_recovery_failed"
    assert "stage=provider_status outcome=success" in caplog.text
    assert "stage=snapshot_client outcome=success" in caplog.text
    assert "stage=startup_recover outcome=failed failure_code=operation_failed" in caplog.text
    assert "stage=recover_rpc outcome=failed failure_code=recover_failed" in caplog.text
    assert "http_status=200" in caplog.text
    assert not any(call["method"] == "EchoSnapshotApi.acquire" for call in worker.operations)
    for value in ("fictional-secret", "12345678", "C:/private", str(tmp_path), "c" * 64):
        assert value not in caplog.text


def test_generation_error_latches_shared_connection_until_explicit_reconnect(tmp_path, monkeypatch):
    worker, factory, service = connection(tmp_path, monkeypatch)
    service.start()
    old_provider = factory.create()
    old_client = service._require_runtime_client()
    worker.boot = "d" * 64
    worker.operations.clear()
    with pytest.raises(ApplicationServiceError) as error:
        service.list_sessions()
    assert error.value.code == "qq_reconnect_required"
    calls = len(worker.calls)
    factory.invalidate()  # Routine config invalidation cannot bypass the latch.
    with pytest.raises(ApplicationServiceError):
        service.list_sessions()
    status = QQConnectionManager(connection_service=QQConnectionService(provider_factory=factory)).get_snapshot()
    assert status.code == "qq_reconnect_required" and not status.connected
    assert "重新连接" in status.message
    assert len(worker.calls) == calls and worker.operations == []
    service.prepare_reconnect()
    factory.reconnect()
    service.start()
    assert factory.create() is not old_provider
    assert service._require_runtime_client() is not old_client
    assert worker.operations[0]["method"] == "EchoSnapshotApi.recover"
    assert worker.operations[0]["boot_id"] == "d" * 64
    with pytest.raises(Exception) as old_error:
        old_client.recover()
    assert old_error.value.code == "qq_snapshot_worker_generation_changed"


def test_reconnect_refuses_inflight_acquisition_without_replacing_binding(tmp_path, monkeypatch):
    worker, factory, service = connection(tmp_path, monkeypatch)
    service._begin_acquisition()
    old = service._require_runtime_client()
    try:
        with pytest.raises(ApplicationServiceError):
            service.prepare_reconnect()
        assert service._require_runtime_client() is old
    finally:
        service._end_acquisition()
    service.prepare_reconnect()


def test_facade_explicit_connect_prepares_data_and_resets_binding_before_auth():
    calls = []
    service = SimpleNamespace(prepare_reconnect=lambda: calls.append("drain/reset data"))
    connection_service = SimpleNamespace(reconnect=lambda: calls.append("reset provider"))
    auth = SimpleNamespace(start_auth_flow=lambda **kwargs: calls.append("auth"))
    facade = ChatAnalyzerFacade(qq_service=service, qq_connection_service=connection_service, qq_auth_bridge=auth)
    facade.start_qq_auth_flow()
    assert calls == ["drain/reset data", "reset provider", "auth"]


def test_member_generation_failure_is_not_optional_metadata(tmp_path):
    from qq_chat_analyzer.application.qq.qq_direct_database_import_service import _group_sender_names_with_diagnostics
    from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import QQSnapshotWorkerGenerationChanged
    def members(group):
        raise QQSnapshotWorkerGenerationChanged()
    with pytest.raises(QQSnapshotWorkerGenerationChanged):
        _group_sender_names_with_diagnostics(SimpleNamespace(get_group_member_all=members),
                                             SimpleNamespace(session_object="12345678"), tmp_path / "payload.json")


def test_old_status_failure_cannot_invalidate_explicit_new_connection(tmp_path, monkeypatch):
    from qq_chat_analyzer.providers.napcat_qq_provider import NapCatQQWorkerGenerationChanged
    worker, factory, service = connection(tmp_path, monkeypatch)
    old = factory.create()
    fresh = []
    def delayed_failure():
        factory.reconnect()  # Simulate the user reconnecting while an old probe is running.
        fresh.append(factory.create())
        raise NapCatQQWorkerGenerationChanged()
    monkeypatch.setattr(old, "status", delayed_failure)
    QQConnectionService(provider_factory=factory).check_status()
    assert factory.create() is fresh[0]


def test_initial_provider_unavailability_keeps_startup_readiness_retry(tmp_path, monkeypatch):
    from qq_chat_analyzer.providers.napcat_qq_provider import NapCatQQError
    worker, factory, service = connection(tmp_path, monkeypatch)
    provider = factory.create()
    original = provider.status
    attempts = []
    def delayed(**kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise NapCatQQError()
        return original(**kwargs)
    monkeypatch.setattr(provider, "status", delayed)
    service.start()
    assert len(attempts) == 2
    assert worker.operations[0]["method"] == "EchoSnapshotApi.recover"


def test_new_connection_recovery_failure_never_allows_acquire(tmp_path, monkeypatch):
    from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import QQSnapshotRuntimeFailure
    worker, factory, service = connection(tmp_path, monkeypatch)
    service.start()
    service.prepare_reconnect()
    factory.reconnect()
    client = service._require_runtime_client()
    def failed(**kwargs):
        raise QQSnapshotRuntimeFailure()
    monkeypatch.setattr(client, "recover", failed)
    worker.operations.clear()
    with pytest.raises(ApplicationServiceError):
        service.start()
    with pytest.raises(ApplicationServiceError):
        service.list_sessions()
    assert worker.operations == []
    assert service._require_runtime_client() is client
