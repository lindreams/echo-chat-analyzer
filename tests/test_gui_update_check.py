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
    dialog = module.UpdatePage(facade, executor=executor)
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
    dialog.close()
    if destroy:
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    task.on_success(UpdateCheckResult("update_available", "7.2.1", "7.3.0"))
    task.on_error("fictional", "迟到错误")
    if not destroy:
        assert dialog.status_label.text() == before


@pytest.mark.parametrize("maximized", [False, True])
def test_main_window_merged_about_uses_main_stack_without_new_windows(app, maximized):
    from qq_chat_analyzer.gui.main_window import MainWindow
    from test_gui import StubFacade
    facade = StubFacade()
    executor = Executor()
    window = MainWindow(facade, executor=executor)
    window.showMaximized() if maximized else window.show()
    app.processEvents()
    geometry, state = window.geometry(), window.windowState()
    top_levels = set(app.topLevelWidgets())
    assert executor.tasks == []
    about = next(b for b in window.home_page.findChildren(QPushButton)
                 if b.accessibleName() == "关于余音")
    about.click()
    page = window.stack.currentWidget()
    assert page is not window.home_page
    assert page.window() is window
    assert set(app.topLevelWidgets()) == top_levels
    assert window.geometry() == geometry and window.windowState() == state
    assert executor.tasks == []
    assert page.maintenance_section.isVisible()
    assert window.stack.count() == 7
    page.back_button.click()
    assert window.stack.currentWidget() is window.home_page
    about.setFocus()
    QTest.keyClick(about, Qt.Key_Space)
    assert window.stack.currentWidget() is page
    assert executor.tasks == []
    assert set(app.topLevelWidgets()) == top_levels
    window.hide()


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
    dialog = module.UpdatePage(Facade(), executor=unavailable_executor)
    dialog.check_button.click()
    assert dialog.check_button.isEnabled()
    assert "重试" in dialog.status_label.text()
    assert "private" not in dialog.status_label.text()
    dialog.close()


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


def _offer_update(dialog, executor):
    dialog.check_button.click()
    executor.tasks[-1].on_success(UpdateCheckResult(
        "update_available", "7.2.1", "7.3.0",
        "https://github.com/lindreams/echo-chat-analyzer/releases/tag/v7.3.0",
    ))


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


def test_every_update_phase_has_an_explicit_presentation():
    module = importlib.import_module("qq_chat_analyzer.gui.update_dialog")
    phase, view = module.UpdatePhase, module.update_presentation
    checking = view(phase.CHECKING)
    assert "正在查询" in checking.text and checking.show_progress
    assert checking.percent is None and not checking.check_enabled
    up_to_date = view(phase.UP_TO_DATE)
    assert "已是最新版本" in up_to_date.text and up_to_date.check_enabled
    assert not up_to_date.show_progress
    available = view(phase.UPDATE_AVAILABLE, latest_version="7.3.0",
                     release_available=True, download_available=True)
    assert "7.3.0" in available.text and available.show_release
    assert available.download_enabled and not available.show_progress
    downloading = view(phase.DOWNLOADING, percent=42.8, download_available=True)
    assert "42%" in downloading.text and downloading.percent == 42
    assert downloading.show_progress and not downloading.download_enabled
    assert "下载完成" in view(phase.DOWNLOAD_COMPLETE).text
    assert "未连接" in view(phase.DOWNLOAD_COMPLETE).text
    assert "暂未发现可安装更新" in view(phase.NO_UPDATE).text
    failed = view(phase.FAILED, message="虚构失败")
    assert failed.text == "虚构失败" and failed.check_enabled


def test_no_download_action_exists_for_release_only_facade(ui):
    dialog, _, executor = ui
    assert not dialog.download_button.isVisible()
    assert not dialog.progress_bar.isVisible()
    _offer_update(dialog, executor)
    assert "7.3.0" in dialog.status_label.text()
    assert dialog.release_button.isVisible()
    assert not dialog.download_button.isVisible()


