"""Fictional resources only; spawned workers never contact a real CDN/account."""
from dataclasses import replace
from email.message import Message
from io import BytesIO
import hashlib
import multiprocessing
from pathlib import Path
import time
import urllib.error

import pytest
from PIL import Image

from qq_chat_analyzer.application.qq import qq_marketface_media as media
from qq_chat_analyzer.analysis.stickers import collect_sticker_sends
from test_qq_db_rich_contents import _parse, _scalar, _bytes


def gif():
    stream = BytesIO()
    Image.new("RGB", (3, 2), "red").save(stream, format="GIF", save_all=True,
        append_images=[Image.new("RGB", (3, 2), "blue")], duration=100, loop=0)
    return stream.getvalue()


def send(index=1):
    return collect_sticker_sends([_parse(_scalar(45002, 11) + _scalar(80810, index)
                                       + _bytes(80903, index.to_bytes(16, "big")))])[0]


def local_only_worker(*args):
    def forbidden(*_):
        raise AssertionError("Tests must not contact a real CDN")
    media._fetch = forbidden
    media._worker(*args)


def cdn_only_worker(*args):
    media._fetch = lambda *_: gif()
    media._worker(*args)


def hanging_worker(channel, output, *args):
    # Persist child identity for exit evidence, without involving QQ processes.
    Path(output).with_suffix(".pid").write_text(str(multiprocessing.current_process().pid))
    time.sleep(20)


def write_cache(root, item):
    path = root / str(item.resource_pack_id) / item.resource_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(media.decode_cache(gif()))


def finish(batch, timeout=10):
    assert batch.done.wait(timeout), "Recovery must finish without a real QQ/CDN"
    return batch.take_results()


def test_cache_xor_integrity_and_authorized_path(tmp_path):
    item = send()
    root = tmp_path / "marketface"
    write_cache(root, item)
    assert media.decode_cache(media.decode_cache(bytes(range(255)) * 3)) == bytes(range(255)) * 3
    raw = media._read_local(root, item.resource_pack_id, item.resource_id)
    assert raw == gif() and media._validate(raw, time.monotonic() + 2) == ("GIF", 2)
    for broken in (raw[:-1], raw + b"trailing", b"<html>failure</html>"):
        with pytest.raises(media._Rejected):
            media._validate(broken, time.monotonic() + 2)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / item.resource_id).write_bytes(media.decode_cache(raw))
    linkroot = tmp_path / "linked-marketface"
    linkroot.mkdir()
    from subprocess import run
    result = run(["cmd", "/c", "mklink", "/J", str(linkroot / str(item.resource_pack_id)), str(outside)],
                 capture_output=True)
    assert result.returncode == 0
    with pytest.raises((media._Rejected, OSError)):
        media._read_local(linkroot, item.resource_pack_id, item.resource_id)


@pytest.mark.parametrize("response", ["ok", "404", "timeout", "html", "truncated", "redirect", "too_large"])
def test_cdn_response_and_raw200_only(tmp_path, monkeypatch, response):
    class Reply(BytesIO):
        status = 200
        def __init__(self):
            content = b"<html>bad</html>" if response == "html" else gif()[:-1] if response == "truncated" else gif()
            super().__init__(content)
            self.headers = Message()
            self.headers["Content-Type"] = "text/html" if response == "html" else "image/gif"
            self.headers["Content-Length"] = str(media.MAX_FETCHED_MEDIA_BYTES + 1 if response == "too_large" else len(content))
    requests = []
    def open_request(request, *, timeout):
        requests.append(request.full_url)
        assert 0 < timeout <= 5
        assert request.full_url.endswith("/raw200.gif") and "raw300" not in request.full_url
        if response in ("404", "redirect"):
            raise urllib.error.HTTPError(request.full_url, 404 if response == "404" else 302, "fictional", {}, None)
        if response == "timeout":
            raise TimeoutError()
        return Reply()
    class Opener:
        open = staticmethod(open_request)
    def build(*handlers):
        assert handlers[0].proxies == {} and isinstance(handlers[1], media._NoRedirect)
        assert handlers[1].redirect_request(None, None, 302, "", {}, "https://invalid.example") is None
        return Opener()
    monkeypatch.setattr(media.urllib.request, "build_opener", build)
    receiver, sender = multiprocessing.Pipe(duplex=False)
    output = tmp_path / "result.gif"
    media._worker(sender, str(output), 1, "01" * 16, (), time.monotonic() + 3, True)
    value = receiver.recv()
    receiver.close()
    assert len(requests) == 1
    if response == "ok":
        assert value["status"] == "preview" and output.read_bytes() == gif()
    else:
        assert value["status"] != "preview" and not output.exists()
        if response == "404":
            assert value["status"] == "missing"


def test_local_hit_does_not_request_cdn_and_corrupt_cache_falls_back(tmp_path, monkeypatch):
    item = send()
    root = tmp_path / "marketface"
    write_cache(root, item)
    calls = []
    monkeypatch.setattr(media, "_fetch", lambda *args: calls.append(args) or gif())
    for index in range(2):
        receiver, sender = multiprocessing.Pipe(duplex=False)
        media._worker(sender, str(tmp_path / f"result{index}.gif"), item.resource_pack_id,
                      item.resource_id, (root,), time.monotonic() + 3, True)
        result = receiver.recv()
        receiver.close()
        assert result["status"] == "preview"
        assert result["reason"] == ("marketface_local_resource_verified" if index == 0 else
                                    "marketface_cdn_raw200_resource_verified")
        (root / str(item.resource_pack_id) / item.resource_id).write_bytes(b"broken")
    assert len(calls) == 1


