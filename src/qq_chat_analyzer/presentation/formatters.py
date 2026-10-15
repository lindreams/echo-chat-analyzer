"""Display formatting helpers for the presentation layer.

Every function here turns already-computed report values into strings.
No statistic is recomputed.
"""

from __future__ import annotations


WEEKDAY_NAMES = (
    "\u5468\u4e00",
    "\u5468\u4e8c",
    "\u5468\u4e09",
    "\u5468\u56db",
    "\u5468\u4e94",
    "\u5468\u516d",
    "\u5468\u65e5",
)

UNKNOWN_TIME = "\u65f6\u95f4\u672a\u77e5"
UNKNOWN_CONVERSATION = "\u672a\u5206\u7ec4\u4f1a\u8bdd"


def format_count(value: int) -> str:
    """Render an integer count with thousands separators."""
    return f"{value:,}"


def format_hour(hour: int | None) -> str:
    """Render an hour bucket as a readable clock range."""
    if hour is None:
        return UNKNOWN_TIME
    return f"{hour:02d}:00-{hour:02d}:59"


def format_weekday(weekday: int | None) -> str:
    """Render a Monday-zero weekday index as a Chinese weekday name."""
    if weekday is None or not 0 <= weekday < len(WEEKDAY_NAMES):
        return UNKNOWN_TIME
    return WEEKDAY_NAMES[weekday]


def format_active_period(hour: int | None, weekday: int | None) -> str:
    """Combine peak hour and weekday into one active-period phrase."""
    if hour is None and weekday is None:
        return UNKNOWN_TIME
    if hour is None:
        return format_weekday(weekday)
    if weekday is None:
        return format_hour(hour)
    return f"{format_weekday(weekday)} {format_hour(hour)}"


def format_duration(duration_seconds: int | None) -> str:
    """Render a duration in seconds as a coarse human readable span."""
    if duration_seconds is None:
        return UNKNOWN_TIME
    if duration_seconds < 60:
        return f"{duration_seconds} \u79d2"

    minutes, seconds = divmod(duration_seconds, 60)
    if minutes < 60:
        return f"{minutes} \u5206\u949f"

    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} \u5c0f\u65f6 {minutes} \u5206\u949f"

    days, hours = divmod(hours, 24)
    return f"{days} \u5929 {hours} \u5c0f\u65f6"
