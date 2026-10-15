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


def test_retain_confirmation_shows_full_deletion_list_and_counts(qt_app):
    from qq_chat_analyzer.gui.local_data_page import _bulk_delete_confirmation_dialog
    reports = tuple(dataclasses.replace(_gui_report_summary(f"delete-{i}"), size_bytes=2048)
                    for i in range(30))
    dialog = _bulk_delete_confirmation_dialog(reports, 2, retain_selected=True)
    dialog.show()
    _drain(dialog)
    assert dialog.windowTitle() == "保留所选，删除其余"
    labels = "\n".join(label.text() for label in dialog.findChildren(QLabel))
    assert "30" in labels and "2" in labels
    assert "删除范围不受搜索筛选限制" in labels
    listing = dialog.findChild(QListWidget, "archiveDeletionList")
    assert listing.count() == 30
    assert all(listing.item(i).text().endswith(f"delete-{i}") for i in range(30))
    assert "2.0 KB" in listing.item(0).text()
    listing.scrollToBottom()
    assert listing.visualItemRect(listing.item(29)).intersects(listing.viewport().rect())
    cancel = next(button for button in dialog.findChildren(QPushButton) if button.text() == "取消")
    assert cancel.isDefault() and cancel.hasFocus()


def test_browse_mode_and_cancel_keep_identical_compact_entries(qt_app, sources):
    window, facade = archive(qt_app, sources)
    window.show()
    page = window.local_data_page
    _drain(window)
    assert checkbox(page, 0).isHidden()
    assert page._open_report_button.isVisibleTo(window)
    assert page._enter_delete_button.text() == "删除报告"
    assert page._enter_delete_button.isVisibleTo(window)
    assert not page._checked_count_label.isVisibleTo(window)
    assert not page._delete_checked_button.isVisibleTo(window)
    item = page._history_list.item(0)
    entry = page._history_list.itemWidget(item)
    title = entry.findChild(QLabel, "archiveEntryTitle")
    before = (entry.height(), title.geometry(), title.text())
    assert 65 <= entry.height() <= 80
    assert page._history_list.visualItemRect(item).height() == entry.height()
    assert page._history_list.viewport().height() // (entry.height() + 8) >= 6
    page._enter_delete_button.click()
    _drain(window)
    assert not checkbox(page, 0).isHidden()
    assert page._cancel_delete_button.isVisibleTo(window)
    assert not page._open_report_button.isVisibleTo(window)
    assert (entry.height(), title.geometry(), title.text()) == before
    assert page._history_list.viewport().height() // (entry.height() + 8) >= 6
    page._select_results_button.click()
    _drain(window)
    assert (entry.height(), title.geometry(), title.text()) == before
    page._cancel_delete_button.click()
    assert checkbox(page, 0).isHidden()
    assert page._checked_names == set()
    assert not facade.batch_calls
    assert "已删除" not in page._status_label.text()


@pytest.mark.parametrize("target", ["title", "metadata", "checkbox", "right-edge"])
def test_delete_mode_whole_row_click_toggles_exactly_once(qt_app, sources, target):
    from PySide6.QtCore import QPoint
    window, _ = archive(qt_app, sources)
    window.show()
    page = window.local_data_page
    page._enter_delete_button.click()
    _drain(window)
    item = page._history_list.item(0)
    entry = page._history_list.itemWidget(item)
    controls = {"title": entry.findChild(QLabel, "archiveEntryTitle"),
                "metadata": entry.findChild(QLabel, "archiveEntryMeta"),
                "checkbox": checkbox(page, 0)}
    if target == "right-edge":
        rect = page._history_list.visualItemRect(item)
        point = QPoint(rect.right() - 8, rect.center().y())
    else:
        control = controls[target]
        point = control.mapTo(page._history_list.viewport(), control.rect().center())
    for expected in ({"a"}, set()):
        QTest.mouseClick(page._history_list.viewport(), Qt.MouseButton.LeftButton, pos=point)
        assert page._checked_names == expected, (point, page._history_list.visualItemRect(item), controls.get(target).geometry() if target in controls else None)
        assert checkbox(page, 0).isChecked() == bool(expected)


@pytest.mark.parametrize("deletion_mode", [False, True])
def test_double_click_opens_only_in_browse_and_never_double_toggles(qt_app, sources, deletion_mode):
    window, facade = archive(qt_app, sources)
    window.show()
    page = window.local_data_page
    opened = []
    facade.get_report_package_html_path = lambda name: name
    page._report_opener = lambda path: opened.append(path) or True
    if deletion_mode:
        page._enter_delete_button.click()
    _drain(window)
    viewport = page._history_list.viewport()
    point = page._history_list.visualItemRect(page._history_list.item(0)).center()
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(viewport, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=point)
    assert opened == ([] if deletion_mode else ["a"])
    assert page._checked_names == ({"a"} if deletion_mode else set())


def test_success_feedback_expires_but_partial_failure_remains(qt_app, sources):
    window, facade = archive(qt_app, sources)
    window.show()
    page = window.local_data_page
    page._enter_delete_button.click()
    page._select_results_button.click()
    page._confirm_delete_reports = lambda names, kept: True
    facade.failed_names = {"b"}
    page._delete_checked_button.click()
    assert "2 份" in page._status_label.text() and "1 份未能删除" in page._status_label.text()
    assert page._delete_mode and not page._feedback_timer.isActive()
    facade.failed_names.clear()
    page._delete_checked_button.click()
    assert not page._delete_mode
    assert "已删除 1 份报告" in page._status_label.text()
    assert page._feedback_timer.isActive() and page._feedback_timer.interval() == 4000
    QTest.qWait(4200)
    assert not page._status_label.isVisibleTo(window)


