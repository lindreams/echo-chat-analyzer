"""Compatibility exports; implementation lives in application.wechat."""

from .wechat.wechat_environment_config import (
    WeChatConfigCorrupted,
    WeChatConfigNotFound,
    WeChatConfigWriteFailed,
    WeChatEnvironmentConfig,
    WeChatEnvironmentConfigError,
    WeChatEnvironmentConfigLoader,
    WeChatEnvironmentConfigWriter,
    bundled_wechat_runtime_available,
    default_wechat_environment_config,
    resolve_wechat_runtime_pair,
)

__all__ = [
    "WeChatConfigCorrupted",
    "WeChatConfigNotFound",
    "WeChatConfigWriteFailed",
    "WeChatEnvironmentConfig",
    "WeChatEnvironmentConfigError",
    "WeChatEnvironmentConfigLoader",
    "WeChatEnvironmentConfigWriter",
    "bundled_wechat_runtime_available",
    "default_wechat_environment_config",
    "resolve_wechat_runtime_pair",
]
