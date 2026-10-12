"""Update permission requires quiescent GUI producers as well as facade evidence."""
import threading
import os
from pathlib import Path
import subprocess
import sys

import pytest

from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
from PySide6.QtWidgets import QApplication

from qq_chat_analyzer.application.facade import ChatAnalyzerFacade, ShutdownResult
from qq_chat_analyzer.gui.main_window import MainWindow
from qq_chat_analyzer.gui import workers


@pytest.mark.slow_integration
def test_no_gui_work_can_report_idle():
    # Other GUI tests can retain relays. Verify the fresh-process claim in a
    # genuinely fresh process, without clearing evidence of existing work.
    env = os.environ.copy()
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
    env['QT_QPA_PLATFORM'] = 'offscreen'
    completed = subprocess.run([
        sys.executable, '-c',
        'from PySide6.QtWidgets import QApplication; '
        'from qq_chat_analyzer.gui import workers; '
        'application = QApplication([]); '
        'raise SystemExit(0 if workers.shutdown() is True else 1)',
    ], env=env, capture_output=True, timeout=8)
    assert completed.returncode == 0, completed.stderr.decode(errors='replace')


def test_running_worker_blocks_update_permission():
    application = QApplication.instance() or QApplication([])
    started, release = threading.Event(), threading.Event()
    def operation():
        started.set()
        release.wait(2)
    window = MainWindow(ChatAnalyzerFacade())
    workers.submit(operation, on_success=lambda _: None, on_error=lambda *_: None)
    try:
        assert started.wait(1)
        window.close()
        assert window.await_shutdown(1)
        assert not window.shutdown_protocol.result.can_apply_update
        assert any(step.name == 'gui_workers' and step.status.value == 'unknown'
                   for step in window.shutdown_protocol.result.steps)
    finally:
        release.set()
        QThreadPool.globalInstance().waitForDone(2000)
        application.processEvents()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)


def test_empty_facade_evidence_cannot_be_replaced_by_idle_gui_success():
    application = QApplication.instance() or QApplication([])
    class Facade(ChatAnalyzerFacade):
        def shutdown(self):
            return ShutdownResult()
    window = MainWindow(Facade())
    try:
        window.close()
        assert window.await_shutdown(1)
        assert not window.shutdown_protocol.result.can_apply_update
    finally:
        window.deleteLater()
        QCoreApplication.sendPostedEvents(window, QEvent.Type.DeferredDelete)
