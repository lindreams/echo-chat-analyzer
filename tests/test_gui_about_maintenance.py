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
from PySide6.QtWidgets import QApplication, QLabel, QWidget

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
