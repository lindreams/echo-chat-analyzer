"""Check shared test isolation in a child pytest with a guarded fake user."""

from pathlib import Path

import pytest

pytest_plugins = ("pytester",)


@pytest.mark.slow_integration
def test_user_data_isolation(pytester, monkeypatch):
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    sentinel = pytester.path / "untouched-user"
    for variable in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME",
                     "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        monkeypatch.setenv(variable, str(sentinel))
    shared = Path(__file__).with_name("conftest.py")
    isolation = shared.read_text(encoding="utf-8") if shared.exists() else ""
    pytester.makeconftest("from pathlib import Path\nimport pytest\n" + isolation + f'''

# Reuse the isolation fixtures, not the repository's domain/Smoke inventory:
# this child project contains only the two synthetic isolation cases below.
del pytest_collection_modifyitems

@pytest.fixture(autouse=True)
def guard_unisolated_user_directory(monkeypatch):
    original = Path.mkdir
    sentinel = Path({str(sentinel)!r})
    def guarded(path, *args, **kwargs):
        if path == sentinel or sentinel in path.parents:
            raise AssertionError("Unisolated access to sentinel user directory")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "mkdir", guarded)
''')
    pytester.makepyfile('''
from pathlib import Path
import pytest
from qq_chat_analyzer.application.echo_report_export import package_echo_report
from qq_chat_analyzer.gui.app import build_facade
from qq_chat_analyzer.resources import user_data_dir

@pytest.mark.parametrize("fallback", [False, True])
def test_io(tmp_path, monkeypatch, fallback):
    if fallback:
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
    root = user_data_dir()
    assert root.is_relative_to(tmp_path)
    assert Path.home().is_relative_to(tmp_path)
    source = tmp_path / "fictional-source"
    source.mkdir()
    for name in ("echo-report.html", "echo-report.json"):
        (source / name).write_text("fictional", encoding="utf-8")
    metadata = {
        "schema_version": "echo-report-meta.v1",
        "generated_at": "2026-10-04T12:00:00+00:00",
        "source": "qq", "conversation_name": "Fictional",
        "message_count": 1,
        "analysis_scope": {"mode": "all", "start_date": None, "end_date": None},
    }
    package = package_echo_report(source, metadata=metadata)
    assert package.parent == root / "reports"
    facade = build_facade()
    assert len(facade.list_report_packages().reports) == 1
    assert facade.delete_report_packages([package.name]).complete
    assert not package.exists()
''')
    result = pytester.runpytest_subprocess("-q", timeout=60)
    result.assert_outcomes(passed=2)
    assert not sentinel.exists()
