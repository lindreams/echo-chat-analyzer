"""Prepare an owned, versioned QQ work copy without starting QQ or NapCat.

Trust is supplied by the build manifest/pins, not by existing work directories.
Only pinned Echo templates and the plugin config seed are copied. Native and
other NapCat assets remain subject to the existing release/build contract.
Published workspaces retain NapCat's config, cache, logs and the exact guild
database filenames as opaque mutable state. Plugin assets stay pinned; staging
remains pristine and is never allowed to contain runtime state. Startup
integration is deliberately separate.
"""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import time

from ..echo_report_export import EchoReportExportError, _require_no_reparse_points
from ..report_staging import _try_lock
from .qq_runtime_paths import QQRuntimePaths, qq_runtime_paths

LAYOUT_VERSION = "echo-qq-workspace.v1"
_LOCK_HEADER = b"echo-qq-prepare.v1\n"
_PLUGIN = "plugins/napcat-plugin-echo/"
# NapCat v4.18.18 packages/napcat-common/src/path.ts defines these writable
# trees. Its plugin loader writes config/plugins.json after normal operation.
# Only the published work copy admits them, never a recoverable staging tree.
_MUTABLE_DIRECTORIES = frozenset({"config", "cache", "logs"})
# Opaque state admitted only at the published work copy's root, never staging.
_MUTABLE_ROOT_FILES = frozenset({"guild1.db", "guild1.db-wal", "guild1.db-shm"})
# Regenerated from trusted program/QQ resources before each launch; never
# executed from an existing work copy without refreshing them first.
_BOOTSTRAP_FILES = frozenset({"loadNapCat.js", "qqnt.echo.json"})


class QQWorkspaceError(ValueError):
    """Preparation failed; damaged/unowned state needs inspection, not repair."""


class QQWorkspaceBusy(QQWorkspaceError):
    """Another preparer holds this component's lease."""


def _safe(path: Path) -> None:
    _require_no_reparse_points(path)


def _identity(info):
    return [info.st_dev, info.st_ino]


def _regular(path: Path):
    _safe(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise QQWorkspaceError("Expected an unlinked regular component file")
    return info


def _json(path: Path):
    _regular(path)
    if path.stat().st_size > 1024 * 1024:
        raise QQWorkspaceError("Oversized runtime metadata")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _sha256(path: Path):
    before = _regular(path)
    with path.open("rb") as stream:
        if _identity(os.fstat(stream.fileno())) != _identity(before):
            raise QQWorkspaceError("Component changed while opening")
        result = hashlib.file_digest(stream, "sha256").hexdigest()
    after = _regular(path)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ):
        raise QQWorkspaceError("Component changed while hashing")
    return result


def _relative(name):
    if not isinstance(name, str) or "\\" in name or ":" in name:
        raise QQWorkspaceError("Unsafe manifest path")
    value = PurePosixPath(name)
    if value.is_absolute() or any(part in ("", ".", "..") for part in name.split("/")):
        raise QQWorkspaceError("Unsafe manifest path")
    return name


