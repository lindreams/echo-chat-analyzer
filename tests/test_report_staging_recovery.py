"""Fictional publication failures and bounded staging ownership recovery."""

import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from qq_chat_analyzer.application import echo_report_export as export
from qq_chat_analyzer.application.report_package_catalog import ReportPackageCatalog
from test_echo_report_export import _metadata, _output_directory


@pytest.fixture
def orphan(tmp_path, monkeypatch):
    output = _output_directory(tmp_path)
    root = tmp_path / "reports"
    def fail_publication(*args):
        raise OSError("fictional publication failure")

    def fail_cleanup(*args, **kwargs):
        raise PermissionError("fictional first cleanup failure")

    with monkeypatch.context() as failure:
        failure.setattr(Path, "rename", fail_publication)
        failure.setattr(export.shutil, "rmtree", fail_cleanup)
        with pytest.raises(OSError, match="publication failure"):
            export.package_echo_report(output, root, metadata=_metadata())
    staging, = [entry for entry in root.iterdir() if entry.is_dir()]
    assert (staging / "echo-report.html").is_file()
    return SimpleNamespace(root=root, staging=staging, output=output)


def test_owned_staging_recovers_after_publication_and_cleanup_failure(orphan):
    catalog = ReportPackageCatalog(orphan.root)
    listing = catalog.list_reports()
    assert not listing.reports and not listing.issues
    assert not orphan.staging.exists()
    assert list(orphan.root.iterdir()) == []
    assert (orphan.output / "echo-report.html").is_file()


def test_prefix_and_report_shaped_unknown_entries_are_preserved(orphan):
    regular = orphan.root / (".echo-report-" + "a" * 32)
    regular.write_text("fictional user file", encoding="utf-8")
    forged = orphan.root / (".echo-report-" + "b" * 32)
    forged.mkdir()
    for name in ("echo-report.html", "echo-report.json", "metadata.json", "README.txt"):
        (forged / name).write_text("fictional user file", encoding="utf-8")
    catalog = ReportPackageCatalog(orphan.root)
    catalog.list_reports()
    assert regular.read_text(encoding="utf-8") == "fictional user file"
    assert len(list(forged.iterdir())) == 4
    assert not orphan.staging.exists()


@pytest.mark.parametrize("location", ["directory", "marker"])
def test_owned_staging_reparse_is_rejected_without_deleting_any_member(orphan, monkeypatch, location):
    selected = {
        "directory": orphan.staging,
        "artifact": orphan.staging / "echo-report.html",
        "marker": next(orphan.root.glob("*.owner.json")),
    }[location]
    original = Path.lstat

    def reparse(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == selected:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return info

    monkeypatch.setattr(Path, "lstat", reparse)
    ReportPackageCatalog(orphan.root).list_reports()
    assert (orphan.staging / "echo-report.json").exists()
    assert (orphan.staging / "echo-report.html").exists()


@pytest.mark.slow_integration
def test_staging_junction_is_preserved_and_external_target_untouched(orphan, tmp_path):
    if os.name != "nt":
        pytest.skip("Windows junction regression")
    external = tmp_path / "external"
    external.mkdir()
    (external / "sentinel.txt").write_text("keep", encoding="utf-8")
    junction = orphan.root / (".echo-report-" + "c" * 32)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(external)], check=True, capture_output=True)
    try:
        ReportPackageCatalog(orphan.root).list_reports()
        assert junction.is_dir()
        assert (external / "sentinel.txt").read_text(encoding="utf-8") == "keep"
        assert not orphan.staging.exists()
    finally:
        junction.rmdir()


def test_staging_cleanup_failure_is_private_and_retryable(orphan, monkeypatch, caplog):
    original = export.shutil.rmtree
    def fail_cleanup(*args, **kwargs):
        raise PermissionError(r"C:\Users\Fictional\Private\report.html")
    monkeypatch.setattr(export.shutil, "rmtree", fail_cleanup)
    catalog = ReportPackageCatalog(orphan.root)
    listing = catalog.list_reports()
    assert not listing.reports and not listing.issues
    assert orphan.staging.exists()
    assert "recovery" in caplog.text.lower()
    assert "Fictional" not in caplog.text
    caplog.clear()
    monkeypatch.setattr(export.shutil, "rmtree", original)
    catalog.list_reports()
    assert not orphan.staging.exists()


