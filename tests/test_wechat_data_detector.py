"""Tests for WeChat chat record directory auto-detection.

Every directory and path here is fabricated in temp folders; the real user
profile and WeChat config are never touched.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))


def _module():
    return importlib.import_module(
        "qq_chat_analyzer.application.wechat.wechat_data_detector"
    )


@pytest.fixture(autouse=True)
def _isolate_registry(monkeypatch):
    """Detector unit tests must never consult the host Windows registry."""
    monkeypatch.setattr(_module(), "registered_wechat_data_dirs", lambda: [])


def _xwechat_account(base: Path, wxid: str) -> Path:
    """Create one valid WeChat 4.x account directory."""
    account = base / "xwechat_files" / wxid
    message_dir = account / "db_storage" / "message"
    message_dir.mkdir(parents=True)
    (message_dir / "session.db").write_bytes(b"fake")
    (message_dir / "message_0.db").write_bytes(b"fake")
    return account


def test_custom_config_location_detected(tmp_path: Path) -> None:
    module = _module()
    home = tmp_path / "home"
    appdata = tmp_path / "appdata"
    base = tmp_path / "custom_storage"
    root = _xwechat_account(base, "wxid_fake_b")
    config_dir = appdata / "Tencent" / "xwechat" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "custom.ini").write_text(str(base), encoding="utf-8")

    detected = module.detect_wechat_data_roots(home=home, appdata=appdata)

    assert detected == [root]


def test_multiple_accounts_return_all_without_guessing(
    tmp_path: Path,
) -> None:
    module = _module()
    home = tmp_path / "home"
    appdata = tmp_path / "appdata"
    first = _xwechat_account(home / "Documents", "wxid_fake_a")
    second = _xwechat_account(home / "Documents", "wxid_fake_b")

    detected = module.detect_wechat_data_roots(home=home, appdata=appdata)

    assert sorted(detected) == sorted([first, second])
    assert (
        module.detect_single_wechat_data_root(
            home=home,
            appdata=appdata,
        )
        is None
    )
