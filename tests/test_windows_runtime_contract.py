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

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "scripts" / "windows_runtime_manifest.json"
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_windows_exe.ps1"
GITIGNORE = PROJECT_ROOT / ".gitignore"


def test_echo_license_is_unmodified_mozilla_official_mpl_20() -> None:
    import hashlib

    license_file = PROJECT_ROOT / "LICENSE"
    assert license_file.is_file()
    assert hashlib.sha256(license_file.read_bytes()).hexdigest() == (
        "3f3d9e0024b1921b067d6f7f88deb4a60cbe7a78e76c64e3f1d7fc3b779b9d04"
    )


def test_echo_release_has_license_scope_and_public_source_notice() -> None:
    manifest = _load_manifest()
    assert {"LICENSE", "NOTICE.md"} <= set(manifest["releaseCopyrightFiles"])
    notice = (PROJECT_ROOT / "NOTICE.md").read_text(encoding="utf-8")
    assert "This Source Code Form is subject to the terms of the Mozilla Public" in notice
    assert "https://github.com/lingmeng-658/echo-chat-analyzer" in notice
    assert "third_party/napcat/NOTICE.md" in notice
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "[MPL 2.0 开源许可](LICENSE)" in readme
    assert "[许可声明](NOTICE.md)" in readme
    assert "[第三方许可](third_party/napcat/NOTICE.md)" in readme
    assert "MPL 2.0 本身允许商业使用" in notice
    napcat_notice = (PROJECT_ROOT / "third_party/napcat/NOTICE.md").read_text(
        encoding="utf-8"
    )
    assert "https://github.com/NapNeko/NapCatQQ/issues/2096" in napcat_notice
PYPROJECT = PROJECT_ROOT / "pyproject.toml"
DEVELOPMENT_GUIDE = PROJECT_ROOT / "DEVELOPMENT.md"

ALLOWED_ENTRY_KEYS = {"path", "source", "type", "description"}
ALLOWED_TYPES = {"file", "directory", "non-empty-directory"}
REQUIRED_TYPES = {"file", "non-empty-directory"}
ALLOWED_SOURCES = {"qq-napcat-candidate", "wechat"}

# State the desktop app itself creates beside its own executable (``logs``) and
# the report the bundled WeChat diagnostic runner writes by default. Both are
# machine-local run residue: a fresh full build cannot produce them, but a smoke
# run followed by a ``-RuntimeOnly`` build or a directory copy can.
RELEASE_TREE_PRIVATE_PATHS = {"logs", "scripts/wcdb-diagnostic.txt"}

# Native WeChat binaries the shipped product actually loads. Their identity is
# pinned by content hash because only presence was checked before.
WECHAT_PINNED_ASSETS = {
    "wechat/WCDB.dll",
    "wechat/wcdb_cli.exe",
    "wechat/wx_key.dll",
}

# The tracked build-toolchain declaration that makes the frozen artifact
# reproducible from a clean clone. Exact pins only: no ranges.
WINDOWS_BUILD_REQUIREMENTS = {"pyinstaller", "pyinstaller-hooks-contrib"}

# The documentation must show an install command that pulls in the build extra
# (tolerant of extra ordering, strict about the extra being there).
_BUILD_EXTRA_COMMAND = re.compile(r"\.\[[^\]\s]*\bbuild\b[^\]\s]*\]")

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
CANDIDATE_CONTRACT = json.loads((PROJECT_ROOT / "scripts/qq_napcat_runtime_manifest.json").read_text())
QQ_REQUIRED_FILES = {"qq-napcat-candidate/" + name for name in CANDIDATE_CONTRACT["requiredFiles"]}
QQ_REQUIRED_NATIVE_ADDONS = set()
QQ_REQUIRED_DIRECTORIES = {"qq-napcat-candidate/" + name for name in CANDIDATE_CONTRACT["requiredDirectories"]}

# ------------------------------------------------------------------ WeChat
WECHAT_REQUIRED_FILES = {
    "wechat/wcdb_cli.exe",
    "wechat/WCDB.dll",
    "wechat/wx_key.dll",
    "wechat/wx_key_helper.cjs",
    "wechat/node.exe",
    "wechat/node_modules/koffi/index.js",
    "wechat/node_modules/koffi/build/koffi/win32_x64/koffi.node",
}

