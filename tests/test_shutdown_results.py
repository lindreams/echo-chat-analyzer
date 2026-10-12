"""A completed shutdown is not necessarily safe for an update."""
import threading

import pytest

from qq_chat_analyzer.application import facade as module
from qq_chat_analyzer.gui.shutdown import ShutdownProtocol


UPDATE_EVIDENCE = (
    'direct_db_cleanup', 'retained_output_cleanup', 'qq_runtime_termination',
    'source_lifecycle', 'gui_workers',
)


def successful_evidence(names=UPDATE_EVIDENCE):
    return module.ShutdownResult(tuple(
        module.ShutdownStepResult(name, module.ShutdownStatus.SUCCESS)
        for name in names
    ))


@pytest.mark.parametrize('missing', UPDATE_EVIDENCE)
def test_missing_required_evidence_cannot_authorize_update(missing):
    result = successful_evidence(name for name in UPDATE_EVIDENCE if name != missing)
    assert_status(result, 'success')


@pytest.mark.parametrize('duplicate', UPDATE_EVIDENCE)
def test_duplicate_evidence_cannot_authorize_update(duplicate):
    assert_status(successful_evidence((*UPDATE_EVIDENCE, duplicate)), 'success')


def test_duplicate_cannot_replace_missing_gui_evidence():
    names = (*UPDATE_EVIDENCE[:-1], 'qq_runtime_termination')
    assert_status(successful_evidence(names), 'success')


def test_runtime_success_alone_cannot_authorize_update():
    assert_status(successful_evidence(('qq_runtime_termination',)), 'success')


def test_unrecognized_success_evidence_cannot_extend_update_contract():
    assert_status(successful_evidence((*UPDATE_EVIDENCE, 'unverified_resource')), 'success')


def test_complete_success_evidence_can_pass_shutdown_admission():
    assert_status(successful_evidence(), 'success', update=True)


@pytest.mark.parametrize('status', [module.ShutdownStatus.FAILED,
                                  module.ShutdownStatus.TIMED_OUT,
                                  module.ShutdownStatus.UNKNOWN])
@pytest.mark.parametrize('name', UPDATE_EVIDENCE)
def test_complete_evidence_with_non_success_still_blocks_update(name, status):
    result = module.ShutdownResult(tuple(
        module.ShutdownStepResult(step, status if step == name else module.ShutdownStatus.SUCCESS)
        for step in UPDATE_EVIDENCE
    ))
    assert_status(result, status.value)


def assert_status(result, status, *, update=False):
    assert result is not None, 'shutdown must return resource evidence'
    assert result.status.value == status
    assert result.can_apply_update is update


def test_no_resources_are_successful_and_repeated_shutdown_preserves_result():
    facade = module.ChatAnalyzerFacade()
    result = facade.shutdown()
    assert_status(result, 'success')
    assert facade.shutdown() is result


def test_real_owned_report_removal_is_verified(tmp_path):
    facade = module.ChatAnalyzerFacade()
    owned = module._RetainedReportDirectory(tmp_path)
    facade._retained_output_directory = owned
    result = facade.shutdown()
    assert_status(result, 'success')
    from pathlib import Path
    assert not Path(owned.name).exists()


def test_swallowed_report_cleanup_failure_is_not_success(tmp_path, monkeypatch):
    owned = module._RetainedReportDirectory(tmp_path)
    facade = module.ChatAnalyzerFacade()
    facade._retained_output_directory = owned
    def fail(*_):
        raise OSError('fictional locked file')
    monkeypatch.setattr(module, '_remove_owned_analysis_output', fail)
    assert_status(facade.shutdown(), 'failed')


def test_partial_failure_is_preserved_on_repeat():
    class Service:
        def shutdown(self):
            raise RuntimeError('fictional cleanup failure')
    facade = module.ChatAnalyzerFacade(qq_service=Service())
    result = facade.shutdown()
    assert_status(result, 'failed')
    assert facade.shutdown() is result


def test_return_without_resource_evidence_is_unknown():
    class Service:
        def shutdown(self):
            pass
    assert_status(module.ChatAnalyzerFacade(qq_service=Service()).shutdown(), 'unknown')


def test_built_wechat_has_no_verified_shutdown_contract():
    assert_status(module.ChatAnalyzerFacade(wechat_service=object()).shutdown(), 'unknown')


def test_abandoned_step_is_timed_out_even_when_it_later_returns():
    release = threading.Event()
    class Service:
        def shutdown(self):
            release.wait(2)
    facade = module.ChatAnalyzerFacade(qq_service=Service(), shutdown_step_seconds=0.01)
    try:
        result = facade.shutdown()
        assert_status(result, 'timed_out')
        release.set()
        assert facade.shutdown() is result
    finally:
        release.set()


def test_runtime_termination_failure_cannot_be_swallowed():
    from qq_chat_analyzer.application.qq.qq_process_registry import QQProcessRegistry
    registry = QQProcessRegistry(terminator=lambda _: False)
    registry.record(123456)
    assert_status(module.ChatAnalyzerFacade(qq_process_registry=registry).shutdown(), 'failed')
    assert registry.recorded() == (123456,)


