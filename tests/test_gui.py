"""Behavior tests for the PySide6 GUI layer.

These tests never open a real window: Qt runs on the ``offscreen`` platform
and every facade call is served by a stub. The GUI is verified as a pure
consumer of the facade.
"""

from __future__ import annotations

import dataclasses
import importlib
import os
import sys
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 is required for the GUI layer")

from PySide6.QtCore import QDate, QThreadPool, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QSizePolicy  # noqa: E402


def _facade_module():
    return importlib.import_module("qq_chat_analyzer.application.facade")


def _presentation():
    return importlib.import_module("qq_chat_analyzer.presentation")


def _analysis_models():
    return importlib.import_module("qq_chat_analyzer.analysis.models")


@pytest.fixture(scope="session")
def qt_app():
    """One QApplication for the whole session; Qt forbids more than one."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def sources():
    module = _facade_module()
    return (
        module.SourceInfo(
            source=module.ChatSource.QQ,
            display_name="QQ",
            available=True,
        ),
        module.SourceInfo(
            source=module.ChatSource.WECHAT,
            display_name="\u5fae\u4fe1",
            available=False,
            description="\u5fae\u4fe1\u6570\u636e\u6e90\u5c1a\u672a\u914d\u7f6e\u3002",
        ),
    )


@pytest.fixture
def instant_qq_connect(monkeypatch):
    """Make the QQ connect min-display delay deterministic.

    ``_connect_display_delay`` keeps the "connecting" state visible for
    ``_QQ_CONNECT_MIN_DISPLAY_MS`` (500ms) and applies the result through
    ``QTimer.singleShot``. Tests assert the *applied* state, not the pause, so
    dropping the delay to 0 turns that callback into a plain zero-timer that
    ``_drain`` delivers immediately - no fixed real wait.
    """
    monkeypatch.setattr(
        importlib.import_module("qq_chat_analyzer.gui.qq_workspace"),
        "_QQ_CONNECT_MIN_DISPLAY_MS",
        0,
    )


class _StaticConnectionService:
    """Return one fixed QQ connection status."""

    def __init__(self, status):
        self._status = status

    def check_status(self):
        return self._status


class StubFacade:
    """Stand in for ChatAnalyzerFacade with recorded calls."""

    def __init__(
        self,
        sources=(),
        sessions=(),
        outcome=None,
        error=None,
        connection_status=None,
        connection_status_after_connect=None,
        connection_error=None,
        verify_error=None,
        connect_qq_error=None,
        setup_status=None,
        setup_error=None,
        data_root=None,
        data_roots=(),
        qq_setup_status=None,
        qq_runtime_status=None,
        qq_environment_config=None,
        message_range=None,
        reports=(),
        report_issues=(),
        report_usage=None,
        report_usage_error=None,
        list_reports_error=None,
        clear_reports_error=None,
        share_image_path=None,
        share_image_error=None,
    ):
        self._sources = tuple(sources)
        self._sessions = list(sessions)
        self._outcome = outcome
        self._error = error
        self._connection_status = connection_status
        self._connection_status_after_connect = connection_status_after_connect
        self._connection_error = connection_error
        self._verify_error = verify_error
        self._connect_qq_error = connect_qq_error
        self._setup_status = setup_status
        self._setup_error = setup_error
        self._data_root = data_root
        self._data_roots = list(data_roots)
        self._qq_setup_status = qq_setup_status
        self._qq_runtime_status = qq_runtime_status
        self._qq_environment_config = qq_environment_config
        self._message_range = message_range
        self._reports = list(reports)
        self._report_issues = tuple(report_issues)
        self._report_usage = report_usage
        self._report_usage_error = report_usage_error
        self._list_reports_error = list_reports_error
        self._clear_reports_error = clear_reports_error
        self._share_image_path = share_image_path
        self._share_image_error = share_image_error
        self.list_sessions_calls: list[object] = []
        self.get_connection_status_calls: list[object] = []
        self.get_wechat_setup_status_calls: list[object] = []
        self.setup_wechat_environment_calls: list[object] = []
        self.detect_wechat_data_root_calls: list[object] = []
        self.detect_wechat_data_roots_calls: list[object] = []
        self.acquire_wechat_db_key_calls: list[object] = []
        self.verify_wechat_database_calls: list[object] = []
        self.get_qq_setup_status_calls: list[object] = []
        self.get_qq_runtime_status_calls: list[object] = []
        self.get_qq_environment_config_calls: list[object] = []
        self.setup_qq_environment_calls: list[object] = []
        self.set_qq_install_path_calls: list[object] = []
        self.start_qq_runtime_calls: list[object] = []
        self.connect_qq_calls: list[object] = []
        self.start_qq_auth_flow_calls: list[object] = []
        self.get_qq_connection_snapshot_calls: list[object] = []
        self.shutdown_qq_runtime_calls: list[object] = []
        self.shutdown_calls: list[object] = []
        self.disconnect_qq_calls: list[object] = []
        self.disconnect_wechat_calls: list[object] = []
        self.get_session_message_range_calls: list[tuple] = []
        self.analyze_session_calls: list[tuple] = []
        self.list_report_packages_calls: list[object] = []
        self.get_report_storage_usage_calls: list[object] = []
        self.clear_report_packages_calls: list[object] = []
        self.list_snapshots_calls: list[tuple] = []
        self.validate_snapshot_calls: list[object] = []
        self.remove_snapshot_calls: list[object] = []
        self.remove_all_snapshots_calls: list[object] = []
        self.get_snapshot_storage_usage_calls: list[object] = []
        self.generate_share_image_calls: list[object] = []

    def list_report_packages(self):
        from qq_chat_analyzer.application.report_package_catalog import ReportPackageListing
        self.list_report_packages_calls.append(1)
        if self._list_reports_error is not None:
            raise self._list_reports_error
        return ReportPackageListing(tuple(self._reports), self._report_issues)

    def get_report_storage_usage(self):
        from qq_chat_analyzer.application.report_package_catalog import ReportStorageUsage
        self.get_report_storage_usage_calls.append(1)
        if self._report_usage_error is not None:
            raise self._report_usage_error
        if self._report_usage is not None:
            return self._report_usage
        return ReportStorageUsage(len(self._reports), 0)

    def clear_report_packages(self):
        self.clear_report_packages_calls.append(1)
        if self._clear_reports_error is not None:
            self._reports = self._reports[:1]
            raise self._clear_reports_error
        self._reports = []
        self._report_issues = ()

    def delete_report_packages(self, names):
        from qq_chat_analyzer.application.report_package_catalog import ReportPackageDeletionResult
        self._reports = [record for record in self._reports if record.package_name not in names]
        return ReportPackageDeletionResult(tuple(names))

    def list_snapshots(self, source=None, session_id=None):
        self.list_snapshots_calls.append((source, session_id))
        if self._snapshot_error is not None:
            raise self._snapshot_error
        return tuple(self._snapshots)

    def validate_snapshot(self, snapshot_id):
        self.validate_snapshot_calls.append(snapshot_id)
        if self._snapshot_error is not None:
            raise self._snapshot_error
        return next(
            (
                snapshot
                for snapshot in self._snapshots
                if getattr(snapshot, "id", None) == snapshot_id
            ),
            None,
        )

    def remove_snapshot(self, snapshot_id):
        self.remove_snapshot_calls.append(snapshot_id)
        if self._remove_snapshot_error is not None:
            raise self._remove_snapshot_error
        if self._snapshot_error is not None:
            raise self._snapshot_error
        snapshot_module = importlib.import_module(
            "qq_chat_analyzer.application.chat_data_snapshot"
        )
        removed = next(
            (
                snapshot
                for snapshot in self._snapshots
                if getattr(snapshot, "id", None) == snapshot_id
            ),
            None,
        )
        self._snapshots = [
            dataclasses.replace(
                snapshot,
                payload_state=snapshot_module.SnapshotPayloadState.REMOVED,
            )
            if getattr(snapshot, "id", None) == snapshot_id
            else snapshot
            for snapshot in self._snapshots
        ]
        self._snapshot_storage_usage = 0
        return removed

    def remove_all_snapshots(self):
        self.remove_all_snapshots_calls.append(1)
        if self._remove_all_snapshots_error is not None:
            raise self._remove_all_snapshots_error
        self._snapshots = []
        self._snapshot_storage_usage = 0
        return 0

    def get_snapshot_storage_usage(self):
        self.get_snapshot_storage_usage_calls.append(1)
        if self._snapshot_error is not None:
            raise self._snapshot_error
        return self._snapshot_storage_usage

    def generate_share_image(self, outcome):
        self.generate_share_image_calls.append(outcome)
        if self._share_image_error is not None:
            raise self._share_image_error
        return self._share_image_path

    def list_sources(self):
        return self._sources

    def list_sessions(self, source):
        self.list_sessions_calls.append(source)
        if self._error is not None:
            raise self._error
        return self._sessions

    def get_connection_status(self, source):
        self.get_connection_status_calls.append(source)
        if self._connection_error is not None:
            raise self._connection_error
        if self._connection_status is None:
            return self._default_connection_status(source)
        return self._connection_status

    def get_qq_setup_status(self):
        self.get_qq_setup_status_calls.append(1)
        if self._qq_setup_status is not None:
            return self._qq_setup_status
        module = importlib.import_module(
            "qq_chat_analyzer.application.qq.qq_setup_service"
        )
        return module.QQSetupStatus(
            state=module.QQSetupState.CONFIG_MISSING,
            configured=False,
            runtime_available=False,
            message="QQ \u5c1a\u672a\u8fde\u63a5\u3002",
            action_hint="\u8bf7\u70b9\u51fb\u300c\u8fde\u63a5QQ\u300d\u81ea\u52a8\u5b8c\u6210\u8fde\u63a5\u3002",
        )

    def get_qq_runtime_status(self):
        self.get_qq_runtime_status_calls.append(1)
        if self._qq_runtime_status is not None:
            return self._qq_runtime_status
        module = importlib.import_module("qq_chat_analyzer.application.qq.qq_runtime_manager")
        return module.QQRuntimeStatus(
            state=module.QQRuntimeState.STOPPED,
            available=False,
            message="QQ \u672a\u8fde\u63a5\u3002",
            action_hint="\u8bf7\u70b9\u51fb\u300c\u8fde\u63a5QQ\u300d\u3002",
        )

    def get_qq_environment_config(self):
        self.get_qq_environment_config_calls.append(1)
        return self._qq_environment_config

    def setup_qq_environment(self, config):
        self.setup_qq_environment_calls.append(config)
        if self._setup_error is not None:
            raise self._setup_error
        return None

    def set_qq_install_path(self, path):
        self.set_qq_install_path_calls.append(path)
        if self._setup_error is not None:
            raise self._setup_error
        return None

    def start_qq_runtime(self):
        self.start_qq_runtime_calls.append(1)
        if self._qq_runtime_status is not None:
            return self._qq_runtime_status
        module = importlib.import_module("qq_chat_analyzer.application.qq.qq_runtime_manager")
        return module.QQRuntimeStatus(
            state=module.QQRuntimeState.RUNNING,
            available=True,
            message="QQ \u5df2\u8fde\u63a5\u3002",
            action_hint="",
        )

    def connect_qq(self):
        self.connect_qq_calls.append(1)
        if self._connect_qq_error is not None:
            raise self._connect_qq_error
        if self._connection_status_after_connect is not None:
            self._connection_status = self._connection_status_after_connect
        return self._qq_snapshot()

    def start_qq_auth_flow(self, progress=None, *, cancel_event=None):
        self.start_qq_auth_flow_calls.append(1)
        if progress is not None:
            progress("正在加载 NapCat...")
        if self._connect_qq_error is not None:
            raise self._connect_qq_error
        if self._connection_status_after_connect is not None:
            self._connection_status = self._connection_status_after_connect
        return self._qq_snapshot()

    def is_qq_qrcode_ready(self):
        return True

    def get_qq_connection_snapshot(self):
        self.get_qq_connection_snapshot_calls.append(1)
        if self._connection_error is not None:
            raise self._connection_error
        return self._qq_snapshot()

    def shutdown_qq_runtime(self):
        self.shutdown_qq_runtime_calls.append(1)

    def shutdown(self):
        self.shutdown_calls.append(1)
        # The real facade orders Direct DB plaintext cleanup before QQ runtime
        # termination; the stub mirrors that by delegating to its own runtime
        # shutdown so closeEvent keeps exercising the same single shutdown path.
        self.shutdown_qq_runtime()

    def disconnect_qq(self):
        self.disconnect_qq_calls.append(1)
        if self._connection_error is not None:
            raise self._connection_error
        module = _facade_module()
        self._connection_status = module.QQConnectionStatus(
            available=False,
            runtime_running=False,
            qq_online=False,
            version="",
            message="QQ 尚未连接。",
            action_hint="",
        )
        return self._qq_snapshot()

    def disconnect_wechat(self):
        self.disconnect_wechat_calls.append(1)
        if self._connection_error is not None:
            raise self._connection_error
        module = _facade_module()
        self._connection_status = module.WeChatConnectionStatus(
            available=False,
            data_found=True,
            db_key_available=False,
            runtime_available=True,
            message="等待微信登录",
            action_hint="",
        )
        return self._connection_status

    def _qq_snapshot(self):
        """Map the stubbed QQ status onto the connection lifecycle model."""
        module = _facade_module()
        status = self._connection_status
        if status is None:
            status = self._default_connection_status(module.ChatSource.QQ)
        manager = importlib.import_module(
            "qq_chat_analyzer.application.qq.qq_connection_manager"
        )
        return manager.QQConnectionManager(
            connection_service=_StaticConnectionService(status),
        ).get_snapshot()

    def get_session_message_range(self, source, session_id):
        self.get_session_message_range_calls.append((source, session_id))
        return self._message_range

    def get_wechat_setup_status(self):
        self.get_wechat_setup_status_calls.append(1)
        if self._setup_error is not None:
            raise self._setup_error
        if self._setup_status is not None:
            return self._setup_status
        module = importlib.import_module(
            "qq_chat_analyzer.application.wechat.wechat_setup_service"
        )
        return module.WeChatSetupStatus(
            state=module.WeChatSetupState.CONFIG_MISSING,
            configured=False,
            message="\u5fae\u4fe1\u73af\u5883\u672a\u51c6\u5907",
            action_hint="\u8bf7\u5148\u5b8c\u6210\u5fae\u4fe1\u73af\u5883\u8bbe\u7f6e",
        )

    def detect_wechat_data_root(self):
        self.detect_wechat_data_root_calls.append(1)
        return self._data_root

    def detect_wechat_data_roots(self):
        self.detect_wechat_data_roots_calls.append(1)
        if self._data_roots:
            return [Path(value) for value in self._data_roots]
        if self._data_root is not None:
            return [Path(self._data_root)]
        return []

    def acquire_wechat_db_key(self, progress=None, *, cancel_event=None):
        self.acquire_wechat_db_key_calls.append(progress)
        if self._connection_status_after_connect is not None:
            self._connection_status = self._connection_status_after_connect
        return "fictional-key-64"

    def verify_wechat_database(self):
        self.verify_wechat_database_calls.append(1)
        if self._verify_error is not None:
            raise self._verify_error
        return None

    def setup_wechat_environment(self, config):
        self.setup_wechat_environment_calls.append(config)
        if self._setup_error is not None:
            raise self._setup_error
        return self._connection_status or self._default_connection_status(
            _facade_module().ChatSource.WECHAT
        )

    def _default_connection_status(self, source):
        module = _facade_module()
        if source == module.ChatSource.WECHAT:
            return module.WeChatConnectionStatus(
                available=True,
                data_found=True,
                db_key_available=True,
                runtime_available=True,
                message="\u5fae\u4fe1\u53ef\u7528",
                action_hint="",
            )
        return module.QQConnectionStatus(
            available=True,
            runtime_running=True,
            qq_online=True,
            version="4.1.0",
            message="\u5df2\u8fde\u63a5",
            action_hint="",
        )

    def analyze_session(self, source, session_id, config=None, progress=None, on_phase=None):
        self.analyze_session_calls.append((source, session_id, config))
        if on_phase is not None:
            from qq_chat_analyzer.application.analysis_phase import AnalysisPhase
            on_phase(AnalysisPhase.READING)
            on_phase(AnalysisPhase.ANALYZING_REPORT)
        if progress is not None:
            progress("正在分析聊天内容...")
        if self._error is not None:
            raise self._error
        return self._outcome


def _session(
    source,
    session_id: str,
    display_name: str,
    count=None,
    last_message_time=None,
):
    module = _facade_module()
    return module.SessionInfo(
        source=source,
        session_id=session_id,
        display_name=display_name,
        message_count=count,
        last_message_time=last_message_time,
    )


def _sort_index(page, value: str) -> int:
    for index in range(page._session_sort.count()):
        if page._session_sort.itemData(index) == value:
            return index
    raise AssertionError(f"missing sort mode {value}")


def _dashboard_view(*, has_data: bool = True):
    presentation = _presentation()
    if not has_data:
        return presentation.DashboardView(
            title="\u865a\u6784\u62a5\u544a",
            has_data=False,
            empty_description="\u6ca1\u6709\u6570\u636e\u3002",
        )

    return presentation.DashboardView(
        title="\u865a\u6784\u62a5\u544a",
        has_data=True,
        summary_metrics=(
            presentation.MetricCard(
                key="total_messages",
                title="\u6d88\u606f\u6570\u91cf",
                value="42",
                description="\u603b\u6570",
            ),
        ),
        charts=(
            presentation.ChartData(
                key="top_words",
                kind=presentation.ChartKind.RANKING,
                title="\u9ad8\u9891\u8bcd",
                series=(
                    presentation.ChartSeries(
                        name="\u8bcd\u9891",
                        points=(
                            presentation.ChartPoint(label="deck", value=5.0),
                            presentation.ChartPoint(label="trade", value=2.0),
                        ),
                    ),
                ),
            ),
        ),
        user_cards=(
            presentation.UserCard(
                rank=1,
                sender="Fictional-Alice",
                message_count=30,
                percentage=75.0,
                average_length=4.0,
                percentage_display="75.0%",
                average_length_display="4.0 \u5b57",
                active_period="\u5468\u4e00 09:00-09:59",
                top_words=("deck",),
            ),
        ),
        conversation_cards=(
            presentation.ConversationCard(
                conversation_id="fictional-room-1",
                message_count=42,
                participant_count=2,
                time_span="2 \u5c0f\u65f6 0 \u5206\u949f",
            ),
        ),
    )


class _StubOutcome:
    def __init__(
        self,
        view,
        *,
        data_acquired_at=None,
        report_path=None,
        report_directory=None,
    ):
        self.view = view
        self.data_acquired_at = data_acquired_at
        self.report_path = report_path
        self.report_directory = report_directory


def _dashboard_page(qt_app):
    module = importlib.import_module("qq_chat_analyzer.gui.dashboard_page")
    return module.DashboardPage()


def _main_window(qt_app, facade, executor=None):
    module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    return module.MainWindow(facade, executor=executor or _inline_executor())


def _main_window_no_executor(qt_app, facade):
    """Create MainWindow without executor, as in real GUI app.py."""
    module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    return module.MainWindow(facade, executor=None)


def _inline_executor():
    """Run facade calls on the calling thread.

    The GUI defaults to a real thread pool. Tests inject this instead so no
    test depends on thread scheduling or on a Qt event loop turn.
    """
    module = importlib.import_module("qq_chat_analyzer.gui.workers")
    return module.run_inline


def test_worker_forwards_analysis_progress_to_the_ui_callback() -> None:
    workers = importlib.import_module("qq_chat_analyzer.gui.workers")
    received: list[str] = []

    workers.run_inline(
        lambda report: report("正在分析聊天内容..."),
        on_success=lambda _result: None,
        on_error=lambda _code, _message: None,
        on_progress=received.append,
    )

    assert received == ["正在分析聊天内容..."]


def test_cancelled_worker_stops_emitting_and_cleans_up(qt_app) -> None:
    workers = importlib.import_module("qq_chat_analyzer.gui.workers")
    started = threading.Event()
    release = threading.Event()
    successes: list[object] = []
    errors: list[tuple[str, str]] = []
    progress: list[str] = []

    def operation(report):
        report("step-1")
        started.set()
        release.wait(timeout=5)
        report("step-2")
        return "done"

    workers.submit(
        operation,
        on_success=successes.append,
        on_error=lambda code, message: errors.append((code, message)),
        on_progress=progress.append,
    )

    assert started.wait(timeout=2)
    for worker in workers._PENDING:
        worker.cancel()
    release.set()
    _settle_workers()

    assert progress == ["step-1"]
    assert successes == []
    assert errors == []
    assert workers._PENDING == set()


def test_worker_stops_when_signal_source_is_destroyed(qt_app) -> None:
    workers = importlib.import_module("qq_chat_analyzer.gui.workers")
    started = threading.Event()
    progress_received = threading.Event()
    successes: list[object] = []
    errors: list[tuple[str, str]] = []
    progress: list[str] = []

    def operation(report):
        report("step-1")
        started.set()
        progress_received.wait(timeout=5)
        report("step-2")
        return "done"

    worker = workers.submit(
        operation,
        on_success=successes.append,
        on_error=lambda code, message: errors.append((code, message)),
        on_progress=lambda message: (
            progress.append(message),
            progress_received.set(),
        ),
    )

    assert started.wait(timeout=2)
    deadline = time.monotonic() + 2
    while not progress_received.is_set() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    assert progress_received.is_set()
    import shiboken6

    shiboken6.delete(worker._callback_relay)
    _settle_workers()

    assert progress == ["step-1"]
    assert successes == []
    assert errors == []
    assert workers._PENDING == set()


def test_worker_shutdown_cancels_pending_workers(qt_app) -> None:
    workers = importlib.import_module("qq_chat_analyzer.gui.workers")
    started = threading.Event()
    release = threading.Event()
    successes: list[object] = []
    errors: list[tuple[str, str]] = []
    progress: list[str] = []

    def operation(report):
        started.set()
        release.wait(timeout=5)
        report("late")
        return "done"

    workers.submit(
        operation,
        on_success=successes.append,
        on_error=lambda code, message: errors.append((code, message)),
        on_progress=progress.append,
    )

    assert started.wait(timeout=2)
    workers.shutdown()
    release.set()
    _settle_workers()

    assert progress == []
    assert successes == []
    assert errors == []
    assert workers._PENDING == set()


def test_worker_shutdown_is_non_blocking_and_clears_pool(
    qt_app,
    monkeypatch,
) -> None:
    workers = importlib.import_module("qq_chat_analyzer.gui.workers")
    pool = QThreadPool.globalInstance()
    clears: list[int] = []
    waits: list[int] = []
    monkeypatch.setattr(pool, "clear", lambda: clears.append(1))
    monkeypatch.setattr(
        pool,
        "waitForDone",
        lambda timeout: waits.append(timeout) or True,
    )

    workers.shutdown()

    assert clears == [1]
    assert waits == []


def test_wechat_workspace_cancel_restores_connect_and_ignores_stale_finish(
    qt_app,
) -> None:
    from qq_chat_analyzer.gui.wechat_workspace import WeChatWorkspace

    module = _facade_module()
    facade = StubFacade(
        sources=_wechat_available_sources(),
        data_roots=["D:/fake_xwechat_files"],
    )
    executor = _DeferredExecutor()
    workspace = WeChatWorkspace(facade, executor=executor)

    workspace.connect_wechat()
    assert executor.submission_count == 1
    assert workspace._wechat_connect_button.text() == "取消连接"
    assert workspace._wechat_connect_button.isEnabled() is True

    workspace.connect_wechat()
    assert executor.cancelled is True
    assert workspace._wechat_connect_button.text() == "连接微信"
    assert workspace._wechat_connect_button.isEnabled() is True
    assert workspace._connection_task is None

    workspace.connect_wechat()
    assert executor.submission_count == 2

    workspace._connection_task = object()
    stale_task = workspace._connection_task
    workspace._finish_wechat_connect(executor)
    assert workspace._connection_task is stale_task

    workspace._finish_wechat_connect(stale_task)
    assert workspace._connection_task is None


@pytest.mark.parametrize(
    "code",
    [
        "database_not_found",
        "wechat_database_error",
        "wcdb_library_not_found",
    ],
)
def test_wechat_database_connect_error_shows_database_stage(
    qt_app,
    code,
) -> None:
    from qq_chat_analyzer.gui.wechat_workspace import WeChatWorkspace

    facade = StubFacade(sources=_wechat_available_sources())
    workspace = WeChatWorkspace(facade)

    workspace._handle_wechat_connect_error(code, "未找到有效微信数据库")

    assert "微信数据库读取失败" in workspace._status_label.text()
    assert "获取权限" not in workspace._status_label.text()


class _DeferredExecutor:
    """Capture a facade call and let the test finish it manually."""

    def __init__(self):
        self.operation = None
        self.on_success = None
        self.on_error = None
        self.on_finished = None
        self.on_progress = None
        self.submission_count = 0
        self.cancelled = False

    def __call__(
        self,
        operation,
        *,
        on_success,
        on_error,
        on_finished=None,
        on_progress=None,
    ):
        self.submission_count += 1
        self.operation = operation
        self.on_success = on_success
        self.on_error = on_error
        self.on_finished = on_finished
        self.on_progress = on_progress
        return self

    def cancel(self):
        self.cancelled = True

    def progress(self, message):
        if self.on_progress is not None:
            self.on_progress(message)

    def succeed(self, result):
        if self.on_success is not None:
            self.on_success(result)
        if self.on_finished is not None:
            self.on_finished()

    def fail(self, code, message):
        if self.on_error is not None:
            self.on_error(code, message)
        if self.on_finished is not None:
            self.on_finished()


class _QueuedExecutor:
    """Keep every submitted call so a test chooses the completion order."""

    def __init__(self):
        self.tasks: list[tuple] = []

    def __call__(
        self,
        operation,
        *,
        on_success,
        on_error,
        on_finished=None,
        on_progress=None,
    ):
        self.tasks.append((operation, on_success, on_error, on_finished))
        return self.tasks[-1]

    def succeed(self, index: int) -> None:
        operation, on_success, _on_error, on_finished = self.tasks[index]
        on_success(operation())
        if on_finished is not None:
            on_finished()

    def fail(self, index: int, code: str, message: str) -> None:
        _operation, _on_success, on_error, on_finished = self.tasks[index]
        on_error(code, message)
        if on_finished is not None:
            on_finished()


def test_qq_exit_wait_stays_preparing_and_allows_cancel(qt_app):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    workspace = QQWorkspace(StubFacade(), executor=_DeferredExecutor())
    workspace.connect_qq()
    workspace._connection_task.progress("请完全退出 QQ")
    assert workspace._qq_guide_label.text() == "请完全退出 QQ"
    assert workspace._qq_connect_button.isEnabled()
    assert workspace._progress_track.stage == 0
    workspace._qq_connect_button.click()
    assert workspace._qq_connect_in_flight is False


@pytest.mark.parametrize("cancel", [False, True])
def test_qq_process_wait_runs_in_background_through_real_facade(qt_app, monkeypatch, cancel):
    from qq_chat_analyzer.application.qq import qq_auth_bridge as auth
    from qq_chat_analyzer.application.qq.qq_process_registry import QQProcessRegistry
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    from qq_chat_analyzer.application.connection_models import ConnectionSnapshot, ConnectionState
    main_thread = threading.get_ident()
    detected_threads = []
    conflicts = threading.Event()
    conflicts.set()
    completed = threading.Event()
    launches = []
    def detect(owned):
        detected_threads.append(threading.get_ident())
        return [101, 102] if conflicts.is_set() else []
    def launch():
        launches.append(threading.get_ident())
    monkeypatch.setattr(auth, "find_conflicting_qq_pids", detect)
    manager = SimpleNamespace(
        get_snapshot=lambda: ConnectionSnapshot(ConnectionState.DISCONNECTED, "qq", "disconnected"),
        begin_auth_waiting=lambda: None, end_auth_waiting=completed.set,
    )
    bridge = auth.QQAuthBridge(setup_service=SimpleNamespace(), manager=manager,
                              window_launcher=launch, process_registry=QQProcessRegistry(),
                              process_poll_interval=0.01)
    facade = _facade_module().ChatAnalyzerFacade(qq_auth_bridge=bridge)
    workspace = QQWorkspace(facade)
    workspace.connect_qq()
    deadline = time.monotonic() + 3
    while workspace._qq_guide_label.text() != "请完全退出 QQ" and time.monotonic() < deadline:
        qt_app.processEvents()
        QTest.qWait(5)
    assert workspace._qq_guide_label.text() == "请完全退出 QQ"
    assert detected_threads and main_thread not in detected_threads
    assert launches == []
    if cancel:
        workspace.cancel_connection()
        conflicts.clear()
        assert completed.wait(2)
        QTest.qWait(30)
        assert launches == []
        assert workspace._qq_connect_in_flight is False
    else:
        conflicts.clear()
        deadline = time.monotonic() + 3
        while not launches and time.monotonic() < deadline:
            qt_app.processEvents()
            QTest.qWait(5)
        assert len(launches) == 1
        assert launches[0] != main_thread
        workspace.cancel_connection()
    workspace._stop_qq_status_polling()


@pytest.mark.parametrize("event", ["progress", "success", "error", "delayed_success", "delayed_error"])
def test_qq_cancel_rejects_old_callbacks_after_restart(qt_app, monkeypatch, event):
    from qq_chat_analyzer.gui import qq_workspace as module
    executor = _IndependentDeferredExecutor()
    workspace = module.QQWorkspace(StubFacade(), executor=executor)
    delayed = []
    monkeypatch.setattr(module.QTimer, "singleShot", lambda delay, callback: delayed.append(callback))
    workspace.connect_qq()
    first = executor.tasks[0]
    if event == "delayed_success":
        first.succeed(SimpleNamespace(state="waiting_auth", message="old"))
    if event == "delayed_error":
        first.fail("old_error", "old failure")
    workspace.cancel_connection()
    workspace.connect_qq()
    second = executor.tasks[-1]
    before = workspace._status_label.text()
    if event == "progress":
        first.progress("请完全退出 QQ")
    elif event == "success":
        first.succeed(SimpleNamespace(state="waiting_auth", message="old"))
    elif event == "error":
        first.fail("old_error", "old failure")
    for callback in delayed:
        callback()
    assert workspace._status_label.text() == before
    assert workspace._connection_task is second
    assert workspace._qq_connect_in_flight


@pytest.mark.parametrize("poll", [False, True])
def test_qq_cancel_ignores_older_status_worker(qt_app, poll):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    executor = _IndependentDeferredExecutor()
    workspace = QQWorkspace(StubFacade(), executor=executor)
    if poll:
        workspace._start_qq_status_polling()
        workspace._poll_qq_status()
    else:
        workspace.refresh_qq_status()
    old_status = executor.tasks[0]
    workspace.connect_qq()
    workspace.cancel_connection()
    before = workspace._status_label.text()
    old_status.succeed(SimpleNamespace(state="waiting_auth", message="old status"))
    assert workspace._status_label.text() == before
    assert not workspace._qq_status_timer.isActive()


class _IndependentDeferredExecutor:
    """Keep each submitted callback set available for stale-event tests."""

    class Task:
        def __init__(
            self,
            operation,
            on_success,
            on_error,
            on_finished,
            on_progress,
        ):
            self.operation = operation
            self.on_success = on_success
            self.on_error = on_error
            self.on_finished = on_finished
            self.on_progress = on_progress
            self.cancelled = False

        def cancel(self):
            self.cancelled = True

        def progress(self, message):
            if self.on_progress is not None:
                self.on_progress(message)

        def succeed(self, result):
            if self.on_success is not None:
                self.on_success(result)

        def fail(self, code, message):
            if self.on_error is not None:
                self.on_error(code, message)

        def finish(self):
            if self.on_finished is not None:
                self.on_finished()

    def __init__(self):
        self.tasks = []

    def __call__(
        self,
        operation,
        *,
        on_success,
        on_error,
        on_finished=None,
        on_progress=None,
    ):
        task = self.Task(
            operation,
            on_success,
            on_error,
            on_finished,
            on_progress,
        )
        self.tasks.append(task)
        return task


def test_wechat_cancel_queued_attempt_cannot_start_key_and_fresh_attempt_can(qt_app):
    class Facade(StubFacade):
        def cancel_wechat_connection(self, cancel_event):
            cancel_event.set()
        def acquire_wechat_db_key(self, progress=None, *, cancel_event=None):
            assert cancel_event is not None and not cancel_event.is_set()
            return super().acquire_wechat_db_key(progress)
    facade = Facade()
    executor = _IndependentDeferredExecutor()
    workspace = _wechat_guide_module().WeChatWorkspace(facade, executor=executor)
    workspace._start_wechat_connect(_wechat_connection_config())
    old = executor.tasks[0]
    workspace.cancel_connection()
    with pytest.raises(_facade_module().FacadeError) as error:
        old.operation(lambda _: None)
    assert error.value.code == "wechat_key_cancelled"
    assert facade.acquire_wechat_db_key_calls == []
    workspace._start_wechat_connect(_wechat_connection_config())
    executor.tasks[1].operation(lambda _: None)
    assert len(facade.acquire_wechat_db_key_calls) == 1


def test_begin_shutdown_signals_wechat_attempt_without_waiting_on_gui(qt_app):
    facade = StubFacade()
    executor = _IndependentDeferredExecutor()
    window = _main_window(qt_app, facade, executor=executor)
    window.wechat_workspace._start_wechat_connect(_wechat_connection_config())
    attempt = executor.tasks[-1]
    assert window.begin_shutdown()
    assert attempt.cancelled
    assert window.await_shutdown(2)
    assert not window.shutdown_protocol.result.can_apply_update


def _drain(page):
    """Deliver zero-timer GUI work used by the synchronous test executor."""
    QApplication.processEvents()


def _settle_workers(timeout_ms: int = 5000) -> None:
    """Wait for real thread-pool work and deliver queued GUI callbacks."""
    workers = importlib.import_module("qq_chat_analyzer.gui.workers")
    import shiboken6

    def relay_can_dispatch(relay) -> bool:
        if not shiboken6.isValid(relay):
            return False
        try:
            return any(
                isinstance(source, workers.WorkerSignals)
                and shiboken6.isValid(source)
                for source in relay.children()
            )
        except RuntimeError:
            return False

    deadline = time.monotonic() + timeout_ms / 1000
    pool = QThreadPool.globalInstance()
    while True:
        QApplication.processEvents()
        live_relays = tuple(
            relay
            for relay in workers._RELAYS
            if relay_can_dispatch(relay)
        )
        if (
            not workers._PENDING
            and not live_relays
            and pool.activeThreadCount() == 0
        ):
            return
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            return
        pool.waitForDone(min(100, remaining_ms))
        QTest.qWait(min(20, remaining_ms))


def test_settle_workers_returns_immediately_when_pool_is_idle(monkeypatch) -> None:
    workers = importlib.import_module("qq_chat_analyzer.gui.workers")

    class _IdlePool:
        def activeThreadCount(self) -> int:
            return 0

        def waitForDone(self, _timeout: int) -> bool:
            raise AssertionError("idle worker pool should not be waited on")

    monkeypatch.setattr(workers, "_PENDING", set())
    monkeypatch.setattr(workers, "_RELAYS", set())
    monkeypatch.setattr(
        QThreadPool,
        "globalInstance",
        staticmethod(lambda: _IdlePool()),
    )

    _settle_workers(timeout_ms=5000)


def test_settle_workers_still_honors_timeout_for_pending_workers(monkeypatch) -> None:
    workers = importlib.import_module("qq_chat_analyzer.gui.workers")
    clock = [0.0]
    waits: list[int] = []

    class _BusyPool:
        def activeThreadCount(self) -> int:
            return 1

        def waitForDone(self, timeout: int) -> bool:
            waits.append(timeout)
            clock[0] = 0.011
            return False

    monkeypatch.setattr(workers, "_PENDING", {object()})
    monkeypatch.setattr(workers, "_RELAYS", set())
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        QThreadPool,
        "globalInstance",
        staticmethod(lambda: _BusyPool()),
    )
    monkeypatch.setattr(QTest, "qWait", lambda _timeout: None)
    monkeypatch.setattr(QApplication, "processEvents", lambda: None)

    _settle_workers(timeout_ms=10)

    assert waits


def test_settle_workers_keeps_processing_events_for_an_active_relay(
    monkeypatch,
) -> None:
    workers = importlib.import_module("qq_chat_analyzer.gui.workers")
    relay = workers._CallbackRelay(
        lambda _result: None,
        lambda *_error: None,
        None,
        None,
    )
    signal_source = workers.WorkerSignals(relay)
    relays = {relay}
    event_turns: list[int] = []
    waits: list[int] = []

    class _IdlePool:
        def activeThreadCount(self) -> int:
            return 0

        def waitForDone(self, timeout: int) -> bool:
            waits.append(timeout)
            return True

    def process_events() -> None:
        event_turns.append(1)
        if len(event_turns) == 2:
            relays.discard(relay)

    monkeypatch.setattr(workers, "_PENDING", set())
    monkeypatch.setattr(workers, "_RELAYS", relays)
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(
        QThreadPool,
        "globalInstance",
        staticmethod(lambda: _IdlePool()),
    )
    monkeypatch.setattr(QTest, "qWait", lambda _timeout: None)
    monkeypatch.setattr(QApplication, "processEvents", process_events)

    _settle_workers(timeout_ms=10)

    assert signal_source.parent() is relay
    assert len(event_turns) == 2
    assert waits == [10]


def test_settle_workers_ignores_relay_whose_signal_source_was_destroyed(
    monkeypatch,
) -> None:
    import shiboken6

    workers = importlib.import_module("qq_chat_analyzer.gui.workers")
    relay = workers._CallbackRelay(
        lambda _result: None,
        lambda *_error: None,
        None,
        None,
    )
    signal_source = workers.WorkerSignals(relay)

    shiboken6.delete(signal_source)
    assert shiboken6.isValid(relay)
    assert not shiboken6.isValid(signal_source)

    class _IdlePool:
        def activeThreadCount(self) -> int:
            return 0

        def waitForDone(self, _timeout: int) -> bool:
            raise AssertionError("a stale relay cannot receive another callback")

    monkeypatch.setattr(workers, "_PENDING", set())
    monkeypatch.setattr(workers, "_RELAYS", {relay})
    monkeypatch.setattr(
        QThreadPool,
        "globalInstance",
        staticmethod(lambda: _IdlePool()),
    )
    monkeypatch.setattr(QApplication, "processEvents", lambda: None)

    _settle_workers(timeout_ms=5000)


# ------------------------------------------------------------ initialization


def test_main_window_builds_both_pages(qt_app, sources) -> None:
    window = _main_window(qt_app, StubFacade(sources=sources))

    assert window.stack.count() == 6
    assert window.windowTitle() != ""
    assert window.stack.currentIndex() == 0


def test_main_window_has_no_status_bar(qt_app, sources) -> None:
    from PySide6.QtWidgets import QStatusBar

    window = _main_window(qt_app, StubFacade(sources=sources))

    assert window.findChild(QStatusBar) is None


def test_status_area_is_moved_to_header_row(qt_app, sources) -> None:
    window = _main_window(qt_app, StubFacade(sources=sources))
    status = window._status_label
    layout = window.centralWidget().layout()
    header = layout.itemAt(0).layout()

    assert window._title_label.text() == "余音 Echo"
    assert header is not None
    assert header.itemAt(header.count() - 1).widget() is status
    assert not hasattr(window, "_top_status_label")


def test_qq_and_wechat_share_one_moved_status_area(qt_app, sources) -> None:
    window = _main_window(qt_app, StubFacade(sources=sources))
    status = window._status_label

    window.show_status("等待 QQ 登录")
    assert status.text() == "等待 QQ 登录"
    window.show_status("等待微信登录")
    assert status.text() == "等待微信登录"
    assert window._status_label is status


def test_top_status_follows_status_changed_without_bottom_duplicate(
    qt_app,
    sources,
) -> None:
    window = _main_window(qt_app, StubFacade(sources=sources))

    window.show_status("等待 QQ 登录")

    assert window._status_label.text() == "等待 QQ 登录"


def test_main_window_uses_echo_brand_icon(qt_app, sources) -> None:
    window = _main_window(qt_app, StubFacade(sources=sources))

    assert window.windowIcon().isNull() is False


def test_main_window_close_cleans_up_qq_runtime(qt_app, sources) -> None:
    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)

    window.close()

    deadline = time.monotonic() + 1.0
    while not facade.shutdown_qq_runtime_calls and time.monotonic() < deadline:
        time.sleep(0.005)

    assert facade.shutdown_qq_runtime_calls == [1]


def test_main_window_close_does_not_wait_for_slow_process_cleanup(
    qt_app,
    sources,
) -> None:
    cleanup_finished = threading.Event()

    class _SlowShutdownFacade(StubFacade):
        def shutdown_qq_runtime(self):
            time.sleep(0.2)
            cleanup_finished.set()

    window = _main_window(qt_app, _SlowShutdownFacade(sources=sources))

    started = time.monotonic()
    window.close()
    elapsed = time.monotonic() - started

    assert elapsed < 0.1
    assert cleanup_finished.wait(timeout=1.0)

def test_main_window_close_calls_facade_shutdown(qt_app, sources) -> None:
    """closeEvent calls facade.shutdown() in addition to QQ shutdown."""
    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)

    window.close()

    deadline = time.monotonic() + 1.0
    while not facade.shutdown_calls and time.monotonic() < deadline:
        time.sleep(0.005)

    assert facade.shutdown_calls == [1]


def test_main_window_close_still_calls_qq_shutdown(qt_app, sources) -> None:
    """Original QQ runtime shutdown is preserved alongside facade.shutdown()."""
    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)

    window.close()

    deadline = time.monotonic() + 1.0
    while not facade.shutdown_qq_runtime_calls and time.monotonic() < deadline:
        time.sleep(0.005)

    assert facade.shutdown_qq_runtime_calls == [1]
    assert facade.shutdown_calls == [1]


def test_main_window_close_survives_facade_shutdown_exception(qt_app, sources) -> None:
    """An exception in facade.shutdown() must not prevent window close."""
    class _ShutdownRaisesFacade(StubFacade):
        def shutdown(self):
            self.shutdown_calls.append(1)
            raise RuntimeError("simulated shutdown failure")

    facade = _ShutdownRaisesFacade(sources=sources)
    window = _main_window(qt_app, facade)

    # close() should not raise
    window.close()

    deadline = time.monotonic() + 1.0
    while not facade.shutdown_calls and time.monotonic() < deadline:
        time.sleep(0.005)

    assert facade.shutdown_calls == [1]


def test_main_window_close_cancels_background_workers(
    qt_app,
    sources,
    monkeypatch,
) -> None:
    """closeEvent stops pending workers before facade cleanup starts."""
    main_window = importlib.import_module("qq_chat_analyzer.gui.main_window")
    calls: list[int] = []
    monkeypatch.setattr(
        main_window,
        "shutdown_workers",
        lambda: calls.append(1),
    )
    window = _main_window(qt_app, StubFacade(sources=sources))

    window.close()

    assert calls == [1]


def test_main_window_close_quits_application(
    qt_app,
    sources,
    monkeypatch,
) -> None:
    """closeEvent explicitly ends the Qt event loop."""
    main_window = importlib.import_module("qq_chat_analyzer.gui.main_window")
    calls: list[int] = []
    monkeypatch.setattr(
        main_window,
        "_quit_application",
        lambda: calls.append(1),
    )
    window = _main_window(qt_app, StubFacade(sources=sources))

    window.close()

    assert calls == [1]


def test_main_window_close_owns_shutdown_without_waiting(qt_app, sources) -> None:
    """The window disappears at once, but Echo keeps shutdown ownership.

    ``closeEvent`` must not block the GUI thread, and the cleanup must not be
    left to interpreter finalization: the window exposes the very protocol the
    desktop entry point waits on, so the ordered shutdown (Direct DB plaintext
    cleanup, then QQ runtime termination) still completes.
    """
    module = importlib.import_module("qq_chat_analyzer.gui.shutdown")
    release = threading.Event()

    class _SlowShutdownFacade(StubFacade):
        def shutdown(self):
            self.shutdown_calls.append(1)
            release.wait(5.0)

    facade = _SlowShutdownFacade(sources=sources)
    window = _main_window(qt_app, facade)
    window.show()

    started = time.monotonic()
    window.close()
    elapsed = time.monotonic() - started

    assert elapsed < 0.1
    assert window.isVisible() is False

    protocol = window.shutdown_protocol
    assert protocol.started is True
    assert protocol.finished is False
    assert module.THREAD_NAME in {
        thread.name for thread in threading.enumerate()
    }

    # The entry point still owns the outcome: it can wait for the protocol.
    release.set()
    assert window.await_shutdown(2.0) is True
    assert protocol.finished is True
    assert facade.shutdown_calls == [1]


def test_main_window_shutdown_protocol_thread_is_daemon(qt_app, sources) -> None:
    """A stuck cleanup must never keep the Python process alive forever."""
    module = importlib.import_module("qq_chat_analyzer.gui.shutdown")
    release = threading.Event()

    class _SlowShutdownFacade(StubFacade):
        def shutdown(self):
            release.wait(5.0)

    window = _main_window(qt_app, _SlowShutdownFacade(sources=sources))

    window.close()

    protocol_thread = next(
        (
            candidate
            for candidate in threading.enumerate()
            if candidate.name == module.THREAD_NAME
        ),
        None,
    )
    assert protocol_thread is not None
    assert protocol_thread.daemon is True
    release.set()
    assert window.await_shutdown(2.0) is True


def test_main_window_close_starts_only_one_shutdown_protocol(
    qt_app,
    sources,
) -> None:
    """Repeated closes must never start a competing shutdown."""
    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)

    window.close()
    window.close()
    assert window.begin_shutdown() is False

    assert window.await_shutdown(2.0) is True
    assert facade.shutdown_calls == [1]
    assert facade.shutdown_qq_runtime_calls == [1]


def test_main_window_has_minimum_size(qt_app, sources) -> None:
    """MainWindow has a reasonable minimum size set."""
    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)

    minimum = window.minimumSize()
    assert minimum.width() > 0
    assert minimum.height() > 0
    assert minimum.width() >= 800
    assert minimum.height() >= 600


def test_main_window_size_stable_across_page_switches(qt_app, sources) -> None:
    """Page switching must not change the MainWindow actual size."""
    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)
    window.show()
    window.resize(960, 720)

    initial = window.size()

    window.show_processing_page()
    _drain(window)
    after_processing = window.size()
    assert after_processing == initial

    window.show_qq_workspace()
    _drain(window)
    after_workspace = window.size()
    assert after_workspace == initial

    # Simulate a successful outcome to reach DashboardPage
    window.show_outcome(_StubOutcome(_dashboard_view()))
    _drain(window)
    after_dashboard = window.size()
    assert after_dashboard == initial


def _connection_status(
    *,
    available: bool,
    runtime_running: bool,
    qq_online: bool,
    version: str | None = None,
    message: str,
    action_hint: str,
):
    module = _facade_module()
    return module.QQConnectionStatus(
        available=available,
        runtime_running=runtime_running,
        qq_online=qq_online,
        version=version,
        message=message,
        action_hint=action_hint,
    )


def _qq_setup_status(
    *,
    configured: bool,
    runtime_available: bool = False,
    message: str = "",
    action_hint: str = "",
):
    module = importlib.import_module(
        "qq_chat_analyzer.application.qq.qq_setup_service"
    )
    return module.QQSetupStatus(
        state=(
            module.QQSetupState.CONFIG_READY
            if configured
            else module.QQSetupState.CONFIG_MISSING
        ),
        configured=configured,
        runtime_available=runtime_available,
        message=message,
        action_hint=action_hint,
    )


def _qq_runtime_status(
    *,
    state: str,
    message: str = "",
    action_hint: str = "",
):
    module = importlib.import_module("qq_chat_analyzer.application.qq.qq_runtime_manager")
    return module.QQRuntimeStatus(
        state=module.QQRuntimeState(state),
        available=state == "running",
        message=message,
        action_hint=action_hint,
    )


def _wechat_available_sources():
    module = _facade_module()
    return (
        module.SourceInfo(
            source=module.ChatSource.QQ,
            display_name="QQ",
            available=True,
        ),
        module.SourceInfo(
            source=module.ChatSource.WECHAT,
            display_name="\u5fae\u4fe1",
            available=True,
        ),
    )




def test_dashboard_page_starts_empty(qt_app) -> None:
    page = _dashboard_page(qt_app)

    assert page._user_table.rowCount() == 0
    assert page._word_list.count() == 0
    assert page._empty_label.isVisibleTo(page) is True


# ------------------------------------------------------------------ sessions


# ------------------------------------------------------------------ analysis


# ----------------------------------------------------------------- dashboard


def test_dashboard_renders_every_section(qt_app) -> None:
    page = _dashboard_page(qt_app)

    page.render_view(_dashboard_view())

    assert page._title_label.text() == "\u865a\u6784\u62a5\u544a"
    assert page._user_table.rowCount() == 1
    assert page._user_table.item(0, 1).text() == "Fictional-Alice"
    assert page._user_table.item(0, 3).text() == "75.0%"
    assert page._word_list.count() == 2
    assert "deck" in page._word_list.item(0).text()
    assert page._conversation_table.rowCount() == 1
    assert page._conversation_table.item(0, 3).text() == "2 \u5c0f\u65f6 0 \u5206\u949f"
    assert page._metrics_layout.count() == 1


def test_dashboard_shows_the_empty_state(qt_app) -> None:
    page = _dashboard_page(qt_app)

    page.render_view(_dashboard_view(has_data=False))

    assert page._user_table.rowCount() == 0
    assert page._word_list.count() == 0
    assert page._empty_label.text() == "\u6ca1\u6709\u6570\u636e\u3002"


def test_dashboard_tolerates_a_missing_view(qt_app) -> None:
    page = _dashboard_page(qt_app)

    page.render_view(None)

    assert page._user_table.rowCount() == 0


def test_dashboard_rerender_replaces_previous_content(qt_app) -> None:
    page = _dashboard_page(qt_app)

    page.render_view(_dashboard_view())
    page.render_view(_dashboard_view())

    assert page._user_table.rowCount() == 1
    assert page._metrics_layout.count() == 1


def test_show_outcome_without_report_path_stays_recoverable(
    qt_app,
    sources,
) -> None:
    """Success without a report path never crashes and avoids Dashboard."""
    from qq_chat_analyzer.gui.main_window import DASHBOARD_PAGE_INDEX

    window = _main_window(qt_app, StubFacade(sources=sources))

    window.show_outcome(_dashboard_view())

    assert window.stack.currentIndex() != DASHBOARD_PAGE_INDEX
    assert window._status_label.text() == "分析完成"
    assert not window._open_echo_button.isVisibleTo(window)


def test_successful_outcome_saves_report_and_opens_echo(
    qt_app,
    sources,
    tmp_path,
) -> None:
    """MainWindow keeps the report path and reuses the existing opener."""
    report_path = tmp_path / "echo-report.html"
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")
    opened: list[Path] = []
    window = _main_window(qt_app, StubFacade(sources=sources))
    window._report_opener = lambda path: opened.append(path) or True

    window.show_outcome(
        _StubOutcome(_dashboard_view(), report_path=report_path)
    )

    assert window._current_report_path == report_path.resolve()
    assert window._open_echo_button.isVisibleTo(window)
    assert window._open_echo_button.isEnabled()
    assert opened == [report_path.resolve()]


def test_echo_entry_reopens_the_latest_outcome_report_path(
    qt_app,
    sources,
    tmp_path,
) -> None:
    first_path = tmp_path / "first-report.html"
    second_path = tmp_path / "second-report.html"
    first_path.write_text("<html>first</html>", encoding="utf-8")
    second_path.write_text("<html>second</html>", encoding="utf-8")
    opened: list[Path] = []
    window = _main_window(qt_app, StubFacade(sources=sources))
    window._report_opener = lambda path: opened.append(path) or True

    window.show_outcome(_StubOutcome(_dashboard_view(), report_path=first_path))
    window.show_outcome(_StubOutcome(_dashboard_view(), report_path=second_path))
    assert opened == [first_path.resolve(), second_path.resolve()]
    window._open_echo_button.click()

    assert opened == [
        first_path.resolve(),
        second_path.resolve(),
        second_path.resolve(),
    ]


def test_duplicate_show_outcome_opens_echo_only_once(
    qt_app,
    sources,
    tmp_path,
) -> None:
    report_path = tmp_path / "echo-report.html"
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")
    opened: list[Path] = []
    window = _main_window(qt_app, StubFacade(sources=sources))
    window._report_opener = lambda path: opened.append(path) or True
    outcome = _StubOutcome(_dashboard_view(), report_path=report_path)

    window.show_outcome(outcome)
    window.show_outcome(outcome)

    assert opened == [report_path.resolve()]


def test_default_echo_opener_uses_windows_file_association(
    qt_app,
    tmp_path,
    monkeypatch,
) -> None:
    module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    report_path = (tmp_path / "echo-report.html").resolve()
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")
    opened_paths = []
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(
        module.os,
        "startfile",
        lambda path: opened_paths.append(path),
        raising=False,
    )

    assert module._open_report_path(report_path) is True
    assert opened_paths == [str(report_path)]


def test_default_echo_opener_uses_local_file_url_outside_windows(
    qt_app,
    tmp_path,
    monkeypatch,
) -> None:
    module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    report_path = (tmp_path / "echo-report.html").resolve()
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")
    opened_urls = []
    monkeypatch.setattr(module.os, "name", "posix")
    monkeypatch.setattr(
        module.QDesktopServices,
        "openUrl",
        lambda url: opened_urls.append(url) or True,
    )

    assert module._open_report_path(report_path) is True
    assert len(opened_urls) == 1
    assert opened_urls[0].isLocalFile()
    assert opened_urls[0].toLocalFile() == str(report_path).replace("\\", "/")


def test_default_directory_opener_uses_windows_file_association(
    qt_app,
    tmp_path,
    monkeypatch,
) -> None:
    module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    report_directory = (tmp_path / "Echo_Report_20260815_143012").resolve()
    report_directory.mkdir()
    opened_paths = []
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(
        module.os,
        "startfile",
        lambda path: opened_paths.append(path),
        raising=False,
    )

    assert module._open_directory_path(report_directory) is True
    assert opened_paths == [str(report_directory)]


def test_default_directory_opener_uses_local_file_url_outside_windows(
    qt_app,
    tmp_path,
    monkeypatch,
) -> None:
    module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    report_directory = (tmp_path / "Echo_Report_20260815_143012").resolve()
    report_directory.mkdir()
    opened_urls = []
    monkeypatch.setattr(module.os, "name", "posix")
    monkeypatch.setattr(
        module.QDesktopServices,
        "openUrl",
        lambda url: opened_urls.append(url) or True,
    )

    assert module._open_directory_path(report_directory) is True
    assert len(opened_urls) == 1
    assert opened_urls[0].isLocalFile()
    assert opened_urls[0].toLocalFile() == str(report_directory).replace(
        "\\",
        "/",
    )


def test_missing_report_and_failed_analysis_leave_echo_entry_unavailable(
    qt_app,
    sources,
    tmp_path,
    monkeypatch,
) -> None:
    report_path = tmp_path / "echo-report.html"
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")
    window = _main_window(qt_app, StubFacade(sources=sources))
    window._report_opener = lambda path: True
    window.show_outcome(_StubOutcome(_dashboard_view(), report_path=report_path))

    window.show_processing_page()
    module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *_args: None)
    window.show_error("fictional_failure", "虚构分析失败")

    assert not window._open_echo_button.isVisibleTo(window)
    assert not window._open_echo_button.isEnabled()
    assert not window._generate_share_button.isVisibleTo(window)
    assert not window._generate_share_button.isEnabled()

    report_path.unlink()
    window.show_outcome(_StubOutcome(_dashboard_view(), report_path=report_path))

    assert not window._open_echo_button.isVisibleTo(window)
    assert not window._open_echo_button.isEnabled()
    assert not window._generate_share_button.isVisibleTo(window)
    assert not window._generate_share_button.isEnabled()


def test_session_discovery_error_does_not_restart_active_qq_workspace(
    qt_app,
    sources,
    monkeypatch,
) -> None:
    """A QQ session-list failure must not submit a recursive status refresh."""
    module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    executor = _DeferredExecutor()
    window = _main_window(
        qt_app,
        StubFacade(sources=sources),
        executor=executor,
    )
    warnings = []
    monkeypatch.setattr(
        module.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    window.navigate_to_qq()
    assert executor.submission_count == 1

    window.qq_workspace.analysis_failed.emit(
        "qq_direct_database_recovery_failed",
        "Fictional local QQ data recovery failure.",
    )

    assert window.stack.currentIndex() == module.QQ_WORKSPACE_INDEX
    assert executor.submission_count == 1
    assert warnings == [
        (module._ERROR_TITLE, "Fictional local QQ data recovery failure.")
    ]


def test_echo_open_failure_is_recoverable_and_does_not_crash(
    qt_app,
    sources,
    tmp_path,
    monkeypatch,
) -> None:
    from qq_chat_analyzer.gui.main_window import QQ_WORKSPACE_INDEX

    main_window_module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    # The failure is now announced with one modal warning; capture it instead
    # of blocking the test on a real dialog.
    monkeypatch.setattr(
        main_window_module.QMessageBox, "warning", lambda *_args: None
    )

    report_path = tmp_path / "echo-report.html"
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")

    def _failing_opener(path):
        raise OSError("fictional open failure")

    window = _main_window(qt_app, StubFacade(sources=sources))
    window._report_opener = _failing_opener
    window.navigate_to_qq()
    _drain(window)

    window.show_outcome(
        _StubOutcome(_dashboard_view(), report_path=report_path)
    )

    assert window._current_report_path == report_path.resolve()
    assert "无法打开" in window._status_label.text()
    assert window._open_echo_button.isVisibleTo(window)
    assert window.stack.currentIndex() == QQ_WORKSPACE_INDEX


def test_successful_outcome_exposes_report_directory_button(
    qt_app,
    sources,
    tmp_path,
) -> None:
    report_directory = tmp_path / "Echo_Report_20260815_143012"
    report_directory.mkdir()
    report_path = report_directory / "echo-report.html"
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")
    opened: list[Path] = []
    window = _main_window(qt_app, StubFacade(sources=sources))
    window._report_opener = lambda path: opened.append(path) or True
    window._directory_opener = lambda path: opened.append(path) or True

    window.show_outcome(
        _StubOutcome(
            _dashboard_view(),
            report_path=report_path,
            report_directory=report_directory,
        )
    )

    assert window._current_report_directory == report_directory.resolve()
    assert window._open_report_directory_button.isVisibleTo(window)
    assert window._open_report_directory_button.isEnabled()
    window._open_report_directory_button.click()

    assert opened == [report_path.resolve(), report_directory.resolve()]


def test_report_directory_button_falls_back_to_report_parent(
    qt_app,
    sources,
    tmp_path,
) -> None:
    report_path = tmp_path / "echo-report.html"
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")
    opened: list[Path] = []
    window = _main_window(qt_app, StubFacade(sources=sources))
    window._report_opener = lambda path: True
    window._directory_opener = lambda path: opened.append(path) or True

    window.show_outcome(_StubOutcome(_dashboard_view(), report_path=report_path))

    assert window._current_report_directory == report_path.resolve().parent
    window._open_report_directory_button.click()
    assert opened == [report_path.resolve().parent]


def test_report_directory_open_failure_is_recoverable(
    qt_app,
    sources,
    tmp_path,
    monkeypatch,
) -> None:
    main_window_module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    monkeypatch.setattr(
        main_window_module.QMessageBox, "warning", lambda *_args: None
    )
    report_directory = tmp_path / "Echo_Report_20260815_143012"
    report_directory.mkdir()
    report_path = report_directory / "echo-report.html"
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")

    def _failing_directory_opener(path):
        raise OSError("fictional directory open failure")

    window = _main_window(qt_app, StubFacade(sources=sources))
    window._report_opener = lambda path: True
    window._directory_opener = _failing_directory_opener

    window.show_outcome(
        _StubOutcome(
            _dashboard_view(),
            report_path=report_path,
            report_directory=report_directory,
        )
    )
    window.open_echo_report_directory()

    assert "无法打开报告目录" in window._status_label.text()
    assert window._open_report_directory_button.isVisibleTo(window)


def test_generate_share_button_creates_and_opens_share_image(
    qt_app,
    sources,
    tmp_path,
) -> None:
    report_path = tmp_path / "echo-report.html"
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")
    share_path = tmp_path / "echo-share.png"
    share_path.write_bytes(b"fictional-share-png")
    opened: list[Path] = []
    outcome = _StubOutcome(_dashboard_view(), report_path=report_path)
    facade = StubFacade(sources=sources, share_image_path=share_path)
    window = _main_window(qt_app, facade)
    window._report_opener = lambda path: True
    window._image_opener = lambda path: opened.append(path) or True

    window.show_outcome(outcome)

    assert window._generate_share_button.isVisibleTo(window)
    assert window._generate_share_button.isEnabled()
    window._generate_share_button.click()

    assert facade.generate_share_image_calls == [outcome]
    assert window._status_label.text() == "分享图片已生成"
    assert opened == [share_path.resolve()]


def test_generate_share_failure_shows_public_message(
    qt_app,
    sources,
    tmp_path,
    monkeypatch,
) -> None:
    module = _facade_module()
    main_window_module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    monkeypatch.setattr(
        main_window_module.QMessageBox, "warning", lambda *_args: None
    )
    report_path = tmp_path / "echo-report.html"
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")
    facade = StubFacade(
        sources=sources,
        share_image_error=module.FacadeError(
            code="share_image_generation_failed",
            public_message="分享图片生成失败，请稍后重试。",
        ),
    )
    window = _main_window(qt_app, facade)
    window._report_opener = lambda path: True

    window.show_outcome(_StubOutcome(_dashboard_view(), report_path=report_path))
    window._generate_share_button.click()

    assert window._status_label.text() == (
        "分享图片生成失败，请稍后重试。"
    )
    assert window._generate_share_button.isEnabled()


def test_generate_share_without_outcome_shows_visible_error(
    qt_app,
    sources,
    monkeypatch,
) -> None:
    main_window_module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    monkeypatch.setattr(
        main_window_module.QMessageBox, "warning", lambda *_args: None
    )
    window = _main_window(qt_app, StubFacade(sources=sources))

    window.generate_share_image()

    assert window._status_label.text() == (
        "暂时没有可生成分享图片的分析结果。"
    )


def test_generate_share_without_facade_method_shows_visible_error(
    qt_app,
    sources,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delattr(StubFacade, "generate_share_image")
    main_window_module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    monkeypatch.setattr(
        main_window_module.QMessageBox, "warning", lambda *_args: None
    )
    report_path = tmp_path / "echo-report.html"
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")
    window = _main_window(qt_app, StubFacade(sources=sources))
    window._report_opener = lambda path: True

    window.show_outcome(_StubOutcome(_dashboard_view(), report_path=report_path))
    window.generate_share_image()

    assert window._status_label.text() == (
        "暂时没有可生成分享图片的分析结果。"
    )


def test_generate_share_executor_submission_failure_is_visible(
    qt_app,
    sources,
    tmp_path,
    monkeypatch,
) -> None:
    main_window_module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    monkeypatch.setattr(
        main_window_module.QMessageBox, "warning", lambda *_args: None
    )
    report_path = tmp_path / "echo-report.html"
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")

    def _failing_executor(*args, **kwargs):
        raise RuntimeError("fictional executor failure")

    window = _main_window(
        qt_app,
        StubFacade(sources=sources),
        executor=_failing_executor,
    )
    window._report_opener = lambda path: True

    window.show_outcome(_StubOutcome(_dashboard_view(), report_path=report_path))
    window._generate_share_button.click()

    assert window._status_label.text() == (
        "分享图片生成失败，请稍后重试。"
    )
    assert window._generate_share_button.isEnabled()


@pytest.mark.parametrize("published", [True, False])
def test_show_outcome_saved_status_uses_package_publication(qt_app, sources, tmp_path, published):
    report = tmp_path / "echo-report.html"
    report.write_text("fictional", encoding="utf-8")
    window = _main_window(qt_app, StubFacade(sources=sources))
    window._report_opener = lambda path: True
    window.show_outcome(_StubOutcome(_dashboard_view(), report_path=report,
                                    report_directory=tmp_path if published else None))
    assert window._status_label.text() == ("报告已保存" if published else "分析完成，报告暂未保存。")


@pytest.mark.parametrize("open_success", [True, False])
def test_show_outcome_retention_warning_keeps_successful_report_openable(
    qt_app, sources, tmp_path, open_success, monkeypatch,
):
    main_window_module = importlib.import_module("qq_chat_analyzer.gui.main_window")
    monkeypatch.setattr(
        main_window_module.QMessageBox, "warning", lambda *_args: None
    )
    report = tmp_path / "echo-report.html"
    report.write_text("fictional", encoding="utf-8")
    warning = "报告已保存，但部分旧报告清理失败，本地报告数量可能超过 50 份。"
    outcome = SimpleNamespace(
        report_path=report, report_directory=tmp_path, retention_warning=warning,
    )
    window = _main_window(qt_app, StubFacade(sources=sources))
    opened = []
    window._report_opener = lambda path: opened.append(path) or open_success
    window.show_outcome(outcome)
    assert warning in window._status_label.text()
    if open_success:
        assert window._status_label.text() == warning
    else:
        assert "\n" in window._status_label.text()
    assert opened == [report]
    assert window._current_report_directory == tmp_path


# -------------------------------------------------------------------- errors


# -------------------------------------------------------------------- layering


def test_gui_never_imports_analysis_provider_or_parser_internals() -> None:
    gui_directory = SRC_ROOT / "qq_chat_analyzer" / "gui"
    forbidden = (
        "from ..providers",
        "from ..parser",
        "from ..wechat_parser",
        "from ..analyzer",
        "from ..tokenizer",
        "from ..cleaner",
        "from ..qq_chat_exporter_adapter",
        "from ..wechat_db_adapter",
        "from ..wechat_cli_adapter",
        "import sqlite3",
    )

    for module_path in gui_directory.glob("*.py"):
        source = module_path.read_text(encoding="utf-8")
        if module_path.name == "app.py":
            continue
        for marker in forbidden:
            assert marker not in source, f"{module_path.name} imports {marker}"


def test_gui_pages_do_not_compute_statistics() -> None:
    gui_directory = SRC_ROOT / "qq_chat_analyzer" / "gui"

    for name in ("dashboard_page.py", "main_window.py"):
        source = (gui_directory / name).read_text(encoding="utf-8")
        for marker in ("Counter(", "statistics.", "sum(", "sorted("):
            assert marker not in source, f"{name} computes {marker}"


def test_gui_pages_only_import_the_facade_from_application() -> None:
    gui_directory = SRC_ROOT / "qq_chat_analyzer" / "gui"

    for name in (
        "dashboard_page.py",
        "main_window.py",
        "wechat_setup_dialog.py",
        "processing_page.py",
        "processing_animation_model.py",
    ):
        source = (gui_directory / name).read_text(encoding="utf-8")
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("from ..application"):
                assert "facade" in stripped, f"{name} imports {stripped}"


# ------------------------------------------------------------- read-only


def test_user_table_is_not_editable(qt_app) -> None:
    from PySide6.QtWidgets import QAbstractItemView

    page = _dashboard_page(qt_app)

    assert (
        page._user_table.editTriggers()
        == QAbstractItemView.EditTrigger.NoEditTriggers
    )


def test_conversation_table_is_not_editable(qt_app) -> None:
    from PySide6.QtWidgets import QAbstractItemView

    page = _dashboard_page(qt_app)

    assert (
        page._conversation_table.editTriggers()
        == QAbstractItemView.EditTrigger.NoEditTriggers
    )


def test_word_list_is_not_editable(qt_app) -> None:
    from PySide6.QtWidgets import QAbstractItemView

    page = _dashboard_page(qt_app)

    assert (
        page._word_list.editTriggers()
        == QAbstractItemView.EditTrigger.NoEditTriggers
    )


def test_report_widgets_stay_read_only_after_rendering(qt_app) -> None:
    from PySide6.QtWidgets import QAbstractItemView

    page = _dashboard_page(qt_app)
    page.render_view(_dashboard_view())

    for widget in (page._user_table, page._conversation_table, page._word_list):
        assert (
            widget.editTriggers()
            == QAbstractItemView.EditTrigger.NoEditTriggers
        )


def test_report_widgets_still_allow_selection(qt_app) -> None:
    from PySide6.QtWidgets import QAbstractItemView

    page = _dashboard_page(qt_app)

    for widget in (page._user_table, page._conversation_table, page._word_list):
        assert (
            widget.selectionMode()
            != QAbstractItemView.SelectionMode.NoSelection
        )


def _qq_snapshot(state, message="", action_hint="", version=None):
    """Build one QQ ConnectionSnapshot in a given lifecycle state."""
    connection = importlib.import_module(
        "qq_chat_analyzer.application.connection_models"
    )
    return connection.ConnectionSnapshot(
        state=connection.ConnectionState(state),
        source="qq",
        message=message,
        action_hint=action_hint,
        version=version,
    )


def test_qq_session_loading_coalesces_connected_callbacks_until_final_success(qt_app):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    executor = _DeferredExecutor()
    workspace = QQWorkspace(StubFacade(), executor=executor)
    errors = []
    workspace.analysis_failed.connect(lambda *args: errors.append(args))
    snapshot = _qq_snapshot("connected")
    workspace._show_qq_status(snapshot, True)
    workspace._show_qq_status(snapshot, True)

    assert executor.submission_count == 1
    sessions = [_session(_facade_module().ChatSource.QQ, "fictional", "Fictional group")]
    executor.succeed(sessions)
    assert workspace._sessions_loaded
    assert workspace.session_panel._sessions_ready
    assert errors == []
    workspace._show_qq_status(snapshot, True)
    assert executor.submission_count == 1
    assert workspace.session_panel._sessions_data == sessions


def test_qq_generation_error_discards_pending_session_result(qt_app):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    from qq_chat_analyzer.application.connection_models import ConnectionSnapshot, ConnectionState
    executor = _DeferredExecutor()
    workspace = QQWorkspace(StubFacade(), executor=executor)
    workspace._load_sessions()
    workspace._show_qq_status(ConnectionSnapshot(ConnectionState.ERROR, "qq",
        "QQ 运行环境已变化，请重新连接。", code="qq_reconnect_required"), False)
    executor.succeed([_session(_facade_module().ChatSource.QQ, "old", "Old group")])
    assert not workspace._sessions_loaded
    assert workspace._qq_connect_button.isEnabled()
    assert "重新连接" in workspace._status_label.text()


def test_qq_explicit_connect_invalidates_old_analysis_result(qt_app):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    workspace = QQWorkspace(StubFacade(), executor=_DeferredExecutor())
    panel = workspace.session_panel
    panel._analysis_operation = object()
    panel._set_busy(True)
    workspace.connect_qq()
    assert panel._analysis_operation is None


def test_qq_cancelled_queued_operations_do_not_use_new_connection(qt_app):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    executor = _DeferredExecutor()
    facade = StubFacade()
    calls = []
    facade.list_sessions = lambda source: calls.append("sessions") or []
    workspace = QQWorkspace(facade, executor=executor)
    workspace._load_sessions()
    sessions = executor.operation
    workspace._invalidate_session_request()
    assert sessions() == [] and calls == []
    panel = workspace.session_panel
    identity = object()
    panel._analysis_operation = identity
    panel._set_busy(True)
    panel._submit_analysis(lambda report: calls.append("analysis"), identity)
    analysis = executor.operation
    panel.cancel_analysis()
    analysis(lambda message: None)
    assert calls == []


def test_qq_old_disconnect_callback_cannot_replace_new_status(qt_app):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    executor = _IndependentDeferredExecutor()
    workspace = QQWorkspace(StubFacade(), executor=executor)
    workspace.disconnect_qq()
    old = executor.tasks[-1]
    workspace.connect_qq()
    workspace._qq_connect_in_flight = False
    workspace._show_qq_status(_qq_snapshot("connected", message="New connection"), False)
    old.succeed(_qq_snapshot("disconnected", message="Old disconnect"))
    assert "New connection" in workspace._status_label.text()


def test_qq_old_queued_disconnect_cannot_stop_new_connection(qt_app):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    executor = _DeferredExecutor()
    facade = StubFacade()
    workspace = QQWorkspace(facade, executor=executor)
    workspace.disconnect_qq()
    old_operation = executor.operation
    workspace.connect_qq()
    old_operation()
    assert facade.disconnect_qq_calls == []


def test_qq_session_loading_transient_acquisition_then_success_has_no_error(
    qt_app, tmp_path, monkeypatch,
):
    import json
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    from qq_chat_analyzer.providers import qq_direct_snapshot_runtime as runtime

    monkeypatch.setattr(runtime.time, "sleep", lambda _seconds: None)
    executor = _DeferredExecutor()
    facade = StubFacade()
    workspace = QQWorkspace(facade, executor=executor)
    errors = []
    workspace.analysis_failed.connect(lambda *args: errors.append(args))
    attempts = []

    def transport(_url, _payload, _timeout):
        attempts.append(True)
        if len(attempts) == 1:
            workspace._show_qq_status(_qq_snapshot("connected"), True)
            result = {"ok": False, "status": "failed", "code": "snapshot_unstable"}
        else:
            result = {"ok": True, "status": "ready", "generation_id": "fictional"}
        return 200, json.dumps({"id": "fictional", "ok": True, "result": result})

    client = runtime.QQDirectSnapshotRuntimeClient(
        "http://127.0.0.1:1", snapshot_root=tmp_path, transport=transport,
        boot_id="b" * 64,  # This retry fixture starts with a verified fictional binding.
    )
    sessions = [_session(_facade_module().ChatSource.QQ, "fictional", "Fictional group")]

    def list_sessions(_source):
        client.acquire()  # Real bounded retry; GUI sees only the final result.
        return sessions

    facade.list_sessions = list_sessions
    workspace._load_sessions()
    operation = executor.operation
    executor.succeed(operation())
    assert len(attempts) == 2
    assert executor.submission_count == 1
    assert workspace.session_panel._sessions_data == sessions
    assert errors == []


@pytest.mark.parametrize("old_failure_first", [True, False])
def test_qq_session_loading_ignores_old_failure_across_source_reset(qt_app, old_failure_first):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    executor = _DeferredExecutor()
    workspace = QQWorkspace(StubFacade(), executor=executor)
    errors = []
    workspace.analysis_failed.connect(lambda *args: errors.append(args))
    workspace._load_sessions()
    old_failure = executor.on_error
    workspace.select_source(_facade_module().ChatSource.QQ)
    workspace._load_sessions()
    sessions = [_session(_facade_module().ChatSource.QQ, "fictional", "Fictional group")]
    if old_failure_first:
        old_failure("qq_direct_snapshot_acquire_failed", "Fictional failure")
    executor.succeed(sessions)
    if not old_failure_first:
        old_failure("qq_direct_snapshot_acquire_failed", "Fictional failure")
    assert workspace._sessions_loaded
    assert workspace.session_panel._sessions_ready
    assert errors == []


@pytest.mark.parametrize("code", [
    "qq_direct_database_not_ready", "qq_direct_snapshot_acquire_failed",
    "qq_direct_snapshot_invalid", "qq_direct_snapshot_cleanup_failed",
    "qq_direct_database_recovery_failed", "unexpected_error",
])
def test_qq_session_loading_preserves_final_failure(qt_app, code):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    executor = _DeferredExecutor()
    workspace = QQWorkspace(StubFacade(), executor=executor)
    errors = []
    workspace.analysis_failed.connect(lambda *args: errors.append(args))
    workspace._load_sessions()
    executor.fail(code, "Fictional failure")
    # Reading the session list is part of connecting, so the failure is shown
    # on the page and never reported as an analysis failure.
    assert errors == []
    assert not workspace._sessions_loaded
    assert not workspace.session_panel._sessions_ready
    assert executor.submission_count == 1  # No GUI retries of acquisition errors.
    workspace._load_sessions()
    assert executor.submission_count == 2  # A later user action is still allowed.


def test_qq_session_loading_ignores_old_success_during_new_load(qt_app):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    executor = _DeferredExecutor()
    workspace = QQWorkspace(StubFacade(), executor=executor)
    workspace._load_sessions()
    old_success = executor.on_success
    workspace.select_source(_facade_module().ChatSource.QQ)
    workspace._load_sessions()
    old_success([])
    assert not workspace._sessions_loaded
    assert not workspace.session_panel._sessions_ready


def test_qq_session_loading_reconnect_starts_a_fresh_load(qt_app, instant_qq_connect):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    executor = _DeferredExecutor()
    workspace = QQWorkspace(StubFacade(), executor=executor)
    workspace._load_sessions()
    executor.succeed([])
    workspace.connect_qq()
    executor.succeed(_qq_snapshot("connected"))
    _drain(workspace)
    assert executor.submission_count == 3  # Initial load, connect, fresh load.
    assert not workspace._sessions_loaded


def test_qq_waiting_cancel_button_disconnects_instead_of_authorizing(qt_app):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    facade = StubFacade()
    executor = _IndependentDeferredExecutor()
    workspace = QQWorkspace(facade, executor=executor)
    workspace._show_qq_status(_qq_snapshot("waiting_auth"), False)
    # A usable QR enables this action; no real QR or account is needed here.
    workspace._qq_connect_button.setEnabled(True)
    workspace._qq_connect_button.click()

    assert not workspace._qq_status_timer.isActive()
    assert workspace._progress_track.isHidden()
    assert workspace._qq_qrcode_label.isHidden()
    assert len(executor.tasks) == 1
    task = executor.tasks[0]
    task.succeed(task.operation())
    assert facade.disconnect_qq_calls == [1]
    assert facade.start_qq_auth_flow_calls == []
    assert not workspace._qq_connect_in_flight
    assert workspace._qq_connect_button.isEnabled()
    assert workspace._qq_connect_button.isVisibleTo(workspace)


def test_qq_sessions_failure_exits_journey_and_preserves_error(qt_app):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    executor = _IndependentDeferredExecutor()
    workspace = QQWorkspace(StubFacade(), executor=executor)
    errors = []
    workspace.analysis_failed.connect(lambda *args: errors.append(args))
    workspace.show()
    try:
        workspace._show_qq_status(_qq_snapshot("connected"), True)
        assert workspace._session_loading_book._timer.isActive()
        executor.tasks[0].fail("qq_direct_snapshot_acquire_failed", "Fictional safe error")

        assert workspace._progress_track.isHidden()
        assert workspace._session_loading.isHidden()
        assert not workspace._session_loading_book._timer.isActive()
        assert not workspace._qq_status_timer.isActive()
        assert workspace._status_label.isVisibleTo(workspace)
        assert workspace._status_label.toolTip() == "Fictional safe error"
        assert workspace._qq_connect_button.isVisibleTo(workspace)
        assert workspace._qq_connect_button.isEnabled()
        assert workspace._qq_connect_button.text() == "重新开始"
        assert workspace._qq_disconnect_button.isHidden()
        # Reading the session list is part of connecting: the failure is shown
        # on the page and must not surface as an analysis failure.
        assert errors == []
    finally:
        workspace.hide()


def test_qq_cancel_ignores_already_submitted_status_poll(qt_app):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    facade = StubFacade()
    executor = _IndependentDeferredExecutor()
    workspace = QQWorkspace(facade, executor=executor)
    workspace._show_qq_status(_qq_snapshot("waiting_auth"), False)
    workspace._poll_qq_status()
    poll = executor.tasks[0]
    workspace._qq_connect_button.setEnabled(True)
    workspace._qq_connect_button.click()
    disconnect = executor.tasks[1]
    disconnect.succeed(disconnect.operation())
    poll.succeed(_qq_snapshot("connected"))

    assert len(executor.tasks) == 2
    assert workspace._progress_track.isHidden()
    assert workspace._session_loading.isHidden()
    assert workspace._session_request is None
    assert not workspace._qq_status_timer.isActive()


def test_qq_session_loading_keeps_a_lightweight_echo_waiting_state(qt_app):
    """The session read keeps its waiting copy, as the connection page's quiet
    status - not as the old grey card with an infinite blue bar."""
    from PySide6.QtWidgets import QLabel, QProgressBar
    from qq_chat_analyzer.gui import theme
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    executor = _DeferredExecutor()
    workspace = QQWorkspace(StubFacade(), executor=executor)
    workspace._show_qq_status(
        _qq_snapshot("connected", "Connected"), True,
    )

    loading = workspace._session_loading
    assert loading.isVisibleTo(workspace)
    assert loading.objectName() == "qqSessionLoading"
    assert "QWidget#qqSessionLoading" in theme.QQ_SETUP_QSS
    assert [label.text() for label in loading.findChildren(QLabel)] == [
        "正在准备聊天记录",
        "首次连接可能需要一点时间，Echo 正在整理可读取的会话内容。",
    ]
    assert loading.findChildren(QProgressBar) == []
    assert workspace._status_label.text().endswith("Connected")
    sessions = [_session(_facade_module().ChatSource.QQ, "fictional", "Fictional group")]
    executor.succeed(sessions)
    assert not workspace._session_loading.isVisibleTo(workspace)
    assert workspace.session_panel._session_box.isVisibleTo(workspace)
    assert workspace.session_panel._sessions_data == sessions
    workspace._show_qq_status(
        _qq_snapshot("connected", "Connected"), True,
    )
    assert not workspace._session_loading.isVisibleTo(workspace)
    assert executor.submission_count == 1


@pytest.mark.parametrize("size", [(1200, 760), (800, 600)])
def test_qq_session_loading_block_paints_no_card_and_stays_compact(
    qt_app, sources, size
) -> None:
    """The fourth-stage loading group stays centered on transparent paper."""
    from PySide6.QtGui import QColor, QPixmap
    from qq_chat_analyzer.gui.main_window import QQ_WORKSPACE_INDEX
    from qq_chat_analyzer.gui.theme import BASE_QSS

    facade = _GatedQRFacade(
        _qq_snapshot("waiting_auth"),
        _qq_snapshot("waiting_auth"),
        sources=sources,
    )
    window = _main_window(qt_app, facade, executor=_IndependentDeferredExecutor())
    window.setStyleSheet(BASE_QSS)
    window.stack.setCurrentIndex(QQ_WORKSPACE_INDEX)
    page = window.qq_workspace
    window.resize(*size)
    window.show()
    page._show_qq_stage(3)
    page._session_loading.show()
    _drain(window)
    try:
        loading = page._session_loading
        assert loading.isVisibleTo(page)
        action = page._session_loading_action
        note = page._session_loading_note
        assert action.isVisibleTo(page)
        assert note.isVisibleTo(page)
        # The animation and copy form one centered group in the loading region.
        book = page._session_loading_book
        assert book.size().width() == book.size().height() == 60
        assert abs(book.geometry().center().x() - loading.width() / 2) < 3
        assert book.geometry().bottom() < action.y()
        assert action.geometry().bottom() < note.y()
        assert note.geometry().bottom() < page._session_loading_exit.y()
        assert abs((book.y() + page._session_loading_exit.geometry().bottom()) / 2 - loading.height() / 2) < 25
        assert book._timer.isActive()
        page._show_qq_stage(2)
        assert not book._timer.isActive()
        page._show_qq_stage(3)
        assert book._timer.isActive()
        page._leave_qq_journey()
        assert not book._timer.isActive()
        page._show_qq_stage(3)
        # Nothing of the block's own is painted: the page's paper stays visible.
        probe = QPixmap(loading.size())
        probe.fill(QColor("#ff00ff"))
        loading.render(probe)
        assert (
            probe.toImage().pixelColor(loading.width() - 2, loading.height() - 2)
            == QColor("#ff00ff")
        )
    finally:
        window.hide()


def test_qq_session_loading_state_ends_before_final_error_and_returns_on_retry(qt_app):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    executor = _DeferredExecutor()
    workspace = QQWorkspace(StubFacade(), executor=executor)
    analysis_failures = []
    workspace.analysis_failed.connect(
        lambda *args: analysis_failures.append(args)
    )
    workspace._load_sessions()
    assert workspace._session_loading.isVisibleTo(workspace)
    executor.fail("qq_direct_snapshot_acquire_failed", "Fictional failure")
    # The reading indicator is already gone when the error lands, and a session
    # read failure is never reported as an analysis failure.
    assert not workspace._session_loading.isVisibleTo(workspace)
    assert analysis_failures == []
    workspace._load_sessions()
    assert workspace._session_loading.isVisibleTo(workspace)
    executor.succeed([])
    assert not workspace._session_loading.isVisibleTo(workspace)


@pytest.mark.parametrize("callback", ["on_success", "on_error"])
def test_qq_session_loading_stale_callback_keeps_current_indicator(qt_app, callback):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    executor = _DeferredExecutor()
    workspace = QQWorkspace(StubFacade(), executor=executor)
    workspace._load_sessions()
    old_callback = getattr(executor, callback)
    workspace.select_source(_facade_module().ChatSource.QQ)
    assert not workspace._session_loading.isVisibleTo(workspace)
    workspace._load_sessions()
    if callback == "on_success":
        old_callback([])
    else:
        old_callback("qq_direct_snapshot_acquire_failed", "Fictional old failure")
    assert workspace._session_loading.isVisibleTo(workspace)
    assert not workspace._sessions_loaded
    executor.succeed([])
    assert not workspace._session_loading.isVisibleTo(workspace)


def test_qq_session_loading_reconnect_indicator_waits_for_fresh_request(qt_app, instant_qq_connect):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    executor = _DeferredExecutor()
    workspace = QQWorkspace(StubFacade(), executor=executor)
    workspace._load_sessions()
    workspace.connect_qq()
    assert not workspace._session_loading.isVisibleTo(workspace)
    executor.succeed(_qq_snapshot("connected"))
    _drain(workspace)
    assert workspace._session_loading.isVisibleTo(workspace)
    executor.succeed([])
    assert not workspace._session_loading.isVisibleTo(workspace)


def test_qq_session_loading_timing_logs_contain_only_stage_and_durations(qt_app, caplog):
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    executor = _DeferredExecutor()
    workspace = QQWorkspace(StubFacade(), executor=executor)
    with caplog.at_level("INFO", logger="qq_chat_analyzer.desktop.qq_workspace"):
        workspace._load_sessions()
        executor.succeed([
            _session(_facade_module().ChatSource.QQ, "fictional-private-id", "Fictional private name")
        ])
    messages = [record.getMessage() for record in caplog.records if "[qq sessions]" in record.getMessage()]
    assert messages[0] == "[qq sessions] request started"
    assert messages[1].startswith("[qq sessions] request completed elapsed=")
    assert " render_elapsed=" in messages[1]
    assert "fictional-private-id" not in " ".join(messages)
    assert "Fictional private name" not in " ".join(messages)


class _SnapshotFacade(StubFacade):
    """Return one fixed QQ snapshot regardless of the underlying status."""

    def __init__(self, snapshot, **kwargs):
        super().__init__(**kwargs)
        self._snapshot = snapshot

    def set_snapshot(self, snapshot):
        self._snapshot = snapshot

    def _qq_snapshot(self):
        return self._snapshot


class _ConnectWaitingAuthFacade(_SnapshotFacade):
    """Return a fixed status snapshot but a WAITING_AUTH connect result."""

    def __init__(self, status_snapshot, connect_snapshot, **kwargs):
        super().__init__(status_snapshot, **kwargs)
        self._connect_snapshot = connect_snapshot

    def start_qq_auth_flow(self, progress=None, *, cancel_event=None):
        self.start_qq_auth_flow_calls.append(1)
        return self._connect_snapshot


class _GatedQRFacade(_ConnectWaitingAuthFacade):
    """Simulate a fresh auth session that gates the QR file until it changes."""

    def __init__(self, status_snapshot, connect_snapshot, **kwargs):
        super().__init__(status_snapshot, connect_snapshot, **kwargs)
        self.qr_ready = False
        self.qr_path = None

    def is_qq_qrcode_ready(self):
        return self.qr_ready

    def get_qq_qrcode_path(self):
        return self.qr_path if self.qr_ready else None


def _write_qrcode_png(path: Path) -> None:
    from PySide6.QtGui import QPixmap

    pixmap = QPixmap(8, 8)
    pixmap.fill(Qt.GlobalColor.black)
    assert pixmap.save(str(path)) is True


@pytest.mark.parametrize("runtime_mode", ["managed", "custom"])
def test_qq_gui_reads_fresh_qr_from_auth_workspace(qt_app, tmp_path, runtime_mode, monkeypatch):
    """Display the bridge's QR, never an installation or previous session QR."""
    from PySide6.QtGui import QPixmap
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
    from qq_chat_analyzer.application.qq.qq_auth_bridge import QQAuthBridge
    from qq_chat_analyzer.application.qq import qq_auth_bridge
    monkeypatch.setattr(qq_auth_bridge, "find_conflicting_qq_pids", lambda owned: [])
    from qq_chat_analyzer.application.qq.qq_environment_config import QQEnvironmentConfig
    from qq_chat_analyzer.application.qq.qq_runtime_paths import (
        qq_runtime_paths, resolve_runtime_paths,
    )
    from qq_chat_analyzer.application.qq.qq_setup_service import QQSetupService
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    program = tmp_path / "fictional-program"
    config = QQEnvironmentConfig(runtime_directory=program, runtime_mode=runtime_mode)
    paths = (qq_runtime_paths(component_id="a" * 64, program_root=program,
                              data_root=tmp_path / "user")
             if runtime_mode == "managed" else resolve_runtime_paths(config))
    qr = (tmp_path / "user/runtime/qq" / ("a" * 64) / "cache/qrcode.png"
          if runtime_mode == "managed" else program / "cache/qrcode.png")
    qr.parent.mkdir(parents=True)
    stale = QPixmap(8, 8)
    stale.fill(Qt.GlobalColor.white)
    assert stale.save(str(qr))
    setup = QQSetupService(config_loader=SimpleNamespace(
        load_or_default=lambda: config, runtime_paths=lambda **_: paths,
    ))
    manager = SimpleNamespace(
        get_snapshot=lambda: _qq_snapshot("disconnected"),
        begin_auth_waiting=lambda: None, end_auth_waiting=lambda: None,
        disconnect=lambda: _qq_snapshot("disconnected"),
    )
    bridge = QQAuthBridge(setup_service=setup, manager=manager,
                          window_launcher=lambda: None, runtime_cleaner=lambda _: None)
    facade = ChatAnalyzerFacade(qq_auth_bridge=bridge)
    workspace = QQWorkspace(facade, executor=_inline_executor())

    workspace._refresh_qq_qrcode()
    assert workspace._qq_qrcode_label.isHidden()
    facade.start_qq_auth_flow()
    workspace._show_qq_status(_qq_snapshot("waiting_auth"), False)
    assert workspace._qq_qrcode_label.isHidden()
    assert workspace._qq_guide_label.text() == "等待 QQ 登录，请在 QQ 登录窗口完成登录。"
    assert "扫码" not in workspace._qq_login_guide_label.text()
    _write_qrcode_png(qr)
    workspace._show_qq_status(_qq_snapshot("waiting_auth"), False)
    assert workspace._qq_qrcode_label.isVisibleTo(workspace)
    assert workspace._qq_guide_label.text() == "请使用手机 QQ 扫码登录"
    assert facade.get_qq_qrcode_path() == qr
    assert bridge.get_qrcode_path() == qr

    # A new GUI instance must not reuse an old runtime's otherwise fresh QR.
    other = ChatAnalyzerFacade(qq_auth_bridge=QQAuthBridge(setup_service=setup))
    assert other.get_qq_qrcode_path() is None
    qr.write_bytes(b"fictional invalid PNG")
    workspace._refresh_qq_qrcode()
    assert workspace._qq_qrcode_label.isHidden()
    qr.unlink()
    workspace._refresh_qq_qrcode()
    assert workspace._qq_qrcode_label.isHidden()
    assert facade.get_qq_qrcode_path() is None

    _write_qrcode_png(qr)
    facade.disconnect_qq()
    assert facade.get_qq_qrcode_path() is None
    # Reconnection resolves the current workspace rather than a GUI-cached path.
    if runtime_mode == "managed":
        paths = qq_runtime_paths(component_id="b" * 64, program_root=program,
                                 data_root=tmp_path / "user")
        next_qr = tmp_path / "user/runtime/qq" / ("b" * 64) / "cache/qrcode.png"
    else:
        config = dataclasses.replace(config, runtime_directory=tmp_path / "custom-second")
        paths = resolve_runtime_paths(config)
        next_qr = tmp_path / "custom-second/cache/qrcode.png"
    facade.start_qq_auth_flow()
    workspace._refresh_qq_qrcode()
    assert workspace._qq_qrcode_label.isHidden()
    next_qr.parent.mkdir(parents=True)
    _write_qrcode_png(next_qr)
    workspace._refresh_qq_qrcode()
    assert workspace._qq_qrcode_label.isVisibleTo(workspace)
    assert facade.get_qq_qrcode_path() == next_qr


