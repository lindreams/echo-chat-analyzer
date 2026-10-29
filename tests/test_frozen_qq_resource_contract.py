"""QQ metadata declarations and simulated Frozen reads, without building an EXE."""

import hashlib
import json
from pathlib import Path
import runpy
import shutil
import sys

import pytest

from qq_chat_analyzer import resources
from qq_chat_analyzer.application.qq.qq_environment_config import QQEnvironmentConfig
from qq_chat_analyzer.application.qq.qq_runtime_paths import resolve_runtime_paths
from qq_chat_analyzer.application.qq.qq_runtime_workspace import QQWorkspaceError


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_FILES = ("windows_runtime_manifest.json", "qq_napcat_runtime_pins.json")


def _spec_datas(project_root):
    # Stop before PyInstaller analysis: evaluate the real declarations only.
    class AnalysisReached(Exception):
        pass

    captured = []

    def capture_analysis(*args, **kwargs):
        captured.extend(kwargs["datas"])
        raise AnalysisReached

    with pytest.raises(AnalysisReached):
        runpy.run_path(str(ROOT / "LocalChatAnalyzer.spec"), init_globals={
            "SPEC": str(project_root / "LocalChatAnalyzer.spec"),
            "Analysis": capture_analysis,
        })
    return captured


@pytest.mark.parametrize("filename", CONTRACT_FILES)
def test_spec_declares_explicit_qq_contract_files_in_scripts(filename):
    datas = _spec_datas(ROOT)
    declarations = [(Path(source), target) for source, target in datas]
    assert (ROOT / "scripts" / filename, "scripts") in declarations
    assert all(source != ROOT / "scripts" for source, _ in declarations)


@pytest.fixture
def frozen_qq(tmp_path, monkeypatch):
    """Fictional program plus source metadata that must never be a fallback."""
    from test_windows_runtime_contract import prepare_sqlite_build_input

    project = tmp_path / "development-checkout"
    metadata = project / "scripts"
    prepare_sqlite_build_input(project)
    shutil.copyfile(ROOT / "pyproject.toml", project / "pyproject.toml")
    version_source = project / "src/qq_chat_analyzer/version.py"
    version_source.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "src/qq_chat_analyzer/version.py", version_source)
    install = tmp_path / "安装 空间" / "Echo"
    internal = install / "_internal"
    internal.mkdir(parents=True)
    program = install / "runtime" / "qq-napcat-candidate"
    assets = {
        "plugins/napcat-plugin-echo/index.mjs": b"fictional plugin",
        "config/plugins.json": b'{"napcat-plugin-echo":true}\n',
        "napcat.mjs": b"fictional patched program",
    }
    for name, content in assets.items():
        path = program / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    digest = lambda content: hashlib.sha256(content).hexdigest()
    manifest = {
        "qqPins": "qq_napcat_runtime_pins.json",
        "requirements": [{"path": "qq-napcat-candidate/" + name, "type": "file"}
                         for name in assets],
    }
    pins = {
        "upstream": {"version": "fictional-version"},
        "napcatPatch": {"path": "napcat.mjs", "patchedSha256": digest(assets["napcat.mjs"])},
        "templates": [{"target": "plugins/napcat-plugin-echo/index.mjs",
                       "sha256": digest(assets["plugins/napcat-plugin-echo/index.mjs"])}],
        "pluginConfigSha256": digest(assets["config/plugins.json"]),
    }
    for filename, content in zip(CONTRACT_FILES, (manifest, pins)):
        (metadata / filename).write_text(json.dumps(content), encoding="utf-8")
    monkeypatch.setattr(resources, "_PROJECT_ROOT", project)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "Echo.exe"))
    monkeypatch.chdir(project)
    return project, internal, program, assets


@pytest.mark.parametrize("prepare", [False, True])
def test_spec_destinations_support_managed_frozen_resolution(frozen_qq, prepare):
    project, internal, program, assets = frozen_qq
    for source, target in _spec_datas(project):
        source = Path(source)
        if source.name in CONTRACT_FILES:
            destination = internal / target / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    for filename in CONTRACT_FILES:
        path = resources.resource_path("scripts/" + filename)
        assert path == internal / "scripts" / filename
        assert path.read_bytes() == (project / "scripts" / filename).read_bytes()
    # Remove the development metadata before the actual managed resolver runs.
    shutil.rmtree(project / "scripts")
    user = resources.user_data_root()
    result = resolve_runtime_paths(QQEnvironmentConfig(runtime_mode="managed"), prepare=prepare)
    assert result.program_root == program
    assert result.work_root.parent == user / "runtime" / "qq"
    assert result.snapshot_root == user / "transient" / "qq-direct-db"
    if prepare:
        assert (result.work_root / "plugins/napcat-plugin-echo/index.mjs").read_bytes() == assets[
            "plugins/napcat-plugin-echo/index.mjs"]
    else:
        assert not user.exists()


@pytest.mark.parametrize("missing", CONTRACT_FILES)
@pytest.mark.parametrize("prepare", [False, True])
def test_missing_frozen_contract_refuses_development_fallback(frozen_qq, missing, prepare):
    project, internal, _, _ = frozen_qq
    packaged = internal / "scripts"
    packaged.mkdir()
    for filename in CONTRACT_FILES:
        if filename != missing:
            shutil.copyfile(project / "scripts" / filename, packaged / filename)
    assert (project / "scripts" / missing).is_file()
    expected_error = QQWorkspaceError if prepare else FileNotFoundError
    with pytest.raises(expected_error) as error:
        resolve_runtime_paths(QQEnvironmentConfig(runtime_mode="managed"), prepare=prepare)
    if not prepare:
        assert Path(error.value.filename) == packaged / missing
    assert resources.resource_path("scripts/" + missing) == packaged / missing
    assert not resources.user_data_root().exists()
