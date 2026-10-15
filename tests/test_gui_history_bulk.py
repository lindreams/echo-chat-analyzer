"""Archive selection and frozen batch deletion, using fictional reports."""

import dataclasses

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QListWidget, QPushButton

from test_gui import (StubFacade, _QueuedExecutor, _drain, _gui_report_summary,
                      _main_window, qt_app, sources)
from qq_chat_analyzer.application.facade import FacadeError
from qq_chat_analyzer.application.report_package_catalog import (
    ReportPackageDeletionFailure, ReportPackageDeletionResult,
)


class BulkFacade(StubFacade):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.batch_calls = []
        self.failed_names = set()
        self.batch_error = None

    def delete_report_packages(self, names):
        assert isinstance(names, tuple)
        self.batch_calls.append(names)
        if self.batch_error:
            raise self.batch_error
        deleted = tuple(name for name in names if name not in self.failed_names)
        self._reports = [r for r in self._reports if r.package_name not in deleted]
        return ReportPackageDeletionResult(
            deleted, tuple(ReportPackageDeletionFailure(name, "delete_failed")
                           for name in names if name in self.failed_names),
        )


def archive(qt_app, sources):
    records = [
        _gui_report_summary("a", source="qq", session_name="Alpha"),
        _gui_report_summary("b", session_name="Beta"),
        _gui_report_summary("c", session_name="Gamma"),
    ]
    facade = BulkFacade(sources=sources, reports=records)
    window = _main_window(qt_app, facade)
    window.show_local_data_page()
    _drain(window)
    return window, facade


def checkbox(page, index):
    item = page._history_list.item(index)
    return page._history_list.itemWidget(item).findChild(QCheckBox)


@pytest.mark.parametrize("confirm", [False, True])
def test_retain_selection_freezes_full_snapshot_complement(qt_app, sources, confirm):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    assert not page._retain_reports_button.isVisibleTo(window)
    page._enter_delete_button.click()
    assert not page._retain_reports_button.isEnabled()
    page._retain_reports_button.click()
    assert not facade.batch_calls
    checkbox(page, 0).setChecked(True)
    page._search_input.setText("Beta")
    seen = []
    def confirmation(names, kept):
        seen.append((names, kept))
        facade._reports.append(_gui_report_summary("new-after-snapshot", session_name="New"))
        page._checked_names = {"c"}
        page.refresh()
        page._retain_selected_reports()
        return confirm
    page._confirm_delete_reports = confirmation
    page._retain_reports_button.click()
    assert seen == [(("b", "c"), 1)]
    assert facade.batch_calls == ([("b", "c")] if confirm else [])
    assert {r.package_name for r in facade._reports} == ({"a", "new-after-snapshot"} if confirm else {"a", "b", "c", "new-after-snapshot"})
    assert page._search_input.text() == "Beta"
    if not confirm:
        assert "已删除" not in page._status_label.text()


def test_retain_retry_only_targets_failed_frozen_names(qt_app, sources):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    page._enter_delete_button.click()
    checkbox(page, 0).setChecked(True)
    facade.failed_names = {"b"}
    def confirmation(names, kept):
        facade._reports.append(_gui_report_summary("new-after-snapshot"))
        return True
    page._confirm_delete_reports = confirmation
    page._retain_reports_button.click()
    assert facade.batch_calls == [("b", "c")]
    assert page._checked_names == {"a"}
    assert "1 份未能删除" in page._status_label.text()
    assert not page._feedback_timer.isActive()
    assert page._retain_reports_button.text() == "重试删除失败项"
    facade.failed_names.clear()
    page._confirm_delete_reports = lambda names, kept: names == ("b",) and kept == 2
    page._retain_reports_button.click()
    assert facade.batch_calls == [("b", "c"), ("b",)]
    assert {r.package_name for r in facade._reports} == {"a", "new-after-snapshot"}