def test_poll_displays_qr_before_snapshot_worker_completes(
    qt_app,
    sources,
    tmp_path: Path,
) -> None:
    """QR refresh must not wait for the async snapshot/health worker.

    While waiting for auth, a ready local QR file has to be shown during the
    current poll even when ``get_qq_connection_snapshot`` is still blocked.
    """
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    qr_path = tmp_path / "qrcode.png"
    _write_qrcode_png(qr_path)

    snapshot_started = threading.Event()
    release = threading.Event()

    class _BlockingSnapshotFacade(_GatedQRFacade):
        def get_qq_connection_snapshot(self):
            self.get_qq_connection_snapshot_calls.append(1)
            snapshot_started.set()
            release.wait(timeout=5)
            return self._qq_snapshot()

    facade = _BlockingSnapshotFacade(
        _qq_snapshot("waiting_auth"),
        _qq_snapshot("waiting_auth"),
        sources=sources,
    )
    facade.qr_ready = True

    workspace = QQWorkspace(facade)
    facade.qr_path = qr_path
    workspace._qq_waiting_auth_since = time.monotonic()

    try:
        workspace._poll_qq_status()

        assert snapshot_started.wait(timeout=2)

        assert workspace._qq_qrcode_label.isVisibleTo(workspace) is True
    finally:
        release.set()
        _settle_workers()


