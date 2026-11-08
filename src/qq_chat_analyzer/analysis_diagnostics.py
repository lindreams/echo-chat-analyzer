"""Anonymous, source-neutral timing diagnostics."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter


_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.analysis_diagnostics")


@contextmanager
def timed_stage(stage: str) -> Iterator[None]:
    """Log one fixed pipeline stage, including when the stage raises."""
    started_at = perf_counter()
    outcome, category = "success", "none"
    try:
        _LOGGER.info("[analysis-stage] stage=%s outcome=started", stage)
    except Exception:
        pass
    try:
        yield
    except BaseException as error:
        outcome = ("cancelled" if isinstance(error, (InterruptedError, KeyboardInterrupt))
                   or getattr(error, "code", None) == "analysis_cancelled" else
                   "timeout" if isinstance(error, TimeoutError) else "failed")
        category = "io_error" if isinstance(error, OSError) else "operation_failed"
        raise
    finally:
        elapsed_ms = max(0, round((perf_counter() - started_at) * 1000))
        try:
            _LOGGER.info(
                "[analysis-stage] stage=%s outcome=%s failure_code=%s elapsed_ms=%d",
                stage, outcome, category, elapsed_ms,
            )
            _LOGGER.info("[analysis-timing] stage=%s elapsed_ms=%d", stage, elapsed_ms)
        except Exception:
            pass  # Logging cannot replace the operation's result or exception.
