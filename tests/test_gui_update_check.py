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
    dialog = module.UpdateDialog(facade, executor=executor)
    dialog.show()
    app.processEvents()
    yield dialog, facade, executor
    from shiboken6 import isValid
    if isValid(dialog):
        dialog.close()
    app.processEvents()


def test_home_about_entry_exists_without_replacing_navigation(app):
    from qq_chat_analyzer.gui.home_page import HomePage
    page = HomePage()
    intents = []
    page.navigate_requested.connect(intents.append)
    about = next((b for b in page.findChildren(QPushButton)
                  if b.accessibleName() == "关于余音"), None)
    assert about is not None
    for button in (page._qq_btn, page._wechat_btn, page._local_data_btn, about):
        button.click()
    assert intents == ["qq", "wechat", "local_data", "about"]
    for width, height in [(800, 560), (1200, 728)]:
        page.resize(width, height)
        page.show()
        app.processEvents()
        a = about.mapTo(page, about.rect().topLeft())
        r = page._local_data_btn.mapTo(page, page._local_data_btn.rect().topLeft())
        assert a.y() == r.y()
        assert a.x() + about.width() <= r.x()
        assert r.x() + page._local_data_btn.width() <= width
    page.close()


def test_open_is_offline_and_version_uses_authoritative_source(app, monkeypatch):
    from qq_chat_analyzer import version
    monkeypatch.setattr(version, "APP_VERSION", "7.2.1+fictional")
    module = importlib.import_module("qq_chat_analyzer.gui.update_dialog")
    facade, executor = Facade(), Executor()
    dialog = module.UpdateDialog(facade, executor=executor)
    assert "7.2.1+fictional" in dialog.version_label.text()
    assert executor.tasks == [] and facade.calls == []
    dialog.close()


def test_manual_check_prevents_duplicate_submission(ui):
    dialog, facade, executor = ui
    dialog.check_button.click()
    dialog.check_button.click()
    assert len(executor.tasks) == 1
    assert not dialog.check_button.isEnabled()
    task = executor.tasks[0]
    task.on_success(task.operation())
    assert facade.calls == [True]
    assert dialog.check_button.isEnabled()


@pytest.mark.parametrize("status,expected", [
    ("update_available", "7.3.0"), ("up_to_date", "已是最新版本"),
    ("no_release", "暂无正式发布"), ("skipped", "未执行"),
    ("unavailable", "虚构网络不可用"),
])
def test_five_result_states(ui, status, expected):
    dialog, _, executor = ui
    dialog.check_button.click()
    executor.tasks[0].on_success(UpdateCheckResult(
        status, "7.2.1", "7.3.0",
        "https://github.com/lindreams/echo-chat-analyzer/releases/tag/v7.3.0",
        public_message="虚构网络不可用" if status == "unavailable" else None,
    ))
    assert expected in dialog.status_label.text()
    assert dialog.release_button.isVisible() == (status == "update_available")
    assert dialog.check_button.isEnabled()


def test_worker_failure_allows_retry_and_clears_old_link(ui):
    dialog, _, executor = ui
    dialog.check_button.click()
    executor.tasks[0].on_error("fictional", "虚构失败，请重试")
    assert dialog.status_label.text() == "虚构失败，请重试"
    dialog.check_button.click()
    assert len(executor.tasks) == 2
    assert not dialog.release_button.isVisible()


