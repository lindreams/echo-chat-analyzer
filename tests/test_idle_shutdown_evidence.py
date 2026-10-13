"""Owned idle evidence; only fictional builders, analyses and processes."""
import threading
from types import SimpleNamespace

import pytest

from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, ChatSource
from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
from qq_chat_analyzer.application.qq.qq_runtime_session import QQRuntimeSession
from qq_chat_analyzer.application.qq.qq_process_registry import QQProcessRegistry
from qq_chat_analyzer.application.shutdown_models import ShutdownStatus, ShutdownResult, ShutdownStepResult


def steps(facade):
    return {step.name: step.status for step in facade.shutdown().steps}


def test_real_production_never_connected_has_complete_idle_path():
    from qq_chat_analyzer.gui.app import build_facade
    facade = build_facade()
    result = facade.shutdown()
    assert all(step.status is ShutdownStatus.SUCCESS for step in result.steps)
    # GUI idle evidence remains a separate mandatory step.
    assert not result.can_apply_update
    assert ShutdownResult(result.steps + (
        ShutdownStepResult('gui_workers', ShutdownStatus.SUCCESS),
    )).can_apply_update


def test_inert_production_builders_cannot_construct_after_shutdown():
    from qq_chat_analyzer.gui.app import build_facade
    facade = build_facade()
    facade.shutdown()
    with pytest.raises(RuntimeError):
        facade._source_bundle(ChatSource.QQ)


def test_idle_analysis_owner_is_not_unknown_just_because_it_exists():
    facade = ChatAnalyzerFacade(analysis_service=AnalysisApplicationService())
    assert steps(facade)['source_lifecycle'] is ShutdownStatus.SUCCESS


def test_running_analysis_is_unknown_even_if_it_later_finishes(monkeypatch):
    service = AnalysisApplicationService()
    entered, release = threading.Event(), threading.Event()
    def execute(_):
        entered.set()
        assert release.wait(2)
    monkeypatch.setattr(service, '_execute', execute)
    owner = threading.Thread(target=service.execute, args=(None,))
    owner.start()
    facade = ChatAnalyzerFacade(analysis_service=service)
    try:
        assert entered.wait(1)
        assert steps(facade)['source_lifecycle'] is ShutdownStatus.UNKNOWN
    finally:
        release.set()
        owner.join(2)
    assert steps(facade)['source_lifecycle'] is ShutdownStatus.UNKNOWN


def test_created_unknown_source_is_not_certified_by_empty_gui():
    facade = ChatAnalyzerFacade(wechat_service=object())
    assert steps(facade)['source_lifecycle'] is ShutdownStatus.UNKNOWN


def test_empty_explicit_session_is_known_idle():
    facade = ChatAnalyzerFacade(qq_runtime_session=QQRuntimeSession(), qq_process_registry=QQProcessRegistry())
    assert steps(facade)['qq_runtime_termination'] is ShutdownStatus.SUCCESS


def test_retired_unverified_process_does_not_erase_runtime_history():
    session = QQRuntimeSession()
    credential = session.begin_launch()
    session.bind_process(SimpleNamespace(closed=True), credential)
    session.retire()
    assert steps(ChatAnalyzerFacade(qq_runtime_session=session))['qq_runtime_termination'] is ShutdownStatus.UNKNOWN


def test_legacy_pid_removed_on_disconnect_does_not_create_exit_proof():
    registry = QQProcessRegistry(terminator=lambda _: True)
    registry.record(123456)
    registry.discard(123456)
    assert steps(ChatAnalyzerFacade(qq_process_registry=registry))['qq_runtime_termination'] is ShutdownStatus.UNKNOWN


def test_runtime_cleanup_failure_remains_failed_and_owned():
    registry = QQProcessRegistry(terminator=lambda _: False)
    registry.record(123456)
    assert steps(ChatAnalyzerFacade(qq_process_registry=registry))['qq_runtime_termination'] is ShutdownStatus.FAILED
    assert registry.recorded() == (123456,)


