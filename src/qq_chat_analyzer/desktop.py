"""Desktop bootstrap shared by source and frozen entry points.

Velopack owns installer hook dispatch. It must run before importing Qt or
constructing the application, and must never apply a pending update at startup.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    import velopack

    arguments = list(sys.argv[1:] if argv is None else argv)
    from .application.setup_uninstall_service import (
        cleanup_entry, maintenance_gate, register_after_setup, register_uninstall_entry,
    )
    if len(arguments) == 2 and arguments[0] == '--echo-uninstall-cleanup':
        return cleanup_entry(arguments[1])
    (velopack.App().set_args(arguments).set_auto_apply_on_startup(False)
        .on_after_install_fast_callback(register_after_setup)
        .on_after_update_fast_callback(register_after_setup).run())

    if sys.platform == 'win32' and getattr(sys, 'frozen', False):
        try:
            with maintenance_gate():
                # Portable/foreign installations do not gain an uninstall entry.
                try:
                    register_uninstall_entry()
                except Exception:
                    pass
        except OSError:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, 'Echo 正在清理数据或卸载，请稍后再打开。', 'Echo', 0x30)
            return 1

    from .gui.app import _run_gui

    return _run_gui(arguments)
