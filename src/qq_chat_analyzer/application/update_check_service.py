"""Qt-free release checks. Call check() on a worker, never during startup.

Only public release metadata is requested; no chat/account data is sent.
Construction performs no network or disk I/O. This is not an updater.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from time import time
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..resources import user_data_dir
from ..version import APP_VERSION
from .update_channel import (
    PRODUCTION_METADATA, PRODUCTION_PACKAGE_ID, PRODUCTION_CHANNEL,
    PRODUCTION_REPOSITORY, official_release_url,
)


_CHECK_INTERVAL = 24 * 60 * 60
_MAX_RESPONSE_BYTES = 256 * 1024
_SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)


@dataclass(frozen=True, slots=True)
class UpdateCheckResult:
    """Source-neutral outcome; unavailable must never be shown as up-to-date.

    release_url is a validated release page, not an executable download.
    checked_at is a Unix timestamp for this attempt (last attempt if skipped).
    error_code/public_message contain safe diagnostics, never response text.
    """

    status: Literal[
        "update_available", "up_to_date", "no_release", "skipped", "unavailable"
    ]
    current_version: str
    latest_version: str | None = None
    release_url: str | None = None
    checked_at: float | None = None
    error_code: str | None = None
    public_message: str | None = None


class UpdateChecker(Protocol):
    def check(self, *, manual: bool = False) -> UpdateCheckResult:
        """Automatic calls honor 24h dedupe; manual calls bypass it."""
        ...


def _parse_version(value: object) -> tuple[tuple[int, int, int, bool], str]:
    if not isinstance(value, str):
        raise ValueError("Invalid version")
    normalized = value.removeprefix("v")
    match = _SEMVER.fullmatch(normalized)
    if match is None:
        raise ValueError("Invalid version")
    prerelease = match[4]
    if prerelease and any(
        part.isdigit() and len(part) > 1 and part.startswith("0")
        for part in prerelease.split(".")
    ):
        raise ValueError("Invalid prerelease")
    # Remote candidates are always stable. Against a stable candidate, only
    # core numbers and whether the current version is a prerelease affect
    # SemVer precedence; build metadata never does.
    return (int(match[1]), int(match[2]), int(match[3]), prerelease is None), normalized


def _fetch_latest_release() -> object:
    request = Request(PRODUCTION_METADATA, headers={
        "Accept": "application/json",
        "User-Agent": f"Echo/{APP_VERSION}",
    })
    # No retries: offline startup must not accumulate retry delays. This is
    # a socket timeout, not a total deadline; callers must use a worker.
    with urlopen(request, timeout=5.0) as response:
        body = response.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise ValueError("Release response too large")
    return json.loads(body.decode("utf-8"))


class UpdateCheckService:
    """Shared automatic/manual policy with best-effort local attempt state.

    Dedupe includes failed and manual attempts, preventing repeated offline
    requests on each launch. Corrupt/future state is ignored. Disk failures
    retain in-memory dedupe; simultaneous calls on this instance never wait.
    """

    def __init__(
        self,
        *,
        state_path: Path | None = None,
        fetch_release: Callable[[], object] | None = None,
        clock: Callable[[], float] = time,
    ) -> None:
        self._state_path = state_path
        self._fetch_release = fetch_release or _fetch_latest_release
        self._clock = clock
        self._last_check_time: float | None = None
        self._lock = Lock()

    def check(self, *, manual: bool = False) -> UpdateCheckResult:
        if not self._lock.acquire(blocking=False):
            return UpdateCheckResult("skipped", APP_VERSION, error_code="in_progress")
        try:
            now = self._clock()
            last = self._last_check_time
            if last is None:
                last = self._read_last_check()
            if not manual and last is not None and 0 <= now - last < _CHECK_INTERVAL:
                return UpdateCheckResult("skipped", APP_VERSION, checked_at=last)
            self._last_check_time = now
            self._save_last_check(now)
            return self._check_release(now)
        finally:
            self._lock.release()

    def _path(self) -> Path:
        if self._state_path is not None:
            return self._state_path
        return user_data_dir() / "update-check.json"

    def _read_last_check(self) -> float | None:
        try:
            with self._path().open(encoding="utf-8") as source:
                state = json.loads(source.read(4096))
            value = state.get("last_check_time")
            if type(value) in (int, float) and math.isfinite(value) and value >= 0:
                return float(value)
        except (OSError, ValueError, AttributeError, OverflowError, RecursionError):
            pass
        return None

    def _save_last_check(self, now: float) -> None:
        temporary: Path | None = None
        try:
            path = self._path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=".update-check-", delete=False,
            ) as target:
                temporary = Path(target.name)
                json.dump({"last_check_time": now}, target)
            os.replace(temporary, path)
        except OSError:
            pass
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _check_release(self, now: float) -> UpdateCheckResult:
        def unavailable(code: str) -> UpdateCheckResult:
            return UpdateCheckResult(
                "unavailable", APP_VERSION, checked_at=now, error_code=code,
                public_message="暂时无法检查更新，请稍后手动重试。",
            )

        try:
            current, _ = _parse_version(APP_VERSION)
        except ValueError:
            return unavailable("invalid_version")
        try:
            payload = self._fetch_release()
            if (not isinstance(payload, dict)
                    or payload.get("draft") is not False
                    or payload.get("prerelease") is not False
                    or payload.get("package_id") != PRODUCTION_PACKAGE_ID
                    or payload.get("channel") != PRODUCTION_CHANNEL):
                raise ValueError("Not a formal release")
            latest, normalized = _parse_version(payload.get("tag_name"))
            if not latest[3]:
                raise ValueError("Prerelease tag")
            url = payload.get("html_url")
            if (not official_release_url(url)
                    or url != f"{PRODUCTION_REPOSITORY}/-/releases/tag/v{normalized}"):
                raise ValueError("Invalid release page")
            return UpdateCheckResult(
                "update_available" if latest > current else "up_to_date",
                APP_VERSION, normalized, url, now,
            )
        except HTTPError as exc:
            if exc.code == 404:
                return UpdateCheckResult("no_release", APP_VERSION, checked_at=now)
            return unavailable("rate_limited" if exc.code in (403, 429) else "http_error")
        except TimeoutError:
            return unavailable("timeout")
        except URLError as exc:
            return unavailable(
                "timeout" if isinstance(exc.reason, TimeoutError) else "network_error"
            )
        except (ValueError, UnicodeError):
            return unavailable("invalid_response")
        except OSError:
            return unavailable("network_error")
        except Exception:
            return unavailable("check_failed")