WECHAT_REQUIRED_DIRECTORIES = {
    "wechat/node_modules",
}

REQUIRED_FILES = QQ_REQUIRED_FILES | QQ_REQUIRED_NATIVE_ADDONS | WECHAT_REQUIRED_FILES
REQUIRED_DIRECTORIES = QQ_REQUIRED_DIRECTORIES | WECHAT_REQUIRED_DIRECTORIES

# Machine-local state that must never become a shipped requirement.
PRIVATE_PATHS = {
    "qq-napcat-candidate/cache",
    "qq-napcat-candidate/logs",
    "qq-napcat-candidate/config/qq_path.txt",
    "qq-napcat-candidate/config/webui.json",
    "qq-napcat-candidate/config/plugins",
    "qq-napcat-candidate/loadNapCat.js",
}

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


def _build_script_text() -> str:
    return BUILD_SCRIPT.read_text(encoding="utf-8-sig")


# ------------------------------------------------------- manifest structure


def test_manifest_uses_the_minimal_agreed_schema() -> None:
    manifest = _load_manifest()

    assert set(manifest) == {
        "requirements",
        "privatePaths",
        "packageDirectories",
        "qqPins",
        "forbiddenPaths",
        "releaseTreePrivatePaths",
        "wechatPinnedAssets",
        "portableExcludedFiles",
        "releaseCopyrightFiles",
    }

    for key in ("requirements", "privatePaths", "packageDirectories"):
        for entry in _entries(manifest, key):
            assert set(entry) <= ALLOWED_ENTRY_KEYS, entry
            assert "path" in entry and "source" in entry and "type" in entry, entry
            assert entry["source"] in ALLOWED_SOURCES, entry
            assert entry["type"] in ALLOWED_TYPES, entry


def test_manifest_uses_presence_types_only_for_requirements() -> None:
    manifest = _load_manifest()

    for entry in _entries(manifest, "requirements"):
        assert entry["type"] in REQUIRED_TYPES, entry
    for entry in _entries(manifest, "privatePaths"):
        assert entry["type"] in {"file", "directory"}, entry


def test_manifest_paths_are_relative_and_normalised() -> None:
    manifest = _load_manifest()

    for key in ("requirements", "privatePaths", "packageDirectories"):
        for entry in _entries(manifest, key):
            path = str(entry["path"])
            assert not path.startswith(("/", "\\")), path
            assert ":" not in path, path
            assert "\\" not in path, path
            assert ".." not in path.split("/"), path


def test_manifest_entries_belong_to_their_declared_source() -> None:
    manifest = _load_manifest()

    for key in ("requirements", "privatePaths", "packageDirectories"):
        for entry in _entries(manifest, key):
            assert str(entry["path"]).startswith(f"{entry['source']}/"), entry


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


@pytest.mark.parametrize("path", sorted(REQUIRED_FILES))
def test_manifest_requires_every_product_hard_dependency(path: str) -> None:
    manifest = _load_manifest()
    entries = {
        str(entry["path"]): entry for entry in _entries(manifest, "requirements")
    }

    assert path in entries, f"runtime contract is missing required asset: {path}"
    assert entries[path]["type"] == "file", entries[path]


@pytest.mark.parametrize("path", sorted(REQUIRED_DIRECTORIES))
def test_manifest_requires_payload_directories_to_be_non_empty(path: str) -> None:
    manifest = _load_manifest()
    entries = {
        str(entry["path"]): entry for entry in _entries(manifest, "requirements")
    }

    assert path in entries, f"runtime contract is missing required directory: {path}"
    assert entries[path]["type"] == "non-empty-directory", entries[path]


def test_manifest_describes_qq_and_wechat_runtime_separately() -> None:
    manifest = _load_manifest()
    sources = {entry["source"] for entry in _entries(manifest, "requirements")}

    assert sources == {"qq-napcat-candidate", "wechat"}


# --------------------------------------------------------- privacy contract


