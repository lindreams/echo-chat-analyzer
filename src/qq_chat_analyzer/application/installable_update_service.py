"""Qt-free Velopack updates. Installation requires final shutdown evidence.

Feed configuration is supplied by the trusted composition root, never by
release-page metadata, chat content, environment variables, or GUI text input.
Construction is inert; check/download/preparation must run on a worker.
"""
from __future__ import annotations

import re
import sys
import hashlib
import secrets
import tempfile
import time
import weakref
from xml.etree import ElementTree
from zipfile import ZipFile
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from .update_check_service import _parse_version
from .shutdown_models import ShutdownResult


@dataclass(frozen=True, slots=True)
class UpdateFeedConfig:
    """An explicitly approved HTTPS feed, or an absolute local test directory.

    HTTPS alone does not establish publisher trust: the composition root must
    supply an approved endpoint. No default production source exists.
    """
    source: str | Path
    package_id: str
    channel: str

    def __post_init__(self) -> None:
        if isinstance(self.source, Path):
            valid = self.source.is_absolute()
        elif isinstance(self.source, str):
            parsed = urlsplit(self.source)
            valid = (parsed.scheme == 'https' and bool(parsed.hostname)
                     and not parsed.username and not parsed.password
                     and not parsed.query and not parsed.fragment
                     and not any(c.isspace() or ord(c) < 32 for c in self.source)
                     and '\\' not in self.source)
        else:
            valid = False
        if (not valid or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,63}', self.package_id)
                or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', self.channel)):
            raise ValueError('Invalid update feed configuration')


@dataclass(frozen=True, slots=True)
class InstallableUpdateResult:
    """Public snapshot; downloaded is NOT authorization to install.

    No SDK objects, source URLs, paths, exception text, or executable links
    cross this boundary. error_code/public_message are safe diagnostics.
    """
    status: Literal['idle', 'unconfigured', 'unsupported', 'checking', 'no_update',
                    'available', 'downloading', 'downloaded', 'failed', 'busy']
    current_version: str | None = None
    target_version: str | None = None
    progress: int = 0
    error_code: str | None = None
    public_message: str | None = None


class InstallableUpdater(Protocol):
    def check(self) -> InstallableUpdateResult: ...
    def download(self, *, progress: Callable[[int], None] | None = None) -> InstallableUpdateResult: ...
    def get_status(self) -> InstallableUpdateResult: ...
    def prepare_install(self) -> InstallHandoffResult: ...
    def handoff(self, token: str, shutdown: ShutdownResult) -> InstallHandoffResult: ...


@dataclass(frozen=True, slots=True)
class InstallHandoffResult:
    """Opaque preparation token, not install permission or an SDK asset."""
    status: Literal['ready', 'denied', 'started', 'failed', 'busy']
    target_version: str | None = None
    token: str | None = None
    public_message: str | None = None


def _manifest_identity(content: bytes) -> tuple[str, str, str]:
    root = ElementTree.fromstring(content)
    fields = {node.tag.rsplit('}', 1)[-1]: node.text or '' for node in root.iter()}
    return fields.get('id', ''), fields.get('version', ''), fields.get('channel', '')


def _installed_directory(feed: UpdateFeedConfig, manager: Any) -> Path:
    # No guessing between SDK caches: the production manager captures its
    # validated writable Setup root before SDK construction. Read-only-root
    # fallback layouts are unsupported until their locator can be proven.
    directory = manager.package_directory
    manager.verify_installation(feed)
    return directory


