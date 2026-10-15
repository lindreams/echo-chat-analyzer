"""Behavior tests for packaging completed Echo report artifacts."""

from __future__ import annotations

import importlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest


def _module():
    return importlib.import_module(
        "qq_chat_analyzer.application.echo_report_export"
    )


def _metadata():
    return {
        "schema_version": "echo-report-meta.v1",
        "generated_at": "2026-08-15T14:30:12+00:00",
        "source": "qq",
        "conversation_name": "Fictional Conversation",
        "conversation_kind": "group",
        "message_count": 120,
        "active_days": 8,
        "participant_count": 5,
        "message_start_timestamp": 1704067200,
        "message_end_timestamp": 1706745600,
        "analysis_scope": {
            "mode": "custom",
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
        },
    }


def _output_directory(tmp_path: Path) -> Path:
    output = tmp_path / "generated-output"
    output.mkdir()
    (output / "echo-report.html").write_text(
        "<html>fictional echo report</html>",
        encoding="utf-8",
    )
    (output / "echo-report.json").write_text(
        '{"schema_version": "echo-report.v0.7"}',
        encoding="utf-8",
    )
    (output / "raw-chat-export.json").write_text(
        '{"messages": [{"text": "fictional raw chat"}]}',
        encoding="utf-8",
    )
    return output


def test_package_creates_echo_report_directory_with_expected_files(
    tmp_path: Path,
) -> None:
    module = _module()
    output = _output_directory(tmp_path)
    reports_root = tmp_path / "reports"

    target = module.package_echo_report(
        output,
        reports_root,
        metadata=_metadata(),
        now=datetime(2026, 8, 15, 14, 30, 12),
    )

    assert target == reports_root / "Echo_Report_20260815_143012"
    assert target.is_dir()
    assert (target / "echo-report.html").is_file()
    assert (target / "echo-report.json").is_file()
    assert (target / "README.txt").is_file()
    assert {path.name for path in target.iterdir()} == {
        "echo-report.html", "echo-report.json", "metadata.json", "README.txt",
    }
    assert json.loads((target / "metadata.json").read_text(encoding="utf-8")) == _metadata()


def test_package_never_copies_raw_chat_data(tmp_path: Path) -> None:
    module = _module()
    output = _output_directory(tmp_path)

    target = module.package_echo_report(
        output,
        tmp_path / "reports",
        metadata=_metadata(),
        now=datetime(2026, 8, 15, 14, 30, 12),
    )

    names = {path.name for path in target.iterdir()}
    assert names == {"echo-report.html", "echo-report.json", "metadata.json", "README.txt"}
    assert "raw-chat-export.json" not in names


@pytest.mark.parametrize("stage", ["html", "metadata", "rename"])
def test_each_publication_failure_removes_staging_and_preserves_scratch(
    tmp_path, monkeypatch, stage,
):
    module = _module()
    output = _output_directory(tmp_path)
    root = tmp_path / "reports"
    root.mkdir()
    existing = root / "Echo_Report_20260815_143012"
    existing.mkdir()
    (existing / "sentinel.txt").write_text("keep", encoding="utf-8")
    copy = module.shutil.copy2
    write = Path.write_text
    rename = Path.rename

    def failing_copy(source, destination, *args, **kwargs):
        assert list(root.glob("Echo_Report_*")) == [existing]
        result = copy(source, destination, *args, **kwargs)
        if Path(source).name == {"html": "echo-report.html", "json": "echo-report.json"}.get(stage):
            raise OSError("fictional copy failure after writing")
        return result

    def failing_write(path, *args, **kwargs):
        assert list(root.glob("Echo_Report_*")) == [existing]
        result = write(path, *args, **kwargs)
        if path.name == {"metadata": "metadata.json", "readme": "README.txt"}.get(stage):
            raise OSError("fictional write failure after writing")
        return result

    def failing_rename(path, target):
        assert {p.name for p in path.iterdir()} == {
            "echo-report.html", "echo-report.json", "metadata.json", "README.txt",
        }
        if stage == "rename":
            raise OSError("fictional publication failure")
        return rename(path, target)

    monkeypatch.setattr(module.shutil, "copy2", failing_copy)
    monkeypatch.setattr(Path, "write_text", failing_write)
    monkeypatch.setattr(Path, "rename", failing_rename)
    with pytest.raises(OSError):
        module.package_echo_report(
            output, root, metadata=_metadata(), now=datetime(2026, 8, 15, 14, 30, 12),
        )
    assert list(root.iterdir()) == [existing]
    assert (existing / "sentinel.txt").read_text(encoding="utf-8") == "keep"
    assert {p.name for p in output.iterdir()} == {
        "echo-report.html", "echo-report.json", "raw-chat-export.json",
    }


def test_publish_collision_does_not_overwrite_another_package(tmp_path, monkeypatch):
    module = _module()
    output = _output_directory(tmp_path)
    root = tmp_path / "reports"
    rename = Path.rename
    collision = []

    def race(path, target):
        if not collision:
            target.mkdir()
            (target / "sentinel.txt").write_text("keep", encoding="utf-8")
            collision.append(target)
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", race)
    target = module.package_echo_report(
        output, root, metadata=_metadata(), now=datetime(2026, 8, 15, 14, 30, 12),
    )
    assert target.name == "Echo_Report_20260815_143012_2"
    assert (collision[0] / "sentinel.txt").read_text(encoding="utf-8") == "keep"
    assert len(list(root.iterdir())) == 2


@pytest.mark.parametrize("linked_location", ["source", "reports_root"])
@pytest.mark.slow_integration
def test_package_rejects_junction_without_touching_target(tmp_path, linked_location):
    import os
    import subprocess

    if os.name != "nt":
        pytest.skip("Windows junction regression")
    output = _output_directory(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    junction = tmp_path / "linked-directory"
    linked_target = output if linked_location == "source" else external
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(linked_target)], check=True, capture_output=True)
    try:
        root = tmp_path / "reports"
        with pytest.raises(_module().EchoReportExportError):
            _module().package_echo_report(
                junction if linked_location == "source" else output,
                junction if linked_location == "reports_root" else root,
                metadata=_metadata(),
            )
        assert not root.exists()
        assert list(external.iterdir()) == []
        assert (output / "echo-report.html").is_file()
    finally:
        junction.rmdir()


@pytest.mark.slow_integration
def test_published_package_preserves_inherited_windows_acl(tmp_path):
    import os
    import subprocess

    if os.name != "nt":
        pytest.skip("Windows ACL regression")
    output = _output_directory(tmp_path)
    target = _module().package_echo_report(
        output, tmp_path / "reports", metadata=_metadata(),
    )
    acl = subprocess.run(
        ["icacls", str(target)], check=True, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    ).stdout
    assert "(I)" in acl
