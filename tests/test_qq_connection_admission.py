"""F regressions: fictional workers and deterministic connection interleavings."""
import threading
from types import SimpleNamespace

import pytest

from qq_chat_analyzer.application.errors import ApplicationServiceError
from qq_chat_analyzer.application.shutdown_models import ShutdownStatus
from qq_chat_analyzer.application.qq.qq_connection_service import QQConnectionService
from qq_chat_analyzer.application.qq.qq_direct_database_import_service import (
    QQDirectDatabaseImportService, QQDirectDatabaseState,
)
from qq_chat_analyzer.providers.napcat_qq_provider import NapCatQQWorkerGenerationChanged
from test_qq_explicit_reconnect import connection


@pytest.mark.parametrize("operation", ["list", "session"])
def test_readiness_gap_never_admits_old_request_to_reconnected_worker(tmp_path, monkeypatch, operation):
    worker, factory, service = connection(tmp_path, monkeypatch)
    service.start()
    checked, resume = threading.Event(), threading.Event()
    ensure = service._ensure_usable
    errors = []

    def paused_check(*args, **kwargs):
        ensure(*args, **kwargs)
        checked.set()
        assert resume.wait(5)

    def old_request():
        try:
            if operation == "list":
                service.list_sessions()
            else:
                with service.acquired_session("group:fictional"):
                    pass
        except ApplicationServiceError as error:
            errors.append(error.code)

    monkeypatch.setattr(service, "_ensure_usable", paused_check)
    task = threading.Thread(target=old_request)
    task.start()
    try:
        assert checked.wait(5)
        service.prepare_reconnect()
        factory.reconnect()
        worker.boot = "d" * 64
        service.start()
        worker.operations.clear()
    finally:
        resume.set()
        task.join(5)
    assert not task.is_alive()
    assert errors == ["qq_reconnect_required"]
    assert worker.operations == []


def test_invalidate_before_restart_detection_cannot_drop_verified_binding(tmp_path, monkeypatch):
    worker, factory, service = connection(tmp_path, monkeypatch)
    factory.create().status()
    worker.boot = "d" * 64
    factory.invalidate()
    worker.operations.clear()

    status = QQConnectionService(provider_factory=factory).check_status()

    assert status.code == "qq_reconnect_required"
    assert not status.available
    assert worker.operations == []


def test_old_request_paused_before_readiness_cannot_recover_new_connection(tmp_path, monkeypatch):
    worker, factory, service = connection(tmp_path, monkeypatch)
    service.start()
    entered, resume = threading.Event(), threading.Event()
    ensure = service._ensure_usable
    errors = []

    def paused_check(*args, **kwargs):
        entered.set()
        assert resume.wait(5)
        return ensure(*args, **kwargs)

    def old_request():
        try:
            service.list_sessions()
        except ApplicationServiceError as error:
            errors.append(error.code)

    monkeypatch.setattr(service, "_ensure_usable", paused_check)
    task = threading.Thread(target=old_request)
    task.start()
    try:
        assert entered.wait(5)
        service.prepare_reconnect()
        factory.reconnect()
        worker.boot = "d" * 64
        worker.operations.clear()
    finally:
        resume.set()
        task.join(5)
    assert not task.is_alive()
    assert errors == ["qq_reconnect_required"]
    assert worker.operations == []
    assert service.state is QQDirectDatabaseState.CLOSED


def test_startup_recovery_does_not_hold_admission_lock(tmp_path, monkeypatch):
    from qq_chat_analyzer.application.qq.qq_direct_database_import_service import QQDirectDatabaseShuttingDown
    worker, factory, service = connection(tmp_path, monkeypatch)
    client = service._require_runtime_client()
    entered, resume, refused = threading.Event(), threading.Event(), threading.Event()
    recover = client.recover
    errors = []

    def paused_recover(**kwargs):
        entered.set()
        assert resume.wait(5)
        recover(**kwargs)

    def try_reconnect():
        try:
            service.prepare_reconnect()
        except QQDirectDatabaseShuttingDown:
            refused.set()
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(client, "recover", paused_recover)
    startup = threading.Thread(target=service.start)
    reconnect = threading.Thread(target=try_reconnect)
    startup.start()
    try:
        assert entered.wait(5)
        reconnect.start()
        promptly_refused = refused.wait(0.5)
    finally:
        resume.set()
        startup.join(5)
        reconnect.join(5)
    assert not startup.is_alive() and not reconnect.is_alive()
    assert errors == []
    assert promptly_refused