class _SetupManager:
    def __init__(self, feed: UpdateFeedConfig) -> None:
        import velopack
        current = Path(sys.executable).resolve().parent
        if current.name.lower() != 'current':
            raise ValueError('Unsupported Setup layout')
        self.root = current.parent
        self.package_directory = self.root / 'packages'
        self.verify_installation(feed)
        locator = velopack.VelopackLocatorConfig(
            str(self.root), str(self.root / 'Update.exe'), str(self.package_directory),
            str(current / 'sq.version'), str(current), False)
        self.sdk = velopack.UpdateManager(str(feed.source),
            options=velopack.UpdateOptions(False, -1, feed.channel), locator=locator)

    def verify_installation(self, feed: UpdateFeedConfig) -> None:
        if (not _setup_runtime() or (self.root / '.portable').exists()
                or not (self.root / 'Update.exe').is_file()):
            raise ValueError('Not a Setup installation')
        identity = _manifest_identity((self.root / 'current' / 'sq.version').read_bytes())
        if identity[0] != feed.package_id or identity[2] != feed.channel:
            raise ValueError('Installed identity does not match trusted feed')
        if hasattr(self, 'sdk') and identity[1] != self.sdk.get_current_version():
            raise ValueError('Installed version changed')
        # Match the pinned SDK's writable-root locator branch. This short probe
        # creates no user data, and never probes a source/GUI-provided directory.
        with tempfile.TemporaryFile(dir=self.root):
            pass

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, 'sdk'), name)


class _PackageReadGuard:
    """Keep verified Windows bytes immutable through updater launch and exit.

    Read sharing lets Velopack inspect the archive. Write/delete sharing is
    denied. The retained guard is released by normal process teardown; it
    owns only this read handle, not processes or a second shutdown protocol.
    """
    def __init__(self, path: Path) -> None:
        if sys.platform != 'win32':
            stream = path.open('rb')
            self._release = weakref.finalize(self, stream.close)
            return
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self._release = weakref.finalize(self, kernel.CloseHandle, handle)

    def close(self) -> None:
        self._release()


def _setup_runtime() -> bool:
    return sys.platform == 'win32' and getattr(sys, 'frozen', False) is True


def _manager(feed: UpdateFeedConfig) -> Any:
    # Never omit source: SDK 1.2.161 otherwise selects hosted Velopack Flow.
    # Full packages only for this stage; no downgrade or channel inference.
    return _SetupManager(feed)