# ---------------------------------------------------------------- GUI-2: Home + Navigation

def test_main_window_starts_at_home_page(qt_app, sources) -> None:
    """MainWindow starts with HomePage visible."""
    from qq_chat_analyzer.gui.main_window import HOME_PAGE_INDEX
    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)
    assert window.stack.currentIndex() == HOME_PAGE_INDEX
    # home_page is the current (top) page in the stack


def test_main_window_default_size_is_shared_and_remains_resizable(qt_app, sources):
    window = _main_window(qt_app, StubFacade(sources=sources))
    window.show()
    _drain(window)
    assert window.size().toTuple() == (1200, 760)
    assert window.minimumSize().toTuple() == (800, 600)
    assert not window.windowFlags() & Qt.FramelessWindowHint
    for navigate in (window.show_qq_workspace, window.show_wechat_workspace,
                     window.show_local_data_page, window.show_home_page):
        navigate()
        _drain(window)
        assert window.size().toTuple() == (1200, 760)
    window.resize(900, 650)
    _drain(window)
    assert window.size().toTuple() == (900, 650)
    window.hide()


@pytest.mark.parametrize("activation", ["mouse", "keyboard"])
@pytest.mark.parametrize(
    "name, destination, active_source",
    [("从QQ开始", 1, "qq"), ("从微信开始", 2, "wechat"),
     ("查看本地报告", 5, None)],
)
def test_home_entries_navigate_by_mouse_and_keyboard(
    qt_app, sources, name, destination, active_source, activation,
) -> None:
    """The two identically captioned start links must route to their own source."""
    from PySide6.QtWidgets import QPushButton

    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)
    window.show()
    _drain(window)
    buttons = window.home_page.findChildren(QPushButton)
    matches = [button for button in buttons if button.accessibleName() == name]
    assert len(matches) == 1
    button = matches[0]
    if activation == "mouse":
        QTest.mouseClick(button, Qt.LeftButton)
    else:
        button.setFocus()
        QTest.keyClick(button, Qt.Key_Space)
    _drain(window)
    assert window.stack.currentIndex() == destination
    assert window._active_source == active_source
    window.hide()


def test_home_uses_full_content_area_and_restores_workspace_header(qt_app, sources):
    """Home has no duplicate header or outer gutter; workspace chrome returns."""
    window = _main_window(qt_app, StubFacade(sources=sources))
    window.resize(960, 720)
    window.show()
    _drain(window)
    initial_size = window.size()
    assert not window._title_label.isVisibleTo(window)
    assert window.home_page.size() == window.centralWidget().size()

    window.show_qq_workspace()
    _drain(window)
    assert window._title_label.isVisibleTo(window)
    assert window._home_button.isVisibleTo(window)
    assert window.centralWidget().layout().contentsMargins().left() > 0

    window._home_button.click()
    _drain(window)
    assert not window._title_label.isVisibleTo(window)
    assert window.home_page.size() == window.centralWidget().size()
    assert window.size() == initial_size
    window.hide()


def test_home_theme_preserves_type_hierarchy_on_first_show(qt_app):
    """The generic Home rule must not flatten named title/secondary styles."""
    from PySide6.QtWidgets import QLabel, QWidget
    from qq_chat_analyzer.gui.home_page import HomePage
    from qq_chat_analyzer.gui.theme import BASE_QSS

    host = QWidget()
    host.setStyleSheet(BASE_QSS)
    page = HomePage(host)
    host.show()
    _drain(host)
    title = page.findChild(QLabel, "homeTitle")
    source = page.findChild(QLabel, "homeSourceName")
    description = page.findChild(QLabel, "homeSourceDescription")
    assert title.font().pixelSize() > source.font().pixelSize()
    assert source.font().pixelSize() > description.font().pixelSize()
    assert source.palette().windowText().color() != description.palette().windowText().color()
    host.hide()


@pytest.mark.parametrize("size", [(800, 600), (960, 720), (1200, 728), (1600, 900)])
def test_home_content_fits_resized_window(qt_app, sources, size):
    """Responsive gutters must keep source copy and all actions unclipped."""
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QLabel, QPushButton
    from qq_chat_analyzer.gui.theme import BASE_QSS

    window = _main_window(qt_app, StubFacade(sources=sources))
    window.setStyleSheet(BASE_QSS)
    window.resize(*size)
    window.show()
    _drain(window)
    page = window.home_page
    assert window.size().toTuple() == size
    for widget in page.findChildren(QLabel) + page.findChildren(QPushButton):
        bounds = QRect(widget.mapTo(page, QPoint()), widget.size())
        assert page.rect().contains(bounds), widget.objectName() or widget.text()
        if isinstance(widget, QLabel) and widget.wordWrap():
            assert widget.height() >= widget.heightForWidth(widget.width())
        else:
            assert widget.width() >= widget.sizeHint().width()
            assert widget.height() >= widget.sizeHint().height()
    assert page._sources.geometry().bottom() < page._local_data_btn.geometry().top()
    window.hide()


def test_home_tab_order_follows_source_then_report_hierarchy(qt_app, sources):
    window = _main_window(qt_app, StubFacade(sources=sources))
    window.show()
    _drain(window)
    page = window.home_page
    page._qq_btn.setFocus()
    QTest.keyClick(page._qq_btn, Qt.Key_Tab)
    assert page._wechat_btn.hasFocus()
    QTest.keyClick(page._wechat_btn, Qt.Key_Tab)
    assert page._local_data_btn.hasFocus()
    QTest.keyClick(page._local_data_btn, Qt.Key_Backtab)
    assert page._wechat_btn.hasFocus()
    window.hide()


def test_click_qq_navigates_to_qq_workspace_with_qq_source(qt_app, sources) -> None:
    """Clicking QQ on HomePage navigates to QQWorkspace with QQ preselected."""
    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)
    window.navigate_to_qq()
    _drain(window)
    from qq_chat_analyzer.gui.main_window import QQ_WORKSPACE_INDEX
    assert window.stack.currentIndex() == QQ_WORKSPACE_INDEX
    from qq_chat_analyzer.gui.main_window import QQ_WORKSPACE_INDEX
    assert window.stack.currentIndex() == QQ_WORKSPACE_INDEX
def test_click_wechat_navigates_to_wechat_workspace_with_wechat_source(qt_app, sources) -> None:
    """Clicking WeChat on HomePage navigates to WeChatWorkspace with WeChat preselected."""
    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)
    window.navigate_to_wechat()
    _drain(window)
    from qq_chat_analyzer.gui.main_window import WECHAT_WORKSPACE_INDEX
    assert window.stack.currentIndex() == WECHAT_WORKSPACE_INDEX
    from qq_chat_analyzer.gui.main_window import WECHAT_WORKSPACE_INDEX
    assert window.stack.currentIndex() == WECHAT_WORKSPACE_INDEX
    """Clicking local data on HomePage navigates to LocalDataPage."""
    from qq_chat_analyzer.gui.main_window import LOCAL_DATA_PAGE_INDEX
    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)
    window.show_local_data_page()
    _drain(window)
    assert window.stack.currentIndex() == LOCAL_DATA_PAGE_INDEX
    # local_data_page is the current (top) page in the stack


def test_local_data_page_uses_global_home_navigation(qt_app, sources) -> None:
    """History keeps one home entry in the global navigation."""
    from PySide6.QtWidgets import QPushButton
    from qq_chat_analyzer.gui.main_window import HOME_PAGE_INDEX
    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)
    window.show_local_data_page()
    _drain(window)
    assert window._home_button.isVisibleTo(window)
    assert "返回首页" not in {
        button.text() for button in window.local_data_page.findChildren(QPushButton)
    }
    window._home_button.click()
    _drain(window)
    assert window.stack.currentIndex() == HOME_PAGE_INDEX


def test_workspace_can_return_to_home_from_home_button(qt_app, sources) -> None:
    """The home button in the header returns to HomePage from a workspace."""
    from qq_chat_analyzer.gui.main_window import HOME_PAGE_INDEX
    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)
    window.show_qq_workspace()
    _drain(window)
    window.show()
    _drain(window)
    assert window._home_button.isVisible() is True
    window._home_button.click()
    _drain(window)
    assert window.stack.currentIndex() == HOME_PAGE_INDEX


def test_home_button_hidden_on_home_page(qt_app, sources) -> None:
    """Home button is hidden when on HomePage."""
    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)
    assert window._home_button.isVisible() is False


def test_page_switch_does_not_change_window_size_with_home_page(qt_app, sources) -> None:
    """Switching pages does not resize the window (incl. HomePage)."""
    facade = StubFacade(sources=sources)
    window = _main_window(qt_app, facade)
    window.show()
    window.resize(960, 720)
    initial = window.size()
    window.show_qq_workspace()
    _drain(window)
    assert window.size() == initial
    window.show_local_data_page()
    _drain(window)
    assert window.size() == initial
    window.show_home_page()
    _drain(window)
    assert window.size() == initial


# ----------------------------------------------------------------

# ----------------------------------------------------------------
# GUI-3 stabilization: restore GUI-2 workspace behavior equivalence
# ----------------------------------------------------------------


def test_wechat_workspace_uses_connection_status_facade_api(
    qt_app, sources
) -> None:
    """WeChat status flows through facade.get_connection_status(WECHAT)."""
    from qq_chat_analyzer.gui.main_window import WECHAT_WORKSPACE_INDEX
    module = _facade_module()
    status = module.WeChatConnectionStatus(
        available=False, data_found=False, db_key_available=False,
        runtime_available=False, message="微信尚未连接。", action_hint="",
    )
    facade = StubFacade(sources=sources, connection_status=status)
    window = _main_window(qt_app, facade)
    window.navigate_to_wechat()
    _drain(window)

    assert window.stack.currentIndex() == WECHAT_WORKSPACE_INDEX
    assert facade.get_connection_status_calls == [module.ChatSource.WECHAT]
    assert "微信" in window.wechat_workspace._status_label.text()
    assert window.wechat_workspace._wechat_connect_button.isVisibleTo(window) is True
    assert window.wechat_workspace.session_panel._sessions_ready is False


def test_qq_workspace_shows_connect_button_when_disconnected(
    qt_app, sources
) -> None:
    """QQ disconnected status shows the connect action and no sessions."""
    from qq_chat_analyzer.gui.main_window import QQ_WORKSPACE_INDEX
    module = _facade_module()
    status = module.QQConnectionStatus(
        available=False, runtime_running=False, qq_online=False,
        version="", message="QQ 服务未运行。", action_hint="",
    )
    facade = StubFacade(
        sources=sources,
        connection_status=status,
        sessions=[_session(module.ChatSource.QQ, "10001", "虚构群")],
    )
    window = _main_window(qt_app, facade)
    window.navigate_to_qq()
    _drain(window)

    assert window.stack.currentIndex() == QQ_WORKSPACE_INDEX
    assert window.qq_workspace._qq_connect_button.isVisibleTo(window) is True
    assert window.qq_workspace._qq_connect_button.isEnabled()
    assert window.qq_workspace.session_panel._sessions_ready is False


def test_qq_workspace_connect_disables_button_until_finish(
    qt_app,
    sources,
    instant_qq_connect,
) -> None:
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    facade = StubFacade(sources=sources)
    executor = _DeferredExecutor()
    workspace = QQWorkspace(facade, executor=executor)

    workspace.connect_qq()
    assert workspace._qq_connect_button.isEnabled() is False

    executor.progress("等待QQ登录")
    assert workspace._qq_connect_button.isEnabled() is False

    executor.fail("qq_connect_failed", "QQ 连接失败")
    _drain(workspace)
    assert workspace._qq_connect_button.isEnabled() is True
    assert workspace._qq_connect_button.text() == "重新开始"

    cancel_workspace = QQWorkspace(facade, executor=_DeferredExecutor())
    cancel_workspace.connect_qq()
    cancel_workspace.cancel_connection()
    assert cancel_workspace._qq_connect_button.isEnabled() is True
    assert cancel_workspace._qq_connect_button.text() == "连接QQ"


def test_qq_workspace_waiting_auth_disables_button_until_qr_ready(
    qt_app,
    sources,
    tmp_path: Path,
    instant_qq_connect,
) -> None:
    """Regression: the connect button must stay disabled while QR is not ready."""
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    from PySide6.QtGui import QPixmap

    qr_path = tmp_path / "qrcode.png"
    pixmap = QPixmap(8, 8)
    pixmap.fill(Qt.GlobalColor.black)
    assert pixmap.save(str(qr_path)) is True

    facade = _GatedQRFacade(
        _qq_snapshot("waiting_auth"),
        _qq_snapshot("waiting_auth"),
        sources=sources,
    )
    facade.qr_ready = False
    workspace = QQWorkspace(facade, executor=_inline_executor())
    facade.qr_path = qr_path

    workspace.connect_qq()
    _drain(workspace)

    assert workspace._qq_qrcode_label.isVisibleTo(workspace) is False
    assert workspace._qq_connect_button.isEnabled() is False


def test_qq_workspace_waiting_auth_enables_button_once_qr_displayed(
    qt_app,
    sources,
    tmp_path: Path,
    instant_qq_connect,
) -> None:
    """Once the QR is actually displayed, the connect button becomes enabled."""
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    from PySide6.QtGui import QPixmap

    qr_path = tmp_path / "qrcode.png"
    pixmap = QPixmap(8, 8)
    pixmap.fill(Qt.GlobalColor.black)
    assert pixmap.save(str(qr_path)) is True

    facade = _GatedQRFacade(
        _qq_snapshot("waiting_auth"),
        _qq_snapshot("waiting_auth"),
        sources=sources,
    )
    facade.qr_ready = True
    workspace = QQWorkspace(facade, executor=_inline_executor())
    facade.qr_path = qr_path

    workspace.connect_qq()
    _drain(workspace)

    assert workspace._qq_qrcode_label.isVisibleTo(workspace) is True
    assert workspace._qq_connect_button.isEnabled() is True


