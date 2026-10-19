"""Bounded, opt-in local original verification. Never uses network itself.

Only a content MD5 explicitly extracted from WeChat type-47 XML or from the QQ
PIC 45406 field authorizes a match. A file name or directory may only nominate
a candidate inside a caller-approved root; the full bytes must still hash to
the trusted digest and decode completely. QQ cache paths and opaque identity
bytes cannot prove an original. All paths and file contents are private;
failures expose fixed reason codes only.

Bytes the authenticated QQ bridge already fetched are validated here as well:
identity of the message and its unique PIC element is a precondition owned by
the caller, never inferred from these bytes.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
import hashlib
import os
from pathlib import Path
import re
import stat
import time
import warnings

from ..analysis.stickers import StickerData, StickerMedia, StickerSend


STICKER_MEDIA_BATCH_SIZE = 32
MAX_RETAINED_MEDIA_BYTES = 128 * 1024 * 1024
# Mirrors the bridge transfer bound: one base64 field under the RPC cap.
MAX_FETCHED_MEDIA_BYTES = 2 * 1024 * 1024
# Decoding is sequential. Bound canvas memory independently from total work;
# a fixed charge also bounds tiny-frame animations and per-frame bookkeeping.
MAX_FRAME_PIXELS = 4 * 1024 * 1024
DECODE_FRAME_COST = 64 * 1024
MAX_DECODE_WORK = 64 * 1024 * 1024
MAX_TOTAL_DECODE_WORK = 128 * 1024 * 1024
MAX_DECODE_SECONDS = 2.0


def qq_media_failure(media_key: str, code: str) -> StickerMedia:
    """Fixed shared failure categories; no private provider text enters reports."""
    if code == "qq_media_time_budget":
        return StickerMedia(media_key, "limited", "report_media_time_budget")
    if code in {"qq_media_budget_exhausted", "qq_media_too_large", "qq_media_decode_budget", "qq_media_transport_limit"}:
        return StickerMedia(media_key, "limited", "media_resource_budget")
    if code in {"qq_media_mapping_rejected", "qq_media_element_unconfirmed", "qq_media_message_unconfirmed"} or code.startswith("qq_media_group_"):
        return StickerMedia(media_key, "failed", "message_mapping_unconfirmed")
    if code == "qq_media_file_missing":
        return StickerMedia(media_key, "missing", "media_file_missing")
    return StickerMedia(media_key, "failed", "media_fetch_failed")


def associate_sticker_media(
    data: StickerData, *, media_keys: tuple[str, ...], roots: tuple[Path, ...] = (),
    source: str, cancelled: Callable[[], bool] = lambda: False,
    diagnostics: dict[str, int | bool] | None = None,
) -> StickerData:
    """Return the same sending facts with one bounded, explicitly selected batch.

    All keys must belong to this source/result. Repeated sends and already
    available originals do not cause repeated reads/decodes. Retained bytes
    across batches share the same memory ceiling; no disk cache is created.
    """
    if diagnostics is not None:
        diagnostics.clear()
    keys = set(media_keys)
    sends = {send.media_key: send for send in data.sends if send.source == source}
    if source not in {"qq", "wechat"} or not keys.issubset(sends) or len(keys) > STICKER_MEDIA_BATCH_SIZE:
        raise ValueError("invalid_sticker_batch")
    if not keys or cancelled():
        return data
    media = {item.media_key: item for item in resolve_sticker_media(data.sends)}
    media.update((item.media_key, item) for item in data.media)
    # Keep all occurrences' path hints; the resolver still reads/decodes once
    # per unique content. A later send need not carry the earlier cache path.
    pending = tuple(send for send in data.sends if send.source == source
                    and send.media_key in keys and not (
        media[send.media_key].status == "available" and media[send.media_key].original_bytes))
    if not pending:
        return data
    retained = sum(len(item.original_bytes or b"") for item in media.values())
    options = {}
    if source == "qq" and len(roots) > 16:
        from .qq.qq_media_directories import qq_media_search_roots

        options["authorized_scopes"] = roots
        roots = qq_media_search_roots(roots)
    results = resolve_sticker_media(
        pending, roots=roots, targeted=source == "qq", digest_names_only=source == "qq",
        cancelled=cancelled, max_total_bytes=max(0, MAX_RETAINED_MEDIA_BYTES - retained),
        diagnostics=diagnostics,
        **options)
    if cancelled():
        return data
    media.update((item.media_key, item) for item in results)
    return replace(data, media=tuple(media.values()))


# Source/basis pairs whose content digest may authorize an original. Any other
# evidence level (for example QQ MFACE opaque bytes) stays unsupported.
_VERIFIABLE_MD5_BASES = frozenset({
    ("wechat", "wechat_xml_md5"),
    ("qq", "qq_pic_45406_md5"),
})


class _Rejected(Exception):
    def __init__(self, status: str, reason: str):
        self.status = status
        self.reason = reason


def _no_links(path: Path) -> None:
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise _Rejected("unsafe", "reparse_or_symlink")


@contextmanager
def _open_original(path: Path, root: Path):
    """Read a regular file only after validating the opened handle's location.

    Windows denies concurrent write/delete while the handle is held. POSIX
    walks directory descriptors with O_NOFOLLOW, including every ancestor.
    Neither path opens a symlink target and then reads it before checking.
    """
    _no_links(path)
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        final = kernel.GetFinalPathNameByHandleW
        final.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        final.restype = wintypes.DWORD
        handle = create(str(path), 0x80000000, 1, None, 3, 0x08200000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise OSError("Cannot open local media")
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = final(handle, buffer, len(buffer), 0)
            if not length or length >= len(buffer):
                raise _Rejected("unsafe", "handle_location_unknown")
            actual = buffer.value
            if actual.startswith("\\\\?\\UNC\\"):
                actual = "\\\\" + actual[8:]
            elif actual.startswith("\\\\?\\"):
                actual = actual[4:]
            # A changed ancestor/junction may redirect an open. Reject before read.
            if Path(actual) != path or not Path(actual).is_relative_to(root):
                raise _Rejected("unsafe", "handle_path_changed")
            _no_links(path)
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            handle = None  # Ownership transferred to the descriptor.
        finally:
            if handle is not None:
                close(handle)
    else:
        directories = []
        try:
            descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            directories.append(descriptor)
            for component in path.parts[1:-1]:
                descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                     dir_fd=descriptor)
                directories.append(descriptor)
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=descriptor)
        finally:
            for directory in reversed(directories):
                os.close(directory)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise _Rejected("unsafe", "not_regular_file")
        yield stream


def _witness(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _check_gif_canvas(raw: bytes, check_time: Callable[[], None]) -> None:
    """Check block extents before a codec can allocate a disposal canvas.

    This skips compressed sub-blocks; it does not decode LZW or replace Pillow's
    complete frame validation. Later GIF frames may otherwise enlarge its canvas
    during seek(), before the caller can inspect the new dimensions.
    """
    if len(raw) < 13:
        raise _Rejected("invalid", "invalid_image")
    width = int.from_bytes(raw[6:8], "little")
    height = int.from_bytes(raw[8:10], "little")
    if not width or not height:
        raise _Rejected("invalid", "invalid_image")
    packed = raw[10]
    position = 13 + (3 * (2 << (packed & 7)) if packed & 128 else 0)
    while position < len(raw):
        check_time()
        tag = raw[position]
        position += 1
        if tag == 0x3B:  # trailer
            if width * height > MAX_FRAME_PIXELS:
                raise _Rejected("limited", "decode_budget")
            return
        if tag == 0x2C:  # image descriptor and optional local palette
            if position + 9 > len(raw):
                break
            x, y, w, h = (int.from_bytes(raw[position + i:position + i + 2], "little")
                           for i in (0, 2, 4, 6))
            if not w or not h or x + w > width or y + h > height:
                raise _Rejected("invalid", "invalid_image")
            packed = raw[position + 8]
            position += 9 + (3 * (2 << (packed & 7)) if packed & 128 else 0)
            position += 1  # LZW minimum code size; Pillow validates the raster.
        elif tag == 0x21:  # extension label followed by data sub-blocks
            position += 1
        else:
            break
        while position < len(raw):
            check_time()
            size = raw[position]
            position += 1
            if not size:
                break
            position += size
        else:
            break
    raise _Rejected("invalid", "invalid_image")


def _inspect(raw: bytes, *, max_pixels: int, max_frames: int | None,
             budget: dict[str, int] | None = None) -> tuple[str, int]:
    """Validate sequentially without retaining decoded frames or a frame cache."""
    # Recognizable out-of-scope containers are not corrupt supported images.
    # Do not load additional codecs just to identify them.
    if raw.startswith((b"BM", b"II\x2a\x00", b"MM\x00\x2a")):
        raise _Rejected("unsupported", "unsupported_format")
    # Keep decoding lazy so ordinary analysis never loads native image codecs.
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        raise _Rejected("unsupported", "decoder_unavailable") from None
    deadline = time.monotonic() + MAX_DECODE_SECONDS

    def check_time() -> None:
        # Cooperative: native codec calls cannot be forcibly interrupted here.
        if time.monotonic() > deadline:
            raise _Rejected("limited", "decode_budget")

    try:
        if raw.startswith((b"GIF87a", b"GIF89a")):
            _check_gif_canvas(raw, check_time)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw), formats=("PNG", "JPEG", "GIF", "WEBP")) as container:
                if container.format not in {"PNG", "JPEG", "GIF", "WEBP"}:
                    raise _Rejected("invalid", "unsupported_format")
                if container.width * container.height > MAX_FRAME_PIXELS:
                    raise _Rejected("limited", "decode_budget")
                container.verify()
            check_time()
            with Image.open(BytesIO(raw), formats=("PNG", "JPEG", "GIF", "WEBP")) as image:
                fmt = image.format
                count = 0
                total_pixels = 0
                work = 0
                while True:
                    check_time()
                    try:
                        image.seek(count)
                    except EOFError:
                        break
                    count += 1
                    pixels = image.width * image.height
                    total_pixels += pixels
                    frame_work = pixels + DECODE_FRAME_COST
                    work += frame_work
                    if (pixels > MAX_FRAME_PIXELS or total_pixels > max_pixels
                            or work > MAX_DECODE_WORK
                            or (max_frames is not None and count > max_frames)):
                        raise _Rejected("limited", "decode_budget")
                    if budget is not None:
                        budget["pixels"] -= pixels
                        budget["work"] -= frame_work
                        if "frames" in budget:
                            budget["frames"] -= 1
                        if any(remaining < 0 for remaining in budget.values()):
                            raise _Rejected("limited", "total_decode_budget")
                    image.load()
                    check_time()
                # APNG can include a default image in addition to animation frames.
                actual = "APNG" if fmt == "PNG" and image.get_format_mimetype() == "image/apng" else fmt
                return "WebP" if actual == "WEBP" else actual, count
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, IndexError, EOFError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise _Rejected("invalid", "invalid_image") from None


def verify_fetched_media(
    raw: bytes, *, media_key: str, expected_md5: str,
    max_pixels: int = 32 * 1024 * 1024, max_frames: int | None = None,
) -> StickerMedia:
    """Validate bytes fetched for one message whose PIC element was proved.

    A digest equal to the message's own PIC digest is the verified original.
    A different digest stays a distinct trusted preview: the kernel uniquely
    proved message, sender and element, so the content is that send's media, but
    it is not shown or counted as the digest-verified original. Anything that
    fails the size, format or complete decode check yields no bytes at all.
    """
    if not isinstance(raw, (bytes, bytearray)) or not raw or len(raw) > MAX_FETCHED_MEDIA_BYTES:
        return StickerMedia(media_key, "invalid", "invalid_size")
    content = bytes(raw)
    try:
        fmt, frames = _inspect(content, max_pixels=max_pixels, max_frames=max_frames)
    except _Rejected as failure:
        return StickerMedia(media_key, failure.status, failure.reason)
    verified = isinstance(expected_md5, str) and hashlib.md5(content).hexdigest() == expected_md5.lower()
    return StickerMedia(
        media_key, "available" if verified else "preview",
        None if verified else "content_digest_mismatch",
        sha256=hashlib.sha256(content).hexdigest(), format=fmt, frame_count=frames,
        animation_preserved=frames > 1, byte_count=len(content), original_bytes=content,
    )


def resolve_sticker_media(
    sends: Iterable[StickerSend], *, roots: tuple[Path, ...] = (),
    targeted: bool = False,
    digest_names_only: bool = False,
    authorized_scopes: tuple[Path, ...] | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    max_file_bytes: int = 16 * 1024 * 1024,
    max_total_bytes: int = 128 * 1024 * 1024,
    max_entries: int = 4096, max_scan_entries: int = 100_000,
    max_depth: int = 8,
    max_pixels: int = 32 * 1024 * 1024, max_frames: int | None = None,
    max_files: int = 4096,
    max_total_pixels: int = 64 * 1024 * 1024, max_total_frames: int | None = None,
    diagnostics: dict[str, int | bool] | None = None,
) -> tuple[StickerMedia, ...]:
    """Return one media result per key; any incomplete search fails closed.

    Caller-supplied roots are the only read authority. No roots means no file
    I/O. MD5 is source linkage, not collision-resistant integrity: conflicting
    SHA-256 contents for one MD5 are ambiguous, never arbitrarily selected.
    Total bytes/entries/depth include unmatched files; decoding has per-original
    canvas/pixel/work/time limits and optional explicit frame limits. A 10-second
    cooperative deadline bounds traversal.

    ``targeted`` is for a large client cache whose layout is unknown: the walk
    is bounded by ``max_scan_entries``; only digest-named or exact QQ path-hint
    candidates are opened. Names, directories and suffixes remain candidate
    hints; the full-file MD5 and the decode must still agree. A tree no larger
    than ``max_entries`` files keeps the complete read, so an explicitly
    selected folder of renamed copies behaves exactly as before.
    ``digest_names_only`` disables full-content fallback even in small caches;
    the default preserves explicit folders of renamed copies. ``cancelled``
    stops cooperatively between entries, reads and bounded decoding stages.
    ``authorized_scopes`` restricts coalesced traversal roots to the original
    approved directories. Only their ancestors may be enumerated to reach
    them; siblings are skipped and never opened. Scope validation and all
    traversal share one entry budget, deadline and byte budget.

    QQ absolute local path hints may also nominate files encountered by this
    authorized walk. Hints never add roots, bypass the whitelist or establish
    content identity. Diagnostics contain aggregate counts/coverage only.
    """
    occurrences = tuple(sends)
    unique = {send.media_key: send for send in occurrences}
    stats = dict(entries_seen=0, files_seen=0, candidate_files=0, files_read=0,
                 name_candidates=0, path_candidates=0, content_matches=0,
                 traversal_complete=False, all_files_checked=False, budget_exhausted=False)
    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update(stats)
    results = {}
    wanted = {}
    for key, send in unique.items():
        digest = send.content_md5
        if (send.source, send.identity_basis) not in _VERIFIABLE_MD5_BASES or not digest:
            results[key] = StickerMedia(key, "unsupported", "original_digest_unproven")
        elif not re.fullmatch("[0-9a-f]{32}", digest):
            results[key] = StickerMedia(key, "unsupported", "invalid_digest")
        elif not roots:
            results[key] = StickerMedia(key, "not_requested", "no_trusted_roots")
        else:
            wanted[digest] = key
    if not wanted:
        return tuple(results[key] for key in unique)

    originals: dict[str, tuple[bytes, str]] = {}
    ambiguous = set()
    entries = total_bytes = files = 0
    deadline = time.monotonic() + 10
    every: list[tuple[Path, Path]] = []
    named: dict[str, list[tuple[Path, Path]]] = {digest: [] for digest in wanted}
    decode_budget = {"pixels": max_total_pixels, "work": MAX_TOTAL_DECODE_WORK}
    if max_total_frames is not None:
        decode_budget["frames"] = max_total_frames

    def check_cancelled():
        if cancelled():
            raise _Rejected("cancelled", "user_cancelled")

    try:
        check_cancelled()
        if len(roots) > 16:
            raise _Rejected("limited", "root_budget")
        hints: dict[str, set[Path]] = {digest: set() for digest in wanted}
        for send in occurrences:
            check_cancelled()
            if time.monotonic() > deadline:
                raise _Rejected("limited", "scan_budget")
            if (send.source != "qq" or send.identity_basis != "qq_pic_45406_md5"
                    or send.content_md5 not in wanted):
                continue
            for value in send.local_paths:
                # No filesystem access to source-provided paths here. Only
                # exact matches encountered inside approved scopes nominate.
                path = Path(value)
                if (path.is_absolute() and ".." not in path.parts
                        and not path.drive.startswith("\\\\") and "\x00" not in value):
                    hints[send.content_md5].add(path)
        limit = max_scan_entries if targeted else max_entries
        pending = []
        for supplied in roots:
            root = Path(supplied)
            if not root.is_absolute() or ".." in root.parts or root.drive.startswith("\\\\"):
                raise _Rejected("unsafe", "invalid_root")
            _no_links(root)
            root = root.resolve(strict=True)
            if not root.is_dir():
                raise _Rejected("unsafe", "invalid_root")
            pending.append((root, root, 0))
        scopes = None
        scope_ancestors = set()
        if authorized_scopes is not None:
            if not authorized_scopes:
                raise _Rejected("unsafe", "invalid_scope")
            scopes = set()
            for supplied in authorized_scopes:
                check_cancelled()
                entries += 1
                if entries > limit or time.monotonic() > deadline:
                    raise _Rejected("limited", "scan_budget")
                scope = Path(supplied)
                if not scope.is_absolute() or ".." in scope.parts or scope.drive.startswith("\\\\"):
                    raise _Rejected("unsafe", "invalid_scope")
                if not any(scope.is_relative_to(root) for root, _, _ in pending):
                    raise _Rejected("unsafe", "invalid_scope")
                _no_links(scope)
                if not scope.is_dir():
                    raise _Rejected("unsafe", "invalid_scope")
                scopes.add(scope)
                scope_ancestors.update((scope, *scope.parents))
        while pending:
            check_cancelled()
            directory, root, depth = pending.pop()
            inside_scope = scopes is None or any(part in scopes for part in (directory, *directory.parents))
            _no_links(directory)
            with os.scandir(directory) as children:
                for child in children:
                    check_cancelled()
                    entries += 1
                    if entries > limit or time.monotonic() > deadline:
                        raise _Rejected("limited", "scan_budget")
                    path = Path(child.path)
                    if not inside_scope and path not in scope_ancestors:
                        continue
                    _no_links(path)
                    # Windows DirEntry.stat caches dev/ino as zero. Path.lstat
                    # supplies the real identity for comparison with fstat.
                    info = path.lstat()
                    if stat.S_ISDIR(info.st_mode):
                        if depth >= max_depth:
                            raise _Rejected("limited", "depth_budget")
                        pending.append((path, root, depth + 1))
                        continue
                    if not stat.S_ISREG(info.st_mode):
                        raise _Rejected("unsafe", "not_regular_file")
                    if not inside_scope:
                        raise _Rejected("unsafe", "scope_changed")
                    files += 1
                    if len(every) < max_entries:
                        every.append((path, root))
                    if targeted or digest_names_only:
                        name = path.name.lower()
                        name_match = path_match = False
                        for digest in wanted:
                            by_name, by_path = digest in name, path in hints[digest]
                            if by_name or by_path:
                                named[digest].append((path, root))
                            name_match |= by_name
                            path_match |= by_path
                        stats["name_candidates"] += int(name_match)
                        stats["path_candidates"] += int(path_match)

        stats["traversal_complete"] = True
        complete = targeted and not digest_names_only and files <= max_entries and len(every) == files
        if (not targeted and not digest_names_only) or complete:
            selected = every
        else:
            selected, seen = [], set()
            for digest in wanted:
                for item in named[digest]:
                    if item[0] not in seen:
                        seen.add(item[0])
                        selected.append(item)
        stats["candidate_files"] = len(selected)
        if len(selected) > max_files:
            raise _Rejected("limited", "file_count_budget")
        for path, root in selected:
            check_cancelled()
            if time.monotonic() > deadline:
                raise _Rejected("limited", "scan_budget")
            _no_links(path)
            info = path.lstat()
            if info.st_size > max_file_bytes:
                raise _Rejected("limited", "file_byte_budget")
            if total_bytes + info.st_size > max_total_bytes:
                raise _Rejected("limited", "total_byte_budget")
            with _open_original(path, root) as stream:
                check_cancelled()
                before = os.fstat(stream.fileno())
                # Windows Python's path stat and CRT fstat can report
                # different ctime meanings. Compare shared identity and
                # mtime across APIs; compare ctime only within each API.
                if _witness(before)[:4] != _witness(info)[:4]:
                    raise _Rejected("unsafe", "file_changed")
                raw = stream.read(min(max_file_bytes, max_total_bytes - total_bytes) + 1)
                total_bytes += len(raw)
                if (len(raw) != before.st_size or len(raw) > max_file_bytes
                        or total_bytes > max_total_bytes
                        or _witness(os.fstat(stream.fileno())) != _witness(before)):
                    raise _Rejected("unsafe", "file_changed")
                _no_links(path)
                if _witness(path.stat()) != _witness(info):
                    raise _Rejected("unsafe", "file_changed")
            digest = hashlib.md5(raw).hexdigest()
            stats["files_read"] += 1
            check_cancelled()
            if digest in wanted:
                previous = originals.get(digest)
                if previous is not None and previous[0] != raw:
                    ambiguous.add(digest)
                else:
                    originals[digest] = (raw, str(path))
        for digest, key in wanted.items():
            if digest in ambiguous:
                results[key] = StickerMedia(key, "ambiguous", "digest_content_conflict")
            elif digest not in originals:
                # No name/path candidate is not proof of content absence.
                # Keep the existing fixed reason code for callers.
                no_name = (targeted or digest_names_only) and not complete and not named[digest]
                results[key] = StickerMedia(
                    key, "missing",
                    "no_digest_name_match" if no_name else (
                        "digest_mismatch" if digest_names_only else "no_digest_match"))
            else:
                raw, reference = originals[digest]
                try:
                    if time.monotonic() > deadline:
                        raise _Rejected("limited", "scan_budget")
                    fmt, frames = _inspect(raw, max_pixels=max_pixels, max_frames=max_frames,
                                           budget=decode_budget)
                    check_cancelled()
                    if time.monotonic() > deadline:
                        raise _Rejected("limited", "scan_budget")
                    results[key] = StickerMedia(
                        key, "available", verified_reference=reference,
                        sha256=hashlib.sha256(raw).hexdigest(), format=fmt,
                        frame_count=frames, animation_preserved=frames > 1,
                        byte_count=len(raw), original_bytes=raw,
                    )
                except _Rejected as failure:
                    results[key] = StickerMedia(key, failure.status, failure.reason)
        stats["all_files_checked"] = len(selected) == files
    except (_Rejected, OSError, ValueError) as failure:
        status = failure.status if isinstance(failure, _Rejected) else "unreadable"
        reason = failure.reason if isinstance(failure, _Rejected) else "local_read_failed"
        # An incomplete search cannot rule out ambiguity or assert absence.
        for key in wanted.values():
            results[key] = StickerMedia(key, status, reason)
    finally:
        stats["entries_seen"], stats["files_seen"] = entries, files
        stats["content_matches"] = len(originals)
        stats["budget_exhausted"] = any(item.status == "limited" for item in results.values())
        if diagnostics is not None:
            diagnostics.update(stats)
    return tuple(results[key] for key in unique)
