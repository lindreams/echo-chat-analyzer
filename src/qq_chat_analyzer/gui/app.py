"""Compose the desktop application and its facade.

This is the only place that knows how to build a real facade with real
providers. Keeping it separate means the widgets stay injectable and testable
with stubs.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable

from ..application.facade import ChatAnalyzerFacade, ChatSource
from ..resources import resources_dir
from ..version import APP_VERSION
from ..desktop import main
from .desktop_runtime import (
    STARTUP_FAILED_MESSAGE,
    configure_logging,
    install_global_exception_handler,
    log_startup,
)
from .shutdown import DEFAULT_SHUTDOWN_WAIT_SECONDS
from .theme import BASE_QSS


_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.app")

#: How long the entry point waits for the window's shutdown protocol before it
#: gives up and forces the process out.  The protocol is bounded by the facade,
#: which gives each ordered shutdown step its own window, so this only has to
#: cover the worst-case sum of those steps.
SHUTDOWN_WAIT_SECONDS = DEFAULT_SHUTDOWN_WAIT_SECONDS

#: Last-resort delay before the process is forced out even if a shutdown step
#: ignores every bound.  Deliberately larger than ``SHUTDOWN_WAIT_SECONDS`` so
#: the protocol always gets its full window first.
FORCED_EXIT_SECONDS = SHUTDOWN_WAIT_SECONDS + 10.0

FORCED_EXIT_THREAD_NAME = "echo-exit-watchdog"


def build_facade() -> ChatAnalyzerFacade:
    """Create a facade with whatever providers this machine can offer.

    Provider construction is optional by design: a machine without QQ or
    WeChat tooling still gets a working window with those sources disabled.
    """
    from ..application.analysis_service import AnalysisApplicationService
    from ..application.qq.qq_runtime_session import QQRuntimeSession
    from ..application.report_package_catalog import ReportPackageCatalog

    # One owner for the local bridge credential of the QQ runtime Echo launches:
    # every QQ service below is wired with the same session, and the facade keeps
    # it to retire the credential after the runtime is stopped.
    session = QQRuntimeSession()
    return ChatAnalyzerFacade(
        source_builders={
            ChatSource.QQ: lambda: _qq_bundle_factory(session),
            ChatSource.WECHAT: _wechat_bundle_factory,
        },
        qq_runtime_session=session,
        analysis_service=AnalysisApplicationService(),
        report_package_catalog=ReportPackageCatalog(),
        stopwords_directory=resources_dir(),
    )


def _qq_bundle_factory(session: Any = None) -> Any:
    """Build all QQ services together on first QQ access."""
    provider_factory = _qq_provider_factory(session)
    connection_service = _optional_qq_connection_service(provider_factory)
    return SimpleNamespace(
        service=_optional_qq_service(provider_factory, session),
        connection=connection_service,
        setup=_optional_qq_setup_service(
            provider_factory,
            connection_service,
            session,
        ),
    )


def _wechat_bundle_factory() -> Any:
    """Build all WeChat services together on first WeChat access."""
    provider_factory = _wechat_provider_factory()
    connection_service = _optional_wechat_connection_service(provider_factory)
    return SimpleNamespace(
        service=_optional_wechat_service(provider_factory),
        connection=connection_service,
        setup=_optional_wechat_setup_service(
            provider_factory,
            connection_service,
        ),
    )


def _qq_provider_factory(session: Any = None) -> Any:
    """Build the one factory all QQ services share."""
    from ..application.qq.qq_provider_factory import QQProviderFactory
    from ..application.qq.qq_environment_config import QQEnvironmentConfigLoader

    return QQProviderFactory(
        config_loader=QQEnvironmentConfigLoader(), bridge_credential=session
    )


def _optional_qq_service(provider_factory: Any, session: Any = None) -> Any:
    from ..application.qq.qq_direct_database_import_service import (
        QQDirectDatabaseImportService,
    )

    return QQDirectDatabaseImportService(provider_factory=provider_factory, config_loader=getattr(provider_factory, "config_loader", None), bridge_credential=session)


def _optional_qq_connection_service(provider_factory: Any) -> Any:
    from ..application.qq.qq_connection_service import QQConnectionService

    return QQConnectionService(provider_factory=provider_factory)


def _optional_qq_setup_service(
    provider_factory: Any,
    connection_service: Any,
    session: Any = None,
) -> Any:
    from ..application.qq.qq_setup_service import QQSetupService

    return QQSetupService(
        config_loader=getattr(provider_factory, "config_loader", None),
        provider_factory=provider_factory,
        connection_service=connection_service,
        bridge_credential=session,
    )


def _wechat_provider_factory() -> Any:
    """Build the one factory both WeChat services share.

    Status checks and session reads must agree, so they are given the same
    factory rather than each constructing a provider of their own.
    """
    from ..application.wechat.wechat_provider_factory import WeChatProviderFactory

    return WeChatProviderFactory()


def _optional_wechat_service(provider_factory: Any) -> Any:
    from ..application.wechat.wechat_export_import_service import (
        WeChatExportImportService,
    )

    return WeChatExportImportService(provider_factory=provider_factory)


def _optional_wechat_connection_service(provider_factory: Any) -> Any:
    from ..application.wechat.wechat_connection_service import (
        WeChatConnectionService,
    )

    return WeChatConnectionService(provider_factory=provider_factory)


def _optional_wechat_setup_service(
    provider_factory: Any,
    connection_service: Any,
) -> Any:
    from ..application.wechat.wechat_key_service import WeChatKeyService
    from ..application.wechat.wechat_setup_service import WeChatSetupService

    return WeChatSetupService(
        provider_factory=provider_factory,
        connection_service=connection_service,
        key_service=WeChatKeyService(),
    )


def _run_gui(argv: list[str] | None = None) -> int:
    """Start the Qt event loop with the main window."""
    install_global_exception_handler()
    logger = None
    try:
        logger = configure_logging()
        log_startup(APP_VERSION)
    except Exception:
        # Diagnostics are optional; an unwritable log must not prevent GUI startup.
        logger = None

    arguments = list(sys.argv[1:] if argv is None else argv)

    from PySide6.QtWidgets import QApplication, QMessageBox

    try:
        from .main_window import MainWindow

        app = QApplication(arguments)
        app.setQuitOnLastWindowClosed(True)
        app.setStyleSheet(BASE_QSS)
        window = MainWindow(build_facade())
        window.show()
        exit_code = app.exec()
        _finish_process_exit(exit_code, window=window)
        return exit_code
    except Exception as error:
        if logger is not None:
            try:
                logger.exception("desktop startup failed", exc_info=error)
            except Exception:
                # Reporting a startup failure must not fail with the log itself.
                pass
        app = QApplication.instance()
        if app is not None:
            QMessageBox.critical(None, "\u9519\u8bef", STARTUP_FAILED_MESSAGE)
        return 1


def _finish_process_exit(
    exit_code: int,
    *,
    window: Any = None,
    hard_exit: Callable[[int], None] | None = None,
) -> None:
    """Wait, bounded, for the started shutdown protocol, then force the exit.

    Qt and CPython teardown must not decide whether Echo's owned QQ process
    tree is stopped: daemon threads are frozen when the interpreter finalizes,
    so a shutdown that was merely *started* used to be lost. The entry point
    therefore owns the outcome - it starts the window's single-flight protocol
    if the close handler had not done so, gives it one bounded window, and then
    forces the process out either way.
    """
    force_exit = hard_exit or _hard_exit
    _arm_forced_exit(exit_code, force_exit)
    _begin_window_shutdown(window)
    if _await_window_shutdown(window):
        _LOGGER.info("Echo shutdown protocol completed before process exit")
    else:
        _LOGGER.warning(
            "Echo shutdown protocol exceeded its %.1fs window; forcing exit",
            SHUTDOWN_WAIT_SECONDS,
        )
    _flush_desktop_logging()
    force_exit(exit_code)


def _begin_window_shutdown(window: Any) -> None:
    """Start the window's shutdown protocol; repeated calls are ignored."""
    begin = getattr(window, "begin_shutdown", None)
    if not callable(begin):
        return
    try:
        begin()
    except Exception as error:
        _LOGGER.warning(
            "Echo shutdown protocol could not be started error=%s",
            type(error).__name__,
        )


