"""Fictional QQ quick-update installations; never inspect a real user install."""
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from qq_chat_analyzer.application.qq import qq_auth_bridge as bridge
from test_qq_auth_bridge import _FakeProcess, _launch_target, _runtime_config


def _active(executable, version="9.9.36-53644", *, alternate=False):
    root = executable.parent / ("resources/app/versions" if alternate else "versions")
    app = root / version / ("" if alternate else "resources/app")
    app.mkdir(parents=True, exist_ok=True)
    package = app / "package.json"
    package.write_text(json.dumps({"name": "qq-chat", "version": version,
                                  "buildVersion": version.split("-")[1], "main": "index.js"}))
    for name in ("wrapper.node", "major.node"):
        (app / name).write_bytes(b"fictional native resource")
    config = root / "config.json"
    config.write_text(json.dumps({"curVersion": version, "readyVersion": "9.9.99-65535"}))
    return config, package


@pytest.mark.parametrize("alternate", [False, True])
def test_active_resources_launch_the_selected_package(tmp_path, monkeypatch, alternate):
    config = _runtime_config(tmp_path)
    version_config, package = _active(config.qq_install_path, alternate=alternate)
    # A newer pending package (and mtime) must not override curVersion.
    _, pending = _active(config.qq_install_path, "9.9.99-65535", alternate=alternate)
    version_config.write_text(json.dumps({"curVersion": "9.9.36-53644", "readyVersion": "9.9.99-65535"}))
    os.utime(pending, (2000000000, 2000000000))
    launches = []
    monkeypatch.setattr(*_launch_target(bridge), lambda command, **options: launches.append((command, options)) or _FakeProcess(4243))
    for key in ("NAPCAT_QQ_PACKAGE_INFO_PATH", "NAPCAT_QQ_VERSION_CONFIG_PATH", "NAPCAT_WRAPPER_PATH"):
        monkeypatch.setenv(key, "fictional-unrelated-install")
    bridge.default_auth_window_launcher(config)()
    command, options = launches[0]
    assert command[1] == str(config.qq_install_path.resolve())
    env = options["env"]
    patched = json.loads(Path(env["NAPCAT_PATCH_PACKAGE"]).read_text())
    assert patched["version"] == "9.9.36-53644"
    assert json.loads(Path(env["NAPCAT_QQ_VERSION_CONFIG_PATH"]).read_text())["curVersion"] == patched["version"]
    assert json.loads(Path(env["NAPCAT_QQ_PACKAGE_INFO_PATH"]).read_text())["version"] == patched["version"]
    assert Path(env["NAPCAT_WRAPPER_PATH"]) == (package.parent / "wrapper.node").resolve()


def test_old_current_resources_are_blocked_even_with_ready_new_version(tmp_path, monkeypatch, caplog):
    config = _runtime_config(tmp_path)
    current, _ = _active(config.qq_install_path, "9.9.19-35469")
    _active(config.qq_install_path)
    current.write_text(json.dumps({"curVersion": "9.9.19-35469", "readyVersion": "9.9.36-53644"}))
    monkeypatch.setattr(*_launch_target(bridge), lambda *a, **k: pytest.fail("old resources must not launch"))
    with caplog.at_level("DEBUG"), pytest.raises(bridge.QQAuthWindowUnavailable) as error:
        bridge.default_auth_window_launcher(config)
    assert error.value.code == "qq_version_too_old"
    assert "35469" in str(error.value)
    assert str(tmp_path) not in str(error.value) + caplog.text


