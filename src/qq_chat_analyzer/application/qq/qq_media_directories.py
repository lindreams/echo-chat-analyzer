"""Opt-in QQ NT directory discovery; never grants authority to read media.

Only the public INI is read. Directory metadata identifies existing original
scopes; installation paths, runtime state and snapshots are not inputs.
"""
from __future__ import annotations

from collections.abc import Callable
import configparser
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import time

from .. import sticker_media


@dataclass(frozen=True)
class QQMediaDirectories:
    account_directory: Path = field(repr=False)
    roots: tuple[Path, ...] = field(repr=False)


def qq_media_search_roots(scopes: tuple[Path, ...]) -> tuple[Path, ...]:
    """Coalesce known month layouts for traversal, never for read authority.

    The caller must also pass the unchanged scopes to the validator. Unknown
    layouts remain individual roots and retain the existing root-budget limit.
    """
    roots = []
    for scope in scopes:
        root = scope
        if scope.name == "Ori" and re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", scope.parent.name):
            base = scope.parent.parent
            if (base.name == "Pic" and base.parent.name == "nt_data"
                    and base.parent.parent.name == "nt_qq") or (
                base.name == "emoji-recv" and base.parent.name == "Emoji"
                and base.parent.parent.name == "nt_data"
                and base.parent.parent.parent.name == "nt_qq"
            ):
                root = base
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def discover_qq_media(
    *, config_path: Path | None = None, data_path: Path | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> tuple[QQMediaDirectories, ...]:
    """Check a data parent or numeric account directory, with bounded metadata I/O.

    Missing/invalid/unsafe/over-budget discovery returns no candidates, allowing
    one manual fallback. No partial list is used to infer an active account.
    """
    deadline = time.monotonic() + 3
    remaining = 4096

    def check_budget():
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or cancelled() or time.monotonic() > deadline:
            raise ValueError("Discovery stopped")

    def directory(path):
        check_budget()
        try:
            sticker_media._no_links(path)
            return path.is_dir()
        except (OSError, sticker_media._Rejected):
            return False

    def children(path):
        if not directory(path):
            return
        with os.scandir(path) as entries:
            for entry in entries:
                check_budget()
                yield Path(entry.path)

    try:
        check_budget()
        if data_path is None:
            ini = config_path if config_path is not None else (
                Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
                / "Documents/Tencent/QQ/UserDataInfo.ini")
            if not ini.is_absolute() or ".." in ini.parts or ini.drive.startswith("\\\\"):
                return ()
            with sticker_media._open_original(ini, ini.parent) as stream:
                before = sticker_media._witness(os.fstat(stream.fileno()))
                raw = stream.read(65537)
                if len(raw) > 65536 or sticker_media._witness(os.fstat(stream.fileno())) != before:
                    return ()
            encodings = ("utf-16",) if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "gb18030")
            text = None
            for encoding in encodings:
                try:
                    text = raw.decode(encoding)
                    break
                except UnicodeError:
                    continue
            if text is None or "\x00" in text:
                return ()
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(text)
            value = parser.get("UserDataSet", "UserDataSavePath").strip().strip('"')
            data_path = Path(value)
        parent = Path(data_path)
        if not parent.is_absolute() or ".." in parent.parts or parent.drive.startswith("\\\\"):
            return ()
        if not directory(parent):
            return ()
        accounts = [parent] if re.fullmatch(r"[0-9]{5,12}", parent.name) else children(parent)
        candidates = []
        for account in accounts:
            if not re.fullmatch(r"[0-9]{5,12}", account.name) or not directory(account):
                continue
            data = account / "nt_qq/nt_data"
            if not directory(data):
                continue
            roots = []
            for base in (data / "Pic", data / "Emoji/emoji-recv"):
                for month in sorted(children(base)):
                    if re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month.name) and directory(month / "Ori"):
                        roots.append(month / "Ori")
            for name in ("personal_emoji", "personal-emoji"):
                original = data / "Emoji" / name / "Ori"
                if directory(original):
                    roots.append(original)
            if roots:
                candidates.append(QQMediaDirectories(account, tuple(roots)))
        check_budget()
        return tuple(sorted(candidates, key=lambda item: item.account_directory.name))
    except (OSError, ValueError, configparser.Error, sticker_media._Rejected):
        return ()
