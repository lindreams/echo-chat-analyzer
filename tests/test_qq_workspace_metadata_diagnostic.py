"""Windows subprocess checks using only fictional release and user trees."""
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/diagnose_qq_workspace_rc6.ps1"
COMPONENT = "61c2be90548a0a77080c9099731e24dcb1ad50790f530ad5ad06ef4cc996c019"
STAGES = {"input", "release", "workspace", "ownership", "staging", "lease", "diagnostic", "summary"}
CODES = {
    "reparse_point", "member_kind_invalid", "metadata_access_failed", "input_invalid",
    "release_resource_missing", "release_directory_empty", "release_hashes_unverified",
    "workspace_missing", "owner_missing", "ownership_content_unverified",
    "staging_conflict", "staging_present_unverified", "lease_missing",
    "lease_content_and_lock_unverified", "hardlinks_and_identity_unverified",
    "inspection_limit_unverified", "metadata_changed", "member_unknown",
    "pinned_asset_missing", "metadata_check_failed", "metadata_shape_valid_content_unverified",
    "concurrent_replacement_unverified",
    "publication_incomplete_unverified",
}
pytestmark = [pytest.mark.slow_integration, pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell")]


@pytest.fixture
def trees(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("e6")
    release = tmp_path / "fictional release secret-account-987654"
    local = tmp_path / "token-super-secret"
    manifest = json.loads((ROOT / "scripts/windows_runtime_manifest.json").read_text())
    excluded = set(manifest["portableExcludedFiles"])
    for entry in manifest["requirements"]:
        if not entry["path"].startswith("qq-napcat-candidate/") or entry["path"] in excluded:
            continue
        path = release / "runtime" / entry["path"]
        if entry["type"] != "file":
            path.mkdir(parents=True, exist_ok=True)
            (path / "fictional-entry").write_bytes(b"fictional release")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fictional release")
    for name in ["Echo.exe", "scripts/windows_runtime_manifest.json", "scripts/qq_napcat_runtime_pins.json"]:
        path = release / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not JSON: private-body-canary")
    qq = local / "LocalChatAnalyzer/runtime/qq"
    work = qq / COMPONENT
    pins = json.loads((ROOT / "scripts/qq_napcat_runtime_pins.json").read_text())
    names = [entry["target"] for entry in pins["templates"]]
    names += ["config/plugins/napcat-plugin-echo/config.json", "logs/account-secret.log", "cache/chat-secret.db", "loadNapCat.js", "qqnt.echo.json"]
    for name in names:
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"private-body-canary token-super-secret")
    (qq / (COMPONENT + ".owner.json")).write_bytes(b"not JSON: private-body-canary")
    (qq / ("." + COMPONENT + ".prepare.lock")).write_bytes(b"bad-header")
    return release, local, qq, work


def run(trees, script=SCRIPT, *, include_rows=False):
    assert script.is_file(), "standalone RC6 metadata diagnostic is missing"
    release, local, _, _ = trees
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(local)
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), "-ReleaseDirectory", str(release)], env=env, capture_output=True, text=True, timeout=30)
    assert result.stderr == ""
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert rows
    for row in rows:
        fields = {"stage", "code", "ok", "verified"}
        if row["code"] == "member_unknown":
            fields |= {"location_category", "member_kind"}
            assert row.get("location_category") in {"workspace_root", "plugin_container", "echo_plugin", "other"}
            assert row.get("member_kind") in {"file", "directory", "other"}
        assert set(row) == fields
        assert row["stage"] in STAGES
        assert row["code"] in CODES
        assert type(row["ok"]) is bool and type(row["verified"]) is bool
    assert all(secret not in result.stdout for secret in [str(release), str(local), "987654", "super-secret", "private-body-canary", "chat-secret", ".json", ".lock"])
    return result.returncode, rows if include_rows else {(r["stage"], r["code"]) for r in rows}


@pytest.mark.parametrize("name,kind,location", [
    ("private-unknown-account", "file", "workspace_root"),
    ("plugins/private-unknown-account", "file", "plugin_container"),
    ("plugins/napcat-plugin-echo/private-unknown-account", "file", "echo_plugin"),
    ("loadNapCat.js", "directory", "workspace_root"),
    ("plugins/napcat-plugin-echo/index.mjs", "directory", "echo_plugin"),
])
def test_unknown_classification_matches_inspect_and_does_not_enter_unknown_directory(trees, name, kind, location):
    from qq_chat_analyzer.application.qq import qq_runtime_workspace as workspace
    path = trees[3] / name
    if path.exists():
        path.unlink()  # Fictional fixture only.
    if kind == "directory":
        path.mkdir()
        # Entering this directory would emit an extra member_unknown event.
        (path / "private-body-canary").write_bytes(b"token-super-secret")
    else:
        path.write_bytes(b"private-body-canary token-super-secret")
    pins = json.loads((ROOT / "scripts/qq_napcat_runtime_pins.json").read_text())
    files = {entry["target"]: entry["sha256"] for entry in pins["templates"]}
    with pytest.raises(workspace.QQWorkspaceError):
        workspace._inspect(trees[3], files, complete=False, runtime_state=True)
    code, rows = run(trees, include_rows=True)
    unknown = [r for r in rows if r["code"] == "member_unknown"]
    assert code == 1 and len(unknown) == 1
    assert unknown[0] == {"stage": "workspace", "code": "member_unknown", "ok": False,
                          "verified": True, "location_category": location, "member_kind": kind}
    assert not any(r["code"] == "reparse_point" for r in rows)


