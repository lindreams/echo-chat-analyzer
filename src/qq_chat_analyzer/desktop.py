"""Desktop bootstrap shared by source and frozen entry points.

Velopack owns installer hook dispatch. It must run before importing Qt or
constructing the application, and must never apply a pending update at startup.
"""

from __future__ import annotations

import sys
from pathlib import Path


# Retain through interpreter teardown, including GUI shutdown finalizers. No
# atexit close: Windows releases this handle only when the process terminates.
_startup_admission = None


def _admit_setup_startup() -> None:
    global _startup_admission
    if sys.platform != 'win32' or getattr(sys, 'frozen', False) is not True:
        return
    executable = Path(sys.executable)
    if executable.parent.name.lower() != 'current':
        return  # Portable layout is outside the managed Setup current directory.
    root = executable.parent.parent
    if (root / '.portable').exists():
        return
    from .application.windows_update_broker import StartupAdmission

    if _startup_admission is None:
        _startup_admission = StartupAdmission(root / '.echo-startup-admission')


def main(argv: list[str] | None = None) -> int:
    import velopack

    arguments = list(sys.argv[1:] if argv is None else argv)
    velopack.App().set_args(arguments).set_auto_apply_on_startup(False).run()

    try:
        _admit_setup_startup()
    except (OSError, ValueError):
        # Also reject unknown IO/reparse failures; never import GUI/providers.
        # A frozen windowed executable may have no stderr.
        if sys.stderr is not None:
            print('Echo startup admission unavailable. Close this launch and retry later.',
                  file=sys.stderr)
        return 75

    from .gui.app import _run_gui

    return _run_gui(arguments)