@pytest.mark.parametrize("url", [None, "", "http://github.com/lindreams/echo-chat-analyzer/releases/tag/v7",
    "https://evil.example/releases/tag/v7", "https://github.com/other/repo/releases/tag/v7",
    "https://github.com/lindreams/echo-chat-analyzer/releases/download/v7/app.exe",
    "https://github.com/lindreams/echo-chat-analyzer/releases/tag/v7?download=1",
    "https://github.com/lindreams/echo-chat-analyzer/releases/tag/",
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


@pytest.mark.parametrize("failure", [False, OSError("fictional browser error")])
def test_browser_failure_is_visible_and_link_can_retry(ui, monkeypatch, failure):
    dialog, _, executor = ui
    module = importlib.import_module("qq_chat_analyzer.gui.update_dialog")
    opened = []
    url = "https://github.com/lindreams/echo-chat-analyzer/releases/tag/v7.3.0"
    def open_url(value):
        opened.append(value.toString())
        if isinstance(failure, Exception):
            raise failure
        return failure
    monkeypatch.setattr(module.QDesktopServices, "openUrl", open_url)
    dialog.check_button.click()
    executor.tasks[0].on_success(UpdateCheckResult("update_available", "7.2.1", "7.3.0", url))
    dialog.release_button.click()
    assert opened == [url]
    assert "无法打开" in dialog.status_label.text()
    assert dialog.release_button.isEnabled()


@pytest.mark.parametrize("destroy", [False, True])
def test_late_callbacks_after_close_never_touch_widgets(ui, app, destroy):
    dialog, _, executor = ui
    dialog.check_button.click()
    task = executor.tasks[0]
    before = dialog.status_label.text()
    dialog.reject()
    if destroy:
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    task.on_success(UpdateCheckResult("update_available", "7.2.1", "7.3.0"))
    task.on_error("fictional", "迟到错误")
    if not destroy:
        assert dialog.status_label.text() == before


def test_main_window_about_is_offline_and_keeps_home(app):
    from qq_chat_analyzer.gui.main_window import MainWindow
    from test_gui import StubFacade
    facade = StubFacade()
    executor = Executor()
    window = MainWindow(facade, executor=executor)
    window.show()
    assert executor.tasks == []
    about = next(b for b in window.home_page.findChildren(QPushButton)
                 if b.accessibleName() == "关于余音")
    about.click()
    from qq_chat_analyzer.gui.update_dialog import UpdateDialog
    dialogs = window.findChildren(UpdateDialog)
    assert len(dialogs) == 1 and dialogs[0].isVisible()
    assert window.stack.currentWidget() is window.home_page
    assert executor.tasks == []
    about.click()
    assert len(window.findChildren(UpdateDialog)) == 1
    dialogs[0].reject()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    about.setFocus()
    QTest.keyClick(about, Qt.Key_Space)
    assert window._update_dialog.isVisible()
    window._update_dialog.reject()
    window.hide()


def test_successful_browser_open_and_retry_removes_previous_link(ui, monkeypatch):
    dialog, _, executor = ui
    module = importlib.import_module("qq_chat_analyzer.gui.update_dialog")
    opened = []
    monkeypatch.setattr(module.QDesktopServices, "openUrl", lambda u: opened.append(u.toString()) or True)
    url = "https://github.com/lindreams/echo-chat-analyzer/releases/tag/v7.3.0"
    dialog.check_button.click()
    executor.tasks[0].on_success(UpdateCheckResult("update_available", "7.2.1", "7.3.0", url))
    dialog.release_button.click()
    assert opened == [url]
    dialog.check_button.click()
    assert not dialog.release_button.isVisible()
    executor.tasks[1].on_success(UpdateCheckResult("no_release", "7.2.1"))
    dialog.release_button.click()
    assert opened == [url]


def test_submission_failure_allows_retry(app):
    module = importlib.import_module("qq_chat_analyzer.gui.update_dialog")
    def unavailable_executor(*args, **kwargs):
        raise RuntimeError("fictional private detail")
    dialog = module.UpdateDialog(Facade(), executor=unavailable_executor)
    dialog.check_button.click()
    assert dialog.check_button.isEnabled()
    assert "重试" in dialog.status_label.text()
    assert "private" not in dialog.status_label.text()
    dialog.close()


def test_real_worker_runs_off_gui_thread_and_returns_on_gui_thread(app):
    import threading
    import time
    module = importlib.import_module("qq_chat_analyzer.gui.update_dialog")
    seen = []
    class ThreadFacade:
        def check_for_updates(self, *, manual):
            seen.append((manual, QThread.currentThread() == app.thread()))
            return UpdateCheckResult("up_to_date", "7.2.1")
    dialog = module.UpdateDialog(ThreadFacade())
    delivered = threading.Event()
    original = dialog._show_result
    def show_result(result):
        seen.append(QThread.currentThread() == app.thread())
        original(result)
        delivered.set()
    dialog._show_result = show_result
    dialog.check_button.click()
    deadline = time.monotonic() + 3
    while not delivered.is_set() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert delivered.is_set()
    assert seen == [(True, False), True]
    assert "已是最新版本" in dialog.status_label.text()
    dialog.close()
