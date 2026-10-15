"""Map passive QQ probes and auth waiting into safe connection snapshots.

The auth bridge owns launch, cancellation and process cleanup. This manager
only observes status and tracks whether that bridge is waiting for login.
"""

from __future__ import annotations

import logging
from typing import Any

from ..connection_models import ConnectionSnapshot, ConnectionState
from .qq_runtime_manager import QQRuntimeState
from .qq_connection_service import runtime_running


SOURCE_QQ = "qq"

MESSAGE_DISCONNECTED = "QQ \u5c1a\u672a\u8fde\u63a5\u3002"
MESSAGE_CONNECTED = "QQ \u5df2\u8fde\u63a5\u3002"
MESSAGE_STARTING = "\u6b63\u5728\u542f\u52a8 QQ \u8fd0\u884c\u73af\u5883..."
MESSAGE_WAITING_AUTH = (
    "QQ \u9700\u8981\u5148\u5b8c\u6210\u767b\u5f55\u6388\u6743\u3002"
)
MESSAGE_ERROR = (
    "\u65e0\u6cd5\u8fde\u63a5 QQ\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"
)
MESSAGE_UNAVAILABLE = "QQ \u6570\u636e\u6e90\u6682\u4e0d\u53ef\u7528\u3002"

HINT_CONNECT = "\u8bf7\u70b9\u51fb\u300c\u8fde\u63a5QQ\u300d\u81ea\u52a8\u5b8c\u6210\u8fde\u63a5\u3002"
HINT_CONNECTED = (
    "\u53ef\u4ee5\u5f00\u59cb\u9009\u62e9 QQ \u8d26\u53f7\u5206\u6790\u804a\u5929\u8bb0\u5f55\u3002"
)
HINT_WAITING_AUTH = (
    "\u8bf7\u5728 QQ \u4e2d\u5b8c\u6210\u767b\u5f55\u6388\u6743\u540e\u91cd\u8bd5\u3002"
)
HINT_RETRY = "\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"


_LOGGER = logging.getLogger("qq_chat_analyzer.desktop.qq_connection_manager")