def test_facade_reconnect_reset_gap_cannot_start_an_acquisition(tmp_path, monkeypatch):
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
    worker, factory, service = connection(tmp_path, monkeypatch)
    service.start()
    entered, resume, requested, completed = (threading.Event() for _ in range(4))
    reset = factory.reconnect
    errors = []

    def paused_reset():
        entered.set()
        assert resume.wait(5)
        reset()

    def start_request():
        requested.set()
        try:
            service.start()
        except Exception as error:
            errors.append(error)
        finally:
            completed.set()

    monkeypatch.setattr(factory, "reconnect", paused_reset)
    facade = ChatAnalyzerFacade(qq_service=service,
        qq_connection_service=QQConnectionService(provider_factory=factory),
        qq_auth_bridge=SimpleNamespace(start_auth_flow=lambda **kwargs: None))
    reconnect = threading.Thread(target=facade.start_qq_auth_flow)
    request = threading.Thread(target=start_request)
    reconnect.start()
    try:
        assert entered.wait(5)
        worker.boot = "d" * 64
        worker.operations.clear()
        request.start()
        assert requested.wait(5)
        crossed_reset = completed.wait(0.2)
    finally:
        resume.set()
        reconnect.join(5)
        request.join(5)
    assert not request.is_alive() and not reconnect.is_alive()
    assert not crossed_reset
    assert errors == []
    assert [op["method"] for op in worker.operations] == ["EchoSnapshotApi.recover"]
    assert worker.operations[0]["boot_id"] == "d" * 64


@pytest.mark.parametrize("operation", ["list", "session"])
def test_admitted_task_reads_and_cleans_with_captured_client(tmp_path, monkeypatch, operation):
    from qq_direct_db_testing import FakeSnapshotRuntime
    from test_qq_direct_db_lifecycle import _create_snapshot, GROUP_SESSION_ID
    source = tmp_path / "fictional.db"
    _create_snapshot(source)
    runtime = FakeSnapshotRuntime(tmp_path, snapshot_path=source)
    service = QQDirectDatabaseImportService(runtime_client=runtime)
    service.start()

    def forbidden_lookup(**kwargs):
        pytest.fail("An admitted acquisition must not look up a replacement client")

    monkeypatch.setattr(service, "_require_runtime_client", forbidden_lookup)
    if operation == "list":
        assert [s.session_id for s in service.list_sessions()] == [GROUP_SESSION_ID]
    else:
        with service.acquired_session(GROUP_SESSION_ID) as payload:
            assert payload.payload_path.is_file()
            assert service._active_acquisitions == 1
            with pytest.raises(ApplicationServiceError):
                service.prepare_reconnect()
    assert runtime.acquired == ["gen-0001"]
    assert runtime.cleaned == ["gen-0001"]
    assert service._active_acquisitions == 0
    service.shutdown()  # Shutdown also uses the captured, already-bound client.
    assert service.state is QQDirectDatabaseState.CLOSED


def test_admitted_old_acquire_blocks_reconnect_and_never_touches_new_worker(tmp_path, monkeypatch):
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, FacadeError
    worker, factory, service = connection(tmp_path, monkeypatch)
    service.start()
    client, provider = service._runtime_client, factory.create()
    entered, resume = threading.Event(), threading.Event()
    acquire = client.acquire
    errors = []

    def paused_acquire():
        entered.set()
        assert resume.wait(5)
        return acquire()

    def old_request():
        try:
            service.list_sessions()
        except ApplicationServiceError as error:
            errors.append(error.code)

    monkeypatch.setattr(client, "acquire", paused_acquire)
    facade = ChatAnalyzerFacade(qq_service=service,
        qq_connection_service=QQConnectionService(provider_factory=factory),
        qq_auth_bridge=SimpleNamespace(start_auth_flow=lambda **kwargs: pytest.fail("Must not start login")))
    task = threading.Thread(target=old_request)
    task.start()
    try:
        assert entered.wait(5)
        worker.boot = "d" * 64
        worker.operations.clear()
        with pytest.raises(FacadeError) as error:
            facade.start_qq_auth_flow()
        assert error.value.code == "qq_direct_database_shutting_down"
        assert factory.create() is provider and service._runtime_client is client
    finally:
        resume.set()
        task.join(5)
    assert not task.is_alive()
    assert errors == ["qq_reconnect_required"]
    assert worker.operations == []
    assert service._active_acquisitions == 0
    facade = ChatAnalyzerFacade(qq_service=service,
        qq_connection_service=QQConnectionService(provider_factory=factory),
        qq_auth_bridge=SimpleNamespace(start_auth_flow=lambda **kwargs: None))
    facade.start_qq_auth_flow()
    service.start()
    assert [op["method"] for op in worker.operations] == ["EchoSnapshotApi.recover"]
    assert worker.operations[0]["boot_id"] == "d" * 64