@pytest.mark.parametrize(
    "next_state", ["initializing", "starting", "connected", "disconnected", "error"]
)
def test_qq_status_leaves_auth_wait_and_preserves_session_load_timing(
    qt_app, sources, tmp_path, next_state
) -> None:
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    from PySide6.QtGui import QPixmap

    facade = _GatedQRFacade(
        _qq_snapshot("waiting_auth"),
        _qq_snapshot("waiting_auth"),
        sources=sources,
    )
    facade.qr_ready = True
    workspace = QQWorkspace(facade, executor=_inline_executor())
    qr_path = tmp_path / "fictional-qr.png"
    pixmap = QPixmap(8, 8)
    pixmap.fill(Qt.GlobalColor.black)
    assert pixmap.save(str(qr_path))
    facade.qr_path = qr_path
    workspace._show_qq_status(
        _qq_snapshot("waiting_auth"), load_sessions_on_ready=False
    )
    assert workspace._qq_status_timer.isActive()
    assert workspace._qq_qrcode_label.isVisibleTo(workspace)

    state_at_session_load = []
    list_sessions = facade.list_sessions

    def observe_session_load(source):
        state_at_session_load.append((
            workspace._qq_status_timer.isActive(),
            workspace._qq_qrcode_label.isVisibleTo(workspace),
        ))
        return list_sessions(source)

    facade.list_sessions = observe_session_load
    workspace._show_qq_status(
        _qq_snapshot(next_state),
        load_sessions_on_ready=True,
    )

    assert not workspace._qq_status_timer.isActive()
    assert not workspace._qq_qrcode_label.isVisibleTo(workspace)
    assert workspace._qq_waiting_auth_since is None
    connected = next_state == "connected"
    assert workspace._qq_connect_button.isVisibleTo(workspace) is not connected
    assert workspace._qq_disconnect_button.isVisibleTo(workspace) is connected
    assert state_at_session_load == ([(True, True)] if connected else [])


def test_qq_workspace_offers_qq_exe_selection_when_install_path_missing(
    qt_app,
    tmp_path,
    monkeypatch,
) -> None:
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    module = importlib.import_module("qq_chat_analyzer.gui.qq_workspace")
    qq_path = tmp_path / "QQ.exe"
    qq_path.write_text("fictional", encoding="utf-8")
    facade = StubFacade(sources=())
    workspace = QQWorkspace(facade, executor=_inline_executor())
    dialog_calls = []

    def _fake_file_dialog(parent, title, directory, file_filter):
        dialog_calls.append((title, file_filter))
        return str(qq_path), ""

    monkeypatch.setattr(
        module.QFileDialog,
        "getOpenFileName",
        staticmethod(_fake_file_dialog),
    )
    snapshot = importlib.import_module(
        "qq_chat_analyzer.application.connection_models"
    ).ConnectionSnapshot(
        state=importlib.import_module(
            "qq_chat_analyzer.application.connection_models"
        ).ConnectionState.ERROR,
        source="qq",
        message="未检测到 QQ 客户端。",
        code="qq_install_path_missing",
    )

    workspace._show_qq_status(snapshot, load_sessions_on_ready=False)

    assert facade.set_qq_install_path_calls == [qq_path]
    assert facade.start_qq_auth_flow_calls == [1]
    assert dialog_calls == [
        (module._QQ_PATH_PROMPT_TITLE, module._QQ_PATH_PROMPT_FILTER)
    ]


# ---------------------------------------------------------------------------
# QQ connection journey in the shared Echo visual language
# ---------------------------------------------------------------------------


def test_qq_connection_trail_walks_prepare_start_scan_connect(
    qt_app, sources
) -> None:
    """The QQ journey draws the shared trail, stage by stage, without a
    second invitation to connect while it advances by itself."""
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    module = importlib.import_module("qq_chat_analyzer.gui.qq_workspace")
    facade = _SnapshotFacade(_qq_snapshot("waiting_auth"), sources=sources)
    executor = _DeferredExecutor()
    workspace = QQWorkspace(facade, executor=executor)

    assert module._QQ_CONNECT_STAGES == ("准备", "启动 QQ", "登录", "连接")
    assert workspace._progress_track.isHidden() is True

    workspace.connect_qq()
    assert workspace._progress_track.isVisibleTo(workspace) is True
    assert workspace._progress_track.stage == 0
    assert workspace._qq_guide_label.isVisibleTo(workspace) is True
    assert workspace._status_label.isVisibleTo(workspace) is False
    assert workspace._qq_connect_button.text() == "取消连接"

    workspace._handle_qq_connect_progress("正在启动 QQ 连接环境")
    assert workspace._progress_track.stage == 1
    assert workspace._qq_connect_button.text() != "连接QQ"

    workspace._handle_qq_connect_progress("等待QQ登录")
    assert workspace._progress_track.stage == 2
    assert workspace._qq_login_guide_label.isVisibleTo(workspace) is True
    assert workspace._qq_connect_button.text() != "连接QQ"


def test_qq_scan_stage_makes_the_qr_the_subject_then_hands_over_to_sessions(
    qt_app, sources, tmp_path: Path
) -> None:
    """The QR owns the scan stage; a loaded session list ends the journey."""
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    qr_path = tmp_path / "fictional-qq-qr.png"
    _write_qrcode_png(qr_path)
    facade = _GatedQRFacade(
        _qq_snapshot("waiting_auth"),
        _qq_snapshot("waiting_auth"),
        sources=sources,
        sessions=[_session(_facade_module().ChatSource.QQ, "q1", "虚构群")],
    )
    facade.qr_ready = True
    workspace = QQWorkspace(facade, executor=_inline_executor())
    facade.qr_path = qr_path

    workspace._show_qq_status(
        _qq_snapshot("waiting_auth"), load_sessions_on_ready=False
    )

    assert workspace._progress_track.stage == 2
    assert workspace._qq_qrcode_label.isVisibleTo(workspace) is True
    assert "扫码" in workspace._qq_guide_label.text()
    # The QR sits beside the copy, exactly like the guided setup's picture.
    assert workspace._qq_guide_row.itemAt(0).layout().count() >= 2
    assert workspace._qq_guide_row.itemAt(1).widget() is workspace._qq_qrcode_label

    workspace._show_qq_status(
        _qq_snapshot("connected"), load_sessions_on_ready=True,
    )

    assert workspace.session_panel._sessions_ready is True
    assert workspace._progress_track.isHidden() is True
    assert workspace._qq_qrcode_label.isVisibleTo(workspace) is False
    assert workspace._qq_guide_label.isVisibleTo(workspace) is False
    assert workspace._qq_login_guide_label.isVisibleTo(workspace) is False
    assert workspace._status_label.isVisibleTo(workspace) is True


def test_qq_connected_stage_covers_the_session_read(
    qt_app, sources
) -> None:
    """The trail's last stage stays up while the session list is still read."""
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    facade = _SnapshotFacade(
        _qq_snapshot("connected"), sources=sources,
    )
    executor = _DeferredExecutor()
    workspace = QQWorkspace(facade, executor=executor)

    workspace._show_qq_status(
        _qq_snapshot("connected"), load_sessions_on_ready=True,
    )

    assert workspace._progress_track.isVisibleTo(workspace) is True
    assert workspace._progress_track.stage == 3

    executor.succeed([_session(_facade_module().ChatSource.QQ, "q1", "虚构群")])
    assert workspace._progress_track.isHidden() is True


def test_qq_status_line_returns_for_idle_and_error_states(qt_app, sources) -> None:
    """Leaving the journey hands the top line back to the status label."""
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    facade = StubFacade(sources=sources)
    workspace = QQWorkspace(facade, executor=_DeferredExecutor())

    workspace._show_qq_status(
        _qq_snapshot("disconnected"), load_sessions_on_ready=False
    )

    assert workspace._progress_track.isHidden() is True
    assert workspace._qq_guide_label.isVisibleTo(workspace) is True
    assert workspace._qq_connect_button.text() == "连接QQ"

    workspace._show_qq_status(
        _qq_snapshot("initializing"), load_sessions_on_ready=False
    )
    assert workspace._progress_track.isVisibleTo(workspace) is True
    assert workspace._progress_track.stage == 0

    workspace._show_qq_status(_qq_snapshot("starting"), load_sessions_on_ready=False)
    assert workspace._progress_track.stage == 1

    workspace._show_qq_status(_qq_snapshot("error"), load_sessions_on_ready=False)
    assert workspace._progress_track.isHidden() is True
    assert workspace._qq_guide_label.isVisibleTo(workspace) is False
    assert workspace._qq_connect_button.text() == "重新开始"
    assert workspace._status_label.isVisibleTo(workspace) is True


def test_qq_connection_surface_uses_the_shared_echo_language(
    qt_app, sources
) -> None:
    """QQ's surface must reuse Home/WeChat's tokens, never a hand-tuned copy."""
    from qq_chat_analyzer.gui import theme
    from qq_chat_analyzer.gui.progress_track import ConnectionProgressTrack
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

    module = importlib.import_module("qq_chat_analyzer.gui.qq_workspace")
    workspace = QQWorkspace(StubFacade(sources=sources), executor=_DeferredExecutor())

    assert workspace.objectName() == "qqWorkspace"
    assert workspace._connection_surface.objectName() == "qqConnectionSurface"
    assert workspace.styleSheet() == theme.QQ_SETUP_QSS

    for token in (theme.HOME_COLOR_PAPER, theme.HOME_COLOR_ACCENT, theme.HOME_COLOR_TEXT):
        assert token in theme.QQ_SETUP_QSS
        assert token in theme.WECHAT_SETUP_QSS
    assert "font-size: 26px" in theme.QQ_GUIDE_STYLE
    assert "font-size: 26px" in theme.WECHAT_GUIDE_STYLE
    assert theme.QQ_STATUS_STYLE == theme.WECHAT_STATUS_STYLE

    assert isinstance(workspace._progress_track, ConnectionProgressTrack)
    assert workspace._progress_track.STAGES == module._QQ_CONNECT_STAGES
    assert workspace._progress_track.accessibleName() == "连接进度"


def test_qq_current_action_height_follows_the_font_ink_not_the_line_box() -> None:
    """A font may declare a descent its glyphs do not obey - the Latin "Q" tail
    is the usual offender - and a box sized from font-size alone then cuts it.
    The reserve has to come from the ink the font really draws, never from a
    hand-tuned pixel offset."""
    from PySide6.QtCore import QRectF
    from qq_chat_analyzer.gui.qq_workspace import _current_action_height

    class _TightDescent:
        """26px font whose "Q" ink reaches 4px below its declared descent."""

        @staticmethod
        def ascent():
            return 26.0

        @staticmethod
        def descent():
            return 0.0

        @staticmethod
        def leading():
            return 0.0

        @staticmethod
        def tightBoundingRect(_text):
            return QRectF(0.0, -26.0, 22.0, 30.0)

    class _ObeyingDescent:
        """Same ink, but the declared descent already covers it."""

        @staticmethod
        def ascent():
            return 26.0

        @staticmethod
        def descent():
            return 6.0

        @staticmethod
        def leading():
            return 0.0

        @staticmethod
        def tightBoundingRect(_text):
            return QRectF(0.0, -26.0, 22.0, 30.0)

    assert _TightDescent.ascent() + _TightDescent.descent() == 26.0
    assert _current_action_height(_TightDescent(), "正在连接 QQ") == 30
    assert _current_action_height(_ObeyingDescent(), "正在连接 QQ") == 32


def test_qq_connection_stage_copy_stays_short(qt_app) -> None:
    """One short action and one short note per stage, never a paragraph."""
    module = importlib.import_module("qq_chat_analyzer.gui.qq_workspace")

    assert set(module._QQ_STAGE_COPY) == {0, 1, 2, 3}
    for stage, (action, note) in module._QQ_STAGE_COPY.items():
        assert action and "\n" not in action and len(action) <= 12
        assert note and "\n" not in note and len(note) <= 60
    assert len(module._QQ_IDLE_NOTE) <= 60


@pytest.mark.parametrize("size", [(1200, 760), (800, 600)])
@pytest.mark.parametrize("state", ["idle", "starting", "scanning", "error"])
def test_qq_connection_journey_fits_window(
    qt_app, sources, tmp_path: Path, size, state
) -> None:
    """The trail, the QR and the actions must stay inside the QQ page."""
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QFontMetricsF
    from qq_chat_analyzer.gui.main_window import QQ_WORKSPACE_INDEX
    from qq_chat_analyzer.gui.qq_workspace import _current_action_height
    from qq_chat_analyzer.gui.theme import BASE_QSS

    qr_path = tmp_path / "fictional-qq-qr.png"
    _write_qrcode_png(qr_path)
    facade = _GatedQRFacade(
        _qq_snapshot("waiting_auth"),
        _qq_snapshot("waiting_auth"),
        sources=sources,
    )
    facade.qr_ready = True
    window = _main_window(qt_app, facade, executor=_IndependentDeferredExecutor())
    window.setStyleSheet(BASE_QSS)
    window.stack.setCurrentIndex(QQ_WORKSPACE_INDEX)
    page = window.qq_workspace
    facade.qr_path = qr_path

    if state == "idle":
        page._show_qq_status(_qq_snapshot("disconnected"), load_sessions_on_ready=False)
    elif state == "starting":
        page._show_qq_status(_qq_snapshot("starting"), load_sessions_on_ready=False)
    elif state == "scanning":
        page._show_qq_status(_qq_snapshot("waiting_auth"), load_sessions_on_ready=False)
    else:
        page._show_qq_status(_qq_snapshot("error"), load_sessions_on_ready=False)

    window.resize(*size)
    window.show()
    _drain(window)
    try:
        assert window.size().toTuple() == size
        labels = (page._status_label, page._qq_guide_label, page._qq_login_guide_label)
        for widget in (
            *labels,
            page._qq_qrcode_label,
            page._qq_connect_button,
            page._qq_disconnect_button,
        ):
            if widget.isVisibleTo(page):
                bounds = QRect(widget.mapTo(page, QPoint()), widget.size())
                assert page.rect().contains(bounds), widget.text()
                if widget in labels:
                    assert widget.height() >= widget.heightForWidth(widget.width())
        if page._progress_track.isVisibleTo(page):
            track_bounds = QRect(
                page._progress_track.mapTo(page, QPoint()),
                page._progress_track.size(),
            )
            assert page.rect().contains(track_bounds)
        if page._qq_guide_label.isVisibleTo(page):
            assert (
                page._qq_guide_label.font().pixelSize()
                > page._qq_login_guide_label.font().pixelSize()
            )
            metrics = QFontMetricsF(page._qq_guide_label.font())
            assert page._qq_guide_label.height() >= _current_action_height(
                metrics,
                page._qq_guide_label.text(),
            )
            assert (
                page._qq_guide_label.minimumHeight()
                >= _current_action_height(metrics, page._qq_guide_label.text())
            )
        assert page._qq_connect_button.width() < page.width() / 2
    finally:
        window.hide()


def test_wechat_workspace_shows_connect_button_when_disconnected(
    qt_app, sources
) -> None:
    """WeChat disconnected status shows the connect action and no sessions."""
    from qq_chat_analyzer.gui.main_window import WECHAT_WORKSPACE_INDEX
    module = _facade_module()
    status = module.WeChatConnectionStatus(
        available=False, data_found=False, db_key_available=False,
        runtime_available=False, message="微信环境未配置。", action_hint="",
    )
    facade = StubFacade(
        sources=sources,
        connection_status=status,
        sessions=[_session(module.ChatSource.WECHAT, "20001", "测试群")],
    )
    window = _main_window(qt_app, facade)
    window.navigate_to_wechat()
    _drain(window)

    assert window.stack.currentIndex() == WECHAT_WORKSPACE_INDEX
    assert window.wechat_workspace._wechat_connect_button.isVisibleTo(window) is True
    assert window.wechat_workspace._wechat_connect_button.isEnabled()
    assert window.wechat_workspace.session_panel._sessions_ready is False


def test_qq_workspace_disconnect_returns_to_disconnected(
    qt_app, sources
) -> None:
    """Connected QQ workspace offers logout and returns to disconnected."""
    from qq_chat_analyzer.gui.main_window import QQ_WORKSPACE_INDEX
    module = _facade_module()
    connected = module.QQConnectionStatus(
        available=True,
        runtime_running=True,
        qq_online=True,
        version="4.1.0",
        message="QQ 已连接。",
        action_hint="",
    )
    facade = StubFacade(sources=sources, connection_status=connected)
    window = _main_window(qt_app, facade)
    window.navigate_to_qq()
    _drain(window)

    assert window.stack.currentIndex() == QQ_WORKSPACE_INDEX
    assert window.qq_workspace._qq_disconnect_button.isVisibleTo(window) is True
    assert window.qq_workspace._qq_connect_button.isVisibleTo(window) is False

    window.qq_workspace._qq_disconnect_button.click()
    _drain(window)

    assert facade.disconnect_qq_calls == [1]
    assert window.qq_workspace._qq_connect_button.isVisibleTo(window) is True
    assert window.qq_workspace._qq_disconnect_button.isVisibleTo(window) is False


def test_wechat_workspace_disconnect_returns_to_disconnected(
    qt_app, sources
) -> None:
    """Connected WeChat workspace offers logout and returns to disconnected."""
    from qq_chat_analyzer.gui.main_window import WECHAT_WORKSPACE_INDEX
    module = _facade_module()
    connected = module.WeChatConnectionStatus(
        available=True,
        data_found=True,
        db_key_available=True,
        runtime_available=True,
        message="微信已连接。",
        action_hint="",
    )
    facade = StubFacade(sources=sources, connection_status=connected)
    window = _main_window(qt_app, facade)
    window.navigate_to_wechat()
    _drain(window)

    assert window.stack.currentIndex() == WECHAT_WORKSPACE_INDEX
    assert window.wechat_workspace._wechat_disconnect_button.isVisibleTo(window) is True
    assert window.wechat_workspace._wechat_connect_button.isVisibleTo(window) is False

    window.wechat_workspace._wechat_disconnect_button.click()
    _drain(window)

    assert facade.disconnect_wechat_calls == [1]
    assert window.wechat_workspace._wechat_connect_button.isVisibleTo(window) is True
    assert window.wechat_workspace._wechat_disconnect_button.isVisibleTo(window) is False


def test_qq_connection_does_not_crash_without_explicit_executor(
    qt_app, sources
) -> None:
    """QQ connect works when MainWindow was created without an executor."""
    module = _facade_module()
    status = module.QQConnectionStatus(
        available=False, runtime_running=False, qq_online=False,
        version="", message="QQ 尚未连接。", action_hint="",
    )
    facade = StubFacade(sources=sources, connection_status=status)
    window = _main_window_no_executor(qt_app, facade)
    window.navigate_to_qq()
    _drain(window)

    window.qq_workspace._qq_connect_button.click()
    _drain(window)

    assert window.qq_workspace._connection_task is not None


def test_wechat_connection_does_not_crash_without_explicit_executor(
    qt_app, sources
) -> None:
    """WeChat connect opens setup when MainWindow has no executor."""
    module = _facade_module()
    status = module.WeChatConnectionStatus(
        available=False, data_found=False, db_key_available=False,
        runtime_available=False, message="微信尚未连接。", action_hint="",
    )
    facade = StubFacade(sources=sources, connection_status=status)
    window = _main_window_no_executor(qt_app, facade)
    window.navigate_to_wechat()
    _drain(window)

    window.wechat_workspace._wechat_connect_button.click()
    _drain(window)

    assert hasattr(window.wechat_workspace, "_wechat_setup_dialog")


def test_session_panel_populates_sessions_without_crash(qt_app, sources) -> None:
    """The shared panel renders sessions and becomes ready."""
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel
    module = _facade_module()
    facade = StubFacade(sources=sources)
    panel = SessionAnalysisPanel()
    panel.configure(facade, module.ChatSource.WECHAT)
    sessions = [
        _session(module.ChatSource.WECHAT, "wx1", "测试会话1", 10),
        _session(module.ChatSource.WECHAT, "wx2", "测试会话2", 5),
    ]
    panel.populate_sessions(sessions)

    assert panel._session_list.count() == 2
    assert panel._sessions_ready is True


def test_session_panel_empty_source_shows_real_empty_state(
    qt_app, sources
) -> None:
    """An empty session list renders a non-interactive empty state."""
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel
    module = _facade_module()
    panel = SessionAnalysisPanel()
    panel.configure(StubFacade(sources=sources), module.ChatSource.WECHAT)

    panel.populate_sessions([])

    assert panel._sessions_ready is True
    assert panel._session_list.count() == 0
    from PySide6.QtWidgets import QLabel
    title = panel.findChild(QLabel, "sessionEmptyTitle")
    detail = panel.findChild(QLabel, "sessionEmptyDetail")
    panel.resize(800, 600)
    panel.show()
    qt_app.processEvents()
    assert title is not None and title.isVisible() and "没有找到" in title.text()
    assert detail is not None and detail.isVisible() and detail.text()
    assert panel._session_box.isVisible()
    assert panel._analyze_button.isEnabled() is False
    panel.close()


def test_session_panel_disables_sessions_without_messages(
    qt_app, sources
) -> None:
    """Sessions without analyzable messages stay disabled."""
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel
    module = _facade_module()
    sessions = [
        module.SessionInfo(
            source=module.ChatSource.WECHAT,
            session_id="wx1",
            display_name="有消息",
            message_count=5,
        ),
        module.SessionInfo(
            source=module.ChatSource.WECHAT,
            session_id="wx2",
            display_name="无消息",
            message_count=0,
            message_available=False,
            unavailable_reason="该会话没有可分析消息",
        ),
    ]
    panel = SessionAnalysisPanel()
    panel.configure(StubFacade(sources=sources), module.ChatSource.WECHAT)
    panel.populate_sessions(sessions)

    panel._session_list.setCurrentRow(1)
    assert panel._analyze_button.isEnabled() is False
    panel._session_list.setCurrentRow(0)
    assert panel._analyze_button.isEnabled() is True


def test_wechat_session_panel_selection_requests_message_range(
    qt_app,
    sources,
) -> None:
    """WeChat panel selection fetches the real message range through the facade."""
    from datetime import datetime

    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel
    module = _facade_module()
    session_id = "wx_time_range"
    start = 1704067200
    end = 1704153600
    facade = StubFacade(
        sources=sources,
        sessions=[_session(module.ChatSource.WECHAT, session_id, "测试会话", 10)],
        message_range=(start, end),
    )
    panel = SessionAnalysisPanel()
    panel.configure(facade, module.ChatSource.WECHAT, executor=_inline_executor())
    panel.populate_sessions(facade._sessions)
    panel._session_list.setCurrentRow(0)
    _drain(panel)
    panel._scope_custom.setChecked(True)

    assert facade.get_session_message_range_calls == [
        (module.ChatSource.WECHAT, session_id)
    ]
    assert panel._start_date.date().toPython() == datetime.fromtimestamp(
        start
    ).date()
    assert panel._end_date.date().toPython() == datetime.fromtimestamp(end).date()


def test_qq_session_panel_selection_skips_range_probe(qt_app) -> None:
    """QQ panel selection must not probe the range and must not start a worker."""
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel
    module = _facade_module()
    facade = StubFacade(
        sources=_wechat_available_sources(),
        sessions=[_session(module.ChatSource.QQ, "10002", "Fictional Group", 10)],
        message_range=(1704067200, 1704153600),
    )
    panel = SessionAnalysisPanel()
    panel.configure(facade, module.ChatSource.QQ, executor=_inline_executor())
    panel.populate_sessions(facade._sessions)
    panel._session_list.setCurrentRow(0)
    _drain(panel)

    assert facade.get_session_message_range_calls == []
    assert panel._message_range is None


def test_session_panel_scope_blocks_accept_clicks_across_the_whole_option(qt_app, sources):
    """The full option surface selects a scope, including outside its text."""
    from PySide6.QtCore import QPoint
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel

    module = _facade_module()
    panel = SessionAnalysisPanel()
    panel.configure(StubFacade(sources=sources), module.ChatSource.QQ)
    panel.populate_sessions([_session(module.ChatSource.QQ, "fictional", "测试会话", 10)])
    panel.resize(780, 560)
    panel.show()
    qt_app.processEvents()
    for control, mode in (
        (panel._scope_custom, module.AnalysisScopeMode.CUSTOM),
        (panel._scope_last_year, module.AnalysisScopeMode.LAST_YEAR),
        (panel._scope_last_six_months, module.AnalysisScopeMode.LAST_SIX_MONTHS),
        (panel._scope_all, module.AnalysisScopeMode.ALL),
    ):
        QTest.mouseClick(control, Qt.MouseButton.LeftButton,
                         pos=QPoint(control.width() - 5, control.height() - 5))
        assert panel.build_config().scope_mode is mode
        assert panel._custom_range_widget.isVisible() is (mode is module.AnalysisScopeMode.CUSTOM)
        assert panel._analyze_button.isEnabled() is False
    panel.close()


@pytest.mark.parametrize("source", ["QQ", "WECHAT"])
def test_session_workspace_ready_header_is_one_compact_row(qt_app, sources, source):
    """A ready connection leaves the vertical space to the session list."""
    module = _facade_module()
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    from qq_chat_analyzer.gui.wechat_workspace import WeChatWorkspace

    workspace_type = QQWorkspace if source == "QQ" else WeChatWorkspace
    workspace = workspace_type(StubFacade(sources=sources), executor=_inline_executor())
    workspace.resize(900, 700)
    workspace._handle_sessions_loaded([
        _session(getattr(module.ChatSource, source), "fictional", "测试会话", 10)
    ])
    workspace._status_label.show()
    button = getattr(workspace, f"_{source.lower()}_disconnect_button")
    button.show()
    workspace.show()
    qt_app.processEvents()
    status_y = workspace._status_label.mapTo(workspace, workspace._status_label.rect().center()).y()
    button_y = button.mapTo(workspace, button.rect().center()).y()
    assert abs(status_y - button_y) <= 2
    assert workspace._connection_surface.height() <= 90
    workspace.close()


def test_session_panel_selected_name_tracks_selection_and_search(qt_app, sources):
    """Configuration names the selected chat and clears when search removes it."""
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel

    module = _facade_module()
    panel = SessionAnalysisPanel()
    panel.configure(StubFacade(sources=sources), module.ChatSource.QQ)
    panel.populate_sessions([
        _session(module.ChatSource.QQ, "fictional1", "周末读书会", 10),
        _session(module.ChatSource.QQ, "fictional2", "旧日朋友", 5),
    ])
    panel._session_list.setCurrentRow(0)
    # Assert the user-facing label, not the facade's identity fields.
    from PySide6.QtWidgets import QLabel
    label = panel.findChild(QLabel, "selectedSessionName")
    assert label is not None
    assert label.text() == "周末读书会"
    panel._session_list.setCurrentRow(1)
    assert label.text() == "旧日朋友"
    panel._session_search.setText("读书")
    assert label.text() == "尚未选择会话"
    assert not panel._analyze_button.isEnabled()


@pytest.mark.parametrize("size", [(1500, 850), (800, 600), (640, 560), (500, 560)])
def test_session_panel_layout_keeps_custom_controls_reachable(qt_app, sources, size):
    """Wide pages stay bounded; smaller pages keep selection and CTA reachable."""
    from PySide6.QtCore import QPoint
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel

    module = _facade_module()
    panel = SessionAnalysisPanel()
    panel.configure(StubFacade(sources=sources), module.ChatSource.QQ)
    panel.populate_sessions([
        _session(module.ChatSource.QQ, f"fictional{i}", "很长的虚构会话名称" * 15, 10)
        for i in range(30)
    ])
    panel.resize(*size)
    panel.show()
    panel._session_list.setCurrentRow(0)
    panel._scope_custom.setChecked(True)
    qt_app.processEvents()
    assert panel.size().toTuple() == size
    assert panel._session_list.horizontalScrollBar().maximum() == 0
    assert 50 <= panel._session_list.visualItemRect(panel._session_list.item(0)).height() <= 56
    button = panel._analyze_button
    button_rect = button.rect().translated(button.mapTo(panel, QPoint(0, 0)))
    assert panel.rect().contains(button_rect)
    assert button.isVisible() and button.isEnabled()
    assert panel._selected_session_label.toolTip() == "很长的虚构会话名称" * 15
    assert "…" in panel._selected_session_label.text()
    viewport = panel._configuration_scroll.viewport()
    for control in (panel._scope_all, panel._scope_custom, panel._start_date, panel._end_date):
        panel._configuration_scroll.ensureWidgetVisible(control)
        qt_app.processEvents()
        rect = control.rect().translated(control.mapTo(viewport, QPoint(0, 0)))
        assert viewport.rect().contains(rect)
    if size[0] == 1500:
        list_rect = panel._session_list.rect().translated(panel._session_list.mapTo(panel, QPoint(0, 0)))
        range_rect = panel._analysis_range_box.rect().translated(panel._analysis_range_box.mapTo(panel, QPoint(0, 0)))
        assert list_rect.right() < range_rect.left()
        assert list_rect.left() >= 150
        assert range_rect.right() <= 1350
    panel.close()


@pytest.mark.parametrize("count", [None, 42])
def test_session_panel_list_tooltip_keeps_complete_name(custom_date_panel, count):
    panel = custom_date_panel()
    module = _facade_module()
    name = "虚构的很长会话名称" * 20
    panel.populate_sessions([_session(module.ChatSource.QQ, "fiction-long", name, count)])
    item = panel._session_list.item(0)
    assert name in item.toolTip()
    if count is not None:
        assert "42" in item.toolTip()
    assert item.text() == name


def test_session_panel_selection_echo_retargets_without_moving_rows(qt_app, custom_date_panel):
    from PySide6.QtCore import QVariantAnimation
    from qq_chat_analyzer.gui.theme import HOME_COLOR_ACCENT

    panel = custom_date_panel()
    view = panel._session_list
    animation = view.findChild(QVariantAnimation, "sessionSelectionEcho")
    assert animation is not None, "选中标记需要一次性的展开反馈"
    assert 360 <= animation.duration() <= 440
    rects = [view.visualItemRect(view.item(i)) for i in range(2)]

    def marker_pixels(row):
        rect = view.visualItemRect(view.item(row))
        pixels = view.viewport().grab().toImage()
        ratio = pixels.devicePixelRatio()
        return sum(pixels.pixelColor(round((rect.left() + 1) * ratio), round(y * ratio)).name() == HOME_COLOR_ACCENT
                   for y in range(rect.top() + 1, rect.bottom()))

    animation.setCurrentTime(0)
    initial = marker_pixels(0)
    animation.setCurrentTime(animation.duration() // 2)
    middle = marker_pixels(0)
    animation.setCurrentTime(animation.duration())
    complete = marker_pixels(0)
    assert initial == middle == complete and complete > 0
    # Rapid keyboard changes must immediately clear the old row's marker.
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Down)
    animation.setCurrentTime(animation.duration() // 2)
    assert marker_pixels(0) == 0
    assert marker_pixels(1) > 0
    animation.setCurrentTime(animation.duration())
    pixels = view.viewport().grab().toImage()
    ratio = pixels.devicePixelRatio()
    previous_row_edge = pixels.pixelColor(round(ratio), round((rects[1].top() - 1) * ratio))
    assert previous_row_edge.name() != HOME_COLOR_ACCENT
    QTest.keyClick(view, Qt.Key.Key_Up)
    animation.setCurrentTime(animation.duration())
    assert marker_pixels(1) == 0
    assert marker_pixels(0) > 0
    assert [view.visualItemRect(view.item(i)) for i in range(2)] == rects
    # Refresh clears selection; old animation frames cannot mark replacement rows.
    panel._session_search.setText("会话 B")
    qt_app.processEvents()
    assert not view.selectedItems()
    assert animation.state() == QVariantAnimation.State.Stopped
    assert marker_pixels(0) == 0
    assert not panel._analyze_button.isEnabled()


def _session_echo_frame(panel, row, milliseconds):
    """Capture the real viewport at a deterministic time, without advancing timers."""
    animation = panel._selection_delegate._animation
    animation.setCurrentTime(milliseconds)
    return panel._session_list.viewport().grab().toImage().copy()


def _session_echo_samples(panel, image, row):
    rect = panel._session_list.visualItemRect(panel._session_list.item(row))
    ratio = image.devicePixelRatio()
    # Below the text, above the separator: measure painted background only.
    return [image.pixelColor(round((rect.left() + rect.width() * x) * ratio),
                             round((rect.bottom() - 9) * ratio))
            for x in (0.15, 0.50, 0.85)]


def test_session_piano_echo_light_press_is_visible_across_the_selected_row(custom_date_panel):
    panel = custom_date_panel()
    start = _session_echo_samples(panel, _session_echo_frame(panel, 0, 0), 0)
    pressed = _session_echo_samples(panel, _session_echo_frame(panel, 0, 45), 0)
    assert all(s.red() - p.red() >= 4 for s, p in zip(start, pressed)), "轻按需要可见的整行明暗变化"


def test_session_piano_echo_releases_into_a_visible_travelling_front(custom_date_panel):
    panel = custom_date_panel()
    animation = panel._selection_delegate._animation
    start_frame = _session_echo_frame(panel, 0, 0)
    start = _session_echo_samples(panel, start_frame, 0)
    peaks = []
    rect = panel._session_list.visualItemRect(panel._session_list.item(0))
    for ms in (150, 200, 250):
        frame = _session_echo_frame(panel, 0, ms)
        ratio = frame.devicePixelRatio()
        y = round((rect.bottom() - 9) * ratio)
        # A substantial light crest, not just a one-channel pixel difference.
        profile = [frame.pixelColor(round((rect.left() + rect.width() * x / 100) * ratio), y).red()
                   - start_frame.pixelColor(round((rect.left() + rect.width() * x / 100) * ratio), y).red()
                   for x in range(5, 96)]
        assert max(profile) >= 14, "正常速度可见的浅色波峰需要足够对比"
        peaks.append((profile.index(max(profile)) + 5) / 100)
    assert 0.05 <= peaks[0] < 0.30
    assert 0.40 <= peaks[1] <= 0.60
    assert 0.70 < peaks[2] <= 0.95
    complete_frame = _session_echo_frame(panel, 0, animation.duration())
    complete = _session_echo_samples(panel, complete_frame, 0)
    assert start == complete
    assert animation.state() == animation.State.Stopped
    assert _session_echo_frame(panel, 0, animation.duration()) == complete_frame
    panel.close()


def test_session_piano_echo_tail_fades_without_changing_foreground_or_other_rows(custom_date_panel):
    from qq_chat_analyzer.gui.theme import HOME_COLOR_TEXT
    panel = custom_date_panel()
    view = panel._session_list
    view.setFocus()
    frames = [_session_echo_frame(panel, 0, ms) for ms in (0, 45, 200, 300, 360, 400)]
    rect = view.visualItemRect(view.item(0))
    ratio = frames[0].devicePixelRatio()
    # Compare the whole surrounding viewport to catch clipping regressions.
    below = view.viewport().rect().adjusted(0, rect.bottom() + 1, 0, 0)
    from PySide6.QtCore import QRect
    pixels_below = QRect(round(below.x() * ratio), round(below.y() * ratio),
                         round(below.width() * ratio), round(below.height() * ratio))
    assert all(frame.copy(pixels_below) == frames[0].copy(pixels_below) for frame in frames)
    # Solid ink must stay put. Antialiased edges blend with the animated paper,
    # so a darkness threshold would wrongly include partially covered pixels.
    def ink_positions(frame):
        return {(x, y) for y in range(round(rect.top() * ratio), round(rect.bottom() * ratio))
                for x in range(round((rect.left() + 16) * ratio), round(rect.right() * ratio))
                if frame.pixelColor(x, y).name() == HOME_COLOR_TEXT}
    ink = ink_positions(frames[0])
    assert ink
    assert all(ink_positions(frame) == ink for frame in frames)
    def difference(frame):
        return sum(abs(a.red() - b.red()) for a, b in zip(
            _session_echo_samples(panel, frame, 0), _session_echo_samples(panel, frames[0], 0)))
    assert difference(frames[3]) > difference(frames[4]) > difference(frames[5]) == 0
    assert frames[0] == frames[-1]


@pytest.mark.parametrize("action", ["search", "sort", "clear"])
def test_session_piano_echo_view_changes_cancel_without_restarting_stale_frames(custom_date_panel, action):
    panel = custom_date_panel()
    view = panel._session_list
    animation = panel._selection_delegate._animation
    animation.setCurrentTime(45)
    if action == "search":
        panel._session_search.setText("会话 B")
    elif action == "sort":
        panel._session_sort.setCurrentIndex(_sort_index(panel, "message_count"))
    else:
        view.clearSelection()
    assert animation.state() == animation.State.Stopped
    assert not panel._selection_delegate._current.isValid()
    clean = view.viewport().grab().toImage().copy()
    animation.setCurrentTime(200)
    assert view.viewport().grab().toImage() == clean
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     pos=view.visualItemRect(view.item(0)).center())
    assert view.selectedItems() == [view.item(0)]
    assert animation.state() == animation.State.Running
    assert animation.currentTime() < 70
    from PySide6.QtCore import QVariantAnimation
    assert view.findChildren(QVariantAnimation) == [animation]