@pytest.mark.parametrize("fault", ["json", "traversal", "package_version", "native", "duplicate", "config_directory", "escape"])
def test_invalid_active_resources_never_claim_compatibility_or_launch(tmp_path, monkeypatch, caplog, fault):
    config = _runtime_config(tmp_path)
    active, package = _active(config.qq_install_path)
    if fault == "json": active.write_text("{invalid fictional-account")
    if fault == "traversal": active.write_text('{"curVersion":"../9.9.36-53644"}')
    if fault == "package_version": package.write_text('{"version":"9.9.19-35469","buildVersion":"35469"}')
    if fault == "native": (package.parent / "wrapper.node").unlink()
    if fault == "duplicate": active.write_text('{"curVersion":"9.9.19-35469","curVersion":"9.9.36-53644"}')
    if fault == "config_directory": active.unlink(); active.mkdir()
    if fault == "escape":
        outside = tmp_path.parent / (tmp_path.name + "-outside.node")
        outside.write_bytes(b"fictional external resource")
        original = Path.resolve
        monkeypatch.setattr(Path, "resolve", lambda p, *a, **k: outside if p == package.parent / "wrapper.node" else original(p, *a, **k))
    monkeypatch.setattr(*_launch_target(bridge), lambda *a, **k: pytest.fail("invalid resources must not launch"))
    with caplog.at_level("DEBUG"), pytest.raises(bridge.QQAuthWindowUnavailable) as error:
        bridge.default_auth_window_launcher(config)()
    assert error.value.code != "qq_version_too_old"
    assert str(tmp_path) not in str(error.value) + caplog.text
    assert "fictional-account" not in str(error.value) + caplog.text


def test_no_config_does_not_adopt_unselected_new_directory(tmp_path, monkeypatch):
    config = _runtime_config(tmp_path)
    active, _ = _active(config.qq_install_path)
    active.unlink()
    (tmp_path / "resources/app/package.json").write_text('{"version":"9.9.19-35469","buildVersion":"35469"}')
    with pytest.raises(bridge.QQAuthWindowUnavailable) as error:
        bridge.default_auth_window_launcher(config)
    assert error.value.code == "qq_version_too_old"


def test_multi_install_selection_uses_active_resources_and_respects_manual_choice(tmp_path, monkeypatch):
    config = _runtime_config(tmp_path)
    old = config.qq_install_path
    new = tmp_path / "updated/QQ.exe"
    new.parent.mkdir(); new.write_bytes(b"fictional")
    _active(old, "9.9.19-35469")
    _active(new)
    monkeypatch.setattr(bridge, "_qq_install_candidates", lambda: [old, new, new])
    assert bridge.resolve_qq_install_path(replace(config, qq_install_path_explicit=False), tmp_path) == new
    assert bridge.resolve_qq_install_path(config, tmp_path) == old


def test_changed_current_version_between_check_and_launch_requires_retry(tmp_path, monkeypatch):
    config = _runtime_config(tmp_path)
    active, _ = _active(config.qq_install_path)
    launcher = bridge.default_auth_window_launcher(config)
    _active(config.qq_install_path, "9.9.19-35469")
    monkeypatch.setattr(*_launch_target(bridge), lambda *a, **k: pytest.fail("changed resources must not launch"))
    with pytest.raises(bridge.QQAuthWindowUnavailable): launcher()
    with pytest.raises(bridge.QQAuthWindowUnavailable) as error: bridge.default_auth_window_launcher(config)
    assert error.value.code == "qq_version_too_old"


@pytest.mark.parametrize("first", ["9.9.19-35469", "9.9.36-53644"])
def test_cancel_during_resource_check_and_retry_after_update(tmp_path, monkeypatch, first):
    import threading
    from test_qq_version_gate import _auth, _connection_module

    instance, config = _auth(tmp_path)
    _active(config.qq_install_path, first)
    cancelled = threading.Event()
    read = bridge.read_qq_resources
    calls = []

    def cancel_on_first(path):
        result = read(path)
        calls.append(path)
        if len(calls) == 1:
            cancelled.set()
        return result

    monkeypatch.setattr(bridge, "find_conflicting_qq_pids", lambda _: [])
    monkeypatch.setattr(bridge, "read_qq_resources", cancel_on_first)
    launched = []
    monkeypatch.setattr(*_launch_target(bridge), lambda *a, **k: launched.append(True) or _FakeProcess(4243))
    assert instance.start_auth_flow(cancel_event=cancelled).code == "qq_auth_cancelled"
    assert not launched
    _active(config.qq_install_path)
    assert instance.start_auth_flow(cancel_event=threading.Event()).state is _connection_module().ConnectionState.WAITING_AUTH
    assert launched == [True]


