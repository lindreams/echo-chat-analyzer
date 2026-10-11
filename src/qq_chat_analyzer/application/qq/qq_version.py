"""Read QQ executable versions and corroborated active update resources.

No execution, registry search, package-version guessing, or private logging.
Absent, contradictory, incomplete, or unreadable metadata is unknown.
"""

from __future__ import annotations

import ctypes
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class QQResources:
    """A checked package and active update config from one installation."""

    package_path: Path
    package_text: str
    version: tuple[int, int, int, int] | None = None
    config_text: str | None = None
    wrapper_path: Path | None = None
    file_states: tuple = ()


class QQVersionConflict(ValueError):
    """Two explicit version declarations disagree; PE cannot resolve this."""


def _package_version(info: dict) -> tuple[int, int, int, int] | None:
    if "version" not in info and "buildVersion" not in info:
        return None
    text = info.get("version")
    match = re.fullmatch(r"9\.9\.(0|[1-9][0-9]{0,4})(?:-([1-9][0-9]{0,4}))?", text) if isinstance(text, str) else None
    if match is None or int(match[1]) > 65535:
        raise ValueError("unidentified package version")
    declared = match[2]
    build = info.get("buildVersion")
    if "buildVersion" in info:
        if type(build) not in (str, int) or re.fullmatch(r"[1-9][0-9]{0,4}", str(build)) is None or int(build) > 65535:
            raise ValueError("unidentified package build")
        if declared is not None and declared != str(build):
            raise QQVersionConflict("conflicting package version")
    elif declared is None:
        raise ValueError("missing package build")
    build = declared if declared is not None else str(build)
    if int(build) > 65535:
        raise ValueError("unidentified package build")
    return (9, 9, int(match[1]), int(build))


def _json_object(text: str) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("ambiguous metadata")
            result[key] = value
        return result
    def invalid_constant(_):
        raise ValueError("invalid metadata")
    value = json.loads(text, object_pairs_hook=unique, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("invalid metadata")
    return value


def _metadata(path: Path, root: Path) -> str:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file() or resolved.stat().st_size > 1024 * 1024:
        raise ValueError("invalid metadata file")
    before = resolved.stat()
    text = resolved.read_text(encoding="utf-8-sig")
    after = resolved.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
    ):
        raise ValueError("metadata changed")
    _json_object(text)
    return text


def read_qq_resources(executable: Path) -> QQResources | None:
    """Follow NapCat 4.18.34's Windows curVersion lookup, never readyVersion.

    An existing invalid update config is an error, not permission to choose
    another directory. Package identity and native resources must corroborate
    curVersion before it can supersede the shell executable's PE version.
    Without a config, validate the base package instead of substituting PE.
    """
    root = executable.parent.resolve()
    configs = (root / "versions/config.json", root / "resources/app/versions/config.json")
    config = next((p for p in configs if p.exists() or p.is_symlink()), None)
    if config is None:
        package = root / "resources/app/package.json"
        if not package.exists():
            return None
        text = _metadata(package, root)
        version = _package_version(_json_object(text))
        wrapper = package.parent / "wrapper.node"
        if wrapper.exists():
            wrapper = wrapper.resolve(strict=True)
            if not wrapper.is_relative_to(root) or not wrapper.is_file():
                raise ValueError("invalid base resource")
        else:
            wrapper = None
        files = [package.resolve()]
        if wrapper is not None:
            files.append(wrapper)
        if executable.is_file():
            files.append(executable.resolve())
        states = tuple((p, p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ino) for p in files)
        return QQResources(package.resolve(), text, version, wrapper_path=wrapper, file_states=states)
    config_text = _metadata(config, root)
    current = _json_object(config_text).get("curVersion")
    match = re.fullmatch(r"9\.9\.(0|[1-9][0-9]{0,4})-([1-9][0-9]{0,4})", current) if isinstance(current, str) else None
    if match is None or any(int(part) > 65535 for part in match.groups()):
        raise ValueError("invalid active version")
    version = (9, 9, int(match[1]), int(match[2]))
    # Match lQ/Dae/Oae in the pinned NapCat bundle, including their fallback.
    primary = root / "versions" / current
    alternate = root / "resources/app/versions" / current
    package = primary / "resources/app/package.json"
    if not package.exists():
        package = alternate / "package.json"
    package_text = _metadata(package, root)
    info = _json_object(package_text)
    if _package_version(info) != version:
        raise QQVersionConflict("conflicting active version")
    natives = []
    for name in ("wrapper.node", "major.node"):
        candidates = (primary / name, primary / "resources/app" / name, alternate / name)
        native = next((p for p in candidates if p.exists()), None)
        if native is None and name == "major.node":
            # NapCat can use its AppId table when optional major.node is absent.
            continue
        if native is None:
            raise ValueError("missing active resource")
        native = native.resolve(strict=True)
        if not native.is_relative_to(root) or not native.is_file():
            raise ValueError("invalid active resource")
        natives.append(native)
    files = [config.resolve(), package.resolve(), *natives]
    if executable.is_file():
        files.append(executable.resolve())
    states = tuple((p, p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ino) for p in files)
    return QQResources(package.resolve(), package_text, version, config_text, natives[0], states)


