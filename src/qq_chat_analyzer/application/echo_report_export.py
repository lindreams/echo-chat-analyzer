"""Package completed Echo report artifacts into a shareable directory."""

from __future__ import annotations

import json
import logging
import shutil
import stat
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from ..resources import user_data_dir


ECHO_REPORT_DIRECTORY_PREFIX = "Echo_Report_"
ECHO_REPORT_HTML_NAME = "echo-report.html"
ECHO_REPORT_JSON_NAME = "echo-report.json"
ECHO_REPORT_METADATA_NAME = "metadata.json"
ECHO_REPORT_README_NAME = "README.txt"
_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.report_package")

ECHO_REPORT_README = """\
Echo 聊天分析报告
=================

这是 Echo 生成的聊天分析报告。

隐私说明：所有数据均在本机处理，不会上传到网络。

文件说明：
- echo-report.html：报告页面，直接用浏览器打开即可查看。
- echo-report.json：报告的结构化数据，可供其他工具阅读。
- 若包含 media/ 目录，请保留整个报告目录一起移动或分享，离线打开无需联网。
- metadata.json：本报告包的轻量摘要。

本目录只包含分析结果，不包含原始聊天数据。
"""


class EchoReportExportError(RuntimeError):
    """Raised when the Echo report directory cannot be packaged."""


def package_echo_report(
    output_directory: Path,
    reports_root: Path | None = None,
    *,
    metadata: Mapping[str, object],
    now: datetime | None = None,
    cancelled=lambda: False,
) -> Path:
    """Publish a complete package by renaming same-root staging.

    Raw exports are never copied. The generated time comes from metadata,
    while ``now`` optionally controls the existing directory-name contract.
    """
    source_html = Path(output_directory) / ECHO_REPORT_HTML_NAME
    source_json = Path(output_directory) / ECHO_REPORT_JSON_NAME
    for source in (source_html, source_json):
        _require_no_reparse_points(source)
        if not source.is_file():
            raise EchoReportExportError(f"Echo report artifact is missing: {source.name}")

    root = (Path(reports_root) if reports_root is not None else user_data_dir() / "reports").absolute()
    _require_no_reparse_points(root)
    stamp = (
        now or datetime.fromisoformat(str(metadata["generated_at"])).astimezone()
    ).strftime("%Y%m%d_%H%M%S")
    root.mkdir(parents=True, exist_ok=True)
    target = _next_report_directory(root, stamp)
    from .report_staging import owned_report_staging

    with owned_report_staging(root) as staging:
        shutil.copy2(source_html, staging / ECHO_REPORT_HTML_NAME, follow_symlinks=False)
        shutil.copy2(source_json, staging / ECHO_REPORT_JSON_NAME, follow_symlinks=False)
        media_directory = Path(output_directory) / "media"
        references = set()
        try:
            payload = json.loads(source_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            if media_directory.exists() or media_directory.is_symlink():
                raise EchoReportExportError("Invalid report media manifest.") from None
            payload = {}
        if media_directory.exists() or media_directory.is_symlink():
            _require_no_reparse_points(media_directory)
        if isinstance(payload, dict):
            chapter = payload.get("stickers") or {}
            references = {asset.get("data_uri", "") for asset in chapter.get("assets", {}).values()
                          if asset.get("data_uri", "").startswith("media/")}
        if references:
            from ..media_content import MEDIA_FILE_NAME, file_chunks, publish_media
            media_directory = Path(output_directory) / "media"
            _require_no_reparse_points(media_directory)
            for reference in sorted(references):
                name = reference.removeprefix("media/")
                if not MEDIA_FILE_NAME.fullmatch(name):
                    raise EchoReportExportError("Unexpected report media artifact.")
                publish_media(file_chunks(media_directory / name), staging / "media" / name, cancelled=cancelled)
        (staging / ECHO_REPORT_METADATA_NAME).write_text(
            json.dumps(dict(metadata), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        (staging / ECHO_REPORT_README_NAME).write_text(
            ECHO_REPORT_README,
            encoding="utf-8",
        )
        for artifact in staging.iterdir():
            _require_no_reparse_points(artifact)
        if cancelled():
            raise InterruptedError("media_export_cancelled")
        while True:
            _require_no_reparse_points(target)
            if target.exists():
                target = _next_report_directory(root, stamp)
                continue
            try:
                # Windows rename fails if another publisher created target.
                staging.rename(target)
                break
            except FileExistsError:
                target = _next_report_directory(root, stamp)
    return target


def _require_no_reparse_points(path: Path) -> None:
    """Reject links/junctions in artifacts and every existing ancestor."""
    for candidate in (path.absolute(), *path.absolute().parents):
        try:
            attributes = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(attributes.st_mode) or (
            getattr(attributes, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            raise EchoReportExportError("Report package paths must not contain links.")


def _next_report_directory(root: Path, stamp: str) -> Path:
    candidate = root / f"{ECHO_REPORT_DIRECTORY_PREFIX}{stamp}"
    suffix = 2
    while candidate.exists() or candidate.is_symlink():
        candidate = root / f"{ECHO_REPORT_DIRECTORY_PREFIX}{stamp}_{suffix}"
        suffix += 1
    return candidate


__all__ = [
    "ECHO_REPORT_DIRECTORY_PREFIX",
    "ECHO_REPORT_HTML_NAME",
    "ECHO_REPORT_JSON_NAME",
    "ECHO_REPORT_METADATA_NAME",
    "ECHO_REPORT_README_NAME",
    "EchoReportExportError",
    "package_echo_report",
]