def test_inflight_inert_builder_is_unknown_even_before_bundle_publication():
    from qq_chat_analyzer.application.source_bundle_builder import SourceBundleBuilder
    entered, release = threading.Event(), threading.Event()
    def build():
        entered.set()
        assert release.wait(2)
        return SimpleNamespace(service=object())
    builder = SourceBundleBuilder(build)
    facade = ChatAnalyzerFacade(source_builders={ChatSource.QQ: builder})
    owner = threading.Thread(target=builder)
    owner.start()
    try:
        assert entered.wait(1)
        assert steps(facade)['source_lifecycle'] is ShutdownStatus.UNKNOWN
    finally:
        release.set()
        owner.join(2)


def test_completed_analysis_is_idle_and_new_admission_is_sealed(monkeypatch):
    from qq_chat_analyzer.application.analysis_service import AnalysisServiceClosing
    service = AnalysisApplicationService()
    monkeypatch.setattr(service, '_execute', lambda _: 'fictional result')
    assert service.execute(None) == 'fictional result'
    assert steps(ChatAnalyzerFacade(analysis_service=service))['source_lifecycle'] is ShutdownStatus.SUCCESS
    with pytest.raises(AnalysisServiceClosing):
        service.execute(None)


def test_pending_launch_cannot_be_retired_into_idle_proof():
    session = QQRuntimeSession()
    session.begin_launch()
    session.retire()
    assert steps(ChatAnalyzerFacade(qq_runtime_session=session))['qq_runtime_termination'] is ShutdownStatus.UNKNOWN


def test_normal_disconnect_of_unproven_runtime_keeps_both_steps_unknown(tmp_path):
    from qq_chat_analyzer import runtime
    from qq_chat_analyzer.application.qq.qq_runtime_manager import QQRuntimeManager
    executable = tmp_path / 'fictional.exe'
    executable.write_text('fictional, never executed')
    process = SimpleNamespace(pid=123456, closed=False)
    process.poll = lambda: 0 if process.closed else None
    process.tree_running = lambda: not process.closed
    process.close = lambda: setattr(process, 'closed', True)
    instance = runtime.BundledQQRuntime(runtime.QQRuntimeConfig(executable, tmp_path),
        health_checker=lambda _: False, launcher=lambda: process)
    registry = QQProcessRegistry(terminator=lambda _: pytest.fail('no PID fallback'))
    manager = QQRuntimeManager(instance, process_registry=registry)
    assert manager.start().state.value == 'running'
    assert manager.stop().state.value == 'stopped'
    assert process.closed
    assert registry.recorded() == ()
    evidence = steps(ChatAnalyzerFacade(qq_connection_manager=manager, qq_process_registry=registry))
    assert evidence['qq_runtime_termination'] is ShutdownStatus.UNKNOWN
    assert evidence['source_lifecycle'] is ShutdownStatus.UNKNOWN


@pytest.mark.slow_integration
def test_registry_proves_real_fictional_job_tree_exit(tmp_path):
    import sys
    from qq_chat_analyzer.runtime.windows_job import launch_owned_process
    if sys.platform != 'win32':
        pytest.skip('Windows Job evidence')
    from test_windows_job_process import _command, _tree_handles, _dead, _native
    process = launch_owned_process(_command(tmp_path), cwd=tmp_path)
    handles = _tree_handles(tmp_path)
    registry, session = QQProcessRegistry(), QQRuntimeSession()
    registry.record_process(process)
    credential = session.begin_launch()
    session.bind_process(process, credential)
    try:
        assert steps(ChatAnalyzerFacade(qq_process_registry=registry, qq_runtime_session=session))['qq_runtime_termination'] is ShutdownStatus.SUCCESS
        assert process.closed
        assert process.exit_verified is True
        assert _dead(handles)
    finally:
        process.close()
        for handle in handles:
            _native().CloseHandle(handle)


