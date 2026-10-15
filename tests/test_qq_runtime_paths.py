"""Pure path and explicitly opted-in config migration contracts."""

import json
import sys
from pathlib import Path

import pytest

from qq_chat_analyzer import resources
from qq_chat_analyzer.application.qq import qq_environment_config as config
from qq_chat_analyzer.application.qq import qq_runtime_paths as paths


@pytest.mark.parametrize("installation", [r"C:\Program Files\Echo", r"D:\中文 空格\Echo"])
def test_install_move_only_changes_program_root(installation, tmp_path):
    user = tmp_path / "用户 数据"
    settings = config.QQEnvironmentConfig(
        runtime_directory=Path(r"Z:\old install\runtime"), runtime_mode="managed"
    )
    result = paths.qq_runtime_paths(settings, component_id="a" * 64,
                                    program_root=Path(installation), data_root=user)
    assert result.program_root == Path(installation)
    assert result.work_root == user / "runtime" / "qq" / ("a" * 64)
    assert result.snapshot_root == user / "transient" / "qq-direct-db"
    assert not user.exists()


def test_custom_path_is_never_replaced(tmp_path):
    custom = config.QQEnvironmentConfig(runtime_directory=tmp_path / "custom",
                                        runtime_mode="custom")
    result = paths.qq_runtime_paths(custom, component_id="c" * 64,
                                    program_root=tmp_path / "new", data_root=tmp_path / "user")
    assert result.program_root == tmp_path / "custom"


def test_untagged_existing_config_requires_explicit_decision(tmp_path):
    location = tmp_path / "qq.json"
    location.write_text(json.dumps({"runtime_directory": str(tmp_path / "old")}), encoding="utf-8")
    saved = config.QQEnvironmentConfigLoader(location).load()
    assert saved.runtime_directory == tmp_path / "old"
    assert saved.runtime_mode is None
    with pytest.raises(paths.AmbiguousQQRuntime):
        paths.qq_runtime_paths(saved, component_id="d" * 64)
    assert json.loads(location.read_text(encoding="utf-8")) == {"runtime_directory": str(tmp_path / "old")}


def test_unknown_mode_cannot_be_interpreted_as_managed(tmp_path):
    location = tmp_path / "qq.json"
    location.write_text('{"runtime_mode":"typo"}', encoding="utf-8")
    with pytest.raises(config.QQConfigCorrupted):
        config.QQEnvironmentConfigLoader(location).load()


@pytest.mark.parametrize("identity", ["../escape", "", "A" * 64, "a" * 63])
def test_component_identity_cannot_escape_user_directory(identity):
    with pytest.raises(ValueError):
        paths.qq_runtime_paths(component_id=identity)


def test_legacy_fallback_does_not_claim_to_migrate_saved_ownership(tmp_path):
    location = tmp_path / "qq.json"
    original = {"runtime_directory": str(tmp_path / "old-install")}
    location.write_text(json.dumps(original), encoding="utf-8")
    fallback = config.QQEnvironmentConfigLoader(location).load_or_default()
    # The old startup fallback is retained, but cannot silently settle ownership
    # of the user's persisted, untagged choice for the future path resolver.
    assert fallback.runtime_mode is None
    assert json.loads(location.read_text(encoding="utf-8")) == original
