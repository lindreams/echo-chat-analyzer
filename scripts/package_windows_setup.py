"""Package a validated onedir build with the pinned, explicitly supplied vpk.

No builds, downloads, signing, installs or updates are performed by this wrapper.
Existing output directories are never overwritten.

The Setup creates a desktop shortcut and a Start Menu shortcut, and both the
Setup and its shortcuts reuse the existing Echo application icon. Install
branding and progress come from Velopack's native progress dialog, which is
driven by ``--packTitle``; no custom splash image is shipped.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import tomllib
import zipfile

import package_windows_portable as portable
from qq_chat_analyzer.application.update_channel import PRODUCTION_PACKAGE_ID, PRODUCTION_CHANNEL
from qq_chat_analyzer.version import normalize_release_version

PackageError = portable.PackageError
VELOPACK_VERSION = "1.2.161"
ROOT = Path(__file__).resolve().parents[1]
ECHO_SETUP_ICON = ROOT / "branding/Echo.ico"


def _validate_pins(entries: dict, contract: dict, manifest: Path) -> None:
    pins = json.loads((manifest.parent / portable._manifest_path(contract["qqPins"])).read_text(encoding="utf-8"))
    if pins["upstream"].get("version") != "4.18.34" or pins["upstream"].get("project") != "NapNeko/NapCatQQ":
        raise PackageError("Unsupported NapCat source")
    hashes = dict(pins["requiredFiles"])
    hashes[pins["napcatPatch"]["path"]] = pins["napcatPatch"]["patchedSha256"]
    hashes["config/plugins.json"] = pins["pluginConfigSha256"]
    hashes.update({item["target"]: item["sha256"] for item in pins["templates"]})
    runtime_hashes = {"qq-napcat-candidate/" + name: digest for name, digest in hashes.items()}
    runtime_hashes.update(contract["wechatPinnedAssets"])
    for name, expected in runtime_hashes.items():
        portable._manifest_path(name)
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise PackageError("Invalid runtime pin")
        if name in contract["portableExcludedFiles"]:
            continue
        entry = entries.get("runtime/" + name)
        if entry is None or portable._file_digest(entry[0]) != expected:
            raise PackageError("Runtime pin mismatch: " + name)


def _run(command: list[str], *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    if result.returncode:
        raise PackageError(f"vpk failed ({result.returncode}): {result.stdout}\n{result.stderr}")
    return result.stdout + result.stderr


def package_setup(source_dir: str | Path, output_dir: str | Path, *, vpk_path: Path,
                  pack_id: str, channel: str, project_file: Path = ROOT / "pyproject.toml",
                  manifest_file: Path = portable.MANIFEST_FILE, dotnet_path: Path | None = None,
                  timings: dict[str, float] | None = None) -> Path:
    started = time.perf_counter()
    root = Path(os.path.abspath(source_dir))
    output = Path(os.path.abspath(output_dir))
    portable._no_links(output)
    if output.exists() or output == root or root in output.parents:
        raise PackageError("Output must be a new directory outside the source tree")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{2,63}", pack_id) or pack_id.casefold() == "localchatanalyzer":
        raise PackageError("Invalid or data-directory-conflicting packId")
    # vpk 1.2.161's legacy RELEASES writer selects the first version-shaped
    # numeric pair in a filename, including a pair inside the package ID.
    # Ordinary dotted IDs (including Lindreams.Echo) remain supported.
    if re.search(r"[.-](0|[1-9]\d*)\.(0|[1-9]\d*)($|[^\d])", pack_id):
        raise PackageError("packId contains a version-like prefix unsupported by vpk 1.2.161")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", channel):
        raise PackageError("Invalid channel")
    if not ECHO_SETUP_ICON.is_file():
        raise PackageError("Missing Echo application icon for the Setup: " + str(ECHO_SETUP_ICON))
    release_version = tomllib.loads(Path(project_file).read_text(encoding="utf-8"))["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", release_version):
        raise PackageError("Invalid project release version")
    contract = json.loads(Path(manifest_file).read_text(encoding="utf-8"))
    entries = portable._inventory(root)
    portable._validate_release(entries, contract)
    _validate_pins(entries, contract, Path(manifest_file))
    distributions = list(importlib.metadata.distributions(path=[str(root / "_internal")]))
    for name, expected in [("qq-chat-analyzer", release_version), ("velopack", VELOPACK_VERSION)]:
        versions = [d.version for d in distributions if d.metadata["Name"].replace("_", "-").lower() == name]
        if name == "qq-chat-analyzer":
            versions = [normalize_release_version(value) for value in versions]
        if versions != [expected]:
            raise PackageError(f"Frozen {name} metadata must be exactly {expected}")
    vpk_command = [str(vpk_path)] if dotnet_path is None else [str(dotnet_path), str(vpk_path)]
    if not re.search(r"Velopack CLI 1\.2\.161(?:,|\s|$)", _run(vpk_command + ["-h"])):
        raise PackageError("vpk must be version " + VELOPACK_VERSION)
    hashes = {name: portable._file_digest(path) for name, (path, _) in entries.items() if not name.endswith("/")}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="echo-setup-", dir=output.parent) as temporary:
        stage = Path(temporary) / "app"
        artifacts = Path(temporary) / "artifacts"
        stage.mkdir()
        for name, (path, _) in entries.items():
            target = stage / name
            if name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                if portable._file_digest(target) != hashes[name]:
                    raise PackageError("Source changed while staging")
        pack_started = time.perf_counter()
        _run(vpk_command + ["pack", "--packId", pack_id, "--packVersion", release_version,
                           "--packDir", str(stage), "--mainExe", "Echo.exe", "--packTitle", "Echo",
                           "--channel", channel, "--runtime", "win-x64", "--delta", "None",
                           "--icon", str(ECHO_SETUP_ICON),
                           "--shortcuts", "Desktop,StartMenuRoot",
                           "--outputDir", str(artifacts), "--skip-updates", "--legacyConsole"])
        pack_seconds = time.perf_counter() - pack_started
        setups = list(artifacts.glob("*-Setup.exe"))
        assets = json.loads((artifacts / f"releases.{channel}.json").read_text(encoding="utf-8"))["Assets"]
        if len(setups) != 1 or len(assets) != 1:
            raise PackageError("Expected one Setup and one full package")
        asset = assets[0]
        package_name = portable._manifest_path(asset["FileName"])
        if "/" in package_name or asset["PackageId"] != pack_id or asset["Version"] != release_version or asset["Type"] != "Full":
            raise PackageError("Unexpected feed identity")
        package = artifacts / package_name
        if portable._file_digest(package).lower() != asset["SHA256"].lower() or package.stat().st_size != asset["Size"]:
            raise PackageError("Package integrity differs from feed")
        with zipfile.ZipFile(package) as zipped:
            names = zipped.namelist()
            if len(names) != len(set(names)):
                raise PackageError("Duplicate package members")
            for name, digest in hashes.items():
                with zipped.open("lib/app/" + name) as stream:
                    if portable._digest(stream) != digest:
                        raise PackageError("Package changed application content: " + name)
        if portable._inventory(root) != entries or any(portable._file_digest(entries[n][0]) != h for n, h in hashes.items()):
            raise PackageError("Source changed during packaging")
        (artifacts / "setup-build.json").write_text(json.dumps({
            "packId": pack_id, "channel": channel, "version": release_version,
            "sdkVersion": VELOPACK_VERSION, "vpkVersion": VELOPACK_VERSION,
            "setupSha256": portable._file_digest(setups[0]), "packageSha256": asset["SHA256"],
        }, indent=2) + "\n", encoding="utf-8")
        setup_name = setups[0].name
        artifacts.rename(output)
    if timings is not None:
        timings["vpk_pack"] = round(pack_seconds, 3)
        timings["asset_validation_and_staging"] = round(time.perf_counter() - started - pack_seconds, 3)
    return output / setup_name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "dist/Echo")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vpk", type=Path, required=True)
    parser.add_argument("--dotnet", type=Path, help="explicit dotnet host for a vpk.dll entry (avoids SDK-selected shims)")
    parser.add_argument("--pack-id", default=PRODUCTION_PACKAGE_ID)
    parser.add_argument("--channel", default=PRODUCTION_CHANNEL)
    args = parser.parse_args()
    try:
        print(package_setup(args.source, args.output, vpk_path=args.vpk, pack_id=args.pack_id, channel=args.channel,
                            dotnet_path=args.dotnet))
        return 0
    except (PackageError, OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print(f"Setup packaging refused: {error}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
