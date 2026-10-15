"""Offline update UI contracts using fictional versions and controlled workers."""
import importlib
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication, QEvent, QThread, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from qq_chat_analyzer.application.facade import UpdateCheckResult
from qq_chat_analyzer.application.installable_update_service import InstallableUpdateResult


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


class Executor:
    def __init__(self):
        self.tasks = []

    def __call__(self, operation, **callbacks):
        task = SimpleNamespace(operation=operation, **callbacks)
        self.tasks.append(task)
        return task


class Facade:
    def __init__(self):
        self.calls = []

    def check_for_updates(self, *, manual=False):
        self.calls.append(manual)
        return UpdateCheckResult("up_to_date", "7.2.1")


@pytest.fixture
def ui(app):
    module = importlib.import_module("qq_chat_analyzer.gui.update_dialog")
    facade, executor = Facade(), Executor()
    dialog = module.UpdatePage(facade, executor=executor)
    dialog.show()
    app.processEvents()
    yield dialog, facade, executor
    from shiboken6 import isValid
    if isValid(dialog):
        dialog.close()
    app.processEvents()


@pytest.mark.parametrize("url", [None,
    "https://evil.example/releases/tag/v7",
    "https://github.com/lindreams/echo-chat-analyzer/releases/download/v7/app.exe",
    "https://github.com@evil.example/lindreams/echo-chat-analyzer/releases/tag/v7"])
def test_missing_or_unsafe_release_url_cannot_open(ui, monkeypatch, url):
    dialog, _, executor = ui
    opened = []
    module = importlib.import_module("qq_chat_analyzer.gui.update_dialog")
    monkeypatch.setattr(module.QDesktopServices, "openUrl", lambda u: opened.append(u) or True)
    dialog.check_button.click()
    executor.tasks[0].on_success(UpdateCheckResult("update_available", "7.2.1", "7.3.0", url))
    assert not dialog.release_button.isVisible()
    dialog.release_button.click()
    assert opened == []


@pytest.mark.parametrize("destroy", [False, True])
def test_late_callbacks_after_close_never_touch_widgets(ui, app, destroy):
    dialog, _, executor = ui
    dialog.check_button.click()
    task = executor.tasks[0]
    before = dialog.status_label.text()
    dialog.close()
    if destroy:
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    task.on_success(UpdateCheckResult("update_available", "7.2.1", "7.3.0"))
    task.on_error("fictional", "迟到错误")
    if not destroy:
        assert dialog.status_label.text() == before


def test_main_window_navigation_keeps_download_progress_and_install_handoff(app, monkeypatch):
    from qq_chat_analyzer.gui.main_window import MainWindow
    from qq_chat_analyzer.application.facade import InstallHandoffResult
    from test_gui import StubFacade
    module = importlib.import_module("qq_chat_analyzer.gui.update_dialog")
    facade = StubFacade()
    facade.get_update_status = lambda: InstallableUpdateResult("available", "0.1.0", "0.2.0")
    facade.download_update = lambda **kwargs: None
    facade.prepare_update_install = lambda: InstallHandoffResult("ready", token="fictional-token")
    executor = Executor()
    window = MainWindow(facade, executor=executor)
    prepared = []
    monkeypatch.setattr(window, "request_update_install", prepared.append)
    confirmations = []
    def confirm(*args):
        confirmations.append(args[2])
        return module.QMessageBox.Yes
    monkeypatch.setattr(module.QMessageBox, "question", confirm)
    window.show()
    window.home_page._about_btn.click()
    page = window.stack.currentWidget()
    page.download_button.click()
    task = executor.tasks[0]
    task.on_progress(35)
    page.back_button.click()
    task.on_progress(68)
    window.home_page._about_btn.click()
    assert page.progress_bar.value() == 68
    assert not page.check_button.isEnabled()
    page.back_button.click()
    task.on_success(InstallableUpdateResult("downloaded", "0.1.0", "0.2.0", 100))
    facade.get_update_status = lambda: InstallableUpdateResult("downloaded", "0.1.0", "0.2.0", 100)
    window.home_page._about_btn.click()
    assert window.stack.currentWidget() is page
    assert page.install_button.isVisible() and page.install_button.isEnabled()
    page.install_button.click()
    assert len(confirmations) == 1
    assert all(word in confirmations[0] for word in ('关闭', '安装', '自动重启'))
    install_task = executor.tasks[-1]
    install_task.on_success(install_task.operation())
    app.processEvents()
    assert len(prepared) == 1 and prepared[0].token == "fictional-token"
    assert len(executor.tasks) == 2
    page.close()
    assert not page._status_timer.isActive()
    task.on_progress(1)
    window.hide()