def test_other_metadata_kind_is_redacted_with_fixed_fallback(trees, tmp_path, monkeypatch):
    import stat
    from types import SimpleNamespace
    from qq_chat_analyzer.application.qq import qq_runtime_workspace as workspace
    path = trees[3] / "cache/private-unknown-account"
    path.write_bytes(b"private-body-canary")
    real_lstat = Path.lstat
    def fictional_other(item, *args, **kwargs):
        if item == path:
            return SimpleNamespace(st_mode=stat.S_IFIFO, st_file_attributes=0, st_nlink=1)
        return real_lstat(item, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", fictional_other)
        with pytest.raises(workspace.QQWorkspaceError):
            workspace._inspect(trees[3], {}, complete=False, runtime_state=True)
    source = SCRIPT.read_text(encoding="utf-8")
    anchor = "$kind = Get-SafeMetadata $child 'workspace'"
    assert anchor in source
    source = source.replace(anchor, anchor + "\n                    if ($child.EndsWith('private-unknown-account')) { $kind = 'other' }")
    simulated = tmp_path / "fictional-other.ps1"
    simulated.write_text(source, encoding="utf-8-sig")
    code, rows = run(trees, simulated, include_rows=True)
    unknown = [r for r in rows if r["code"] == "member_unknown"]
    assert code == 1 and len(unknown) == 1
    assert unknown[0]["location_category"] == "other" and unknown[0]["member_kind"] == "other"


@pytest.mark.parametrize("location", ["workspace", "release", "ancestor"])
def test_junctions_are_refused_without_enumerating_target(trees, tmp_path, location):
    outside = tmp_path / "fictional other application"
    outside.mkdir()
    (outside / "private-body-canary").write_bytes(b"secret")
    if location == "workspace":
        junction = trees[3] / "cache/linked"
    elif location == "release":
        junction = trees[0] / "runtime/qq-napcat-candidate/native/linked"
        # Only trusted release paths are inspected, so replace a required directory.
        junction = trees[0] / "runtime/qq-napcat-candidate/static"
        (junction / "fictional-entry").unlink()
        junction.rmdir()
    else:
        junction = tmp_path / "fictional linked local"
        trees = (trees[0], junction, trees[2], trees[3])
    made = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True)
    assert made.returncode == 0
    try:
        code, events = run(trees)
        assert code == 1 and any(c == "reparse_point" for _, c in events), events
        assert not any(c == "member_unknown" for _, c in events)
    finally:
        junction.rmdir()  # Test-created junction only; never remove its target.


def test_metadata_exception_is_redacted(trees, tmp_path):
    assert SCRIPT.is_file(), "standalone RC6 metadata diagnostic is missing"
    source = SCRIPT.read_text(encoding="utf-8")
    anchor = "[IO.File]::GetAttributes($Path)"
    assert anchor in source
    source = source.replace(anchor, "$(throw 'private-body-canary token-super-secret')")
    simulated = tmp_path / "fictional-failure.ps1"
    simulated.write_text(source, encoding="utf-8-sig")
    code, events = run(trees, simulated)
    assert code == 1 and any(c == "metadata_access_failed" for _, c in events), events


def test_private_files_cannot_be_opened_for_content(trees):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handles = []
    try:
        for path in trees[1].rglob("*"):
            if path.is_file():
                handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0, None)
                assert handle != wintypes.HANDLE(-1).value, ctypes.get_last_error()
                handles.append(handle)
        code, events = run(trees)
        assert code == 0 and ("summary", "metadata_shape_valid_content_unverified") in events
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)


@pytest.mark.parametrize("value", ["relative-private-body-canary", r"\\private-body-canary\share"])
def test_invalid_input_does_not_scan_or_echo_it(trees, value):
    code, events = run((Path(value), *trees[1:]))
    assert code == 1
    assert events == {("input", "input_invalid"), ("summary", "metadata_check_failed")}