@pytest.mark.parametrize("source", ["local", "cdn"])
@pytest.mark.slow_integration
def test_spawned_recovery_deduplicates_cleans_and_survives_three_reports(tmp_path, monkeypatch, source):
    monkeypatch.setattr(media, "_worker", local_only_worker if source == "local" else cdn_only_worker)
    items = [send(1), send(2), send(3)]
    root = tmp_path / "marketface"
    if source == "local":
        for item in items:
            write_cache(root, item)
    baseline = {p.pid for p in multiprocessing.active_children()}
    for _ in range(3):
        batch = media.MarketFaceRecovery(items + items, roots=(root,), deadline=time.monotonic() + 8).start()
        paths = set()
        peak = 0
        while not batch.done.wait(0.01):
            with media._LOCK:
                peak = max(peak, len(media._ACTIVE))
                paths.update(j.directory.name for j in media._ACTIVE.values() if j.directory is not None)
        results = batch.take_results()
        batch.close()
        assert len(results) == 3 and all(r.status == "preview" and r.stored.read() == gif() for r in results)
        assert batch.stats["requests"] == (0 if source == "local" else 3)
        assert batch.stats[source] == 3
        assert peak <= 2 and not media._ACTIVE
        assert all(not Path(p).exists() for p in paths)
        for item in results:
            item.stored.close()
    assert {p.pid for p in multiprocessing.active_children()} == baseline


@pytest.mark.slow_integration
def test_deadline_cancel_and_cross_report_limit_stop_owned_workers(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "_worker", hanging_worker)
    items = [send(i) for i in range(1, 8)]
    baseline = {p.pid for p in multiprocessing.active_children()}
    started = time.monotonic()
    batch = media.MarketFaceRecovery(items, deadline=started + 1.5).start()
    until = time.monotonic() + 1
    while time.monotonic() < until:
        with media._LOCK:
            if len(media._ACTIVE) == 2:
                break
        time.sleep(0.01)
    with media._LOCK:
        assert len(media._ACTIVE) == 2
        paths = [j.directory.name for j in media._ACTIVE.values() if j.directory is not None]
    second = media.MarketFaceRecovery(items, deadline=time.monotonic() + 3).start()
    blocked = finish(second)
    second.close()
    assert len(blocked) == 7 and all(r.reason == "marketface_resource_busy" for r in blocked)
    results = finish(batch)
    batch.close()
    assert time.monotonic() - started < 2.5
    assert len(results) == 7 and all(r.stored is None for r in results)
    assert not media._ACTIVE and all(not Path(p).exists() for p in paths)
    assert {p.pid for p in multiprocessing.active_children()} == baseline
    # Expired budgets must not launch new work; cancellation closes late pipes.
    expired = media.MarketFaceRecovery(items, deadline=time.monotonic() - 1).start()
    finish(expired)
    expired.close()
    assert not media._ACTIVE
    monkeypatch.setattr(media, "ITEM_SECONDS", 0.5)
    item_limited = media.MarketFaceRecovery(items[:2], deadline=time.monotonic() + 3).start()
    item_results = finish(item_limited)
    item_limited.close()
    assert len(item_results) == 2 and all(r.reason == "marketface_item_timeout" for r in item_results)
    assert not media._ACTIVE
    cancelled = media.MarketFaceRecovery(items, deadline=time.monotonic() + 3).start()
    cancelled.close()
    assert cancelled.done.wait(1) and cancelled.take_results() == () and not media._ACTIVE
    from qq_chat_analyzer.analysis.stickers import StickerMedia
    from qq_chat_analyzer.media_content import StoredMedia
    late = StickerMedia(items[0].media_key, "preview", stored=StoredMedia(gif()))
    cancelled._publish(late)
    assert cancelled.take_results() == ()
    with pytest.raises(ValueError):
        late.stored.read()
    # Crossing the per-item deadline while adopting a completed file must not
    # turn that late result into a successful preview or retain its storage.
    monkeypatch.setattr(media, "_worker", cdn_only_worker)
    monkeypatch.setattr(media, "ITEM_SECONDS", 3)
    created = []
    def crossed_deadline(raw):
        stored = StoredMedia(raw)
        created.append(stored)
        with media._LOCK:
            for job in media._ACTIVE.values():
                job.deadline = time.monotonic() - 1
        return stored
    monkeypatch.setattr(media, "StoredMedia", crossed_deadline)
    adopting = media.MarketFaceRecovery(items[:1], deadline=time.monotonic() + 4).start()
    adopted = finish(adopting)
    adopting.close()
    assert len(adopted) == 1 and adopted[0].reason == "marketface_item_timeout" and not media._ACTIVE
    assert len(created) == 1
    with pytest.raises(ValueError):
        created[0].read()


def test_resource_evidence_cannot_be_forged_from_md5_or_legacy():
    item = send()
    assert media.is_marketface(item)
    for bad in (replace(item, identity_basis="qq_45600_sha256_opaque"),
                replace(item, source="wechat"), replace(item, resource_id="../outside"),
                replace(item, identity_key="qq-pic:md5:" + "01" * 16)):
        assert not media.is_marketface(bad)