class QQConnectionManager:
    """Report QQ connection state without starting a runtime."""

    def __init__(
        self,
        *,
        setup_service: Any = None,
        connection_service: Any = None,
    ) -> None:
        self._setup_service = setup_service
        self._connection_service = connection_service
        self._auth_waiting = False

    # ------------------------------------------------------------ inspection

    def get_snapshot(self) -> ConnectionSnapshot:
        """Report the current lifecycle state without starting anything.

        This is the passive question the GUI asks when a user selects QQ. It
        never launches a runtime, so selecting the source stays cheap.
        """
        if self._setup_service is None and self._connection_service is None:
            return self._unavailable()

        status = self._safe_connection_status()
        if status is None:
            if self._auth_waiting:
                return self._waiting_auth_snapshot()
            return self._snapshot(
                ConnectionState.DISCONNECTED,
                MESSAGE_DISCONNECTED,
                HINT_CONNECT,
            )
        snapshot = self._from_connection_status(status)
        if snapshot.code == "qq_reconnect_required":
            self._auth_waiting = False
            return snapshot
        if snapshot.state is ConnectionState.CONNECTED:
            self._auth_waiting = False
            return snapshot

        runtime_status = self._safe_runtime_status()
        if self._auth_waiting and self._runtime_failed(runtime_status):
            self._auth_waiting = False
            _LOGGER.info("[qq connection] runtime failed, leaving auth wait")
            return self._snapshot(
                ConnectionState.ERROR,
                MESSAGE_ERROR,
                HINT_RETRY,
            )
        if (
            snapshot.state is ConnectionState.DISCONNECTED
            and (
                self._auth_waiting
                or self._runtime_started(runtime_status)
            )
        ):
            _LOGGER.info(
                "[qq connection] runtime started, waiting for QQ login"
            )
            return self._waiting_auth_snapshot()
        return snapshot

    # --------------------------------------------------------------- actions

    def disconnect(self) -> ConnectionSnapshot:
        """Stop treating this lifecycle as connected and report disconnected.

        Process cleanup is owned by the caller (the auth bridge/facade); this
        only resets the manager's transient auth state so a later snapshot
        does not keep waiting for a login that was cancelled.
        """
        self._auth_waiting = False
        return self._snapshot(
            ConnectionState.DISCONNECTED,
            MESSAGE_DISCONNECTED,
            HINT_CONNECT,
        )

    def begin_auth_waiting(self) -> None:
        """Remember that a runtime-owned login window is waiting for auth."""
        self._auth_waiting = True

    def end_auth_waiting(self) -> None:
        """Stop treating bridge unavailability as an in-progress login."""
        self._auth_waiting = False

    # ------------------------------------------------------------- internals

    def _safe_connection_status(self) -> Any:
        """Ask the connection service once, swallowing every failure."""
        service = self._connection_service
        if service is None:
            return None
        try:
            return service.check_status()
        except Exception as error:
            _LOGGER.info(
                "[qq connection] status probe failed error=%s",
                type(error).__name__,
            )
            return None

    def _safe_runtime_status(self) -> Any:
        """Return the setup service's runtime status without raising."""
        service = self._setup_service
        if service is None:
            return None
        get_status = getattr(service, "get_runtime_status", None)
        if get_status is None:
            return None
        try:
            return get_status()
        except Exception:
            return None

    def _runtime_started(self, runtime_status: Any) -> bool:
        """Return whether the setup service reports a running runtime."""
        return getattr(runtime_status, "state", None) is QQRuntimeState.RUNNING

    def _runtime_failed(self, runtime_status: Any) -> bool:
        """Return whether the runtime reports an explicit fatal state."""
        state = getattr(runtime_status, "state", None)
        return state in (QQRuntimeState.ERROR, QQRuntimeState.UNAVAILABLE)

    def _waiting_auth_snapshot(self) -> ConnectionSnapshot:
        return self._snapshot(
            ConnectionState.WAITING_AUTH,
            MESSAGE_WAITING_AUTH,
            HINT_WAITING_AUTH,
        )

    def _from_connection_status(self, status: Any) -> ConnectionSnapshot:
        """Map one QQConnectionStatus onto the lifecycle vocabulary.

        The flags the connection service exposes map cleanly: available means
        the QQ data is usable (connected), a running service whose QQ data is
        not usable means the user still has to log in, and anything else is a
        plain disconnected state the user can act on.
        """
        if getattr(status, "code", None) == "qq_reconnect_required":
            return ConnectionSnapshot(ConnectionState.ERROR, SOURCE_QQ, status.message,
                                      status.action_hint, code="qq_reconnect_required")
        available = bool(getattr(status, "available", False))
        running = runtime_running(status)
        version = getattr(status, "version", None) or None
        message = _clean(getattr(status, "message", ""))
        action_hint = _clean(getattr(status, "action_hint", ""))

        if available:
            return self._snapshot(
                ConnectionState.CONNECTED,
                message or MESSAGE_CONNECTED,
                action_hint or HINT_CONNECTED,
                version=version,
            )
        if running and not available:
            return self._snapshot(
                ConnectionState.WAITING_AUTH,
                message or MESSAGE_WAITING_AUTH,
                action_hint or HINT_WAITING_AUTH,
                version=version,
            )
        return self._snapshot(
            ConnectionState.DISCONNECTED,
            message or MESSAGE_DISCONNECTED,
            action_hint or HINT_CONNECT,
            version=version,
        )

    def _unavailable(self) -> ConnectionSnapshot:
        return self._snapshot(
            ConnectionState.ERROR,
            MESSAGE_UNAVAILABLE,
            HINT_RETRY,
        )

    @staticmethod
    def _snapshot(
        state: ConnectionState,
        message: str,
        action_hint: str = "",
        *,
        version: str | None = None,
    ) -> ConnectionSnapshot:
        return ConnectionSnapshot(
            state=state,
            source=SOURCE_QQ,
            message=message,
            action_hint=action_hint,
            version=version,
        )


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = ["QQConnectionManager", "SOURCE_QQ"]