class InstallableFacade(Facade):
    """Fictional Facade implementing the actual A3 public contract."""

    def __init__(self):
        super().__init__()
        self.result = InstallableUpdateResult("idle")
        self.downloads = []

    def get_update_status(self):
        return self.result

    def check_installable_update(self):
        self.result = InstallableUpdateResult("available", "7.2.1", "7.3.0")
        return self.result

    def download_update(self, *, progress=None):
        self.downloads.append(True)
        progress(30)
        self.result = InstallableUpdateResult("downloaded", "7.2.1", "7.3.0", 100)
        return self.result


def _offer_installable(dialog, executor):
    dialog.check_button.click()
    task = executor.tasks[-1]
    task.on_success(task.operation())


@pytest.fixture
def update_ui(app):
    """About dialog with a fictional Facade, never a second updater."""
    module = importlib.import_module("qq_chat_analyzer.gui.update_dialog")
    executor, facade = Executor(), InstallableFacade()
    dialog = module.UpdatePage(facade, executor=executor)
    dialog.show()
    app.processEvents()
    yield dialog, executor, facade
    from shiboken6 import isValid
    if isValid(dialog):
        dialog.close()
    app.processEvents()


def test_download_percent_is_monotonic_and_cannot_confirm_completion(update_ui):
    dialog, executor, _ = update_ui
    _offer_installable(dialog, executor)
    dialog.download_button.click()
    task = executor.tasks[1]
    task.on_progress(40)
    task.on_progress(12)
    assert dialog.progress_bar.value() == 40
    task.on_progress(240)
    assert dialog.progress_bar.value() == 99
    assert "下载完成" not in dialog.status_label.text()
    task.on_progress(float("nan"))
    task.on_progress(True)
    assert dialog.progress_bar.value() == 99


def test_a_late_check_result_cannot_overwrite_a_started_download(update_ui):
    dialog, executor, _ = update_ui
    _offer_installable(dialog, executor)
    check_task = executor.tasks[0]
    dialog.download_button.click()
    executor.tasks[1].on_progress(55)
    check_task.on_success(UpdateCheckResult("up_to_date", "7.2.1"))
    check_task.on_error("fictional", "迟到的失败")
    assert "55%" in dialog.status_label.text()
    assert dialog.progress_bar.value() == 55


def test_a_check_cannot_discard_a_downloaded_update(update_ui):
    dialog, executor, facade = update_ui
    _offer_installable(dialog, executor)
    dialog.download_button.click()
    task = executor.tasks[1]
    task.on_success(task.operation(task.on_progress))
    staged = dialog.status_label.text()
    assert "下载完成" in staged
    assert not dialog.check_button.isEnabled()
    dialog._check()
    assert len(executor.tasks) == 2
    assert dialog.status_label.text() == staged
    task.on_success("late invalid result")
    assert dialog.status_label.text() == staged


@pytest.mark.parametrize("destroy", [False, True])
def test_download_progress_after_close_never_touches_widgets(update_ui, app, destroy):
    dialog, executor, _ = update_ui
    _offer_installable(dialog, executor)
    dialog.download_button.click()
    task = executor.tasks[1]
    before = dialog.status_label.text()
    dialog.close()
    if destroy:
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    task.on_progress(99)
    task.on_success(InstallableUpdateResult("downloaded", progress=100))
    task.on_error("fictional", "迟到的失败")
    if not destroy:
        assert dialog.status_label.text() == before


def test_real_worker_downloads_off_thread_and_relays_progress_to_gui_thread(app):
    import time
    module = importlib.import_module("qq_chat_analyzer.gui.update_dialog")
    seen = []

    class ThreadFacade(InstallableFacade):
        def download_update(self, *, progress=None):
            seen.append(("download", QThread.currentThread() == app.thread()))
            return super().download_update(progress=progress)

    dialog = module.UpdatePage(ThreadFacade())
    dialog.show()
    app.processEvents()
    original = dialog._apply_progress

    def apply_progress(report):
        seen.append(("progress", QThread.currentThread() == app.thread()))
        original(report)

    dialog._apply_progress = apply_progress

    def wait_for(predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(5)
        return predicate()

    dialog.check_button.click()
    assert wait_for(lambda: dialog.download_button.isVisible())
    dialog.download_button.click()
    assert wait_for(lambda: "下载完成" in dialog.status_label.text())
    assert seen == [("download", False), ("progress", True)]
    assert "30%" not in dialog.status_label.text()
    dialog.close()
