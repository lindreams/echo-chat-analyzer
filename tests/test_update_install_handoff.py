"""Install authorization must come from bytes and final owner evidence, not UI."""
from types import SimpleNamespace

import pytest

from qq_chat_analyzer.application.shutdown_models import (
    ShutdownResult, ShutdownStatus, ShutdownStepResult,
)
from update_feed_test_data import local_feed_service


def evidence(status=ShutdownStatus.SUCCESS):
    return ShutdownResult(tuple(ShutdownStepResult(name, status) for name in (
        'source_lifecycle', 'direct_db_cleanup', 'retained_output_cleanup',
        'qq_runtime_termination', 'gui_workers')))


def fixture(tmp_path):
    service, cached, _, _ = local_feed_service(tmp_path)
    assert service.check().status == 'available'
    assert service.download().status == 'downloaded'
    calls = []
    sdk = service._manager

    class RecordingSDK:
        def __getattr__(self, name):
            return getattr(sdk, name)

        def wait_exit_then_apply_updates(self, asset, *, silent, restart):
            calls.append((asset.Version, silent, restart))

    service._manager = RecordingSDK()
    service._package_directory = lambda feed, manager: cached.parent
    return service, cached, calls


def test_valid_package_preparation_never_starts_updater(tmp_path):
    service, _, calls = fixture(tmp_path)
    prepared = service.prepare_install()
    assert prepared.status == 'ready'
    assert prepared.target_version == '0.2.0'
    assert prepared.token
    assert calls == []


@pytest.mark.parametrize('status', list(ShutdownStatus))
def test_only_complete_success_can_handoff(tmp_path, status):
    service, _, calls = fixture(tmp_path)
    prepared = service.prepare_install()
    result = service.handoff(prepared.token, evidence(status))
    assert result.status == ('started' if status is ShutdownStatus.SUCCESS else 'denied')
    assert calls == ([('0.2.0', False, True)] if status is ShutdownStatus.SUCCESS else [])


@pytest.mark.parametrize('damage', ['changed', 'missing', 'portable', 'no_source'])
def test_final_revalidation_rejects_changed_installation(tmp_path, damage):
    service, cached, calls = fixture(tmp_path)
    prepared = service.prepare_install()
    if damage == 'changed':
        cached.write_bytes(b'fictional corrupt bytes')
    elif damage == 'missing':
        cached.unlink()
    elif damage == 'portable':
        service._setup_runtime = lambda: False
    else:
        service._feed = None
    assert service.handoff(prepared.token, evidence()).status != 'started'
    assert calls == []


def test_missing_step_forged_token_and_repeated_handoff_are_denied(tmp_path):
    service, _, calls = fixture(tmp_path)
    prepared = service.prepare_install()
    assert service.handoff(prepared.token, ShutdownResult(evidence().steps[:-1])).status == 'denied'
    assert service.handoff('forged', evidence()).status == 'denied'
    assert service.handoff(prepared.token, evidence()).status == 'started'
    assert service.handoff(prepared.token, evidence()).status != 'started'
    assert calls == [('0.2.0', False, True)]


def test_prepare_hashes_existing_cache_instead_of_trusting_downloaded(tmp_path):
    service, cached, calls = fixture(tmp_path)
    cached.write_bytes(b'invalid cache')
    assert service.get_status().status == 'downloaded'
    assert service.prepare_install().status != 'ready'
    assert calls == []


def test_exit_entrypoint_handoffs_only_after_final_protocol(monkeypatch):
    from qq_chat_analyzer.gui import app
    events = []
    monkeypatch.setattr(app, '_arm_forced_exit', lambda *args: None)
    window = SimpleNamespace(
        begin_shutdown=lambda: events.append('begin'),
        await_shutdown=lambda timeout: events.append('wait') or True,
        finish_update_handoff=lambda: events.append('handoff'),
    )
    app._finish_process_exit(0, window=window, hard_exit=lambda code: events.append('forced'))
    assert events == ['begin', 'wait', 'handoff']


def test_timeout_never_handoffs(monkeypatch):
    from qq_chat_analyzer.gui import app
    events = []
    monkeypatch.setattr(app, '_arm_forced_exit', lambda *args: None)
    window = SimpleNamespace(begin_shutdown=lambda: None, await_shutdown=lambda timeout: False,
                             finish_update_handoff=lambda: events.append('handoff'))
    app._finish_process_exit(0, window=window, hard_exit=lambda code: events.append('forced'))
    assert events == ['forced']