def test_registry_empty_after_termination_does_not_prove_descendant_exit():
    from qq_chat_analyzer.application.qq.qq_process_registry import QQProcessRegistry
    registry = QQProcessRegistry(terminator=lambda _: True)
    registry.record(123456)
    assert_status(module.ChatAnalyzerFacade(qq_process_registry=registry).shutdown(), 'unknown')
    assert registry.recorded() == ()


def test_missing_credential_retirement_contract_is_unknown():
    assert_status(module.ChatAnalyzerFacade(qq_runtime_session=object()).shutdown(), 'unknown')


def test_credential_still_live_after_retirement_is_failed():
    class Session:
        def retire(self):
            pass
        def credential(self):
            return 'fictional-test-value'
    assert_status(module.ChatAnalyzerFacade(qq_runtime_session=Session()).shutdown(), 'failed')


def test_real_recover_failure_is_failed_even_though_service_becomes_closed():
    from qq_chat_analyzer.application.qq.qq_direct_database_import_service import (
        QQDirectDatabaseImportService, QQDirectDatabaseState)
    from qq_chat_analyzer.providers.qq_direct_snapshot_runtime import QQSnapshotRuntimeError
    class Client:
        calls = 0
        def recover(self, **_):
            self.calls += 1
            if self.calls > 1:
                raise QQSnapshotRuntimeError('fictional recovery failure')
    service = QQDirectDatabaseImportService(runtime_client=Client())
    service.start()
    assert_status(module.ChatAnalyzerFacade(qq_service=service).shutdown(), 'failed')
    assert service.state is QQDirectDatabaseState.CLOSED


@pytest.mark.parametrize('owner', [None, lambda: None])
def test_protocol_completion_without_evidence_is_unknown(owner):
    protocol = ShutdownProtocol()
    protocol.begin(owner)
    assert protocol.wait(1)
    assert_status(getattr(protocol, 'result', None), 'unknown')


def test_protocol_owner_failure_is_failed_but_finished():
    def fail():
        raise RuntimeError('fictional failure')
    protocol = ShutdownProtocol()
    protocol.begin(fail)
    assert protocol.wait(1)
    assert protocol.finished
    assert_status(getattr(protocol, 'result', None), 'failed')


def test_protocol_propagates_verified_result():
    protocol = ShutdownProtocol()
    protocol.begin(module.ChatAnalyzerFacade().shutdown)
    assert protocol.wait(1)
    assert_status(getattr(protocol, 'result', None), 'success')


def test_protocol_timeout_cannot_become_update_permission_later():
    release = threading.Event()
    facade = module.ChatAnalyzerFacade()
    def owner():
        release.wait(2)
        return facade.shutdown()
    protocol = ShutdownProtocol()
    protocol.begin(owner)
    try:
        assert not protocol.wait(0.01)
        assert_status(getattr(protocol, 'result', None), 'timed_out')
        release.set()
        assert protocol.wait(1)
        assert_status(protocol.result, 'timed_out')
    finally:
        release.set()


def test_protocol_result_is_not_published_before_task_finishes(monkeypatch):
    from types import SimpleNamespace
    from qq_chat_analyzer.gui import shutdown
    finalizing, release = threading.Event(), threading.Event()
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        if calls == 2:
            finalizing.set()
            release.wait(2)
        return float(calls)

    monkeypatch.setattr(shutdown, 'time', SimpleNamespace(monotonic=clock))
    protocol = ShutdownProtocol()
    protocol.begin(successful_evidence)
    try:
        assert finalizing.wait(1)
        assert not protocol.finished
        assert_status(protocol.result, 'unknown')
    finally:
        release.set()
        assert protocol.wait(1)
    assert_status(protocol.result, 'success', update=True)


def test_unpublished_source_builder_resources_are_unknown():
    # An injected builder can already own resources or still be building them.
    facade = module.ChatAnalyzerFacade(source_builders={module.ChatSource.WECHAT: lambda: object()})
    assert_status(facade.shutdown(), 'unknown')


def test_injected_analysis_lifecycle_is_unknown():
    assert_status(module.ChatAnalyzerFacade(analysis_service=object()).shutdown(), 'unknown')


@pytest.mark.parametrize('inventory', [None, ()])
def test_unknown_registry_cannot_prove_no_owned_resources(inventory):
    class Registry:
        def recorded(self):
            return inventory
        def terminate_all(self):
            pass
    assert_status(module.ChatAnalyzerFacade(qq_process_registry=Registry()).shutdown(), 'unknown')


def test_retiring_unregistered_runtime_does_not_prove_process_exit():
    from qq_chat_analyzer.application.qq.qq_runtime_session import QQRuntimeSession
    class Process:
        def poll(self):
            return None
    session = QQRuntimeSession()
    credential = session.begin_launch()
    session.bind_process(Process(), credential)
    assert_status(module.ChatAnalyzerFacade(qq_runtime_session=session).shutdown(), 'unknown')


def test_runtime_exception_does_not_skip_credential_retirement():
    retired = threading.Event()
    class Registry:
        def recorded(self):
            return ()
        def terminate_all(self):
            raise RuntimeError('fictional runtime termination failure')
    class Session:
        def credential(self):
            return None
        def retire(self):
            retired.set()
    result = module.ChatAnalyzerFacade(qq_process_registry=Registry(),
                                       qq_runtime_session=Session()).shutdown()
    assert_status(result, 'failed')
    assert retired.is_set()
