"""About action tests with real facade and fictional installation."""
import importlib
import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
from test_setup_uninstall import installation


def _module():
    return importlib.import_module("qq_chat_analyzer.gui.update_dialog")


def _pin_maintenance(monkeypatch, module, *, kind, program_dir, data_dir):
    """Monkeypatch the dialog's install identity and data root per test."""
    monkeypatch.setattr(
        module, "detect_install_location",
        lambda executable, *, frozen: module.InstallLocation(kind, program_dir))
    monkeypatch.setattr(module, "user_data_root", lambda: data_dir)


@pytest.fixture
def window(tmp_path, monkeypatch):
    from qq_chat_analyzer.gui import main_window as module
    app = QApplication.instance() or QApplication([])
    service, root, data, _, calls = installation(tmp_path)
    _pin_maintenance(monkeypatch, _module(), kind=_module().InstallKind.SETUP,
                     program_dir=root, data_dir=data)
    monkeypatch.setattr(module, '_quit_application', lambda: None)
    monkeypatch.setattr(module, 'shutdown_workers', lambda: True)
    facade = ChatAnalyzerFacade(setup_uninstall_service=service)
    page = module.MainWindow(facade)
    page.show()
    page.show_about_page()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[2]))
    yield page, service, calls, warnings
    page.hide()
    page.deleteLater()
    app.processEvents()


def settle(window):
    limit = time.monotonic() + 3
    while window.isVisible() and time.monotonic() < limit:
        QApplication.processEvents()
        time.sleep(.01)


def test_cancel_is_inert_and_reentrant_click_is_ignored(window, monkeypatch):
    page, service, calls, _ = window
    button = page.about_page.maintenance_section.uninstall_button
    assert button.isEnabled()
    questions = []
    def cancel(*args):
        questions.append(args[2])
        page.request_setup_uninstall()
        return QMessageBox.No
    monkeypatch.setattr(QMessageBox, 'question', cancel)
    button.click()
    assert len(questions) == 1
    assert all(word in questions[0] for word in ('程序', '快捷方式', '报告', '配置', '保留'))
    assert not page.shutdown_protocol.started and service._pending is None and calls == []
    assert button.isEnabled()


def test_confirm_shuts_down_before_one_handoff_and_normal_close(window, monkeypatch):
    page, service, calls, warnings = window
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
    button = page.about_page.maintenance_section.uninstall_button
    button.click()
    button.click()
    settle(page)
    assert page.shutdown_protocol.finished
    assert page.shutdown_protocol.result.can_apply_update
    assert len(calls) == 1 and not page.isVisible() and warnings == []
    assert page._facade._shutdown_result is not None


def test_busy_task_refuses_without_shutdown_or_confirmation(window, monkeypatch):
    from qq_chat_analyzer.gui import main_window as module
    page, service, calls, warnings = window
    monkeypatch.setattr(module, 'workers_idle', lambda: False)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: pytest.fail('busy confirmation'))
    page.about_page.maintenance_section.uninstall_button.click()
    assert warnings and not page.shutdown_protocol.started and calls == []


@pytest.mark.parametrize('failure', ['spawn', 'cleanup', 'changed_identity'])
def test_failed_handoff_stays_visible_and_reports_failure(window, monkeypatch, failure):
    page, service, calls, warnings = window
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
    if failure == 'spawn':
        def fail(snapshot):
            raise OSError('fictional failure')
        service._launcher = fail
    elif failure == 'cleanup':
        from qq_chat_analyzer.application.shutdown_models import ShutdownResult
        monkeypatch.setattr(page._facade, 'shutdown', lambda: ShutdownResult())
    else:
        original = service.handoff
        def changed(token, proof):
            service._setup_runtime = lambda: False
            return original(token, proof)
        service.handoff = changed
    page.about_page.maintenance_section.uninstall_button.click()
    limit = time.monotonic() + 3
    while not warnings and time.monotonic() < limit:
        QApplication.processEvents()
        time.sleep(.01)
    assert warnings and page.isVisible() and calls == []
    assert not page.about_page.maintenance_section.uninstall_button.isEnabled()


def test_invalid_identity_never_enables_or_confirms(window, monkeypatch):
    page, service, calls, warnings = window
    service._setup_runtime = lambda: False
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: pytest.fail('invalid confirmation'))
    page.request_setup_uninstall()
    assert calls == [] and not page.shutdown_protocol.started
    assert not page.about_page.maintenance_section.uninstall_button.isEnabled()


def test_timeout_does_not_handoff_or_close(window, monkeypatch):
    page, service, calls, warnings = window
    from qq_chat_analyzer.gui.shutdown import ShutdownProtocol
    page._shutdown_protocol = ShutdownProtocol(wait_seconds=0)
    monkeypatch.setattr(page, 'begin_shutdown', lambda: None)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
    page.about_page.maintenance_section.uninstall_button.click()
    page._poll_uninstall_shutdown()
    assert warnings and calls == [] and page.isVisible()
    assert not page._uninstall_timer.isActive()


def test_task_started_during_confirmation_is_rejected(window, monkeypatch):
    from qq_chat_analyzer.gui import main_window as module
    page, service, calls, warnings = window
    idle = iter([True, False])
    monkeypatch.setattr(module, 'workers_idle', lambda: next(idle))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
    page.about_page.maintenance_section.uninstall_button.click()
    assert warnings and not page.shutdown_protocol.started and calls == []