def test_session_piano_echo_rapid_keyboard_switch_does_not_leave_old_row_tint(qt_app, custom_date_panel):
    panel = custom_date_panel()
    view = panel._session_list
    view.setFocus()
    # Save unselected rendering of row 0, with the same keyboard focus state.
    view.setCurrentRow(1)
    animation = panel._selection_delegate._animation
    animation.setCurrentTime(animation.duration())
    unselected = _session_echo_samples(panel, view.viewport().grab().toImage(), 0)
    for _ in range(3):
        QTest.keyClick(view, Qt.Key.Key_Up)
        tinted = _session_echo_samples(panel, _session_echo_frame(panel, 0, 200), 0)
        QTest.keyClick(view, Qt.Key.Key_Down)
        new_frame = _session_echo_frame(panel, 1, 200)
        assert _session_echo_samples(panel, new_frame, 0) == unselected
        assert tinted[1] != _session_echo_samples(panel, _session_echo_frame(panel, 1, animation.duration()), 1)[1]
        assert _session_echo_samples(panel, new_frame, 1)[1] != tinted[2]
    panel.close()


def test_session_piano_echo_filter_cancels_timer_and_cannot_tint_replacement_row(qt_app, custom_date_panel):
    panel = custom_date_panel()
    animation = panel._selection_delegate._animation
    before = _session_echo_samples(panel, _session_echo_frame(panel, 0, 200), 0)
    static = _session_echo_samples(panel, _session_echo_frame(panel, 0, animation.duration()), 0)
    assert before != static, "过滤前应有正在运行的背景扩散"
    panel._session_list.setCurrentRow(1)
    panel._selection_delegate._animation.setCurrentTime(90)
    panel._session_search.setText("会话 A")
    qt_app.processEvents()
    assert panel._selection_delegate._animation.state() == panel._selection_delegate._animation.State.Stopped
    assert not panel._session_list.selectedItems()
    replacement = panel._session_list.viewport().grab().toImage().copy()
    panel._selection_delegate._animation.setCurrentTime(150)
    assert panel._session_list.viewport().grab().toImage() == replacement
    panel.close()


def test_session_piano_echo_scroll_and_resize_use_current_row_geometry(qt_app, custom_date_panel):
    panel = custom_date_panel()
    module = _facade_module()
    panel.populate_sessions([_session(module.ChatSource.QQ, f"fiction-{i}", f"虚构会话 {i:02}", 1)
                             for i in range(40)])
    view = panel._session_list
    view.setCurrentRow(0)
    animation = panel._selection_delegate._animation
    active = _session_echo_frame(panel, 0, 200)
    assert _session_echo_samples(panel, active, 0) != _session_echo_samples(panel, _session_echo_frame(panel, 0, animation.duration()), 0)
    view.setCurrentRow(1)
    animation.pause()
    animation.setCurrentTime(200)
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
    qt_app.processEvents()
    scrolled = view.viewport().grab().toImage().copy()
    animation.setCurrentTime(animation.duration())
    assert view.viewport().grab().toImage() == scrolled
    view.scrollToItem(view.item(1))
    view.setCurrentRow(0)
    animation.pause()
    animation.setCurrentTime(200)
    panel.resize(1150, 700)
    qt_app.processEvents()
    view.scrollToItem(view.item(0))
    resized = _session_echo_samples(panel, view.viewport().grab().toImage(), 0)
    restored = _session_echo_samples(panel, _session_echo_frame(panel, 0, animation.duration()), 0)
    assert resized[1] != restored[1]
    panel.close()


@pytest.mark.parametrize("source_name,source_text", [("QQ", "QQ"), ("WECHAT", "微信")])
@pytest.mark.parametrize("count,number_text", [(None, None), (0, "0 条消息"), (1234, "1,234 条消息")])
def test_session_panel_summary_tracks_selection_without_extra_requests(
    custom_date_panel, source_name, source_text, count, number_text,
):
    from PySide6.QtWidgets import QLabel

    panel = custom_date_panel(source_name)
    module = _facade_module()
    source = getattr(module.ChatSource, source_name)
    panel.populate_sessions([
        _session(source, "fiction-A", "虚构会话 A", count),
        _session(source, "fiction-B", "虚构会话 B", 9),
    ])
    panel._session_list.setCurrentRow(0)
    meta = panel.findChild(QLabel, "selectedSessionMeta")
    assert meta is not None, "右侧应展示已提供的会话信息"
    assert meta.isVisible() and source_text in meta.text()
    if number_text:
        assert number_text in meta.text()
    else:
        assert "条消息" not in meta.text()
    requests = list(panel._facade.get_session_message_range_calls)
    panel._start_date.setDate(QDate(2024, 1, 1))
    panel._end_date.setDate(QDate(2024, 2, 1))
    panel._scope_all.setChecked(True)
    assert panel._facade.get_session_message_range_calls == requests
    assert not panel._facade.list_sessions_calls
    panel._session_list.setCurrentRow(1)
    assert panel._selected_session_label.text() == "虚构会话 B"
    assert "9 条消息" in meta.text()
    panel._session_search.setText("会话 A")
    assert not meta.isVisible() and meta.text() == ""
    assert not panel._analyze_button.isEnabled()


def test_session_panel_report_action_keeps_bottom_anchor(qt_app, custom_date_panel):
    from PySide6.QtCore import QPoint

    panel = custom_date_panel()
    assert panel._analyze_button.text() == "生成回顾报告"
    for mode in (panel._scope_all, panel._scope_custom):
        mode.setChecked(True)
        qt_app.processEvents()
        button = panel._analyze_button
        bottom = button.mapTo(panel._configuration_panel, QPoint(0, button.height())).y()
        assert panel._configuration_panel.height() - bottom <= 1
        settings = panel._configuration_scroll.widget()
        name = panel._selected_session_label
        name_bottom = name.mapTo(settings, QPoint(0, name.height())).y()
        range_top = panel._analysis_range_box.mapTo(settings, QPoint(0, 0)).y()
        assert name_bottom < range_top


def test_session_panel_empty_search_has_independent_copy_and_no_restored_selection(
    qt_app, custom_date_panel,
):
    from PySide6.QtWidgets import QLabel

    panel = custom_date_panel()
    hint = panel.findChild(QLabel, "sessionSelectionHint")
    assert hint is not None and hint.isHidden()
    panel._session_search.setText("不存在的虚构会话")
    qt_app.processEvents()
    assert panel._session_list.count() == 0
    assert panel.selected_session_id() is None
    title = panel.findChild(QLabel, "sessionEmptyTitle")
    detail = panel.findChild(QLabel, "sessionEmptyDetail")
    assert title is not None and title.isVisible() and title.text() == "没有匹配的会话"
    assert detail is not None and detail.isVisible()
    assert "清空搜索" in detail.text()
    assert hint.isVisible() and hint.text() == "选择一段聊天，看看时间留下了什么。"
    assert panel._selected_session_meta.isHidden()
    assert not panel._analyze_button.isEnabled()
    panel._session_search.clear()
    qt_app.processEvents()
    assert panel._session_list.isVisible() and panel._session_list.count() == 2
    assert title.isHidden() or not title.isVisible()
    assert not panel._session_list.selectedItems()
    assert panel.selected_session_id() is None
    assert hint.isVisible() and not panel._analyze_button.isEnabled()
    panel._session_list.setCurrentRow(1)
    assert hint.isHidden() and panel._analyze_button.isEnabled()
    assert panel._selected_session_label.text() == "虚构会话 B"


def test_session_panel_cleared_selection_cannot_analyze(custom_date_panel):
    panel = custom_date_panel()
    panel._session_list.clearSelection()
    # Qt retains a current item after deselection; it is no longer a selection.
    assert panel._session_list.currentItem() is not None
    assert panel.selected_session_id() is None
    assert not panel._analyze_button.isEnabled()


def test_session_panel_unselected_guide_survives_resize_and_blocks_analysis(
    qt_app, custom_date_panel,
):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QLabel

    panel = custom_date_panel()
    panel._session_list.clearSelection()
    hint = panel.findChild(QLabel, "sessionSelectionHint")
    assert hint is not None and hint.isVisible()
    assert not panel._selected_session_meta.isVisible()
    assert not panel._analyze_button.isEnabled()
    started = []
    panel.analysis_started.connect(lambda: started.append(True))
    panel.start_analysis()
    _drain(panel)
    assert started == []
    panel.resize(500, 560)
    qt_app.processEvents()
    panel._configuration_scroll.ensureWidgetVisible(hint)
    qt_app.processEvents()
    viewport = panel._configuration_scroll.viewport()
    rect = hint.rect().translated(hint.mapTo(viewport, QPoint(0, 0)))
    assert viewport.rect().contains(rect)


@pytest.fixture
def session_layout_window(qt_app, sources):
    """Real window states with a controlled logical size on Qt offscreen."""
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel

    windows = []

    def make(size, maximized=False):
        module = _facade_module()
        window = QWidget()
        # Prevent the offscreen platform's 800px virtual screen from replacing
        # the requested size; Qt still sends real window-state and resize events.
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        layout = QVBoxLayout(window)
        layout.setContentsMargins(0, 0, 0, 0)
        panel = SessionAnalysisPanel(window)
        panel.configure(StubFacade(sources=sources), module.ChatSource.QQ,
                        executor=_inline_executor())
        panel.populate_sessions([
            _session(module.ChatSource.QQ, f"fiction-{i}", "虚构会话名称" * 15, 10)
            for i in range(30)
        ])
        layout.addWidget(panel)
        panel._session_list.setCurrentRow(0)
        panel._scope_custom.setChecked(True)
        panel._start_date.setDate(QDate(2024, 1, 31))
        panel._end_date.setDate(QDate(2024, 3, 1))
        window.resize(*size)
        if maximized:
            window.setWindowState(Qt.WindowState.WindowMaximized)
        window.show()
        qt_app.processEvents()
        windows.append(window)
        return window, panel

    yield make
    for window in windows:
        window.close()
        window.deleteLater()
    qt_app.processEvents()


@pytest.mark.parametrize("size", [(800, 600), (1200, 760), (1600, 900), (1920, 1080)])
def test_session_panel_maximized_space_goes_to_list_without_scaling_controls(
    qt_app, session_layout_window, size,
):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QPushButton

    window, panel = session_layout_window(size)
    content = panel._workspace_content
    normal_width = content.width()
    normal_list_width = panel._session_box.width()
    normal_configuration_width = panel._configuration_panel.width()
    assert normal_width <= 1120
    assert abs(normal_configuration_width / (normal_width - 28) - 0.37) < 0.03
    font = panel._session_list.font()
    button_height = panel._analyze_button.height()
    config = panel.build_config()
    window.setWindowState(Qt.WindowState.WindowMaximized)
    qt_app.processEvents()
    assert window.isMaximized() and window.size().toTuple() == size
    assert panel.build_config() == config
    if size[0] >= 1600:
        assert 1400 <= content.width() <= 1520
        growth = content.width() - normal_width
        assert panel._session_box.width() - normal_list_width >= growth - 8
        assert abs(panel._configuration_panel.width() - normal_configuration_width) <= 8
    assert 240 <= panel._configuration_panel.width() <= 420
    left_gutter = content.mapTo(panel, QPoint(0, 0)).x()
    right_gutter = panel.width() - left_gutter - content.width()
    assert abs(left_gutter - right_gutter) <= 1
    assert left_gutter >= 24
    assert panel._session_list.font() == font
    assert panel._analyze_button.height() == button_height
    assert 50 <= panel._session_list.visualItemRect(panel._session_list.item(0)).height() <= 56
    assert panel._session_list.horizontalScrollBar().maximum() == 0
    viewport = panel._configuration_scroll.viewport()
    controls = [panel._start_date, panel._end_date, panel._date_adjust_target,
                panel._date_adjust_unit, *panel._date_adjust_tools.findChildren(QPushButton)]
    # Error feedback must remain reachable as well as the date adjustment tools.
    panel._start_date.setDate(QDate(2024, 3, 2))
    controls.append(panel._date_range_error)
    for control in controls:
        panel._configuration_scroll.ensureWidgetVisible(control)
        qt_app.processEvents()
        rect = control.rect().translated(control.mapTo(viewport, QPoint(0, 0)))
        assert control.isVisible() and viewport.rect().contains(rect)
    button_rect = panel._analyze_button.rect().translated(
        panel._analyze_button.mapTo(panel, QPoint(0, 0)))
    assert panel.rect().contains(button_rect)


def test_session_panel_maximized_first_show_and_restore_reapply_width_rules(
    qt_app, session_layout_window,
):
    window, panel = session_layout_window((1920, 1080), maximized=True)
    assert 1400 <= panel._workspace_content.width() <= 1520
    assert panel._configuration_panel.width() <= 420
    config = panel.build_config()
    window.setWindowState(Qt.WindowState.WindowNoState)
    qt_app.processEvents()
    assert window.size().toTuple() == (1920, 1080)
    assert panel._workspace_content.width() <= 1120
    # Repeated state changes at the same size must not need a resize event.
    for state, minimum_width in ((Qt.WindowState.WindowMaximized, 1400),
                                 (Qt.WindowState.WindowNoState, 1100)):
        window.setWindowState(state)
        qt_app.processEvents()
        assert panel._workspace_content.width() >= minimum_width
    assert panel._workspace_content.width() <= 1120
    assert panel.build_config() == config


def test_session_panel_maximized_narrow_reflow_releases_configuration_width(
    qt_app, session_layout_window,
):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QBoxLayout, QPushButton

    window, panel = session_layout_window((1920, 1080), maximized=True)
    window.setWindowState(Qt.WindowState.WindowNoState)
    # Cross the reflow breakpoint first, as a resize drag does, so Qt can
    # recompute the containing window's minimum size for the stacked layout.
    window.resize(560, 560)
    for _ in range(3):
        qt_app.processEvents()
    window.resize(500, 560)
    qt_app.processEvents()
    assert window.size().toTuple() == (500, 560)
    assert panel._columns.direction() is QBoxLayout.Direction.TopToBottom
    assert panel._configuration_panel.width() >= 440
    viewport = panel._configuration_scroll.viewport()
    for control in [panel._start_date, panel._end_date, panel._date_adjust_target,
                    panel._date_adjust_unit, *panel._date_adjust_tools.findChildren(QPushButton)]:
        panel._configuration_scroll.ensureWidgetVisible(control)
        qt_app.processEvents()
        rect = control.rect().translated(control.mapTo(viewport, QPoint(0, 0)))
        assert viewport.rect().contains(rect)


@pytest.mark.parametrize("source_name", ["QQ", "WECHAT"])
def test_session_workspace_maximized_ready_row_aligns_with_shared_content(
    qt_app, sources, source_name,
):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from qq_chat_analyzer.gui.qq_workspace import QQWorkspace
    from qq_chat_analyzer.gui.wechat_workspace import WeChatWorkspace

    module = _facade_module()
    window = QWidget()
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(0, 0, 0, 0)
    workspace_type = QQWorkspace if source_name == "QQ" else WeChatWorkspace
    workspace = workspace_type(StubFacade(sources=sources), executor=_inline_executor())
    layout.addWidget(workspace)
    workspace._handle_sessions_loaded([
        _session(getattr(module.ChatSource, source_name), "fiction-A", "虚构会话", 10)
    ])
    workspace._status_label.show()
    window.resize(1920, 1080)
    window.show()
    qt_app.processEvents()
    try:
        for state in (Qt.WindowState.WindowMaximized, Qt.WindowState.WindowNoState):
            window.setWindowState(state)
            qt_app.processEvents()
            content = workspace.session_panel._workspace_content
            if state is Qt.WindowState.WindowMaximized:
                assert content.width() >= 1400
            left = content.mapTo(workspace, QPoint(0, 0)).x()
            status_left = workspace._status_label.mapTo(workspace, QPoint(0, 0)).x()
            assert abs(left - status_left) <= 1
            margins = workspace._connection_layout.contentsMargins()
            assert margins.left() == margins.right()
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


@pytest.fixture
def custom_date_panel(qt_app, sources):
    """Real widgets with fictional sessions and controllable facade callbacks."""
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel

    panels = []

    def make(source_name="QQ", executor=None):
        module = _facade_module()
        source = getattr(module.ChatSource, source_name)
        panel = SessionAnalysisPanel()
        panel.configure(StubFacade(sources=sources), source,
                        executor=executor or _inline_executor())
        panel.populate_sessions([
            _session(source, "fiction-A", "虚构会话 A", 10),
            _session(source, "fiction-B", "虚构会话 B", 5),
        ])
        panel.resize(780, 620)
        panel.show()
        panel._session_list.setCurrentRow(0)
        panel._scope_custom.setChecked(True)
        qt_app.processEvents()
        panels.append(panel)
        return panel

    yield make
    for panel in panels:
        panel.cancel_analysis()
        panel.close()
        panel.deleteLater()
    qt_app.processEvents()


def _date_adjust_controls(panel):
    from PySide6.QtWidgets import QComboBox, QPushButton, QWidget

    tools = panel.findChild(QWidget, "dateAdjustmentTools")
    target = panel.findChild(QComboBox, "dateAdjustTarget")
    unit = panel.findChild(QComboBox, "dateAdjustUnit")
    assert tools is not None, "自定义日期需要微调工具"
    assert target is not None and unit is not None
    steps = {}
    for button in tools.findChildren(QPushButton):
        steps[int(button.text())] = button
    assert set(steps) == {-5, -1, 1, 5}
    return tools, target, unit, steps


