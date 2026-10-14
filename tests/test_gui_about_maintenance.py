"""Offline contracts for the single main-window About page.

Updates and maintenance share one centered surface. Setup offers a disabled
uninstall entry; Portable explains removal. Directory actions never create,
change or delete user data, and cannot overwrite the update status.
"""
import importlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QUrl
from PySide6.QtGui import QFontDatabase, QFontInfo
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QLabel, QWidget

from qq_chat_analyzer.application.installable_update_service import InstallableUpdateResult
from test_gui import StubFacade


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def cleanup_windows(app):
    original = set(app.topLevelWidgets())
    yield
    for widget in set(app.topLevelWidgets()) - original:
        widget.hide()
        widget.deleteLater()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


# Wrapped Chinese text needs a real glyph source: the offscreen font database
# otherwise paints tofu boxes, which are narrower than real text and would hide
# a squeezed label instead of reproducing it. The font is registered for one
# test and removed again, so no other suite's metrics change.
CJK_FONT_FILES = (Path(r"C:\Windows\Fonts\msyh.ttc"),)


@pytest.fixture
def cjk_font(app):
    loaded = [QFontDatabase.addApplicationFont(str(path))
              for path in CJK_FONT_FILES if path.is_file()]
    loaded = [font_id for font_id in loaded if font_id != -1]
    try:
        yield
    finally:
        for font_id in loaded:
            QFontDatabase.removeApplicationFont(font_id)


@pytest.fixture
def echo_theme(app):
    from qq_chat_analyzer.gui.theme import BASE_QSS
    previous = app.styleSheet()
    app.setStyleSheet(BASE_QSS)
    try:
        yield
    finally:
        app.setStyleSheet(previous)


class Executor:
    def __init__(self):
        self.tasks = []

    def __call__(self, operation, **callbacks):
        task = SimpleNamespace(operation=operation, **callbacks)
        self.tasks.append(task)
        return task


class Facade(StubFacade):
    """Release-only facade: no installable update core is wired in."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def check_for_updates(self, *, manual=False):
        self.calls.append(manual)
        return SimpleNamespace(status="up_to_date")


class CoreFacade(Facade):
    """A facade that also exposes the installable update core's snapshot."""

    def __init__(self, status="downloaded"):
        super().__init__()
        self.result = InstallableUpdateResult(status, "0.1.0", "0.2.0", 100)

    def get_update_status(self):
        return self.result

    def prepare_update_install(self):
        raise AssertionError("the maintenance contract never installs")


def _module():
    return importlib.import_module("qq_chat_analyzer.gui.update_dialog")


def _make_setup_tree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "EchoSetup"
    current = root / "current"
    current.mkdir(parents=True)
    (root / "Update.exe").write_bytes(b"fictional, non-executable updater")
    (current / "sq.version").write_bytes(b"<package><metadata><id>Echo</id></metadata></package>")
    return root, current


def _process() -> None:
    QApplication.instance().processEvents()


def _show(module, facade=None):
    """Build and show the About window; identity and data paths are pinned."""
    facade = facade if facade is not None else Facade()
    executor = Executor()
    from qq_chat_analyzer.gui.main_window import MainWindow
    window = MainWindow(facade, executor=executor)
    window.show()
    window.home_page._about_btn.click()
    dialog = window.about_page
    _process()
    return dialog, facade, executor


def _pin_maintenance(monkeypatch, module, *, kind, program_dir, data_dir):
    """Monkeypatch the dialog's install identity and data root per test."""
    monkeypatch.setattr(
        module, "detect_install_location",
        lambda executable, *, frozen: module.InstallLocation(kind, program_dir))
    monkeypatch.setattr(module, "user_data_root", lambda: data_dir)




def _visible_texts(widget) -> str:
    """Every string painted in the window right now, tooltips excluded."""
    painted = []
    for child in widget.findChildren(QWidget):
        getter = getattr(child, "text", None)
        if child.isVisible() and callable(getter):
            painted.append(str(getter()))
    return "\n".join(painted)


def _squeezed_labels(widget) -> list[str]:
    """Visible wrapped labels that got less height than their text needs."""
    squeezed = []
    for label in widget.findChildren(QLabel):
        if not label.isVisible() or not label.wordWrap():
            continue
        needed = label.heightForWidth(label.width())
        if needed > 0 and label.height() < needed:
            squeezed.append(f"{label.objectName()}:{label.height()}<{needed}")
    return squeezed


