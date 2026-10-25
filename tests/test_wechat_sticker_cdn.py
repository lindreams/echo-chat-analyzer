"""Behavioral tests for bounded WeChat sticker CDN acquisition.

All fixtures are fictional; no real URL, digest, key or account appears here.
The opener is always injected, so no test performs a network request.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from qq_chat_analyzer.analysis.stickers import StickerData, StickerSend  # noqa: E402
from qq_chat_analyzer.application.wechat.wechat_sticker_cdn import (  # noqa: E402
    fetch_wechat_sticker_media,
    recover_wechat_sticker_media,
    wechat_cdn_url_rejection,
)

FICTIONAL_URL = "https://fictional-vweixinf.tc.qq.com/fictional-sticker"


def _gif_bytes() -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buffer, format="GIF")
    return buffer.getvalue()


class _Response:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}
        self.status = 200

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            body, self._body = self._body, b""
            return body
        body, self._body = self._body[:size], self._body[size:]
        return body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc_info) -> None:
        return None


class _ChunkedResponse:
    """Answers chunk by chunk so a test can observe progress and deadlines."""

    def __init__(self, chunks: list[bytes], *, on_read=None, headers=None) -> None:
        self._chunks = list(chunks)
        self._on_read = on_read
        self.headers = headers or {}
        self.read_calls = 0

    def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        if self._on_read is not None:
            self._on_read()
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self) -> "_ChunkedResponse":
        return self

    def __exit__(self, *exc_info) -> None:
        return None


class _Opener:
    def __init__(self, *outcomes) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[str] = []

    def open(self, request, timeout=None):
        self.calls.append(request.full_url)
        outcome = self._outcomes[0] if len(self._outcomes) == 1 else self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if hasattr(outcome, "read"):
            return outcome
        return _Response(*outcome) if isinstance(outcome, tuple) else _Response(outcome)


def _send(media_key: str, digest: str | None, url: str | None) -> StickerSend:
    return StickerSend(
        occurrence_id=f"occ-{media_key}", source="wechat", conversation_id="fictional_room",
        conversation_type="group", sender_id="wxid_fictional", is_self=False,
        message_id=media_key, content_index=0, timestamp=1760000000,
        epoch_seconds=1760000000, chat_date="2026-10-20",
        classification_basis="wechat_type_47",
        identity_basis="wechat_xml_md5" if digest else "unresolved",
        identity_key=f"wechat:md5:{digest}" if digest else None,
        media_key=media_key, content_md5=digest, recovery_url=url,
    )


@pytest.mark.parametrize("url, reason", [
    pytest.param("https://evil.example/sticker", "wechat_cdn_url_host_rejected", id="foreign-host"),
    pytest.param("file:///fictional/sticker", "wechat_cdn_url_scheme_rejected", id="scheme"),
    pytest.param("https://user:pass@fictional.tc.qq.com/x", "wechat_cdn_url_credentials_rejected",
                 id="credentials"),
    pytest.param("https://fictional.tc.qq.com:8443/x", "wechat_cdn_url_port_rejected", id="port"),
    pytest.param("", "wechat_cdn_url_absent", id="absent"),
    pytest.param("https://fictional.tc.qq.com.evil.example/x", "wechat_cdn_url_host_rejected",
                 id="suffix-spoof"),
])
def test_url_policy_rejects_untrusted_locations(url: str, reason: str) -> None:
    assert wechat_cdn_url_rejection(url) == reason


def test_url_policy_accepts_wechat_material_host() -> None:
    assert wechat_cdn_url_rejection(FICTIONAL_URL) is None


@pytest.mark.parametrize("earlier_url", [None, "https://fictional.invalid/not-authorized"])
def test_recovery_uses_a_valid_later_occurrence_of_the_same_material(earlier_url):
    body = _gif_bytes()
    digest = hashlib.md5(body).hexdigest()
    data = StickerData(sends=(
        _send("sticker:repeated", digest, earlier_url),
        _send("sticker:repeated", digest, FICTIONAL_URL),
    ))
    opener = _Opener(body)
    result = recover_wechat_sticker_media(data, media_keys=("sticker:repeated",), opener=opener)
    assert result.media[0].status == "available"
    assert result.media[0].original_bytes == body
    assert opener.calls == [FICTIONAL_URL]


def test_android_only_sends_reuse_verified_material_in_each_private_relay_turn():
    from qq_chat_analyzer.wechat_db_adapter import parse_rich_messages
    from qq_chat_analyzer.analysis.stickers import collect_sticker_sends
    from qq_chat_analyzer.analysis.sticker_index import build_sticker_fact_index
    from qq_chat_analyzer.analysis.sticker_features import analyze_private_stickers
    from qq_chat_analyzer.analysis.models import AnalysisReports
    from qq_chat_analyzer.presentation import build_echo_report_view, echo_report_to_dict
    from qq_chat_analyzer.presentation.stickers import sticker_report_targets

    body = _gif_bytes()
    digest = hashlib.md5(body).hexdigest()
    rows = [{
        "local_id": i + 1, "local_type": 47, "create_time": 1760000000 + i * 10,
        "username": "wxid_fictional_peer", "conversation_type": "private",
        "user_name": "wxid_fictional_self" if i % 2 == 0 else "wxid_fictional_peer",
        "self_username": "wxid_fictional_self",
        "message_content": (f'<msg><emoji androidmd5="{digest}"/></msg>' if i % 2 == 0
                            else f'<msg><emoji md5="{digest}" cdnurl="{FICTIONAL_URL}"/></msg>'),
    } for i in range(4)]
    rich = tuple(parse_rich_messages(rows))
    data = StickerData(sends=collect_sticker_sends(rich))
    index = build_sticker_fact_index(data, rich, source_positions=range(len(rich)))
    features = analyze_private_stickers(index)
    view = build_echo_report_view(AnalysisReports(stickers=(index.report,), private_stickers=features),
                                  conversation_kind="private")
    relay = next(f for m in echo_report_to_dict(view)["sticker_memories"] for f in m["findings"]
                 if f["kind"] == "relay")
    assert len(relay["points"]) == 4
    assert all(len(point["materials"]) == 1 for point in relay["points"])
    targets = sticker_report_targets(view.stickers)
    assert len(targets) == 1
    opener = _Opener(body)
    recovered = recover_wechat_sticker_media(data, media_keys=tuple(t.media_key for t in targets), opener=opener)
    assert recovered.media[0].original_bytes == body
    assert opener.calls == [FICTIONAL_URL]


def test_matching_digest_yields_verified_original() -> None:
    body = _gif_bytes()
    opener = _Opener(body)

    media = fetch_wechat_sticker_media(
        FICTIONAL_URL, media_key="sticker:1", expected_md5=hashlib.md5(body).hexdigest(),
        opener=opener)

    assert media.status == "available"
    assert media.format == "GIF"
    assert media.original_bytes == body
    assert media.verified_reference is None
    assert len(opener.calls) == 1


def test_digest_mismatch_is_rejected_without_bytes() -> None:
    body = _gif_bytes()
    media = fetch_wechat_sticker_media(
        FICTIONAL_URL, media_key="sticker:2",
        expected_md5=hashlib.md5(b"another fictional sticker").hexdigest(),
        opener=_Opener(body))

    assert (media.status, media.reason) == ("invalid", "wechat_cdn_digest_mismatch")
    assert media.original_bytes is None


def test_received_content_must_decode_as_an_image() -> None:
    body = b"not an image at all"
    media = fetch_wechat_sticker_media(
        FICTIONAL_URL, media_key="sticker:3",
        expected_md5=hashlib.md5(body).hexdigest(), opener=_Opener(body))

    assert (media.status, media.reason) == ("invalid", "wechat_cdn_invalid_content")


def test_redirect_is_not_followed() -> None:
    error = urllib.error.HTTPError(FICTIONAL_URL, 302, "Found", {}, None)
    media = fetch_wechat_sticker_media(
        FICTIONAL_URL, media_key="sticker:4", expected_md5="a" * 32, opener=_Opener(error))

    assert (media.status, media.reason) == ("failed", "wechat_cdn_redirect_refused")


def test_declared_and_actual_size_are_bounded() -> None:
    body = _gif_bytes()
    oversized_header = fetch_wechat_sticker_media(
        FICTIONAL_URL, media_key="sticker:5", expected_md5=hashlib.md5(body).hexdigest(),
        opener=_Opener((body, {"Content-Length": str(len(body) + 1)})), max_bytes=len(body))
    assert (oversized_header.status, oversized_header.reason) == (
        "limited", "wechat_cdn_response_too_large")

    streamed = fetch_wechat_sticker_media(
        FICTIONAL_URL, media_key="sticker:6", expected_md5=hashlib.md5(body).hexdigest(),
        opener=_Opener(body), max_bytes=len(body) - 1)
    assert (streamed.status, streamed.reason) == ("limited", "wechat_cdn_response_too_large")


def test_unreachable_transport_keeps_fixed_reason() -> None:
    media = fetch_wechat_sticker_media(
        FICTIONAL_URL, media_key="sticker:7", expected_md5="b" * 32,
        opener=_Opener(urllib.error.URLError("fictional offline")))

    assert (media.status, media.reason) == ("failed", "wechat_cdn_unreachable")


def test_recovery_fetches_only_selected_missing_materials() -> None:
    body = _gif_bytes()
    digest = hashlib.md5(body).hexdigest()
    other = hashlib.md5(b"fictional other").hexdigest()
    data = StickerData(sends=(
        _send("sticker:a", digest, FICTIONAL_URL),
        _send("sticker:b", other, FICTIONAL_URL),
        _send("sticker:c", None, None),
    ))
    opener = _Opener(body)

    recovered = recover_wechat_sticker_media(
        data, media_keys=("sticker:a", "sticker:c"), cancelled=lambda: False, opener=opener)

    by_key = {item.media_key: item for item in recovered.media}
    assert by_key["sticker:a"].status == "available"
    # An occurrence without verified identity never authorizes a request.
    assert "sticker:c" not in by_key
    assert len(opener.calls) == 1


def test_recovery_rejects_keys_outside_this_result() -> None:
    data = StickerData(sends=(_send("sticker:a", "c" * 32, FICTIONAL_URL),))

    with pytest.raises(ValueError):
        recover_wechat_sticker_media(data, media_keys=("sticker:unknown",), opener=_Opener(_gif_bytes()))


def test_recovery_skips_materials_already_resolved_locally() -> None:
    from qq_chat_analyzer.analysis.stickers import StickerMedia

    body = _gif_bytes()
    data = StickerData(
        sends=(_send("sticker:a", hashlib.md5(body).hexdigest(), FICTIONAL_URL),),
        media=(StickerMedia("sticker:a", "available", original_bytes=body),),
    )
    opener = _Opener(body)

    recovered = recover_wechat_sticker_media(
        data, media_keys=("sticker:a",), opener=opener)

    assert recovered.media[0].status == "available"
    assert opener.calls == []


def test_recovery_records_failure_and_keeps_other_targets() -> None:
    body = _gif_bytes()
    digest = hashlib.md5(body).hexdigest()
    data = StickerData(sends=(
        _send("sticker:a", digest, FICTIONAL_URL),
        _send("sticker:b", digest, "https://evil.example/sticker"),
    ))

    recovered = recover_wechat_sticker_media(
        data, media_keys=("sticker:a", "sticker:b"), opener=_Opener(body))

    by_key = {item.media_key: item for item in recovered.media}
    assert by_key["sticker:a"].status == "available"
    assert (by_key["sticker:b"].status, by_key["sticker:b"].reason) == (
        "unsupported", "wechat_cdn_url_host_rejected")


MODULE = "qq_chat_analyzer.application.wechat.wechat_sticker_cdn"


def test_environment_proxy_is_not_inherited(monkeypatch) -> None:
    module = importlib.import_module(MODULE)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")

    opener = module._build_opener()

    # Passing an empty ProxyHandler suppresses the default one, so no handler
    # can route a request through the environment proxy.
    assert not [h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert not [h for h in opener.handlers if hasattr(h, "proxy_open")]


def test_failed_transfers_count_toward_batch_budget(monkeypatch) -> None:
    module = importlib.import_module(MODULE)
    monkeypatch.setattr(module, "MAX_TOTAL_TRANSFERRED_BYTES", 8)
    body = b"x" * 8
    digest = hashlib.md5(b"fictional other").hexdigest()
    data = StickerData(sends=(
        _send("sticker:a", digest, FICTIONAL_URL),
        _send("sticker:b", digest, FICTIONAL_URL),
    ))
    opener = _Opener(body)

    recovered = module.recover_wechat_sticker_media(
        data, media_keys=("sticker:a", "sticker:b"), opener=opener)

    by_key = {item.media_key: item for item in recovered.media}
    assert by_key["sticker:a"].status == "invalid"
    assert by_key["sticker:a"].original_bytes is None
    assert (by_key["sticker:b"].status, by_key["sticker:b"].reason) == (
        "limited", "wechat_cdn_total_bytes_budget")
    assert len(opener.calls) == 1


def test_cancellation_during_read_stops_transfer() -> None:
    state = {"cancelled": False}

    response = _ChunkedResponse(
        [b"y" * 16, b"y" * 16], on_read=lambda: state.update(cancelled=True))
    media = fetch_wechat_sticker_media(
        FICTIONAL_URL, media_key="sticker:c", expected_md5="a" * 32,
        cancelled=lambda: state["cancelled"], opener=_Opener(response))

    assert (media.status, media.reason) == ("cancelled", "wechat_cdn_cancelled")
    assert media.original_bytes is None


def test_deadline_interrupts_slow_response(monkeypatch) -> None:
    module = importlib.import_module(MODULE)
    clock = {"now": 1000.0}
    monkeypatch.setattr(module.time, "monotonic", lambda: clock["now"])

    response = _ChunkedResponse(
        [b"z" * 16, b"z" * 16], on_read=lambda: clock.update(now=1100.0))
    media = module.fetch_wechat_sticker_media(
        FICTIONAL_URL, media_key="sticker:d", expected_md5="b" * 32,
        opener=_Opener(response), timeout=8.0)

    assert (media.status, media.reason) == ("failed", "wechat_cdn_timeout")
    assert response.read_calls == 1


def test_report_budget_skips_download_it_cannot_inline(monkeypatch) -> None:
    module = importlib.import_module(MODULE)
    body = _gif_bytes()
    digest = hashlib.md5(body).hexdigest()
    data = StickerData(sends=(
        _send("sticker:a", digest, FICTIONAL_URL),
        _send("sticker:b", digest, FICTIONAL_URL),
    ))
    first = _ChunkedResponse([body])
    # Declared size already exceeds what the report can still hold.
    second = _ChunkedResponse([body], headers={"Content-Length": str(len(body))})
    opener = _Opener(first, second)

    recovered = module.recover_wechat_sticker_media(
        data, media_keys=("sticker:a", "sticker:b"),
        max_report_bytes=len(body) + 10, opener=opener)

    by_key = {item.media_key: item for item in recovered.media}
    assert by_key["sticker:a"].status == "available"
    assert (by_key["sticker:b"].status, by_key["sticker:b"].reason) == (
        "limited", "report_asset_budget")
    assert second.read_calls == 0
