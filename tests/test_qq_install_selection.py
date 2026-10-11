"""Installation selection uses fictional files and version resources only."""

import json
from pathlib import Path

import pytest

from qq_chat_analyzer.application.qq import qq_auth_bridge as bridge
from qq_chat_analyzer.application.qq.qq_environment_config import (
    QQEnvironmentConfig, QQEnvironmentConfigLoader, QQEnvironmentConfigWriter,
)
from test_qq_auth_bridge import _FakeProcess, _launch_target, _runtime_config


def _install(root, name, build=None):
    path = root / name / "QQ.exe"
    path.parent.mkdir()
    path.write_bytes(b"fictional executable")
    package = path.parent / "resources/app/package.json"
    package.parent.mkdir(parents=True)
    info = {"name": "QQ", "main": "index.js"}
    if build is not None:
        info.update(version=f"9.9.21-{build}", buildVersion=str(build))
        (package.parent / "wrapper.node").write_bytes(b"fictional native resource")
    package.write_text(json.dumps(info), encoding="utf-8")
    return path


def _saved(root, path):
    (root / "config").mkdir(exist_ok=True)
    (root / "config/qq_path.txt").write_text(str(path), encoding="utf-8")


@pytest.mark.parametrize("old,new", [(38711, 53644), (27597, 40768)])
@pytest.mark.parametrize("cache", ["launcher", "legacy_config"])
def test_old_cache_cannot_hide_compatible_system_install(tmp_path, monkeypatch, old, new, cache):
    cached = _install(tmp_path, "cached", old)
    current = _install(tmp_path, "current", new)
    _saved(tmp_path, cached)
    config = None
    if cache == "legacy_config":
        config_file = tmp_path / "qq.json"
        config_file.write_text(json.dumps({"qq_install_path": str(cached)}), encoding="utf-8")
        config = QQEnvironmentConfigLoader(config_file).load()
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [cached, current])
    monkeypatch.setattr(bridge, "read_qq_version", lambda p: (9, 9, 21, old if p == cached else new))
    assert bridge.resolve_qq_install_path(config, tmp_path) == current


def test_old_cache_without_confirmed_compatible_install_keeps_old_version_error(tmp_path, monkeypatch, caplog):
    config = _runtime_config(tmp_path, with_qq_path=False)
    cached = _install(tmp_path, "cached", 38711)
    unknown = _install(tmp_path, "9.9.99-65535")
    _saved(tmp_path, cached)
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [unknown])
    monkeypatch.setattr(bridge, "read_qq_version", lambda p: (9, 9, 21, 38711) if p == cached else None)
    with caplog.at_level("DEBUG"), pytest.raises(bridge.QQAuthWindowUnavailable) as error:
        bridge.default_auth_window_launcher(config)
    assert error.value.code == "qq_version_too_old"
    assert "38711" in str(error.value)
    assert str(tmp_path) not in str(error.value) + caplog.text


def test_candidate_validation_deduplication_and_stable_compatible_choice(tmp_path, monkeypatch):
    unknown = _install(tmp_path, "unknown")
    older = _install(tmp_path, "older", 38711)
    compatible = _install(tmp_path, "compatible", 40768)
    newer = _install(tmp_path, "newer", 53644)
    wrong_file = tmp_path / "uninstall.exe"
    wrong_file.write_bytes(b"fictional")
    directory = tmp_path / "directory/QQ.exe"
    directory.mkdir(parents=True)
    reads = []

    original_read = bridge.read_qq_resources

    def read(path):
        reads.append(path)
        if path == unknown:
            raise OSError(f"{tmp_path} fictional-account fictional-token")
        return original_read(path)

    monkeypatch.setattr(bridge, "read_qq_resources", read)
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [
        tmp_path / "missing/QQ.exe", directory, wrong_file, Path("invalid\0/QQ.exe"),
        unknown, unknown.parent / "../unknown/QQ.exe", older, compatible, newer,
    ])
    assert bridge.resolve_qq_install_path(None, tmp_path) == compatible
    assert reads.count(unknown) == 1
    assert directory not in reads and wrong_file not in reads


