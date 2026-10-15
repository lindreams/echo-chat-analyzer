"""User-visible feedback for report and share actions on the main window.

The main window owns one header status line. These tests pin the contract the
0.1 release audit found broken: status copy written by report and share actions
must actually reach the user, and a failed action must be announced instead of
only being logged.

All data here is fictional; no real chat records, databases, or network calls
are involved.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from qq_chat_analyzer.application.facade import FacadeError

from test_gui import (  # noqa: F401  (qt_app/sources are fixtures re-exported here)
    StubFacade,
    _StubOutcome,
    _dashboard_view,
    _main_window,
    qt_app,
    sources,
)


def _module():
    return importlib.import_module("qq_chat_analyzer.gui.main_window")


def _record_warnings(monkeypatch) -> list[tuple[str, str]]:
    """Capture the modal failure announcements instead of blocking on them."""
    module = _module()
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        module.QMessageBox,
        "warning",
        lambda _parent, title, message: calls.append((title, message)),
    )
    return calls


def _fictional_report(tmp_path: Path) -> Path:
    path = tmp_path / "fictional-echo-report.html"
    path.write_text("<html>fictional report</html>", encoding="utf-8")
    return path


def test_analysis_completion_status_is_visible(qt_app, sources, tmp_path) -> None:
    """A finished analysis must show its saved-report copy to the user."""
    report = _fictional_report(tmp_path)
    window = _main_window(qt_app, StubFacade(sources=sources))
    window._report_opener = lambda path: True

    window.show_outcome(
        _StubOutcome(
            _dashboard_view(),
            report_path=report,
            report_directory=tmp_path,
        )
    )

    assert window._status_label.text() == "报告已保存"
    assert window._status_label.isVisibleTo(window) is True


def test_share_success_status_is_visible(qt_app, sources, tmp_path) -> None:
    report = _fictional_report(tmp_path)
    share = tmp_path / "fictional-share.png"
    share.write_bytes(b"fictional-share-image")
    window = _main_window(
        qt_app, StubFacade(sources=sources, share_image_path=share)
    )
    window._report_opener = lambda path: True
    window._image_opener = lambda path: True

    window.show_outcome(
        _StubOutcome(
            _dashboard_view(),
            report_path=report,
            report_directory=tmp_path,
        )
    )
    window._generate_share_button.click()

    assert window._status_label.text() == "分享图片已生成"
    assert window._status_label.isVisibleTo(window) is True


def test_share_failure_is_visible_and_announced(
    qt_app, sources, tmp_path, monkeypatch
) -> None:
    """A generation failure must be visible and announced, not only logged."""
    warnings = _record_warnings(monkeypatch)
    report = _fictional_report(tmp_path)
    facade = StubFacade(
        sources=sources,
        share_image_error=FacadeError(
            code="share_image_generation_failed",
            public_message="分享图片生成失败，请稍后重试。",
        ),
    )
    window = _main_window(qt_app, facade)
    window._report_opener = lambda path: True

    window.show_outcome(
        _StubOutcome(
            _dashboard_view(),
            report_path=report,
            report_directory=tmp_path,
        )
    )
    window._generate_share_button.click()

    assert window._status_label.text() == "分享图片生成失败，请稍后重试。"
    assert window._status_label.isVisibleTo(window) is True
    assert warnings[-1][1] == "分享图片生成失败，请稍后重试。"


def test_open_report_with_deleted_file_is_visible_and_announced(
    qt_app, sources, tmp_path, monkeypatch
) -> None:
    """A stale entry whose report is gone must be reported, not silently dropped."""
    warnings = _record_warnings(monkeypatch)
    report = _fictional_report(tmp_path)
    window = _main_window(qt_app, StubFacade(sources=sources))
    window._report_opener = lambda path: True

    window.show_outcome(
        _StubOutcome(
            _dashboard_view(),
            report_path=report,
            report_directory=tmp_path,
        )
    )
    assert window._open_echo_button.isVisibleTo(window) is True

    report.unlink()
    window.open_echo_report()

    assert window._open_echo_button.isVisibleTo(window) is False
    assert window._generate_share_button.isVisibleTo(window) is False
    assert window._status_label.isVisibleTo(window) is True
    assert "不存在" in window._status_label.text()
    assert warnings[-1][1] == window._status_label.text()
