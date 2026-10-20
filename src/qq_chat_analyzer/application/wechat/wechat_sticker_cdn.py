"""Bounded WeChat sticker acquisition from the official WeChat CDN.

The only authority to fetch is a digest-verified Type-47 occurrence: an exact
single ``<emoji>`` XML whose ``md5`` is 32 hex characters. Its ``cdnurl`` is an
untrusted hint and never identity; this module re-hashes every received body
and rejects anything that does not match the message digest.

Network rules (see ``docs/STICKER_DATA.md``):

* Only ``http``/``https`` URLs on the WeChat material host suffixes below.
* No redirects, no credentials, no non-default ports, no inherited proxy.
* One request per selected material, bounded response size and wall clock.
* URLs, digests, bytes and exception text never enter logs, reports or results.

Budgets are soft deadlines, not a hard real-time guarantee: socket reads can
only be interrupted between chunks, so a single blocking receive may outlast
the deadline by at most the request timeout. Every attempt's transferred bytes
count toward the batch budget, including failed and digest-mismatched bodies.

Only materials already selected by the report (Top N targets) are requested;
the complete chat is never downloaded.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import replace

from ...analysis.stickers import StickerData, StickerMedia
from ..sticker_media import verify_fetched_media


# Official WeChat material hosts observed in Type-47 XML. This is stricter than
# a bare suffix check: the host must be a subdomain of these registrable names.
WECHAT_CDN_HOST_SUFFIXES = (".tc.qq.com", ".qpic.cn")
WECHAT_CDN_ALLOWED_PORTS = (None, 80, 443)
MAX_RECEIVED_BYTES = 8 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
REQUEST_TIMEOUT_SECONDS = 8.0
# Report-wide bounds: the union of selected rankings, never the whole chat.
MAX_TARGETS_PER_REPORT = 64
MAX_TOTAL_TRANSFERRED_BYTES = 48 * 1024 * 1024
TOTAL_TIME_BUDGET_SECONDS = 45.0
USER_AGENT = "EchoStickerFetch/1"


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is never followed: the final location is not verified."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _FetchFailure(Exception):
    """Internal fixed outcome that also carries the bytes already received."""

    def __init__(self, status: str, reason: str, transferred: int = 0) -> None:
        self.status = status
        self.reason = reason
        self.transferred = transferred


def _build_opener() -> urllib.request.OpenerDirector:
    """Request only through the validated URL: no proxy, no redirect.

    An inherited ``HTTP(S)_PROXY``/``ALL_PROXY`` would route the full material
    URL through a third party, so the proxy handler is installed empty.
    """
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _RefuseRedirect
    )


def wechat_cdn_url_rejection(url: str | None) -> str | None:
    """Return a fixed rejection reason for an untrusted URL, or ``None``."""
    if not isinstance(url, str) or not url.strip():
        return "wechat_cdn_url_absent"
    try:
        parsed = urllib.parse.urlsplit(url.strip())
        port = parsed.port
    except ValueError:
        return "wechat_cdn_url_malformed"
    if parsed.scheme not in {"http", "https"}:
        return "wechat_cdn_url_scheme_rejected"
    if parsed.username or parsed.password:
        return "wechat_cdn_url_credentials_rejected"
    if port not in WECHAT_CDN_ALLOWED_PORTS:
        return "wechat_cdn_url_port_rejected"
    host = (parsed.hostname or "").lower()
    if not any(host.endswith(suffix) and len(host) > len(suffix)
               for suffix in WECHAT_CDN_HOST_SUFFIXES):
        return "wechat_cdn_url_host_rejected"
    return None


def _open(url: str, *, timeout: float, opener: urllib.request.OpenerDirector | None):
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.8"}
    )
    return (opener or _build_opener()).open(request, timeout=timeout)


def _read_body(
    response: object,
    *,
    max_bytes: int,
    deadline: float,
    cancelled: Callable[[], bool],
) -> tuple[bytes, int]:
    """Read one response in bounded chunks, honouring cancel and deadline."""
    chunks: list[bytes] = []
    transferred = 0
    while True:
        if cancelled():
            raise _FetchFailure("cancelled", "wechat_cdn_cancelled", transferred)
        if time.monotonic() >= deadline:
            raise _FetchFailure("failed", "wechat_cdn_timeout", transferred)
        try:
            chunk = response.read(min(READ_CHUNK_BYTES, max_bytes + 1 - transferred))
        except Exception:
            raise _FetchFailure(
                "failed", "wechat_cdn_transport_failed", transferred
            ) from None
        if not chunk:
            return b"".join(chunks), transferred
        chunks.append(chunk)
        transferred += len(chunk)
        if transferred > max_bytes:
            raise _FetchFailure(
                "limited", "wechat_cdn_response_too_large", transferred
            )


def _fetch(
    url: str | None,
    *,
    media_key: str,
    expected_md5: str | None,
    cancelled: Callable[[], bool],
    opener: urllib.request.OpenerDirector | None,
    max_bytes: int,
    deadline: float,
) -> tuple[StickerMedia, int]:
    """Return one attempt's media result and the bytes actually transferred."""
    rejection = wechat_cdn_url_rejection(url)
    if rejection is not None:
        return StickerMedia(media_key, "unsupported", rejection), 0
    if not isinstance(expected_md5, str) or not expected_md5:
        return StickerMedia(media_key, "unsupported", "wechat_cdn_digest_absent"), 0
    if cancelled():
        return StickerMedia(media_key, "cancelled", "wechat_cdn_cancelled"), 0
    budget = min(REQUEST_TIMEOUT_SECONDS, deadline - time.monotonic())
    if budget <= 0:
        return StickerMedia(media_key, "limited", "wechat_cdn_time_budget"), 0
    body = b""
    transferred = 0
    try:
        with _open(url, timeout=budget, opener=opener) as response:
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    if int(declared) > max_bytes:
                        return StickerMedia(
                            media_key, "limited", "wechat_cdn_response_too_large"
                        ), 0
                except ValueError:
                    pass
            body, transferred = _read_body(
                response, max_bytes=max_bytes, deadline=deadline, cancelled=cancelled
            )
    except _FetchFailure as failure:
        return StickerMedia(media_key, failure.status, failure.reason), failure.transferred
    except urllib.error.HTTPError as error:
        reason = (
            "wechat_cdn_redirect_refused"
            if 300 <= int(getattr(error, "code", 0) or 0) < 400
            else "wechat_cdn_http_status"
        )
        return StickerMedia(media_key, "failed", reason), 0
    except urllib.error.URLError:
        return StickerMedia(media_key, "failed", "wechat_cdn_unreachable"), 0
    except Exception:
        # Any other transport failure keeps one fixed, non-disclosing outcome.
        return StickerMedia(media_key, "failed", "wechat_cdn_transport_failed"), 0
    if cancelled():
        return StickerMedia(media_key, "cancelled", "wechat_cdn_cancelled"), transferred
    if not body:
        return StickerMedia(media_key, "failed", "wechat_cdn_empty_response"), transferred
    verified = verify_fetched_media(
        body, media_key=media_key, expected_md5=expected_md5, cancelled=cancelled
    )
    if verified.status == "available":
        return verified, transferred
    if verified.status == "preview":
        # A different digest proves the bytes are not this message's material.
        return StickerMedia(media_key, "invalid", "wechat_cdn_digest_mismatch"), transferred
    if verified.status == "cancelled":
        return StickerMedia(media_key, "cancelled", "wechat_cdn_cancelled"), transferred
    if verified.status == "limited":
        return StickerMedia(media_key, "limited", "wechat_cdn_decode_budget"), transferred
    return StickerMedia(media_key, "invalid", "wechat_cdn_invalid_content"), transferred


