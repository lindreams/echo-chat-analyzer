"""The updater's hook dispatch must precede every desktop GUI import."""

from __future__ import annotations

import importlib
import importlib.abc
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_importing_frozen_entry_does_not_import_gui(monkeypatch):
    class BlockGUI(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "qq_chat_analyzer.gui.app" or fullname.startswith("PySide6"):
                raise AssertionError("GUI imported before bootstrap")

    monkeypatch.delitem(sys.modules, "qq_chat_analyzer.gui.app", raising=False)
    monkeypatch.setattr(sys, "meta_path", [BlockGUI(), *sys.meta_path])
    entry = runpy.run_path(str(ROOT / "desktop_entry.py"), run_name="entry_import_test")
    assert callable(entry["main"])


@pytest.mark.parametrize("entry", ["desktop", "frozen", "module"])
@pytest.mark.parametrize("hook", [False, True])
def test_bootstrap_disables_auto_apply_before_gui(monkeypatch, entry, hook):
    events = []
    arguments = ["--veloapp-install", "0.1.0"] if hook else ["fictional-argument"]
    monkeypatch.delitem(sys.modules, "qq_chat_analyzer.gui.app", raising=False)

    class BlockEarlyGUI(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "qq_chat_analyzer.gui.app":
                raise AssertionError("GUI imported before bootstrap")

    monkeypatch.setattr(sys, "meta_path", [BlockEarlyGUI(), *sys.meta_path])

    class App:
        def set_args(self, args):
            assert args == arguments
            events.append("args")
            return self

        def set_auto_apply_on_startup(self, value):
            assert value is False
            events.append("auto-apply-disabled")
            return self

        def run(self):
            assert "qq_chat_analyzer.gui.app" not in sys.modules
            events.append("bootstrap")
            if hook:
                raise SystemExit(0)
            monkeypatch.setitem(sys.modules, "qq_chat_analyzer.gui.app", SimpleNamespace(
                _run_gui=lambda args: events.append(("gui", args)) or 7,
            ))

    monkeypatch.setitem(sys.modules, "velopack", SimpleNamespace(App=App))
    monkeypatch.setattr(sys, "argv", ["fictional-echo", *arguments])

    def invoke():
        if entry == "desktop":
            return importlib.import_module("qq_chat_analyzer.desktop").main(arguments)
        if entry == "frozen":
            runpy.run_path(str(ROOT / "desktop_entry.py"), run_name="__main__")
        else:
            runpy.run_path(str(ROOT / "src/qq_chat_analyzer/gui/__main__.py"),
                           run_name="__main__")

    if hook or entry != "desktop":
        with pytest.raises(SystemExit) as result:
            invoke()
        assert result.value.code == (0 if hook else 7)
    else:
        assert invoke() == 7
    assert events == ["args", "auto-apply-disabled", "bootstrap"] + (
        [] if hook else [("gui", arguments)]
    )
