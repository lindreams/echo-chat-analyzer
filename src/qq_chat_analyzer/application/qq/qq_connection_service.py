"""Translate Echo NapCat readiness into user-safe Desktop connection state."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from ...providers.napcat_qq_provider import NapCatQQProvider, NapCatQQWorkerGenerationChanged
from .qq_provider_factory import QQReconnectRequired
from .qq_environment_config import (
    QQConfigCorrupted,
    QQConfigNotFound,
    QQEnvironmentConfigError,
)


MESSAGE_AVAILABLE = "QQ 数据源已连接。"
MESSAGE_NOT_RUNNING = "QQ 服务未运行，QQ 数据源当前不可用。"
MESSAGE_LOGIN_REQUIRED = "QQ 需要先登录并授权才能读取聊天记录。"
MESSAGE_UNKNOWN_ERROR = "无法确认 QQ 数据源状态，请稍后重试。"
MESSAGE_CONFIG_MISSING = "QQ 数据源尚未连接。"
MESSAGE_CONFIG_INVALID = "QQ 数据源暂不可用，请稍后重试。"

ACTION_HINT_AVAILABLE = "可以开始选择 QQ 账号分析聊天记录。"
ACTION_HINT_START_RUNTIME = "请打开并登录 QQ 后重试。"
ACTION_HINT_AUTHORIZE = "请在 QQ 中完成登录授权后重试。"
ACTION_HINT_RETRY = "请稍后重试，或确认 QQ 已完成登录授权。"
ACTION_HINT_CONFIG_MISSING = "请点击「连接QQ」自动完成连接。"
ACTION_HINT_CONFIG_INVALID = "请稍后重试。"


@dataclass(frozen=True, slots=True)
class QQConnectionStatus:
    """QQ login and Direct DB readiness are separate facts."""

    available: bool
    runtime_running: bool
    qq_online: bool
    version: str | None
    message: str
    action_hint: str
    direct_db_ready: bool = False
    code: str | None = None


def runtime_running(status: Any) -> bool:
    return bool(getattr(status, "runtime_running", False))


class QQConnectionService:
    """Turn bridge readiness and QQ login state into a stable user status."""

    def __init__(
        self,
        provider: NapCatQQProvider | None = None,
        *,
        provider_factory: Any = None,
    ) -> None:
        if provider is None and provider_factory is None:
            raise TypeError(
                "QQConnectionService needs a provider or provider_factory"
            )
        self._injected_provider = provider
        self._provider_factory = provider_factory

    def provider(self) -> NapCatQQProvider:
        """Return the provider used for probes.

        When a shared provider factory is injected, the instance comes from
        that factory, so connection checks and session reads use the same
        configuration and provider.
        """
        if self._provider_factory is not None:
            return self._provider_factory.create()
        return self._injected_provider

    def check_status(self) -> QQConnectionStatus:
        """Probe once; collapse failures to a safe status."""
        provider = None
        try:
            provider = self.provider()
        except QQReconnectRequired:
            return self._reconnect_status()
        except QQConfigNotFound:
            return self._config_missing_status()
        except (QQConfigCorrupted, QQEnvironmentConfigError):
            return self._config_invalid_status()
        except NapCatQQWorkerGenerationChanged:
            if self._provider_factory is not None:
                self._provider_factory.require_reconnect(provider)
            return self._reconnect_status()
        except Exception:
            return self._unknown_status()

        try:
            snapshot = provider.status()
            running = snapshot.bridge_ready
            logged_in = running and snapshot.qq_online and bool(re.fullmatch(r"[1-9][0-9]{4,19}", snapshot.self_info.get("uin", "")))
            return QQConnectionStatus(
                available=logged_in, qq_online=logged_in,
                runtime_running=running, direct_db_ready=logged_in and snapshot.ready,
                version=None, message=MESSAGE_AVAILABLE if logged_in else MESSAGE_LOGIN_REQUIRED if running else MESSAGE_NOT_RUNNING,
                action_hint=ACTION_HINT_AVAILABLE if logged_in else ACTION_HINT_AUTHORIZE if running else ACTION_HINT_START_RUNTIME,
            )
        except NapCatQQWorkerGenerationChanged:
            if self._provider_factory is not None:
                self._provider_factory.require_reconnect(provider)
            return self._reconnect_status()
        except Exception:
            return self._unknown_status()

    def reconnect(self) -> None:
        if self._provider_factory is not None:
            self._provider_factory.reconnect()

    def _reconnect_status(self) -> QQConnectionStatus:
        return QQConnectionStatus(False, False, False, None,
                                  QQReconnectRequired.public_message, "请点击「重新连接」。",
                                  code=QQReconnectRequired.code)

    def _unknown_status(self) -> QQConnectionStatus:
        return QQConnectionStatus(
            available=False,
            runtime_running=False,
            qq_online=False,
            version=None,
            message=MESSAGE_UNKNOWN_ERROR,
            action_hint=ACTION_HINT_RETRY,
        )

    def _config_missing_status(self) -> QQConnectionStatus:
        return QQConnectionStatus(
            available=False,
            runtime_running=False,
            qq_online=False,
            version=None,
            message=MESSAGE_CONFIG_MISSING,
            action_hint=ACTION_HINT_CONFIG_MISSING,
        )

    def _config_invalid_status(self) -> QQConnectionStatus:
        return QQConnectionStatus(
            available=False,
            runtime_running=False,
            qq_online=False,
            version=None,
            message=MESSAGE_CONFIG_INVALID,
            action_hint=ACTION_HINT_CONFIG_INVALID,
        )
