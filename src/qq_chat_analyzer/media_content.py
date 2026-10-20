"""Owned, read-only media storage; no cache paths or borrowed files."""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path
from threading import RLock


class StoredMedia:
    """A verified byte snapshot, deleted by the OS when its last owner closes.

    Consumers receive no path or write operation. Only one file/chunk needs to
    be resident while a report with many materials is retained or exported.
    """

    def __init__(self, raw: bytes):
        self.size = len(raw)
        self._lock = RLock()
        self._file = tempfile.TemporaryFile()
        try:
            self._file.write(raw)
            self._file.flush()
        except BaseException:
            self._file.close()
            raise

    def chunks(self, size: int = 256 * 1024):
        with self._lock:
            self._file.seek(0)
            while chunk := self._file.read(size):
                yield chunk

    def read(self) -> bytes:
        with self._lock:
            self._file.seek(0)
            return self._file.read()

    def close(self) -> None:
        with self._lock:
            self._file.close()


MEDIA_FILE_NAME = re.compile(r"[0-9a-f]{64}\.(?:png|jpg|gif|webp)\Z")


def require_safe_media_path(path: Path) -> None:
    for candidate in (path.absolute(), *path.absolute().parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
            raise ValueError("unsafe_media_export_path")


def file_chunks(path: Path):
    """Read an owned report artifact, rejecting links and concurrent changes."""
    require_safe_media_path(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("unsafe_media_export_file")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("media_export_file_changed")
        while chunk := stream.read(256 * 1024):
            yield chunk
        after = os.fstat(stream.fileno())
        named = path.stat()
        def witness(info):
            return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns

        require_safe_media_path(path)
        # Windows path stat can expose birth time as ctime while fstat exposes
        # change time. Compare stability within each API, never across them.
        if witness(before) != witness(named) or witness(opened) != witness(after):
            raise ValueError("media_export_file_changed")


def publish_media(chunks, destination: Path, *, cancelled=lambda: False) -> None:
    """Create a digest-named artifact exclusively; never overwrite user files."""
    if not MEDIA_FILE_NAME.fullmatch(destination.name):
        raise ValueError("invalid_media_export_name")
    expected = destination.stem
    require_safe_media_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        digest = hashlib.sha256()
        for chunk in file_chunks(destination):
            if cancelled():
                raise InterruptedError("media_export_cancelled")
            digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError("media_export_digest_mismatch")
        return
    digest = hashlib.sha256()
    with destination.open("xb") as stream:
        for chunk in chunks:
            if cancelled():
                raise InterruptedError("media_export_cancelled")
            digest.update(chunk)
            stream.write(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("media_export_digest_mismatch")