@pytest.mark.parametrize("section,text,expected", [
    ("YearSection", "2023", "2023-01-15"),
    ("MonthSection", "12", "2024-12-15"),
    ("DaySection", "28", "2024-01-28"),
])
def test_session_panel_date_native_input_commits_without_intermediate_updates(
    custom_date_panel, section, text, expected,
):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QDateEdit

    panel = custom_date_panel()
    edit = panel._start_date
    edit.setDate(QDate(2024, 1, 15))
    panel._end_date.setDate(QDate(2025, 12, 31))
    assert not edit.calendarPopup()
    assert not edit.keyboardTracking()
    assert not panel._end_date.calendarPopup()
    assert not panel._end_date.keyboardTracking()
    # Click each native section, then replace its selected text with the keyboard.
    prefix = {"YearSection": "", "MonthSection": "2024-", "DaySection": "2024-01-"}[section]
    line = edit.lineEdit()
    QTest.mouseClick(line, Qt.MouseButton.LeftButton,
                     pos=QPoint(line.fontMetrics().horizontalAdvance(prefix) + 6,
                                line.height() // 2))
    assert edit.currentSection() == getattr(QDateEdit, section)
    edit.setSelectedSection(edit.currentSection())
    changes = []
    edit.dateChanged.connect(changes.append)
    QTest.keyClicks(edit, text)
    assert changes == []
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert panel.build_config().start_time == expected
    assert panel.build_config().end_time == "2025-12-31"
    assert len(changes) == 1


def test_session_panel_date_adjustment_has_clear_defaults_and_scope_visibility(custom_date_panel):
    panel = custom_date_panel()
    tools, target, unit, _ = _date_adjust_controls(panel)
    assert tools.isVisible()
    assert target.currentText() == "开始日期"
    assert unit.currentText() == "日"
    assert panel._start_date.property("adjustmentTarget") is True
    assert panel._end_date.property("adjustmentTarget") is False
    target.setCurrentIndex(1)
    assert panel._end_date.property("adjustmentTarget") is True
    assert panel._start_date.property("adjustmentTarget") is False
    panel._scope_all.setChecked(True)
    assert not tools.isVisible()
    panel._scope_custom.setChecked(True)
    assert tools.isVisible()


@pytest.mark.parametrize("target_index", [0, 1])
@pytest.mark.parametrize("unit_text,step,before,expected", [
    ("日", -5, (2024, 3, 3), (2024, 2, 27)),
    ("日", -1, (2024, 3, 1), (2024, 2, 29)),
    ("日", 1, (2024, 12, 31), (2025, 1, 1)),
    ("日", 5, (2024, 1, 29), (2024, 2, 3)),
    ("月", -5, (2024, 7, 31), (2024, 2, 29)),
    ("月", -1, (2023, 3, 31), (2023, 2, 28)),
    ("月", 1, (2024, 1, 31), (2024, 2, 29)),
    ("月", 5, (2024, 8, 31), (2025, 1, 31)),
    ("年", -5, (2024, 2, 29), (2019, 2, 28)),
    ("年", -1, (2024, 2, 29), (2023, 2, 28)),
    ("年", 1, (2024, 2, 29), (2025, 2, 28)),
    ("年", 5, (2024, 2, 29), (2029, 2, 28)),
])
def test_session_panel_date_steps_change_only_selected_endpoint(
    custom_date_panel, target_index, unit_text, step, before, expected,
):
    panel = custom_date_panel()
    _, target, unit, steps = _date_adjust_controls(panel)
    edits = (panel._start_date, panel._end_date)
    edit, other = edits[target_index], edits[1 - target_index]
    edit.setDate(QDate(*before))
    other.setDate(QDate(2030, 6, 15))
    target.setCurrentIndex(target_index)
    unit.setCurrentText(unit_text)
    QTest.mouseClick(steps[step], Qt.MouseButton.LeftButton)
    assert edit.date() == QDate(*expected)
    assert other.date() == QDate(2030, 6, 15)


@pytest.mark.parametrize("unit_text", ["年", "月", "日"])
@pytest.mark.parametrize("step,before,expected", [
    (-5, (1, 1, 2), (1, 1, 1)),
    (-1, (1, 1, 1), (1, 1, 1)),
    (1, (9999, 12, 31), (9999, 12, 31)),
    (5, (9999, 12, 30), (9999, 12, 31)),
])
def test_session_panel_date_steps_clamp_to_editor_bounds(
    custom_date_panel, unit_text, step, before, expected,
):
    panel = custom_date_panel()
    _, _, unit, steps = _date_adjust_controls(panel)
    panel._start_date.setDate(QDate(*before))
    unit.setCurrentText(unit_text)
    steps[step].click()
    assert panel._start_date.date() == QDate(*expected)


def test_session_panel_date_reverse_range_blocks_analysis_and_recovers(custom_date_panel):
    from PySide6.QtWidgets import QLabel

    executor = _IndependentDeferredExecutor()
    panel = custom_date_panel(executor=executor)
    started = []
    panel.analysis_started.connect(lambda: started.append(True))
    panel._start_date.setDate(QDate(2024, 3, 2))
    panel._end_date.setDate(QDate(2024, 3, 1))
    error = panel.findChild(QLabel, "dateRangeError")
    assert error is not None and error.isVisible()
    assert "开始日期" in error.text() and "结束日期" in error.text()
    assert not panel._analyze_button.isEnabled()
    panel.start_analysis()  # The callable entry must enforce the same guard.
    _drain(panel)
    assert started == [] and executor.tasks == []
    # A single-endpoint step fixes the range without moving the start date.
    _, target, unit, steps = _date_adjust_controls(panel)
    target.setCurrentIndex(1)
    unit.setCurrentText("日")
    steps[1].click()
    assert panel._start_date.date() == QDate(2024, 3, 2)
    assert panel._end_date.date() == QDate(2024, 3, 2)
    assert error.isHidden() and panel._analyze_button.isEnabled()
    panel._end_date.setDate(QDate(2024, 3, 1))
    panel._scope_all.setChecked(True)
    assert error.isHidden() and panel._analyze_button.isEnabled()


@pytest.mark.parametrize("endpoint", ["start", "end"])
@pytest.mark.parametrize("pending", [False, True])
def test_session_panel_date_wechat_defaults_preserve_manual_input(
    custom_date_panel, endpoint, pending,
):
    from PySide6.QtWidgets import QDateEdit

    executor = _IndependentDeferredExecutor()
    panel = custom_date_panel("WECHAT", executor)
    edit = getattr(panel, f"_{endpoint}_date")
    edit.setFocus()
    edit.setSelectedSection(QDateEdit.Section.YearSection)
    QTest.keyClicks(edit, "2023")
    typed = edit.lineEdit().text()
    if not pending:
        QTest.keyClick(edit, Qt.Key.Key_Return)
    executor.tasks[0].succeed((1704067200, 1704153600))
    assert edit.lineEdit().text() == typed
    if pending:
        QTest.keyClick(edit, Qt.Key.Key_Return)
    assert edit.date().year() == 2023
    other = panel._end_date if endpoint == "start" else panel._start_date
    timestamp = 1704153600 if endpoint == "start" else 1704067200
    assert other.date().toPython() == datetime.fromtimestamp(timestamp).date()


def test_session_panel_date_wechat_defaults_preserve_microadjustment(custom_date_panel):
    executor = _IndependentDeferredExecutor()
    panel = custom_date_panel("WECHAT", executor)
    _, _, _, steps = _date_adjust_controls(panel)
    steps[-5].click()
    adjusted = panel._start_date.date()
    executor.tasks[0].succeed((1704067200, 1704153600))
    assert panel._start_date.date() == adjusted


def test_session_panel_date_wechat_stale_requests_cannot_pollute_reselected_session(custom_date_panel):
    executor = _IndependentDeferredExecutor()
    panel = custom_date_panel("WECHAT", executor)
    # A -> B -> A needs request identity as well as session identity.
    panel._start_date.setDate(QDate(2023, 5, 6))
    panel._session_list.setCurrentRow(1)
    assert panel._start_date.date() == QDate.currentDate()
    panel._session_list.setCurrentRow(0)
    executor.tasks[2].succeed((1704067200, 1704153600))
    expected = panel.build_config()
    executor.tasks[0].succeed((1609459200, 1609545600))
    executor.tasks[1].succeed((1640995200, 1641081600))
    assert panel.build_config() == expected
    assert panel._start_date.date().toPython() == datetime.fromtimestamp(1704067200).date()
    assert panel._end_date.date().toPython() == datetime.fromtimestamp(1704153600).date()


def test_session_panel_scope_defaults_to_all(qt_app, sources) -> None:
    """The shared panel defaults to analysing the full history."""
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel
    module = _facade_module()
    panel = SessionAnalysisPanel()
    panel.configure(StubFacade(sources=sources), module.ChatSource.QQ)

    config = panel.build_config()

    assert panel._scope_all.isChecked() is True
    assert panel._custom_range_widget.isHidden() is True
    assert config.scope_mode is module.AnalysisScopeMode.ALL
    assert config.start_time is None
    assert config.end_time is None


@pytest.mark.parametrize(
    ("control_name", "expected_mode"),
    [
        ("_scope_last_year", "LAST_YEAR"),
        ("_scope_last_six_months", "LAST_SIX_MONTHS"),
    ],
)
def test_session_panel_relative_scope_reaches_the_config(
    qt_app,
    sources,
    control_name,
    expected_mode,
) -> None:
    """Relative scope choices translate into the facade config."""
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel
    module = _facade_module()
    panel = SessionAnalysisPanel()
    panel.configure(StubFacade(sources=sources), module.ChatSource.QQ)

    getattr(panel, control_name).setChecked(True)
    config = panel.build_config()

    assert config.scope_mode is getattr(module.AnalysisScopeMode, expected_mode)
    assert config.start_time is None
    assert config.end_time is None
    assert panel._custom_range_widget.isHidden() is True


def test_session_panel_custom_scope_reaches_the_config(
    qt_app,
    sources,
) -> None:
    """Custom scope exposes the date editors and carries them into the config."""
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel
    module = _facade_module()
    panel = SessionAnalysisPanel()
    panel.configure(StubFacade(sources=sources), module.ChatSource.QQ)

    panel._scope_custom.setChecked(True)
    panel._start_date.setDate(QDate(2026, 2, 11))
    panel._end_date.setDate(QDate(2026, 8, 11))
    config = panel.build_config()

    assert panel._custom_range_widget.isHidden() is False
    assert config.scope_mode is module.AnalysisScopeMode.CUSTOM
    assert config.start_time == "2026-02-11"
    assert config.end_time == "2026-08-11"


def test_session_panel_search_filters_display_names(qt_app) -> None:
    """The shared panel search filters by display name and tracks the count."""
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel
    module = _facade_module()
    panel = SessionAnalysisPanel()
    panel.configure(
        StubFacade(sources=_wechat_available_sources()),
        module.ChatSource.WECHAT,
    )
    panel.populate_sessions(
        [
            _session(module.ChatSource.WECHAT, "wxid_a", "Alice"),
            _session(module.ChatSource.WECHAT, "wxid_b", "Board Game"),
            _session(module.ChatSource.WECHAT, "wxid_c", "Alice's Study Room"),
        ]
    )

    panel._session_search.setText("alice")

    assert panel._session_list.count() == 2
    assert [panel._session_list.item(i).text() for i in range(2)] == [
        "Alice",
        "Alice's Study Room",
    ]
    assert "聊天会话（2）" in panel._session_box.title()

    panel._session_search.setText("board")

    assert panel._session_list.count() == 1
    assert panel._session_list.item(0).text() == "Board Game"


@pytest.mark.parametrize("source_name", ["qq", "wechat"])
def test_session_panel_sort_modes_reorder_the_list(qt_app, source_name) -> None:
    """The shared panel re-sorts the cached sessions for each mode."""
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel
    module = _facade_module()
    panel = SessionAnalysisPanel()
    panel.configure(
        StubFacade(sources=_wechat_available_sources()),
        module.ChatSource(source_name),
    )
    panel.populate_sessions(
        [
            _session(
                module.ChatSource(source_name),
                "wxid_old",
                "Alpha",
                count=50,
                last_message_time=100,
            ),
            _session(
                module.ChatSource(source_name),
                "wxid_new",
                "Beta",
                count=1,
                last_message_time=300,
            ),
            _session(
                module.ChatSource(source_name),
                "wxid_mid",
                "Gamma",
                count=30,
                last_message_time=200,
            ),
        ]
    )

    def names():
        return [
            panel._session_list.item(i).text()
            for i in range(panel._session_list.count())
        ]

    assert names() == ["Beta", "Gamma", "Alpha"]

    panel._session_sort.setCurrentIndex(_sort_index(panel, "message_count"))
    assert names() == ["Alpha", "Gamma", "Beta"]

    panel._session_sort.setCurrentIndex(_sort_index(panel, "name"))
    assert names() == ["Alpha", "Beta", "Gamma"]
    from PySide6.QtCore import QEvent
    panel.close()
    panel.deleteLater()
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("source_name", ["qq", "wechat"])
def test_session_sort_disables_unknown_counts_and_restores_supported_sort(qt_app, source_name):
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel
    module = _facade_module()
    source = module.ChatSource(source_name)
    panel = SessionAnalysisPanel()
    panel.configure(StubFacade(), source)
    count_index = _sort_index(panel, "message_count")
    def names():
        return [panel._session_list.item(i).text() for i in range(panel._session_list.count())]
    panel.populate_sessions([
        _session(source, "fiction-b", "Beta", None, last_message_time=100),
        _session(source, "fiction-a", "Alpha", None, last_message_time=300),
    ])
    assert not panel._session_sort.model().item(count_index).isEnabled()
    assert "消息数量" in panel._session_sort.toolTip()
    assert names() == ["Alpha", "Beta"]
    panel._session_sort.setCurrentIndex(_sort_index(panel, "name"))
    assert names() == ["Alpha", "Beta"]
    panel.populate_sessions([
        _session(source, "fiction-b", "Beta", 0, last_message_time=None),
        _session(source, "fiction-a", "Alpha", 4, last_message_time=300),
        _session(source, "fiction-c", "Gamma", 4, last_message_time=300),
        _session(source, "fiction-d", "Delta", None, last_message_time=None),
    ])
    assert panel._session_sort.model().item(count_index).isEnabled()
    panel._session_sort.setCurrentIndex(count_index)
    assert names() == ["Alpha", "Gamma", "Beta", "Delta"]
    panel._session_sort.setCurrentIndex(_sort_index(panel, "recent"))
    assert names() == ["Alpha", "Gamma", "Beta", "Delta"]
    panel._session_sort.setCurrentIndex(count_index)
    panel.populate_sessions([
        _session(source, "fiction-z", "Zulu", None),
        _session(source, "fiction-a", "Alpha", None),
    ])
    assert panel._session_sort.currentData() == "recent"
    assert names() == ["Zulu", "Alpha"]  # absent timestamps preserve source order
    panel.close()
    panel.deleteLater()
    from PySide6.QtCore import QEvent
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_wechat_database_counts_drive_all_three_gui_sorts(qt_app, tmp_path):
    from test_wechat_db_source import _counting_session_provider
    from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, ChatSource
    from qq_chat_analyzer.application.wechat.wechat_export_import_service import WeChatExportImportService
    from qq_chat_analyzer.gui.session_analysis_panel import SessionAnalysisPanel
    from contextlib import closing
    import sqlite3

    provider, queries = _counting_session_provider(
        tmp_path,
        [{"wxid_alpha": 3, "wxid_beta": 1, "wxid_gamma": 0}, {"wxid_alpha": 4}],
        ["wxid_alpha", "wxid_gamma", "wxid_beta", "wxid_unknown"],
    )
    contact = tmp_path / "xwechat_files" / "wxid_owner" / "db_storage" / "message" / "contact.db"
    with closing(sqlite3.connect(contact)) as connection, connection:
        connection.execute("CREATE TABLE contact (username TEXT, remark TEXT, nick_name TEXT)")
        connection.executemany("INSERT INTO contact VALUES (?, ?, '')", [
            ("wxid_alpha", "Alpha"), ("wxid_beta", "Beta"),
            ("wxid_gamma", "Gamma"), ("wxid_unknown", "Unknown"),
        ])
    facade = ChatAnalyzerFacade(wechat_service=WeChatExportImportService(provider=provider))
    panel = SessionAnalysisPanel()
    panel.configure(facade, ChatSource.WECHAT)
    panel.populate_sessions(facade.list_sessions(ChatSource.WECHAT))
    query_count = len(queries)

    def names():
        return [panel._session_list.item(i).text() for i in range(panel._session_list.count())]

    assert names() == ["Unknown", "Beta", "Gamma", "Alpha"]
    count_index = _sort_index(panel, "message_count")
    assert panel._session_sort.model().item(count_index).isEnabled()
    panel._session_sort.setCurrentIndex(count_index)
    assert names() == ["Alpha", "Beta", "Gamma", "Unknown"]
    assert "7" in panel._session_list.item(0).toolTip()
    assert "0" in panel._session_list.item(2).toolTip()
    panel._session_sort.setCurrentIndex(_sort_index(panel, "name"))
    assert names() == ["Alpha", "Beta", "Gamma", "Unknown"]
    panel._session_sort.setCurrentIndex(_sort_index(panel, "recent"))
    assert names() == ["Unknown", "Beta", "Gamma", "Alpha"]
    assert len(queries) == query_count  # Sorting the cached DTOs never re-queries.
    panel.close()
    panel.deleteLater()
    from PySide6.QtCore import QEvent
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_session_panel_keeps_session_ids_out_of_display_text(qt_app) -> None:
    """Session IDs drive selection but never appear in the displayed text."""
    from qq_chat_analyzer.gui.session_analysis_panel import (
        SESSION_ID_ROLE,
        SessionAnalysisPanel,
    )
    module = _facade_module()
    panel = SessionAnalysisPanel()
    panel.configure(
        StubFacade(sources=_wechat_available_sources()),
        module.ChatSource.WECHAT,
    )
    panel.populate_sessions(
        [
            _session(
                module.ChatSource.WECHAT,
                "secret-id-10001",
                "\u865a\u6784\u7fa4 A",
            )
        ]
    )

    item = panel._session_list.item(0)

    assert item.text() == "\u865a\u6784\u7fa4 A"
    assert "secret-id-10001" not in item.text()
    assert item.data(SESSION_ID_ROLE) == "secret-id-10001"


def test_qq_workspace_full_chain_connect_sessions_analyze(
    qt_app, sources, tmp_path, monkeypatch
) -> None:
    """QQ workspace keeps the GUI-2 connect -> sessions -> analyze chain."""
    from qq_chat_analyzer.gui.main_window import (
        DASHBOARD_PAGE_INDEX,
        PROCESSING_PAGE_INDEX,
        QQ_WORKSPACE_INDEX,
    )
    module = _facade_module()
    qq_module = importlib.import_module("qq_chat_analyzer.gui.qq_workspace")
    monkeypatch.setattr(qq_module, "_QQ_CONNECT_MIN_DISPLAY_MS", 0)
    disconnected = module.QQConnectionStatus(
        available=False, runtime_running=False, qq_online=False,
        version="", message="QQ 尚未连接。", action_hint="",
    )
    connected = module.QQConnectionStatus(
        available=True, runtime_running=True, qq_online=True,
        version="4.1.0", message="已连接", action_hint="",
    )
    report_path = tmp_path / "echo-qq.html"
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")
    opened: list[Path] = []
    facade = StubFacade(
        sources=sources,
        sessions=[_session(module.ChatSource.QQ, "q1", "QQ群1", 100)],
        outcome=_StubOutcome(_dashboard_view(), report_path=report_path),
        connection_status=disconnected,
        connection_status_after_connect=connected,
    )
    executor = _DeferredExecutor()
    window = _main_window(qt_app, facade, executor=executor)
    window._report_opener = lambda path: opened.append(path) or True
    window.navigate_to_qq()
    _drain(window)

    # status -> disconnected
    assert executor.operation is not None
    executor.operation()
    executor.succeed(facade.get_qq_connection_snapshot())
    assert window.qq_workspace._qq_connect_button.isVisibleTo(window) is True
    assert window.qq_workspace.session_panel._sessions_ready is False

    # connect/auth operation with progress
    window.qq_workspace._qq_connect_button.click()
    executor.on_progress("等待QQ登录")
    assert window.qq_workspace._qq_login_guide_label.isVisibleTo(window) is True
    executor.operation(lambda _message: None)
    assert facade.start_qq_auth_flow_calls
    executor.succeed(facade.get_qq_connection_snapshot())
    _drain(window)

    # connected -> list_sessions(QQ)
    executor.operation()
    executor.succeed(facade._sessions)
    assert facade.list_sessions_calls == [module.ChatSource.QQ]
    assert window.qq_workspace.session_panel._sessions_ready is True
    assert window.qq_workspace.session_panel._session_list.count() == 1

    # select session + custom scope -> analyze_session -> processing -> dashboard
    window.qq_workspace.session_panel._session_list.setCurrentRow(0)
    window.qq_workspace.session_panel._scope_custom.setChecked(True)
    window.qq_workspace.session_panel._start_date.setDate(QDate(2024, 1, 1))
    window.qq_workspace.session_panel._end_date.setDate(QDate(2024, 12, 31))
    window.qq_workspace.session_panel.start_analysis()
    _drain(window.qq_workspace.session_panel)
    assert window.stack.currentIndex() == PROCESSING_PAGE_INDEX

    executor.operation(lambda _message: None)
    assert facade.analyze_session_calls
    source, session_id, config = facade.analyze_session_calls[0]
    assert source == module.ChatSource.QQ
    assert session_id == "q1"
    assert config.scope_mode is module.AnalysisScopeMode.CUSTOM
    assert config.start_time == "2024-01-01"
    assert config.end_time == "2024-12-31"
    executor.succeed(_StubOutcome(_dashboard_view(), report_path=report_path))
    assert window.stack.currentIndex() == QQ_WORKSPACE_INDEX
    assert window.stack.currentIndex() != DASHBOARD_PAGE_INDEX
    assert opened == [report_path.resolve()]
    assert window._open_echo_button.isVisibleTo(window)


def test_wechat_workspace_full_chain_connect_sessions_analyze(
    qt_app, sources, tmp_path
) -> None:
    """WeChat workspace keeps the GUI-2 connect -> sessions -> analyze chain."""
    from qq_chat_analyzer.gui.main_window import (
        DASHBOARD_PAGE_INDEX,
        PROCESSING_PAGE_INDEX,
        WECHAT_WORKSPACE_INDEX,
    )
    module = _facade_module()
    disconnected = module.WeChatConnectionStatus(
        available=False, data_found=True, db_key_available=False,
        runtime_available=True, message="等待微信登录", action_hint="",
    )
    connected = module.WeChatConnectionStatus(
        available=True, data_found=True, db_key_available=True,
        runtime_available=True, message="微信已连接", action_hint="",
    )
    report_path = tmp_path / "echo-wechat.html"
    report_path.write_text("<html>fictional report</html>", encoding="utf-8")
    opened: list[Path] = []
    facade = StubFacade(
        sources=sources,
        sessions=[_session(module.ChatSource.WECHAT, "wx1", "测试会话1", 10)],
        outcome=_StubOutcome(_dashboard_view(), report_path=report_path),
        connection_status=disconnected,
        connection_status_after_connect=connected,
        data_roots=["D:/fictional_wechat"],
    )
    executor = _DeferredExecutor()
    window = _main_window(qt_app, facade, executor=executor)
    window._report_opener = lambda path: opened.append(path) or True
    window.navigate_to_wechat()
    _drain(window)

    # status -> disconnected
    executor.operation()
    executor.succeed(disconnected)
    assert window.wechat_workspace._wechat_connect_button.isVisibleTo(window) is True
    assert window.wechat_workspace.session_panel._sessions_ready is False

    # one-click connect: detect root -> save environment + key -> connected
    window.wechat_workspace._wechat_connect_button.click()
    assert facade.detect_wechat_data_roots_calls
    executor.on_progress(module.WeChatConnectionProgress.READY_FOR_LOGIN)
    assert "现在可以登录微信" in window.wechat_workspace._status_label.text()
    executor.operation(lambda _message: None)
    assert facade.setup_wechat_environment_calls
    assert facade.acquire_wechat_db_key_calls
    executor.succeed(connected)
    _drain(window)

    # connected -> list_sessions(WECHAT)
    executor.operation()
    executor.succeed(facade._sessions)
    assert facade.list_sessions_calls == [module.ChatSource.WECHAT]
    assert window.wechat_workspace.session_panel._sessions_ready is True
    assert window.wechat_workspace.session_panel._session_list.count() == 1

    # select session + analyze -> processing -> dashboard
    window.wechat_workspace.session_panel._session_list.setCurrentRow(0)
    window.wechat_workspace.session_panel.start_analysis()
    _drain(window.wechat_workspace.session_panel)
    assert window.stack.currentIndex() == PROCESSING_PAGE_INDEX

    executor.operation(lambda _message: None)
    assert facade.analyze_session_calls
    source, session_id, config = facade.analyze_session_calls[0]
    assert source == module.ChatSource.WECHAT
    assert session_id == "wx1"
    assert config.scope_mode is module.AnalysisScopeMode.ALL
    executor.succeed(_StubOutcome(_dashboard_view(), report_path=report_path))
    assert window.stack.currentIndex() == WECHAT_WORKSPACE_INDEX
    assert window.stack.currentIndex() != DASHBOARD_PAGE_INDEX
    assert opened == [report_path.resolve()]
    assert window._open_echo_button.isVisibleTo(window)


def test_workspace_analysis_failure_returns_to_workspace(
    qt_app, sources, monkeypatch
) -> None:
    """A failed workspace analysis returns to its workspace, not the legacy page."""
    from qq_chat_analyzer.gui.main_window import QQ_WORKSPACE_INDEX
    main_window_module = importlib.import_module(
        "qq_chat_analyzer.gui.main_window"
    )
    monkeypatch.setattr(
        main_window_module.QMessageBox, "warning", lambda *args: None
    )
    module = _facade_module()
    facade = StubFacade(
        sources=sources,
        sessions=[_session(module.ChatSource.QQ, "q1", "QQ群1", 100)],
    )
    executor = _DeferredExecutor()
    window = _main_window(qt_app, facade, executor=executor)
    window._report_opener = lambda path: opened.append(path) or True
    window.navigate_to_qq()
    _drain(window)
    executor.operation()
    executor.succeed(facade.get_qq_connection_snapshot())
    executor.operation()
    executor.succeed(facade._sessions)

    window.qq_workspace.session_panel._session_list.setCurrentRow(0)
    window.qq_workspace.session_panel.start_analysis()
    _drain(window.qq_workspace.session_panel)
    executor.operation(lambda _message: None)
    executor.fail("fictional_failure", "虚构分析失败")

    assert window.stack.currentIndex() == QQ_WORKSPACE_INDEX
    assert "虚构分析失败" in window._status_label.text()


def test_workspace_cancel_analysis_returns_to_workspace(
    qt_app, sources
) -> None:
    """Cancelling workspace analysis returns to the same workspace."""
    from qq_chat_analyzer.gui.main_window import QQ_WORKSPACE_INDEX
    module = _facade_module()
    facade = StubFacade(
        sources=sources,
        sessions=[_session(module.ChatSource.QQ, "q1", "QQ群1", 100)],
    )
    executor = _DeferredExecutor()
    window = _main_window(qt_app, facade, executor=executor)
    window._report_opener = lambda path: opened.append(path) or True
    window.navigate_to_qq()
    _drain(window)
    executor.operation()
    executor.succeed(facade.get_qq_connection_snapshot())
    executor.operation()
    executor.succeed(facade._sessions)

    window.qq_workspace.session_panel._session_list.setCurrentRow(0)
    window.qq_workspace.session_panel.start_analysis()
    _drain(window.qq_workspace.session_panel)
    assert executor.cancelled is False

    window._cancel_analysis_button.click()

    assert executor.cancelled is True
    assert window.stack.currentIndex() == QQ_WORKSPACE_INDEX
    assert window.qq_workspace.session_panel._analysis_running is False

# ----------------------------------------------------------------
# GUI-5: WeChat data path auto-detection on workspace entry
# ----------------------------------------------------------------

def _window_with_running_fictional_analysis(qt_app, source):
    """Keep a loaded workspace and hold its analysis until cancellation."""
    module = _facade_module()
    facade = StubFacade(
        sessions=[_session(source, "fiction-A", "Fiction A", 2),
                  _session(source, "fiction-B", "Fiction B", 3)],
        connection_status=SimpleNamespace(
            available=True, runtime_running=True, qq_online=True,
            message="Fiction ready", action_hint="", version=None,
        ),
    )
    executor = _IndependentDeferredExecutor()
    window = _main_window(qt_app, facade, executor=executor)
    workspace = window.qq_workspace if source is module.ChatSource.QQ else window.wechat_workspace
    workspace.select_source(module.SourceInfo(source=source, display_name="Fiction", available=True))
    workspace._handle_sessions_loaded(facade._sessions)
    window._active_source = source.value
    panel = workspace.session_panel
    panel._session_list.setCurrentRow(1)
    panel._scope_custom.setChecked(True)
    panel._start_date.setDate(QDate(2020, 1, 2))
    panel._end_date.setDate(QDate(2021, 3, 4))
    panel.start_analysis()
    _drain(panel)
    return window, facade, executor, panel


@pytest.mark.parametrize("source_name", ["qq", "wechat"])
def test_processing_structured_phase_chain_ignores_progress_wording(qt_app, source_name):
    from qq_chat_analyzer.application.analysis_phase import AnalysisPhase
    source = _facade_module().ChatSource(source_name)
    window, _, executor, panel = _window_with_running_fictional_analysis(qt_app, source)
    page = window.processing_page
    assert page.phase is AnalysisPhase.READING
    task = executor.tasks[-1]
    task.progress("正在分析聊天内容...")
    assert page.phase is AnalysisPhase.READING
    task.progress(AnalysisPhase.ANALYZING_REPORT)
    assert page.phase is AnalysisPhase.ANALYZING_REPORT
    task.progress("正在读取聊天记录...")
    assert window.processing_status_label.text() == "正在分析与生成报告"
    assert panel._analysis_running  # analysis is not task completion


@pytest.mark.parametrize("size", [(800, 600), (1200, 760)])
def test_processing_layout_in_the_formal_window(qt_app, size):
    from PySide6.QtCore import QPoint
    from qq_chat_analyzer.gui.theme import BASE_QSS
    window, _, _, _ = _window_with_running_fictional_analysis(qt_app, _facade_module().ChatSource.QQ)
    window.setStyleSheet(BASE_QSS)
    window.resize(*size)
    window.show()
    _drain(window)
    page = window.processing_page
    assert (window.width(), window.height()) == size
    surface_point = page.mapTo(window, QPoint(5, 5))
    assert window.grab().toImage().pixelColor(surface_point).name() == "#fbf9f4"
    children = (page.animation, page.status_label, page.subtitle_label, page.cancel_button)
    for child in children:
        assert child.isVisibleTo(window)
        assert page.rect().contains(child.geometry())
        assert window.rect().contains(child.mapTo(window, QPoint(0, 0)))
        assert window.rect().contains(child.mapTo(window, child.rect().bottomRight()))
    for upper, lower in zip(children, children[1:]):
        assert upper.geometry().bottom() < lower.geometry().top()
    window.hide()


@pytest.mark.parametrize("source_name", ["qq", "wechat"])
def test_processing_cancel_returns_while_real_worker_is_still_blocked(qt_app, source_name):
    from qq_chat_analyzer.application.facade import AnalysisPhase
    from qq_chat_analyzer.gui.main_window import QQ_WORKSPACE_INDEX, WECHAT_WORKSPACE_INDEX
    from qq_chat_analyzer.gui.workers import submit
    window, facade, _, panel = _window_with_running_fictional_analysis(qt_app, _facade_module().ChatSource(source_name))
    window.cancel_analysis()
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    def analyze_session(source, session_id, config=None, progress=None, on_phase=None):
        on_phase(AnalysisPhase.READING)
        entered.set()
        release.wait(5)
        returned.set()
        on_phase(AnalysisPhase.ANALYZING_REPORT)
        return _StubOutcome(_dashboard_view())
    facade.analyze_session = analyze_session
    panel._executor = submit
    opened = []
    window._report_opener = lambda path: opened.append(path)
    panel.start_analysis()
    _drain(window)
    try:
        assert entered.wait(2)
        window.cancel_analysis()
        assert not returned.is_set()  # cancellation does not kill blocking work
        assert not panel._analysis_running
        assert not window.processing_page.animation._timer.isActive()
        assert window.stack.currentIndex() == (QQ_WORKSPACE_INDEX if source_name == "qq" else WECHAT_WORKSPACE_INDEX)
        assert panel.selected_session_id() == "fiction-B"
        assert panel.build_config().start_time == "2020-01-02"
        assert panel.build_config().end_time == "2021-03-04"
    finally:
        release.set()
        _settle_workers()
    assert returned.is_set()
    assert opened == []


@pytest.mark.parametrize("source_name", ["qq", "wechat"])
def test_processing_cancel_retry_rejects_old_phase_and_terminal_callbacks(qt_app, source_name, tmp_path, monkeypatch):
    from qq_chat_analyzer.application.analysis_phase import AnalysisPhase
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: pytest.fail("stale error displayed"))
    source = _facade_module().ChatSource(source_name)
    window, _, executor, panel = _window_with_running_fictional_analysis(qt_app, source)
    opened = []
    window._report_opener = lambda path: opened.append(path) or True
    old = executor.tasks[-1]
    window.cancel_analysis()
    assert not window.processing_page.animation.model.active
    assert not window.processing_page.animation._timer.isActive()
    panel.start_analysis()
    _drain(panel)
    current = executor.tasks[-1]
    old.progress(AnalysisPhase.ANALYZING_REPORT)
    old.progress("旧任务进度")
    report = tmp_path / "fictional-report.html"
    report.write_text("<html>Fiction</html>", encoding="utf-8")
    old.succeed(_StubOutcome(_dashboard_view(), report_path=report))
    old.fail("fiction", "旧任务错误")
    old.finish()
    assert window.processing_page.phase is AnalysisPhase.READING
    assert panel._analysis_task is current
    assert panel._analysis_running
    assert opened == []


@pytest.mark.parametrize("source_name", ["qq", "wechat"])
def test_processing_quick_success_stops_before_open_and_opens_once(qt_app, source_name, tmp_path):
    from qq_chat_analyzer.gui.main_window import QQ_WORKSPACE_INDEX, WECHAT_WORKSPACE_INDEX
    source = _facade_module().ChatSource(source_name)
    window, _, executor, panel = _window_with_running_fictional_analysis(qt_app, source)
    report = tmp_path / "fictional-report.html"
    report.write_text("<html>Fiction</html>", encoding="utf-8")
    opened = []
    def open_report(path):
        assert not window.processing_page.animation.model.active
        assert not window.processing_page.animation._timer.isActive()
        opened.append(path)
        return True
    window._report_opener = open_report
    task = executor.tasks[-1]
    outcome = _StubOutcome(_dashboard_view(), report_path=report)
    task.succeed(outcome)
    task.succeed(outcome)
    task.progress("迟到进度")
    task.finish()
    assert opened == [report.resolve()]
    assert not panel._analysis_running
    assert window.stack.currentIndex() == (QQ_WORKSPACE_INDEX if source_name == "qq" else WECHAT_WORKSPACE_INDEX)
    assert window._status_label.text() != "迟到进度"


@pytest.mark.parametrize("source_name", ["qq", "wechat"])
def test_processing_failure_stops_before_safe_error_dialog(qt_app, source_name, monkeypatch):
    source = _facade_module().ChatSource(source_name)
    window, _, executor, panel = _window_with_running_fictional_analysis(qt_app, source)
    shown = []
    def warning(_window, _title, message):
        assert not window.processing_page.animation.model.active
        assert not window.processing_page.animation._timer.isActive()
        shown.append(message)
    monkeypatch.setattr(QMessageBox, "warning", warning)
    task = executor.tasks[-1]
    task.fail("fictional_error", "虚构安全错误")
    task.fail("fictional_error", "重复错误")
    assert shown == ["虚构安全错误"]
    assert not panel._analysis_running


def test_processing_close_invalidates_task_before_shutdown(qt_app, monkeypatch):
    source = _facade_module().ChatSource.QQ
    window, facade, executor, _ = _window_with_running_fictional_analysis(qt_app, source)
    monkeypatch.setattr("qq_chat_analyzer.gui.main_window._quit_application", lambda: None)
    called = []
    window._report_opener = lambda path: called.append(path)
    task = executor.tasks[-1]
    window.close()
    assert not window.processing_page.animation.model.active
    assert not window.processing_page.animation._timer.isActive()
    assert task.cancelled
    task.succeed(_StubOutcome(_dashboard_view()))
    task.finish()
    assert called == []
    assert window._shutdown_protocol.wait(1)
    assert facade.shutdown_calls == [1]


def test_processing_hidden_window_pauses_but_page_departure_stops(qt_app):
    source = _facade_module().ChatSource.QQ
    window, _, _, _ = _window_with_running_fictional_analysis(qt_app, source)
    window.processing_page.set_reduced_motion(False)
    window.show()
    _drain(window)
    animation = window.processing_page.animation
    assert animation._timer.isActive()
    window.hide()
    assert not animation._timer.isActive()
    assert animation.model.active
    window.show()
    assert animation._timer.isActive()
    assert animation._elapsed.nsecsElapsed()/1_000_000 < 50
    window.show_home_page()
    assert not animation._timer.isActive()
    assert not animation.model.active


@pytest.mark.parametrize("source_name", ["qq", "wechat"])
def test_processing_real_worker_delivers_typed_phases_on_gui_thread(qt_app, source_name):
    from qq_chat_analyzer.application.analysis_phase import AnalysisPhase
    from qq_chat_analyzer.gui.workers import submit
    source = _facade_module().ChatSource(source_name)
    window, facade, _, panel = _window_with_running_fictional_analysis(qt_app, source)
    window.cancel_analysis()
    gui_thread = threading.get_ident()
    published_from = []
    received = []
    def analyze_session(source, session_id, config=None, progress=None, on_phase=None):
        published_from.append(threading.get_ident())
        on_phase(AnalysisPhase.READING)
        progress("旧字符串仍可传递")
        on_phase(AnalysisPhase.ANALYZING_REPORT)
        return _StubOutcome(_dashboard_view())
    facade.analyze_session = analyze_session
    panel._executor = submit
    panel.analysis_phase_changed.connect(lambda phase: received.append((phase, threading.get_ident())))
    panel.start_analysis()
    _drain(window)
    _settle_workers()
    assert published_from and published_from[0] != gui_thread
    assert received == [(AnalysisPhase.READING, gui_thread), (AnalysisPhase.ANALYZING_REPORT, gui_thread)]
    assert not panel._analysis_running
    assert not window.processing_page.animation._timer.isActive()


@pytest.mark.parametrize("source_name", ["qq", "wechat"])
def test_cancel_analysis_does_not_refresh_data_source(qt_app, source_name):
    source = _facade_module().ChatSource(source_name)
    window, facade, executor, panel = _window_with_running_fictional_analysis(qt_app, source)
    analysis = executor.tasks[-1]
    submissions = len(executor.tasks)
    window._cancel_analysis_button.click()
    assert analysis.cancelled
    assert not panel._analysis_running

    # Run any new refresh jobs, including a refresh's session-load callback.
    index = submissions
    while index < len(executor.tasks):
        task = executor.tasks[index]
        task.succeed(task.operation())
        task.finish()
        index += 1
    assert {
        "qq_status": facade.get_qq_connection_snapshot_calls,
        "wechat_status": facade.get_connection_status_calls,
        "verify": facade.verify_wechat_database_calls,
        "sessions": facade.list_sessions_calls,
    } == {"qq_status": [], "wechat_status": [], "verify": [], "sessions": []}
    assert len(executor.tasks) == submissions


@pytest.mark.parametrize("source_name", ["qq", "wechat"])
def test_cancel_analysis_preserves_workspace_selection_and_dates(qt_app, source_name):
    from qq_chat_analyzer.gui.main_window import QQ_WORKSPACE_INDEX, WECHAT_WORKSPACE_INDEX

    source = _facade_module().ChatSource(source_name)
    window, _, executor, panel = _window_with_running_fictional_analysis(qt_app, source)
    config = panel.build_config()
    rows = [panel._session_list.item(i).text() for i in range(panel._session_list.count())]
    window._cancel_analysis_button.click()
    _drain(window)

    assert panel.selected_session_id() == "fiction-B"
    assert [panel._session_list.item(i).text() for i in range(panel._session_list.count())] == rows
    assert panel.build_config() == config
    assert panel.isEnabled()
    assert panel._analyze_button.isEnabled()
    expected_page = QQ_WORKSPACE_INDEX if source_name == "qq" else WECHAT_WORKSPACE_INDEX
    assert window.stack.currentIndex() == expected_page
    assert window._home_button.isVisibleTo(window)
    assert not window._back_button.isVisibleTo(window)
    assert window._status_label.text() == "分析已取消。"


def test_wechat_workspace_auto_detects_single_root_when_not_configured(
    qt_app, sources
) -> None:
    """No saved path and one candidate: auto-use it and continue connecting."""
    module = _facade_module()
    missing = module.WeChatConnectionStatus(
        available=False, data_found=False, db_key_available=False,
        runtime_available=False, message="未找到微信数据位置。", action_hint="",
    )
    connected = module.WeChatConnectionStatus(
        available=True, data_found=True, db_key_available=True,
        runtime_available=True, message="微信已连接", action_hint="",
    )
    facade = StubFacade(
        sources=sources,
        connection_status=missing,
        connection_status_after_connect=connected,
        sessions=[_session(module.ChatSource.WECHAT, "wx1", "测试会话1", 10)],
        data_roots=["D:/fictional_wechat"],
    )
    executor = _DeferredExecutor()
    window = _main_window(qt_app, facade, executor=executor)
    window.navigate_to_wechat()
    _drain(window)

    assert facade.detect_wechat_data_roots_calls == []
    executor.operation()
    executor.succeed(missing)

    # The user starts detection and the one-click connect operation.
    assert facade.detect_wechat_data_roots_calls == []
    window.wechat_workspace._wechat_connect_button.click()
    assert facade.detect_wechat_data_roots_calls
    assert executor.operation is not None
    executor.operation(lambda _message: None)
    assert facade.setup_wechat_environment_calls
    assert facade.acquire_wechat_db_key_calls
    executor.succeed(connected)
    _drain(window)

    executor.operation()
    executor.succeed(facade._sessions)
    assert window.wechat_workspace.session_panel._sessions_ready is True
    assert window.wechat_workspace.session_panel._session_list.count() == 1


def test_wechat_workspace_auto_detection_keeps_saved_path_flow_when_key_missing(
    qt_app, sources
) -> None:
    """A valid saved path keeps the existing flow; no auto-detection."""
    module = _facade_module()
    status = module.WeChatConnectionStatus(
        available=False, data_found=True, db_key_available=False,
        runtime_available=True, message="等待微信登录", action_hint="",
    )
    facade = StubFacade(
        sources=sources,
        connection_status=status,
        sessions=[_session(module.ChatSource.WECHAT, "wx1", "测试会话1", 10)],
        data_roots=["D:/fictional_wechat"],
    )
    executor = _DeferredExecutor()
    window = _main_window(qt_app, facade, executor=executor)
    window.navigate_to_wechat()
    _drain(window)

    executor.operation()
    executor.succeed(status)

    assert facade.detect_wechat_data_roots_calls == []
    assert window.wechat_workspace._connection_task is None
    assert window.wechat_workspace._wechat_connect_button.isVisibleTo(window) is True
    assert not hasattr(window.wechat_workspace, "_wechat_setup_dialog")


def test_wechat_workspace_auto_detection_opens_choice_for_multiple_roots(
    qt_app, sources
) -> None:
    """Multiple candidates open the existing selection dialog."""
    module = _facade_module()
    status = module.WeChatConnectionStatus(
        available=False, data_found=False, db_key_available=False,
        runtime_available=False, message="未找到微信数据位置。", action_hint="",
    )
    facade = StubFacade(
        sources=sources,
        connection_status=status,
        data_roots=["D:/wechat_one", "D:/wechat_two"],
    )
    window = _main_window(qt_app, facade)
    window.navigate_to_wechat()
    _drain(window)

    assert facade.detect_wechat_data_roots_calls == []
    window.wechat_workspace._wechat_connect_button.click()
    assert facade.detect_wechat_data_roots_calls
    dialog = window.wechat_workspace._wechat_setup_dialog
    assert dialog is not None
    assert dialog._use_data_roots is True
    assert dialog._data_root_combo.count() == 2
    assert facade.setup_wechat_environment_calls == []
    assert facade.verify_wechat_database_calls == []
    assert window.wechat_workspace._wechat_connect_pending is True


def test_wechat_workspace_auto_detection_opens_manual_setup_when_no_candidates(
    qt_app, sources
) -> None:
    """No candidates open the existing manual setup dialog."""
    module = _facade_module()
    status = module.WeChatConnectionStatus(
        available=False, data_found=False, db_key_available=False,
        runtime_available=False, message="未找到微信数据位置。", action_hint="",
    )
    facade = StubFacade(
        sources=sources,
        connection_status=status,
        data_roots=[],
    )
    window = _main_window(qt_app, facade)
    window.navigate_to_wechat()
    _drain(window)

    assert facade.detect_wechat_data_roots_calls == []
    window.wechat_workspace._wechat_connect_button.click()
    assert facade.detect_wechat_data_roots_calls
    dialog = window.wechat_workspace._wechat_setup_dialog
    assert dialog is not None
    assert dialog._use_data_roots is False
    assert facade.setup_wechat_environment_calls == []

# ----------------------------------------------------------------
# GUI-5b: WeChat key/database verification fallback
# ----------------------------------------------------------------


def _wechat_unreadable_error():
    module = _facade_module()
    return module.FacadeError(
        code="wechat_database_unreadable",
        public_message=(
            "\u5f53\u524d\u5fae\u4fe1\u767b\u5f55\u4fe1\u606f\u65e0\u6cd5"
            "\u8bfb\u53d6\u6240\u9009\u6570\u636e\u5e93\uff0c\u8bf7\u786e\u8ba4"
            "\u6570\u636e\u4f4d\u7f6e\u662f\u5426\u5bf9\u5e94\u5f53\u524d"
            "\u767b\u5f55\u8d26\u53f7\uff0c\u6216\u91cd\u65b0\u83b7\u53d6"
            "\u5fae\u4fe1\u8fde\u63a5\u4fe1\u606f\u3002"
        ),
        source=module.ChatSource.WECHAT,
    )


def _wechat_connected_status():
    module = _facade_module()
    return module.WeChatConnectionStatus(
        available=True, data_found=True, db_key_available=True,
        runtime_available=True, message="\u5fae\u4fe1\u5df2\u8fde\u63a5",
        action_hint="",
    )


def _wechat_missing_status():
    module = _facade_module()
    return module.WeChatConnectionStatus(
        available=False, data_found=False, db_key_available=False,
        runtime_available=False,
        message="\u672a\u627e\u5230\u5fae\u4fe1\u6570\u636e\u4f4d\u7f6e\u3002",
        action_hint="",
    )


def _wechat_mismatch_facade(
    sources,
    *,
    verify_error,
    data_roots=("D:/fictional_wechat",),
):
    module = _facade_module()
    return StubFacade(
        sources=sources,
        connection_status=_wechat_missing_status(),
        connection_status_after_connect=_wechat_connected_status(),
        sessions=[
            _session(module.ChatSource.WECHAT, "wx1", "\u6d4b\u8bd5\u4f1a\u8bdd1", 10)
        ],
        data_roots=list(data_roots),
        verify_error=verify_error,
    )


def _run_wechat_verification(executor):
    """Run the queued verification, which raises for a mismatched database."""
    with pytest.raises(_facade_module().FacadeError):
        executor.operation()


def _drive_wechat_database_mismatch(
    qt_app,
    sources,
    *,
    data_roots=("D:/fictional_wechat",),
):
    """Run the one-click flow until the captured key fails verification."""
    facade = _wechat_mismatch_facade(
        sources,
        verify_error=_wechat_unreadable_error(),
        data_roots=data_roots,
    )
    executor = _DeferredExecutor()
    window = _main_window(qt_app, facade, executor=executor)
    window.navigate_to_wechat()
    _drain(window)

    executor.operation()
    executor.succeed(_wechat_missing_status())
    _drain(window)

    workspace = window.wechat_workspace
    workspace._wechat_connect_button.click()
    if len(data_roots) > 1:
        # Several candidates: the user picks one first, so the connect runs
        # from the setup dialog instead of the one-click auto path.
        workspace._wechat_setup_dialog.set_data_root(data_roots[0])
        workspace._save_wechat_environment_from_dialog()
        _drain(window)

    executor.operation(lambda _message: None)
    executor.succeed(_wechat_connected_status())
    _drain(window)

    _run_wechat_verification(executor)
    executor.fail(
        "wechat_database_unreadable",
        facade._verify_error.public_message,
    )
    _drain(window)
    return window, facade, executor


@pytest.mark.parametrize("code", ["query_failed", "unexpected_error"])
def test_wechat_session_load_failure_exits_reading_state_and_allows_restart(
    qt_app, sources, code,
) -> None:
    executor = _DeferredExecutor()
    facade = _wechat_mismatch_facade(sources, verify_error=None)
    workspace = _wechat_guide_module().WeChatWorkspace(facade, executor=executor)
    workspace._show_connection_status(_wechat_connected_status(), True)
    panel = workspace.session_panel
    assert panel._session_list.item(0).text() == "正在读取聊天数据..."

    executor.fail(code, "虚构会话读取失败，请重试。")

    assert panel._session_list.item(0).text() == "暂无会话\n连接数据源后，这里会显示聊天记录"
    assert not panel._sessions_ready
    assert not workspace._sessions_loaded
    assert not panel._analyze_button.isEnabled()
    assert workspace._status_label.toolTip() == "虚构会话读取失败，请重试。"
    assert getattr(workspace, "_wechat_setup_dialog", None) is None
    button = workspace._wechat_connect_button
    assert button.text() == "重新开始"
    assert button.isVisibleTo(workspace)
    assert button.isEnabled()
    assert not workspace._wechat_disconnect_button.isVisibleTo(workspace)

    button.click()
    assert executor.submission_count == 2
    assert panel._session_list.item(0).text() == "正在连接数据源..."


def test_wechat_workspace_verifies_the_database_before_listing_sessions(
    qt_app, sources
) -> None:
    """A: one auto-detected root keeps the existing connect chain."""
    module = _facade_module()
    connected = _wechat_connected_status()
    facade = _wechat_mismatch_facade(sources, verify_error=None)
    order: list[str] = []
    verify = facade.verify_wechat_database
    list_sessions = facade.list_sessions

    def verify_spy():
        order.append("verify")
        return verify()

    def list_sessions_spy(source):
        order.append("list_sessions")
        return list_sessions(source)

    facade.verify_wechat_database = verify_spy
    facade.list_sessions = list_sessions_spy

    executor = _DeferredExecutor()
    window = _main_window(qt_app, facade, executor=executor)
    window.navigate_to_wechat()
    _drain(window)

    executor.operation()
    executor.succeed(_wechat_missing_status())
    _drain(window)

    assert facade.detect_wechat_data_roots_calls == []
    window.wechat_workspace._wechat_connect_button.click()
    assert facade.detect_wechat_data_roots_calls
    executor.operation(lambda _message: None)
    assert facade.setup_wechat_environment_calls
    assert facade.acquire_wechat_db_key_calls
    executor.succeed(connected)
    _drain(window)

    executor.operation()
    executor.succeed(facade._sessions)
    _drain(window)

    assert order[:2] == ["verify", "list_sessions"]
    assert facade.verify_wechat_database_calls
    assert facade.list_sessions_calls == [module.ChatSource.WECHAT]
    assert window.wechat_workspace.session_panel._sessions_ready is True
    assert window.wechat_workspace.session_panel._session_list.item(0).text() == "测试会话1"


def test_wechat_workspace_mismatch_returns_to_directory_selection(
    qt_app, sources
) -> None:
    """B: a failed verification must not load sessions and must re-ask."""
    window, facade, executor = _drive_wechat_database_mismatch(qt_app, sources)
    workspace = window.wechat_workspace

    assert facade.verify_wechat_database_calls, "verification must run first"
    assert facade.list_sessions_calls == []
    assert workspace._sessions_loaded is False
    assert workspace._wechat_setup_dialog is not None
    # A single detected candidate is offered as an editable field so the user
    # can also paste a directory Echo never detected.
    assert workspace._wechat_setup_dialog._use_data_roots is False
    assert workspace._wechat_connect_pending is True
    assert facade._verify_error.public_message in workspace._status_label.text()
    assert workspace._wechat_connect_button.text() == "\u91cd\u65b0\u5f00\u59cb"
    assert workspace._wechat_connect_button.isEnabled() is True
    assert workspace.session_panel._session_list.item(0).text() == "暂无会话\n连接数据源后，这里会显示聊天记录"
    assert not workspace.session_panel._sessions_ready


def test_wechat_workspace_reselected_root_reuses_the_captured_key(
    qt_app, sources
) -> None:
    """D: the new directory is retried with the key already in this process."""
    module = _facade_module()
    window, facade, executor = _drive_wechat_database_mismatch(qt_app, sources)
    workspace = window.wechat_workspace
    assert len(facade.acquire_wechat_db_key_calls) == 1

    workspace._wechat_setup_dialog.set_data_root("D:/other_wechat_root")
    facade._verify_error = None
    workspace._save_wechat_environment_from_dialog()
    _drain(window)

    executor.operation(lambda _message: None)
    assert facade.setup_wechat_environment_calls[-1].data_root == Path(
        "D:/other_wechat_root"
    )
    # Changing the directory must not require another WeChat login.
    assert len(facade.acquire_wechat_db_key_calls) == 1
    executor.succeed(_wechat_connected_status())
    _drain(window)

    executor.operation()
    executor.succeed(facade._sessions)
    _drain(window)

    assert facade.verify_wechat_database_calls
    assert facade.list_sessions_calls == [module.ChatSource.WECHAT]
    assert workspace.session_panel._sessions_ready is True


def test_wechat_workspace_second_mismatch_offers_another_choice(
    qt_app, sources
) -> None:
    """E: a still-unreadable directory stays actionable without auto retry."""
    window, facade, executor = _drive_wechat_database_mismatch(qt_app, sources)
    workspace = window.wechat_workspace
    verify_calls_before = len(facade.verify_wechat_database_calls)

    workspace._wechat_setup_dialog.set_data_root("D:/still_wrong_root")
    workspace._save_wechat_environment_from_dialog()
    _drain(window)
    executor.operation(lambda _message: None)
    executor.succeed(_wechat_connected_status())
    _drain(window)
    _run_wechat_verification(executor)
    executor.fail(
        "wechat_database_unreadable",
        facade._verify_error.public_message,
    )
    _drain(window)

    assert facade.list_sessions_calls == []
    # One user action equals one verification: no automatic retry loop.
    assert len(facade.verify_wechat_database_calls) - verify_calls_before == 1
    assert workspace._wechat_setup_dialog is not None
    assert facade._verify_error.public_message in workspace._status_label.text()
    assert workspace._wechat_connect_pending is True
    assert workspace._wechat_connect_button.isEnabled() is True


def test_wechat_workspace_mismatch_offers_every_detected_candidate(
    qt_app, sources
) -> None:
    """C/E: several candidates stay selectable when verification fails."""
    module = _facade_module()
    window, facade, executor = _drive_wechat_database_mismatch(
        qt_app,
        sources,
        data_roots=("D:/fictional_wechat_a", "D:/fictional_wechat_b"),
    )
    workspace = window.wechat_workspace
    dialog = workspace._wechat_setup_dialog

    assert dialog is not None
    assert dialog._use_data_roots is True
    # The reused window keeps every detected candidate selectable; the dialog
    # lists them as combo entries.
    candidates = {
        Path(dialog._data_root_combo.itemText(index)).name
        for index in range(dialog._data_root_combo.count())
    }
    assert {"fictional_wechat_a", "fictional_wechat_b"} <= candidates
    assert facade.list_sessions_calls == []

    # Picking the other detected candidate still reuses the captured key.
    facade._verify_error = None
    dialog._data_root_combo.setCurrentIndex(1)
    workspace._save_wechat_environment_from_dialog()
    _drain(window)

    executor.operation(lambda _message: None)
    assert facade.setup_wechat_environment_calls[-1].data_root == Path(
        "D:/fictional_wechat_b"
    )
    assert len(facade.acquire_wechat_db_key_calls) == 1
    executor.succeed(_wechat_connected_status())
    _drain(window)

    executor.operation()
    executor.succeed(facade._sessions)
    _drain(window)

    assert facade.list_sessions_calls == [module.ChatSource.WECHAT]
    assert workspace.session_panel._sessions_ready is True


def test_wechat_workspace_mismatch_message_exposes_no_internal_details(
    qt_app, sources
) -> None:
    """F: the recovery text stays actionable without internal details."""
    window, facade, executor = _drive_wechat_database_mismatch(qt_app, sources)
    workspace = window.wechat_workspace
    status_label = workspace._status_label

    visible = status_label.text() + "\n" + status_label.toolTip()
    assert "\u5f53\u524d\u5fae\u4fe1\u767b\u5f55\u4fe1\u606f" in visible
    assert "a" * 64 not in visible
    assert "session.db" not in visible
    assert "SELECT" not in visible
    assert ".db_storage" not in visible
    assert "D:/fictional_wechat" not in visible
    assert "wcdb" not in visible.lower()

# ---------------------------------------------------------------
# GUI-6: Local Data page
# ---------------------------------------------------------------

def _gui_report_summary(package_name, source="wechat", session_name="测试会话",
                        analysis_scope="all", scope_start=None, scope_end=None):
    from qq_chat_analyzer.application.report_package_catalog import ReportPackageSummary
    from qq_chat_analyzer.application.scope_filter import AnalysisScope, AnalysisScopeMode
    return ReportPackageSummary(package_name, datetime(2026, 8, 1, tzinfo=timezone.utc),
                                source, session_name, 42,
                                AnalysisScope(AnalysisScopeMode(analysis_scope), scope_start, scope_end))


def test_local_data_history_scope_uses_user_facing_labels(
    qt_app,
    sources,
) -> None:
    facade = StubFacade(
        sources=sources,
        reports=[
            _gui_report_summary("h-all", analysis_scope="all"),
            _gui_report_summary("h-real-six", analysis_scope="last_six_months"),
            _gui_report_summary("h-year", analysis_scope="last_year"),
            _gui_report_summary(
                "h-custom",
                analysis_scope="custom",
                scope_start=datetime(2026, 1, 1).date(),
                scope_end=datetime(2026, 6, 30).date(),
            ),
        ],
    )
    window = _main_window(qt_app, facade)
    window.show_local_data_page()
    _drain(window)

    table = window.local_data_page._history_list
    assert table.count() == 4
    from PySide6.QtWidgets import QLabel
    scopes = [table.itemWidget(table.item(row)).findChild(QLabel, "archiveEntryScope").text().removeprefix("分析范围：")
              for row in range(table.count())]
    assert scopes == [
        "全部消息",
        "最近六个月",
        "最近一年",
        "2026-01-01 至 2026-06-30",
    ]


def test_local_data_delete_entry_is_visible_in_browse_mode(qt_app, sources) -> None:
    window = _main_window(qt_app, StubFacade(sources=sources))
    window.show_local_data_page()
    _drain(window)

    assert window.local_data_page._enter_delete_button.isVisibleTo(window) is True
    assert window.local_data_page._delete_checked_button.isVisibleTo(window) is False


def _search_window(qt_app, sources):
    first = _gui_report_summary(
        "Echo_Report_20261004_120000", source="qq", session_name="虚构读书群 Straße",
        analysis_scope="last_six_months",
    )
    second = _gui_report_summary(
        "Echo_Report_20261004_120000_2", source="wechat", session_name="Fictional Alice",
        analysis_scope="custom", scope_start=date(2026, 1, 1), scope_end=date(2026, 6, 30),
    )
    records = [dataclasses.replace(r, conversation_kind=kind)
               for r, kind in ((first, "group"), (second, "private"))]
    from qq_chat_analyzer.application.report_package_catalog import ReportPackageIssue
    facade = StubFacade(sources=sources, reports=records)
    facade._report_issues = (ReportPackageIssue("Echo_Report_20261003_120000", "metadata_unreadable"),)
    window = _main_window(qt_app, facade)
    window.show_local_data_page()
    _drain(window)
    return window, facade, records


@pytest.mark.parametrize("query, indexes", [
    ("  读书  ", [0]), ("fIcTiOnAl aLiCe", [1]), ("STRASSE", [0]),
    ("qq", [0]), ("微信", [1]), ("群聊", [0]), ("私聊", [1]),
    ("2026-08-01", [0, 1]), ("最近六个月", [0]), ("2026-01-01 至 2026-06-30", [1]),
    ("42", []), ("Echo_Report_", []), ("no match", []), ("   ", [0, 1]),
])
def test_local_data_search_matches_only_summary_display_fields(qt_app, sources, query, indexes):
    window, facade, records = _search_window(qt_app, sources)
    page = window.local_data_page
    page._search_input.setText(query)
    table = page._history_list
    assert [table.item(row).data(Qt.ItemDataRole.UserRole) for row in range(table.count())] == [
        records[index].package_name for index in indexes
    ]
    assert page._issues_label.isVisibleTo(window)
    assert page._issues_label.text() == "发现 1 个无法读取的 Echo 报告"
    if not indexes:
        assert page._history_empty_label.isVisibleTo(window)
        assert page._history_empty_label.text() == "没有匹配的报告"


def test_local_data_search_clear_restores_rows_without_storage_calls(qt_app, sources, monkeypatch):
    window, facade, records = _search_window(qt_app, sources)
    page = window.local_data_page
    calls = list(facade.list_report_packages_calls)
    def forbidden(*args, **kwargs):
        pytest.fail("Typing a search must use only loaded summaries")
    monkeypatch.setattr(facade, "list_report_packages", forbidden)
    monkeypatch.setattr(facade, "get_report_storage_usage", forbidden)
    monkeypatch.setattr(facade, "get_report_package_html_path", forbidden, raising=False)
    monkeypatch.setattr(facade, "clear_report_packages", forbidden)
    monkeypatch.setattr(page, "_executor", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "iterdir", forbidden)
    for text in ("读书", "alice", "not found", ""):
        page._search_input.setText(text)
    assert page._history_list.count() == 2
    assert not page._history_empty_label.isVisibleTo(window)
    assert facade.list_report_packages_calls == calls


def test_local_data_search_refresh_and_delete_preserve_query(qt_app, sources):
    window, facade, records = _search_window(qt_app, sources)
    page = window.local_data_page
    page._search_input.setText("alice")
    facade._reports = [records[0]]
    page.refresh()
    assert page._search_input.text() == "alice"
    assert page._history_list.count() == 0
    assert page._history_empty_label.text() == "没有匹配的报告"
    facade._reports = records
    page.refresh()
    assert page._history_list.count() == 1
    page._enter_delete_button.click()
    page._select_results_button.click()
    page._confirm_delete_reports = lambda names, kept: True
    page._delete_checked_button.click()
    assert page._search_input.text() == "alice"
    assert page._history_list.count() == 0
    assert page._history_empty_label.text() == "没有匹配的报告"
    assert page._history_empty_label.isVisibleTo(window)
    assert page._issues_label.isVisibleTo(window)
    page._search_input.clear()
    assert page._history_list.count() == 1


def test_local_data_search_pending_refresh_uses_latest_query(qt_app, sources):
    window, facade, records = _search_window(qt_app, sources)
    page = window.local_data_page
    executor = _DeferredExecutor()
    page._executor = executor
    page._search_input.setText("读书")
    page.refresh()
    page._search_input.setText("alice")
    executor.succeed(executor.operation())
    assert executor.submission_count == 1
    assert page._search_input.text() == "alice"
    assert page._history_list.count() == 1
    assert page._history_list.item(0).data(Qt.ItemDataRole.UserRole) == records[1].package_name


@pytest.mark.parametrize("action", ["button", "double_click"])
def test_local_data_search_reopen_keeps_identity_and_invalidates_selection(qt_app, sources, tmp_path, action):
    window, facade, records = _search_window(qt_app, sources)
    page = window.local_data_page
    resolved, opened = [], []
    html = tmp_path / "fictional.html"
    facade.get_report_package_html_path = lambda name: resolved.append(name) or html
    window._report_opener = lambda path: opened.append(path) or True
    page._history_list.setCurrentRow(0)
    assert page._open_report_button.isEnabled()
    page._search_input.setText("alice")
    assert not page._open_report_button.isEnabled()
    page._history_list.setCurrentRow(0)
    if action == "button":
        page._open_report_button.click()
    else:
        page._history_list.itemDoubleClicked.emit(page._history_list.item(0))
    assert resolved == [records[1].package_name]
    assert opened == [html]
    page._search_input.setText("absent")
    assert not page._open_report_button.isEnabled()
    page.refresh()
    assert page._search_input.text() == "absent"
    assert not page._open_report_button.isEnabled()


def test_local_data_page_exposes_history_without_retired_snapshot_controls(
    qt_app, sources,
) -> None:
    from PySide6.QtWidgets import QGroupBox, QLabel, QPushButton, QListWidget

    facade = StubFacade(sources=sources, reports=[_gui_report_summary("h1")])
    window = _main_window(qt_app, facade)
    window.show_local_data_page()
    _drain(window)
    page = window.local_data_page

    assert page.findChildren(QGroupBox) == []
    assert {button.text() for button in page.findChildren(QPushButton)} == {
        "刷新", "打开报告", "删除报告", "删除所选", "全选当前结果", "清空勾选", "取消",
        "保留所选，删除其余",
    }
    assert all("快照" not in label.text() for label in page.findChildren(QLabel))
    assert len(page.findChildren(QListWidget)) == 1
    assert page._history_list.count() == 1


def _archive_window(qt_app, sources, reports=(), **kwargs):
    facade = StubFacade(sources=sources, reports=list(reports), **kwargs)
    window = _main_window(qt_app, facade)
    window.show_local_data_page()
    _drain(window)
    return window, facade


def test_local_data_page_shows_archive_heading_and_storage_summary(
    qt_app, sources,
) -> None:
    from PySide6.QtWidgets import QLabel
    from qq_chat_analyzer.application.report_package_catalog import ReportStorageUsage

    window, _facade = _archive_window(
        qt_app,
        sources,
        reports=[_gui_report_summary("h1"), _gui_report_summary("h2")],
        report_usage=ReportStorageUsage(2, 12_975_513),
    )
    page = window.local_data_page

    assert page.findChild(QLabel, "localDataTitle").text() == "Echo 历史"
    assert page.findChild(QLabel, "localDataDescription") is None
    assert not page.findChildren(QLabel, "localDataMetricCaption")
    assert page._summary_count_label.parent() is page._search_input.parent()
    assert page._summary_count_label.text() == "2 份"
    assert page._summary_size_label.text() == "12.4 MB"
    assert page._summary_note_label.isVisibleTo(window) is False


def test_local_data_page_empty_archive_state(qt_app, sources) -> None:
    window, _facade = _archive_window(qt_app, sources)
    page = window.local_data_page

    assert page._history_list.isVisibleTo(window) is False
    assert page._history_empty_label.isVisibleTo(window) is True
    assert page._history_empty_label.text() == "暂无报告"
    assert page._history_empty_detail_label.isVisibleTo(window) is True
    assert "报告会保存在本机" in page._history_empty_detail_label.text()
    assert page._summary_count_label.text() == "0 份"
    assert page._summary_size_label.text() == "0 B"


def test_local_data_page_search_without_matches_state(qt_app, sources) -> None:
    window, _facade = _archive_window(
        qt_app, sources, reports=[_gui_report_summary("h1")],
    )
    page = window.local_data_page
    page._search_input.setText("虚构关键词")

    assert page._history_list.isVisibleTo(window) is False
    assert page._history_empty_label.text() == "没有匹配的报告"
    assert page._history_empty_detail_label.text() == "换一个关键词试试，或清空搜索框。"
    assert page._summary_count_label.text() == "1 份"

    page._search_input.clear()
    assert page._history_empty_label.isVisibleTo(window) is False
    assert page._history_list.count() == 1


def test_local_data_page_marks_incomplete_storage_usage_as_lower_bound(
    qt_app, sources,
) -> None:
    from qq_chat_analyzer.application.report_package_catalog import ReportStorageUsage

    window, _facade = _archive_window(
        qt_app,
        sources,
        reports=[_gui_report_summary("h1"), _gui_report_summary("h2")],
        report_usage=ReportStorageUsage(4, 2_048, ("h3", "h4")),
    )
    page = window.local_data_page

    assert page._summary_count_label.text() == "4 份"
    assert page._summary_size_label.text() == "2.0 KB"
    assert page._summary_note_label.isVisibleTo(window) is True
    assert "已测量下界" in page._summary_note_label.text()
    assert "2 份" in page._summary_note_label.text()


def test_local_data_page_load_failure_state(qt_app, sources) -> None:
    module = _facade_module()
    facade = StubFacade(
        sources=sources,
        list_reports_error=module.FacadeError(
            "report_list_failed", "无法读取 Echo 本地报告，请稍后重试。",
        ),
    )
    window = _main_window(qt_app, facade)
    window.show_local_data_page()
    _drain(window)
    page = window.local_data_page

    assert page._status_label.isVisibleTo(window) is True
    assert page._status_label.text() == "无法读取 Echo 本地报告，请稍后重试。"
    assert page._summary_count_label.text() == "—"
    assert page._summary_size_label.text() == "—"
    assert page._history_empty_label.text() == "暂时无法读取本地报告"
    assert page._history_empty_detail_label.text() == "请稍后点击刷新重试。"
    assert page._refresh_button.isEnabled() is True


def test_local_data_page_keeps_last_known_archive_when_reload_fails(
    qt_app, sources,
) -> None:
    from qq_chat_analyzer.application.report_package_catalog import ReportStorageUsage

    module = _facade_module()
    window, facade = _archive_window(
        qt_app,
        sources,
        reports=[_gui_report_summary("h1")],
        report_usage=ReportStorageUsage(1, 4_096),
    )
    page = window.local_data_page
    facade._list_reports_error = module.FacadeError(
        "report_list_failed", "无法读取 Echo 本地报告，请稍后重试。",
    )
    page.refresh()

    assert page._status_label.text() == "无法读取 Echo 本地报告，请稍后重试。"
    assert page._history_list.count() == 1
    assert page._history_empty_label.isVisibleTo(window) is False
    assert page._summary_count_label.text() == "1 份"
    assert page._summary_size_label.text() == "4.0 KB"


def test_local_data_page_uses_one_report_scan_per_refresh(qt_app, sources) -> None:
    window, facade = _archive_window(
        qt_app, sources, reports=[_gui_report_summary("h1")],
    )
    page = window.local_data_page

    assert len(facade.list_report_packages_calls) == 1
    assert len(facade.get_report_storage_usage_calls) == 1

    page._search_input.setText("h1")
    assert len(facade.list_report_packages_calls) == 1
    assert len(facade.get_report_storage_usage_calls) == 1

    page.refresh()
    assert len(facade.list_report_packages_calls) == 2
    assert len(facade.get_report_storage_usage_calls) == 2


def test_local_data_page_ignores_stale_refresh_results(qt_app, sources) -> None:
    window, facade = _archive_window(
        qt_app, sources, reports=[_gui_report_summary("first")],
    )
    page = window.local_data_page
    executor = _QueuedExecutor()
    page._executor = executor

    facade._reports = [_gui_report_summary("second")]
    page.refresh()
    facade._reports = [_gui_report_summary("third")]
    page.refresh()
    assert len(executor.tasks) == 2

    # The newer load lands first ...
    executor.succeed(1)
    assert page._history_list.item(0).data(Qt.ItemDataRole.UserRole) == "third"
    # ... and the older result, which arrives last, must not overwrite it.
    facade._reports = [_gui_report_summary("second")]
    executor.succeed(0)
    assert page._history_list.count() == 1
    assert page._history_list.item(0).data(Qt.ItemDataRole.UserRole) == "third"
    assert page._refresh_button.isEnabled() is True


def test_local_data_page_keeps_list_when_storage_usage_fails(qt_app, sources) -> None:
    module = _facade_module()
    window, _facade = _archive_window(
        qt_app, sources, reports=[_gui_report_summary("h1")],
        report_usage_error=module.FacadeError(
            "report_usage_failed", "无法统计 Echo 本地报告占用空间，请稍后重试。",
        ),
    )
    page = window.local_data_page

    assert page._history_list.count() == 1
    assert page._history_list.isVisibleTo(window)
    assert page._summary_count_label.text() == "1 份"
    assert page._summary_size_label.text() == "—"
    assert page._summary_note_label.isVisibleTo(window)
    assert "无法统计" in page._summary_note_label.text()
    page._history_list.setCurrentRow(0)
    assert page._open_report_button.isEnabled()


def test_local_data_page_stale_error_and_finish_do_not_end_latest_refresh(
    qt_app, sources,
) -> None:
    window, _facade = _archive_window(
        qt_app, sources, reports=[_gui_report_summary("h1")],
    )
    page = window.local_data_page
    executor = _QueuedExecutor()
    page._executor = executor
    page.refresh()
    assert len(executor.tasks) == 1
    page.refresh()
    assert len(executor.tasks) == 2

    executor.fail(0, "report_list_failed", "过期的错误")
    assert "过期的错误" not in page._status_label.text()
    assert not page._refresh_button.isEnabled()
    executor.succeed(1)
    assert page._refresh_button.isEnabled()
    assert page._status_label.text() == ""
    assert page._history_list.count() == 1


def _reopen_window(qt_app, sources, tmp_path):
    names = ["Echo_Report_20261004_120000", "Echo_Report_20261004_120000_2"]
    facade = StubFacade(sources=sources, reports=[_gui_report_summary(name) for name in names])
    resolved = tmp_path / "facade-resolved.html"
    calls = []
    def resolve(name):
        calls.append(name)
        return resolved
    facade.get_report_package_html_path = resolve
    window = _main_window(qt_app, facade)
    opened = []
    window._report_opener = lambda path: opened.append(path) or True
    window.show_local_data_page()
    return window, facade, names, calls, opened, resolved


def test_local_data_reopen_identity_selection_and_refresh(qt_app, sources, tmp_path):
    window, facade, names, calls, opened, resolved = _reopen_window(qt_app, sources, tmp_path)
    page = window.local_data_page
    assert not page._open_report_button.isEnabled()
    for row, name in enumerate(names):
        assert page._history_list.item(row).data(Qt.ItemDataRole.UserRole) == name
    page._history_list.setCurrentRow(1)
    assert page._open_report_button.isEnabled()
    page._history_list.clearSelection()
    assert not page._open_report_button.isEnabled()
    page._history_list.setCurrentRow(1)
    # Same row count after refresh must not reuse an old selection for new records.
    facade._reports = [_gui_report_summary(names[0]), _gui_report_summary("Echo_Report_20261004_130000")]
    page.refresh()
    assert not page._open_report_button.isEnabled()
    facade._reports = []
    page.refresh()
    assert not page._open_report_button.isEnabled()
    assert calls == opened == []


def test_local_data_focus_frame_hidden_but_selection_remains_visible(qt_app, sources, tmp_path):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QStyle, QStyleFactory, QStyleOptionViewItem

    window, _, _, _, _, _ = _reopen_window(qt_app, sources, tmp_path)
    table = window.local_data_page._history_list
    # Use a deterministic native style and compare states, not a golden screenshot.
    style = QStyleFactory.create("Fusion")
    style.setParent(table)
    table.setStyle(style)
    table.ensurePolished()

    def draw(*, selected, focused):
        option = QStyleOptionViewItem()
        option.initFrom(table)
        option.rect = QRect(0, 0, 160, 32)
        option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Active
        if selected:
            option.state |= QStyle.StateFlag.State_Selected
        if focused:
            option.state |= QStyle.StateFlag.State_HasFocus
        option.showDecorationSelected = True
        image = QImage(160, 32, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        table.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, table)
        painter.end()
        return bytes(image.constBits())

    selected = draw(selected=True, focused=False)
    assert draw(selected=True, focused=True) == selected
    assert selected != draw(selected=False, focused=False)
    assert table.focusPolicy() != Qt.FocusPolicy.NoFocus


@pytest.mark.parametrize("selected", [False, True])
def test_local_data_hover_does_not_change_cell_background(qt_app, sources, tmp_path, selected):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QStyle, QStyleFactory, QStyleOptionViewItem
    from qq_chat_analyzer.gui.theme import BASE_QSS

    window, _, _, _, _, _ = _reopen_window(qt_app, sources, tmp_path)
    # Reproduce the production theme's item:hover rule without changing app state.
    window.setStyleSheet(BASE_QSS)
    table = window.local_data_page._history_list
    style = QStyleFactory.create("Fusion")
    style.setParent(table)
    table.setStyle(style)
    table.ensurePolished()

    def draw(*, selected, hovered):
        option = QStyleOptionViewItem()
        option.initFrom(table)
        option.rect = QRect(0, 0, 160, 32)
        option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Active
        if selected:
            option.state |= QStyle.StateFlag.State_Selected
        if hovered:
            option.state |= QStyle.StateFlag.State_MouseOver
        option.showDecorationSelected = True
        image = QImage(160, 32, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(table.palette().base().color())
        painter = QPainter(image)
        table.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, table)
        painter.end()
        return bytes(image.constBits())

    normal = draw(selected=selected, hovered=False)
    assert draw(selected=selected, hovered=True) == normal
    assert draw(selected=True, hovered=False) != draw(selected=False, hovered=False)


def test_local_data_mouse_selection_keyboard_navigation_and_reopen(qt_app, sources, tmp_path):
    window, facade, names, calls, opened, resolved = _reopen_window(qt_app, sources, tmp_path)
    window.show()
    _drain(window)
    page = window.local_data_page
    table = page._history_list
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton,
                     pos=table.visualItemRect(table.item(0)).center())
    assert table.hasFocus()
    assert page._selected_package_name() == names[0]
    assert len(table.selectedItems()) == 1
    QTest.keyClick(table, Qt.Key.Key_Down)
    assert page._selected_package_name() == names[1]
    assert page._open_report_button.isEnabled()
    page._open_report_button.click()
    assert calls == [names[1]] and opened == [resolved]
    QTest.keyClick(table, Qt.Key.Key_Up)
    assert page._selected_package_name() == names[0]