def test_retain_retry_preserves_a_failed_report_checked_after_failure(qt_app, sources):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    page._enter_delete_button.click()
    checkbox(page, 0).setChecked(True)
    facade.failed_names = {"b", "c"}
    def confirmation(names, kept):
        facade._reports.append(_gui_report_summary("new-after-snapshot"))
        return True
    page._confirm_delete_reports = confirmation
    page._retain_reports_button.click()
    checkbox(page, 1).setChecked(True)  # Beta now explicitly belongs to the retained selection.
    checkbox(page, 2).setChecked(True)
    assert not page._retain_reports_button.isEnabled()  # New reports cannot become retry targets.
    checkbox(page, 2).setChecked(False)
    page._confirm_delete_reports = lambda names, kept: names == ("c",) and kept == 3
    facade.failed_names.clear()
    page._retain_reports_button.click()
    assert facade.batch_calls == [("b", "c"), ("c",)]
    assert {r.package_name for r in facade._reports} == {"a", "b", "new-after-snapshot"}


def test_retain_error_retry_preserves_frozen_boundary_and_cancel_clears_retry(qt_app, sources):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    page._enter_delete_button.click()
    checkbox(page, 0).setChecked(True)
    page._confirm_delete_reports = lambda names, kept: True
    facade.batch_error = FacadeError("delete_failed", "未能删除报告。")
    page._retain_reports_button.click()
    assert page._checked_names == {"a"}
    assert "未能删除报告" in page._status_label.text()
    facade.batch_error = None
    facade._reports.append(_gui_report_summary("new-after-error"))
    page.refresh()
    page._retain_reports_button.click()
    assert facade.batch_calls == [("b", "c"), ("b", "c")]
    assert {r.package_name for r in facade._reports} == {"a", "new-after-error"}
    page._enter_delete_button.click()
    assert page._retain_reports_button.text() == "保留所选，删除其余"
    assert not page._retain_reports_button.isEnabled()


def test_retain_cannot_run_with_all_or_none_selected_and_blocks_duplicates(qt_app, sources):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    page._enter_delete_button.click()
    page._select_results_button.click()
    assert not page._retain_reports_button.isEnabled()
    page._retain_selected_reports()
    assert not facade.batch_calls
    page._clear_checks_button.click()
    checkbox(page, 0).setChecked(True)
    executor = _QueuedExecutor()
    page._executor = executor
    page._confirm_delete_reports = lambda names, kept: True
    page._retain_reports_button.click()
    assert not page._retain_reports_button.isEnabled()
    page._retain_selected_reports()
    page._delete_checked_reports()
    page.refresh()
    assert len(executor.tasks) == 1
    executor.succeed(0)
    executor.succeed(1)
    executor.fail(0, "late", "Stale retain error")
    assert "Stale" not in page._status_label.text()
    assert facade.batch_calls == [("b", "c")]


@pytest.mark.parametrize("confirm", [False, True])
def test_delete_freezes_identity_before_confirmation(qt_app, sources, confirm):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    page._enter_delete_button.click()
    checkbox(page, 0).setChecked(True)
    checkbox(page, 1).setChecked(True)
    page._search_input.setText("Alpha")
    seen = []
    def confirmation(names, kept):
        seen.append((names, kept))
        assert names == ("a", "b") and kept == 1
        page._checked_names.clear()
        page._checked_names.add("c")
        facade._reports.append(_gui_report_summary("published-later"))
        page.refresh()  # A modal callback must not start a scan.
        page._delete_checked_reports()  # Or a second delete.
        return confirm
    page._confirm_delete_reports = confirmation
    page._delete_checked_button.click()
    assert seen == [(("a", "b"), 1)]
    assert facade.batch_calls == ([("a", "b")] if confirm else [])
    assert len(facade.list_report_packages_calls) == (2 if confirm else 1)
    assert "published-later" in {r.package_name for r in facade._reports}
    assert "c" in {r.package_name for r in facade._reports}
    assert page._search_input.text() == "Alpha"
    assert page._refresh_button.isEnabled()