def test_leaving_delete_mode_does_not_revive_a_pending_open(qt_app, sources):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    opened = []
    facade.get_report_package_html_path = lambda name: name
    page._report_opener = lambda path: opened.append(path) or True
    executor = _QueuedExecutor()
    page._executor = executor
    page._history_list.setCurrentRow(0)
    page._open_report_button.click()
    page._enter_delete_button.click()
    page._cancel_delete_button.click()
    executor.succeed(0)
    assert opened == []


def test_deleting_disables_mode_changes_and_keeps_progress_visible(qt_app, sources):
    window, _ = archive(qt_app, sources)
    page = window.local_data_page
    page._enter_delete_button.click()
    page._select_results_button.click()
    page._confirm_delete_reports = lambda names, kept: True
    executor = _QueuedExecutor()
    page._executor = executor
    page._delete_checked_button.click()
    assert page._status_label.text() == "正在删除…"
    assert not page._cancel_delete_button.isEnabled()
    assert not page._clear_checks_button.isEnabled()
    assert not page._select_results_button.isEnabled()
    page._set_delete_mode(False)
    assert page._delete_mode and page._checked_names == {"a", "b", "c"}
    executor.succeed(0)
    assert not page._delete_checked_button.isVisibleTo(window)
    assert not page._enter_delete_button.isEnabled()  # Rescan still pending.
    executor.succeed(1)
    assert "已删除 3 份报告" in page._status_label.text()


def test_new_error_stops_old_success_feedback_timer(qt_app, sources):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    page._enter_delete_button.click()
    page._select_results_button.click()
    page._confirm_delete_reports = lambda names, kept: True
    page._delete_checked_button.click()
    assert page._feedback_timer.isActive()
    facade._list_reports_error = FacadeError("report_list_failed", "新的读取失败。")
    page.refresh()
    assert not page._feedback_timer.isActive()
    assert page._status_label.text() == "新的读取失败。"


def test_archive_uses_named_entries_and_independent_checks(qt_app, sources):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    assert isinstance(page._history_list, QListWidget)
    assert page._history_list.item(0).text() == ""  # Native delegate must not duplicate the card labels.
    assert "Alpha" in page._history_list.item(0).data(Qt.ItemDataRole.AccessibleTextRole)
    entry = page._history_list.itemWidget(page._history_list.item(0))
    assert entry.findChild(QLabel, "archiveEntryTitle").text() == "Alpha"
    assert "QQ" in entry.findChild(QLabel, "archiveEntryMeta").text()
    assert "42" in entry.findChild(QLabel, "archiveEntryMeta").text()
    assert "全部消息" in entry.findChild(QLabel, "archiveEntryScope").text()
    window.show()
    _drain(window)
    QTest.mouseClick(entry.findChild(QLabel, "archiveEntryTitle"), Qt.MouseButton.LeftButton)
    assert page._selected_package_name() == "a"
    assert not checkbox(page, 0).isChecked()
    assert not page._delete_checked_button.isEnabled()
    page._enter_delete_button.click()
    QTest.mouseClick(checkbox(page, 1), Qt.MouseButton.LeftButton)
    assert page._selected_package_name() == "a"
    page._history_list.setCurrentRow(2)
    assert page._selected_package_name() == "c"
    assert page._checked_names == {"b"}


def test_checks_survive_search_and_select_only_visible_results(qt_app, sources):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    page._enter_delete_button.click()
    checkbox(page, 0).setChecked(True)
    page._search_input.setText("Beta")
    page._select_results_button.click()
    assert page._checked_names == {"a", "b"}
    assert "2 份" in page._checked_count_label.text()
    assert "筛选外 1 份" in page._checked_count_label.text()
    assert len(facade.list_report_packages_calls) == 1
    assert len(facade.get_report_storage_usage_calls) == 1
    page._search_input.setText("absent")
    assert not page._select_results_button.isEnabled()
    assert "筛选外 2 份" in page._checked_count_label.text()
    page._search_input.clear()
    assert checkbox(page, 0).isChecked() and checkbox(page, 1).isChecked()
    page._search_input.setText("Beta")
    page._clear_checks_button.click()
    assert page._checked_names == set()
    assert not page._delete_checked_button.isEnabled()


def test_refresh_preserves_existing_checks_and_drops_missing_reports(qt_app, sources):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    page._enter_delete_button.click()
    checkbox(page, 0).setChecked(True)
    checkbox(page, 1).setChecked(True)
    facade._reports = [facade._reports[1], _gui_report_summary("new")]
    page.refresh()
    assert page._checked_names == {"b"}
    assert checkbox(page, 0).isChecked()
    assert not checkbox(page, 1).isChecked()


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


def test_partial_failure_keeps_failed_checks_and_shows_honest_result(qt_app, sources):
    window, facade = archive(qt_app, sources)
    page = window.local_data_page
    page._enter_delete_button.click()
    facade.failed_names = {"b"}
    page._select_results_button.click()
    page._confirm_delete_reports = lambda names, kept: True
    page._delete_checked_button.click()
    assert facade.batch_calls == [("a", "b", "c")]
    assert page._checked_names == {"b"}
    assert page._history_list.count() == 1
    assert checkbox(page, 0).isChecked()
    assert "2 份" in page._status_label.text() and "1 份未能删除" in page._status_label.text()
    assert page._delete_checked_button.isEnabled()
    facade.failed_names.clear()
    page._delete_checked_button.click()
    assert facade.batch_calls[-1] == ("b",)
    assert page._checked_names == set()
    assert page._history_list.count() == 0


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