def test_facade_refuses_used_sources_before_destructive_shutdown(tmp_path):
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, FacadeError
    service, _, calls = fixture(tmp_path)
    facade = ChatAnalyzerFacade(qq_service=object(), installable_update_service=service)
    with pytest.raises(FacadeError) as error:
        facade.prepare_update_install()
    assert error.value.code == 'update_idle_required'
    assert facade._shutdown_result is None
    assert calls == []


def test_install_confirmation_and_closed_dialog_drop_late_preparation(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
    from qq_chat_analyzer.gui.update_dialog import UpdateDialog
    service, _, calls = fixture(tmp_path)
    facade = ChatAnalyzerFacade(installable_update_service=service)
    requests = []
    def executor(operation, **callbacks):
        requests.append((operation, callbacks))
    dialog = UpdateDialog(facade, executor=executor)
    dialog.show()
    received = []
    dialog.install_requested.connect(received.append)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.No)
    dialog.install_button.click()
    assert requests == []
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
    dialog.install_button.click()
    dialog.install_button.click()
    assert len(requests) == 1
    prepared = requests[0][0]()
    dialog.reject()
    requests[0][1]['on_success'](prepared)
    assert received == []
    assert calls == []


def test_handoff_hash_budget_expiry_never_starts_updater(tmp_path):
    service, _, calls = fixture(tmp_path)
    prepared = service.prepare_install()
    assert service.handoff(prepared.token, evidence(), verification_seconds=0).status == 'failed'
    assert calls == []


def test_sdk_spawn_failure_consumes_token_without_success(tmp_path):
    service, _, calls = fixture(tmp_path)
    prepared = service.prepare_install()
    def fail(*args, **kwargs):
        raise OSError('fictional spawn failure')
    service._manager.wait_exit_then_apply_updates = fail
    assert service.handoff(prepared.token, evidence()).status == 'failed'
    assert service.handoff(prepared.token, evidence()).status == 'denied'
    assert calls == []


def test_facade_rejects_invented_success_without_owner_shutdown(tmp_path):
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
    service, _, calls = fixture(tmp_path)
    facade = ChatAnalyzerFacade(installable_update_service=service)
    prepared = facade.prepare_update_install()
    assert facade.handoff_update_install(prepared.token, evidence()).status == 'denied'
    assert calls == []


@pytest.mark.skipif(__import__('sys').platform != 'win32', reason='Windows package handoff guard')
def test_verified_package_cannot_change_at_sdk_launch_boundary(tmp_path):
    service, cached, calls = fixture(tmp_path)
    prepared = service.prepare_install()
    def try_change(asset, *, silent, restart):
        with pytest.raises(PermissionError):
            cached.write_bytes(b'changed after verification')
        calls.append(asset.Version)
    service._manager.wait_exit_then_apply_updates = try_change
    assert service.handoff(prepared.token, evidence()).status == 'started'
    assert calls == ['0.2.0']


def test_preflight_refuses_running_analysis_without_sealing_it(tmp_path, monkeypatch):
    from threading import Thread, Event
    from qq_chat_analyzer.application.analysis_service import AnalysisApplicationService
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, FacadeError
    service, _, calls = fixture(tmp_path)
    analysis = AnalysisApplicationService()
    entered, release = Event(), Event()
    def execute(_):
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(analysis, '_execute', execute)
    thread = Thread(target=analysis.execute, args=(None,))
    thread.start()
    facade = ChatAnalyzerFacade(analysis_service=analysis, installable_update_service=service)
    try:
        assert entered.wait(1)
        with pytest.raises(FacadeError) as error:
            facade.prepare_update_install()
        assert error.value.code == 'update_idle_required'
        assert facade._shutdown_result is None
    finally:
        release.set()
        thread.join(2)
    assert analysis.is_idle  # refusal did not mutate resource lifecycle
    assert calls == []


