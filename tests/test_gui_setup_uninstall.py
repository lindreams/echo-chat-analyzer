"""About action tests with real facade and fictional installation."""
import importlib
import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication, QPushButton

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
    page.activateWindow()
    app.processEvents()
    yield page, service, calls
    page.hide()
    page.deleteLater()
    app.processEvents()


def settle(window):
    limit = time.monotonic() + 3
    while window.isVisible() and time.monotonic() < limit:
        QApplication.processEvents()
        time.sleep(.01)


def confirm_uninstall(page, mode):
    prompt = page.about_page.maintenance_section.uninstall_prompt
    text = '保留报告和普通设置并卸载' if mode == 'keep' else '清除 Echo 本地数据并卸载'
    assert prompt.isVisibleTo(page) and not prompt.isWindow()
    button = next(button for button in prompt.findChildren(QPushButton)
                  if button.isVisible() and button.text() == text)
    button.click()


def test_cancel_is_inert_and_reentrant_click_is_ignored(window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    page, service, calls = window
    button = page.about_page.maintenance_section.uninstall_button
    assert button.isEnabled()
    button.click()
    prompt = page.about_page.maintenance_section.uninstall_prompt
    choices = prompt.findChildren(QPushButton)
    page.request_setup_uninstall()
    assert prompt.findChildren(QPushButton) == choices
    assert {choice.text() for choice in choices} == {
        '取消', '保留报告和普通设置并卸载', '清除 Echo 本地数据并卸载',
    }
    assert not any(choice.isDefault() for choice in choices)
    cancel = next(choice for choice in choices if choice.text() == '取消')
    assert cancel.hasFocus()
    QTest.keyClick(cancel, Qt.Key.Key_Escape)
    assert not prompt.pending
    assert not page.shutdown_protocol.started and service._pending is None and calls == []
    assert button.isEnabled()
    button.click()
    page.show_home_page()
    assert not prompt.pending and service._pending is None and calls == []


@pytest.mark.parametrize('mode', ['keep', 'purge'])
def test_confirm_shuts_down_before_one_handoff_and_normal_close(window, mode):
    page, service, calls = window
    button = page.about_page.maintenance_section.uninstall_button
    button.click()
    button.click()
    assert not page.shutdown_protocol.started and calls == []
    confirm_uninstall(page, mode)
    settle(page)
    assert page.shutdown_protocol.finished
    assert page.shutdown_protocol.result.can_apply_update
    assert len(calls) == 1 and not page.isVisible()
    assert calls[0].cleanup_mode == mode
    assert page._facade._shutdown_result is not None


def test_busy_task_refuses_without_shutdown_or_confirmation(window, monkeypatch):
    from qq_chat_analyzer.gui import main_window as module
    page, service, calls = window
    monkeypatch.setattr(module, 'workers_idle', lambda: False)
    page.about_page.maintenance_section.uninstall_button.click()
    maintenance = page.about_page.maintenance_section
    assert '请等待后台任务' in maintenance.status_label.text()
    assert not maintenance.uninstall_prompt.pending
    assert not page.shutdown_protocol.started and calls == []


@pytest.mark.parametrize('failure', ['spawn', 'cleanup', 'changed_identity'])
def test_failed_handoff_stays_visible_and_reports_failure(window, monkeypatch, failure):
    page, service, calls = window
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
    confirm_uninstall(page, 'keep')
    limit = time.monotonic() + 3
    status = page.about_page.maintenance_section.status_label
    while '请关闭并重新打开' not in status.text() and time.monotonic() < limit:
        QApplication.processEvents()
        time.sleep(.01)
    assert '请关闭并重新打开' in status.text() and page.isVisible() and calls == []
    assert not page.about_page.maintenance_section.uninstall_button.isEnabled()


def test_invalid_identity_never_enables_or_confirms(window):
    page, service, calls = window
    service._setup_runtime = lambda: False
    page.request_setup_uninstall()
    assert calls == [] and not page.shutdown_protocol.started
    assert not page.about_page.maintenance_section.uninstall_prompt.pending
    assert not page.about_page.maintenance_section.uninstall_button.isEnabled()


def test_timeout_does_not_handoff_or_close(window, monkeypatch):
    page, service, calls = window
    from qq_chat_analyzer.gui.shutdown import ShutdownProtocol
    page._shutdown_protocol = ShutdownProtocol(wait_seconds=0)
    monkeypatch.setattr(page, 'begin_shutdown', lambda: None)
    page.about_page.maintenance_section.uninstall_button.click()
    confirm_uninstall(page, 'keep')
    page._poll_uninstall_shutdown()
    assert '安全退出超时' in page.about_page.maintenance_section.status_label.text()
    assert calls == [] and page.isVisible()
    assert not page._uninstall_timer.isActive()


def test_task_started_during_confirmation_is_rejected(window, monkeypatch):
    from qq_chat_analyzer.gui import main_window as module
    page, service, calls = window
    idle = iter([True, False])
    monkeypatch.setattr(module, 'workers_idle', lambda: next(idle))
    page.about_page.maintenance_section.uninstall_button.click()
    confirm_uninstall(page, 'keep')
    assert '请等待后台任务' in page.about_page.maintenance_section.status_label.text()
    assert not page.shutdown_protocol.started and calls == []