@pytest.mark.parametrize("change", ["package", "wrapper", "executable"])
def test_captured_resources_cannot_change_before_launch(tmp_path, monkeypatch, change):
    config = _runtime_config(tmp_path)
    _, package = _active(config.qq_install_path)
    launcher = bridge.default_auth_window_launcher(config)
    target = {"package": package, "wrapper": package.parent / "wrapper.node", "executable": config.qq_install_path}[change]
    if change == "package":
        info = json.loads(target.read_text()); info["main"] = "other.js"
        target.write_text(json.dumps(info))
    else:
        target.write_bytes(b"fictional changed resource, different size")
    monkeypatch.setattr(*_launch_target(bridge), lambda *a, **k: pytest.fail("changed resources must not launch"))
    with pytest.raises(bridge.QQAuthWindowUnavailable) as error: launcher()
    assert error.value.code == "qq_resources_changed"


@pytest.mark.slow_integration
@pytest.mark.parametrize("alternate", [False, True])
def test_pinned_napcat_lookup_agrees_with_checked_launch_resources(tmp_path, monkeypatch, alternate):
    """Execute the real pinned lookup functions with fake native loading."""
    import hashlib
    import subprocess
    import zipfile

    project = Path(__file__).resolve().parents[1]
    archive = os.environ.get("ECHO_NAPCAT_AUDIT_ARCHIVE")
    node = project / "runtime/wechat/node.exe"
    if not archive or not node.is_file():
        pytest.skip("requires pinned NapCat audit archive and verified bundled Node")
    pins = json.loads((project / "scripts/qq_napcat_runtime_pins.json").read_text())
    data = Path(archive).read_bytes()
    assert hashlib.sha256(data).hexdigest() == pins["upstream"]["archiveSha256"]
    with zipfile.ZipFile(archive) as bundle:
        source = bundle.read("napcat.mjs")
    assert hashlib.sha256(source).hexdigest() == pins["napcatPatch"]["upstreamSha256"]
    source = source.decode()
    functions = "\n".join(source[source.index(start):source.index(end)] for start, end in (
        ("function lQ(", "function pQ("), ("function pQ(", "function Kw("),
        ("function Dae(", "function Oae("), ("function Oae(", "class I0 "),
    ))
    config = _runtime_config(tmp_path)
    _, package = _active(config.qq_install_path, alternate=alternate)
    launches = []
    monkeypatch.setattr(*_launch_target(bridge), lambda command, **options: launches.append(options) or _FakeProcess(4243))
    bridge.default_auth_window_launcher(config)()
    env = launches[0]["env"]
    script = "const xe=require('path'), fe=require('fs'), $e=fe, dt=require('os'); const zN=p=>p;\n" + functions
    script += "\nconst exe=" + json.dumps(str(config.qq_install_path)) + ";"
    script += "const cfg=JSON.parse(fe.readFileSync(pQ(exe))); const pkg=lQ(exe,cfg.curVersion);"
    script += "const wrapper=Dae(exe,cfg.curVersion); delete process.env.NAPCAT_WRAPPER_PATH;"
    script += "console.log(JSON.stringify({version:cfg.curVersion,package:JSON.parse(fe.readFileSync(pkg)).version,wrapper,defaultWrapper:Dae(exe,cfg.curVersion),major:Oae(exe,cfg.curVersion)}));"
    result = subprocess.run([str(node), "-e", script], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    lookup = json.loads(result.stdout)
    assert lookup["version"] == lookup["package"] == "9.9.36-53644"
    assert Path(lookup["wrapper"]) == Path(lookup["defaultWrapper"]) == (package.parent / "wrapper.node").resolve()
    assert Path(lookup["major"]) == (package.parent / "major.node").resolve()
