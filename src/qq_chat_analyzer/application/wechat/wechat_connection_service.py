"""Translate WeChat database readiness into a user-facing connection status.

This module is the WeChat counterpart of
:mod:`~qq_chat_analyzer.application.qq.qq_connection_service`. It probes the
provider's existing resolver surface and returns a stable status instead of
leaking provider exceptions to a caller such as the GUI.

Deliberate boundaries:

* The shared provider factory loads the application configuration and builds
  the provider. A provider can also be injected directly for local validation. GUI
  and Facade callers never pass data roots, keys, or runtime paths directly.
* It calls the same resolver probes used by
  :class:`~qq_chat_analyzer.providers.wechat_database_provider
  .WeChatDatabaseProvider` and never calls ``list_sessions`` or
  ``read_session_rows``, so a status check does not read chat content.
* ``check_status()`` never raises. Every failure collapses into a status with
  a safe message and an actionable hint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...providers.wechat_database_provider import (
    DatabaseNotFound,
    KeyUnavailable,
    WcdbHelperNotFound,
    WcdbLibraryNotFound,
)
from .wechat_environment_config import (
    WeChatConfigCorrupted,
    WeChatConfigNotFound,
    WeChatEnvironmentConfigError,
)

from .wechat_provider_factory import WeChatProviderFactory


MESSAGE_AVAILABLE = (
    "\u5fae\u4fe1\u6570\u636e\u6e90\u53ef\u7528\uff0c"
    "\u53ef\u4ee5\u5f00\u59cb\u5206\u6790\u3002"
)
ACTION_HINT_AVAILABLE = (
    "\u53ef\u4ee5\u5f00\u59cb\u9009\u62e9\u4f1a\u8bdd\u5e76\u5206\u6790\u3002"
)
MESSAGE_DATA_MISSING = (
    "未找到微信数据位置。"
    "请确认微信已在本机登录过，或手动选择存储文件夹。"
)
ACTION_HINT_DATA_MISSING = (
    "请确认微信已登录并生成数据，或手动选择存储文件夹。"
)
MESSAGE_KEY_MISSING = (
    "尚未获取微信读取授权，暂时无法读取微信数据。"
)
ACTION_HINT_KEY_MISSING = (
    "请保持微信电脑版打开，然后在余音中重新点击连接。"
)
MESSAGE_RUNTIME_MISSING = (
    "微信连接组件不完整，暂时无法读取微信数据。"
)
ACTION_HINT_RUNTIME_MISSING = (
    "请重新安装余音后重试。"
)
MESSAGE_UNKNOWN = (
    "\u65e0\u6cd5\u786e\u8ba4\u5fae\u4fe1\u6570\u636e\u6e90\u72b6\u6001\uff0c"
    "\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"
)
ACTION_HINT_UNKNOWN = (
    "请稍后重试。"
)
MESSAGE_CONFIG_MISSING = (
    "尚未完成微信连接设置，请先完成微信连接设置。"
)
ACTION_HINT_CONFIG_MISSING = (
    "请先完成微信连接设置，再连接微信。"
)
MESSAGE_CONFIG_CORRUPTED = (
    "微信连接设置无法使用，请重新设置。"
)
ACTION_HINT_CONFIG_CORRUPTED = (
    "请重新设置微信连接。"
)


@dataclass(frozen=True, slots=True)
class WeChatConnectionStatus:
    """User-facing snapshot of the WeChat database connection state.

    ``available`` is the only flag a caller should gate on. The other flags
    explain why it is false, while ``message`` and ``action_hint`` tell the
    user what to do next.
    """

    available: bool
    data_found: bool
    db_key_available: bool
    runtime_available: bool
    message: str
    action_hint: str


class WeChatConnectionService:
    """Turn WeChat provider readiness into a stable user status."""

    def __init__(
        self,
        provider: Any | None = None,
        *,
        provider_factory: WeChatProviderFactory | None = None,
    ) -> None:
        self._provider = provider
        self._provider_factory = provider_factory
        if provider is None and provider_factory is None:
            self._provider_factory = WeChatProviderFactory()

    def provider(self) -> Any:
        """Return the provider this service probes.

        When a shared :class:`~qq_chat_analyzer.application.wechat
        .wechat_provider_factory.WeChatProviderFactory` is injected, the
        instance comes from that factory, so the status check and the session
        read path observe exactly the same provider and configuration.
        """
        if self._provider_factory is not None:
            return self._provider_factory.create()
        return self._provider

    def check_status(self) -> WeChatConnectionStatus:
        """Load config, build a provider, and translate the result."""
        if self._provider_factory is not None or self._provider is None:
            config_status = self._load_config_status()
            if config_status is not None:
                return config_status

        data_found = self._probe_data()
        key_available = self._probe_key()
        runtime_available = self._probe_runtime()

        if (
            data_found is None
            or key_available is None
            or runtime_available is None
        ):
            return self._unknown_status(
                data_found,
                key_available,
                runtime_available,
            )

        if not data_found:
            return WeChatConnectionStatus(
                available=False,
                data_found=False,
                db_key_available=key_available,
                runtime_available=runtime_available,
                message=MESSAGE_DATA_MISSING,
                action_hint=ACTION_HINT_DATA_MISSING,
            )
        if not key_available:
            return WeChatConnectionStatus(
                available=False,
                data_found=True,
                db_key_available=False,
                runtime_available=runtime_available,
                message=MESSAGE_KEY_MISSING,
                action_hint=ACTION_HINT_KEY_MISSING,
            )
        if not runtime_available:
            return WeChatConnectionStatus(
                available=False,
                data_found=True,
                db_key_available=True,
                runtime_available=False,
                message=MESSAGE_RUNTIME_MISSING,
                action_hint=ACTION_HINT_RUNTIME_MISSING,
            )

        return WeChatConnectionStatus(
            available=True,
            data_found=True,
            db_key_available=True,
            runtime_available=True,
            message=MESSAGE_AVAILABLE,
            action_hint=ACTION_HINT_AVAILABLE,
        )

    # ---------------------------------------------------------------- internals

    def _load_config_status(self) -> WeChatConnectionStatus | None:
        try:
            self._provider = self.provider()
        except WeChatConfigNotFound:
            return self._config_missing_status()
        except (WeChatConfigCorrupted, WeChatEnvironmentConfigError):
            return self._config_corrupted_status()
        except Exception:
            return self._unknown_status(None, None, None)
        return None

    def _probe_data(self) -> bool | None:
        try:
            self._provider._session_db_path()
        except DatabaseNotFound:
            return False
        except Exception:
            return None
        return True

    def _probe_key(self) -> bool | None:
        try:
            key = self._provider._resolve_key()
        except KeyUnavailable:
            return False
        except Exception:
            return None
        return bool(key and key.strip())

    def _probe_runtime(self) -> bool | None:
        try:
            self._provider._resolve_helper()
            self._provider._resolve_library()
        except (WcdbHelperNotFound, WcdbLibraryNotFound):
            return False
        except Exception:
            return None
        return True

    def _config_missing_status(self) -> WeChatConnectionStatus:
        return WeChatConnectionStatus(
            available=False,
            data_found=False,
            db_key_available=False,
            runtime_available=False,
            message=MESSAGE_CONFIG_MISSING,
            action_hint=ACTION_HINT_CONFIG_MISSING,
        )

    def _config_corrupted_status(self) -> WeChatConnectionStatus:
        return WeChatConnectionStatus(
            available=False,
            data_found=False,
            db_key_available=False,
            runtime_available=False,
            message=MESSAGE_CONFIG_CORRUPTED,
            action_hint=ACTION_HINT_CONFIG_CORRUPTED,
        )

    def _unknown_status(
        self,
        data_found: bool | None,
        key_available: bool | None,
        runtime_available: bool | None,
    ) -> WeChatConnectionStatus:
        return WeChatConnectionStatus(
            available=False,
            data_found=bool(data_found),
            db_key_available=bool(key_available),
            runtime_available=bool(runtime_available),
            message=MESSAGE_UNKNOWN,
            action_hint=ACTION_HINT_UNKNOWN,
        )


__all__ = [
    "WeChatConnectionService",
    "WeChatConnectionStatus",
]
