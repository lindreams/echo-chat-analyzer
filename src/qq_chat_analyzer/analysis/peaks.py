"""Shared helpers for locating peak activity buckets."""

from __future__ import annotations

from collections.abc import Sequence


HOURS_PER_DAY = 24
DAYS_PER_WEEK = 7


def busiest_index(counts: Sequence[int]) -> int | None:
    """Return the index with the highest count, preferring the earliest.

    Returns None when every bucket is empty, so callers can distinguish
    "no activity" from "most active at midnight".
    """
    best_index: int | None = None
    best_count = 0

    for index, count in enumerate(counts):
        if count > best_count:
            best_index = index
            best_count = count

    return best_index
