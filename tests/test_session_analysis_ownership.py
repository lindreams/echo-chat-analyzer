"""Deterministic GUI ownership regressions using fictional sessions."""

from __future__ import annotations

import os
import threading
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox

from qq_chat_analyzer.application.facade import AnalysisPhase, ChatSource, FacadeError, SessionInfo
from qq_chat_analyzer.gui import workers
from qq_chat_analyzer.gui.main_window import MainWindow, PROCESSING_PAGE_INDEX
from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class HeldExecutor:
    """Use production workers but explicitly control when they run."""

    def __init__(self):
        self.tasks = []

    def start(self, worker):
        self.tasks.append(worker)

    def __call__(self, operation, **callbacks):
        return workers.submit(operation, pool=self, **callbacks)


def drain(app):
    for _ in range(4):
        app.processEvents()


def run_background(worker):
    thread = threading.Thread(target=worker.run, daemon=True)
    thread.start()
    thread.join(3)
    assert not thread.is_alive(), "Fictional worker did not complete"


@pytest.fixture
def make_panel(app):
    resources = []

    def make(source, facade=None, *, window=False):
        executor = HeldExecutor()
        facade = facade or SimpleNamespace()
        owner = MainWindow(facade, executor=executor) if window else SessionAnalysisPanel()
        if window:
            workspace = owner.qq_workspace if source is ChatSource.QQ else owner.wechat_workspace
            panel = workspace.session_panel
        else:
            panel = owner
        panel.configure(facade, source, executor)
        panel.populate_sessions([
            SessionInfo(source=source, session_id=name, display_name=name,
                        message_count=2)
            for name in ("fiction-A", "fiction-B")
        ])
        panel._session_list.setCurrentRow(0)
        resources.append((owner, panel, executor))
        return panel, executor

    yield make
    for owner, panel, executor in resources:
        panel.cancel_analysis()
        # Release every production relay, including workers never started.
        for worker in executor.tasks:
            worker.cancel()
            if worker in workers._PENDING:
                run_background(worker)
        drain(app)
        owner.deleteLater()
    drain(app)


@pytest.mark.parametrize("source", [ChatSource.QQ, ChatSource.WECHAT])
def test_old_finished_preserves_retry_task_and_cancellation(app, make_panel, source):
    panel, executor = make_panel(source)
    panel.start_analysis()
    drain(app)
    old = panel._analysis_task
    panel.cancel_analysis()
    panel.start_analysis()
    drain(app)
    current = panel._analysis_task

    run_background(old)  # Cancellation still emits finished through Qt.
    drain(app)
    assert panel._analysis_task is current
    assert panel._analysis_running
    assert not panel.isEnabled()
    panel.cancel_analysis()
    assert current._cancelled.is_set()


@pytest.mark.parametrize("source", [ChatSource.QQ, ChatSource.WECHAT])
@pytest.mark.parametrize("event", ["phase", "progress", "success", "error"])
def test_queued_old_callbacks_cannot_reach_retry_ui(
    app, make_panel, monkeypatch, source, event,
):
    outcome = object()

    def analyze(*args, progress, on_phase, cancelled=lambda: False):
        if event == "error":
            raise FacadeError(code="fiction-old", public_message="fiction-old")
        if event == "progress":
            progress("fiction-old-progress")
        if event == "phase":
            on_phase(AnalysisPhase.ANALYZING_REPORT)
        return outcome

    panel, executor = make_panel(
        source, SimpleNamespace(analyze_session=analyze), window=True,
    )
    window = panel.window()
    dialogs = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: dialogs.append(args[-1]))
    statuses, successes, errors = [], [], []
    panel.status_changed.connect(statuses.append)
    panel.analysis_succeeded.connect(successes.append)
    panel.analysis_failed.connect(lambda *error: errors.append(error))
    panel.start_analysis()
    drain(app)
    old = panel._analysis_task
    # Emit on a background thread without dispatching GUI events yet.
    run_background(old)
    assert not successes and not errors
    panel.cancel_analysis()
    panel._session_list.setCurrentRow(1)
    panel.start_analysis()
    expected_status = window._status_label.text()
    drain(app)

    assert "fiction-old-progress" not in statuses
    assert successes == []
    assert errors == []
    assert panel._analysis_running
    assert panel._analysis_task is executor.tasks[-1]
    assert window.stack.currentIndex() == PROCESSING_PAGE_INDEX
    assert window._status_label.text() == expected_status
    assert window.processing_page.phase is AnalysisPhase.READING
    assert dialogs == []

    # The current operation must still deliver all normal callbacks.
    run_background(panel._analysis_task)
    drain(app)
    assert not panel._analysis_running
    assert panel._analysis_task is None
    if event == "error":
        assert errors == [("fiction-old", "fiction-old")]
        assert dialogs == ["fiction-old"]
    else:
        assert successes == [outcome]
        if event == "progress":
            assert statuses.count("fiction-old-progress") == 1


@pytest.mark.parametrize("source", [ChatSource.QQ, ChatSource.WECHAT])
def test_inline_finished_does_not_retain_completed_task(app, make_panel, source):
    panel, _ = make_panel(source)
    completed = object()

    def inline(operation, *, on_success, on_error, on_finished, on_progress):
        on_success(object())
        on_finished()
        return completed

    panel.configure(SimpleNamespace(), source, inline)
    panel.start_analysis()
    drain(app)
    assert panel._analysis_task is None
    assert not panel._analysis_running


@pytest.mark.parametrize("source", [ChatSource.QQ, ChatSource.WECHAT])
@pytest.mark.parametrize("retry", [False, True])
def test_cancel_before_deferred_submit_does_not_launch_old_worker(
    app, make_panel, source, retry,
):
    panel, executor = make_panel(source)
    panel.start_analysis()
    panel.cancel_analysis()
    if retry:
        panel.start_analysis()
    drain(app)
    assert len(executor.tasks) == int(retry)
    assert panel._analysis_running is retry
    if retry:
        assert panel._analysis_task is executor.tasks[0]
        panel.cancel_analysis()
        assert executor.tasks[0]._cancelled.is_set()


def test_wechat_old_range_cannot_change_current_session_config(app, make_panel):
    def message_range(source, session):
        return (946684800, 978307200) if session == "fiction-A" else (
            1577836800, 1609459200
        )

    panel, executor = make_panel(
        ChatSource.WECHAT, SimpleNamespace(get_session_message_range=message_range)
    )
    old = executor.tasks[-1]
    panel._session_list.setCurrentRow(1)
    current = executor.tasks[-1]
    panel._scope_custom.setChecked(True)
    run_background(current)
    drain(app)
    expected = panel.build_config()
    assert expected.start_time == "2020-01-01"
    run_background(old)
    drain(app)
    assert panel.selected_session_id() == "fiction-B"
    assert panel.build_config() == expected


@pytest.mark.parametrize("change", ["clear", "source"])
def test_wechat_range_request_invalidated_by_panel_changes(app, make_panel, change):
    panel, executor = make_panel(
        ChatSource.WECHAT,
        SimpleNamespace(get_session_message_range=lambda *_: (946684800, 978307200)),
    )
    old = executor.tasks[-1]
    if change == "clear":
        panel.clear()
    elif change == "source":
        panel.configure(SimpleNamespace(), ChatSource.QQ)
    panel._scope_custom.setChecked(True)
    expected = panel.build_config()
    run_background(old)
    drain(app)
    assert panel._message_range is None
    assert panel.build_config() == expected