def _assert_fits(widget) -> None:
    """No wrapped text is clipped, and the window is as tall as its layout asks."""
    assert _squeezed_labels(widget) == []
    assert widget.height() >= widget.layout().heightForWidth(widget.width())


@pytest.mark.parametrize("status", ["idle", "downloaded"])
def test_about_functional_fonts_and_right_aligned_outlined_actions(
        app, cjk_font, echo_theme, monkeypatch, tmp_path, status):
    module = _module()
    _pin_maintenance(monkeypatch, module, kind=module.InstallKind.SETUP,
                     program_dir=tmp_path / "EchoSetup", data_dir=tmp_path / "data")
    page, _, _ = _show(module, CoreFacade(status))
    reference = page.window().home_page.findChild(QLabel, "homeSourceDescription")
    family = QFontInfo(reference.font()).family()
    maintenance = page.maintenance_section
    widgets = [page.findChild(QLabel, "aboutTitle"), page.version_label,
               page.findChild(QLabel, "updateSection"), page.status_label,
               maintenance.program_heading, maintenance.data_heading,
               maintenance.footer_note, page.check_button, page.install_button,
               maintenance.open_program_button, maintenance.open_data_button]
    for widget in widgets:
        assert QFontInfo(widget.font()).family() == family
        assert QFontInfo(widget.font()).pixelSize() >= 15
    for button in (page.check_button, maintenance.open_program_button,
                   maintenance.open_data_button):
        assert button.height() >= 38
        assert button.mapTo(page.page_content, button.rect().topRight()).x() == page.page_content.width() - 1
        rendered = button.grab().toImage()
        x = rendered.width() // 2
        assert rendered.pixelColor(x, 0) != rendered.pixelColor(x, 3)
    assert page.status_label.mapTo(page, page.status_label.rect().topLeft()).x() < page.check_button.mapTo(page, page.check_button.rect().topLeft()).x()
    assert not maintenance.uninstall_button.isEnabled()
    _assert_fits(page)


@pytest.mark.parametrize("status", ["idle", "downloaded"])
def test_about_spacious_rows_keep_uninstall_note_with_its_action(
        app, cjk_font, echo_theme, monkeypatch, tmp_path, status):
    module = _module()
    _pin_maintenance(monkeypatch, module, kind=module.InstallKind.SETUP,
                     program_dir=tmp_path / "EchoSetup", data_dir=tmp_path / "data")
    page, _, _ = _show(module, CoreFacade(status))
    maintenance = page.maintenance_section
    assert 30 <= QFontInfo(page.findChild(QLabel, "aboutTitle").font()).pixelSize() <= 32
    for heading, button in ((maintenance.program_heading, maintenance.open_program_button),
                            (maintenance.data_heading, maintenance.open_data_button)):
        assert 72 <= heading.height() <= 80
        assert 42 <= button.height() <= 44
        assert abs(heading.mapTo(page, heading.rect().center()).y() - button.mapTo(page, button.rect().center()).y()) <= 1
    note = maintenance.footer_note
    uninstall = maintenance.uninstall_button
    assert note.isVisible() and not uninstall.isEnabled()
    assert note.mapTo(page, note.rect().topLeft()).x() < uninstall.mapTo(page, uninstall.rect().topLeft()).x()
    assert abs(note.mapTo(page, note.rect().center()).y() - uninstall.mapTo(page, uninstall.rect().center()).y()) < 30
    assert page.status_label.height() >= 72
    assert abs(page.status_label.mapTo(page, page.status_label.rect().center()).y() - page.check_button.mapTo(page, page.check_button.rect().center()).y()) <= 1