def _await_window_shutdown(window: Any) -> bool:
    """Wait, bounded, for the window's shutdown protocol."""
    await_shutdown = getattr(window, "await_shutdown", None)
    if not callable(await_shutdown):
        return True
    try:
        return bool(await_shutdown(SHUTDOWN_WAIT_SECONDS))
    except Exception as error:
        _LOGGER.warning(
            "Echo shutdown wait failed error=%s",
            type(error).__name__,
        )
        return False


def _arm_forced_exit(
    exit_code: int,
    hard_exit: Callable[[int], None],
    *,
    delay: float = FORCED_EXIT_SECONDS,
) -> None:
    """Force the process out if a shutdown step ignores every bound."""

    def _watchdog() -> None:
        time.sleep(delay)
        hard_exit(exit_code)

    threading.Thread(
        target=_watchdog,
        name=FORCED_EXIT_THREAD_NAME,
        daemon=True,
    ).start()


def _hard_exit(exit_code: int) -> None:
    """Force the process out without waiting for interpreter/Qt finalization."""
    os._exit(exit_code)


def _flush_desktop_logging() -> None:
    """Flush diagnostics handlers so the final shutdown lines survive."""
    loggers: list[logging.Logger] = [logging.getLogger()]
    loggers.extend(
        value
        for value in logging.root.manager.loggerDict.values()
        if isinstance(value, logging.Logger)
    )
    seen: set[int] = set()
    for logger in loggers:
        for handler in logger.handlers:
            if id(handler) in seen:
                continue
            seen.add(id(handler))
            try:
                handler.flush()
            except Exception:
                continue


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
