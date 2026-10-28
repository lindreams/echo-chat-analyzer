"""The updater's hook dispatch must precede every desktop GUI import."""

from __future__ import annotations

import importlib
import importlib.abc
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.slow_integration
def test_desktop_import_does_not_require_share_or_chart_modules():
    result = subprocess.run(
        [sys.executable, "-c", """
import importlib.abc
import sys

class BlockUnusedFeatures(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('qq_chat_analyzer.presentation.share',
                                'matplotlib', 'wordcloud', 'PIL')):
            raise AssertionError('desktop imported unused feature: ' + fullname)

sys.meta_path.insert(0, BlockUnusedFeatures())
import qq_chat_analyzer.gui.app
"""],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("entry", ["desktop", "frozen", "module"])
@pytest.mark.parametrize("hook", [True])
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

        def on_after_install_fast_callback(self, callback):
            assert callable(callback)
            return self

        def on_after_update_fast_callback(self, callback):
            assert callable(callback)
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