def _hash(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise QQWorkspaceError("Invalid component hash")
    return value


def _components(program: Path, manifest_path: Path):
    manifest = _json(manifest_path)
    pins_name = _relative(manifest["qqPins"])
    if "/" in pins_name:
        raise QQWorkspaceError("Pins must be beside the release manifest")
    pins = _json(manifest_path.parent / pins_name)
    required = {entry["path"] for entry in manifest["requirements"] if entry["type"] == "file"}
    files = {}
    for template in pins["templates"]:
        name = _relative(template["target"])
        if not name.startswith(_PLUGIN) or name in files:
            raise QQWorkspaceError("Unexpected or duplicate Echo plugin target")
        files[name] = _hash(template["sha256"])
    if not files or _PLUGIN + "index.mjs" not in files:
        raise QQWorkspaceError("Echo plugin entry is missing")
    manifest_plugins = {name.removeprefix("qq-napcat-candidate/") for name in required
                        if name.startswith("qq-napcat-candidate/" + _PLUGIN)}
    if manifest_plugins != set(files):
        raise QQWorkspaceError("Manifest and pins disagree about Echo plugin contents")
    files["config/plugins.json"] = _hash(pins["pluginConfigSha256"])
    guard = _relative(pins["napcatPatch"]["path"])
    if guard != "napcat.mjs":
        raise QQWorkspaceError("Unexpected NapCat program entry")
    guard_hash = _hash(pins["napcatPatch"]["patchedSha256"])
    for name, expected in {**files, guard: guard_hash}.items():
        if "qq-napcat-candidate/" + name not in required or _sha256(program / name) != expected:
            raise QQWorkspaceError("Release component does not match manifest/pins")
    content = {"layout": LAYOUT_VERSION, "files": files, "napcat": guard_hash,
               "upstream": pins["upstream"]["version"]}
    component = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return component, files


@contextmanager
def _lease(path: Path, timeout: float):
    deadline = time.monotonic() + max(0, timeout)
    while True:
        _safe(path)
        created = False
        try:
            stream = path.open("x+b")
            created = True
        except FileExistsError:
            _regular(path)
            stream = path.open("r+b")
        with stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or _identity(info) != _identity(path.lstat()):
                raise QQWorkspaceError("Lease file identity changed")
            while not _try_lock(stream):
                if time.monotonic() >= deadline:
                    raise QQWorkspaceBusy("QQ workspace preparation is already active")
                time.sleep(0.02)
            if created:
                stream.write(_LOCK_HEADER)
                stream.flush()
                os.fsync(stream.fileno())
            stream.seek(0)
            header = stream.read(len(_LOCK_HEADER) + 1)
            if header == _LOCK_HEADER:
                _regular(path)
                yield
                return
            if header:
                raise QQWorkspaceError("Unknown preparation lease file")
            # Another creator may have been paused immediately after exclusive
            # creation. Release our OS lock by closing, so it can initialize.
        if time.monotonic() >= deadline:
            raise QQWorkspaceBusy("Preparation lease has not been initialized")
        time.sleep(0.02)


def _proof(root, directory, marker, component):
    return {"schema": LAYOUT_VERSION, "component": component,
            "root_identity": _identity(root.lstat()),
            "directory_identity": _identity(directory.lstat()),
            "marker_identity": _identity(marker.lstat())}


def _owner_proof(root, marker, component):
    _safe(root)
    proof = _json(marker)
    identity = proof.get("directory_identity")
    if (not isinstance(identity, list) or len(identity) != 2
            or any(type(value) is not int for value in identity)):
        raise QQWorkspaceError("Invalid directory ownership identity")
    expected = {"schema": LAYOUT_VERSION, "component": component,
                "root_identity": _identity(root.lstat()),
                "directory_identity": identity,
                "marker_identity": _identity(marker.lstat())}
    if proof != expected:
        raise QQWorkspaceError("Workspace ownership or identity does not match")
    return proof


def _owned(root, directory, marker, component):
    _safe(directory)
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise QQWorkspaceError("Workspace is not a directory")
    if _owner_proof(root, marker, component) != _proof(root, directory, marker, component):
        raise QQWorkspaceError("Workspace ownership or identity does not match")


def _inspect(directory, files, *, complete, runtime_state=False):
    """Verify assets, checking mutable trees' shape without opening their data.

    The seed is verified in the release and staging only. Published state may
    change or disappear; preparation neither restores it nor validates NapCat
    configuration semantics. Every descendant must still be an ordinary file
    or directory without links/reparse points. Anything outside these three
    state trees must match the pinned program inventory, the exact mutable root
    filenames, or the two generated bootstrap filenames, which the launcher
    refreshes before executing them.
    """
    if runtime_state:
        files = {name: expected for name, expected in files.items()
                 if PurePosixPath(name).parts[0] not in _MUTABLE_DIRECTORIES}
    directories = {parent.as_posix() for name in files
                   for parent in PurePosixPath(name).parents if parent != PurePosixPath(".")}
    found = set()
    pending = [directory]
    while pending:
        for child in pending.pop().iterdir():
            _safe(child)
            info = child.lstat()
            name = child.relative_to(directory).as_posix()
            parts = PurePosixPath(name).parts
            mutable = runtime_state and parts[0] in _MUTABLE_DIRECTORIES
            if stat.S_ISDIR(info.st_mode) and (name in directories or mutable):
                pending.append(child)
            elif (mutable and len(parts) > 1 and stat.S_ISREG(info.st_mode)
                  and info.st_nlink == 1):
                # No read, hash, migration, overwrite or deletion of private state.
                continue
            elif (runtime_state and name in _BOOTSTRAP_FILES
                  and stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
                continue
            elif (runtime_state and name in _MUTABLE_ROOT_FILES
                  and stat.S_ISREG(info.st_mode) and info.st_nlink == 1):
                # Preserve opaque state without opening or hashing its contents.
                continue
            elif stat.S_ISREG(info.st_mode) and name in files and info.st_nlink == 1:
                found.add(name)
                if complete and _sha256(child) != files[name]:
                    raise QQWorkspaceError("Work copy hash mismatch")
            else:
                raise QQWorkspaceError("Unknown workspace member; refusing cleanup or reuse")
    if complete and found != set(files):
        raise QQWorkspaceError("Work copy is incomplete")


def _prepare(program, manifest, data_root, timeout):
    _safe(program)
    component, files = _components(program, manifest)
    paths = qq_runtime_paths(component_id=component, program_root=program, data_root=data_root)
    root = paths.work_root.parent
    _safe(root)
    # A caller must not accidentally select a user root inside the release tree.
    if root.absolute().is_relative_to(program.absolute()) or program.absolute().is_relative_to(root.absolute()):
        raise QQWorkspaceError("Program and workspace roots must be separate")
    root.mkdir(parents=True, exist_ok=True)
    _safe(root)
    final = paths.work_root
    final_owner = root / (component + ".owner.json")
    stage = root / ("." + component + ".staging")
    stage_owner = root / (stage.name + ".owner.json")
    with _lease(root / ("." + component + ".prepare.lock"), timeout):
        for path in (final, final_owner, stage, stage_owner):
            _safe(path)
        if final.exists():
            # Recover a crash between the two publication renames. Both identities
            # and all completed contents must verify before moving the proof.
            if not final_owner.exists() and stage_owner.exists() and not stage.exists():
                _owned(root, final, stage_owner, component)
                _inspect(final, files, complete=True)
                stage_owner.rename(final_owner)
            _owned(root, final, final_owner, component)
            _inspect(final, files, complete=True, runtime_state=True)
            _owned(root, final, final_owner, component)
            if stage.exists() or stage_owner.exists():
                raise QQWorkspaceError("Conflicting staging beside a valid workspace")
            return paths
        if final_owner.exists():
            raise QQWorkspaceError("Orphaned final ownership proof")
        if stage.exists() or stage_owner.exists():
            if stage.exists():
                _owned(root, stage, stage_owner, component)
                _inspect(stage, files, complete=False)
                _owned(root, stage, stage_owner, component)
                shutil.rmtree(stage)
            # Recover an interruption after owned directory deletion but before
            # its marker deletion. Unknown/orphaned unproven markers are retained.
            _owner_proof(root, stage_owner, component)
            stage_owner.unlink()
        stage.mkdir()
        # Write proof before any component copy. If writing itself is interrupted,
        # leave the unproven directory for inspection rather than guessing ownership.
        with stage_owner.open("x", encoding="utf-8") as stream:
            json.dump(_proof(root, stage, stage_owner, component), stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        for name in sorted(files):
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            _regular(program / name)
            shutil.copyfile(program / name, destination)
        _owned(root, stage, stage_owner, component)
        _inspect(stage, files, complete=True)
        # Recheck the release identity after copying; a changing source is not trusted.
        if _components(program, manifest) != (component, files):
            raise QQWorkspaceError("Release components changed during preparation")
        stage.rename(final)  # No replacement of existing destinations on Windows.
        stage_owner.rename(final_owner)
        return paths


def prepare_qq_workspace(
    program_root: str | Path,
    manifest_path: str | Path,
    *,
    data_root: str | Path | None = None,
    lock_timeout: float = 10,
) -> QQRuntimePaths:
    """Validate, recover owned staging, copy, verify and publish under an OS lease.

    Metadata must come from the trusted build resource, never from mutable work
    state. Returning paths confirms the owned work copy can be reused, not that
    its user configuration is semantically valid. Reuse failures require manual
    inspection: no asset repair or fallback to an old installation is attempted.
    No processes start, snapshot directories are not created, and failed
    preparation retains its proof for safe retry. Unknown entries remain intact.
    """
    try:
        return _prepare(Path(program_root), Path(manifest_path),
                        Path(data_root) if data_root is not None else None, lock_timeout)
    except QQWorkspaceError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, EchoReportExportError):
        raise QQWorkspaceError("QQ workspace preparation failed safely") from None