class _FixedFileInfo(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "signature", "structure_version", "file_ms", "file_ls", "product_ms",
        "product_ls", "flags_mask", "flags", "os", "file_type", "subtype",
        "date_ms", "date_ls",
    )]


def _version(ms: int, ls: int) -> tuple[int, int, int, int]:
    return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)


def read_qq_version(path: Path) -> tuple[int, int, int, int] | None:
    """Return a full QQ NT Windows version, or None without guessing a build.

    Fixed file/product versions may omit the build (zero); use the other only
    when the release components agree. Conflicting full versions are unknown.
    Other product families are outside the known 9.9.x Windows build contract.
    """
    if sys.platform != "win32":
        return None
    try:
        if path.name.lower() != "qq.exe" or not path.is_file():
            return None
        before = path.stat()
        api = ctypes.WinDLL("version", use_last_error=True)
        api.GetFileVersionInfoSizeW.argtypes = [
            ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32),
        ]
        api.GetFileVersionInfoSizeW.restype = ctypes.c_uint32
        api.GetFileVersionInfoW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ]
        api.GetFileVersionInfoW.restype = ctypes.c_int
        api.VerQueryValueW.argtypes = [
            ctypes.c_void_p, ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint),
        ]
        api.VerQueryValueW.restype = ctypes.c_int
        handle = ctypes.c_uint32()
        size = api.GetFileVersionInfoSizeW(str(path), ctypes.byref(handle))
        # Version resources are small; corrupt sizes must not allocate gigabytes.
        if size < ctypes.sizeof(_FixedFileInfo) or size > 1024 * 1024:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not api.GetFileVersionInfoW(str(path), 0, size, buffer):
            return None
        pointer = ctypes.c_void_p()
        length = ctypes.c_uint()
        if not api.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return None
        address = pointer.value
        start = ctypes.addressof(buffer)
        if (
            address is None or length.value < ctypes.sizeof(_FixedFileInfo)
            or address < start or address + length.value > start + size
        ):
            return None
        info = _FixedFileInfo.from_buffer_copy(
            ctypes.string_at(address, ctypes.sizeof(_FixedFileInfo))
        )
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino,
        ):
            return None
        if info.signature != 0xFEEF04BD or info.file_type != 1:
            return None
        file = _version(info.file_ms, info.file_ls)
        product = _version(info.product_ms, info.product_ls)
        if file[:3] != product[:3]:
            return None
        if file[3] and product[3] and file != product:
            return None
        version = file if file[3] else product
        return version if version[:2] == (9, 9) and version[3] > 0 else None
    except Exception:
        # A failure to identify a version is neither a compatibility verdict
        # nor a launch failure. Never log the path or raw native exception.
        return None
