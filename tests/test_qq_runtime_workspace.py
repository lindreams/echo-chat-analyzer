"""Prepare only fictional Echo plugin assets, with owned recovery and leases."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import threading

import pytest

from qq_chat_analyzer.application.qq import qq_runtime_workspace as workspace


def digest(content):
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def bundle(tmp_path):
    program = tmp_path / "安装 空间" / "runtime" / "qq-napcat-candidate"
    assets = {
        "plugins/napcat-plugin-echo/index.mjs": b"fictional plugin",
        "plugins/napcat-plugin-echo/snapshot/workspace.mjs": b"fictional snapshot module",
        "config/plugins.json": b'{"plugins": ["fictional"]}',
        "napcat.mjs": b"fictional patched program",
        "native/not-copied.dll": b"fictional native binary",
    }
    for name, content in assets.items():
        file = program / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
    metadata = tmp_path / "trusted-build-metadata"
    metadata.mkdir()
    manifest = metadata / "windows_runtime_manifest.json"
    manifest.write_text(json.dumps({
        "qqPins": "pins.json",
        "requirements": [{"path": "qq-napcat-candidate/" + name, "type": "file"}
                         for name in assets],
    }), encoding="utf-8")
    pins = {
        "upstream": {"version": "fictional-version"},
        "napcatPatch": {"path": "napcat.mjs", "patchedSha256": digest(assets["napcat.mjs"])},
        "templates": [{"target": name, "sha256": digest(content)}
                      for name, content in assets.items() if name.startswith("plugins/")],
        "pluginConfigSha256": digest(assets["config/plugins.json"]),
    }
    (metadata / "pins.json").write_text(json.dumps(pins), encoding="utf-8")
    return program, manifest, tmp_path / "fictional-user", assets


def prepare(bundle):
    program, manifest, user, _ = bundle
    return workspace.prepare_qq_workspace(program, manifest, data_root=user)


def test_copies_only_pinned_plugin_and_seed_and_reuses_valid_workspace(bundle):
    program, _, user, assets = bundle
    before = {p.relative_to(program): p.read_bytes() for p in program.rglob("*") if p.is_file()}
    result = prepare(bundle)
    assert result.snapshot_root == user / "transient/qq-direct-db"
    copied = {p.relative_to(result.work_root).as_posix(): p.read_bytes()
              for p in result.work_root.rglob("*") if p.is_file()}
    assert copied == {k: v for k, v in assets.items() if k.startswith(("plugins/", "config/"))}
    identity = result.work_root.stat().st_ino
    assert prepare(bundle) == result
    assert result.work_root.stat().st_ino == identity
    assert before == {p.relative_to(program): p.read_bytes() for p in program.rglob("*") if p.is_file()}
    assert not result.snapshot_root.exists()


@pytest.mark.parametrize("name", ["napcat.mjs", "plugins/napcat-plugin-echo/index.mjs"])
def test_corrupt_or_missing_source_cannot_publish_or_create_user_root(bundle, name):
    program, _, user, _ = bundle
    (program / name).write_bytes(b"corruption")
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert not user.exists()
    (program / name).unlink()
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert not user.exists()


def test_copy_failure_keeps_owned_staging_and_next_prepare_recovers(bundle, monkeypatch):
    real_copy = workspace.shutil.copyfile
    calls = 0

    def fail_after_partial(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            Path(destination).write_bytes(b"partial fictional file")
            raise OSError("fictional interrupted copy")
        return real_copy(source, destination)

    monkeypatch.setattr(workspace.shutil, "copyfile", fail_after_partial)
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    root = bundle[2] / "runtime/qq"
    assert not [p for p in root.iterdir() if len(p.name) == 64]
    assert list(root.glob("*.staging.owner.json"))
    monkeypatch.setattr(workspace.shutil, "copyfile", real_copy)
    result = prepare(bundle)
    assert result.work_root.is_dir()
    assert not list(root.glob("*.staging*"))


def test_copied_corruption_is_rejected_before_publish(bundle, monkeypatch):
    def corrupt(source, destination):
        Path(destination).write_bytes(b"damaged copy")
    monkeypatch.setattr(workspace.shutil, "copyfile", corrupt)
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert not [p for p in (bundle[2] / "runtime/qq").iterdir() if len(p.name) == 64]


@pytest.mark.parametrize("damage", ["unknown", "corrupt", "owner", "missing-owner"])
def test_existing_unknown_or_conflicting_workspace_is_never_modified(bundle, damage):
    result = prepare(bundle)
    owner = result.work_root.with_name(result.work_root.name + ".owner.json")
    if damage == "unknown":
        (result.work_root / "unknown.txt").write_bytes(b"keep me")
    elif damage == "corrupt":
        (result.work_root / "plugins/napcat-plugin-echo/index.mjs").write_bytes(b"modified")
    elif damage == "owner":
        owner.write_text('{}', encoding="utf-8")
    else:
        owner.unlink()
    before = {p: p.read_bytes() for p in result.work_root.rglob("*") if p.is_file()}
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert before == {p: p.read_bytes() for p in result.work_root.rglob("*") if p.is_file()}


def test_unknown_interrupted_staging_is_not_cleaned(bundle, monkeypatch):
    monkeypatch.setattr(workspace.shutil, "copyfile", lambda *args: (_ for _ in ()).throw(OSError("interruption")))
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    stage = next((bundle[2] / "runtime/qq").glob("*.staging"))
    (stage / "unknown.txt").write_bytes(b"keep me")
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert (stage / "unknown.txt").read_bytes() == b"keep me"


def test_simultaneous_preparation_never_overwrites_or_exposes_partial_result(bundle):
    barrier = threading.Barrier(4)
    def run():
        barrier.wait()
        result = prepare(bundle)
        assert (result.work_root / "config/plugins.json").read_bytes() == bundle[3]["config/plugins.json"]
        return result.work_root.stat().st_ino
    with ThreadPoolExecutor(max_workers=4) as pool:
        identities = list(pool.map(lambda _: run(), range(4)))
    assert len(set(identities)) == 1


@pytest.mark.slow_integration
def test_live_preparation_lease_blocks_second_process(bundle, monkeypatch):
    # A real second interpreter exercises the OS lock, not a mocked mutex.
    import os
    import sys
    real_copy = workspace.shutil.copyfile
    observed = []
    def inspect_lock(source, destination):
        if not observed:
            program, manifest, user, _ = bundle
            script = (
                "from qq_chat_analyzer.application.qq.qq_runtime_workspace import "
                "prepare_qq_workspace, QQWorkspaceBusy\n"
                "import sys\n"
                "try: prepare_qq_workspace(sys.argv[1], sys.argv[2], data_root=sys.argv[3], lock_timeout=0)\n"
                "except QQWorkspaceBusy: sys.exit(23)\n"
            )
            process = subprocess.run([sys.executable, "-B", "-c", script, str(program), str(manifest), str(user)],
                                     env=os.environ.copy(), capture_output=True, timeout=10)
            observed.append(process.returncode)
        return real_copy(source, destination)
    monkeypatch.setattr(workspace.shutil, "copyfile", inspect_lock)
    prepare(bundle)
    assert observed == [23]


@pytest.mark.slow_integration
def test_windows_junction_is_rejected_without_reading_target(bundle, tmp_path):
    import os
    if os.name != "nt":
        pytest.skip("Windows junction test")
    program = bundle[0]
    original = program / "plugins"
    original.rename(program / "saved-plugins")
    outside = tmp_path / "outside"
    outside.mkdir()
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(original), str(outside)], capture_output=True)
    assert result.returncode == 0
    try:
        with pytest.raises(workspace.QQWorkspaceError):
            prepare(bundle)
        assert list(outside.iterdir()) == []
    finally:
        original.rmdir()  # Remove only the test-created junction itself.


@pytest.mark.slow_integration
def test_user_workspace_ancestor_junction_is_rejected(bundle, tmp_path):
    import os
    if os.name != "nt":
        pytest.skip("Windows junction test")
    user = bundle[2]
    outside = tmp_path / "outside-user"
    outside.mkdir()
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(user), str(outside)], capture_output=True)
    assert result.returncode == 0
    try:
        with pytest.raises(workspace.QQWorkspaceError):
            prepare(bundle)
        assert not list(outside.iterdir())
    finally:
        user.rmdir()


@pytest.mark.parametrize("target", ["../escape", "config/other.json"])
def test_untrusted_pin_target_is_rejected_before_writing(bundle, target):
    pins_path = bundle[1].parent / "pins.json"
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    pins["templates"][0]["target"] = target
    pins_path.write_text(json.dumps(pins), encoding="utf-8")
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert not bundle[2].exists()


def test_crash_after_directory_publish_recovers_verified_ownership(bundle, monkeypatch):
    real_rename = Path.rename
    def interrupt_marker(path, destination):
        if path.name.endswith(".staging.owner.json"):
            raise OSError("fictional crash before proof rename")
        return real_rename(path, destination)
    monkeypatch.setattr(Path, "rename", interrupt_marker)
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    published = next(p for p in (bundle[2] / "runtime/qq").iterdir() if len(p.name) == 64)
    identity = published.stat().st_ino
    monkeypatch.setattr(Path, "rename", real_rename)
    assert prepare(bundle).work_root.stat().st_ino == identity


def test_replaced_staging_identity_is_not_cleaned(bundle, monkeypatch):
    monkeypatch.setattr(workspace.shutil, "copyfile", lambda *args: (_ for _ in ()).throw(OSError("interruption")))
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    stage = next((bundle[2] / "runtime/qq").glob("*.staging"))
    stage.rename(stage.with_name(stage.name + ".preserved"))
    stage.mkdir()
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert stage.is_dir()


def test_hardlinked_source_is_rejected(bundle, tmp_path):
    import os
    source = bundle[0] / "plugins/napcat-plugin-echo/index.mjs"
    os.link(source, tmp_path / "external-hardlink")
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert not bundle[2].exists()


def test_crash_during_owned_recovery_can_resume_without_stage_directory(bundle, monkeypatch):
    real_copy = workspace.shutil.copyfile
    monkeypatch.setattr(workspace.shutil, "copyfile", lambda *args: (_ for _ in ()).throw(OSError("interruption")))
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    real_unlink = Path.unlink
    def interrupt_unlink(path, *args, **kwargs):
        if path.name.endswith(".staging.owner.json"):
            raise OSError("interruption after owned directory cleanup")
        return real_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", interrupt_unlink)
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert not list((bundle[2] / "runtime/qq").glob("*.staging"))
    monkeypatch.setattr(Path, "unlink", real_unlink)
    monkeypatch.setattr(workspace.shutil, "copyfile", real_copy)
    assert prepare(bundle).work_root.is_dir()


@pytest.mark.slow_integration
def test_hard_killed_preparer_releases_lease_and_owned_partial_copy_recovers(bundle):
    import os
    import sys
    script = (
        "from qq_chat_analyzer.application.qq import qq_runtime_workspace as w\n"
        "from pathlib import Path\nimport sys, os\n"
        "def interrupted(source, destination):\n"
        " Path(destination).write_bytes(b'fictional partial')\n os._exit(29)\n"
        "w.shutil.copyfile = interrupted\n"
        "w.prepare_qq_workspace(sys.argv[1], sys.argv[2], data_root=sys.argv[3])\n"
    )
    process = subprocess.run([sys.executable, "-B", "-c", script, *map(str, bundle[:3])],
                             env=os.environ.copy(), capture_output=True, timeout=10)
    assert process.returncode == 29
    assert prepare(bundle).work_root.is_dir()


def test_manifest_cannot_omit_a_pinned_plugin_requirement(bundle):
    manifest_path = bundle[1]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["requirements"] = [e for e in manifest["requirements"] if not e["path"].endswith("workspace.mjs")]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert not bundle[2].exists()


def test_pins_cannot_omit_a_manifest_plugin_requirement(bundle):
    pins_path = bundle[1].parent / "pins.json"
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    pins["templates"] = pins["templates"][:1]
    pins_path.write_text(json.dumps(pins), encoding="utf-8")
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert not bundle[2].exists()


def test_existing_unknown_lease_file_is_preserved(bundle):
    result = prepare(bundle)
    lease = next(result.work_root.parent.glob("*.prepare.lock"))
    lease.write_bytes(b"unknown owner")
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert lease.read_bytes() == b"unknown owner"


def test_workspace_root_cannot_be_inside_release_directory(bundle):
    with pytest.raises(workspace.QQWorkspaceError):
        workspace.prepare_qq_workspace(bundle[0], bundle[1], data_root=bundle[0] / "user")
    assert not (bundle[0] / "user").exists()


def inventory(directory):
    """Observe bytes and identities in a fictional tree without changing it."""
    return {p.relative_to(directory).as_posix(): (
        p.stat().st_ino, p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None,
    ) for p in directory.rglob("*")}


def add_running_state(root):
    state = {
        "config/plugins.json": b'{\n  "napcat-plugin-echo": true\n}\n',
        "config/napcat.json": b'{fileLog: true, /* fictional JSON5 config */}',
        "config/napcat_123456.json": b'{"fileLog": true}',
        "config/onebot11_123456.json": b'{"network": {}}',
        "config/webui.json": b'{"port": 6099}',
        "config/plugins/napcat-plugin-echo.json": b'{}',
        "cache/fictional/nested/blob": b'fictional binary cache\x00\xff',
        "logs/2026-10-08.log": b'fictional NapCat log',
    }
    for name, content in state.items():
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    (root / "cache/empty").mkdir()
    return state


def test_running_workspace_reuses_without_reading_or_rewriting_state(bundle, monkeypatch):
    result = prepare(bundle)
    add_running_state(result.work_root)
    before = inventory(result.work_root)
    real_open = Path.open

    def protect_private_contents(path, *args, **kwargs):
        if path.is_relative_to(result.work_root):
            relative = path.relative_to(result.work_root)
            if relative.parts[0] in {"config", "cache", "logs"}:
                raise AssertionError("Preparation must not open user runtime state")
        return real_open(path, *args, **kwargs)

    with monkeypatch.context() as guard:
        guard.setattr(Path, "open", protect_private_contents)
        reused = prepare(bundle)
    assert reused == result
    assert inventory(result.work_root) == before


@pytest.mark.parametrize("remove", ["config/plugins.json", "config"])
def test_reuse_never_restores_removed_mutable_state(bundle, remove):
    result = prepare(bundle)
    (result.work_root / "config/plugins.json").unlink()
    if remove == "config":
        (result.work_root / remove).rmdir()
    before = inventory(result.work_root)
    assert prepare(bundle) == result
    assert inventory(result.work_root) == before
    assert not (result.work_root / remove).exists()


@pytest.mark.parametrize("damage", ["modify", "delete"])
def test_plugin_damage_with_runtime_state_requires_inspection_not_repair(bundle, damage):
    result = prepare(bundle)
    add_running_state(result.work_root)
    plugin = result.work_root / "plugins/napcat-plugin-echo/index.mjs"
    if damage == "modify":
        plugin.write_bytes(b'fictional tampering')
    else:
        plugin.unlink()
    before = inventory(result.work_root)
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert inventory(result.work_root) == before


@pytest.mark.parametrize("name,is_directory", [("unknown.txt", False), ("unknown", True), ("plugins/napcat-plugin-echo/extra.mjs", False)])
def test_unknown_members_with_runtime_state_are_retained_and_refused(bundle, name, is_directory):
    result = prepare(bundle)
    add_running_state(result.work_root)
    unknown = result.work_root / name
    if is_directory:
        unknown.mkdir()
    else:
        unknown.write_bytes(b'unknown fictional member')
    before = inventory(result.work_root)
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert inventory(result.work_root) == before


@pytest.mark.parametrize("root_name", ["config"])
def test_mutable_root_must_be_a_directory(bundle, root_name):
    result = prepare(bundle)
    if root_name == "config":
        (result.work_root / "config/plugins.json").unlink()
        (result.work_root / "config").rmdir()
    wrong_kind = result.work_root / root_name
    wrong_kind.write_bytes(b'not a directory')
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert wrong_kind.read_bytes() == b'not a directory'


def test_simultaneous_reuse_preserves_running_state(bundle):
    result = prepare(bundle)
    add_running_state(result.work_root)
    before = inventory(result.work_root)
    barrier = threading.Barrier(4)

    def reuse():
        barrier.wait()
        return prepare(bundle)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: reuse(), range(4)))
    assert results == [result] * 4
    assert inventory(result.work_root) == before


@pytest.mark.parametrize("state_name", ["config/napcat.json"])
def test_hardlinked_runtime_state_is_not_reused(bundle, tmp_path, state_name):
    import os
    result = prepare(bundle)
    state = result.work_root / state_name
    state.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside-state"
    outside.write_bytes(b'fictional shared state')
    os.link(outside, state)
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert state.read_bytes() == outside.read_bytes() == b'fictional shared state'


@pytest.mark.slow_integration
@pytest.mark.parametrize("relative", ["cache", "config/plugins"])
def test_runtime_state_junction_is_refused_without_traversing_target(bundle, tmp_path, relative):
    import os
    if os.name != "nt":
        pytest.skip("Windows junction test")
    result = prepare(bundle)
    link = result.work_root / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside-state"
    outside.mkdir()
    sentinel = outside / "do-not-open"
    sentinel.write_bytes(b'fictional outside content')
    created = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
    assert created.returncode == 0
    try:
        with pytest.raises(workspace.QQWorkspaceError):
            prepare(bundle)
        assert sentinel.read_bytes() == b'fictional outside content'
        assert list(outside.iterdir()) == [sentinel]
    finally:
        link.rmdir()  # Remove only this test-created junction, never its target.


def test_staging_with_runtime_state_is_not_recursively_cleaned(bundle, monkeypatch):
    real_copy = workspace.shutil.copyfile
    monkeypatch.setattr(workspace.shutil, "copyfile", lambda *args: (_ for _ in ()).throw(OSError("interruption")))
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    stage = next((bundle[2] / "runtime/qq").glob("*.staging"))
    (stage / "logs").mkdir()
    (stage / "logs/keep.log").write_bytes(b'fictional ambiguous staging state')
    before = inventory(stage)
    monkeypatch.setattr(workspace.shutil, "copyfile", real_copy)
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert inventory(stage) == before


@pytest.mark.parametrize("state_kind", ["napcat", "guild"])
def test_workspace_replaced_during_inspection_is_refused_without_touching_state(bundle, monkeypatch, state_kind):
    result = prepare(bundle)
    if state_kind == "guild":
        add_guild_state(result.work_root)
    else:
        add_running_state(result.work_root)
    before = inventory(result.work_root)
    preserved = result.work_root.with_name(result.work_root.name + ".preserved")
    real_inspect = workspace._inspect

    def replace_after_inspection(directory, *args, **kwargs):
        real_inspect(directory, *args, **kwargs)
        if directory == result.work_root:
            assert directory.resolve().is_relative_to(bundle[2].resolve())
            assert preserved.resolve().is_relative_to(bundle[2].resolve())
            directory.rename(preserved)
            directory.mkdir()

    monkeypatch.setattr(workspace, "_inspect", replace_after_inspection)
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert inventory(preserved) == before
    assert list(result.work_root.iterdir()) == []


GUILD_STATE_NAMES = ("guild1.db", "guild1.db-wal", "guild1.db-shm")


def add_guild_state(root, names=GUILD_STATE_NAMES):
    for name in names:
        (root / name).write_bytes(b'fictional opaque state, not a chat database')


@pytest.mark.parametrize("names", [GUILD_STATE_NAMES])
def test_guild_state_reuses_owned_workspace_without_opening_or_hashing(bundle, monkeypatch, names):
    result = prepare(bundle)
    add_guild_state(result.work_root, names)
    before = inventory(result.work_root)
    protected = {result.work_root / name for name in names}
    real_open = Path.open
    real_hash = workspace._sha256

    def protect_open(path, *args, **kwargs):
        assert path not in protected, "Preparation must not open guild runtime state"
        return real_open(path, *args, **kwargs)

    def protect_hash(path):
        assert path not in protected, "Preparation must not hash guild runtime state"
        return real_hash(path)

    with monkeypatch.context() as guard:
        guard.setattr(Path, "open", protect_open)
        guard.setattr(workspace, "_sha256", protect_hash)
        assert prepare(bundle) == result
    assert inventory(result.work_root) == before


@pytest.mark.parametrize("name", ['guild1.db'])
def test_guild_state_directory_is_refused_and_preserved(bundle, name):
    result = prepare(bundle)
    (result.work_root / name).mkdir()
    (result.work_root / name / "keep").write_bytes(b'fictional directory content')
    before = inventory(result.work_root)
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert inventory(result.work_root) == before


@pytest.mark.parametrize("name", ['guild1.db'])
def test_guild_state_hardlink_is_refused_and_preserved(bundle, tmp_path, name):
    import os
    result = prepare(bundle)
    outside = tmp_path / "fictional-outside-state"
    outside.write_bytes(b'fictional shared state')
    os.link(outside, result.work_root / name)
    before = inventory(result.work_root)
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert inventory(result.work_root) == before
    assert outside.read_bytes() == b'fictional shared state'


@pytest.mark.parametrize("name", ['guild1.db'])
def test_guild_state_reparse_point_is_refused(bundle, monkeypatch, name):
    import stat
    from types import SimpleNamespace
    result = prepare(bundle)
    state = result.work_root / name
    add_guild_state(result.work_root, (name,))
    before = inventory(result.work_root)
    real_lstat = Path.lstat

    def link_attributes(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if path == state:
            attributes = {field: getattr(info, field) for field in dir(info)
                          if field.startswith("st_")}
            attributes["st_file_attributes"] = stat.FILE_ATTRIBUTE_REPARSE_POINT
            return SimpleNamespace(**attributes)
        return info

    with monkeypatch.context() as guard:
        guard.setattr(Path, "lstat", link_attributes)
        with pytest.raises(workspace.QQWorkspaceError):
            prepare(bundle)
    assert inventory(result.work_root) == before


@pytest.mark.slow_integration
@pytest.mark.parametrize("name", ['guild1.db'])
def test_guild_state_link_is_refused_without_opening_target(bundle, tmp_path, monkeypatch, name):
    import os
    if os.name != "nt":
        pytest.skip("Windows junction test")
    result = prepare(bundle)
    outside = tmp_path / "fictional-outside-state"
    link = result.work_root / name
    outside.mkdir()
    sentinel = outside / "keep"
    sentinel.write_bytes(b'fictional outside content')
    created = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
    assert created.returncode == 0
    real_open = Path.open

    def protect_target(path, *args, **kwargs):
        assert path != link and not path.is_relative_to(outside), "Must not open link or its target"
        return real_open(path, *args, **kwargs)

    try:
        with monkeypatch.context() as guard:
            guard.setattr(Path, "open", protect_target)
            with pytest.raises(workspace.QQWorkspaceError):
                prepare(bundle)
        assert link.lstat()
        assert sentinel.read_bytes() == b'fictional outside content'
    finally:
        link.rmdir()  # Only the test-created junction itself.


def test_guild_state_does_not_allow_other_unknown_members(bundle):
    result = prepare(bundle)
    add_guild_state(result.work_root)
    unknown = result.work_root / "plugins/napcat-plugin-echo/guild1.db"
    unknown.write_bytes(b'fictional unknown member')
    before = inventory(result.work_root)
    with pytest.raises(workspace.QQWorkspaceError, match="Unknown workspace member"):
        prepare(bundle)
    assert inventory(result.work_root) == before


@pytest.mark.parametrize("name", ['guild1.db'])
@pytest.mark.parametrize("phase", ["staging_recovery", "first_publish", "publish_recovery"])
def test_guild_state_is_refused_on_strict_publication_paths(bundle, monkeypatch, name, phase):
    real_copy = workspace.shutil.copyfile
    real_rename = Path.rename
    if phase == "publish_recovery":
        def interrupt_owner_rename(path, destination):
            if path.name.endswith(".staging.owner.json"):
                raise OSError("fictional interruption before owner publication")
            return real_rename(path, destination)
        monkeypatch.setattr(Path, "rename", interrupt_owner_rename)
    else:
        def interrupt_copy(source, destination):
            if phase == "staging_recovery":
                raise OSError("fictional interrupted staging copy")
            copied = real_copy(source, destination)
            # Simulate unexpected state appearing before first publication.
            if Path(source).relative_to(bundle[0]).as_posix() == "config/plugins.json":
                stage = next((bundle[2] / "runtime/qq").glob("*.staging"))
                add_guild_state(stage, (name,))
            return copied
        monkeypatch.setattr(workspace.shutil, "copyfile", interrupt_copy)
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    parent = bundle[2] / "runtime/qq"
    if phase == "publish_recovery":
        directory = next(p for p in parent.iterdir() if len(p.name) == 64)
    else:
        directory = next(parent.glob("*.staging"))
    if phase != "first_publish":
        add_guild_state(directory, (name,))
    before = inventory(parent)
    monkeypatch.setattr(workspace.shutil, "copyfile", real_copy)
    monkeypatch.setattr(Path, "rename", real_rename)
    with pytest.raises(workspace.QQWorkspaceError, match="Unknown workspace member"):
        prepare(bundle)
    assert inventory(parent) == before
    if phase != "publish_recovery":
        assert not any(p.is_dir() and len(p.name) == 64 for p in parent.iterdir())
    else:
        assert not (parent / (directory.name + ".owner.json")).exists()


def test_guild_state_does_not_bypass_plugin_integrity(bundle):
    result = prepare(bundle)
    add_guild_state(result.work_root)
    plugin = result.work_root / "plugins/napcat-plugin-echo/index.mjs"
    plugin.write_bytes(b'fictional tampering')
    before = inventory(result.work_root)
    with pytest.raises(workspace.QQWorkspaceError, match="Work copy hash mismatch"):
        prepare(bundle)
    assert inventory(result.work_root) == before


def test_guild_state_does_not_bypass_ownership(bundle):
    result = prepare(bundle)
    add_guild_state(result.work_root)
    marker = result.work_root.parent / (result.work_root.name + ".owner.json")
    proof = json.loads(marker.read_text(encoding="utf-8"))
    proof["directory_identity"][1] += 1
    marker.write_text(json.dumps(proof), encoding="utf-8")
    before = inventory(result.work_root.parent)
    with pytest.raises(workspace.QQWorkspaceError):
        prepare(bundle)
    assert inventory(result.work_root.parent) == before
