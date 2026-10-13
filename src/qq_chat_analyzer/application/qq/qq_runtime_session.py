"""The single bridge credential of the runtime Echo launched.

Echo owns at most one NapCat runtime per process (one fixed bridge port, one
launch serialized by the auth bridge), so exactly one credential exists at a
time. The launcher mints a fresh value for each launch. Cached status/metadata
providers follow the current session; snapshot clients retain one launch's
credential across acquire, retries and cleanup. Stopping the owned tree or
observing its exit retires the credential.

The value never reaches the repository, a configuration file, a log line or a
report.  It travels only through the launched child's private environment block
and a request header. Each bridge accepts only the credential of its launch.
"""

from __future__ import annotations

import re
import secrets
import threading
from ..shutdown_models import ShutdownStatus

#: 256 bits of entropy, lowercase hex: the same shape rule the runtime identity
#: uses, so no encoding question arises when the value crosses the env/header.
CREDENTIAL_BYTES = 32
_BRIDGE_CREDENTIAL = re.compile(r"[0-9a-f]{64}\Z")
BRIDGE_CREDENTIAL_PATTERN = r"[0-9a-f]{64}"


def mint_bridge_credential() -> str:
    """Return a new high-entropy credential."""
    return secrets.token_hex(CREDENTIAL_BYTES)


def is_bridge_credential(value: object) -> bool:
    """Return whether ``value`` has the required credential shape."""
    return isinstance(value, str) and _BRIDGE_CREDENTIAL.fullmatch(value) is not None


class QQRuntimeSession:
    """Own the credential of the one bridge instance Echo launched."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._credential: str | None = None
        self._process: object | None = None
        self._closing = False
        self._pending_launch = False
        self._unverified_launch = False
        self._owned_history: dict[int, object] = {}

    def begin_launch(self) -> str:
        """Mint a new credential for a launch and make it the current one.

        A previous value is replaced, never kept: an old credential must never
        match a new instance, and a later request must never retry with it.
        """
        credential = mint_bridge_credential()
        with self._lock:
            if self._closing:
                raise RuntimeError('QQ runtime launch is closed')
            if self._pending_launch:
                self._unverified_launch = True
            self._credential = credential
            self._process = None
            self._pending_launch = True
        return credential

    def bind_process(self, process: object, credential: str) -> None:
        """Associate the owned process tree with exactly this launch."""
        with self._lock:
            # Retiring a credential must not erase an unverified owned tree.
            self._owned_history[id(process)] = process
            if self._credential == credential:
                self._process = process
                self._pending_launch = False

    def shutdown(self) -> ShutdownStatus:
        """Seal launches and retire secrets, retaining process exit evidence."""
        from ...runtime.windows_job import WindowsJobProcess
        with self._lock:
            self._closing = True
            self._credential = None
            self._process = None
            if self._pending_launch or self._unverified_launch:
                return ShutdownStatus.UNKNOWN
            return (ShutdownStatus.SUCCESS if all(
                type(process) is WindowsJobProcess and process.exit_verified
                for process in self._owned_history.values()) else ShutdownStatus.UNKNOWN)

    def retire_process(self, process: object) -> None:
        """Retire a cancelled late launch without affecting a newer process."""
        with self._lock:
            if self._process is process:
                self._credential = None
                self._process = None

    def credential(self) -> str | None:
        """Return the current credential, or ``None`` when none is live.

        Read at request time: a launch that replaced the value is picked up by
        cached status/metadata providers without rebuilding them. Snapshot
        clients pin this value to their own lifecycle instead.
        """
        with self._lock:
            process = self._process
            if process is not None:
                tree_running = getattr(process, "tree_running", None)
                try:
                    exited = (getattr(process, "closed", False) is True or
                              (callable(tree_running) and not tree_running()))
                    if not callable(tree_running):
                        exited = exited or process.poll() not in (None, 0)
                except Exception:
                    exited = True
                if exited:
                    self._credential = None
                    self._process = None
            return self._credential

    def retire(self, credential: str | None = None) -> None:
        """Drop the current credential.

        With no argument the current value is dropped.  With a value, it is
        dropped only if it is still the current one, so a failed launch cannot
        clear the credential of an instance that is still running.
        """
        with self._lock:
            if credential is None or self._credential == credential:
                self._credential = None
                self._process = None

    def __repr__(self) -> str:
        """Never render the credential, not even inside a traceback."""
        state = "set" if self.credential() is not None else "unset"
        return f"{type(self).__name__}(credential={state})"

    __str__ = __repr__


_DEFAULT_SESSION = QQRuntimeSession()


def default_qq_runtime_session() -> QQRuntimeSession:
    """Return the process-wide session used when none was injected explicitly.

    Mirrors ``default_qq_process_registry()``: the desktop composition root
    injects its own instance, and unwired callers and factory defaults still
    converge on one owner instead of silently having no credential.
    """
    return _DEFAULT_SESSION


__all__ = [
    "BRIDGE_CREDENTIAL_PATTERN",
    "CREDENTIAL_BYTES",
    "QQRuntimeSession",
    "default_qq_runtime_session",
    "is_bridge_credential",
    "mint_bridge_credential",
]