@pytest.mark.slow_integration
def test_verified_disconnect_retains_tree_evidence(tmp_path):
    import sys
    from qq_chat_analyzer.runtime.windows_job import launch_owned_process
    if sys.platform != 'win32':
        pytest.skip('Windows Job evidence')
    process = launch_owned_process([sys.executable, '-c', 'import time; time.sleep(30)'], cwd=tmp_path)
    registry, session = QQProcessRegistry(), QQRuntimeSession()
    registry.record_process(process)
    credential = session.begin_launch()
    session.bind_process(process, credential)
    try:
        process.close_with_exit_evidence()
        registry.discard(process.pid)
        session.retire()
        assert steps(ChatAnalyzerFacade(qq_process_registry=registry, qq_runtime_session=session))['qq_runtime_termination'] is ShutdownStatus.SUCCESS
    finally:
        process.close()


@pytest.mark.slow_integration
def test_closed_job_without_pre_close_query_remains_unknown(tmp_path):
    import sys
    from qq_chat_analyzer.runtime.windows_job import launch_owned_process
    if sys.platform != 'win32':
        pytest.skip('Windows Job evidence')
    process = launch_owned_process([sys.executable, '-c', 'pass'], cwd=tmp_path)
    registry = QQProcessRegistry()
    registry.record_process(process)
    process.close()
    registry.discard(process.pid)
    assert steps(ChatAnalyzerFacade(qq_process_registry=registry))['qq_runtime_termination'] is ShutdownStatus.UNKNOWN


@pytest.mark.slow_integration
def test_runtime_proof_does_not_ignore_an_unreleased_pipe(tmp_path):
    import sys
    from qq_chat_analyzer.runtime.windows_job import launch_owned_process
    if sys.platform != 'win32':
        pytest.skip('Windows Job evidence')
    process = launch_owned_process([sys.executable, '-c', 'pass'], cwd=tmp_path)
    process.close_with_exit_evidence()
    # Native tree proof remains real; substitute only an unclosed Python stream.
    process.stdout = SimpleNamespace(closed=False)
    assert process.exit_verified is False


@pytest.mark.slow_integration
def test_replaced_inflight_launch_is_not_hidden_by_newer_verified_tree(tmp_path):
    import sys
    from qq_chat_analyzer.runtime.windows_job import launch_owned_process
    if sys.platform != 'win32':
        pytest.skip('Windows Job evidence')
    session = QQRuntimeSession()
    session.begin_launch()  # Its launcher outcome remains unavailable.
    credential = session.begin_launch()
    process = launch_owned_process([sys.executable, '-c', 'pass'], cwd=tmp_path)
    session.bind_process(process, credential)
    try:
        process.close_with_exit_evidence()
        assert steps(ChatAnalyzerFacade(qq_runtime_session=session))['qq_runtime_termination'] is ShutdownStatus.UNKNOWN
    finally:
        process.close()


@pytest.mark.slow_integration
def test_real_idle_main_window_has_update_admission_in_isolated_process(tmp_path):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path
    env = os.environ.copy()
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'),
               LOCALAPPDATA=str(tmp_path / 'local'), APPDATA=str(tmp_path / 'roaming'),
               USERPROFILE=str(tmp_path / 'home'), HOME=str(tmp_path / 'home'),
               QT_QPA_PLATFORM='offscreen')
    script = '''
import json
from PySide6.QtWidgets import QApplication
from qq_chat_analyzer.gui import app
from qq_chat_analyzer.gui.main_window import MainWindow
def forbidden(*args, **kwargs):
    raise AssertionError('idle startup must not construct a source')
app._qq_bundle_factory = forbidden
app._wechat_bundle_factory = forbidden
application = QApplication([])
window = MainWindow(app.build_facade())
window.show()
application.processEvents()
window.close()
assert window.await_shutdown(2)
result = window.shutdown_protocol.result
print(json.dumps({'can_apply': result.can_apply_update,
                  'steps': {step.name: step.status.value for step in result.steps}}))
'''
    completed = subprocess.run([sys.executable, '-c', script], env=env, cwd=tmp_path,
                               capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(completed.stdout)
    assert evidence == {'can_apply': True, 'steps': {
        'direct_db_cleanup': 'success', 'retained_output_cleanup': 'success',
        'qq_runtime_termination': 'success', 'source_lifecycle': 'success',
        'gui_workers': 'success',
    }}, (evidence, completed.stderr)