def test_facade_download_shows_percent_and_only_completes_on_result(update_ui):
    dialog, executor, facade = update_ui
    _offer_installable(dialog, executor)
    assert dialog.download_button.isVisible() and dialog.download_button.isEnabled()
    dialog.download_button.click()
    assert len(executor.tasks) == 2
    assert facade.downloads == []
    task = executor.tasks[1]
    task.on_progress(42)
    assert "42%" in dialog.status_label.text()
    assert dialog.progress_bar.isVisible() and dialog.progress_bar.value() == 42
    assert "下载完成" not in dialog.status_label.text()
    facade.result = InstallableUpdateResult("downloaded", "7.2.1", "7.3.0", 100)
    task.on_success(facade.result)
    assert "下载完成" in dialog.status_label.text()


def test_dialog_without_install_facade_offers_no_install_or_restart_action(update_ui):
    dialog, executor, facade = update_ui
    _offer_installable(dialog, executor)
    dialog.download_button.click()
    task = executor.tasks[1]
    task.on_success(task.operation(task.on_progress))
    labels = [button.text() for button in dialog.findChildren(QPushButton)
              if button.isVisible()]
    assert not any("安装" in label or "重启" in label for label in labels)


def test_unknown_progress_reports_never_invent_a_state(update_ui):
    dialog, executor, _ = update_ui
    _offer_installable(dialog, executor)
    dialog.download_button.click()
    task = executor.tasks[1]
    task.on_progress(10)
    before = dialog.status_label.text()
    for report in [object(), None, "downloading", {"phase": "downloading"},
                   SimpleNamespace(phase="download_complete"), True, float("nan")]:
        task.on_progress(report)
    assert dialog.status_label.text() == before
    assert dialog.progress_bar.value() == 10


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


def test_repeated_download_clicks_submit_exactly_one_download(update_ui):
    dialog, executor, facade = update_ui
    _offer_installable(dialog, executor)
    dialog.download_button.click()
    dialog.download_button.click()
    dialog.download_button.click()
    assert len(executor.tasks) == 2
    assert facade.downloads == []
    assert not dialog.download_button.isEnabled()
    assert not dialog.check_button.isEnabled()


def test_download_worker_failure_is_visible_and_retryable(update_ui):
    dialog, executor, _ = update_ui
    _offer_installable(dialog, executor)
    dialog.download_button.click()
    executor.tasks[1].on_error("fictional", "虚构下载失败，请重试")
    assert "虚构下载失败" in dialog.status_label.text()
    assert dialog.download_button.isVisible() and dialog.download_button.isEnabled()
    assert not dialog.progress_bar.isVisible()
    assert dialog.check_button.isEnabled()
    dialog.download_button.click()
    assert len(executor.tasks) == 3
    executor.tasks[2].on_progress(7)
    assert dialog.progress_bar.isVisible() and dialog.progress_bar.value() == 7


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


def test_a_finished_attempt_cannot_fall_back_to_downloading(update_ui):
    dialog, executor, _ = update_ui
    _offer_installable(dialog, executor)
    dialog.download_button.click()
    task = executor.tasks[1]
    task.on_success(task.operation(task.on_progress))
    completed = dialog.status_label.text()
    task.on_progress(5)
    task.on_error("late", "late failure")
    assert dialog.status_label.text() == completed
    assert not dialog.progress_bar.isVisible()
    assert not dialog.download_button.isVisible()


def test_browser_failure_message_is_rendered_not_written_around(ui, monkeypatch):
    dialog, _, executor = ui
    module = importlib.import_module("qq_chat_analyzer.gui.update_dialog")
    monkeypatch.setattr(module.QDesktopServices, "openUrl", lambda _url: False)
    _offer_update(dialog, executor)
    dialog.release_button.click()
    assert "无法打开" in dialog.status_label.text()
    dialog._render()
    assert "无法打开" in dialog.status_label.text()
    assert dialog.release_button.isVisible() and dialog.release_button.isEnabled()
    dialog.check_button.click()
    assert "无法打开" not in dialog.status_label.text()


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


def test_real_worker_runs_off_gui_thread_and_returns_on_gui_thread(app):
    import threading
    import time
    module = importlib.import_module("qq_chat_analyzer.gui.update_dialog")
    seen = []
    class ThreadFacade:
        def check_for_updates(self, *, manual):
            seen.append((manual, QThread.currentThread() == app.thread()))
            return UpdateCheckResult("up_to_date", "7.2.1")
    dialog = module.UpdatePage(ThreadFacade())
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
