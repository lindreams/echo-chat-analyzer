"""Fictional cleanup evidence; never access a real source or run an updater."""
import threading

import pytest

from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
from qq_chat_analyzer.application.shutdown_models import ShutdownStatus
from qq_chat_analyzer.application.qq.qq_direct_database_import_service import (
    QQDirectDatabaseImportService, QQDirectDatabaseRecoveryFailed,
)
from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import QQSnapshotRuntimeError


class FictionalClient:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def recover(self, **_):
        self.calls += 1
        if self.fail:
            raise QQSnapshotRuntimeError('fictional recovery failure')


def test_unused_direct_db_proves_empty_without_constructing_a_client():
    service = QQDirectDatabaseImportService()
    assert service.shutdown() is ShutdownStatus.SUCCESS
    assert service.shutdown() is ShutdownStatus.SUCCESS


def test_real_direct_db_reports_drained_and_recovered_evidence_to_facade():
    client = FictionalClient()
    service = QQDirectDatabaseImportService(runtime_client=client)
    service.start()
    result = ChatAnalyzerFacade(qq_service=service).shutdown()
    steps = {step.name: step.status for step in result.steps}
    assert steps['direct_db_cleanup'] is ShutdownStatus.SUCCESS
    assert steps['source_lifecycle'] is ShutdownStatus.UNKNOWN
    assert not result.can_apply_update
    assert service.shutdown() is ShutdownStatus.SUCCESS
    assert client.calls == 2


def test_drain_timeout_is_not_repaired_by_successful_recover_or_late_completion():
    client = FictionalClient()
    service = QQDirectDatabaseImportService(runtime_client=client, shutdown_drain_seconds=0.01)
    service.start()
    # The acquisition admission is real; no generation/DB is requested.
    service._begin_acquisition()
    try:
        result = ChatAnalyzerFacade(qq_service=service).shutdown()
        steps = {step.name: step.status for step in result.steps}
        assert steps['direct_db_cleanup'] is ShutdownStatus.TIMED_OUT
        assert not result.can_apply_update
    finally:
        service._end_acquisition()
    assert service.shutdown() is ShutdownStatus.TIMED_OUT
    assert client.calls == 2


def test_recover_exception_keeps_failure_on_repeat():
    client = FictionalClient()
    service = QQDirectDatabaseImportService(runtime_client=client)
    service.start()
    client.fail = True
    with pytest.raises(QQDirectDatabaseRecoveryFailed):
        service.shutdown()
    assert service.shutdown() is ShutdownStatus.FAILED


def test_failed_startup_is_not_empty_resource_evidence():
    client = FictionalClient()
    client.fail = True
    service = QQDirectDatabaseImportService(runtime_client=client)
    with pytest.raises(QQDirectDatabaseRecoveryFailed):
        service.start()
    with pytest.raises(QQDirectDatabaseRecoveryFailed):
        service.shutdown()
    assert service.shutdown() is ShutdownStatus.FAILED


def test_retryable_startup_failure_still_requires_recover(monkeypatch):
    from qq_chat_analyzer.application.qq import qq_direct_database_import_service as module
    from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import QQSnapshotRuntimeUnavailable
    monkeypatch.setattr(module, 'DEFAULT_STARTUP_READINESS_SECONDS', 0.01)
    class Client:
        def recover(self, **_):
            raise QQSnapshotRuntimeUnavailable()
    service = QQDirectDatabaseImportService(runtime_client=Client())
    with pytest.raises(module.QQDirectDatabaseNotReady):
        service.start()
    with pytest.raises(QQDirectDatabaseRecoveryFailed):
        service.shutdown()
    assert service.shutdown() is ShutdownStatus.FAILED


def test_inflight_shutdown_repeat_cannot_claim_success():
    entered, release = threading.Event(), threading.Event()
    client = FictionalClient()
    service = QQDirectDatabaseImportService(runtime_client=client)
    service.start()
    def recover(**_):
        entered.set()
        assert release.wait(2)
    client.recover = recover
    owner = threading.Thread(target=service.shutdown)
    owner.start()
    try:
        assert entered.wait(1)
        assert service.shutdown() is ShutdownStatus.UNKNOWN
    finally:
        release.set()
        owner.join(2)
    assert service.shutdown() is ShutdownStatus.SUCCESS


def test_production_composition_proves_idle_without_opening_sources(monkeypatch):
    from qq_chat_analyzer.gui import app
    from qq_chat_analyzer.application import report_package_catalog
    def forbidden(*_, **__):
        pytest.fail('must not open a source or real user storage')
    monkeypatch.setattr(app, '_qq_bundle_factory', forbidden)
    monkeypatch.setattr(app, '_wechat_bundle_factory', forbidden)
    monkeypatch.setattr(report_package_catalog, 'user_data_dir', forbidden)
    facade = app.build_facade()
    result = facade.shutdown()
    steps = {step.name: step.status for step in result.steps}
    assert steps == {
        'direct_db_cleanup': ShutdownStatus.SUCCESS,
        'retained_output_cleanup': ShutdownStatus.SUCCESS,
        'qq_runtime_termination': ShutdownStatus.SUCCESS,
        'source_lifecycle': ShutdownStatus.SUCCESS,
    }
    assert not result.can_apply_update
