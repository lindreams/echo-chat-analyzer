"""Application-layer setup for the WeChat environment.

The connection layer can only report "not configured" until something writes
``wechat.json``. This service is that something: it inspects the stored
configuration, saves a new one on the user's behalf, and refreshes the shared
provider factory so the next read observes the new settings.

Deliberate boundaries:

* No database access and no WeChat parsing happen here. When no key is
  configured, an injected key service may acquire one; otherwise this service
  only reads and writes application configuration.
* No GUI code. A widget calls this through
  :class:`~qq_chat_analyzer.application.facade.ChatAnalyzerFacade` and never
  writes JSON itself.
* ``check_setup()`` never raises: an unreadable or damaged config becomes a
  status, so a caller can render guidance instead of a traceback.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from ..errors import ApplicationServiceError
from .wechat_connection_progress import WeChatConnectionProgress
from .wechat_data_detector import (
    detect_wechat_data_roots,
    is_valid_wechat_data_root,
)
from .wechat_environment_config import (
    WeChatConfigNotFound,
    WeChatEnvironmentConfig,
    WeChatEnvironmentConfigLoader,
    WeChatEnvironmentConfigWriter,
    resolve_wechat_runtime_pair,
)


_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.wechat_setup_service")


MESSAGE_CONFIG_MISSING = (
    "尚未完成微信连接设置。"
)
ACTION_HINT_CONFIG_MISSING = (
    "请先完成微信连接设置，再连接微信。"
)
MESSAGE_CONFIG_READY = (
    "微信连接设置已保存。"
)
ACTION_HINT_CONFIG_READY = (
    "可以返回微信入口开始连接。"
)
MESSAGE_CONFIG_INVALID = (
    "微信连接设置无法使用。"
)
ACTION_HINT_CONFIG_INVALID = (
    "请重新设置微信连接。"
)


class WeChatSetupState(Enum):
    """Coarse state of the stored WeChat environment configuration."""

    CONFIG_MISSING = "config_missing"
    CONFIG_READY = "config_ready"
    CONFIG_INVALID = "config_invalid"


@dataclass(frozen=True, slots=True)
class WeChatSetupStatus:
    """User-facing snapshot of the stored WeChat configuration."""

    state: WeChatSetupState
    configured: bool
    message: str
    action_hint: str
    config_path: Path | None = None


class WeChatSetupService:
    """Inspect and persist the WeChat environment configuration."""

    class InvalidEnvironment(ApplicationServiceError):
        """Raised when the caller supplies something that is not a config."""

        code = "wechat_invalid_environment"
        public_message = (
            "微信连接设置无效，请重新填写。"
        )

    def __init__(
        self,
        *,
        config_loader: Any = None,
        config_writer: Any = None,
        provider_factory: Any = None,
        connection_service: Any = None,
        key_service: Any = None,
        data_root_detector: Callable[[], Path | None] | None = None,
        data_roots_detector: Callable[[], list[Path]] | None = None,
    ) -> None:
        self._config_loader = config_loader or WeChatEnvironmentConfigLoader()
        self._config_writer = config_writer or WeChatEnvironmentConfigWriter()
        self._provider_factory = provider_factory
        self._connection_service = connection_service
        self._key_service = key_service
        self._data_root_detector = data_root_detector
        self._data_roots_detector = (
            data_roots_detector or detect_wechat_data_roots
        )
        self._key_request_lock = threading.Lock()
        self._key_request_generation = 0
        self._key_commit_lock = threading.Lock()

    def check_setup(self) -> WeChatSetupStatus:
        """Report whether a usable configuration is stored, never raising."""
        config_path = self._config_path()
        try:
            self._load_config_or_default()
        except WeChatConfigNotFound:
            return WeChatSetupStatus(
                state=WeChatSetupState.CONFIG_MISSING,
                configured=False,
                message=MESSAGE_CONFIG_MISSING,
                action_hint=ACTION_HINT_CONFIG_MISSING,
                config_path=config_path,
            )
        except Exception:
            return WeChatSetupStatus(
                state=WeChatSetupState.CONFIG_INVALID,
                configured=False,
                message=MESSAGE_CONFIG_INVALID,
                action_hint=ACTION_HINT_CONFIG_INVALID,
                config_path=config_path,
            )

        return WeChatSetupStatus(
            state=WeChatSetupState.CONFIG_READY,
            configured=True,
            message=MESSAGE_CONFIG_READY,
            action_hint=ACTION_HINT_CONFIG_READY,
            config_path=config_path,
        )

    def detect_wechat_data_root(self) -> Path | None:
        """Return a detected local WeChat data directory, or ``None``."""
        if self._data_root_detector is not None:
            try:
                detected = self._data_root_detector()
            except Exception:
                return None
            if detected is None:
                return None
            detected_path = Path(detected)
            if is_valid_wechat_data_root(detected_path):
                return detected_path
            return None
        roots = self.detect_wechat_data_roots()
        if len(roots) == 1:
            return roots[0]
        return None

    def detect_wechat_data_roots(self) -> list[Path]:
        """Return every valid WeChat data directory detected locally.

        The caller decides what to do with several candidates; this service
        never picks one on the user's behalf.
        """
        saved = self._saved_valid_data_root()
        if saved is not None:
            return [saved]

        try:
            detected = self._data_roots_detector()
        except Exception:
            return []
        roots: list[Path] = []
        for value in detected or ():
            if value is None:
                continue
            path = Path(value)
            if is_valid_wechat_data_root(path) and path not in roots:
                roots.append(path)
        if len(roots) == 1 and is_valid_wechat_data_root(roots[0]):
            self._persist_detected_data_root(roots[0])
        return roots

    def save_environment(self, config: WeChatEnvironmentConfig) -> Any:
        """Persist a config, refresh the provider, and re-check connection.

        This only persists configuration. Acquiring the database key needs
        WeChat to be at a login moment, so it belongs to the connect flow via
        :meth:`acquire_db_key`; requiring it here made saving a data root fail
        whenever the user was not logging in. An explicit ``db_key`` on the
        incoming config is still written through untouched.

        The factory is invalidated only after a successful write, so a failed
        save leaves the previously working provider untouched. The return
        value is the refreshed connection status when a connection service is
        available, otherwise ``None``.
        """
        if not isinstance(config, WeChatEnvironmentConfig):
            raise self.InvalidEnvironment()

        config = self._merge_existing_config(config)
        config = self._apply_default_runtime(config)
        self._config_writer.save(config)

        if self._provider_factory is not None:
            self._provider_factory.invalidate()

        if self._connection_service is None:
            return None
        return self._connection_service.check_status()

    def verify_connection(self) -> None:
        """Prove the current key can read the configured database.

        Called right before session loading. A structurally valid but
        unreadable ``session.db`` (wrong login, or a directory that does not
        belong to the current account) must surface as the provider's
        :class:`DatabaseUnreadable` instead of ending as a generic query
        failure, so the caller can offer another data location.

        The verification itself belongs to the provider; this method only
        picks the provider the following session read would use, so the
        verification and the read can never disagree about configuration.
        Returns without verifying when no provider factory is wired, the same
        way the other optional collaborators of this service degrade.
        """
        factory = self._provider_factory
        if factory is None:
            return
        provider = factory.create()
        verify = getattr(provider, "verify_readable", None)
        if not callable(verify):
            return
        try:
            verify()
        except Exception:
            results = self._probe_wechat_databases(provider)
            if self._recover_unique_readable_database(provider, results):
                return
            raise

    def acquire_db_key(
        self,
        progress: Callable[[WeChatConnectionProgress], None] | None = None,
        *, cancel_event: threading.Event | None = None,
    ) -> str | None:
        """Acquire the WeChat database key and persist it, for the connect flow.

        Returns the key, or ``None`` when no key service is configured. A
        failure propagates the key service's own user-safe error so the caller
        can show it verbatim. ``progress`` is forwarded to the key service so
        acquisition milestones reach the caller without native details.
        """
        if self._key_service is None:
            return None

        with self._key_request_lock:
            self._key_request_generation += 1
            generation = self._key_request_generation

        def check_current_request():
            with self._key_request_lock:
                current = generation == self._key_request_generation
            if not current or (cancel_event is not None and cancel_event.is_set()):
                from .wechat_key_service import WeChatKeyUnavailable
                raise WeChatKeyUnavailable("微信连接已取消。", code="wechat_key_cancelled")

        check_current_request()
        _LOGGER.info("[wechat setup] acquire_db_key progress=%s", progress is not None)
        if cancel_event is None or not cancel_event.is_set():
            retry = getattr(self._key_service, "retry_cleanup", None)
            if callable(retry):
                retry()  # Runs on the connection worker; never displaces acquire.
        options = {"cancel_event": cancel_event} if cancel_event is not None else {}
        key = self._key_service.acquire(progress=progress, **options)
        check_current_request()
        if not key or not key.strip():
            return None

        key = key.strip()
        try:
            stored = self._config_loader.load()
        except Exception:
            stored = WeChatEnvironmentConfig()

        config = self._apply_default_runtime(replace(stored, db_key=key))
        # Only connection workers wait here; GUI cancellation just sets its Event.
        # A stale read is rejected. An already-started save must finish (including
        # invalidation) before a newer request may commit, so it cannot overwrite it.
        with self._key_commit_lock:
            check_current_request()
            self._config_writer.save(config)
            if self._provider_factory is not None:
                self._provider_factory.invalidate()
            check_current_request()
        return key

    def shutdown(self):
        """Drain the key owner off the GUI thread; do not claim Node-hook proof."""
        from ..shutdown_models import ShutdownStatus
        if self._key_service is None:
            return ShutdownStatus.SUCCESS
        shutdown = getattr(self._key_service, "shutdown", None)
        if not callable(shutdown):
            return ShutdownStatus.UNKNOWN
        return shutdown(timeout=3.0)

    def disconnect(self) -> Any:
        """Release the current WeChat connection key without deleting data.

        The stored data root and runtime paths stay in ``wechat.json``; only
        the database key is cleared, so the next connect flow re-acquires a
        fresh key through the existing path. Provider and process-local key
        state are also dropped.
        """
        _LOGGER.info("[wechat setup] disconnect requested")
        try:
            stored = self._config_loader.load()
        except WeChatConfigNotFound:
            stored = None

        if stored is not None:
            config = self._apply_default_runtime(replace(stored, db_key=None))
            self._config_writer.save(config)
            if self._provider_factory is not None:
                self._provider_factory.invalidate()

        clear = getattr(self._key_service, "clear", None)
        if callable(clear):
            clear()

        if self._connection_service is None:
            return None
        return self._connection_service.check_status()

    # ---------------------------------------------------------------- internals

    def _merge_existing_config(
        self,
        config: WeChatEnvironmentConfig,
    ) -> WeChatEnvironmentConfig:
        """Keep advanced values already stored when the GUI submits only a root."""
        try:
            existing = self._config_loader.load()
        except Exception:
            return config
        return replace(
            config,
            db_key=config.db_key or existing.db_key,
            wcdb_cli_path=config.wcdb_cli_path or existing.wcdb_cli_path,
            wcdb_dll_path=config.wcdb_dll_path or existing.wcdb_dll_path,
        )

    def _probe_wechat_databases(self, provider: Any) -> list[Any]:
        """Return the provider's read-only candidate results, never raising."""
        probe = getattr(provider, "probe_session_databases", None)
        if not callable(probe):
            return []

        roots: list[Path] = []
        try:
            detected = self._data_roots_detector()
        except Exception:
            detected = ()
        for value in detected or ():
            if value is None:
                continue
            try:
                roots.append(Path(value))
            except Exception:
                continue
        try:
            results = probe(roots)
        except Exception:
            _LOGGER.debug("wechat database candidate probe skipped")
            return []
        try:
            return list(results or ())
        except Exception:
            return []

    def _recover_unique_readable_database(
        self,
        provider: Any,
        results: list[Any],
    ) -> bool:
        """Switch to one uniquely readable account root after a second verify."""
        readable = [
            result
            for result in results
            if bool(getattr(result, "readable", False))
        ]
        if len(readable) != 1:
            return False
        _LOGGER.info("wechat.database.recovery unique_candidate=true")

        data_root = getattr(readable[0], "data_root", None)
        if data_root is None or not is_valid_wechat_data_root(Path(data_root)):
            return False

        with_data_root = getattr(provider, "with_data_root", None)
        if not callable(with_data_root):
            return False
        try:
            recovered_provider = with_data_root(Path(data_root))
            verify = getattr(recovered_provider, "verify_readable", None)
            if not callable(verify):
                return False
            verify()
        except Exception:
            _LOGGER.info("wechat.database.recovery verify_success=false")
            return False

        _LOGGER.info("wechat.database.recovery verify_success=true")
        if not self._persist_detected_data_root(Path(data_root)):
            _LOGGER.info("wechat.database.recovery persisted=false")
            return False
        _LOGGER.info("wechat.database.recovery persisted=true")
        return True

    def _saved_valid_data_root(self) -> Path | None:
        try:
            root = self._config_loader.load().data_root
        except Exception:
            return None
        if root is None or not is_valid_wechat_data_root(root):
            return None
        return root

    def _persist_detected_data_root(self, root: Path) -> bool:
        try:
            existing = self._config_loader.load()
        except Exception:
            existing = WeChatEnvironmentConfig()
        config = self._apply_default_runtime(
            replace(existing, data_root=root)
        )
        try:
            self._config_writer.save(config)
        except Exception:
            return False
        if self._provider_factory is not None:
            self._provider_factory.invalidate()
        return True

    @staticmethod
    def _apply_default_runtime(
        config: WeChatEnvironmentConfig,
    ) -> WeChatEnvironmentConfig:
        """Persist the config with the runtime pair the reader will resolve.

        The CLI and the DLL are chosen by the same policy used when reading, so
        a save can never write a pair that mixes this installation's binary with
        a surviving path from another one. ``data_root`` and ``db_key`` are
        carried through untouched.
        """
        return resolve_wechat_runtime_pair(config)

    def _config_path(self) -> Path | None:
        getter = getattr(self._config_loader, "config_path", None)
        if getter is None:
            return None
        try:
            return getter()
        except Exception:
            return None

    def _load_config_or_default(self) -> WeChatEnvironmentConfig:
        loader = getattr(self._config_loader, "load_or_default", None)
        if callable(loader):
            return loader()
        return self._config_loader.load()


__all__ = [
    "WeChatSetupService",
    "WeChatSetupState",
    "WeChatSetupStatus",
]
