"""Setup packaging refuses unsafe inputs before invoking vpk."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/package_windows_setup.py"


@pytest.fixture
def packager(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("setup_packager", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def release(tmp_path):
    source = tmp_path / "fictional-source"
    files = {
        "Echo.exe": b"fictional program",
        "_internal/python.dll": b"fictional interpreter",
        "scripts/run_wechat_wcdb_diagnostic.ps1": b"fictional diagnostic",
        "LICENSE": b"fictional license",
        "runtime/qq-napcat-candidate/napcat.mjs": b"fictional patched runtime",
        "runtime/qq-napcat-candidate/config/plugins.json": b"fictional seed",
        "runtime/wechat/WCDB.dll": b"fictional native library",
    }
    for name, version in [("qq-chat-analyzer", "0.1.0"), ("velopack", "1.2.161")]:
        files[f"_internal/{name.replace('-', '_')}-{version}.dist-info/METADATA"] = (
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        ).encode()
    for name, body in files.items():
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    digest = lambda name: hashlib.sha256(files[name]).hexdigest()
    pins = {
        "upstream": {"version": "4.18.34", "project": "NapNeko/NapCatQQ"},
        "requiredFiles": {"napcat.mjs": "0" * 64},
        "napcatPatch": {"path": "napcat.mjs", "patchedSha256": digest("runtime/qq-napcat-candidate/napcat.mjs")},
        "pluginConfigSha256": digest("runtime/qq-napcat-candidate/config/plugins.json"),
        "templates": [],
    }
    (metadata / "qq-pins.json").write_text(json.dumps(pins))
    contract = {
        "qqPins": "qq-pins.json",
        "wechatPinnedAssets": {"wechat/WCDB.dll": digest("runtime/wechat/WCDB.dll")},
        "requirements": [dict(path=name.removeprefix("runtime/"), source=name.split("/")[1], type="file")
                         for name in files if name.startswith("runtime/")],
        "packageDirectories": [],
        "privatePaths": [{"path": "qq-napcat-candidate/output"}],
        "releaseTreePrivatePaths": ["logs"],
        "portableExcludedFiles": ["qq-napcat-candidate/private.js"],
        "forbiddenPaths": ["qq"],
        "releaseCopyrightFiles": ["LICENSE"],
    }
    manifest = metadata / "manifest.json"
    manifest.write_text(json.dumps(contract))
    project = metadata / "pyproject.toml"
    project.write_text('[project]\nversion = "0.1.0"\n')
    return source, tmp_path / "setup-artifacts", project, manifest


def invoke(packager, release):
    source, output, project, manifest = release
    return packager.package_setup(source, output, vpk_path=Path("fictional-vpk.exe"),
                                  pack_id="EchoA1.Fictional", channel="win-x64-a1",
                                  project_file=project, manifest_file=manifest)


@pytest.mark.parametrize("damage", ["private", "pin", "license", "sdk-version", "app-version"])
def test_invalid_tree_never_invokes_vpk(packager, release, monkeypatch, damage):
    source, output, _, _ = release
    if damage == "private":
        (source / "logs").mkdir()
    elif damage == "pin":
        (source / "runtime/wechat/WCDB.dll").write_bytes(b"tampered fictional asset")
    elif damage == "license":
        (source / "LICENSE").unlink()
    else:
        name = "velopack" if damage == "sdk-version" else "qq_chat_analyzer"
        metadata = next((source / "_internal").glob(name + "*.dist-info/METADATA"))
        metadata.write_text(f"Name: {name.replace('_', '-')}\nVersion: 9.9.9\n")
    monkeypatch.setattr(packager.subprocess, "run", lambda *a, **k: pytest.fail("vpk reached"))
    with pytest.raises(packager.PackageError):
        invoke(packager, release)
    assert not output.exists()


def test_wrong_vpk_version_is_rejected(packager, release, monkeypatch):
    monkeypatch.setattr(packager.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout="Velopack CLI 9.9.9", stderr=""))
    with pytest.raises(packager.PackageError, match="1.2.161"):
        invoke(packager, release)
    assert not release[1].exists()


def emit_fictional_release(artifacts: Path, source: Path) -> None:
    """Write the feed and package files a successful vpk run would produce."""
    artifacts.mkdir()
    package = artifacts / "EchoA1.Fictional-0.1.0-win-x64-a1-full.nupkg"
    with zipfile.ZipFile(package, "w") as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.writestr("lib/app/" + path.relative_to(source).as_posix(), path.read_bytes())
    (artifacts / "EchoA1.Fictional-win-x64-a1-Setup.exe").write_bytes(b"fictional setup")
    (artifacts / "releases.win-x64-a1.json").write_text(json.dumps({"Assets": [{
        "PackageId": "EchoA1.Fictional", "Version": "0.1.0", "Type": "Full",
        "FileName": package.name, "SHA256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "Size": package.stat().st_size,
    }]}))


def fictional_vpk(source: Path, inspect):
    """Stand in for vpk: hand the pack command to ``inspect``, then emit outputs."""
    def runner(command, **kwargs):
        if command[-1] == "-h":
            return SimpleNamespace(returncode=0, stdout="Velopack CLI 1.2.161,", stderr="")
        inspect(command)
        emit_fictional_release(Path(command[command.index("--outputDir") + 1]), source)
        return SimpleNamespace(returncode=0, stdout="fictional success", stderr="")
    return runner


def test_vpk_receives_staging_and_project_version(packager, release, monkeypatch):
    source, output, _, _ = release
    original = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*") if p.is_file()}

    def inspect(command):
        assert "--skip-updates" in command
        stage = Path(command[command.index("--packDir") + 1])
        assert stage != source and stage.is_dir()
        assert command[command.index("--packVersion") + 1] == "0.1.0"
        assert command[command.index("--packId") + 1] == "EchoA1.Fictional"

    monkeypatch.setattr(packager.subprocess, "run", fictional_vpk(source, inspect))
    setup = invoke(packager, release)
    assert setup.is_file() and setup.parent == output
    assert original == {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert (output / "setup-build.json").is_file()


def test_pack_failure_leaves_no_output(packager, release, monkeypatch):
    def runner(command, **kwargs):
        return SimpleNamespace(returncode=0 if command[-1] == "-h" else 1,
                               stdout="Velopack CLI 1.2.161,", stderr="fictional failure")
    monkeypatch.setattr(packager.subprocess, "run", runner)
    with pytest.raises(packager.PackageError, match="vpk"):
        invoke(packager, release)
    assert not release[1].exists()


def test_existing_output_is_never_overwritten(packager, release):
    release[1].mkdir()
    sentinel = release[1] / "keep.txt"
    sentinel.write_text("fictional existing work")
    with pytest.raises(packager.PackageError):
        invoke(packager, release)
    assert sentinel.read_text() == "fictional existing work"
