"""Release version consumers must agree with the project metadata."""

from pathlib import Path
import importlib.metadata
import subprocess
import sys
import json
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _spec_datas(project_root):
    # Other test modules prepend src at collection time. Its egg-info then
    # shadows the installed dist-info that the real build command consumes.
    # Execute the spec in the same isolated interpreter used for build checks.
    script = """
import json, runpy, sys
# Use the exact metadata directory selected by the parent build environment,
# while -I still rejects incidental source paths and editable imports.
sys.path.insert(0, sys.argv[3])
class AnalysisReached(Exception): pass
captured = []
def capture_analysis(*args, **kwargs):
    captured.extend(kwargs['datas'])
    raise AnalysisReached
try:
    runpy.run_path(sys.argv[1], init_globals={'SPEC': sys.argv[2], 'Analysis': capture_analysis})
except AnalysisReached:
    pass
print(json.dumps(captured))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(ROOT / "LocalChatAnalyzer.spec"),
         str(project_root / "LocalChatAnalyzer.spec"),
         str(importlib.metadata.distribution("qq-chat-analyzer").locate_file(""))],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def test_desktop_startup_version_matches_release_version():
    from qq_chat_analyzer.gui.app import APP_VERSION

    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert APP_VERSION == project["project"]["version"]


@pytest.mark.slow_integration
def test_desktop_spec_ships_release_metadata_for_runtime_version():
    datas = _spec_datas(ROOT)
    metadata_dirs = [
        Path(source)
        for source, target in datas
        if target.endswith((".dist-info", ".egg-info"))
    ]
    distributions = [
        importlib.metadata.PathDistribution(path) for path in metadata_dirs
        if importlib.metadata.PathDistribution(path).metadata["Name"] == "qq-chat-analyzer"
    ]
    assert len(distributions) == 1
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert distributions[0].version == project["project"]["version"]


@pytest.mark.slow_integration
def test_desktop_build_rejects_stale_installed_release_metadata(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "99.0.0"\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="version"):
        _spec_datas(tmp_path)
