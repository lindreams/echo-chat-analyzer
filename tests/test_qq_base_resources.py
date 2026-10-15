"""Base-package regressions with fictional installations and native resources."""
import json
from pathlib import Path

import pytest

from qq_chat_analyzer.application.qq import qq_auth_bridge as bridge
from test_qq_auth_bridge import _FakeProcess, _launch_target, _runtime_config


def _base(root, version="9.9.36-53644", build="53644"):
    config = _runtime_config(root)
    app = config.qq_install_path.parent / "resources/app"
    (app / "package.json").write_text(json.dumps({
        "name": "qq-chat", "version": version, "buildVersion": build, "main": "index.js",
    }))
    (app / "wrapper.node").write_bytes(b"fictional base native")
    return config, app


@pytest.mark.parametrize("version,build,code", [
    ("9.9.19-35469", "35469", "qq_version_too_old"),
    ("9.9.36-53644", "35469", "qq_version_metadata_conflict"),
])
def test_audit_cases_reject_before_launch_or_credential(tmp_path, monkeypatch, caplog, version, build, code):
    config, _ = _base(tmp_path, version, build)
    monkeypatch.setattr(bridge, "read_qq_version", lambda _: (9, 9, 36, 53644))
    monkeypatch.setattr(*_launch_target(bridge), lambda *a, **k: pytest.fail("must not launch"))
    class Credential:
        def begin_launch(self): pytest.fail("must not mint credential")
    with caplog.at_level("DEBUG"), pytest.raises(bridge.QQAuthWindowUnavailable) as error:
        bridge.default_auth_window_launcher(config, credential=Credential())()
    assert error.value.code == code
    assert str(tmp_path) not in str(error.value) + caplog.text
    assert not (tmp_path / "loadNapCat.js").exists()
    assert not (tmp_path / "qqnt.echo.json").exists()


@pytest.mark.parametrize("version,build", [("9.9.36-53644", "53644"), ("9.9.36", "53644")])
def test_base_version_and_wrapper_are_pinned_to_the_launch(tmp_path, monkeypatch, version, build):
    config, app = _base(tmp_path, version, build)
    monkeypatch.setattr(bridge, "read_qq_version", lambda _: (9, 9, 19, 35469))
    # A pending tree without an active config is not this installation's target.
    pending = tmp_path / "versions/9.9.99-65535/resources/app"
    pending.mkdir(parents=True)
    (pending / "package.json").write_text('{"version":"9.9.99-65535","buildVersion":"65535"}')
    (pending / "wrapper.node").write_bytes(b"fictional pending native")
    launches = []
    monkeypatch.setattr(*_launch_target(bridge), lambda command, **options: launches.append((command, options)) or _FakeProcess(4243))
    bridge.default_auth_window_launcher(config)()
    command, options = launches[0]
    env = options["env"]
    assert command[1] == str(config.qq_install_path.resolve())
    info = json.loads(Path(env["NAPCAT_QQ_PACKAGE_INFO_PATH"]).read_text())
    assert info["version"] == info["curVersion"] == "9.9.36-53644"
    assert str(info["buildVersion"]) == "53644"
    assert env["NAPCAT_QQ_VERSION_CONFIG_PATH"] == env["NAPCAT_PATCH_PACKAGE"]
    assert Path(env["NAPCAT_WRAPPER_PATH"]) == (app / "wrapper.node").resolve()


@pytest.mark.parametrize("info", [
    {"version": "newest", "buildVersion": "53644"},
    {"buildVersion": "53644"},
    {"version": "9.9.36-53644", "buildVersion": True},
])
def test_unidentifiable_fields_do_not_fall_back_to_new_pe(tmp_path, monkeypatch, info):
    config, app = _base(tmp_path)
    (app / "package.json").write_text(json.dumps(info))
    monkeypatch.setattr(bridge, "read_qq_version", lambda _: (9, 9, 36, 53644))
    assert bridge._known_qq_version(config.qq_install_path) is None
    with pytest.raises(bridge.QQAuthWindowUnavailable) as error: bridge.default_auth_window_launcher(config)
    assert error.value.code == "qq_resources_unverified"