def test_about_rows_are_divided_and_update_states_keep_the_same_boundaries(
        app, cjk_font, echo_theme, monkeypatch, tmp_path):
    module = _module()
    _pin_maintenance(monkeypatch, module, kind=module.InstallKind.SETUP,
                     program_dir=tmp_path / "EchoSetup", data_dir=tmp_path / "data")
    facade = CoreFacade("idle")
    page, _, _ = _show(module, facade)
    section = page.maintenance_section
    rules = sorted(section.findChildren(QFrame, "aboutRule"),
                   key=lambda line: line.mapTo(page, line.rect().topLeft()).y())
    assert len(rules) == 3
    headings = [section.program_heading, section.data_heading]
    for heading, rule in zip(headings, rules):
        assert rule.mapTo(page, rule.rect().topLeft()).y() == heading.mapTo(page, heading.rect().bottomLeft()).y() + 1
        assert rule.height() == 1 and rule.width() == page.page_content.width()
    assert rules[1].mapTo(page, rules[1].rect().bottomLeft()).y() + 1 == section.uninstall_button.parentWidget().mapTo(page, section.uninstall_button.parentWidget().rect().topLeft()).y()
    assert rules[2].mapTo(page, rules[2].rect().bottomLeft()).y() == section.mapTo(page, section.rect().bottomLeft()).y()
    assert page.status_label.height() == section.program_heading.height() == section.data_heading.height()
    assert page.page_content.mapTo(page, page.page_content.rect().topLeft()).y() == 46
    tracked = [page.page_content, section, page.findChild(QLabel, "updateSection"), *rules]
    before = [(w.mapTo(page, w.rect().topLeft()), w.size()) for w in tracked]
    facade.result = module.InstallableUpdateResult("downloaded", "0.1.0", "0.2.0", 100)
    page._restore_status()
    _process()
    assert page.install_button.isVisible()
    assert [(w.mapTo(page, w.rect().topLeft()), w.size()) for w in tracked] == before


def test_small_about_can_reach_last_row_without_clipping(
        app, cjk_font, echo_theme, monkeypatch, tmp_path):
    module = _module()
    _pin_maintenance(monkeypatch, module, kind=module.InstallKind.SETUP,
                     program_dir=tmp_path / "EchoSetup", data_dir=tmp_path / "data")
    page, _, _ = _show(module, CoreFacade("downloaded"))
    page.window().resize(800, 600)
    _process()
    assert page.window().size().width() == 800 and page.window().size().height() == 600
    assert page.page_content.width() <= page.width() - 32
    assert _squeezed_labels(page) == []
    scroll = page.scroll_area
    scroll.ensureWidgetVisible(page.maintenance_section.footer_note)
    _process()
    note = page.maintenance_section.footer_note
    assert scroll.viewport().rect().contains(note.mapTo(scroll.viewport(), note.rect().center()))
    assert scroll.horizontalScrollBar().maximum() == 0


def test_detect_install_location_classifies_setup(tmp_path):
    module = _module()
    root, current = _make_setup_tree(tmp_path)
    location = module.detect_install_location(current / "Echo.exe", frozen=True)
    assert location.kind is module.InstallKind.SETUP
    assert location.program_dir == root


def test_detect_install_location_classifies_plain_zip_portable(tmp_path):
    module = _module()
    program = tmp_path / "Echo-portable"
    program.mkdir()
    (program / "Echo.exe").write_bytes(b"fictional frozen executable")
    location = module.detect_install_location(program / "Echo.exe", frozen=True)
    assert location.kind is module.InstallKind.PORTABLE
    assert location.program_dir == program


def test_detect_install_location_rejects_setup_without_updater(tmp_path):
    module = _module()
    root, current = _make_setup_tree(tmp_path)
    (root / "Update.exe").unlink()
    location = module.detect_install_location(current / "Echo.exe", frozen=True)
    assert location.kind is module.InstallKind.PORTABLE
    assert location.program_dir == current


def test_detect_install_location_portable_marker_wins_over_updater(tmp_path):
    module = _module()
    root, current = _make_setup_tree(tmp_path)
    (root / ".portable").write_bytes(b"")
    location = module.detect_install_location(current / "Echo.exe", frozen=True)
    assert location.kind is module.InstallKind.PORTABLE
    assert location.program_dir == current


def test_detect_install_location_ignores_source_runs(tmp_path):
    module = _module()
    location = module.detect_install_location(tmp_path / "python.exe", frozen=False)
    assert location.kind is module.InstallKind.UNKNOWN
    assert location.program_dir is None