@pytest.mark.parametrize("action", ["button", "double_click"])
def test_local_data_reopen_resolves_identity_and_uses_existing_opener(qt_app, sources, tmp_path, action):
    window, facade, names, calls, opened, resolved = _reopen_window(qt_app, sources, tmp_path)
    page = window.local_data_page
    page._history_list.setCurrentRow(1)
    if action == "button":
        page._open_report_button.click()
    else:
        page._history_list.itemDoubleClicked.emit(page._history_list.item(1))
    assert calls == [names[1]]
    assert opened == [resolved]
    assert page._status_label.text() == ""
    assert page._history_list.count() == 2


def test_local_data_reopen_resolve_failure_preserves_rows(qt_app, sources, tmp_path):
    window, facade, names, calls, opened, resolved = _reopen_window(qt_app, sources, tmp_path)
    def fail(name):
        raise _facade_module().FacadeError("report_open_failed", "这份 Echo 报告已损坏或缺少报告文件。")
    facade.get_report_package_html_path = fail
    page = window.local_data_page
    page._history_list.setCurrentRow(0)
    page._open_report_button.click()
    assert page._status_label.text() == "这份 Echo 报告已损坏或缺少报告文件。"
    assert page._history_list.count() == 2
    assert opened == []
    assert page._open_report_button.isEnabled()


@pytest.mark.parametrize("raises", [False, True])
def test_local_data_reopen_opener_failure_is_visible(qt_app, sources, tmp_path, raises):
    window, facade, names, calls, opened, resolved = _reopen_window(qt_app, sources, tmp_path)
    def fail(path):
        if raises:
            raise OSError("internal-private-path")
        return False
    window._report_opener = fail
    page = window.local_data_page
    page._history_list.setCurrentRow(0)
    page._open_report_button.click()
    assert calls == [names[0]]
    assert page._status_label.text() == "无法打开 Echo 报告，请检查系统默认浏览器后重试。"
    assert page._history_list.count() == 2


def test_qq_connect_error_snapshot_keeps_workspace_usable(
    qt_app, sources, instant_qq_connect
) -> None:
    """An ERROR snapshot from the auth flow renders restart, never crashes."""
    from qq_chat_analyzer.gui.main_window import QQ_WORKSPACE_INDEX

    models = importlib.import_module(
        "qq_chat_analyzer.application.connection_models"
    )
    error_snapshot = models.ConnectionSnapshot(
        state=models.ConnectionState.ERROR,
        source="qq",
        message="QQ 连接异常。",
        action_hint="请重试",
    )
    facade = StubFacade(sources=sources)
    executor = _DeferredExecutor()
    window = _main_window(qt_app, facade, executor=executor)
    window.navigate_to_qq()
    _drain(window)

    executor.operation()
    executor.succeed(facade.get_qq_connection_snapshot())

    window.qq_workspace._qq_connect_button.click()
    executor.operation(lambda _message: None)
    assert facade.start_qq_auth_flow_calls == [1]
    executor.succeed(error_snapshot)
    _drain(window)

    assert window.qq_workspace._qq_connect_in_flight is False
    assert window.qq_workspace._qq_connect_button.text() == "重新开始"
    assert window.qq_workspace._status_label.text()
    assert window.stack.currentIndex() == QQ_WORKSPACE_INDEX


def test_waiting_auth_timeout_enters_error_state(qt_app, sources) -> None:
    module = importlib.import_module("qq_chat_analyzer.gui.qq_workspace")
    facade = _SnapshotFacade(_qq_snapshot("waiting_auth"), sources=sources)
    workspace = module.QQWorkspace(facade, executor=_inline_executor())

    workspace._show_qq_status(
        _qq_snapshot("waiting_auth"),
        load_sessions_on_ready=False,
    )
    assert workspace._qq_status_timer.isActive() is True

    workspace._qq_waiting_auth_since = module.time.monotonic() - 121
    workspace._poll_qq_status()

    assert workspace._qq_status_timer.isActive() is False
    assert "等待超时" in workspace._status_label.text()
    assert workspace._qq_connect_button.text() == "重新开始"
    assert workspace._qq_connect_button.isEnabled() is True



def test_qq_auth_timeout_calls_facade_disconnect(qt_app, sources):
    doc = 'RED: _handle_qq_auth_timeout must call facade.disconnect_qq(). Root cause: WAITING_AUTH reaches 120s timeout -> QQWorkspace only does UI cleanup -> underlying auth session / connection manager is NOT ended -> user clicks restart -> start_auth_flow may reuse old session / QR. After the fix, _handle_qq_auth_timeout() must call self._facade.disconnect_qq() to ensure the old auth session is truly terminated before the user can restart.'
    module = importlib.import_module('qq_chat_analyzer.gui.qq_workspace')
    facade = _SnapshotFacade(_qq_snapshot('waiting_auth'), sources=sources)
    workspace = module.QQWorkspace(facade, executor=_inline_executor())
    workspace._show_qq_status(
        _qq_snapshot('waiting_auth'),
        load_sessions_on_ready=False,
    )
    assert workspace._qq_status_timer.isActive() is True
    workspace._qq_waiting_auth_since = module.time.monotonic() - 121
    workspace._handle_qq_auth_timeout()
    assert workspace._qq_status_timer.isActive() is False
    assert workspace._qq_connect_button.text() == '\u91cd\u65b0\u5f00\u59cb'
    assert workspace._qq_connect_button.isEnabled() is True
    assert len(facade.disconnect_qq_calls) >= 1, (
        '_handle_qq_auth_timeout() must call facade.disconnect_qq() to '
        'terminate the underlying auth session. Without this call, the '
        'old WAITING_AUTH session is reused on restart.'
    )


# ---------------------------------------------------------------------------
# MainWindow terminal state + preserved behavior
# ---------------------------------------------------------------------------


def test_main_window_owns_its_status_label(qt_app, sources) -> None:
    window = _main_window(qt_app, StubFacade(sources=sources))

    assert hasattr(window, "_status_label")
    window.show_status("分析已取消。")
    assert window._status_label.text() == "分析已取消。"


def test_local_data_page_exposes_unreadable_package_count(qt_app, sources):
    from qq_chat_analyzer.application.report_package_catalog import ReportPackageIssue
    facade = StubFacade(sources=sources, report_issues=[ReportPackageIssue("Echo_Report_20261004_120000", "metadata_unreadable")])
    window = _main_window(qt_app, facade)
    window.show_local_data_page()
    _drain(window)
    assert window.local_data_page._issues_label.text() == "发现 1 个无法读取的 Echo 报告"
    assert window.local_data_page._issues_label.isVisibleTo(window)


# ---------------------------------------------------------------------------
# WeChat workspace guide coverage
# ---------------------------------------------------------------------------


def _wechat_guide_module():
    return importlib.import_module("qq_chat_analyzer.gui.wechat_workspace")


def _wechat_workspace(qt_app, facade):
    from qq_chat_analyzer.gui.wechat_workspace import WeChatWorkspace

    return WeChatWorkspace(facade, executor=_inline_executor())


def test_wechat_login_prompt_waits_for_structured_ready(qt_app):
    module = _wechat_guide_module()
    executor = _DeferredExecutor()
    workspace = module.WeChatWorkspace(StubFacade(), executor=executor)
    workspace._start_wechat_connect(_facade_module().WeChatEnvironmentConfig())

    assert workspace._status_label.text() == "正在准备微信连接"
    for text in ("等待微信登录", "现在可以登录微信", "hook_success=true"):
        executor.on_progress(text)
        assert workspace._status_label.text() == "正在准备微信连接"
        assert "现在可以登录微信" not in workspace._wechat_guide_label.text()

    progress = _facade_module().WeChatConnectionProgress
    executor.on_progress(progress.READY_FOR_LOGIN)
    assert "现在可以登录微信" in workspace._status_label.text()
    assert "现在可以登录微信" in workspace._wechat_guide_label.text()


def test_wechat_login_words_are_not_readiness_signals(qt_app):
    workspace = _wechat_workspace(qt_app, StubFacade())
    workspace._status_label.setText("正在准备连接，请暂时不要登录。")
    before = workspace._status_label.text()

    workspace._handle_wechat_connect_progress("正在准备微信登录监听")

    assert workspace._status_label.text() == before


def _wechat_connection_config():
    return _facade_module().WeChatEnvironmentConfig()


def _wechat_unavailable_status():
    return SimpleNamespace(available=False, data_found=True, action_hint="")


