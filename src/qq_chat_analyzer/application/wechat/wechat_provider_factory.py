"""Build the WeChat database provider from one configuration source.

This factory is the single place in the application layer that turns a
:class:`~qq_chat_analyzer.application.wechat.wechat_environment_config
.WeChatEnvironmentConfig` into a live WeChat provider.

Before this existed, the connection status check and the session/message read
path each constructed their own provider, so the status could report "ready"
from configured paths while the actual read ran against a provider that had
fallen back to default discovery. Sharing one factory keeps those two answers
consistent.

Deliberate boundaries:

* The provider's reading logic, ``wechat_db_adapter``, and the analysis core
  are untouched. This module only decides how a provider is constructed.
* Callers never pass a data root, key, or runtime path. Those come from the
  config loader.
* Construction failures collapse into :class:`WeChatProviderUnavailable`, so a
  native or import error never reaches a user as a traceback.
"""

from __future__ import annotations

from typing import Any, Callable

from ..errors import ApplicationServiceError
from .wechat_environment_config import (
    WeChatEnvironmentConfig,
    WeChatEnvironmentConfigError,
    WeChatEnvironmentConfigLoader,
)


class WeChatProviderUnavailable(ApplicationServiceError):
    """Raised when a provider cannot be built from the current config."""

    code = "wechat_provider_unavailable"
    public_message = (
        "\u65e0\u6cd5\u521d\u59cb\u5316\u5fae\u4fe1\u6570\u636e\u8bfb\u53d6\u7ec4\u4ef6\uff0c"
        "\u8bf7\u68c0\u67e5\u5fae\u4fe1\u73af\u5883\u914d\u7f6e\u3002"
    )


def default_provider_builder(config: WeChatEnvironmentConfig) -> Any:
    """Construct the real provider from one environment config."""
    from ...providers.wechat_database_provider import WeChatDatabaseProvider

    return WeChatDatabaseProvider(
        data_root=config.data_root,
        db_key=config.db_key,
        wcdb_cli_path=config.wcdb_cli_path,
        wcdb_dll_path=config.wcdb_dll_path,
        sticker_media_roots=config.sticker_media_roots,
    )


class WeChatProviderFactory:
    """Create and cache one provider built from the stored configuration.

    The instance is cached so every collaborator observes the same provider.
    Call :meth:`invalidate` after the configuration changes on disk to force
    the next :meth:`create` to reload it.
    """

    def __init__(
        self,
        *,
        config_loader: WeChatEnvironmentConfigLoader | None = None,
        provider_builder: Callable[[WeChatEnvironmentConfig], Any] | None = None,
    ) -> None:
        self._config_loader = config_loader or WeChatEnvironmentConfigLoader()
        self._provider_builder = provider_builder or default_provider_builder
        self._provider: Any | None = None

    def create(self) -> Any:
        """Return the shared provider, building it on first use.

        Config problems surface as the loader's own user-safe errors so a
        caller can distinguish "not configured yet" from "cannot start".
        """
        if self._provider is None:
            self._provider = self._build()
        return self._provider

    def invalidate(self) -> None:
        """Drop the cached provider so the next call reloads the config."""
        self._provider = None

    # ---------------------------------------------------------------- internals

    def _build(self) -> Any:
        config = self._config_loader.load_or_default()
        try:
            return self._provider_builder(config)
        except WeChatEnvironmentConfigError:
            raise
        except Exception:
            raise WeChatProviderUnavailable() from None


__all__ = [
    "WeChatProviderFactory",
    "WeChatProviderUnavailable",
    "default_provider_builder",
]