def test_setup_view_offers_uninstall_and_both_locations(tmp_path):
    module = _module()
    view = module.install_maintenance_view(
        module.InstallKind.SETUP, program_dir=tmp_path / "EchoSetup", data_dir=tmp_path / "data")
    assert view.program_dir == tmp_path / "EchoSetup"
    assert view.data_dir == tmp_path / "data"
    assert "\u5b89\u88c5" in view.program_title
    assert view.show_open_program and view.show_open_data and view.show_uninstall
    assert view.portable_note == ""


def test_portable_view_omits_uninstall_and_explains_removal(tmp_path):
    module = _module()
    view = module.install_maintenance_view(
        module.InstallKind.PORTABLE, program_dir=tmp_path / "Echo-portable", data_dir=tmp_path / "data")
    assert "\u4fbf\u643a\u7248" in view.program_title
    assert view.show_open_program and view.show_open_data
    assert not view.show_uninstall
    assert "\u5220\u9664" in view.portable_note


def test_unknown_view_keeps_only_the_data_location(tmp_path):
    module = _module()
    view = module.install_maintenance_view(
        module.InstallKind.UNKNOWN, program_dir=None, data_dir=tmp_path / "data")
    assert view.program_dir is None
    assert view.data_dir == tmp_path / "data"
    assert not view.show_open_program
    assert not view.show_uninstall
    assert view.show_open_data


@pytest.mark.parametrize("status", ["idle", "downloading", "downloaded"])
@pytest.mark.parametrize("size", [(1200, 760), (800, 600)])
def test_merged_about_is_centered_and_contains_all_sections(app, cjk_font, echo_theme, monkeypatch, tmp_path, status, size):
    module = _module()
    _pin_maintenance(monkeypatch, module, kind=module.InstallKind.SETUP,
                     program_dir=tmp_path / "EchoSetup", data_dir=tmp_path / "data")
    page, _, executor = _show(module, CoreFacade(status))
    window = page.window()
    window.resize(*size)
    _process()
    assert window.stack.currentWidget() is page
    assert page.findChild(QLabel, "homeTitle") is None
    assert not hasattr(page, "maintenance_page")
    assert not hasattr(page, "maintenance_button")
    assert not hasattr(window, "show_maintenance_page")
    assert window.stack.count() == 7
    assert page.size() == window.centralWidget().size()
    assert not window._title_label.isVisible()
    assert not window._home_button.isVisible()
    content = page.page_content
    assert 680 <= content.width() <= 940
    if size == (1200, 760):
        assert 900 <= content.width() <= 940
    viewport = page.scroll_area.viewport()
    assert abs(content.mapTo(viewport, content.rect().center()).x() - viewport.rect().center().x()) <= 1
    assert content.y() >= 24
    if size == (1200, 760):
        assert content.mapTo(page, content.rect().topLeft()).y() <= 80
        assert content.mapTo(page, content.rect().bottomLeft()).y() < page.height() - 24
        assert content.height() >= 600
    title = page.findChild(QLabel, "aboutTitle")
    assert page.findChild(QLabel, "aboutProduct") is None
    update_heading = page.findChild(QLabel, "updateSection")
    maintenance_heading = page.maintenance_section.findChild(QLabel, "maintenanceSection")
    assert title.isVisible() and update_heading.isVisible() and maintenance_heading.isVisible()
    assert title.mapTo(page, title.rect().topLeft()).y() < update_heading.mapTo(page, update_heading.rect().topLeft()).y()
    assert update_heading.mapTo(page, update_heading.rect().topLeft()).y() < maintenance_heading.mapTo(page, maintenance_heading.rect().topLeft()).y()
    reference = window.home_page.findChild(QLabel, "homeSourceDescription")
    assert QFontInfo(update_heading.font()).family() == QFontInfo(reference.font()).family()
    assert QFontInfo(page.check_button.font()).family() == QFontInfo(reference.font()).family()
    assert page.check_button.isVisible()
    assert page.install_button.isVisible() == (status == "downloaded")
    assert page.progress_bar.isVisible() == (status == "downloading")
    section = page.maintenance_section
    assert section.open_program_button.isVisible() and section.open_data_button.isVisible()
    assert section.uninstall_button.isVisible() and not section.uninstall_button.isEnabled()
    assert page.findChildren(QDialog) == []
    assert executor.tasks == []
    _assert_fits(page)
    page.close()


