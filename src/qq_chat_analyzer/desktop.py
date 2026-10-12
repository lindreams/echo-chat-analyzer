"""Desktop bootstrap shared by source and frozen entry points.

Velopack owns installer hook dispatch. It must run before importing Qt or
constructing the application, and must never apply a pending update at startup.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    import velopack

    arguments = list(sys.argv[1:] if argv is None else argv)
    velopack.App().set_args(arguments).set_auto_apply_on_startup(False).run()

    from .gui.app import _run_gui

    return _run_gui(arguments)
