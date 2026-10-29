"""Public release staging rejects mismatched builds without any network."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def module():
    spec = importlib.util.spec_from_file_location("prepare_cnb", Path(__file__).resolve().parents[1] / "scripts/prepare_cnb_release.py")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture
def release(tmp_path):
    source = tmp_path / "build"
    source.mkdir()
    setup = source / "Lindreams.Echo-win-x64-stable-Setup.exe"
    package = source / "Lindreams.Echo-1.2.3-win-x64-stable-full.nupkg"
    setup.write_bytes(b"fictional non-executable setup")
    package.write_bytes(b"fictional package")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    build = dict(packId="Lindreams.Echo", channel="win-x64-stable", version="1.2.3",
                 sdkVersion="1.2.161", vpkVersion="1.2.161", setupSha256=digest(setup), packageSha256=digest(package))
    (source / "setup-build.json").write_text(json.dumps(build))
    asset = dict(PackageId="Lindreams.Echo", Version="1.2.3", Type="Full", FileName=package.name,
                 SHA256=digest(package), Size=package.stat().st_size)
    (source / "releases.win-x64-stable.json").write_text(json.dumps({"Assets": [asset]}))
    (source / "private-build-log.txt").write_text("fictional private build detail")
    return source, tmp_path / "public"


def test_public_staging_only_contains_approved_bytes_and_matching_metadata(release, tmp_path, monkeypatch):
    from qq_chat_analyzer.application import update_check_service
    source, output = release
    module().prepare(source, output)
    assert {path.name for path in output.iterdir()} == {
        "Echo-1.2.3-windows-x64-Setup.exe", "Echo-1.2.3-windows-x64-Setup.exe.sha256",
        "Lindreams.Echo-1.2.3-win-x64-stable-full.nupkg", "releases.win-x64-stable.json",
        "echo-update.json", "SHA256SUMS.txt"}
    for line in (output / "SHA256SUMS.txt").read_text().splitlines():
        expected, name = line.split("  ")
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected
    monkeypatch.setattr(update_check_service, "APP_VERSION", "1.2.3-rc.1")
    checker = update_check_service.UpdateCheckService(state_path=tmp_path / "state.json",
        fetch_release=lambda: json.loads((output / "echo-update.json").read_text()))
    result = checker.check()
    assert result.status == "update_available" and result.latest_version == "1.2.3"


@pytest.mark.parametrize("damage", ["setup-bytes", "package-path", "identity", "prerelease", "existing-output"])
def test_unsafe_publication_is_rejected_without_overwriting(release, damage):
    source, output = release
    if damage == "setup-bytes":
        next(source.glob("*-Setup.exe")).write_bytes(b"changed after validation")
    elif damage == "existing-output":
        output.mkdir()
        (output / "keep.txt").write_text("keep")
    elif damage == "package-path":
        path = source / "releases.win-x64-stable.json"
        feed = json.loads(path.read_text())
        feed["Assets"][0]["FileName"] = "../private.txt"
        path.write_text(json.dumps(feed))
    else:
        path = source / "setup-build.json"
        build = json.loads(path.read_text())
        build["version" if damage == "prerelease" else "packId"] = "1.2.3-rc.1" if damage == "prerelease" else "OtherApp"
        path.write_text(json.dumps(build))
    with pytest.raises(ValueError):
        module().prepare(source, output)
    if damage == "existing-output":
        assert (output / "keep.txt").read_text() == "keep"
    else:
        assert not output.exists()
