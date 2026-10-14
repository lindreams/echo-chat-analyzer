"""Portable ZIP contracts; every input byte is fictional."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/package_windows_portable.py"
MANIFEST = ROOT / "scripts/windows_runtime_manifest.json"


@pytest.fixture
def packager():
    if not SCRIPT.is_file():
        pytest.skip("Portable ZIP implementation is missing")
    spec = importlib.util.spec_from_file_location("portable_packager", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_packaging_command_is_available():
    assert SCRIPT.is_file(), "Portable ZIP implementation is missing"


@pytest.fixture
def release(tmp_path):
    source = tmp_path / "中文 folder" / "Echo"
    source.mkdir(parents=True)
    contract = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for entry in contract["requirements"]:
        if entry["type"] == "file" and entry["path"] in contract["portableExcludedFiles"]:
            continue
        path = source / "runtime" / entry["path"]
        if entry["type"] == "file":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fictional runtime asset")
        else:
            path.mkdir(parents=True, exist_ok=True)
    for entry in contract["packageDirectories"]:
        path = source / "runtime" / entry["path"]
        path.mkdir(parents=True, exist_ok=True)
        (path / "fixture.bin").write_bytes(b"fictional program asset")
    for relative in contract["releaseCopyrightFiles"]:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fictional copyright material")
    for relative, content in {
        "Echo.exe": b"fictional EXE, never executed",
        "_internal/python313.dll": b"fictional Python",
        "_internal/中文 resource.bin": bytes(range(256)) * 512,
        "scripts/run_wechat_wcdb_diagnostic.ps1": b"# fictional diagnostic",
        "runtime/wechat/msvcp140.dll": b"fictional build-provided DLL",
    }.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    return source, tmp_path / "artifacts", project


def run_package(packager, release, **kwargs):
    source, output, project = release
    return packager.package_portable(
        source, output, project_file=project, manifest_file=MANIFEST, **kwargs
    )


def test_zip_has_echo_root_exact_bytes_and_sha256(packager, release):
    source, output, _ = release
    before = {p.relative_to(source).as_posix(): p.read_bytes()
              for p in source.rglob("*") if p.is_file()}
    archive, checksum = run_package(packager, release)
    assert archive == output / "Echo-0.1.0-windows-x64.zip"
    assert checksum.name == "Echo-0.1.0-windows-x64.zip.sha256"
    with zipfile.ZipFile(archive) as zipped:
        assert set(zipped.namelist()) == {"Echo/"} | {
            f"Echo/{name}" for name in before
        } | {f"Echo/{p.relative_to(source).as_posix()}/"
             for p in source.rglob("*") if p.is_dir()}
        for name, content in before.items():
            assert zipped.read(f"Echo/{name}") == content
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert checksum.read_text(encoding="ascii") == f"{digest}  {archive.name}\n"
    assert before == {p.relative_to(source).as_posix(): p.read_bytes()
                      for p in source.rglob("*") if p.is_file()}


@pytest.mark.parametrize("missing", [
    "Echo.exe", "_internal", "runtime", "runtime/wechat/WCDB.dll",
    "scripts/run_wechat_wcdb_diagnostic.ps1",
])
def test_missing_components_leave_no_artifacts(packager, release, missing):
    source, output, _ = release
    path = source / missing
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    with pytest.raises(packager.PackageError):
        run_package(packager, release)
    assert not output.exists() or not list(output.iterdir())


def test_empty_internal_is_rejected(packager, release):
    source, _, _ = release
    for path in (source / "_internal").iterdir():
        path.unlink()
    with pytest.raises(packager.PackageError):
        run_package(packager, release)


CONTRACT = json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_complete_copyright_materials_are_packaged(packager, release):
    source, _, _ = release
    archive, _ = run_package(packager, release)
    with zipfile.ZipFile(archive) as zipped:
        for relative in CONTRACT["releaseCopyrightFiles"]:
            assert zipped.read("Echo/" + relative) == (source / relative).read_bytes()


@pytest.mark.parametrize("relative", CONTRACT["releaseCopyrightFiles"])
@pytest.mark.parametrize("damage", ["missing", "directory"])
def test_required_copyright_material_must_be_a_file(packager, release, relative, damage):
    source, output, _ = release
    path = source / relative
    path.unlink()
    if damage == "directory":
        path.mkdir()
    with pytest.raises(packager.PackageError, match="Missing or empty release component"):
        run_package(packager, release)
    assert not output.exists()


@pytest.mark.parametrize("relative", [
    "third_party/napcat/undeclared-license.txt", "third_party/other-license.txt",
])
def test_undeclared_copyright_file_is_rejected(packager, release, relative):
    source, output, _ = release
    extra = source / relative
    extra.write_bytes(b"fictional undeclared copyright")
    with pytest.raises(packager.PackageError, match="Unexpected release member"):
        run_package(packager, release)
    assert extra.read_bytes() == b"fictional undeclared copyright"
    assert not output.exists()


def test_portable_exclusions_can_be_absent_from_zip(packager, release):
    source, _, _ = release
    for relative in CONTRACT["portableExcludedFiles"]:
        assert not (source / "runtime" / relative).exists()
    archive, _ = run_package(packager, release)
    with zipfile.ZipFile(archive) as zipped:
        assert not {
            "Echo/runtime/" + relative for relative in CONTRACT["portableExcludedFiles"]
        }.intersection(zipped.namelist())


@pytest.mark.parametrize("relative", CONTRACT["portableExcludedFiles"])
def test_reintroduced_portable_exclusion_is_rejected(packager, release, relative):
    source, output, _ = release
    excluded = source / "runtime" / relative
    excluded.parent.mkdir(parents=True, exist_ok=True)
    excluded.write_bytes(b"fictional excluded asset")
    with pytest.raises(packager.PackageError, match="excluded"):
        run_package(packager, release)
    assert excluded.read_bytes() == b"fictional excluded asset"
    assert not output.exists()


PRIVATE_PATHS = [f"runtime/{entry['path']}" for entry in CONTRACT["privatePaths"]]
PRIVATE_PATHS += CONTRACT["releaseTreePrivatePaths"]
PRIVATE_PATHS += [f"runtime/{path}" for path in CONTRACT["forbiddenPaths"]]
PRIVATE_PATHS += [
    "runtime/output/qq_direct_db_phase35/generations/fake/snapshot.db",
    "runtime/qq-napcat-candidate/config/account_fake.json",
    "runtime/wechat/node_modules/koffi/cache/fake.bin",
    "runtime/wechat/node_modules/koffi/data/fake.bin",
    "_internal/private.jsonl", "reports/fictional.html", "config/wechat.json",
]


@pytest.mark.parametrize("relative", PRIVATE_PATHS)
def test_private_and_unknown_state_is_rejected_without_cleanup(packager, release, relative):
    source, output, _ = release
    residue = source / relative
    residue.parent.mkdir(parents=True, exist_ok=True)
    residue.write_bytes(b"fictional private state")
    with pytest.raises(packager.PackageError):
        run_package(packager, release)
    assert residue.read_bytes() == b"fictional private state"
    assert not output.exists() or not list(output.iterdir())


@pytest.mark.parametrize("directory", [False, True])
def test_symlinks_are_rejected(packager, release, tmp_path, directory):
    source, _, _ = release
    outside = tmp_path / "outside"
    outside.mkdir() if directory else outside.write_bytes(b"fictional outside")
    link = source / "_internal/link"
    try:
        link.symlink_to(outside, target_is_directory=directory)
    except OSError:
        pytest.skip("Creating symlinks requires Windows privilege")
    with pytest.raises(packager.PackageError):
        run_package(packager, release)
    assert outside.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction contract")
def test_windows_junction_is_rejected(packager, release, tmp_path):
    source, _, _ = release
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "fixture.bin").write_bytes(b"fictional outside")
    junction = source / "_internal/junction"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True, check=False,
    )
    assert result.returncode == 0
    try:
        with pytest.raises(packager.PackageError):
            run_package(packager, release)
        assert (outside / "fixture.bin").read_bytes() == b"fictional outside"
    finally:
        junction.rmdir()


def test_version_is_read_from_project(packager, release):
    _, _, project = release
    project.write_text('[project]\nversion = "2.3.4"\n', encoding="utf-8")
    archive, _ = run_package(packager, release)
    assert archive.name == "Echo-2.3.4-windows-x64.zip"


def test_existing_outputs_are_preserved(packager, release):
    archive, checksum = run_package(packager, release)
    before = archive.read_bytes(), checksum.read_bytes()
    with pytest.raises(packager.PackageError):
        run_package(packager, release)
    assert (archive.read_bytes(), checksum.read_bytes()) == before


def test_output_inside_source_is_rejected(packager, release):
    source, _, project = release
    with pytest.raises(packager.PackageError):
        packager.package_portable(source, source / "archives", project_file=project)
    assert not (source / "archives").exists()


@pytest.mark.parametrize("damage", ["content", "extra", "missing", "source_change"])
def test_generated_zip_is_verified_and_failure_leaves_no_artifacts(
    packager, release, monkeypatch, damage
):
    source, output, _ = release
    real_write = zipfile.ZipFile.write

    def damaged_write(zipped, filename, arcname=None, *args, **kwargs):
        if arcname == "Echo/Echo.exe":
            if damage == "content":
                zipped.writestr(arcname, b"wrong fictional bytes")
                return
            if damage == "missing":
                return
            if damage == "extra":
                zipped.writestr("Echo/unexpected.bin", b"fictional extra")
            if damage == "source_change":
                (source / "Echo.exe").write_bytes(b"changed fictional source")
        return real_write(zipped, filename, arcname, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "write", damaged_write)
    with pytest.raises(packager.PackageError):
        run_package(packager, release)
    assert not list(output.iterdir())


def test_second_publication_failure_rolls_back_outputs(packager, release, monkeypatch):
    _, output, _ = release
    real_publish = packager._publish_file
    calls = 0

    def fail_checksum(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("fictional publication failure")
        real_publish(source, target)

    monkeypatch.setattr(packager, "_publish_file", fail_checksum)
    with pytest.raises(packager.PackageError):
        run_package(packager, release)
    assert not list(output.iterdir())


def test_zip_is_published_only_after_checksum(packager, release, monkeypatch):
    _, output, _ = release
    real_publish = packager._publish_file

    def check_publication(source, target):
        if target.suffix == ".zip":
            assert (output / (target.name + ".sha256")).is_file()
        real_publish(source, target)

    monkeypatch.setattr(packager, "_publish_file", check_publication)
    run_package(packager, release)


@pytest.mark.parametrize("relative", ["logs", "runtime/output", "runtime/qq-napcat-candidate/cache"])
def test_empty_state_directory_is_rejected(packager, release, relative):
    source, _, _ = release
    (source / relative).mkdir(parents=True)
    with pytest.raises(packager.PackageError):
        run_package(packager, release)


def test_manifest_extension_is_enforced(packager, release, tmp_path):
    source, output, project = release
    contract = json.loads(MANIFEST.read_text(encoding="utf-8"))
    contract["releaseTreePrivatePaths"].append("_internal/fictional-private.bin")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(contract), encoding="utf-8")
    (source / "_internal/fictional-private.bin").write_bytes(b"fictional state")
    with pytest.raises(packager.PackageError):
        packager.package_portable(source, output, project_file=project, manifest_file=manifest)


@pytest.mark.parametrize("failure", ["write_zip", "write_checksum"])
def test_generation_io_failure_cleans_staging_and_preserves_source(
    packager, release, monkeypatch, failure
):
    source, output, _ = release
    before = (source / "Echo.exe").read_bytes()
    if failure == "write_zip":
        def fail_write(*args, **kwargs):
            raise OSError("fictional archive write failure")
        monkeypatch.setattr(zipfile.ZipFile, "write", fail_write)
    else:
        real_write = Path.write_text

        def fail_checksum(path, *args, **kwargs):
            if path.suffix == ".sha256":
                raise OSError("fictional checksum write failure")
            return real_write(path, *args, **kwargs)
        monkeypatch.setattr(Path, "write_text", fail_checksum)
    with pytest.raises(packager.PackageError):
        run_package(packager, release)
    assert not list(output.iterdir())
    assert (source / "Echo.exe").read_bytes() == before


@pytest.mark.parametrize("version", ["../escape", "0.1.0/other", "", "v0.1.0"])
def test_unsafe_version_is_rejected(packager, release, version):
    _, output, project = release
    project.write_text(f'[project]\nversion = "{version}"\n', encoding="utf-8")
    with pytest.raises(packager.PackageError):
        run_package(packager, release)
    assert not output.exists()


@pytest.mark.slow_integration
def test_cli_packages_fictional_tree_and_reports_missing_source(release):
    source, output, _ = release
    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--source", str(source), "--output", str(output)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert (output / f"Echo-{version}-windows-x64.zip").is_file()
    missing_output = output.parent / "missing-output"
    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--source", str(source / "missing"),
         "--output", str(missing_output)], capture_output=True, check=False,
    )
    assert result.returncode == 1
    assert not missing_output.exists()