@pytest.mark.parametrize("data_found", [False, True])
def test_wechat_polish_initial_waits_for_user(qt_app, data_found, monkeypatch):
    from PySide6.QtWidgets import QLabel

    facade = StubFacade(data_roots=["D:/fictional_wechat"])
    workspace = _wechat_guide_module().WeChatWorkspace(
        facade, executor=_IndependentDeferredExecutor(),
    )
    monkeypatch.setattr(workspace, "_refresh_wechat_guide_image",
                        lambda: workspace._wechat_guide_image_label.show())
    workspace.show()
    workspace.refresh_connection_status(load_sessions_on_ready=True)
    assert workspace._status_label.text() == "微信未连接"
    assert workspace._wechat_guide_image_label.isHidden()
    assert workspace._connection_task is None
    workspace._show_connection_status(SimpleNamespace(
        available=False, data_found=data_found, runtime_available=True,
        db_key_available=False, action_hint="",
    ), True)
    assert workspace._status_label.text() == "微信未连接"
    assert workspace._wechat_guide_label.text() == "连接微信"
    assert workspace._wechat_guide_note_label.text() == (
        "点击“连接微信”后，Echo 会一步一步提示你完成连接。"
    )
    assert workspace._wechat_guide_key_label.text() == (
        "聊天数据仅在本机读取，不上传、不保存额外副本。"
    )
    for label in (workspace._status_label, workspace._wechat_guide_label,
                  workspace._wechat_guide_note_label, workspace._wechat_guide_key_label):
        assert label.isVisibleTo(workspace)
    assert workspace._wechat_connect_button.text() == "连接微信"
    assert workspace._wechat_connect_button.isEnabled()
    assert workspace._wechat_setup_button.isVisibleTo(workspace)
    assert workspace._wechat_guide_image_label.isHidden()
    assert facade.detect_wechat_data_roots_calls == []
    assert workspace._connection_task is None
    visible = "\n".join(label.text() for label in workspace.findChildren(QLabel)
                        if label.isVisibleTo(workspace))
    for forbidden in ("等待微信登录", "准备微信连接", "请完全关闭微信",
                      "现在请打开微信", "现在可以登录微信", "等待 Echo 提示"):
        assert forbidden not in visible
    workspace._wechat_setup_button.click()
    assert workspace._wechat_setup_dialog.isVisible()
    workspace._wechat_setup_dialog.reject()
    workspace.close()
    workspace.deleteLater()
    from PySide6.QtCore import QEvent
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("state, status, action, explanation", [
    ("PREPARING", "正在准备微信连接", "正在检查微信连接状态，请稍候。",
     "暂时不需要操作微信，Echo 检查完成后会告诉你下一步怎么做。"),
    ("WAITING_FOR_WECHAT_EXIT", "请完全关闭微信", "请完全关闭微信。",
     "关闭微信窗口后，如果微信仍在后台运行，\n请在任务栏右下角找到微信图标并完全关闭微信。\n\n完全关闭后不用点击 Echo 中的任何按钮，Echo 会自动继续。"),
    ("WAITING_FOR_WECHAT_START", "现在请打开微信", "现在请打开微信，但先不要登录。",
     "打开微信后，请停留在登录界面。\n如果看到“进入微信”或登录按钮，先不要点击。\n\nEcho 检测到微信后，会自动告诉你什么时候可以登录。\n不需要返回 Echo 点击下一步。"),
    ("READY_FOR_LOGIN", "现在可以登录微信了", "现在可以登录微信。",
     "请按照右侧示意图，在微信中点击“进入微信”完成登录。"),
    ("CREDENTIAL_RECEIVED", "正在连接微信", "已获取微信连接信息，正在继续连接……",
     "请稍候，无需操作。"),
])
def test_wechat_polish_current_action(qt_app, monkeypatch, state, status, action, explanation):
    from qq_chat_analyzer.gui.theme import WECHAT_GUIDE_STYLE as GUIDE_STYLE

    executor = _IndependentDeferredExecutor()
    workspace = _wechat_guide_module().WeChatWorkspace(StubFacade(), executor=executor)
    monkeypatch.setattr(workspace, "_refresh_wechat_guide_image",
                        lambda: workspace._wechat_guide_image_label.show())
    workspace.show()
    workspace._start_wechat_connect(_wechat_connection_config())
    task = executor.tasks[0]
    if state == "CREDENTIAL_RECEIVED":
        task.progress(_facade_module().WeChatConnectionProgress.READY_FOR_LOGIN)
        assert not workspace._wechat_guide_image_label.isHidden()
    task.progress(getattr(_facade_module().WeChatConnectionProgress, state))
    assert workspace._status_label.text() == status
    assert workspace._wechat_guide_label.text() == action
    assert workspace._wechat_guide_note_label.text() == explanation
    assert workspace._wechat_guide_note_label.styleSheet() == GUIDE_STYLE
    # The guided stages carry progress on the five-stage trail instead of
    # repeating the privacy line under every step.
    assert workspace._wechat_guide_key_label.isHidden()
    assert workspace._progress_track.isVisibleTo(workspace)
    assert workspace._wechat_guide_image_label.isHidden() == (state != "READY_FOR_LOGIN")
    assert workspace._wechat_connect_button.text() == "取消连接"
    for label in (workspace._wechat_guide_label, workspace._wechat_guide_note_label):
        assert label.isVisibleTo(workspace)
    workspace.close()
    workspace.deleteLater()
    from PySide6.QtCore import QEvent
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_wechat_setup_track_moves_through_five_stages(qt_app):
    """The two states trade places: trail during a stage, status otherwise."""
    from PySide6.QtWidgets import QProgressBar

    module = _wechat_guide_module()
    progress = _facade_module().WeChatConnectionProgress
    executor = _IndependentDeferredExecutor()
    workspace = module.WeChatWorkspace(StubFacade(), executor=executor)
    workspace.show()
    try:
        assert module._WECHAT_STAGES == ("准备", "关闭微信", "打开微信", "登录", "连接")
        assert workspace._progress_track.isHidden()
        assert workspace._status_label.isVisibleTo(workspace)

        workspace._start_wechat_connect(_wechat_connection_config())
        task = executor.tasks[0]
        for state, stage in (
            (progress.PREPARING, 0),
            (progress.WAITING_FOR_WECHAT_EXIT, 1),
            (progress.WAITING_FOR_WECHAT_START, 2),
            (progress.READY_FOR_LOGIN, 3),
            (progress.CREDENTIAL_RECEIVED, 4),
        ):
            task.progress(state)
            assert workspace._progress_track.isVisibleTo(workspace)
            assert workspace._progress_track.stage == stage
            assert workspace._status_label.isHidden()

        # Reading the database is still the final stage, not a status line.
        task.progress(module._WECHAT_READING_DATABASE)
        assert workspace._progress_track.isVisibleTo(workspace)
        assert workspace._progress_track.stage == 4
        assert module._WECHAT_READING_DATABASE == workspace._status_label.text()

        # No traditional progress bar: this is a five-step trail.
        assert workspace.findChild(QProgressBar) is None
    finally:
        workspace.close()


def test_wechat_login_stage_points_at_the_guide_image(qt_app, monkeypatch):
    module = _wechat_guide_module()
    progress = _facade_module().WeChatConnectionProgress
    executor = _IndependentDeferredExecutor()
    workspace = module.WeChatWorkspace(StubFacade(), executor=executor)
    monkeypatch.setattr(workspace, "_refresh_wechat_guide_image",
                        lambda: workspace._wechat_guide_image_label.show())
    workspace.show()
    try:
        workspace._handle_wechat_connect_progress(progress.READY_FOR_LOGIN)

        assert workspace._wechat_guide_label.text() == "现在可以登录微信。"
        assert workspace._wechat_guide_note_label.text() == (
            "请按照右侧示意图，在微信中点击“进入微信”完成登录。"
        )
        assert workspace._wechat_guide_image_label.isVisibleTo(workspace) is True
        assert workspace._progress_track.stage == 3
    finally:
        workspace.close()


@pytest.mark.parametrize("state, instruction", [
    ("PREPARING", "正在检查微信连接状态，请稍候。"),
    ("WAITING_FOR_WECHAT_EXIT", "请完全关闭微信。"),
    ("WAITING_FOR_WECHAT_START", "现在请打开微信，但先不要登录。"),
    ("READY_FOR_LOGIN", "现在可以登录微信。"),
])
def test_wechat_happy_path_shows_only_current_step(qt_app, monkeypatch, state, instruction):
    from PySide6.QtWidgets import QLabel

    module = _wechat_guide_module()
    executor = _IndependentDeferredExecutor()
    workspace = module.WeChatWorkspace(
        StubFacade(data_roots=["D:/fictional_wechat"]), executor=executor,
    )
    monkeypatch.setattr(workspace, "_refresh_wechat_guide_image",
                        lambda: workspace._wechat_guide_image_label.show())
    workspace.show()
    workspace._wechat_connect_button.setVisible(True)
    workspace._wechat_connect_button.click()
    assert not hasattr(workspace, "_wechat_setup_dialog")
    task = executor.tasks[0]
    # The initial presentation must already be a single step before callbacks.
    assert not workspace._progress_track.isHidden()
    assert workspace._wechat_guide_key_label.isHidden()
    task.progress(getattr(_facade_module().WeChatConnectionProgress, state))

    progress = getattr(_facade_module().WeChatConnectionProgress, state)
    assert workspace._status_label.text() == module._WECHAT_PROGRESS_STATUS[progress]
    assert workspace._wechat_guide_label.text() == instruction
    assert workspace._wechat_guide_note_label.isVisibleTo(workspace)
    assert workspace._wechat_guide_note_label.text() == (
        module._WECHAT_PROGRESS_EXPLANATIONS[progress]
    )
    assert not workspace._wechat_guide_label.isHidden()
    assert workspace._wechat_guide_key_label.isHidden()
    assert workspace._progress_track.isVisibleTo(workspace)
    assert workspace._wechat_guide_image_label.isHidden() == (state != "READY_FOR_LOGIN")
    visible_text = "\n".join(
        label.text() for label in workspace.findChildren(QLabel)
        if label.isVisibleTo(workspace)
    )
    assert module._WECHAT_GUIDE_DIRECTORY_NOTE not in visible_text
    assert "1. 进入微信" not in visible_text
    assert "7. 等待 Echo" not in visible_text
    assert "Save" not in visible_text


@pytest.mark.parametrize("code", ["wechat_key_timeout", "wechat_environment_missing"])
def test_wechat_happy_path_error_keeps_retry_and_setup(qt_app, code):
    module = _wechat_guide_module()
    executor = _IndependentDeferredExecutor()
    workspace = module.WeChatWorkspace(
        StubFacade(data_roots=["D:/fictional_wechat"]), executor=executor,
    )
    workspace.show()
    workspace.connect_wechat()
    first = executor.tasks[0]
    first.progress(_facade_module().WeChatConnectionProgress.READY_FOR_LOGIN)
    first.fail(code, "虚构连接失败，请重试。")
    first.finish()
    assert workspace._wechat_connect_button.isVisibleTo(workspace)
    assert workspace._wechat_connect_button.isEnabled()
    assert workspace._wechat_connect_button.text() == module._RESTART_CONNECTION_LABEL
    assert workspace._status_label.toolTip() == "虚构连接失败，请重试。"
    assert workspace._wechat_guide_note_label.isHidden()
    workspace.open_wechat_setup()
    assert workspace._wechat_setup_dialog.isVisible()
    workspace._wechat_setup_dialog.reject()
    workspace._wechat_connect_button.click()
    assert len(executor.tasks) == 2
    assert workspace._status_label.text() == module._WECHAT_CONNECTING
    assert workspace._progress_track.isVisibleTo(workspace)
    assert workspace._wechat_guide_key_label.isHidden()


def test_wechat_happy_path_directory_fallback_remains_reachable(qt_app, monkeypatch):
    module = _wechat_guide_module()
    executor = _IndependentDeferredExecutor()
    facade = StubFacade(data_roots=["D:/fictional_wechat"])
    workspace = module.WeChatWorkspace(facade, executor=executor)
    monkeypatch.setattr(workspace, "_refresh_wechat_guide_image",
                        lambda: workspace._wechat_guide_image_label.show())
    workspace.show()
    workspace.connect_wechat()
    executor.tasks[0].progress(_facade_module().WeChatConnectionProgress.READY_FOR_LOGIN)
    workspace.cancel_connection()
    workspace.connect_wechat(detect_data_roots=lambda: [])

    assert workspace._wechat_setup_dialog.isVisible()
    assert workspace._wechat_guide_label.isVisibleTo(workspace)
    assert workspace._wechat_guide_label.text() == module._WECHAT_GUIDE_DIRECTORY_MISSING
    assert workspace._wechat_guide_note_label.text() == module._WECHAT_GUIDE_DIRECTORY_NOTE
    assert workspace._wechat_guide_note_label.isVisibleTo(workspace)
    assert workspace._wechat_guide_image_label.isHidden()
    workspace._show_wechat_guide(include_directory_help=True, current_step_only=True)
    assert workspace._wechat_guide_note_label.text() == module._WECHAT_GUIDE_DIRECTORY_NOTE
    assert not workspace._wechat_guide_label.isHidden()


@pytest.mark.parametrize("state, instruction", [
    ("PREPARING", "正在准备微信连接"),
    ("WAITING_FOR_WECHAT_EXIT", "请完全关闭微信"),
    ("WAITING_FOR_WECHAT_START", "现在请打开微信，先不要登录"),
    ("READY_FOR_LOGIN", "现在可以登录微信"),
])
def test_wechat_guided_setup_state_instruction(qt_app, state, instruction):
    executor = _DeferredExecutor()
    workspace = _wechat_guide_module().WeChatWorkspace(StubFacade(), executor=executor)
    workspace._start_wechat_connect(_wechat_connection_config())

    executor.progress(getattr(_facade_module().WeChatConnectionProgress, state))

    state_progress = getattr(_facade_module().WeChatConnectionProgress, state)
    assert workspace._status_label.text() == _wechat_guide_module()._WECHAT_PROGRESS_STATUS[state_progress]
    assert workspace._wechat_guide_label.text() == _wechat_guide_module()._WECHAT_PROGRESS_INSTRUCTIONS[state_progress]
    assert not workspace._wechat_guide_note_label.isHidden()


def test_wechat_guided_setup_exit_start_ready_sequence(qt_app):
    executor = _DeferredExecutor()
    workspace = _wechat_guide_module().WeChatWorkspace(StubFacade(), executor=executor)
    workspace._start_wechat_connect(_wechat_connection_config())
    emitted = []
    workspace.status_changed.connect(emitted.append)
    progress = _facade_module().WeChatConnectionProgress

    for state, instruction in (
        (progress.WAITING_FOR_WECHAT_EXIT, "请完全关闭微信"),
        (progress.WAITING_FOR_WECHAT_START, "现在请打开微信，但先不要登录"),
        (progress.READY_FOR_LOGIN, "现在可以登录微信"),
    ):
        executor.progress(state)
        assert workspace._status_label.text() == _wechat_guide_module()._WECHAT_PROGRESS_STATUS[state]
        assert instruction in workspace._wechat_guide_label.text()
        assert emitted[-1] == workspace._status_label.text()
        if state is not progress.READY_FOR_LOGIN:
            assert "现在可以登录微信" not in workspace._wechat_guide_label.text()
            before = workspace._status_label.text()
            executor.progress("现在可以登录微信")
            assert workspace._status_label.text() == before
    assert len(emitted) == 3


@pytest.mark.parametrize("state", ["WAITING_FOR_WECHAT_EXIT", "WAITING_FOR_WECHAT_START"])
def test_wechat_guided_setup_stale_exit_start_isolation(qt_app, state):
    executor = _IndependentDeferredExecutor()
    workspace = _wechat_guide_module().WeChatWorkspace(StubFacade(), executor=executor)
    workspace._start_wechat_connect(_wechat_connection_config())
    first = executor.tasks[0]
    workspace.cancel_connection()
    workspace._start_wechat_connect(_wechat_connection_config())
    second = executor.tasks[1]
    progress = _facade_module().WeChatConnectionProgress
    second.progress(progress.READY_FOR_LOGIN)
    before = (workspace._status_label.text(), workspace._wechat_guide_label.text(),
              workspace._wechat_guide_note_label.text(),
              workspace._wechat_guide_image_label.isHidden())
    emitted = []
    workspace.status_changed.connect(emitted.append)

    first.progress(getattr(progress, state))

    assert before == (workspace._status_label.text(), workspace._wechat_guide_label.text(),
                      workspace._wechat_guide_note_label.text(),
                      workspace._wechat_guide_image_label.isHidden())
    assert workspace._wechat_login_progress is progress.READY_FOR_LOGIN
    assert workspace._connection_task is second
    assert emitted == []


def test_wechat_guided_setup_credential_continues_existing_flow(qt_app, monkeypatch):
    module = _wechat_guide_module()
    executor = _IndependentDeferredExecutor()
    workspace = module.WeChatWorkspace(StubFacade(), executor=executor)
    workspace._start_wechat_connect(_wechat_connection_config())
    task = executor.tasks[0]
    progress = _facade_module().WeChatConnectionProgress
    for state in (progress.WAITING_FOR_WECHAT_EXIT, progress.WAITING_FOR_WECHAT_START,
                  progress.READY_FOR_LOGIN, progress.CREDENTIAL_RECEIVED):
        task.progress(state)
    assert workspace._status_label.text() == module._WECHAT_CREDENTIAL_RECEIVED
    assert workspace._wechat_guide_note_label.text() == "请稍候，无需操作。"
    for state in (progress.WAITING_FOR_WECHAT_EXIT, progress.WAITING_FOR_WECHAT_START):
        task.progress(state)
        assert workspace._status_label.text() == module._WECHAT_CREDENTIAL_RECEIVED
        assert workspace._wechat_guide_note_label.text() == "请稍候，无需操作。"
    task.progress(module._WECHAT_READING_DATABASE)
    assert workspace._status_label.text() == module._WECHAT_READING_DATABASE
    loads = []
    monkeypatch.setattr(workspace, "_load_sessions", lambda **kwargs: loads.append(kwargs))
    task.succeed(_wechat_connected_status())
    assert workspace._wechat_key_captured is True
    assert workspace._status_label.text() == module._WECHAT_LOADING_SESSIONS
    assert loads == [{"attempt_generation": workspace._wechat_attempt_generation}]
    task.finish()
    assert workspace._connection_task is None


def test_wechat_stale_ready_progress_is_ignored_after_restart(qt_app):
    module = _wechat_guide_module()
    executor = _IndependentDeferredExecutor()
    workspace = module.WeChatWorkspace(StubFacade(), executor=executor)

    workspace._start_wechat_connect(_wechat_connection_config())
    first = executor.tasks[0]
    workspace.cancel_connection()
    workspace._start_wechat_connect(_wechat_connection_config())
    second = executor.tasks[1]

    first.progress(_facade_module().WeChatConnectionProgress.READY_FOR_LOGIN)

    assert second.cancelled is False
    assert workspace._wechat_guide_label.text() == module._WECHAT_PROGRESS_INSTRUCTIONS[_facade_module().WeChatConnectionProgress.PREPARING]
    assert workspace._status_label.text() == module._WECHAT_CONNECTING


def test_wechat_stale_success_is_ignored_after_restart(qt_app):
    module = _wechat_guide_module()
    executor = _IndependentDeferredExecutor()
    workspace = module.WeChatWorkspace(StubFacade(), executor=executor)

    workspace._start_wechat_connect(_wechat_connection_config())
    first = executor.tasks[0]
    workspace.cancel_connection()
    workspace._start_wechat_connect(_wechat_connection_config())
    second = executor.tasks[1]

    first.succeed(SimpleNamespace(available=True, data_found=True, action_hint=""))

    assert workspace._connection_task is second
    assert workspace._wechat_disconnect_button.isVisible() is False
    assert workspace._status_label.text() == module._WECHAT_CONNECTING


def test_wechat_stale_error_is_ignored_after_restart(qt_app):
    module = _wechat_guide_module()
    executor = _IndependentDeferredExecutor()
    workspace = module.WeChatWorkspace(StubFacade(), executor=executor)

    workspace._start_wechat_connect(_wechat_connection_config())
    first = executor.tasks[0]
    workspace.cancel_connection()
    workspace._start_wechat_connect(_wechat_connection_config())

    first.fail("wechat_key_timeout", "旧 attempt 错误")

    assert "旧 attempt 错误" not in workspace._status_label.toolTip()
    assert workspace._status_label.text() == module._WECHAT_CONNECTING


def test_wechat_stale_finished_does_not_clear_new_attempt(qt_app):
    module = _wechat_guide_module()
    executor = _IndependentDeferredExecutor()
    workspace = module.WeChatWorkspace(StubFacade(), executor=executor)

    workspace._start_wechat_connect(_wechat_connection_config())
    first = executor.tasks[0]
    workspace.cancel_connection()
    workspace._start_wechat_connect(_wechat_connection_config())
    second = executor.tasks[1]

    first.finish()

    assert workspace._connection_task is second


def test_wechat_cancel_without_restart_rejects_late_events(qt_app):
    module = _wechat_guide_module()
    executor = _IndependentDeferredExecutor()
    workspace = module.WeChatWorkspace(StubFacade(), executor=executor)

    workspace._start_wechat_connect(_wechat_connection_config())
    first = executor.tasks[0]
    workspace.cancel_connection()
    cancelled_status = workspace._status_label.text()

    first.progress(_facade_module().WeChatConnectionProgress.READY_FOR_LOGIN)
    first.succeed(SimpleNamespace(available=True, data_found=True, action_hint=""))
    first.fail("wechat_key_timeout", "迟到错误")
    first.finish()

    assert workspace._status_label.text() == cancelled_status
    assert "现在可以登录微信" not in workspace._wechat_guide_note_label.text()
    assert workspace._connection_task is None


def test_wechat_second_attempt_events_update_gui_normally(qt_app):
    module = _wechat_guide_module()
    progress = _facade_module().WeChatConnectionProgress
    executor = _IndependentDeferredExecutor()
    workspace = module.WeChatWorkspace(StubFacade(), executor=executor)

    workspace._start_wechat_connect(_wechat_connection_config())
    first = executor.tasks[0]
    workspace.cancel_connection()
    workspace._start_wechat_connect(_wechat_connection_config())
    second = executor.tasks[1]

    second.progress(progress.READY_FOR_LOGIN)
    assert "现在可以登录微信" in workspace._wechat_guide_label.text()

    second.succeed(_wechat_unavailable_status())
    assert workspace._status_label.text().startswith(module._DISCONNECTED_PREFIX)

    second.fail("wechat_key_timeout", "本次错误")
    assert workspace._status_label.toolTip() == "本次错误"
    second.finish()
    assert workspace._connection_task is None
    assert first.cancelled is True


def test_wechat_credential_received_does_not_return_to_login(qt_app):
    module = _wechat_guide_module()
    progress = _facade_module().WeChatConnectionProgress
    executor = _DeferredExecutor()
    workspace = module.WeChatWorkspace(StubFacade(), executor=executor)
    config = _facade_module().WeChatEnvironmentConfig()
    workspace._start_wechat_connect(config)
    executor.on_progress(progress.READY_FOR_LOGIN)
    executor.on_progress(progress.CREDENTIAL_RECEIVED)
    received_status = workspace._status_label.text()
    assert received_status == "正在连接微信"
    assert workspace._wechat_guide_note_label.text() == "请稍候，无需操作。"

    for event in (progress.READY_FOR_LOGIN, progress.PREPARING, "等待微信登录"):
        executor.on_progress(event)
        assert workspace._status_label.text() == received_status
        assert workspace._wechat_guide_note_label.text() == "请稍候，无需操作。"

    # A subsequent explicit connection still starts normally.
    workspace._start_wechat_connect(config)
    assert workspace._status_label.text() == "正在准备微信连接"
    executor.on_progress(progress.READY_FOR_LOGIN)
    assert "现在可以登录微信" in workspace._status_label.text()


def test_wechat_failed_listener_removes_login_prompt(qt_app):
    workspace = _wechat_workspace(qt_app, StubFacade())
    progress = _facade_module().WeChatConnectionProgress
    workspace._handle_wechat_connect_progress(progress.READY_FOR_LOGIN)
    assert "现在可以登录微信" in workspace._wechat_guide_label.text()

    workspace._handle_wechat_connect_error("wechat_key_timeout", "等待超时，请重试。")

    assert workspace._wechat_guide_note_label.isHidden()
    assert workspace._wechat_guide_key_label.isHidden()
    assert "现在可以登录微信" not in workspace._wechat_guide_note_label.text()
    assert workspace._wechat_connect_button.isEnabled()


def test_wechat_structured_progress_crosses_real_facade_and_worker(
    qt_app, tmp_path, monkeypatch,
):
    import io
    from types import SimpleNamespace
    from qq_chat_analyzer.application.wechat import wechat_key_service
    from qq_chat_analyzer.application.wechat.wechat_setup_service import WeChatSetupService
    from qq_chat_analyzer.application.wechat.wechat_environment_config import (
        WeChatEnvironmentConfigLoader, WeChatEnvironmentConfigWriter,
    )
    from qq_chat_analyzer.gui import workers

    dll = tmp_path / "fictional.dll"
    helper = tmp_path / "fictional.cjs"
    dll.write_bytes(b"fake")
    helper.write_text("", encoding="utf-8")
    process = SimpleNamespace(
        stdout=io.StringIO("ab12" * 16 + "\n"),
        stderr=io.StringIO(
            "exports loaded: InitializeHook, PollKeyData, CleanupHook\n"
            "2026-08-09T00:00:00.000Z hook_success=true\n"
        ),
        returncode=0,
        wait=lambda **_kwargs: 0,
        closed=False,
    )
    def close_after_readers(readers, *, deadline):
        assert not any(reader.is_alive() for reader in readers)
        process.stdout.close()
        process.stderr.close()
        process.closed = True
    process.close_after_readers = close_after_readers
    snapshots = iter([[], [4242]])
    monkeypatch.setattr(
        wechat_key_service, "_find_weixin_pids",
        lambda: next(snapshots, [4242]),
    )
    helper_commands = []

    def launch(command, **_kwargs):
        helper_commands.append(command)
        return process

    key_service = wechat_key_service.WeChatKeyService(
        dll_path=dll, helper_path=helper,
        process_launcher=launch,
        node_finder=lambda _name: "fictional-node",
    )
    target = tmp_path / "wechat.json"
    setup = WeChatSetupService(
        config_loader=WeChatEnvironmentConfigLoader(target),
        config_writer=WeChatEnvironmentConfigWriter(target),
        key_service=key_service,
    )
    facade = _facade_module().ChatAnalyzerFacade(wechat_setup_service=setup)
    workspace = _wechat_workspace(qt_app, facade)
    seen, errors = [], []
    ui_thread = threading.get_ident()

    def on_progress(event):
        workspace._handle_wechat_connect_progress(event)
        seen.append((event, workspace._status_label.text(), threading.get_ident()))

    workers.submit(
        lambda report: facade.acquire_wechat_db_key(progress=report),
        on_success=lambda _result: None,
        on_error=lambda code, message: errors.append((code, message)),
        on_progress=on_progress,
    )
    _settle_workers()

    assert errors == []
    assert key_service._legacy_injected is False
    assert len(helper_commands) == 1
    command = helper_commands[0]
    assert command[:2] == ["fictional-node", str(helper)]
    assert command[command.index("--pid") + 1] == "4242"
    assert [getattr(event, "name", None) for event, _text, _thread in seen] == [
        "PREPARING", "WAITING_FOR_WECHAT_START", "READY_FOR_LOGIN",
        "CREDENTIAL_RECEIVED",
    ]
    assert all(thread == ui_thread for _event, _text, thread in seen)
    assert seen[0][1] == "正在准备微信连接"
    assert "现在可以登录微信" in seen[2][1]
    assert seen[3][1] == "正在连接微信"


def test_wechat_workspace_guide_shows_status_confirmation(qt_app) -> None:
    module = _wechat_guide_module()
    workspace = _wechat_workspace(qt_app, StubFacade())
    workspace.show()

    workspace._show_wechat_guide()

    assert workspace._wechat_guide_label.isVisibleTo(workspace) is True
    assert workspace._wechat_guide_key_label.isVisibleTo(workspace) is True
    assert workspace._wechat_guide_note_label.isVisibleTo(workspace) is True
    assert workspace._wechat_guide_label.text() == module._WECHAT_GUIDE_STATUS
    assert workspace._wechat_guide_key_label.text() == module._WECHAT_GUIDE_WARNING
    assert workspace._wechat_guide_note_label.text() == (
        module._WECHAT_PROGRESS_INSTRUCTIONS[module.WeChatConnectionProgress.PREPARING]
    )
    # The privacy line is never repeated in this guide; Home already owns it.
    assert "\u4e0d\u4e0a\u4f20" not in workspace._wechat_guide_note_label.text()
    assert "\u4e0d\u4fdd\u5b58" not in workspace._wechat_guide_note_label.text()
    assert "\u4e0d\u4e0a\u4f20" not in workspace._wechat_guide_key_label.text()
    assert "\u4e0d\u4fdd\u5b58" not in workspace._wechat_guide_key_label.text()


def test_wechat_workspace_guide_labels_wrap_and_expand(qt_app) -> None:
    workspace = _wechat_workspace(qt_app, StubFacade())

    for label in (
        workspace._wechat_guide_label,
        workspace._wechat_guide_key_label,
        workspace._wechat_guide_note_label,
    ):
        assert label.wordWrap() is True
        assert label.sizePolicy().horizontalPolicy() == (
            QSizePolicy.Policy.Expanding
        )


def test_wechat_workspace_guide_text_has_no_html_tags(qt_app) -> None:
    workspace = _wechat_workspace(qt_app, StubFacade())
    workspace.show()

    workspace._show_wechat_guide()

    for text in (
        workspace._wechat_guide_label.text(),
        workspace._wechat_guide_key_label.text(),
        workspace._wechat_guide_note_label.text(),
    ):
        assert "<br" not in text
        assert "<span" not in text
        assert ">" not in text


def test_wechat_workspace_directory_help_guide_is_plain_text(qt_app) -> None:
    module = _wechat_guide_module()
    workspace = _wechat_workspace(qt_app, StubFacade())
    workspace.show()

    workspace._show_wechat_guide(include_directory_help=True)

    assert workspace._wechat_guide_label.text() == (
        module._WECHAT_GUIDE_DIRECTORY_MISSING
    )
    assert workspace._wechat_guide_note_label.text() == (
        module._WECHAT_GUIDE_DIRECTORY_NOTE
    )
    assert workspace._wechat_guide_key_label.isVisibleTo(workspace) is False


def test_wechat_workspace_guide_image_load_failure_is_safe(
    qt_app,
    tmp_path: Path,
) -> None:
    module = _wechat_guide_module()
    workspace = _wechat_workspace(qt_app, StubFacade())
    workspace._wechat_guide_image_path = tmp_path / "missing.png"
    workspace.show()

    workspace._handle_wechat_connect_progress(module.WeChatConnectionProgress.READY_FOR_LOGIN)

    assert workspace._wechat_guide_image_label.isVisibleTo(workspace) is False
    assert workspace._status_label.text() == "现在可以登录微信了"
    workspace._handle_wechat_connect_progress(module.WeChatConnectionProgress.CREDENTIAL_RECEIVED)
    workspace._handle_wechat_connect_progress(module._WECHAT_READING_DATABASE)
    assert workspace._status_label.text() == module._WECHAT_READING_DATABASE


def test_wechat_workspace_guide_shows_optional_image(qt_app, tmp_path) -> None:
    from PySide6.QtGui import QPixmap

    workspace = _wechat_workspace(qt_app, StubFacade())
    workspace._wechat_guide_image_path = tmp_path / "fictional-guide.png"
    sample = QPixmap(320, 440)
    sample.fill(Qt.GlobalColor.white)
    assert sample.save(str(workspace._wechat_guide_image_path))
    workspace.show()

    workspace._show_wechat_guide(progress=_facade_module().WeChatConnectionProgress.READY_FOR_LOGIN, current_step_only=True)

    assert workspace._wechat_guide_image_label.isVisibleTo(workspace) is True
    assert workspace._wechat_guide_image_label.pixmap().isNull() is False


def test_wechat_workspace_guide_image_keeps_aspect_ratio(qt_app, tmp_path) -> None:
    from PySide6.QtGui import QPixmap

    workspace = _wechat_workspace(qt_app, StubFacade())
    workspace._wechat_guide_image_path = tmp_path / "fictional-guide.png"
    original = QPixmap(300, 500)
    original.fill(Qt.GlobalColor.white)
    assert original.save(str(workspace._wechat_guide_image_path))
    workspace.show()

    workspace._show_wechat_guide(progress=_facade_module().WeChatConnectionProgress.READY_FOR_LOGIN, current_step_only=True)

    pixmap = workspace._wechat_guide_image_label.pixmap()
    assert pixmap is not None
    assert pixmap.isNull() is False
    assert pixmap.width() > 0 and pixmap.height() > 0
    assert abs(
        (original.width() / original.height())
        - (pixmap.width() / pixmap.height())
    ) < 0.01


def test_wechat_workspace_guide_uses_horizontal_layout(qt_app) -> None:
    from PySide6.QtWidgets import QHBoxLayout

    workspace = _wechat_workspace(qt_app, StubFacade())
    workspace.show()
    workspace.resize(900, 700)

    workspace._show_wechat_guide()

    assert isinstance(workspace._wechat_guide_row, QHBoxLayout)
    assert workspace._wechat_guide_row.indexOf(
        workspace._wechat_guide_image_label
    ) >= 0
    assert workspace._wechat_guide_image_label.maximumWidth() < workspace.width() / 3


@pytest.mark.parametrize("size", [(1200, 760), (800, 600)])
@pytest.mark.parametrize("state", [
    "idle", "PREPARING", "WAITING_FOR_WECHAT_EXIT", "WAITING_FOR_WECHAT_START",
    "READY_FOR_LOGIN", "CREDENTIAL_RECEIVED", "directory", "error", "cancelled",
])
def test_wechat_setup_current_action_fits_window(qt_app, size, state):
    """Large action type must wrap without pushing controls outside the window."""
    from PySide6.QtCore import QPoint, QRect
    from qq_chat_analyzer.gui.theme import BASE_QSS
    from qq_chat_analyzer.gui.main_window import WECHAT_WORKSPACE_INDEX

    window = _main_window(qt_app, StubFacade(), executor=_IndependentDeferredExecutor())
    window.setStyleSheet(BASE_QSS)
    window.stack.setCurrentIndex(WECHAT_WORKSPACE_INDEX)
    page = window.wechat_workspace
    if state == "directory":
        page._show_wechat_guide(include_directory_help=True)
    elif state == "error":
        page._handle_wechat_connect_error("wechat_key_timeout", "等待超时，请重试。")
    elif state == "cancelled":
        page._start_wechat_connect(_wechat_connection_config())
        page.cancel_connection()
    elif state != "idle":
        page._handle_wechat_connect_progress(getattr(_facade_module().WeChatConnectionProgress, state))
    window.resize(*size)
    window.show()
    _drain(window)
    try:
        assert window.size().toTuple() == size
        labels = (page._status_label, page._wechat_guide_label,
                  page._wechat_guide_note_label, page._wechat_guide_key_label)
        for widget in (*labels, page._wechat_connect_button, page._wechat_setup_button,
                       page._wechat_guide_image_label):
            if widget.isVisibleTo(page):
                bounds = QRect(widget.mapTo(page, QPoint()), widget.size())
                assert page.rect().contains(bounds), widget.text()
                if widget in labels:
                    assert widget.height() >= widget.heightForWidth(widget.width()), widget.text()
        if page._progress_track.isVisibleTo(page):
            track_bounds = QRect(page._progress_track.mapTo(page, QPoint()),
                                 page._progress_track.size())
            assert page.rect().contains(track_bounds)
        if page._wechat_guide_label.isVisibleTo(page):
            assert page._wechat_guide_label.font().pixelSize() > page._wechat_guide_note_label.font().pixelSize()
        assert page._wechat_connect_button.width() < page.width() / 2
    finally:
        window.hide()


@pytest.mark.parametrize("data_roots", [None, ["D:/" + "fictional_directory/" * 12]])
def test_wechat_setup_dialog_keeps_path_and_actions_reachable(qt_app, data_roots):
    """Long detected paths and fallback instructions must fit a small dialog."""
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QDialogButtonBox, QScrollArea
    from qq_chat_analyzer.gui.theme import BASE_QSS
    from qq_chat_analyzer.gui.wechat_setup_dialog import WeChatSetupDialog

    parent = _main_window(qt_app, StubFacade())
    parent.setStyleSheet(BASE_QSS)
    dialog = WeChatSetupDialog(parent, data_roots=data_roots)
    dialog.resize(520, 480)
    dialog.show()
    _drain(dialog)
    try:
        assert dialog.width() == 520
        assert dialog.height() <= 480
        scroll = dialog.findChild(QScrollArea)
        assert scroll.widget().width() <= scroll.viewport().width()
        buttons = dialog.findChild(QDialogButtonBox)
        for role in (QDialogButtonBox.Save, QDialogButtonBox.Cancel):
            button = buttons.button(role)
            assert dialog.rect().contains(QRect(button.mapTo(dialog, QPoint()), button.size()))
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        buttons.button(QDialogButtonBox.Cancel).click()
        assert not dialog.isVisible()
    finally:
        dialog.close()
        parent.hide()


def test_wechat_setup_action_tracks_environment_repair(qt_app):
    executor = _IndependentDeferredExecutor()
    facade = StubFacade(
        setup_status=SimpleNamespace(configured=True),
        data_roots=["D:/fictional_wechat"],
    )
    page = _wechat_guide_module().WeChatWorkspace(facade, executor=executor)
    page.show()
    try:
        assert page._wechat_setup_button.isHidden()
        page._start_wechat_connect(_wechat_connection_config())
        task = executor.tasks[0]
        for progress in _facade_module().WeChatConnectionProgress:
            task.progress(progress)
            assert page._wechat_setup_button.isHidden()
        task.fail("wechat_environment_missing", "虚构环境错误")
        task.finish()
        assert page._wechat_setup_button.isVisibleTo(page)
        page._wechat_connect_button.click()
        assert page._wechat_setup_button.isHidden()
        executor.tasks[1].fail("wechat_key_timeout", "虚构等待超时")
        assert page._wechat_setup_button.isHidden()
    finally:
        page.close()


@pytest.mark.parametrize("session_error", [False, True])
def test_wechat_connection_finish_keeps_connect_hidden_while_loading_sessions(qt_app, session_error):
    executor = _IndependentDeferredExecutor()
    page = _wechat_guide_module().WeChatWorkspace(StubFacade(), executor=executor)
    page.show()
    try:
        page._start_wechat_connect(_wechat_connection_config())
        connection = executor.tasks[0]
        connection.succeed(_wechat_connected_status())
        assert page._status_label.text() == "正在加载微信会话..."
        assert page._wechat_connect_button.isHidden()
        connection.finish()
        assert page._wechat_connect_button.isHidden()
        assert page._wechat_setup_button.isHidden()
        if session_error:
            executor.tasks[1].fail("wechat_database_error", "虚构数据库错误")
            assert page._wechat_connect_button.isVisibleTo(page)
            assert page._wechat_connect_button.text() == "重新开始"
            assert page._wechat_setup_button.isVisibleTo(page)
        else:
            executor.tasks[1].succeed([])
            assert page._wechat_connect_button.isHidden()
            assert page._wechat_disconnect_button.isVisibleTo(page)
    finally:
        page.close()