def test_napcat_license_preserves_original_v41818_bytes() -> None:
    import hashlib

    license_path = PROJECT_ROOT / "third_party/napcat/LICENSE"
    assert license_path.is_file()
    assert hashlib.sha256(license_path.read_bytes()).hexdigest() == (
        "2bbc0dba0c62fcde4adfe38ebadad0b7d4e23b06b88d9551904bbe07769dc46f"
    )


@pytest.mark.parametrize("path", sorted(PRIVATE_PATHS))
def test_manifest_declares_machine_local_state_as_private(path: str) -> None:
    manifest = _load_manifest()

    assert path in _paths(manifest, "privatePaths"), (
        f"machine-local state is not declared private: {path}"
    )


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


def test_private_contract_covers_cache_logs_and_local_paths() -> None:
    manifest = _load_manifest()
    private = _paths(manifest, "privatePaths")

    for directory in ("qq-napcat-candidate/cache", "qq-napcat-candidate/logs"):
        assert directory in private
    assert "qq-napcat-candidate/config/qq_path.txt" in private
    assert "qq-napcat-candidate/config/webui.json" in private


# ------------------------------------------- build and tests share one source


def test_gitignore_explicitly_tracks_the_manifest() -> None:
    """``*.json`` is ignored repo-wide, so the contract needs a negation."""
    lines = [
        line.strip()
        for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert "!scripts/windows_runtime_manifest.json" in lines, (
        "scripts/windows_runtime_manifest.json is matched by the global '*.json' "
        "ignore rule and would never be tracked"
    )


def test_build_script_reads_the_same_manifest() -> None:
    script = _build_script_text()

    assert "windows_runtime_manifest.json" in script, (
        "build script does not consume the shared runtime contract manifest"
    )


def test_build_script_keeps_no_parallel_required_path_list() -> None:
    """A second hand-maintained list is exactly what we are removing."""
    script = _build_script_text()

    assert "$RequiredRuntimePaths" not in script, (
        "build script still declares its own required-path array"
    )
    assert "RequiredRuntimePaths" not in script


@pytest.mark.parametrize(
    "filename",
    [
        "napcat.mjs",
        "NapCatWinBootMain.exe",
        "NapCatWinBootHook.dll",
        "launcher-user.bat",
        "conoutSocketWorker.mjs",
        "@primno+dpapi.node",
        "wx_key.dll",
        "wx_key_helper.cjs",
        "wcdb_cli.exe",
        "WCDB.dll",
        "koffi.node",
    ],
)
def test_build_script_does_not_hardcode_runtime_asset_paths(
    filename: str,
) -> None:
    script = _build_script_text()

    assert filename not in script, (
        f"{filename} is restated in the build script instead of being read "
        "from the runtime contract manifest"
    )


def test_build_script_loads_the_contract_before_packaging() -> None:
    script = _build_script_text()

    manifest_index = script.index("windows_runtime_manifest.json")
    pyinstaller_index = script.index("--noconfirm")

    assert manifest_index < pyinstaller_index, (
        "the runtime contract must be validated before packaging starts"
    )


def test_manifest_limits_recursive_copy_to_program_payloads() -> None:
    assert _paths(_load_manifest(), "packageDirectories") == {
        "qq-napcat-candidate/node_modules", "qq-napcat-candidate/static", "qq-napcat-candidate/native", "qq-napcat-candidate/worker", "wechat/node_modules/koffi",
    }


# ------------------------------------------------- release tree run residue


def _release_tree_private_paths(manifest: dict) -> list[str]:
    value = manifest.get("releaseTreePrivatePaths")
    assert isinstance(value, list), "manifest field 'releaseTreePrivatePaths' must be a list"
    return [str(entry) for entry in value]


def test_manifest_declares_the_release_tree_residue_paths() -> None:
    manifest = _load_manifest()

    assert set(_release_tree_private_paths(manifest)) == RELEASE_TREE_PRIVATE_PATHS


def test_release_tree_private_paths_are_relative_and_normalised() -> None:
    for path in _release_tree_private_paths(_load_manifest()):
        assert not path.startswith(("/", "\\")), path
        assert ":" not in path, path
        assert "\\" not in path, path
        assert ".." not in path.split("/"), path


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


def test_build_script_asserts_release_tree_residue_after_packaging() -> None:
    script = _build_script_text()

    assert "releaseTreePrivatePaths" in script, (
        "build script does not consume the shared release-tree residue contract"
    )
    # The assertion has to run after the last packaging step that writes into
    # the release tree root, otherwise a stale ``scripts/`` copy slips through.
    runner_index = script.index("run_wechat_wcdb_diagnostic.ps1")
    assertion_index = script.index("Assert-ReleaseTreeStateAbsent -Root $PortableDirectory")
    assert runner_index < assertion_index, (
        "release-tree residue must be asserted after the release tree is complete"
    )


# ------------------------------------------------ WeChat native asset pins


def _wechat_pins(manifest: dict) -> dict:
    value = manifest.get("wechatPinnedAssets")
    assert isinstance(value, dict), "manifest field 'wechatPinnedAssets' must be an object"
    return {str(name): str(digest) for name, digest in value.items()}


def test_manifest_pins_the_wechat_native_assets_that_ship() -> None:
    manifest = _load_manifest()

    assert set(_wechat_pins(manifest)) == WECHAT_PINNED_ASSETS


@pytest.mark.parametrize("path", sorted(WECHAT_PINNED_ASSETS))
def test_wechat_pinned_assets_use_a_lowercase_sha256(path: str) -> None:
    digest = _wechat_pins(_load_manifest())[path]

    assert re.fullmatch(r"[0-9a-f]{64}", digest), digest


@pytest.mark.parametrize("path", sorted(WECHAT_PINNED_ASSETS))
def test_wechat_pinned_assets_are_declared_shipped_requirements(path: str) -> None:
    """A pin that is not a requirement, or vice versa, is a contract bug."""
    manifest = _load_manifest()
    entries = {
        str(entry["path"]): entry for entry in _entries(manifest, "requirements")
    }

    assert path in entries, f"pinned WeChat asset is not a requirement: {path}"
    assert entries[path]["type"] == "file", entries[path]
    assert entries[path]["source"] == "wechat", entries[path]


def test_wechat_pinned_assets_are_relative_and_normalised() -> None:
    for path in _wechat_pins(_load_manifest()):
        assert path.startswith("wechat/"), path
        assert "\\" not in path and ":" not in path, path
        assert ".." not in path.split("/"), path


def test_build_script_verifies_the_wechat_native_asset_pins() -> None:
    script = _build_script_text()

    assert "wechatPinnedAssets" in script, (
        "build script does not consume the WeChat asset pins"
    )
    assert "WeChat artifact pin mismatch" in script


# ------------------------------------------------ tracked build toolchain


def test_pyproject_declares_the_pinned_windows_build_toolchain() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    extra = project["project"]["optional-dependencies"]["build"]

    pins: dict[str, str] = {}
    for entry in extra:
        name, separator, version = str(entry).partition("==")
        assert separator == "==", f"build dependency must be exactly pinned: {entry}"
        assert re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version), entry
        pins[name] = version

    assert set(pins) == WINDOWS_BUILD_REQUIREMENTS, (
        "the tracked build toolchain must name exactly the tools the frozen "
        "artifact is built with"
    )


def test_development_guide_documents_the_build_toolchain() -> None:
    text = DEVELOPMENT_GUIDE.read_text(encoding="utf-8")

    assert "pyinstaller" in text.lower(), (
        "DEVELOPMENT.md must document the Windows build toolchain"
    )
    assert _BUILD_EXTRA_COMMAND.search(text), (
        "DEVELOPMENT.md must show an install command that includes the 'build' extra"
    )


def test_desktop_velopack_pin_and_upstream_license_ship_together() -> None:
    import hashlib

    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert "velopack==1.2.161" in project["project"]["optional-dependencies"]["gui"]
    relative = "third_party/velopack/LICENSE"
    assert relative in _load_manifest()["releaseCopyrightFiles"]
    assert hashlib.sha256((PROJECT_ROOT / relative).read_bytes()).hexdigest() == (
        "91845db83551c877ebbb1118e0fb92e4e527290d23b995c55dcd438b3293943f"
    )
