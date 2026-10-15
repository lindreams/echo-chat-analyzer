"""Final GUI interaction polish: three focused behaviours.

1. One WeChat setup window per workspace: opening it again raises the existing
   window instead of stacking a second copy.
2. The QQ install-path prompt is asked once per workspace; only an explicit
   reconnect asks again.
3. A session-read failure is a connection/session error, never an analysis
   failure, while a real analysis failure still reports normally.

All data here is fictional; no real WeChat/QQ client, database, or chat data.
"""

from __future__ import annotations

import importlib

from qq_chat_analyzer.application.facade import ChatSource
from qq_chat_analyzer.gui.wechat_workspace import WeChatWorkspace
from qq_chat_analyzer.gui.qq_workspace import QQWorkspace

from test_gui import (  # noqa: F401  (fixtures re-exported for pytest)
    StubFacade,
    _IndependentDeferredExecutor,
    _drain,
    _inline_executor,
    _qq_snapshot,
    _session,
    instant_qq_connect,
    qt_app,
    sources,
)


def _qq_module():
    return importlib.import_module("qq_chat_analyzer.gui.qq_workspace")


def _install_path_missing_snapshot():
    connection = importlib.import_module(
        "qq_chat_analyzer.application.connection_models"
    )
    return connection.ConnectionSnapshot(
        state=connection.ConnectionState.ERROR,
        source="qq",
        message="未检测到 QQ 客户端。",
        code="qq_install_path_missing",
    )


# --------------------------------------------------------------------- WeChat


def test_wechat_loaded_sessions_hide_setup_and_keep_disconnect(qt_app) -> None:
    """A successful load clears the setup action left by idle or repair states."""
    workspace = WeChatWorkspace(StubFacade(), executor=_inline_executor())
    workspace.show()
    try:
        assert workspace._wechat_setup_button.isVisibleTo(workspace)
        workspace._handle_session_error("wechat_environment_missing", "虚构环境待修复")
        assert workspace._wechat_setup_button.isVisibleTo(workspace)

        workspace._handle_sessions_loaded([
            _session(ChatSource.WECHAT, "fictional", "虚构读书会", 10)
        ])

        assert not workspace._wechat_setup_button.isVisibleTo(workspace)
        assert workspace._wechat_disconnect_button.isVisibleTo(workspace)
        assert not workspace._wechat_connect_button.isVisibleTo(workspace)
        assert workspace.session_panel._session_list.count() == 1

        workspace._handle_session_error("wechat_environment_missing", "虚构环境待修复")
        assert workspace._wechat_setup_button.isVisibleTo(workspace)
        assert workspace._wechat_setup_button.isEnabled()
    finally:
        workspace.close()


def test_reused_wechat_setup_dialog_still_saves_the_environment(
    qt_app, sources, tmp_path
) -> None:
    """Reuse must not break the accepted signal or the save path."""
    facade = StubFacade(sources=sources)
    workspace = WeChatWorkspace(facade, executor=_inline_executor())
    workspace.show()
    try:
        workspace.open_wechat_setup()
        dialog = workspace._wechat_setup_dialog
        workspace.open_wechat_setup()

        fictional_root = tmp_path / "fictional_wechat_files"
        dialog.set_data_root(str(fictional_root))
        dialog.accept()

        assert len(facade.setup_wechat_environment_calls) == 1
        assert (
            facade.setup_wechat_environment_calls[0].data_root == fictional_root
        )
    finally:
        workspace.hide()


# ------------------------------------------------------------------------- QQ


def test_qq_install_path_prompt_is_not_repeated_after_cancel(
    qt_app, monkeypatch
) -> None:
    """A cancelled prompt must not come back on passive refreshes."""
    module = _qq_module()
    facade = StubFacade(sources=())
    workspace = QQWorkspace(facade, executor=_inline_executor())
    calls = []

    def _cancelled(parent, title, directory, file_filter):
        calls.append(title)
        return "", ""

    monkeypatch.setattr(
        module.QFileDialog, "getOpenFileName", staticmethod(_cancelled)
    )
    snapshot = _install_path_missing_snapshot()

    workspace._show_qq_status(snapshot, load_sessions_on_ready=False)
    assert len(calls) == 1

    facade.get_qq_connection_snapshot = lambda: snapshot
    workspace.refresh_qq_status()
    _drain(workspace)
    workspace._show_qq_status(snapshot, load_sessions_on_ready=False)

    assert len(calls) == 1


def test_qq_install_path_prompt_returns_after_an_explicit_reconnect(
    qt_app, monkeypatch, instant_qq_connect
) -> None:
    """Clicking connect again is an explicit request to pick QQ.exe again."""
    module = _qq_module()
    facade = StubFacade(sources=())
    workspace = QQWorkspace(facade, executor=_inline_executor())
    calls = []

    def _cancelled(parent, title, directory, file_filter):
        calls.append(title)
        return "", ""

    monkeypatch.setattr(
        module.QFileDialog, "getOpenFileName", staticmethod(_cancelled)
    )
    snapshot = _install_path_missing_snapshot()

    workspace._show_qq_status(snapshot, load_sessions_on_ready=False)
    assert len(calls) == 1

    workspace.connect_qq()
    _drain(workspace)

    workspace._show_qq_status(snapshot, load_sessions_on_ready=False)

    assert len(calls) == 2


def test_qq_session_failure_is_not_reported_as_an_analysis_failure(
    qt_app, sources
) -> None:
    """Reading sessions is part of connecting; it is never an analysis failure."""
    executor = _IndependentDeferredExecutor()
    workspace = QQWorkspace(StubFacade(sources=sources), executor=executor)
    analysis_failures = []
    workspace.analysis_failed.connect(
        lambda *args: analysis_failures.append(args)
    )
    workspace.show()
    try:
        workspace._show_qq_status(_qq_snapshot("connected"), True)
        executor.tasks[0].fail(
            "qq_direct_snapshot_acquire_failed", "虚构会话读取失败。"
        )

        assert analysis_failures == []
        assert workspace._status_label.isVisibleTo(workspace) is True
        assert workspace._status_label.toolTip() == "虚构会话读取失败。"
        assert workspace._qq_connect_button.isVisibleTo(workspace) is True
        assert workspace._qq_connect_button.isEnabled() is True
        assert workspace._qq_connect_button.text() == "重新开始"
    finally:
        workspace.hide()


def test_true_analysis_failure_still_reports_through_the_signal(
    qt_app, sources
) -> None:
    """The real analysis failure path must stay untouched."""
    workspace = QQWorkspace(
        StubFacade(sources=sources), executor=_inline_executor()
    )
    received = []
    workspace.analysis_failed.connect(lambda *args: received.append(args))

    workspace.session_panel.analysis_failed.emit(
        "analyze_failed", "虚构分析失败。"
    )

    assert received == [("analyze_failed", "虚构分析失败。")]