def test_setup_directory_actions_and_disabled_uninstall(app, monkeypatch, tmp_path):
    module = _module()
    program, data = tmp_path / "EchoSetup", tmp_path / "never-created-data"
    _pin_maintenance(monkeypatch, module, kind=module.InstallKind.SETUP,
                     program_dir=program, data_dir=data)
    opened = []
    monkeypatch.setattr(module.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    page, facade, executor = _show(module)
    section = page.maintenance_section
    assert str(program) not in _visible_texts(page) and str(data) not in _visible_texts(page)
    assert str(program) in section.open_program_button.toolTip()
    assert str(data) in section.open_data_button.toolTip()
    section.open_program_button.click()
    section.open_data_button.click()
    section.uninstall_button.click()
    assert opened == [QUrl.fromLocalFile(str(program)).toString(), QUrl.fromLocalFile(str(data)).toString()]
    assert not data.exists()
    assert executor.tasks == [] and facade.calls == []
    page.close()


@pytest.mark.parametrize("kind", ["PORTABLE", "UNKNOWN"])
def test_install_identity_still_controls_maintenance_actions(app, monkeypatch, tmp_path, kind):
    module = _module()
    program = tmp_path / "Echo-portable" if kind == "PORTABLE" else None
    _pin_maintenance(monkeypatch, module, kind=getattr(module.InstallKind, kind),
                     program_dir=program, data_dir=tmp_path / "data")
    page, _, _ = _show(module)
    section = page.maintenance_section
    assert section.open_program_button.isVisible() == (kind == "PORTABLE")
    assert section.open_data_button.isVisible()
    assert not section.uninstall_button.isVisible()
    assert section.portable_note.isVisible() == (kind == "PORTABLE")
    if kind == "PORTABLE":
        assert "删除" in section.portable_note.text()
    _assert_fits(page)
    page.close()


@pytest.mark.parametrize("failure", ["false", "exception"])
def test_directory_error_does_not_overwrite_update_status(app, monkeypatch, tmp_path, failure):
    module = _module()
    def open_url(_url):
        if failure == "exception":
            raise RuntimeError("fictional shell failure")
        return False
    monkeypatch.setattr(module.QDesktopServices, "openUrl", open_url)
    _pin_maintenance(monkeypatch, module, kind=module.InstallKind.SETUP,
                     program_dir=tmp_path / "EchoSetup", data_dir=tmp_path / "data")
    page, _, _ = _show(module, CoreFacade())
    before = page.status_label.text()
    page.maintenance_section.open_data_button.click()
    assert page.maintenance_section.status_label.isVisible()
    assert page.maintenance_section.status_label.text()
    assert page.status_label.text() == before
    _assert_fits(page)
    page.close()


def test_deep_paths_remain_in_tooltips_without_widening_the_page(app, monkeypatch, tmp_path):
    module = _module()
    program = tmp_path / ("fictional-long-folder-" * 10)
    _pin_maintenance(monkeypatch, module, kind=module.InstallKind.SETUP,
                     program_dir=program, data_dir=tmp_path / "data")
    page, _, _ = _show(module)
    assert str(program) in page.maintenance_section.open_program_button.toolTip()
    assert str(program) not in _visible_texts(page)
    assert page.page_content.width() <= 940
    page.close()


def test_check_returns_from_home_and_close_retires_callbacks(app, monkeypatch, tmp_path):
    module = _module()
    _pin_maintenance(monkeypatch, module, kind=module.InstallKind.SETUP,
                     program_dir=tmp_path / "EchoSetup", data_dir=tmp_path / "data")
    page, _, executor = _show(module)
    window = page.window()
    page.check_button.click()
    task = executor.tasks[0]
    page.back_button.click()
    assert window.stack.currentWidget() is window.home_page
    task.on_success(module.UpdateCheckResult("up_to_date", "0.1.0"))
    window.home_page._about_btn.click()
    assert window.stack.currentWidget() is page
    assert "最新版本" in page.status_label.text()
    assert page.check_button.isEnabled()
    page.close()
    assert page._closed and not page._status_timer.isActive()
    before = page.status_label.text()
    task.on_success(module.UpdateCheckResult("failed", "0.1.0"))
    assert page.status_label.text() == before
