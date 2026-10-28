"""Behavior tests for desktop startup hardening and logging."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from unittest import mock

import pytest


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from qq_chat_analyzer import diagnostics as diagnostics_module


def _desktop_runtime():
    return importlib.import_module("qq_chat_analyzer.gui.desktop_runtime")


@pytest.fixture(autouse=True)
def _isolated_diagnostic_loggers() -> None:
    names = (
        diagnostics_module.LOGGER_NAME,
        "qq_chat_analyzer.desktop",
        "qq_chat_analyzer.providers.wechat_database_provider",
    )
    states = []
    for name in names:
        logger = logging.getLogger(name)
        states.append((logger, logger.handlers[:], logger.level, logger.propagate))
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)
        logger.propagate = True
    yield
    for logger, original_handlers, original_level, original_propagate in states:
        for handler in tuple(logger.handlers):
            if handler not in original_handlers:
                handler.close()
        logger.handlers[:] = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagate


def test_uncaught_exception_is_logged_without_leaking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dialog is requested, never shown: a real modal blocks the suite."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    module = _desktop_runtime()
    records: list[logging.LogRecord] = []
    critical = mock.Mock()
    # A live QApplication from another module would open a modal dialog here.
    monkeypatch.setattr(QApplication, "instance", staticmethod(lambda: object()))
    monkeypatch.setattr(QMessageBox, "critical", critical)

    class _RecordingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger(module.LOGGER_NAME)
    original_level = logger.level
    original_propagate = logger.propagate
    try:
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        handler = _RecordingHandler()
        logger.addHandler(handler)

        module._handle_uncaught_exception(
            RuntimeError,
            RuntimeError("secret desktop crash"),
            None,
        )

        assert records
        text = records[0].getMessage()
        assert "secret desktop crash" in text
        assert "RuntimeError" in text
        assert critical.call_count == 1
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)
        logger.propagate = original_propagate


@pytest.fixture
def desktop_startup(monkeypatch: pytest.MonkeyPatch):
    """Isolate the Qt event loop and forced process exit, keeping main real."""
    from types import SimpleNamespace
    from PySide6 import QtWidgets
    from qq_chat_analyzer.gui import app as entry, main_window

    application = mock.Mock()
    application.exec.return_value = 7
    application_class = mock.Mock(return_value=application)
    application_class.instance.return_value = application
    window = mock.Mock()
    window_class = mock.Mock(return_value=window)
    critical = mock.Mock()
    finish_exit = mock.Mock()
    build_facade = mock.Mock(return_value=object())
    logger = mock.Mock(spec=logging.Logger)
    configure = mock.Mock(return_value=logger)
    monkeypatch.setattr(QtWidgets, "QApplication", application_class)
    monkeypatch.setattr(QtWidgets.QMessageBox, "critical", critical)
    monkeypatch.setattr(main_window, "MainWindow", window_class)
    monkeypatch.setattr(entry, "build_facade", build_facade)
    monkeypatch.setattr(entry, "_finish_process_exit", finish_exit)
    monkeypatch.setattr(entry, "configure_logging", configure)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    return SimpleNamespace(
        entry=entry, application=application, window=window,
        window_class=window_class, build_facade=build_facade,
        critical=critical, finish_exit=finish_exit, logger=logger,
        configure=configure,
    )


@pytest.mark.parametrize("logging_fails", [False, True])
def test_main_starts_gui_even_when_logging_initialization_fails(
    desktop_startup, logging_fails: bool,
) -> None:
    startup = desktop_startup
    if logging_fails:
        startup.configure.side_effect = PermissionError(
            13, "Permission denied", r"C:\Users\Fictional\Private\logs\echo.log",
        )

    assert startup.entry.main([]) == 7

    startup.window.show.assert_called_once_with()
    startup.application.exec.assert_called_once_with()
    startup.finish_exit.assert_called_once_with(7, window=startup.window)
    startup.critical.assert_not_called()
    startup.configure.assert_called_once_with()


def test_windows_uninstall_entry_opens_the_shared_confirmation(desktop_startup, monkeypatch):
    from PySide6.QtCore import QTimer
    callbacks = []
    monkeypatch.setattr(QTimer, 'singleShot', lambda delay, callback: callbacks.append(callback))
    startup = desktop_startup
    assert startup.entry._run_gui(['--echo-uninstall']) == 7
    startup.window.show_about_page.assert_called_once_with()
    assert callbacks == [startup.window.request_setup_uninstall]


@pytest.mark.parametrize("logging_fails", [False, True])
def test_startup_failure_only_mentions_a_log_that_was_configured(
    desktop_startup, logging_fails: bool,
) -> None:
    """An unavailable diagnostic log must not be promised to the user."""
    startup = desktop_startup
    module = _desktop_runtime()
    if logging_fails:
        startup.configure.side_effect = PermissionError(
            13, "Permission denied", r"C:\Users\Fictional\Private\logs\echo.log",
        )
    startup.window_class.side_effect = RuntimeError("fictional startup failure")

    assert startup.entry.main([]) == 1

    startup.critical.assert_called_once()
    expected = (
        module.STARTUP_FAILED_NO_LOG_MESSAGE
        if logging_fails
        else module.STARTUP_FAILED_MESSAGE
    )
    assert startup.critical.call_args.args[-1] == expected