@pytest.mark.parametrize("pe_build", [35469, 53644])
def test_absent_metadata_cannot_launch_using_napcat_default_version(tmp_path, monkeypatch, pe_build):
    config = _runtime_config(tmp_path)
    (tmp_path / "resources/app/package.json").write_text('{"name":"QQ","main":"index.js"}')
    monkeypatch.setattr(bridge, "read_qq_version", lambda _: (9, 9, 36, pe_build))
    class Credential:
        def begin_launch(self): pytest.fail("must not mint credential")
    monkeypatch.setattr(*_launch_target(bridge), lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(bridge.QQAuthWindowUnavailable) as error:
        bridge.default_auth_window_launcher(config, credential=Credential())()
    assert error.value.code == "qq_resources_unverified"


def test_missing_base_native_is_rejected_before_credentials(tmp_path, monkeypatch):
    config, app = _base(tmp_path)
    (app / "wrapper.node").unlink()
    class Credential:
        def begin_launch(self): pytest.fail("must not mint credential")
    monkeypatch.setattr(*_launch_target(bridge), lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(bridge.QQAuthWindowUnavailable): bridge.default_auth_window_launcher(config, credential=Credential())()


def test_changed_base_resources_require_retry(tmp_path, monkeypatch):
    config, app = _base(tmp_path)
    launcher = bridge.default_auth_window_launcher(config)
    (app / "wrapper.node").write_bytes(b"fictional changed base native resource")
    monkeypatch.setattr(*_launch_target(bridge), lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(bridge.QQAuthWindowUnavailable) as error: launcher()
    assert error.value.code == "qq_resources_changed"


def test_package_appearing_after_check_cannot_skip_old_version_gate(tmp_path, monkeypatch):
    config = _runtime_config(tmp_path)
    app = config.qq_install_path.parent / "resources/app"
    (app / "package.json").unlink()
    monkeypatch.setattr(bridge, "read_qq_version", lambda _: (9, 9, 36, 53644))
    class Credential:
        def begin_launch(self): pytest.fail("must not mint credential")
    launcher = bridge.default_auth_window_launcher(config, credential=Credential())
    (app / "package.json").write_text('{"version":"9.9.19-35469","buildVersion":"35469"}')
    (app / "wrapper.node").write_bytes(b"fictional old native")
    monkeypatch.setattr(*_launch_target(bridge), lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(bridge.QQAuthWindowUnavailable) as error: launcher()
    assert error.value.code == "qq_version_too_old"


@pytest.mark.slow_integration
def test_pinned_napcat_uses_validated_base_version_and_wrapper(tmp_path, monkeypatch):
    import hashlib
    import os
    import subprocess
    import zipfile

    project = Path(__file__).resolve().parents[1]
    archive = os.environ.get("ECHO_NAPCAT_AUDIT_ARCHIVE")
    node = project / "runtime/wechat/node.exe"
    if not archive or not node.is_file():
        pytest.skip("requires pinned NapCat audit archive and verified bundled Node")
    pins = json.loads((project / "scripts/qq_napcat_runtime_pins.json").read_text())
    assert hashlib.sha256(Path(archive).read_bytes()).hexdigest() == pins["upstream"]["archiveSha256"]
    with zipfile.ZipFile(archive) as bundle: source = bundle.read("napcat.mjs")
    assert hashlib.sha256(source).hexdigest() == pins["napcatPatch"]["upstreamSha256"]
    source = source.decode()
    functions = "\n".join(source[source.index(start):source.index(end)] for start, end in (
        ("function uQ(", "function Kw("), ("function Dae(", "function Oae("),
        ("class Pae ", "var LA ="),
    ))
    config, app = _base(tmp_path)
    monkeypatch.setattr(bridge, "read_qq_version", lambda _: (9, 9, 19, 35469))
    launches = []
    monkeypatch.setattr(*_launch_target(bridge), lambda *a, **k: launches.append(k["env"]) or _FakeProcess(4243))
    bridge.default_auth_window_launcher(config)()
    script = "const xe=require('path'), fe=require('fs'), $e=fe, dt=require('os'); const zN=p=>p;\n" + functions
    script += "\nprocess.execPath=" + json.dumps(str(config.qq_install_path)) + ";"
    script += "Pae.prototype.getAppidV2=()=>({appid:1,qua:'fictional'});"
    script += "const selected=new Pae({}); const cfg=process.env.NAPCAT_QQ_VERSION_CONFIG_PATH;"
    script += "delete process.env.NAPCAT_QQ_VERSION_CONFIG_PATH; const fallback=new Pae({});"
    script += "console.log(JSON.stringify({version:selected.getFullQQVersion(),build:selected.getQQBuildStr(),package:selected.QQPackageInfo.version,wrapper:Dae(selected.QQMainPath,selected.getFullQQVersion()),fallbackBuild:fallback.getQQBuildStr()}));"
    result = subprocess.run([str(node), "-e", script], env=launches[0], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    info = json.loads(result.stdout)
    assert info["version"] == info["package"] == "9.9.36-53644"
    assert info["build"] == "53644"
    assert info["fallbackBuild"] == "28131"
    assert Path(info["wrapper"]) == (app / "wrapper.node").resolve()
