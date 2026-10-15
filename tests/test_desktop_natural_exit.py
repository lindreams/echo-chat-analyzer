"""Normal completion returns; watchdog and timeout still bound process exit."""
import threading
import time

from qq_chat_analyzer.gui import app
from qq_chat_analyzer.gui.shutdown import ShutdownProtocol


class Window:
    def __init__(self, owner):
        self.protocol = ShutdownProtocol()
        self.owner = owner

    def begin_shutdown(self):
        return self.protocol.begin(self.owner)

    def await_shutdown(self, timeout):
        return self.protocol.wait(timeout)


def test_completed_cleanup_returns_without_forced_exit():
    cleaned = threading.Event()
    exits = []
    window = Window(cleaned.set)
    app._finish_process_exit(0, window=window, hard_exit=exits.append)
    assert cleaned.is_set()
    assert exits == []


def test_timeout_and_watchdog_cannot_force_exit_twice(monkeypatch):
    monkeypatch.setattr(app, 'SHUTDOWN_WAIT_SECONDS', 0.02)
    original = app._arm_forced_exit
    monkeypatch.setattr(app, '_arm_forced_exit',
                        lambda code, exit: original(code, exit, delay=0.01))
    release = threading.Event()
    exits = []
    try:
        app._finish_process_exit(7, window=Window(lambda: release.wait(2)),
                                 hard_exit=exits.append)
        time.sleep(0.03)
        assert exits == [7]
    finally:
        release.set()


def test_running_cleanup_is_awaited_before_natural_exit():
    cleaned = threading.Event()
    def owner():
        time.sleep(0.02)
        cleaned.set()
    exits = []
    window = Window(owner)
    app._finish_process_exit(0, window=window, hard_exit=exits.append)
    assert cleaned.is_set()
    assert exits == []