def test_directory_replacement_does_not_inherit_staging_ownership(orphan, tmp_path):
    retained = tmp_path / "retained-original"
    orphan.staging.rename(retained)
    orphan.staging.mkdir()
    (orphan.staging / "echo-report.html").write_text("unknown replacement", encoding="utf-8")
    ReportPackageCatalog(orphan.root).list_reports()
    assert (orphan.staging / "echo-report.html").read_text(encoding="utf-8") == "unknown replacement"
    assert (retained / "echo-report.json").is_file()


def test_copied_proof_does_not_authorize_a_forged_directory(orphan):
    marker, = orphan.root.glob("*.owner.json")
    forged = orphan.root / (".echo-report-" + "d" * 32)
    forged.mkdir()
    (forged / "echo-report.html").write_text("keep", encoding="utf-8")
    copied = orphan.root / (forged.name + ".owner.json")
    copied.write_bytes(marker.read_bytes())
    ReportPackageCatalog(orphan.root).list_reports()
    assert (forged / "echo-report.html").read_text(encoding="utf-8") == "keep"
    assert copied.is_file()
    assert not orphan.staging.exists()


def test_unknown_member_prevents_all_staging_deletion(orphan):
    (orphan.staging / "user-notes.txt").write_text("keep", encoding="utf-8")
    ReportPackageCatalog(orphan.root).list_reports()
    assert (orphan.staging / "user-notes.txt").is_file()
    assert (orphan.staging / "echo-report.html").is_file()
    assert (orphan.staging / "echo-report.json").is_file()


def test_partial_deletion_keeps_proof_for_later_recovery(orphan, monkeypatch):
    original = export.shutil.rmtree
    def partial_delete(path):
        (path / "echo-report.html").unlink()
        raise PermissionError("fictional partial deletion")
    monkeypatch.setattr(export.shutil, "rmtree", partial_delete)
    ReportPackageCatalog(orphan.root).list_reports()
    assert not (orphan.staging / "echo-report.html").exists()
    assert (orphan.staging / "echo-report.json").exists()
    assert list(orphan.root.glob("*.owner.json"))
    monkeypatch.setattr(export.shutil, "rmtree", original)
    ReportPackageCatalog(orphan.root).list_reports()
    assert list(orphan.root.iterdir()) == []


def test_recovery_keeps_active_publication_and_formal_package_contract(tmp_path, monkeypatch):
    output = _output_directory(tmp_path)
    root = tmp_path / "reports"
    original = export.shutil.copy2

    def copy_and_list(source, target, **kwargs):
        listing = ReportPackageCatalog(root).list_reports()
        assert not listing.reports
        assert Path(target).parent.is_dir()
        return original(source, target, **kwargs)

    monkeypatch.setattr(export.shutil, "copy2", copy_and_list)
    published = export.package_echo_report(output, root, metadata=_metadata())
    assert {p.name for p in published.iterdir()} == {
        "echo-report.html", "echo-report.json", "metadata.json", "README.txt",
    }
    catalog = ReportPackageCatalog(root)
    assert [r.package_name for r in catalog.list_reports().reports] == [published.name]
    assert catalog.delete_packages([published.name]).complete
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("stage", ["open", "proof-write"])
def test_ownership_creation_failure_leaves_no_workspace(tmp_path, monkeypatch, stage):
    from qq_chat_analyzer.application import report_staging
    output = _output_directory(tmp_path)
    root = tmp_path / "reports"
    original_open = Path.open
    original_dumps = report_staging.json.dumps

    def fail_open(path, *args, **kwargs):
        if path.name.endswith(".owner.json") and stage == "open":
            raise PermissionError("fictional ownership open failure")
        return original_open(path, *args, **kwargs)

    def fail_proof(value, *args, **kwargs):
        if value.get("schema") == "echo-report-staging.v1" and stage == "proof-write":
            raise OSError("fictional ownership write failure")
        return original_dumps(value, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_open)
    monkeypatch.setattr(report_staging.json, "dumps", fail_proof)
    with pytest.raises(OSError, match="ownership"):
        export.package_echo_report(output, root, metadata=_metadata())
    assert list(root.iterdir()) == []
