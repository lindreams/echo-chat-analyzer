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
    try:
        yield
    except Exception as error:
        category = "io_error" if isinstance(error, OSError) else "operation_failed"
        _LOGGER.info("[analysis-stage] stage=%s outcome=failed failure_code=%s", stage, category)
        raise
    finally:
        _LOGGER.info(
            "[analysis-timing] stage=%s elapsed_ms=%d",
            stage,
            max(0, round((perf_counter() - started_at) * 1000)),
        )