@pytest.mark.parametrize('change', ['feed_identity', 'pending_version', 'manifest'])
def test_preparation_rejects_metadata_mismatch(tmp_path, change):
    import json
    import hashlib
    from zipfile import ZipFile
    service, cached, calls = fixture(tmp_path)
    manifest = service._feed.source / 'releases.test.json'
    metadata = json.loads(manifest.read_text())
    if change == 'feed_identity':
        metadata['Assets'][0]['PackageId'] = 'OtherFictionalPackage'
    elif change == 'pending_version':
        metadata['Assets'][0]['Version'] = '0.3.0'
    else:
        with ZipFile(cached, 'w') as archive:
            archive.writestr('FictionalEcho.nuspec', '<package><metadata><id>FictionalEcho</id><version>0.2.0</version><channel>foreign</channel></metadata></package>')
        content = cached.read_bytes()
        metadata['Assets'][0]['Size'] = len(content)
        metadata['Assets'][0]['SHA256'] = hashlib.sha256(content).hexdigest()
    manifest.write_text(json.dumps(metadata))
    assert service.prepare_install().status != 'ready'
    assert calls == []


@pytest.mark.slow_integration
@pytest.mark.parametrize('mode', ['direct', 'worker', 'entrypoint'])
def test_real_qt_exit_handoff_uses_worktree_code_and_preserves_fictional_data(tmp_path, mode):
    """Real process exit, injected updater only; NOT an actual Setup A->B claim."""
    import os
    import sys
    import json
    import hashlib
    import subprocess
    from pathlib import Path
    worktree = Path(__file__).resolve().parents[1]
    data = tmp_path / 'fictional-data.txt'
    data.write_text('Fictional Alice and Bob; no real user data.', encoding='utf-8')
    before = hashlib.sha256(data.read_bytes()).hexdigest()
    env = os.environ.copy()
    env.update(PYTHONPATH=os.pathsep.join((str(worktree / 'src'), str(worktree / 'tests'))),
               LOCALAPPDATA=str(tmp_path / 'local'), APPDATA=str(tmp_path / 'roaming'),
               USERPROFILE=str(tmp_path / 'home'), HOME=str(tmp_path / 'home'),
               QT_QPA_PLATFORM='offscreen')
    script = r'''
import json, sys
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from qq_chat_analyzer.gui import app
from qq_chat_analyzer.gui.main_window import MainWindow
from qq_chat_analyzer import __file__ as source_file
from update_feed_test_data import local_feed_service
root, mode = Path(sys.argv[1]), sys.argv[2]
service, cached, _, _ = local_feed_service(root)
assert service.check().status == 'available'
assert service.download().status == 'downloaded'
sdk = service._manager
calls = []
class InjectedSDK:
    def __getattr__(self, name): return getattr(sdk, name)
    def wait_exit_then_apply_updates(self, asset, *, silent, restart):
        result = window.shutdown_protocol.result
        assert result.can_apply_update and restart and not silent
        calls.append(asset.Version)
        (root / 'handoff.json').write_text(json.dumps({
            'target': asset.Version, 'source_file': source_file,
            'steps': {s.name: s.status.value for s in result.steps}}))
service._manager = InjectedSDK()
service._package_directory = lambda feed, manager: cached.parent
application = QApplication([])
facade = app.build_facade()
facade._installable_update_service = service
window = MainWindow(facade)
window.show()
QMessageBox.question = lambda *args: QMessageBox.Yes
warnings = []
QMessageBox.warning = lambda *args: warnings.append(args)
prepared = facade.prepare_update_install() if mode == 'direct' else None
def click():
    if mode == 'direct':
        window.request_update_install(prepared)
    else:
        window.show_update_dialog()
        window._update_dialog.install_button.click()
QTimer.singleShot(0, click)
QTimer.singleShot(10000, lambda: application.exit(91))
code = application.exec()
assert code == 0
assert warnings == []
assert calls == []  # never spawn before the exit owner has collected evidence
if mode == 'worker':
    assert window.await_shutdown(5)
    assert window.finish_update_handoff().status == 'started'
    assert window.finish_update_handoff() is None
else:
    app._finish_process_exit(code, window=window)
    app._finish_process_exit(code, window=window)  # repeated exit cannot re-apply
assert window.shutdown_protocol.result.can_apply_update
assert calls == ['0.2.0']
'''
    completed = subprocess.run([sys.executable, '-c', script, str(tmp_path), mode], env=env,
                               cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    recorded = json.loads((tmp_path / 'handoff.json').read_text())
    assert Path(recorded['source_file']).is_relative_to(worktree / 'src')
    assert recorded['target'] == '0.2.0'
    assert recorded['steps'] == dict.fromkeys((
        'direct_db_cleanup', 'retained_output_cleanup', 'qq_runtime_termination',
        'source_lifecycle', 'gui_workers'), 'success')
    assert hashlib.sha256(data.read_bytes()).hexdigest() == before