@pytest.mark.parametrize("version", [None, "9.9.99-65535", (9, 9, 21, 0), (10, 0, 0, 53644), (9, 9, 21, True)])
def test_unknown_metadata_keeps_original_candidate_order(tmp_path, monkeypatch, version):
    cached = _install(tmp_path, "cached")
    other = _install(tmp_path, "other")
    _saved(tmp_path, cached)
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [other])
    monkeypatch.setattr(bridge, "read_qq_version", lambda _: version)
    assert bridge.resolve_qq_install_path(None, tmp_path) == cached


def test_single_compatible_install_is_selected(tmp_path, monkeypatch):
    current = _install(tmp_path, "current", 40768)
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [current])
    monkeypatch.setattr(bridge, "read_qq_version", lambda _: (9, 9, 30, 40768))
    assert bridge.resolve_qq_install_path(None, tmp_path) == current


def test_script_old_install_cannot_hide_registry_compatible_install(tmp_path, monkeypatch):
    old = _install(tmp_path, "old", 38711)
    current = _install(tmp_path, "current", 53644)
    (tmp_path / "find-qq.ps1").write_text("# fictional", encoding="utf-8")
    monkeypatch.setattr(bridge, "_detect_qq_path_with_script", lambda _: old)
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [current])
    monkeypatch.setattr(bridge, "read_qq_version", lambda p: (9, 9, 21, 38711 if p == old else 53644))
    assert bridge.resolve_qq_install_path(None, tmp_path) == current


def test_explicit_path_survives_save_load_and_default_runtime_rebase(tmp_path, monkeypatch):
    chosen = _install(tmp_path, "chosen", 38711)
    current = _install(tmp_path, "current", 53644)
    config_file = tmp_path / "qq.json"
    QQEnvironmentConfigWriter(config_file).save(QQEnvironmentConfig(qq_install_path=chosen, runtime_mode="managed"))
    config = QQEnvironmentConfigLoader(config_file).load_or_default()
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [current])
    monkeypatch.setattr(bridge, "read_qq_version", lambda p: (9, 9, 21, 38711 if p == chosen else 53644))
    assert bridge.resolve_qq_install_path(config, tmp_path) == chosen


def test_selection_is_captured_for_version_gate_and_actual_launch(tmp_path, monkeypatch):
    config = _runtime_config(tmp_path, with_qq_path=False)
    old = _install(tmp_path, "old", 38711)
    current = _install(tmp_path, "current", 53644)
    _saved(tmp_path, old)
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [current])
    reads, launches = [], []

    original_read = bridge.read_qq_resources

    def read(path):
        reads.append(path)
        return original_read(path)

    monkeypatch.setattr(bridge, "read_qq_resources", read)
    monkeypatch.setattr(bridge, "read_qq_version", lambda _: pytest.fail("known resources must not use PE"))
    monkeypatch.setattr(*_launch_target(bridge), lambda command, **options: launches.append((command, options)) or _FakeProcess(4243))
    launcher = bridge.default_auth_window_launcher(config)
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [old])
    launcher()
    assert reads[-1] == current.resolve()
    assert launches[0][0][1] == str(current.resolve())
    assert launches[0][1]["env"]["NAPCAT_QQ_PATH"] == str(current.resolve())


def test_invalid_explicit_path_does_not_launch_another_install(tmp_path, monkeypatch):
    current = _install(tmp_path, "current")
    config = QQEnvironmentConfig(qq_install_path=tmp_path / "missing/QQ.exe")
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [current])
    assert bridge.resolve_qq_install_path(config, tmp_path) is None


def test_legacy_path_stays_automatic_after_config_resave(tmp_path, monkeypatch):
    old = _install(tmp_path, "old", 38711)
    current = _install(tmp_path, "current", 53644)
    config_file = tmp_path / "qq.json"
    config_file.write_text(json.dumps({"qq_install_path": str(old)}), encoding="utf-8")
    loader = QQEnvironmentConfigLoader(config_file)
    QQEnvironmentConfigWriter(config_file).save(loader.load_or_default())
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [current])
    monkeypatch.setattr(bridge, "read_qq_version", lambda p: (9, 9, 21, 38711 if p == old else 53644))
    assert bridge.resolve_qq_install_path(loader.load_or_default(), tmp_path) == current
