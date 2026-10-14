"""Fictional installations only; never execute a real Update.exe."""
from pathlib import Path

import pytest

from qq_chat_analyzer.application.facade import ChatAnalyzerFacade
from qq_chat_analyzer.version import APP_VERSION
from test_update_install_handoff import evidence


def installation(tmp_path):
    from qq_chat_analyzer.application.setup_uninstall_service import SetupUninstallService
    root = tmp_path / "Fictional Echo"
    current = root / "current"
    current.mkdir(parents=True)
    executable = current / "Echo.exe"
    executable.write_bytes(b"fictional Echo")
    (root / "Update.exe").write_bytes(b"fictional Velopack")
    (current / "sq.version").write_text(
        f'<package><metadata><id>Echo.Test</id><version>{APP_VERSION}</version>'
        '<channel>win-x64-test</channel><mainExe>Echo.exe</mainExe>'
        '<title>Echo</title></metadata></package>', encoding="utf-8")
    data = tmp_path / "independent-data"
    data.mkdir()
    (data / "report.html").write_bytes(b"fictional report")
    (data / "config.json").write_bytes(b'{}')
    registration = {
        "InstallLocation": str(root), "DisplayVersion": APP_VERSION,
        "DisplayIcon": str(executable), "DisplayName": "Echo",
        "UninstallString": f'"{root / "Update.exe"}" --uninstall',
    }
    calls = []
    service = SetupUninstallService(
        executable=lambda: executable, setup_runtime=lambda: True,
        data_root=lambda: data, registration=lambda package_id: registration if package_id == 'Echo.Test' else {},
        updater_version=lambda path: (1, 2, 161),
        launcher=lambda snapshot: calls.append(snapshot),
    )
    return service, root, data, registration, calls


def test_valid_setup_requires_confirmation_and_final_shutdown(tmp_path):
    service, root, data, _, calls = installation(tmp_path)
    before = {p.name: p.read_bytes() for p in data.iterdir()}
    assert service.is_available()
    prepared = service.prepare()
    assert prepared.status == "ready" and prepared.token
    assert calls == []
    assert service.handoff(prepared.token, evidence()).status == "started"
    assert len(calls) == 1 and calls[0].updater == root / "Update.exe"
    assert service.handoff(prepared.token, evidence()).status == "denied"
    assert before == {p.name: p.read_bytes() for p in data.iterdir()}


@pytest.mark.parametrize("damage", ["source", "portable", "missing", "wrong_root",
    "wrong_command", "wrong_version", "wrong_exe", "manifest", "updater_version", "data_overlap", "msi",
    "foreign_id", "portable_layout", "missing_registration"])
def test_invalid_installations_are_inert(tmp_path, damage):
    service, root, data, registration, calls = installation(tmp_path)
    if damage == "source":
        service._setup_runtime = lambda: False
    elif damage == "portable":
        (root / ".portable").touch()
    elif damage == "missing":
        (root / "Update.exe").unlink()
    elif damage == "wrong_root":
        registration["InstallLocation"] = str(tmp_path / "another-install")
    elif damage == "wrong_command":
        registration["UninstallString"] += " --rootDir elsewhere"
    elif damage == "wrong_version":
        registration["DisplayVersion"] = "9.9.9"
    elif damage == "wrong_exe":
        registration["DisplayIcon"] = str(root / "other.exe")
    elif damage == "manifest":
        (root / "current" / "sq.version").write_bytes(b"bad xml")
    elif damage == "updater_version":
        service._updater_version = lambda path: (9, 9, 9)
    elif damage == "msi":
        (root / '.msi-installed').touch()
    elif damage == 'foreign_id':
        manifest = root / 'current' / 'sq.version'
        manifest.write_text(manifest.read_text().replace('Echo.Test', 'Other.App'), encoding='utf-8')
    elif damage == 'portable_layout':
        service._executable = lambda: root / 'Echo.exe'
    elif damage == 'missing_registration':
        registration.clear()
    else:
        service._data_root = lambda: root / "reports"
    assert not service.is_available()
    assert service.prepare().status == "denied"
    assert calls == []
    assert (data / "report.html").read_bytes() == b"fictional report"


@pytest.mark.parametrize("damage", ["bytes", "registration", "shutdown", "spawn"])
def test_handoff_revalidates_and_never_claims_success_on_failure(tmp_path, damage):
    service, root, _, registration, calls = installation(tmp_path)
    prepared = service.prepare()
    proof = evidence()
    if damage == "bytes":
        (root / "Update.exe").write_bytes(b"replaced updater")
    elif damage == "registration":
        registration["DisplayName"] = "Other app"
    elif damage == "shutdown":
        proof = type(proof)(proof.steps[:-1])
    else:
        def fail(snapshot):
            raise OSError("fictional launch failure")
        service._launcher = fail
    assert service.handoff(prepared.token, proof).status in ("denied", "failed")
    assert service.handoff(prepared.token, evidence()).status == "denied"
    assert calls == []


def test_facade_needs_its_own_shutdown_evidence(tmp_path):
    service, _, _, _, calls = installation(tmp_path)
    assert hasattr(ChatAnalyzerFacade, "prepare_setup_uninstall")
    facade = ChatAnalyzerFacade(setup_uninstall_service=service)
    prepared = facade.prepare_setup_uninstall()
    assert facade.handoff_setup_uninstall(prepared.token, evidence()).status == "denied"
    assert calls == []
    own = facade.shutdown()
    from qq_chat_analyzer.application.shutdown_models import ShutdownResult, ShutdownStepResult, ShutdownStatus
    final = ShutdownResult(own.steps + (ShutdownStepResult("gui_workers", ShutdownStatus.SUCCESS),))
    assert facade.handoff_setup_uninstall(prepared.token, final).status == "started"


@pytest.mark.slow_integration
def test_junction_in_current_installation_is_rejected(tmp_path):
    import os
    import subprocess
    import sys
    if sys.platform != 'win32':
        pytest.skip('Windows junction')
    service, root, _, _, calls = installation(tmp_path)
    link = tmp_path / 'linked-install'
    result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(root)],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
    assert result.returncode == 0
    try:
        service._executable = lambda: link / 'current' / 'Echo.exe'
        assert not service.is_available() and service.prepare().status == 'denied'
        assert calls == []
    finally:
        os.rmdir(link)  # Remove this test-created junction, never its target.
