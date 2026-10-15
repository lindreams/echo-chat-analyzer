"""Inspect and persist QQ configuration and expose passive runtime status.

The auth bridge owns connection actions and the login process lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from ..errors import ApplicationServiceError
from .qq_environment_config import (
    QQConfigNotFound,
    QQEnvironmentConfig,
    QQEnvironmentConfigLoader,
    QQEnvironmentConfigWriter,
)
from .qq_runtime_manager import QQRuntimeManager, QQRuntimeState, QQRuntimeStatus
from .qq_runtime_session import default_qq_runtime_session


MESSAGE_CONFIG_MISSING = "QQ 尚未连接。"
ACTION_HINT_CONFIG_MISSING = "请点击「连接QQ」自动完成连接。"
MESSAGE_CONFIG_READY = "QQ 已就绪。"
ACTION_HINT_CONFIG_READY = "可以开始选择 QQ 账号分析聊天记录。"
MESSAGE_CONFIG_INVALID = "QQ 数据源暂不可用。"
ACTION_HINT_CONFIG_INVALID = "请稍后重试。"
MESSAGE_RUNTIME_MISSING = "QQ 数据源暂不可用。"
ACTION_HINT_RUNTIME_MISSING = "请稍后重试。"
MESSAGE_RUNTIME_MANAGER_MISSING = "QQ 数据源暂不可用，请稍后重试。"
ACTION_HINT_RUNTIME_MANAGER_MISSING = "请稍后重试。"


class QQSetupState(str, Enum):
    """Coarse state of the stored QQ environment configuration."""

    CONFIG_MISSING = "config_missing"
    CONFIG_READY = "config_ready"
    CONFIG_INVALID = "config_invalid"
    RUNTIME_MISSING = "runtime_missing"


@dataclass(frozen=True, slots=True)
class QQSetupStatus:
    """User-facing snapshot of the stored QQ environment."""

    state: QQSetupState
    configured: bool
    runtime_available: bool
    message: str
    action_hint: str
    config_path: Path | None = None


class QQSetupService:
    """Inspect and persist the QQ environment configuration."""

    class InvalidEnvironment(ApplicationServiceError):
        """Raised when the caller supplies something that is not a config."""

        code = "qq_invalid_environment"
        public_message = (
            "QQ 连接参数无效，请重新填写。"
        )

    def __init__(
        self,
        *,
        config_loader: Any = None,
        config_writer: Any = None,
        provider_factory: Any = None,
        connection_service: Any = None,
        runtime_manager: Any = None,
        runtime_factory: Callable[[QQEnvironmentConfig], Any] | None = None,
        bridge_credential: object | None = None,
    ) -> None:
        self._config_loader = config_loader or QQEnvironmentConfigLoader()
        self._config_writer = config_writer or QQEnvironmentConfigWriter()
        self._provider_factory = provider_factory
        self._connection_service = connection_service
        self._runtime_manager = runtime_manager
        self._bridge_credential = bridge_credential or default_qq_runtime_session()
        self._runtime_factory = runtime_factory or (lambda config: default_runtime_factory(
            config, paths=self.get_runtime_paths(),
            path_preparer=lambda: self.get_runtime_paths(prepare=True),
            credential=self._bridge_credential))
        self._built_runtime_manager: Any = None

    def check_setup(self) -> QQSetupStatus:
        """Report whether a usable environment is stored, never raising."""
        config_path = self._config_path()
        try:
            config = self._load_config_or_default()
        except QQConfigNotFound:
            return QQSetupStatus(
                state=QQSetupState.CONFIG_MISSING,
                configured=False,
                runtime_available=False,
                message=MESSAGE_CONFIG_MISSING,
                action_hint=ACTION_HINT_CONFIG_MISSING,
                config_path=config_path,
            )
        except Exception:
            return QQSetupStatus(
                state=QQSetupState.CONFIG_INVALID,
                configured=False,
                runtime_available=False,
                message=MESSAGE_CONFIG_INVALID,
                action_hint=ACTION_HINT_CONFIG_INVALID,
                config_path=config_path,
            )

        if not self._runtime_complete(config):
            return QQSetupStatus(
                state=QQSetupState.RUNTIME_MISSING,
                configured=True,
                runtime_available=False,
                message=MESSAGE_RUNTIME_MISSING,
                action_hint=ACTION_HINT_RUNTIME_MISSING,
                config_path=config_path,
            )

        return QQSetupStatus(
            state=QQSetupState.CONFIG_READY,
            configured=True,
            runtime_available=True,
            message=MESSAGE_CONFIG_READY,
            action_hint=ACTION_HINT_CONFIG_READY,
            config_path=config_path,
        )

    def get_environment_config(self) -> QQEnvironmentConfig:
        """Return the effective QQ environment config (saved or default)."""
        return self._load_config_or_default()

    def get_runtime_paths(self, *, prepare=False):
        getter = getattr(self._config_loader, "runtime_paths", None)
        if callable(getter):
            return getter(prepare=prepare)
        from .qq_runtime_paths import resolve_runtime_paths
        return resolve_runtime_paths(self.get_environment_config(), prepare=prepare)

    def save_environment(self, config: QQEnvironmentConfig) -> Any:
        """Persist a config, refresh the provider, and re-check connection.

        The provider factory is invalidated only after a successful write. The
        return value is the refreshed QQ connection status when a connection
        service is available, otherwise ``None``.
        """
        if not isinstance(config, QQEnvironmentConfig):
            raise self.InvalidEnvironment()

        self._config_writer.save(config)

        if self._provider_factory is not None:
            self._provider_factory.invalidate()
        self._built_runtime_manager = None

        if self._connection_service is None:
            return None
        return self._connection_service.check_status()

    def get_runtime_status(self) -> QQRuntimeStatus:
        """Return the current QQ runtime lifecycle status."""
        config = self._load_runtime_config()
        if config is None or not self._runtime_complete(config):
            return self._runtime_unavailable_status(self.check_setup())
        return self._runtime_manager_for(config).get_status()

    # ---------------------------------------------------------------- internals

    @staticmethod
    def _runtime_complete(config: QQEnvironmentConfig) -> bool:
        from .qq_environment_config import _runtime_paths_available
        return _runtime_paths_available(config)

    def _config_path(self) -> Path | None:
        getter = getattr(self._config_loader, "config_path", None)
        if getter is None:
            return None
        try:
            return getter()
        except Exception:
            return None

    def _load_runtime_config(self) -> QQEnvironmentConfig | None:
        try:
            return self._load_config_or_default()
        except Exception:
            return None

    def _load_config_or_default(self) -> QQEnvironmentConfig:
        loader = getattr(self._config_loader, "load_or_default", None)
        if callable(loader):
            return loader()
        return self._config_loader.load()

    def _runtime_manager_for(self, config: QQEnvironmentConfig) -> Any:
        self._require_runtime_provenance(config)
        if self._runtime_manager is not None:
            return self._runtime_manager
        if self._built_runtime_manager is None:
            self._built_runtime_manager = self._runtime_factory(config)
        return self._built_runtime_manager

    @staticmethod
    def _require_runtime_provenance(config: QQEnvironmentConfig) -> None:
        if config.runtime_mode not in ("managed", "custom"):
            from .qq_runtime_paths import AmbiguousQQRuntime
            raise AmbiguousQQRuntime(AmbiguousQQRuntime.public_message)

    def _runtime_unavailable_status(
        self,
        config_status: QQSetupStatus,
    ) -> QQRuntimeStatus:
        return QQRuntimeStatus(
            state=QQRuntimeState.UNAVAILABLE,
            available=False,
            message=config_status.message or MESSAGE_RUNTIME_MANAGER_MISSING,
            action_hint=(
                config_status.action_hint
                or ACTION_HINT_RUNTIME_MANAGER_MISSING
            ),
        )


def default_runtime_factory(config: QQEnvironmentConfig, *, paths=None, path_preparer=None,
                            credential: object | None = None) -> Any:
    """Build a QQRuntimeManager from one QQ environment config.

    The health probe and the launcher share one credential session, so a runtime
    Echo just launched is reachable and a runtime Echo does not own is not.
    """
    from ...runtime import BundledQQRuntime, QQRuntimeConfig

    from ...providers.napcat_qq_provider import NapCatQQProvider
    from .qq_auth_bridge import default_auth_window_launcher
    from .qq_runtime_paths import resolve_runtime_paths
    paths = paths or resolve_runtime_paths(config)
    session = credential or default_qq_runtime_session()
    def healthy(url):
        status = NapCatQQProvider(url, timeout=1, credential=session).status()
        return status.bridge_ready and (config.runtime_mode != "managed" or status.runtime_id == paths.runtime_id)
    runtime = BundledQQRuntime(
        QQRuntimeConfig(executable_path=paths.program_root / "NapCatWinBootMain.exe",
                        working_directory=paths.work_root, base_url=config.napcat_bridge_url,
                        version=config.version),
        health_checker=healthy,
        launcher=lambda: default_auth_window_launcher(config, paths=(path_preparer() if path_preparer
                                          else resolve_runtime_paths(config, prepare=True)),
                                          credential=session)(),
    )
    return QQRuntimeManager(runtime)


__all__ = [
    "QQSetupService",
    "QQSetupState",
    "QQSetupStatus",
    "default_runtime_factory",
]