@pytest.mark.parametrize("verified", [False, True])
def test_same_generation_invalidation_and_config_refresh_keep_connection_owner(tmp_path, monkeypatch, verified):
    worker, factory, service = connection(tmp_path, monkeypatch)
    provider = factory.create()
    if verified:
        provider.status()
    # A config refresh must not silently redirect an existing connection.
    factory.config_loader.load_or_default().napcat_bridge_url = "http://127.0.0.1:49999"
    factory.invalidate()
    assert factory.create().list_friends() == []
    assert factory.create() is provider
    assert worker.operations[-1]["boot_id"] == "b" * 64
    factory.reconnect()
    fresh = factory.create()
    assert fresh is not provider
    assert fresh._base_url == "http://127.0.0.1:49999"


def test_first_connection_after_invalidation_still_binds_normally(tmp_path, monkeypatch):
    worker, factory, service = connection(tmp_path, monkeypatch)
    factory.invalidate()
    service.start()
    assert service.state is QQDirectDatabaseState.ACTIVE
    assert worker.operations[0]["method"] == "EchoSnapshotApi.recover"


def test_inflight_first_probe_survives_invalidation_without_new_binding(tmp_path, monkeypatch):
    worker, factory, service = connection(tmp_path, monkeypatch)
    provider = factory.create()
    entered, resume = threading.Event(), threading.Event()
    transport = provider._transport
    errors = []

    def paused_transport(*args, **kwargs):
        response = transport(*args, **kwargs)  # The old worker's verified reply.
        entered.set()
        assert resume.wait(5)
        return response

    def probe():
        try:
            provider.status()
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(provider, "_transport", paused_transport)
    task = threading.Thread(target=probe)
    task.start()
    try:
        assert entered.wait(5)
        factory.invalidate()
        worker.boot = "d" * 64
    finally:
        resume.set()
        task.join(5)
    assert not task.is_alive() and errors == []
    worker.operations.clear()
    with pytest.raises(NapCatQQWorkerGenerationChanged):
        factory.create().list_friends()
    assert worker.operations == []


@pytest.mark.parametrize("failure", [False, True])
def test_parallel_startup_recovers_once_and_failure_never_admits(tmp_path, monkeypatch, failure):
    from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import QQSnapshotRuntimeFailure
    worker, factory, service = connection(tmp_path, monkeypatch)
    client = service._require_runtime_client()
    entered, resume, waiting = (threading.Event() for _ in range(3))
    recover = client.recover
    errors = []
    calls = []

    def paused_recover(**kwargs):
        calls.append(1)
        entered.set()
        assert resume.wait(5)
        if failure:
            raise QQSnapshotRuntimeFailure()
        recover(**kwargs)

    def start(second=False):
        if second:
            waiting.set()
        try:
            service.start()
        except ApplicationServiceError as error:
            errors.append(error.code)

    monkeypatch.setattr(client, "recover", paused_recover)
    first = threading.Thread(target=start)
    second = threading.Thread(target=lambda: start(True))
    first.start()
    try:
        assert entered.wait(5)
        second.start()
        assert waiting.wait(5)
    finally:
        resume.set()
        first.join(5)
        second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert calls == [1]
    if failure:
        assert sorted(errors) == ["qq_direct_database_recovery_failed", "qq_direct_database_unavailable"]
        assert service.state is QQDirectDatabaseState.CLOSED
        with pytest.raises(ApplicationServiceError):
            service.list_sessions()
        assert worker.operations == []
    else:
        assert errors == [] and service.state is QQDirectDatabaseState.ACTIVE