class InstallableUpdateService:
    """One manager and one retained UpdateInfo per service instance.

    Nonblocking operation lock rejects concurrent/reentrant check/download.
    Snapshot reads and callback reads remain nonblocking with respect to I/O.
    SDK owns downloads/cache/locking; installation independently reattests bytes.
    """
    def __init__(self, *, feed: UpdateFeedConfig | None = None,
                 manager_factory: Callable[[UpdateFeedConfig], Any] = _manager,
                 setup_runtime: Callable[[], bool] = _setup_runtime,
                 package_directory: Callable[[UpdateFeedConfig, Any], Path] = _installed_directory) -> None:
        self._feed = feed
        self._factory = manager_factory
        self._setup_runtime = setup_runtime
        self._package_directory = package_directory
        self._prepared: Any = None
        self._handoff_started = False
        self._handoff_guard: _PackageReadGuard | None = None
        self._manager: Any = None
        self._candidate: Any = None
        self._operation = Lock()
        self._snapshot_lock = Lock()
        self._result = InstallableUpdateResult('unconfigured' if feed is None else 'idle')

    def get_status(self) -> InstallableUpdateResult:
        """Memory only; use check() on a worker to recover pending disk state."""
        with self._snapshot_lock:
            return self._result

    def _set(self, status: str, **fields: Any) -> InstallableUpdateResult:
        with self._snapshot_lock:
            self._result = replace(self._result, status=status, error_code=None,
                                   public_message=None, **fields)
            return self._result

    def _failure(self, code: str) -> InstallableUpdateResult:
        with self._snapshot_lock:
            self._result = replace(self._result, status='failed', error_code=code,
                                   progress=0 if self._result.progress == 100 else self._result.progress,
                                   public_message='更新操作未完成，请稍后重试或打开发布页面。')
            return self._result

    def _gate(self) -> InstallableUpdateResult | None:
        if self._feed is None:
            return self._set('unconfigured')
        if not self._setup_runtime():
            return self._set('unsupported')
        if self._manager is None:
            self._manager = self._factory(self._feed)
        # The production factory verifies the manifest/updater/locator first.
        # Frozen alone is insufficient: Portable and foreign packages are denied.
        if (self._manager.get_is_portable() is not False
                or self._manager.get_app_id() != self._feed.package_id):
            self._candidate = None
            return self._set('unsupported', target_version=None, progress=0)
        current = self._manager.get_current_version()
        _parse_version(current)
        self._set(self.get_status().status, current_version=current)
        return None

    def _validate_asset(self, asset: Any, *, remote: bool = True) -> None:
        assert self._feed is not None
        _parse_version(asset.Version)
        if (asset.PackageId != self._feed.package_id or asset.Type != 'Full'
                or not isinstance(asset.FileName, str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*\.nupkg', asset.FileName)
                or (remote and not re.fullmatch(r'[a-fA-F0-9]{64}', asset.SHA256))
                or asset.Size <= 0):
            raise ValueError('Invalid package metadata')

    def _pending(self) -> Any:
        pending = self._manager.get_update_pending_restart()
        if pending is not None:
            # SDK local_path_to_asset intentionally leaves both hashes empty.
            # Pending is disk presence, not a new integrity/install attestation.
            self._validate_asset(pending, remote=False)
        return pending

    def check(self) -> InstallableUpdateResult:
        if not self._operation.acquire(blocking=False):
            return replace(self.get_status(), status='busy', error_code='in_progress')
        try:
            gated = self._gate()
            if gated is not None:
                return gated
            pending = self._pending()
            if pending is not None:
                return self._set('downloaded', target_version=pending.Version, progress=100)
            self._candidate = None
            self._set('checking', target_version=None, progress=0)
            info = self._manager.check_for_updates()
            if info is None:
                return self._set('no_update')
            self._validate_asset(info.TargetFullRelease)
            if info.IsDowngrade:
                raise ValueError('Downgrade denied')
            self._candidate = info
            return self._set('available', target_version=info.TargetFullRelease.Version)
        except Exception:
            self._candidate = None
            return self._failure('check_failed')
        finally:
            self._operation.release()

    def download(self, *, progress: Callable[[int], None] | None = None) -> InstallableUpdateResult:
        if not self._operation.acquire(blocking=False):
            return replace(self.get_status(), status='busy', error_code='in_progress')
        try:
            gated = self._gate()
            if gated is not None:
                return gated
            if self.get_status().status == 'downloaded':
                pending = self._pending()
                if pending is not None and pending.Version == self.get_status().target_version:
                    return self.get_status()
                self._candidate = None
            if self._candidate is None:
                return self._failure('check_required')
            self._set('downloading', progress=0)

            def emit(value: int, *, complete: bool = False) -> None:
                if type(value) is not int:
                    return
                old = self.get_status().progress
                value = max(old, min(100 if complete else 99, max(0, value)))
                self._set('downloading', progress=value)
                if progress is not None:
                    try:
                        progress(value)
                    except Exception:
                        pass  # consumer failure must not corrupt a valid download

            emit(0)
            def report(value: int) -> None:
                if type(value) is int and min(99, value) > self.get_status().progress:
                    emit(value)
            self._manager.download_updates(self._candidate, progress_callback=report)
            pending = self._pending()
            target = self._candidate.TargetFullRelease
            if (pending is None or (pending.Version, pending.FileName, pending.Size)
                    != (target.Version, target.FileName, target.Size)):
                raise ValueError('Downloaded package not pending')
            emit(100, complete=True)
            return self._set('downloaded')
        except Exception:
            return self._failure('download_failed')
        finally:
            self._operation.release()

    def _verified_package(self, target: Any, *, deadline: float | None = None) -> Path:
        def within_budget() -> None:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError('Verification budget exhausted')
        within_budget()
        self._validate_asset(target)
        pending = self._pending()
        if (pending is None or (pending.PackageId, pending.Version, pending.FileName, pending.Size)
                != (target.PackageId, target.Version, target.FileName, target.Size)
                or _parse_version(target.Version) <= _parse_version(self._manager.get_current_version())):
            raise ValueError('Pending asset mismatch')
        assert self._feed is not None
        directory = self._package_directory(self._feed, self._manager).resolve(strict=True)
        path = directory / target.FileName
        if path.is_symlink() or path.resolve(strict=True).parent != directory:
            raise ValueError('Package escapes cache')
        with path.open('rb') as stream:
            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                within_budget()
                digest.update(chunk)
            if path.stat().st_size != target.Size or digest.hexdigest() != target.SHA256.lower():
                raise ValueError('Package integrity mismatch')
        with ZipFile(path) as archive:
            specs = [name for name in archive.namelist() if '/' not in name and name.endswith('.nuspec')]
            if len(specs) != 1 or archive.getinfo(specs[0]).file_size > 1024 * 1024:
                raise ValueError('Invalid package manifest')
            identity = _manifest_identity(archive.read(specs[0]))
        if identity != (self._feed.package_id, target.Version, self._feed.channel):
            raise ValueError('Package identity mismatch')
        within_budget()
        return path

    def prepare_install(self) -> InstallHandoffResult:
        """Worker-only: refresh trusted feed and attest bytes; never starts Update.exe."""
        if not self._operation.acquire(blocking=False):
            return InstallHandoffResult('busy')
        try:
            self._prepared = None
            if self._handoff_started or self._gate() is not None:
                return InstallHandoffResult('denied')
            info = self._manager.check_for_updates()
            if info is None or info.IsDowngrade:
                raise ValueError('No trusted install candidate')
            target = info.TargetFullRelease
            path = self._verified_package(target)
            token = secrets.token_urlsafe(32)
            self._prepared = (token, self._feed, self._manager.get_current_version(), target, path)
            return InstallHandoffResult('ready', target.Version, token)
        except Exception:
            return InstallHandoffResult('failed', public_message='更新包复验失败，请重新检查并下载更新。')
        finally:
            self._operation.release()

    def handoff(self, token: str, shutdown: ShutdownResult, *, verification_seconds: float = 5.0) -> InstallHandoffResult:
        """Exit-entrypoint only. No network, cleanup, immediate exit, or forced restart."""
        if not isinstance(shutdown, ShutdownResult) or not shutdown.can_apply_update:
            return InstallHandoffResult('denied', public_message='安全关闭证据不完整，未启动更新安装。')
        if not self._operation.acquire(blocking=False):
            return InstallHandoffResult('busy')
        guard = None
        try:
            deadline = time.monotonic() + min(5.0, max(0.0, verification_seconds))
            prepared = self._prepared
            if (self._handoff_started or prepared is None or token != prepared[0]
                    or self._feed != prepared[1] or self._gate() is not None
                    or self._manager.get_current_version() != prepared[2]):
                return InstallHandoffResult('denied')
            target = prepared[3]
            guard = _PackageReadGuard(prepared[4])
            if self._verified_package(target, deadline=deadline) != prepared[4]:
                raise ValueError('Package location changed')
            self._prepared = None  # consume BEFORE the SDK boundary, including exceptions
            self._manager.wait_exit_then_apply_updates(target, silent=False, restart=True)
            self._handoff_started = True
            self._handoff_guard = guard
            return InstallHandoffResult('started', target.Version)
        except Exception:
            self._prepared = None
            return InstallHandoffResult('failed', public_message='未能交接更新安装，应用将正常退出；请重新启动后重试。')
        finally:
            if guard is not None and not self._handoff_started:
                guard.close()
            self._operation.release()
