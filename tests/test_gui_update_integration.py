"""GUI -> real Facade -> real update core; only the external SDK is fictional."""
import os
import sys
import time
from threading import Event

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
from qq_chat_analyzer.application.installable_update_service import InstallableUpdateResult
from qq_chat_analyzer.application.update_check_service import UpdateCheckService
from qq_chat_analyzer.gui.update_dialog import UpdatePage
from test_gui_update_check import Executor
from test_installable_update_service import service


@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def integrated(tmp_path, app):
    core, manager = service(tmp_path)
    releases = []
    def fetch():
        releases.append(True)
        return dict(tag_name='v7.3.0', draft=False, prerelease=False,
                    package_id='Lindreams.Echo', channel='win-x64-stable',
                    html_url='https://cnb.cool/echo_mly/echo_releases/-/releases/tag/v7.3.0')
    facade = ChatAnalyzerFacade(installable_update_service=core,
        update_check_service=UpdateCheckService(state_path=tmp_path / 'attempt.json', fetch_release=fetch))
    executor = Executor()
    dialog = UpdatePage(facade, executor=executor)
    dialog.show()
    app.processEvents()
    yield dialog, executor, facade, core, manager, releases
    if isValid(dialog):
        dialog.close()
    app.processEvents()


def run(task):
    if hasattr(task, 'on_progress'):
        result = task.operation(task.on_progress)
    else:
        result = task.operation()
    task.on_success(result)
    return result


def wait(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert predicate()


def test_real_facade_check_download_and_reopen(integrated, app):
    dialog, executor, facade, core, manager, releases = integrated
    assert executor.tasks == []
    dialog.check_button.click()
    result = run(executor.tasks[-1])
    assert result.status == 'available'
    assert releases == []  # installable feed must not consume release-page metadata
    assert dialog.download_button.isVisible()
    dialog.download_button.click()
    assert run(executor.tasks[-1]).status == 'downloaded'
    assert '下载完成' in dialog.status_label.text()
    assert '重启余音后完成安装' not in dialog.status_label.text()
    assert not dialog.download_button.isVisible()
    dialog.close()
    reopened = UpdatePage(facade, executor=executor)
    reopened.show()
    assert '下载完成' in reopened.status_label.text()
    assert len(executor.tasks) == 2
    reopened.close()


def test_failure_result_can_retry_and_late_progress_is_ignored(integrated):
    dialog, executor, _, core, manager, _ = integrated
    dialog.check_button.click()
    run(executor.tasks[-1])
    dialog.download_button.click()
    first = executor.tasks[-1]
    manager.failure = OSError('fictional private path')
    assert run(first).status == 'failed'
    failed = dialog.status_label.text()
    assert '下载完成' not in failed and 'private' not in failed
    assert dialog.download_button.isEnabled()
    first.on_progress(100)
    assert dialog.status_label.text() == failed
    dialog.download_button.click()
    manager.failure = None
    run(executor.tasks[-1])
    completed = dialog.status_label.text()
    first.on_success(InstallableUpdateResult('failed', public_message='late failure'))
    first.on_error('late', 'late failure')
    first.on_progress(1)
    assert dialog.status_label.text() == completed


def test_progress_cannot_invent_success_or_go_backwards(integrated):
    dialog, executor, _, _, _, _ = integrated
    dialog.check_button.click()
    run(executor.tasks[-1])
    dialog.download_button.click()
    dialog.download_button.click()
    assert len(executor.tasks) == 2
    task = executor.tasks[-1]
    task.on_progress(65)
    task.on_progress(20)
    assert dialog.progress_bar.value() == 65
    task.on_progress(100)
    assert '下载完成' not in dialog.status_label.text()
    assert dialog.progress_bar.value() < 100
    task.on_success(InstallableUpdateResult('failed', public_message='虚构失败'))
    assert '虚构失败' in dialog.status_label.text()


@pytest.mark.parametrize('mode', ['source', 'portable', 'unconfigured'])
def test_non_setup_or_missing_feed_only_checks_release_page(integrated, mode):
    dialog, executor, _, core, manager, releases = integrated
    if mode == 'source':
        core._setup_runtime = lambda: False
    elif mode == 'portable':
        manager.portable = True
    else:
        core._feed = None
    dialog.check_button.click()
    run(executor.tasks[-1])
    assert releases == [True]
    assert dialog.release_button.isVisible()
    assert not dialog.download_button.isVisible()
    assert manager.checks == manager.downloads == 0


def test_real_worker_closed_dialog_and_reopened_observer(integrated, app):
    _, _, facade, core, manager, _ = integrated
    entered, release = Event(), Event()
    thread_evidence = []
    def hold():
        thread_evidence.append(QThread.currentThread() == app.thread())
        entered.set()
        assert release.wait(5)
    core.check()
    manager.hook = hold
    dialog = UpdatePage(facade)
    dialog.show()
    dialog.download_button.click()
    observer = None
    try:
        wait(app, entered.is_set)
        dialog.close()
        observer = UpdatePage(facade)
        observer.show()
        assert '正在下载' in observer.status_label.text()
        assert not observer.check_button.isEnabled()
        ui_threads = []
        render = observer._render
        def checked_render():
            ui_threads.append(QThread.currentThread() == app.thread())
            render()
        observer._render = checked_render
        release.set()
        wait(app, lambda: '下载完成' in observer.status_label.text())
        assert thread_evidence == [False]
        assert ui_threads and all(ui_threads)
        assert manager.downloads == 1
    finally:
        release.set()
        wait(app, lambda: core.get_status().status != 'downloading')
        if isValid(dialog):
            dialog.close()
        if observer is not None:
            observer.close()


@pytest.mark.slow_integration
@pytest.mark.skipif(sys.platform != 'win32', reason='Windows Setup SDK boundary')
@pytest.mark.parametrize('corrupt', [False, True])
def test_gui_real_sdk_local_feed_download_and_retry(tmp_path, app, corrupt):
    from update_feed_test_data import local_feed_service
    core, cached, package, content = local_feed_service(tmp_path, corrupt=corrupt)
    facade = ChatAnalyzerFacade(installable_update_service=core)
    dialog = UpdatePage(facade)
    dialog.show()
    renders = []
    render = dialog._render
    def checked_render():
        renders.append(QThread.currentThread() == app.thread())
        render()
    dialog._render = checked_render
    try:
        dialog.check_button.click()
        wait(app, lambda: dialog.download_button.isVisible())
        dialog.download_button.click()
        if corrupt:
            wait(app, lambda: core.get_status().status == 'failed' and dialog.download_button.isEnabled())
            assert not cached.exists()
            assert '下载完成' not in dialog.status_label.text()
            package.write_bytes(content)
            dialog.download_button.click()
        wait(app, lambda: '下载完成' in dialog.status_label.text())
        assert cached.read_bytes() == content
        assert core.get_status().status == 'downloaded'
        assert renders and all(renders)
    finally:
        wait(app, lambda: core.get_status().status not in ('checking', 'downloading'))
        dialog.close()
