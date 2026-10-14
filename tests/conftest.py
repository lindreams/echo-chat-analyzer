"""Keep default user-data paths inside each automated test's sandbox."""

from pathlib import Path
import sys

import pytest


@pytest.fixture(autouse=True)
def release_test_widgets():
    """Delete this test's Qt roots while QApplication is still alive."""
    # Do not import or initialize Qt for tests that do not use it.
    widgets = sys.modules.get("PySide6.QtWidgets")
    if widgets is None:
        yield
        return

    application_type = widgets.QApplication
    if not isinstance(application_type, type):
        yield
        return

    app = application_type.instance()
    existing = set(app.allWidgets()) if isinstance(app, application_type) else set()
    yield

    app = application_type.instance()
    if not isinstance(app, application_type):
        return

    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid

    # Higher-scope fixtures have already been set up; preserve their widgets,
    # including pre-existing children that a test may have reparented.
    roots = [widget for widget in app.allWidgets()
             if widget not in existing and widget.parentWidget() is None
             and not any(child in existing
                         for child in widget.findChildren(widgets.QWidget))]
    for widget in roots:
        if isValid(widget):
            widget.deleteLater()
    for widget in roots:
        if isValid(widget):
            # Target only our roots: do not drain timers or another fixture's
            # pending DeferredDelete events. Parent deletion owns its children.
            QCoreApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def release_finished_worker_relays():
    """Detach this test's finished worker relays from the module registry.

    ``qq_chat_analyzer.gui.workers`` keeps every submitted worker and its
    callback relay in module-global sets, and ``workers.is_idle()`` reads them to
    report whether the GUI is busy. A relay leaves ``_RELAYS`` only when the
    queued ``finished`` slot runs on the thread that created it, so a test that
    destroys a signal source, or that starts the connection flow from a pool
    thread, leaves a relay behind that no later test can release. Every
    following test then sees a busy GUI even though no work is running.

    Only relays this test added, and only once their worker stopped running, are
    detached. ``_PENDING`` and pre-existing relays stay untouched, so genuinely
    running work still reports busy.
    """
    # Do not import or initialize Qt for tests that do not use it.
    registry = sys.modules.get("qq_chat_analyzer.gui.workers")
    if registry is None:
        yield
        return

    existing = set(registry._RELAYS)
    yield

    for relay in tuple(registry._RELAYS):
        if any(relay is kept for kept in existing):
            continue
        if any(relay is getattr(worker, "_callback_relay", None)
               for worker in registry._PENDING):
            continue
        registry._RELAYS.discard(relay)


@pytest.fixture(autouse=True)
def isolate_qq_runtime_ownership(monkeypatch):
    """A fictional launch must never leave a PID for another test to kill."""
    from qq_chat_analyzer.application.qq import qq_process_registry, qq_runtime_session

    monkeypatch.setattr(
        qq_process_registry, "_DEFAULT_REGISTRY",
        qq_process_registry.QQProcessRegistry(terminator=lambda _pid: True),
    )
    monkeypatch.setattr(qq_runtime_session, "_DEFAULT_SESSION", qq_runtime_session.QQRuntimeSession())


@pytest.fixture(autouse=True)
def isolate_user_data(tmp_path, monkeypatch):
    home = tmp_path / "test-home"
    for variable, directory in {
        "LOCALAPPDATA": tmp_path / "local-app-data",
        "APPDATA": tmp_path / "roaming-app-data",
        "USERPROFILE": home,
        "HOME": home,
        "XDG_DATA_HOME": tmp_path / "xdg-data",
        "XDG_CONFIG_HOME": tmp_path / "xdg-config",
        "XDG_CACHE_HOME": tmp_path / "xdg-cache",
    }.items():
        monkeypatch.setenv(variable, str(directory))
    # Cover home fallback and providers using Path.home(), including tests
    # that remove LOCALAPPDATA. Individual tests can still override this.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))


@pytest.fixture(scope="function")
def qq_asset_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Point the QQ resolver at a throwaway directory of fake PNGs."""
    from qq_chat_analyzer.presentation import expression_assets

    root = tmp_path / "qq-emojis"
    root.mkdir()
    monkeypatch.setattr(
        expression_assets, "QQ_ASSET_ROOT", str(root), raising=False
    )
    monkeypatch.setattr(
        expression_assets, "_qq_asset_index", None, raising=False
    )
    return root
