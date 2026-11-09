"""MarketFace resource recovery; no QQ media RPCs or original-digest claims.

Only two owned children may exist across reports. A child handles one resource,
including local I/O and decoding, and writes to its parent's private staging
directory. The reporting thread alone adopts results; late work cannot mutate
a report. An unconfirmed child exit retains its slot rather than being replaced.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import hashlib
import multiprocessing
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import threading
import time
import urllib.error
import urllib.request

from ...analysis.stickers import StickerMedia, StickerSend
from ...media_content import StoredMedia
from ..sticker_media import (
    MAX_FETCHED_MEDIA_BYTES, QQ_MAX_DECODE_PIXELS, QQ_MAX_DECODE_WORK,
    _Rejected, _check_gif_canvas, _inspect, _open_original, _witness,
)

RESOURCE_BASIS = "qq_marketface_pack_resource"
SOCKET_SECONDS = 5.0
ITEM_SECONDS = 10.0
MAX_WORKERS = 2
_LOCK = threading.RLock()
_ACTIVE: dict[str, _Job] = {}


def is_marketface(send: StickerSend) -> bool:
    return (send.source == "qq" and send.identity_basis == RESOURCE_BASIS
            and type(send.resource_pack_id) is int and 0 < send.resource_pack_id <= 0xFFFFFFFF
            and isinstance(send.resource_id, str) and re.fullmatch(r"[0-9a-f]{32}", send.resource_id) is not None
            and send.identity_key == send.media_key ==
            f"qq-marketface:resource:{send.resource_pack_id}:{send.resource_id}")


def decode_cache(raw: bytes) -> bytes:
    content = bytearray(raw)
    for start in range(0, len(content), 50):
        for offset in range(start, min(start + 20, len(content))):
            content[offset] ^= 0xFF
    return bytes(content)


def _read_local(root: Path, pack: int, resource: str) -> bytes:
    path = root / str(pack) / resource
    before = path.stat(follow_symlinks=False)
    with _open_original(path, root) as stream:
        opened = os.fstat(stream.fileno())
        if opened.st_size <= 0 or opened.st_size > MAX_FETCHED_MEDIA_BYTES or opened.st_nlink != 1:
            raise _Rejected("invalid", "invalid_size")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise _Rejected("unsafe", "cache_changed")
        raw = stream.read(MAX_FETCHED_MEDIA_BYTES + 1)
        after = os.fstat(stream.fileno())
        named = path.stat(follow_symlinks=False)
        if (_witness(opened) != _witness(after) or _witness(before) != _witness(named)
                or len(raw) != opened.st_size):
            raise _Rejected("unsafe", "cache_changed")
    return decode_cache(raw)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch(resource: str, deadline: float) -> bytes:
    # Constructed coordinates only: never accept a URL or credentials from data.
    url = f"https://i.gtimg.cn/club/item/parcel/item/{resource[:2]}/{resource}/raw200.gif"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "EchoStickerFetch/1"})
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError()
    with opener.open(request, timeout=min(SOCKET_SECONDS, remaining)) as response:
        if response.status != 200 or response.headers.get_content_type() != "image/gif":
            raise _Rejected("invalid", "marketface_cdn_response")
        length = response.headers.get("Content-Length")
        if length is not None and (not length.isdecimal() or int(length) > MAX_FETCHED_MEDIA_BYTES):
            raise _Rejected("invalid", "invalid_size")
        content = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError()
            chunk = response.read(min(64 * 1024, MAX_FETCHED_MEDIA_BYTES + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > MAX_FETCHED_MEDIA_BYTES:
                raise _Rejected("invalid", "invalid_size")
        if length is not None and len(content) != int(length):
            raise _Rejected("invalid", "marketface_cdn_incomplete")
        return bytes(content)


def _validate(raw: bytes, deadline: float) -> tuple[str, int]:
    if not raw.startswith((b"GIF87a", b"GIF89a")) or len(raw) > MAX_FETCHED_MEDIA_BYTES:
        raise _Rejected("invalid", "invalid_image")
    def check():
        if time.monotonic() >= deadline:
            raise TimeoutError()
    _check_gif_canvas(raw, check, require_eof=True)
    return _inspect(raw, max_pixels=QQ_MAX_DECODE_PIXELS, max_frames=None,
                    max_work=QQ_MAX_DECODE_WORK, max_seconds=max(0, deadline - time.monotonic()),
                    cancelled=lambda: time.monotonic() >= deadline)


def _send(channel, value):
    try:
        channel.send(value)
    except (OSError, EOFError):
        pass  # The owning report has closed; no other batch receives this pipe.


def _worker(channel, output: str, pack: int, resource: str, roots: tuple[Path, ...],
            deadline: float, allow_cdn: bool) -> None:
    parent = multiprocessing.parent_process()
    if parent is not None:
        def exit_with_parent():
            parent.join()
            os._exit(1)
        threading.Thread(target=exit_with_parent, daemon=True).start()
    try:
        raw, origin, local_failure = None, "local", None
        for root in roots:
            if time.monotonic() >= deadline:
                raise TimeoutError()
            try:
                candidate = _read_local(root, pack, resource)
                fmt, frames = _validate(candidate, deadline)
                raw = candidate
                break
            except (OSError, _Rejected):
                local_failure = "marketface_local_unavailable"
        if raw is None:
            if not allow_cdn:
                raise _Rejected("limited", "marketface_cdn_stopped")
            origin = "cdn_raw200"
            Path(output).with_suffix(".requested").touch(exist_ok=False)
            raw = _fetch(resource, deadline)
            fmt, frames = _validate(raw, deadline)
        if time.monotonic() >= deadline:
            raise TimeoutError()
        with open(output, "xb") as stream:
            stream.write(raw)
        _send(channel, {"status": "preview", "reason": f"marketface_{origin}_resource_verified",
                      "sha256": hashlib.sha256(raw).hexdigest(), "format": fmt,
                      "frame_count": frames, "byte_count": len(raw),
                      "cdn_attempted": origin != "local", "local_failure": local_failure})
    except urllib.error.HTTPError as error:
        code = error.code
        error.close()
        _send(channel, {"status": "missing" if code in (404, 410) else "failed",
                      "reason": f"marketface_cdn_http_{code}" if code in (401, 403, 404, 410, 429) else "marketface_cdn_http_error",
                      "cdn_attempted": True})
    except _Rejected as error:
        _send(channel, {"status": error.status, "reason": error.reason,
                      "cdn_attempted": origin != "local"})
    except TimeoutError:
        _send(channel, {"status": "limited", "reason": "marketface_item_timeout",
                      "cdn_attempted": origin != "local"})
    except (OSError, ValueError):
        _send(channel, {"status": "failed", "reason": "marketface_resource_unavailable",
                      "cdn_attempted": origin != "local"})
    except Exception:
        _send(channel, {"status": "failed", "reason": "marketface_worker_failed"})
    finally:
        channel.close()


@dataclass
class _Job:
    deadline: float
    process: object = None
    channel: object = None
    directory: TemporaryDirectory | None = None
    output: Path | None = None
    retired: bool = False
    reaping: bool = False


def _release(key: str, job: _Job) -> bool:
    """Only a positively exited owned Process authorizes slot/file release."""
    if job.process is not None and job.process.pid is not None and job.process.is_alive():
        return False
    if job.process is not None and job.process.pid is not None:
        job.process.join(0)
    try:
        if job.directory is not None:
            job.directory.cleanup()
    except OSError:
        return False  # Retain ownership and retry cleanup, never delete elsewhere.
    if job.channel is not None:
        job.channel.close()
    if job.process is not None:
        job.process.close()
    with _LOCK:
        if _ACTIVE.get(key) is job:
            del _ACTIVE[key]
    return True


def _retire(key, job):
    with _LOCK:
        job.retired = job.reaping = True
    try:
        if job.process is not None and job.process.pid is not None and job.process.is_alive():
            job.process.terminate()
            job.process.join(0.05)
        _release(key, job)
    except OSError:
        pass  # Keep the exact owned Process/slot for a later verified reap.
    finally:
        with _LOCK:
            job.reaping = False


def _reap_retired():
    with _LOCK:
        retired = [(key, job) for key, job in _ACTIVE.items() if job.retired and not job.reaping]
        for _, job in retired:
            job.reaping = True
    for key, job in retired:
        try:
            _release(key, job)
        finally:
            with _LOCK:
                job.reaping = False


class MarketFaceRecovery:
    """One report's bounded acquisition lifetime, separate from PIC's bridge."""
    def __init__(self, sends, *, roots=(), deadline: float, cancelled=lambda: False):
        self._pending = deque({send.media_key: send for send in sends if is_marketface(send)}.values())
        self._roots = tuple(roots)
        self._deadline = deadline
        self._cancelled = cancelled
        self._stop = threading.Event()
        self.done = threading.Event()
        self._results = []
        self._results_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="echo-marketface", daemon=True)
        self.stats = {"targets": len(self._pending), "local": 0, "cdn": 0, "requests": 0, "unfinished": 0}

    def start(self):
        self._thread.start()
        return self

    def take_results(self):
        with self._results_lock:
            results, self._results = self._results, []
        return tuple(results)

    def close(self):
        self._stop.set()
        self._thread.join(0.3)
        for result in self.take_results():
            if result.stored:
                result.stored.close()

    def _publish(self, item):
        with self._results_lock:
            if self._stop.is_set() or self._cancelled() or time.monotonic() >= self._deadline:
                if item.stored:
                    item.stored.close()
            else:
                self._results.append(item)

    def _run(self):
        jobs = {}
        allow_cdn = True
        try:
            while (self._pending or jobs) and not self._stop.is_set() and not self._cancelled():
                now = time.monotonic()
                # Reserve time for owned-process termination within the stage.
                if now >= self._deadline - 0.35:
                    break
                _reap_retired()
                while self._pending:
                    if self._stop.is_set() or self._cancelled() or time.monotonic() >= self._deadline - 0.35:
                        break
                    with _LOCK:
                        if len(_ACTIVE) >= MAX_WORKERS:
                            break
                        send = self._pending.popleft()
                        key = send.media_key
                        if key in _ACTIVE:
                            self._publish(StickerMedia(key, "limited", "marketface_resource_busy"))
                            continue
                        until = min(self._deadline - 0.35, time.monotonic() + ITEM_SECONDS)
                        # Reserve before filesystem/spawn work, outside the lock:
                        # even a stalled launch cannot grow across reports.
                        job = _Job(until)
                        _ACTIVE[key] = jobs[key] = job
                    sender = None
                    try:
                        job.directory = TemporaryDirectory(prefix="echo-marketface-")
                        job.output = Path(job.directory.name) / "resource.gif"
                        job.channel, sender = multiprocessing.get_context("spawn").Pipe(duplex=False)
                        job.process = multiprocessing.get_context("spawn").Process(
                            target=_worker, args=(sender, str(job.output), send.resource_pack_id, send.resource_id,
                                                 self._roots, until, allow_cdn), daemon=True)
                        job.process.start()
                    except Exception:
                        _retire(key, job)
                        del jobs[key]
                        self._publish(StickerMedia(key, "failed", "marketface_worker_unavailable"))
                    finally:
                        if sender is not None:
                            sender.close()
                if not jobs and self._pending:
                    # Other reports/quarantined children own both slots. Do not
                    # leave one more background waiter alive for each report.
                    for send in self._pending:
                        self._publish(StickerMedia(send.media_key, "limited", "marketface_resource_busy"))
                    self._pending.clear()
                for key, job in tuple(jobs.items()):
                    if job.process.is_alive() and time.monotonic() < job.deadline:
                        continue
                    item = StickerMedia(key, "limited", "marketface_item_timeout")
                    if not job.process.is_alive() and time.monotonic() < job.deadline:
                        try:
                            value = job.channel.recv() if job.channel.poll() else {}
                            reason = value.get("reason", "marketface_worker_failed")
                            if reason in {"marketface_cdn_http_401", "marketface_cdn_http_403", "marketface_cdn_http_429"}:
                                allow_cdn = False
                            item = StickerMedia(key, value.get("status", "failed"), reason)
                            if item.status == "preview" and job.process.exitcode == 0:
                                with _open_original(job.output, Path(job.directory.name)) as stream:
                                    raw = stream.read(MAX_FETCHED_MEDIA_BYTES + 1)
                                if (len(raw) != value["byte_count"] or len(raw) > MAX_FETCHED_MEDIA_BYTES
                                        or hashlib.sha256(raw).hexdigest() != value["sha256"]):
                                    raise ValueError()
                                stored = StoredMedia(raw)
                                if time.monotonic() >= job.deadline:
                                    stored.close()
                                    item = StickerMedia(key, "limited", "marketface_item_timeout")
                                else:
                                    item = replace(item, stored=stored, sha256=value["sha256"], format=value["format"],
                                                   frame_count=value["frame_count"], byte_count=len(raw),
                                                   animation_preserved=value["frame_count"] > 1)
                                    self.stats["local" if reason == "marketface_local_resource_verified" else "cdn"] += 1
                        except (OSError, ValueError, KeyError, EOFError, _Rejected):
                            item = StickerMedia(key, "failed", "marketface_worker_failed")
                    self._publish(item)
                    self.stats["requests"] += job.output.with_suffix(".requested").exists()
                    _retire(key, job)
                    del jobs[key]
                self._stop.wait(0.02)
        except Exception:
            # No exception text, private path or worker traceback enters reports.
            for key in jobs:
                self._publish(StickerMedia(key, "failed", "marketface_worker_failed"))
        finally:
            self.stats["unfinished"] = len(jobs)
            for key, job in jobs.items():
                if job.output is not None:
                    self.stats["requests"] += job.output.with_suffix(".requested").exists()
                _retire(key, job)
                self._publish(StickerMedia(key, "limited", "report_media_time_budget"))
            for send in self._pending:
                self._publish(StickerMedia(send.media_key, "limited", "report_media_time_budget"))
            self.done.set()
