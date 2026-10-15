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
