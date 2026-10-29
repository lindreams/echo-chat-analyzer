"""Windows portable runtime contract tests.

The portable package must ship every runtime asset the *product* actually
consumes, and must never ship machine-local state. Both properties are
defined once, in ``scripts/windows_runtime_manifest.json``, and consumed by
both ``scripts/build_windows_exe.ps1`` and these tests so the two can never
drift into separate lists.

These checks are static: they read the manifest and the build script, and they
never require the real runtime (or a real build) to be present.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
import tomllib
import hashlib
import io
import runpy
import struct
import zipfile

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "scripts" / "windows_runtime_manifest.json"


def _sqlite_build_tools():
    return runpy.run_path(str(PROJECT_ROOT / "scripts/bootstrap_sqlite_runtime.py"))


def _fictional_sqlite_archive():
    dll = bytearray(256)
    dll[:2] = b"MZ"
    struct.pack_into("<I", dll, 60, 128)
    dll[128:132] = b"PE\0\0"
    struct.pack_into("<H", dll, 132, 0x8664)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("sqlite3.dll", dll)
        archive.writestr("sqlite3.def", "fictional exports")
    payload = stream.getvalue()
    pins = {"archiveSizeBytes": len(payload),
            "archiveSha3_256": hashlib.sha3_256(payload).hexdigest(),
            "dllSha256": hashlib.sha256(dll).hexdigest()}
    return payload, bytes(dll), pins


def prepare_sqlite_build_input(project_root):
    """Give a simulated project real validation with fictional PE bytes/pins."""
    scripts = project_root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "bootstrap_sqlite_runtime.py").write_bytes(
        (PROJECT_ROOT / "scripts/bootstrap_sqlite_runtime.py").read_bytes())
    payload, _, pins = _fictional_sqlite_archive()
    (scripts / "sqlite_runtime_pins.json").write_text(json.dumps(pins), encoding="utf-8")
    return _sqlite_build_tools()["install_archive"](
        payload, project_root / "runtime/sqlite/sqlite3.dll", pins)


def test_sqlite_bootstrap_verifies_before_publishing_and_preserves_existing(tmp_path):
    tools = _sqlite_build_tools()
    payload, dll, pins = _fictional_sqlite_archive()
    target = tmp_path / "sqlite3.dll"
    with pytest.raises(ValueError):
        tools["install_archive"](payload + b"changed", target, pins)
    assert not target.exists()
    assert tools["install_archive"](payload, target, pins) == target
    assert target.read_bytes() == dll
    target.write_bytes(b"another task's artifact")
    with pytest.raises(ValueError):
        tools["install_archive"](payload, target, pins)
    assert target.read_bytes() == b"another task's artifact"


def test_sqlite_bootstrap_rejects_wrong_dll_even_in_verified_archive(tmp_path):
    tools = _sqlite_build_tools()
    payload, _, pins = _fictional_sqlite_archive()
    pins["dllSha256"] = "0" * 64
    with pytest.raises(ValueError):
        tools["install_archive"](payload, tmp_path / "sqlite3.dll", pins)
    assert not (tmp_path / "sqlite3.dll").exists()


def test_sqlite_collection_refuses_ambient_or_duplicate_dll(tmp_path):
    tools = _sqlite_build_tools()
    _, dll, pins = _fictional_sqlite_archive()
    good, old = tmp_path / "pinned.dll", tmp_path / "ambient.dll"
    good.write_bytes(dll)
    old.write_bytes(b"old interpreter sqlite")
    pinned = ("sqlite3.dll", str(good), "BINARY")
    tools["verify_frozen_binaries"]([pinned], pins)
    for entries in ([], [("sqlite3.dll", str(old), "BINARY")],
                    [pinned, ("nested/sqlite3.dll", str(old), "BINARY")]):
        with pytest.raises(ValueError):
            tools["verify_frozen_binaries"](entries, pins)




# State the desktop app itself creates beside its own executable (``logs``) and
# the report the bundled WeChat diagnostic runner writes by default. Both are
# machine-local run residue: a fresh full build cannot produce them, but a smoke
# run followed by a ``-RuntimeOnly`` build or a directory copy can.

# Native WeChat binaries the shipped product actually loads. Their identity is
# pinned by content hash because only presence was checked before.
WECHAT_PINNED_ASSETS = {
    "wechat/WCDB.dll",
    "wechat/wcdb_cli.exe",
    "wechat/wx_key.dll",
}

# The tracked build-toolchain declaration that makes the frozen artifact
# reproducible from a clean clone. Exact pins only: no ranges.

# The documentation must show an install command that pulls in the build extra
# (tolerant of extra ordering, strict about the extra being there).

# Values that must never appear in a tracked contract file: absolute paths,
# endpoints, and credential vocabulary. Legitimate asset names such as
# ``wx_key.dll`` are deliberately not matched here.
FORBIDDEN_VALUE_FRAGMENTS = (
    "token",
    "cookie",
    "password",
    "secret",
    "db_key",
    "uin",
    "C:\\",
    "C:/",
    "/Users/",
    "http://",
    "https://",
)

# --------------------------------------------------------------------- QQ
# Every path below is reachable from the shipped product boot chain.

# ------------------------------------------------------------------ WeChat



# Machine-local state that must never become a shipped requirement.

# Filename prefixes NapCat uses for per-install configuration. They carry a
# real QQ identifier, so no contract entry may ever be named like one.
INSTALL_SCOPED_PREFIXES = ("napcat_", "napcat-protocol_", "onebot11_")


def _load_manifest() -> dict:
    assert MANIFEST_PATH.is_file(), (
        "runtime contract manifest is missing: "
        "scripts/windows_runtime_manifest.json"
    )
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _entries(manifest: dict, key: str) -> list[dict]:
    value = manifest.get(key)
    assert isinstance(value, list), f"manifest field '{key}' must be a list"
    return value


def _paths(manifest: dict, key: str) -> set[str]:
    return {str(entry["path"]) for entry in _entries(manifest, key)}


# ------------------------------------------------------- manifest structure


def test_manifest_paths_are_relative_and_normalised() -> None:
    manifest = _load_manifest()

    for key in ("requirements", "privatePaths", "packageDirectories"):
        for entry in _entries(manifest, key):
            path = str(entry["path"])
            assert not path.startswith(("/", "\\")), path
            assert ":" not in path, path
            assert "\\" not in path, path
            assert ".." not in path.split("/"), path


def test_manifest_carries_no_endpoints_or_credential_vocabulary() -> None:
    manifest = _load_manifest()
    payload = json.dumps(manifest, ensure_ascii=False).lower()

    for fragment in FORBIDDEN_VALUE_FRAGMENTS:
        assert fragment.lower() not in payload, fragment


def test_manifest_never_names_an_install_scoped_config_file() -> None:
    manifest = _load_manifest()

    for key in ("requirements", "privatePaths", "packageDirectories"):
        for entry in _entries(manifest, key):
            name = str(entry["path"]).rsplit("/", 1)[-1].lower()
            for prefix in INSTALL_SCOPED_PREFIXES:
                assert not name.startswith(prefix), entry


# -------------------------------------------------------- required coverage


@pytest.mark.parametrize("path", ['qq-napcat-candidate/napcat.mjs', 'qq-napcat-candidate/plugins/napcat-plugin-echo/index.mjs', 'wechat/wcdb_cli.exe', 'wechat/wx_key_helper.cjs'])
def test_manifest_requires_every_product_hard_dependency(path: str) -> None:
    manifest = _load_manifest()
    entries = {
        str(entry["path"]): entry for entry in _entries(manifest, "requirements")
    }

    assert path in entries, f"runtime contract is missing required asset: {path}"
    assert entries[path]["type"] == "file", entries[path]


# --------------------------------------------------------- privacy contract


def test_private_paths_are_never_shipped_requirements() -> None:
    manifest = _load_manifest()
    requirements = _paths(manifest, "requirements")
    private = _paths(manifest, "privatePaths")

    assert requirements.isdisjoint(private)
    for requirement in requirements:
        for private_path in private:
            assert not requirement.startswith(f"{private_path}/"), (
                f"{requirement} sits under private path {private_path}"
            )


# ------------------------------------------- build and tests share one source


def test_manifest_limits_recursive_copy_to_program_payloads() -> None:
    assert _paths(_load_manifest(), "packageDirectories") == {
        "qq-napcat-candidate/node_modules", "qq-napcat-candidate/static", "qq-napcat-candidate/native", "qq-napcat-candidate/worker", "wechat/node_modules/koffi",
    }


# ------------------------------------------------- release tree run residue


def _release_tree_private_paths(manifest: dict) -> list[str]:
    value = manifest.get("releaseTreePrivatePaths")
    assert isinstance(value, list), "manifest field 'releaseTreePrivatePaths' must be a list"
    return [str(entry) for entry in value]


def test_release_tree_private_paths_are_not_runtime_requirements() -> None:
    """Run residue must never be reachable through the copy contract."""
    manifest = _load_manifest()
    requirements = _paths(manifest, "requirements")
    copied = set(requirements) | _paths(manifest, "packageDirectories")

    for path in _release_tree_private_paths(manifest):
        # ``scripts/wcdb-diagnostic.txt`` lives beside the shipped runner, so
        # only its exact name may conflict; ``logs`` is a whole tree.
        assert path not in copied, path
        assert not any(entry.startswith(f"{path}/") for entry in copied), path


# ------------------------------------------------ WeChat native asset pins


def _wechat_pins(manifest: dict) -> dict:
    value = manifest.get("wechatPinnedAssets")
    assert isinstance(value, dict), "manifest field 'wechatPinnedAssets' must be an object"
    return {str(name): str(digest) for name, digest in value.items()}


def test_manifest_pins_the_wechat_native_assets_that_ship() -> None:
    manifest = _load_manifest()

    assert set(_wechat_pins(manifest)) == WECHAT_PINNED_ASSETS


# ------------------------------------------------ tracked build toolchain


def test_spec_excludes_unused_jieba_data_and_local_install_provenance(tmp_path):
    """Keep runtime metadata/data without shipping editable-install locations."""
    import runpy
    from types import SimpleNamespace
    from PyInstaller.utils.hooks import collect_data_files

    collected = [
        (str(Path(destination) / Path(source).name), source, "DATA")
        for source, destination in collect_data_files("jieba")
    ]
    metadata = "qq_chat_analyzer-0.2.2.dist-info"
    provenance = f"{metadata}/direct_url.json"
    retained_metadata = {f"{metadata}/{name}" for name in (
        "METADATA", "WHEEL", "entry_points.txt",
    )}
    collected += [(name, "fictional source", "DATA") for name in (
        provenance, *retained_metadata, "unrelated/direct_url.json",
    )]
    # The metadata-only Analysis seam still receives a validated SQLite input.
    (tmp_path / "pyproject.toml").write_bytes((PROJECT_ROOT / "pyproject.toml").read_bytes())
    version_source = tmp_path / "src/qq_chat_analyzer/version.py"
    version_source.parent.mkdir(parents=True)
    version_source.write_bytes((PROJECT_ROOT / "src/qq_chat_analyzer/version.py").read_bytes())
    dll = prepare_sqlite_build_input(tmp_path)
    analysis = SimpleNamespace(datas=collected, pure=[], scripts=[],
                               binaries=[("sqlite3.dll", str(dll), "BINARY")])
    # Execute the real spec's post-Analysis collection rule without building.
    result = runpy.run_path(str(PROJECT_ROOT / "LocalChatAnalyzer.spec"), init_globals={
        "SPEC": str(tmp_path / "LocalChatAnalyzer.spec"),
        "Analysis": lambda *args, **kwargs: analysis,
        "PYZ": lambda *args, **kwargs: None,
        "EXE": lambda *args, **kwargs: None,
        "COLLECT": lambda *args, **kwargs: kwargs,
    })
    assert "sqlite3.dll" in result["coll"]["upx_exclude"]
    retained = {Path(item[0]).as_posix() for item in result["a"].datas}
    assert "jieba/dict.txt" in retained
    assert "jieba/analyse/idf.txt" in retained
    assert not any(name.startswith("jieba/lac_small/") for name in retained)
    assert provenance not in retained
    assert retained_metadata <= retained
    assert "unrelated/direct_url.json" in retained
    assert retained == {
        Path(item[0]).as_posix() for item in collected
        if not Path(item[0]).as_posix().startswith("jieba/lac_small/")
        and item[0] != provenance
    }
    assert "PIL" not in result["desktop_excludes"]
