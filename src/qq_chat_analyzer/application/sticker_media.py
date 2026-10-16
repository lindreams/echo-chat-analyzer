"""Bounded, opt-in local original verification. Never uses network or source hints.

Only a content MD5 explicitly extracted from WeChat type-47 XML authorizes a
match. QQ cache paths and opaque identity bytes cannot prove an original. All
paths and file contents are private; failures expose fixed reason codes only.
"""
from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from io import BytesIO
import hashlib
import os
from pathlib import Path
import re
import stat
import time
import warnings

from ..analysis.stickers import StickerMedia, StickerSend


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


def _inspect(raw: bytes, *, max_pixels: int, max_frames: int) -> tuple[str, int]:
    """Validate all frames with bounded decompression, retaining original bytes."""
    # Keep decoding lazy so ordinary analysis never loads native image codecs.
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        raise _Rejected("unsupported", "decoder_unavailable") from None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw), formats=("PNG", "JPEG", "GIF", "WEBP")) as container:
                if container.format not in {"PNG", "JPEG", "GIF", "WEBP"}:
                    raise _Rejected("invalid", "unsupported_format")
                container.verify()
            with Image.open(BytesIO(raw), formats=("PNG", "JPEG", "GIF", "WEBP")) as image:
                fmt = image.format
                count = 0
                total_pixels = 0
                while True:
                    try:
                        image.seek(count)
                    except EOFError:
                        break
                    count += 1
                    total_pixels += image.width * image.height
                    if count > max_frames or total_pixels > max_pixels:
                        raise _Rejected("limited", "decode_budget")
                    image.load()
                # APNG can include a default image in addition to animation frames.
                actual = "APNG" if fmt == "PNG" and image.get_format_mimetype() == "image/apng" else fmt
                return "WebP" if actual == "WEBP" else actual, count
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise _Rejected("invalid", "invalid_image") from None


def resolve_sticker_media(
    sends: Iterable[StickerSend], *, roots: tuple[Path, ...] = (),
    max_file_bytes: int = 16 * 1024 * 1024,
    max_total_bytes: int = 128 * 1024 * 1024,
    max_entries: int = 4096, max_depth: int = 8,
    max_pixels: int = 32 * 1024 * 1024, max_frames: int = 128,
) -> tuple[StickerMedia, ...]:
    """Return one media result per key; any incomplete search fails closed.

    Caller-supplied roots are the only read authority. No roots means no file
    I/O. MD5 is source linkage, not collision-resistant integrity: conflicting
    SHA-256 contents for one MD5 are ambiguous, never arbitrarily selected.
    Total bytes/entries/depth include unmatched files; decoding has per-original
    pixel/frame limits. A 10-second cooperative deadline bounds traversal.
    """
    unique = {send.media_key: send for send in sends}
    results = {}
    wanted = {}
    for key, send in unique.items():
        digest = send.content_md5
        if send.source != "wechat" or send.identity_basis != "wechat_xml_md5" or not digest:
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
    entries = total_bytes = 0
    deadline = time.monotonic() + 10
    try:
        if len(roots) > 16:
            raise _Rejected("limited", "root_budget")
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
        while pending:
            directory, root, depth = pending.pop()
            _no_links(directory)
            with os.scandir(directory) as children:
                for child in children:
                    entries += 1
                    if entries > max_entries or time.monotonic() > deadline:
                        raise _Rejected("limited", "scan_budget")
                    path = Path(child.path)
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
                    if info.st_size > max_file_bytes:
                        raise _Rejected("limited", "file_byte_budget")
                    if total_bytes + info.st_size > max_total_bytes:
                        raise _Rejected("limited", "total_byte_budget")
                    with _open_original(path, root) as stream:
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
                results[key] = StickerMedia(key, "missing", "no_digest_match")
            else:
                raw, reference = originals[digest]
                try:
                    if time.monotonic() > deadline:
                        raise _Rejected("limited", "scan_budget")
                    fmt, frames = _inspect(raw, max_pixels=max_pixels, max_frames=max_frames)
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
    except (_Rejected, OSError, ValueError) as failure:
        status = failure.status if isinstance(failure, _Rejected) else "unreadable"
        reason = failure.reason if isinstance(failure, _Rejected) else "local_read_failed"
        # An incomplete search cannot rule out ambiguity or assert absence.
        for key in wanted.values():
            results[key] = StickerMedia(key, status, reason)
    return tuple(results[key] for key in unique)
