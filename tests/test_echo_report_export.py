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


@pytest.mark.parametrize("failure", [None, "digest", "traversal", "cancel", "missing", "directory_missing"])
def test_package_media_requires_selected_digest_named_files_and_is_atomic(tmp_path, failure):
    import hashlib
    module = _module()
    output = _output_directory(tmp_path)
    content = b"fictional verified media"
    name = hashlib.sha256(content).hexdigest() + ".gif"
    media = output / "media"
    media.mkdir()
    (media / name).write_bytes(b"damaged" if failure == "digest" else content)
    unrelated = media / "unrelated-user-file.txt"
    unrelated.write_bytes(b"private unselected data")
    reference = "media/../unrelated-user-file.txt" if failure == "traversal" else "media/" + name
    (output / "echo-report.json").write_text(json.dumps({"stickers":{"assets":{
        "sticker:1":{"data_uri":reference,"status":"available"}}}}),encoding="utf-8")
    reports = tmp_path / "reports"
    if failure == "missing":
        (media / name).unlink()
    if failure == "directory_missing":
        media.rename(output / "preserved-media")
        unrelated = output / "preserved-media" / unrelated.name
    if failure:
        with pytest.raises((ValueError, OSError, module.EchoReportExportError)):
            module.package_echo_report(output, reports, metadata=_metadata(), cancelled=lambda: failure == "cancel")
        assert not list(reports.glob("Echo_Report_*"))
    else:
        published = module.package_echo_report(output, reports, metadata=_metadata())
        assert (published / "media" / name).read_bytes() == content
        assert len(list((published / "media").iterdir())) == 1
    assert unrelated.read_bytes() == b"private unselected data"


@pytest.mark.parametrize("changed", [False, True])
def test_media_export_compares_stat_stability_within_each_api(tmp_path, monkeypatch, changed):
    from types import SimpleNamespace
    from qq_chat_analyzer import media_content

    path = tmp_path / "fictional.bin"
    path.write_bytes(b"fictional media")
    fstat = media_content.os.fstat
    calls = 0

    def windows_stat(fd):
        nonlocal calls
        calls += 1
        info = fstat(fd)
        values = {name: getattr(info, name) for name in (
            "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}
        values["st_ctime_ns"] += 100 + (calls if changed else 0)
        return SimpleNamespace(**values)

    monkeypatch.setattr(media_content.os, "fstat", windows_stat)
    if changed:
        with pytest.raises(ValueError, match="media_export_file_changed"):
            b"".join(media_content.file_chunks(path))
    else:
        assert b"".join(media_content.file_chunks(path)) == b"fictional media"


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
    readme = (target / "README.txt").read_text(encoding="utf-8")
    assert "原话" in readme and "分享" in readme
    assert "不包含原始聊天记录" not in readme
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