def test_shutdown_during_slow_startup_is_bounded_and_late_result_cannot_reactivate(tmp_path, monkeypatch):
    worker, factory, service = connection(tmp_path, monkeypatch)
    service._shutdown_drain_seconds = 0.02
    client = service._require_runtime_client()
    entered, resume, stopped = (threading.Event() for _ in range(3))
    recover = client.recover
    errors = []
    count = []

    def paused_first_recover(**kwargs):
        count.append(1)
        if len(count) == 1:
            entered.set()
            assert resume.wait(5)
        recover(**kwargs)

    def start():
        try:
            service.start()
        except ApplicationServiceError as error:
            errors.append(error.code)

    def shutdown():
        try:
            service.shutdown()
        finally:
            stopped.set()

    monkeypatch.setattr(client, "recover", paused_first_recover)
    startup = threading.Thread(target=start)
    stopping = threading.Thread(target=shutdown)
    startup.start()
    try:
        assert entered.wait(5)
        stopping.start()
        assert stopped.wait(3)  # Includes the bounded second drain from PR #53.
        assert service.state is QQDirectDatabaseState.SHUTTING_DOWN
        assert not service.runtime_stop_safe
        with pytest.raises(ApplicationServiceError):
            service.prepare_reconnect()
    finally:
        resume.set()
        startup.join(5)
        stopping.join(5)
    assert not startup.is_alive() and not stopping.is_alive()
    assert errors == ["qq_direct_database_shutting_down"]
    assert service.state is QQDirectDatabaseState.SHUTTING_DOWN
    assert service.shutdown() is ShutdownStatus.TIMED_OUT
    with pytest.raises(ApplicationServiceError):
        service.list_sessions()
    assert all(op["method"] == "EchoSnapshotApi.recover" for op in worker.operations)


def test_old_cleanup_remains_admitted_and_cannot_delete_new_worker_data(tmp_path, monkeypatch):
    worker, factory, service = connection(tmp_path, monkeypatch)
    service.start()
    client = service._runtime_client
    cleanup = client.cleanup
    entered, resume = threading.Event(), threading.Event()
    errors = []

    def paused_cleanup(generation_id):
        entered.set()
        assert resume.wait(5)
        cleanup(generation_id)

    def read():
        try:
            service.list_sessions()
        except ApplicationServiceError as error:
            errors.append(error.code)

    monkeypatch.setattr(client, "cleanup", paused_cleanup)
    task = threading.Thread(target=read)
    task.start()
    try:
        assert entered.wait(5)
        worker.boot = "d" * 64
        worker.operations.clear()
        factory.invalidate()
        with pytest.raises(ApplicationServiceError):
            service.prepare_reconnect()
    finally:
        resume.set()
        task.join(5)
    assert not task.is_alive()
    assert errors == ["qq_reconnect_required"]
    assert worker.operations == []
    assert service._active_acquisitions == 0


def test_shutdown_timeout_retains_old_acquisition_and_recover_binding(tmp_path, monkeypatch):
    worker, factory, service = connection(tmp_path, monkeypatch)
    service.start()
    service._shutdown_drain_seconds = 0.02
    client = service._runtime_client
    acquire = client.acquire
    entered, resume = threading.Event(), threading.Event()
    errors = []

    def paused_acquire():
        entered.set()
        assert resume.wait(5)
        return acquire()

    def read():
        try:
            service.list_sessions()
        except ApplicationServiceError as error:
            errors.append(error.code)

    monkeypatch.setattr(client, "acquire", paused_acquire)
    task = threading.Thread(target=read)
    task.start()
    try:
        assert entered.wait(5)
        worker.boot = "d" * 64
        worker.operations.clear()
        assert service.shutdown() is ShutdownStatus.TIMED_OUT
        assert service.state is QQDirectDatabaseState.SHUTTING_DOWN
        assert not service.runtime_stop_safe
        with pytest.raises(ApplicationServiceError):
            service.prepare_reconnect()
        assert service._runtime_client is client
        assert worker.operations == []
    finally:
        resume.set()
        task.join(5)
    assert not task.is_alive()
    assert errors == ["qq_reconnect_required"]
    assert service._active_acquisitions == 0 and worker.operations == []
    assert service.shutdown() is ShutdownStatus.TIMED_OUT


def test_disconnect_and_routine_invalidate_cannot_rebind_without_explicit_connect(tmp_path, monkeypatch):
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
    worker, factory, service = connection(tmp_path, monkeypatch)
    service.start()
    provider = factory.create()

    def disconnect():
        worker.boot = "d" * 64  # A fictional runtime stop/replacement.

    facade = ChatAnalyzerFacade(qq_service=service,
        qq_connection_service=QQConnectionService(provider_factory=factory),
        qq_auth_bridge=SimpleNamespace(disconnect=disconnect, start_auth_flow=lambda **kwargs: None))
    facade.disconnect_qq()
    factory.invalidate()
    worker.operations.clear()
    status = QQConnectionService(provider_factory=factory).check_status()
    assert status.code == "qq_reconnect_required" and not status.available
    assert worker.operations == []
    facade.start_qq_auth_flow()
    service.start()
    assert factory.create() is not provider
    assert worker.operations[0]["method"] == "EchoSnapshotApi.recover"
