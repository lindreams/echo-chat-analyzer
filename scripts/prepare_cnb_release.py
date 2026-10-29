"""Prepare an allowlisted public release directory; never upload or install.

CNB's immutable version release and persistent ``updates`` release consume the
same files. Only the full nupkg and two JSON pointers belong in ``updates``;
retain older nupkgs so an in-flight download survives a new publication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

from qq_chat_analyzer.application.update_channel import (
    PRODUCTION_PACKAGE_ID, PRODUCTION_CHANNEL, PRODUCTION_REPOSITORY,
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(source: Path, output: Path) -> Path:
    source = source.resolve(strict=True)
    if output.exists() or output.is_symlink():
        raise ValueError("Publication directory must be new")
    build = json.loads((source / "setup-build.json").read_text(encoding="utf-8"))
    version = build["version"]
    if (not isinstance(version, str) or re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version) is None
            or build["packId"] != PRODUCTION_PACKAGE_ID or build["channel"] != PRODUCTION_CHANNEL
            or build["sdkVersion"] != "1.2.161" or build["vpkVersion"] != "1.2.161"):
        raise ValueError("Only a validated stable production package may be published")
    feed_name = f"releases.{PRODUCTION_CHANNEL}.json"
    feed = json.loads((source / feed_name).read_text(encoding="utf-8"))
    if not isinstance(feed, dict) or len(feed.get("Assets", [])) != 1:
        raise ValueError("Expected exactly one full package")
    asset = feed["Assets"][0]
    package_name = f"{PRODUCTION_PACKAGE_ID}-{version}-{PRODUCTION_CHANNEL}-full.nupkg"
    if (asset.get("FileName") != package_name or asset.get("PackageId") != PRODUCTION_PACKAGE_ID
            or asset.get("Version") != version or asset.get("Type") != "Full"):
        raise ValueError("Unexpected package identity or path")
    setups = list(source.glob("*-Setup.exe"))
    if len(setups) != 1:
        raise ValueError("Expected exactly one Setup")
    package, setup = source / package_name, setups[0]
    if any(path.is_symlink() or not path.is_file() for path in (package, setup, source / feed_name)):
        raise ValueError("Release files must be regular files")
    package_hash, setup_hash = digest(package), digest(setup)
    if (package.stat().st_size != asset.get("Size")
            or package_hash != str(asset.get("SHA256")).lower()
            or package_hash != str(build["packageSha256"]).lower()
            or setup_hash != str(build["setupSha256"]).lower()):
        raise ValueError("Release integrity differs from the validated build")
    output.mkdir(parents=True, exist_ok=False)
    setup_name = f"Echo-{version}-windows-x64-Setup.exe"
    feed_hash = digest(source / feed_name)
    for original, name, expected in ((package, package_name, package_hash), (setup, setup_name, setup_hash), (source / feed_name, feed_name, feed_hash)):
        shutil.copyfile(original, output / name)
        if digest(original) != expected or digest(output / name) != expected:
            raise ValueError("Source changed while preparing publication")
    (output / (setup_name + ".sha256")).write_text(f"{setup_hash}  {setup_name}\n", encoding="utf-8")
    metadata = dict(package_id=PRODUCTION_PACKAGE_ID, channel=PRODUCTION_CHANNEL,
                    tag_name="v" + version, draft=False, prerelease=False,
                    html_url=f"{PRODUCTION_REPOSITORY}/-/releases/tag/v{version}")
    (output / "echo-update.json").write_text(json.dumps(metadata, ensure_ascii=False) + "\n", encoding="utf-8")
    checksums = [f"{digest(path)}  {path.name}\n" for path in sorted(output.iterdir())]
    (output / "SHA256SUMS.txt").write_text("".join(checksums), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(prepare(args.source, args.output))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Release preparation refused: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