def fetch_wechat_sticker_media(
    url: str | None,
    *,
    media_key: str,
    expected_md5: str | None,
    cancelled: Callable[[], bool] = lambda: False,
    opener: urllib.request.OpenerDirector | None = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
    max_bytes: int = MAX_RECEIVED_BYTES,
    deadline: float | None = None,
) -> StickerMedia:
    """Fetch one sticker and return a verified original or a fixed failure.

    ``available`` requires the received bytes to hash to ``expected_md5`` and to
    pass the shared image validation (complete frame decode). Anything else is
    a fixed ``status``/``reason`` pair; no bytes are returned on failure. The
    effective deadline is the earlier of ``deadline`` and ``timeout``.
    """
    batch_deadline = time.monotonic() + (timeout if deadline is None else max(
        0.0, deadline - time.monotonic()))
    media, _ = _fetch(
        url,
        media_key=media_key,
        expected_md5=expected_md5,
        cancelled=cancelled,
        opener=opener,
        max_bytes=max_bytes,
        deadline=batch_deadline,
    )
    return media


def recover_wechat_sticker_media(
    data: StickerData,
    *,
    media_keys: tuple[str, ...],
    max_report_bytes: int | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    progress: Callable[[str], None] | None = None,
    opener: urllib.request.OpenerDirector | None = None,
) -> StickerData:
    """Fetch only the selected, still-missing WeChat materials.

    ``media_keys`` must belong to this result and keep the report's priority
    order. Materials already resolved from an authorized local root are not
    fetched again. When ``max_report_bytes`` is given, items that could not fit
    the report's inline budget are not requested at all and are marked
    ``limited/report_asset_budget`` instead of being downloaded and discarded.
    Every attempt records a fixed status/reason; this function does not raise
    for network failures.
    """
    known_keys = {send.media_key for send in data.sends}
    requested = tuple(dict.fromkeys(media_keys))
    if not set(requested).issubset(known_keys):
        raise ValueError("invalid_wechat_media_keys")
    sends = {}
    for send in data.sends:
        if send.source == "wechat" and send.identity_basis == "wechat_xml_md5":
            sends.setdefault(send.media_key, send)
    media = {item.media_key: item for item in data.media}
    # A key without a digest-verified occurrence can never authorize a request.
    pending = [
        key for key in requested
        if key in sends
        and not (media.get(key) is not None
                 and media[key].status in {"available", "preview"}
                 and (media[key].original_bytes or media[key].stored))
    ][:MAX_TARGETS_PER_REPORT]
    if not pending or cancelled():
        return data
    budgeted = max(0, max_report_bytes) if max_report_bytes is not None else None
    report_used = 0
    if budgeted is not None:
        report_used = sum(
            len(media[key].original_bytes)
            for key in requested
            if key in media and media[key].original_bytes is not None
        )
    deadline = time.monotonic() + TOTAL_TIME_BUDGET_SECONDS
    transferred = 0

    def stop_remaining(start: int, reason: str) -> None:
        for key in pending[start:]:
            media[key] = StickerMedia(key, "limited", reason)

    for index, key in enumerate(pending):
        if cancelled():
            break
        if time.monotonic() >= deadline:
            stop_remaining(index, "wechat_cdn_time_budget")
            break
        if transferred >= MAX_TOTAL_TRANSFERRED_BYTES:
            stop_remaining(index, "wechat_cdn_total_bytes_budget")
            break
        item_max = MAX_RECEIVED_BYTES
        if budgeted is not None:
            remaining = budgeted - report_used
            if remaining <= 0:
                stop_remaining(index, "report_asset_budget")
                break
            item_max = min(MAX_RECEIVED_BYTES, remaining)
        send = sends[key]
        if progress is not None:
            try:
                progress(f"正在获取表情包素材（{index + 1}/{len(pending)}）...")
            except Exception:
                pass
        item, used = _fetch(
            send.recovery_url,
            media_key=key,
            expected_md5=send.content_md5,
            cancelled=cancelled,
            opener=opener,
            max_bytes=item_max,
            deadline=deadline,
        )
        # A transfer cut short by the report budget is a report limit, not a
        # remote-size failure; name the limit the user can actually act on.
        if (item.status == "limited"
                and item.reason == "wechat_cdn_response_too_large"
                and item_max < MAX_RECEIVED_BYTES):
            item = replace(item, reason="report_asset_budget")
        media[key] = item
        transferred += used
        if item.original_bytes:
            report_used += len(item.original_bytes)
    return replace(data, media=tuple(media.values()))


__all__ = [
    "fetch_wechat_sticker_media",
    "recover_wechat_sticker_media",
    "wechat_cdn_url_rejection",
    "MAX_TARGETS_PER_REPORT",
    "MAX_RECEIVED_BYTES",
    "MAX_TOTAL_TRANSFERRED_BYTES",
    "WECHAT_CDN_HOST_SUFFIXES",
]