def test_confirmation_lists_every_report_and_defaults_to_cancel(qt_app):
    from qq_chat_analyzer.gui.local_data_page import _bulk_delete_confirmation_dialog
    reports = tuple(dataclasses.replace(_gui_report_summary(str(i)), conversation_name="Same name")
                    for i in range(30))
    dialog = _bulk_delete_confirmation_dialog(reports, 7)
    labels = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "30 份" in labels and "7 份正常报告" in labels
    listing = dialog.findChild(QListWidget, "archiveDeletionList")
    assert listing.count() == 30
    assert [listing.item(i).data(Qt.ItemDataRole.UserRole) for i in range(30)] == [str(i) for i in range(30)]
    assert all(str(i) in listing.item(i).text() for i in range(30))
    cancel = next(b for b in dialog.findChildren(QPushButton) if b.text() == "取消")
    delete = next(b for b in dialog.findChildren(QPushButton) if b.text() == "确认删除")
    assert cancel.isDefault() and not delete.isDefault() and not delete.autoDefault()
    assert "QQ / 微信原始聊天数据" in labels and "删除后无法恢复" in labels
    dialog.show()
    _drain(dialog)
    assert listing.verticalScrollBar().maximum() > 0
    QTest.keyClick(cancel, Qt.Key.Key_Return)
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_delete_blocks_duplicates_refresh_and_stale_callbacks(qt_app, sources):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    executor = _QueuedExecutor()
    page._executor = executor
    page.refresh()
    page.refresh()
    executor.succeed(1)
    page._enter_delete_button.click()
    checkbox(page, 0).setChecked(True)
    page._confirm_delete_reports = lambda names, kept: True
    page._delete_checked_button.click()
    assert len(executor.tasks) == 3
    assert not page._refresh_button.isEnabled()
    assert not page._delete_checked_button.isEnabled()
    assert not page._search_input.isEnabled()
    page.refresh()
    page._delete_checked_reports()
    assert len(executor.tasks) == 3
    executor.fail(0, "stale", "Stale refresh error")
    assert "Stale" not in page._status_label.text()
    executor.succeed(2)
    assert len(executor.tasks) == 4
    executor.succeed(3)
    status = page._status_label.text()
    executor.fail(2, "duplicate", "Stale delete error")
    assert page._status_label.text() == status
    assert facade.batch_calls == [("a",)]
    assert page._refresh_button.isEnabled()


def test_delete_error_and_failed_rescan_preserve_safe_retry(qt_app, sources):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    page._enter_delete_button.click()
    checkbox(page, 0).setChecked(True)
    page._confirm_delete_reports = lambda names, kept: True
    facade.batch_error = FacadeError("report_delete_failed", "所选报告未能删除。")
    facade._list_reports_error = FacadeError("report_list_failed", "无法读取报告。")
    page._delete_checked_button.click()
    assert "所选报告未能删除" in page._status_label.text()
    assert "无法读取报告" in page._status_label.text()
    assert page._checked_names == {"a"}
    assert page._history_list.count() == 3
    assert page._refresh_button.isEnabled()


def test_open_report_does_not_check_it_and_late_open_is_ignored(qt_app, sources):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    opened = []
    facade.get_report_package_html_path = lambda name: name
    window._report_opener = lambda path: opened.append(path) or True
    page._history_list.setCurrentRow(1)
    executor = _QueuedExecutor()
    page._executor = executor
    page._open_report_button.click()
    assert not page._checked_names

    page.refresh()
    executor.succeed(0)
    assert opened == []
    executor.succeed(1)
    page._history_list.setCurrentRow(1)
    page._open_report_button.click()
    executor.succeed(2)
    assert opened == ["b"]
    assert not page._checked_names



def test_successful_deletions_are_not_shown_when_rescan_fails(qt_app, sources):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    page._enter_delete_button.click()
    page._select_results_button.click()
    facade.failed_names = {"b"}
    page._confirm_delete_reports = lambda names, kept: True
    facade._list_reports_error = FacadeError("report_list_failed", "无法读取报告。")
    page._delete_checked_button.click()
    assert page._history_list.count() == 1
    assert page._history_list.item(0).data(Qt.ItemDataRole.UserRole) == "b"
    assert page._checked_names == {"b"}
    assert "1 份未能删除" in page._status_label.text()
    assert "无法读取报告" in page._status_label.text()
    assert page._summary_count_label.text() == "—"
    assert page._summary_size_label.text() == "—"
