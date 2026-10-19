"""Provision the official pinned Windows x64 SQLite DLL for Frozen builds only.

Never modifies Python or a virtual environment. Direct spec builds and the
Windows wrapper both verify the same pins; a missing/mismatched DLL is fatal.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import urllib.request
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_pins() -> dict:
    return json.loads(Path(__file__).with_name("sqlite_runtime_pins.json").read_text(encoding="utf-8"))


def _verify_bytes(data: bytes, pins: dict) -> None:
    if hashlib.sha256(data).hexdigest() != pins["dllSha256"]:
        raise ValueError("SQLite DLL hash mismatch")
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError("SQLite DLL is not a PE image")
    offset = struct.unpack_from("<I", data, 60)[0]
    if (offset + 6 > len(data) or data[offset:offset + 4] != b"PE\0\0"
            or struct.unpack_from("<H", data, offset + 4)[0] != 0x8664):
        raise ValueError("SQLite DLL must be Windows AMD64")


def verify_dll(path: Path, pins: dict | None = None) -> Path:
    pins = load_pins() if pins is None else pins
    if path.is_symlink() or not path.is_file():
        raise ValueError("Pinned SQLite DLL is missing or linked; run bootstrap_sqlite_runtime.py")
    _verify_bytes(path.read_bytes(), pins)
    return path


def install_archive(payload: bytes, destination: Path, pins: dict | None = None) -> Path:
    pins = load_pins() if pins is None else pins
    if (len(payload) != pins["archiveSizeBytes"]
            or hashlib.sha3_256(payload).hexdigest() != pins["archiveSha3_256"]):
        raise ValueError("SQLite official archive size or SHA3-256 mismatch")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if sorted(archive.namelist()) != ["sqlite3.def", "sqlite3.dll"]:
            raise ValueError("Unexpected SQLite archive members")
        data = archive.read("sqlite3.dll")
    _verify_bytes(data, pins)
    if destination.exists() or destination.is_symlink():
        return verify_dll(destination, pins)  # Never overwrite unknown assets.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        output.write(data)
    return verify_dll(destination, pins)


def verify_frozen_binaries(entries: list, pins: dict | None = None) -> None:
    sqlite = [entry for entry in entries if Path(entry[0]).name.lower() == "sqlite3.dll"]
    if len(sqlite) != 1 or sqlite[0][0] != "sqlite3.dll":
        raise ValueError("Frozen build must contain exactly one root SQLite DLL")
    verify_dll(Path(sqlite[0][1]), pins)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Previously downloaded official ZIP")
    parser.add_argument("--verify", type=Path, help="Verify an existing DLL without downloading")
    args = parser.parse_args()
    if args.verify is not None:
        verify_dll(args.verify)
        return
    pins = load_pins()
    if args.archive is not None:
        payload = args.archive.read_bytes()
    else:
        with urllib.request.urlopen(pins["archiveUrl"], timeout=60) as response:
            if response.url != pins["archiveUrl"]:
                raise ValueError("Unexpected SQLite download redirect")
            payload = response.read(pins["archiveSizeBytes"] + 1)
    install_archive(payload, PROJECT_ROOT / "runtime/sqlite/sqlite3.dll", pins)
    print(f"Verified official SQLite {pins['version']} Windows x64 runtime")


if __name__ == "__main__":
    main()
