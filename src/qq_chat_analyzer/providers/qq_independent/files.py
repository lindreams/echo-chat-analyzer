"""Local immutable input admission shared by production and research."""
import os
from pathlib import Path
import stat
SQLITE=b"SQLite format 3\0"
WRAPPED=b"SQLite header 3\0"
MAX_BYTES=64*1024**2

class SourceError(Exception):
    """Only a fixed public code; no path, SQL, key or native exception text."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _local_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    if os.name == "nt" and str(path).startswith("\\\\"):
        raise SourceError("local_path_required")
    return path


def _safe(path: Path) -> Path:
    path = _local_path(path)
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise SourceError("linked_path")
    return path


def _file(path: Path):
    info = _safe(path).stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SourceError("invalid_file")
    return info


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _no_sidecars(path):
    if any(os.path.lexists(str(path) + suffix) for suffix in ("-wal", "-shm", "-journal")):
        raise SourceError("frozen_main_required")


def _read_unchanged(path, *, prefix_bytes=None):
    before = _file(path)
    if prefix_bytes is None and before.st_size > MAX_BYTES:
        raise SourceError("prototype_size_limit")
    with path.open("rb", buffering=0) as stream:
        opened = os.fstat(stream.fileno())
        # Windows Python stat/fstat expose different ctime meanings. Compare
        # identity/size/mtime across APIs; retain ctime within each API below.
        if _identity(opened)[:4] != _identity(before)[:4]:
            raise SourceError("input_changed")
        data = stream.read(prefix_bytes if prefix_bytes is not None else MAX_BYTES + 1)
        if _identity(os.fstat(stream.fileno())) != _identity(opened):
            raise SourceError("input_changed")
    if _identity(_file(path)) != _identity(before):
        raise SourceError("input_changed")
    if prefix_bytes is None and len(data) != before.st_size:
        raise SourceError("input_changed")
    return data, before.st_size


def _read(path, *, header_only=False):
    _no_sidecars(path)
    data, size = _read_unchanged(path, prefix_bytes=1040 if header_only else None)
    _no_sidecars(path)
    return data, size


def _format(header, size):
    if header.startswith(SQLITE) and len(header) >= 100:
        page = int.from_bytes(header[16:18], "big")
        page = 65536 if page == 1 else page
        if page < 512 or page > 65536 or page & (page - 1) or size % page:
            raise SourceError("invalid_sqlite_size")
        if not int.from_bytes(header[28:32], "big") or header[24:28] != header[92:96]:
            raise SourceError("untrusted_page_count")
        if int.from_bytes(header[28:32], "big") != size // page:
            raise SourceError("page_count_mismatch")
        return "plaintext_candidate"
    if header.startswith(WRAPPED):
        if size < 1024 + 4096 or (size - 1024) % 4096:
            raise SourceError("invalid_encrypted_size")
        return "key_required"  # Header recognition is not authentication.
    raise SourceError("unsupported_header")
