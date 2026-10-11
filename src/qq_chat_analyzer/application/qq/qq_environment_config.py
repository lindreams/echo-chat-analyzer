"""Application-layer QQ environment configuration.

This module owns the durable settings that tell the QQ connection layer where
the local QQ client and Echo NapCat bridge live. It does not
start processes, read chat data, or make runtime decisions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ...resources import (
    default_qq_runtime_directory,
    user_data_dir,
)


CONFIG_DIRECTORY = "config"
CONFIG_FILENAME = "qq.json"
DEFAULT_NAPCAT_BRIDGE_URL = "http://127.0.0.1:40655"


class QQEnvironmentConfigError(Exception):
    """Base error for reading or writing the QQ environment config."""

    code = "qq_environment_config_error"
    public_message = "QQ 数据源暂不可用。"

    def __init__(
        self,
        public_message: str | None = None,
        *,
        code: str | None = None,
    ) -> None:
        self.code = code or type(self).code
        self.public_message = public_message or type(self).public_message
        super().__init__(self.public_message)


class QQConfigNotFound(QQEnvironmentConfigError):
    """Raised when no QQ environment config file exists yet."""

    code = "qq_config_not_found"
    public_message = "QQ 数据源尚未连接。"


class QQConfigCorrupted(QQEnvironmentConfigError):
    """Raised when the QQ environment config cannot be parsed safely."""

    code = "qq_config_corrupted"
    public_message = "QQ 数据源暂不可用，请重新连接。"


class QQConfigWriteFailed(QQEnvironmentConfigError):
    """Raised when the QQ environment config cannot be written safely."""

    code = "qq_config_write_failed"
    public_message = "QQ 数据源配置保存失败，请稍后重试。"


@dataclass(frozen=True, slots=True)
class QQEnvironmentConfig:
    """Durable QQ environment settings loaded from disk."""

    qq_install_path: Path | None = None
    runtime_directory: Path | None = None
    napcat_bridge_url: str = DEFAULT_NAPCAT_BRIDGE_URL
    version: str | None = "4.18.18"
    # None means legacy/unknown provenance; never infer ownership from a path.
    runtime_mode: str | None = None
    # Direct API configuration is explicit; unmarked historical disk paths are not.
    qq_install_path_explicit: bool = True


class QQEnvironmentConfigWriter:
    """Persist a QQ environment config as stable JSON."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        writer: Callable[[Path, str], None] | None = None,
    ) -> None:
        self._config_path = (
            Path(config_path)
            if config_path is not None
            else user_data_dir() / CONFIG_DIRECTORY / CONFIG_FILENAME
        )
        self._writer = writer or self._write_file

    def config_path(self) -> Path:
        return self._config_path

    def save(self, config: QQEnvironmentConfig) -> None:
        """Persist one config, raising a user-safe error on failure."""
        payload = {
            "qq_install_path": _stringify(config.qq_install_path),
            "runtime_directory": _stringify(config.runtime_directory),
            "napcat_bridge_url": (
                config.napcat_bridge_url or DEFAULT_NAPCAT_BRIDGE_URL
            ),
            "version": config.version or None,
        }
        if config.runtime_mode is not None:
            if config.runtime_mode not in ("managed", "custom"):
                raise QQConfigWriteFailed()
            payload["runtime_mode"] = config.runtime_mode
        if config.qq_install_path_explicit:
            payload["qq_install_path_explicit"] = True
        body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._writer(self._config_path, body)
        except Exception:
            raise QQConfigWriteFailed() from None

    @staticmethod
    def _write_file(path: Path, body: str) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as file:
            file.write(body)


class QQEnvironmentConfigLoader:
    """Load a QQ environment config from user data."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._config_path = (
            Path(config_path)
            if config_path is not None
            else user_data_dir() / CONFIG_DIRECTORY / CONFIG_FILENAME
        )

    def config_path(self) -> Path:
        return self._config_path

    def load(self) -> QQEnvironmentConfig:
        """Return a config, or raise a user-safe config error."""
        if not self._config_path.exists():
            raise QQConfigNotFound()

        try:
            with self._config_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise QQConfigCorrupted() from None

        if not isinstance(payload, dict):
            raise QQConfigCorrupted()
        runtime_mode = payload.get("runtime_mode")
        if runtime_mode is not None and runtime_mode not in ("managed", "custom"):
            raise QQConfigCorrupted()

        # Old Desktop settings may only contribute the installed QQ path.
        # Never reuse an old runtime directory, API endpoint or credential file.
        legacy = payload.get("runtime_backend") == "qce" or any(
            key in payload for key in ("qce_path", "security_path")
        ) and payload.get("runtime_backend") != "napcat"
        return QQEnvironmentConfig(
            qq_install_path=_path_value(payload.get("qq_install_path")),
            runtime_directory=None if legacy else _path_value(payload.get("runtime_directory")),
            napcat_bridge_url=DEFAULT_NAPCAT_BRIDGE_URL if legacy else (
                _string_value(payload.get("napcat_bridge_url")) or DEFAULT_NAPCAT_BRIDGE_URL
            ),
            version="4.18.18" if legacy else _string_value(payload.get("version")) or "4.18.18",
            runtime_mode=None if legacy else runtime_mode,
            qq_install_path_explicit=not legacy and payload.get("qq_install_path_explicit") is True,
        )

    def load_or_default(self) -> QQEnvironmentConfig:
        """Load valid saved paths or use the bundled Echo NapCat runtime."""
        try:
            config = self.load()
        except QQConfigNotFound:
            config = None
        if config is not None and config.runtime_mode == "managed":
            default = default_qq_environment_config()
            return QQEnvironmentConfig(
                qq_install_path=config.qq_install_path,
                qq_install_path_explicit=config.qq_install_path_explicit,
                runtime_directory=default.runtime_directory,
                napcat_bridge_url=default.napcat_bridge_url,
                version=default.version, runtime_mode="managed",
            )
        if config is not None and config.runtime_mode == "custom":
            return config
        if config is not None and _runtime_paths_available(config):
            return config
        default = default_qq_environment_config()
        return QQEnvironmentConfig(
            qq_install_path=config.qq_install_path if config else None,
            qq_install_path_explicit=config.qq_install_path_explicit if config else False,
            runtime_directory=default.runtime_directory,
            napcat_bridge_url=default.napcat_bridge_url,
            version=default.version,
            # A startup fallback does not establish ownership of a saved path.
            runtime_mode=default.runtime_mode if config is None else None,
        )

    def runtime_paths(self, *, prepare=False):
        """Share one resolved path object with setup, auth and Direct DB.

        Preparation always rechecks ownership and contents. Passive consumers
        reuse that object's paths until configuration changes; no writes occur.
        """
        from .qq_runtime_paths import resolve_runtime_paths
        config = self.load_or_default()
        cached = getattr(self, "_resolved_runtime", None)
        if prepare or cached is None or cached[0] != config:
            paths = resolve_runtime_paths(config, prepare=prepare)
            self._resolved_runtime = (config, paths)
        return self._resolved_runtime[1]


def bundled_qq_runtime_available() -> bool:
    """Return whether the bundled Echo NapCat entry files are present."""
    return _runtime_paths_available(default_qq_environment_config())


def default_qq_environment_config() -> QQEnvironmentConfig:
    return QQEnvironmentConfig(
        runtime_directory=default_qq_runtime_directory(), runtime_mode="managed"
    )


def _runtime_paths_available(config: QQEnvironmentConfig) -> bool:
    return bool(config.runtime_directory and all(
        (config.runtime_directory / name).is_file() for name in (
            "napcat.mjs", "NapCatWinBootMain.exe", "NapCatWinBootHook.dll",
            "plugins/napcat-plugin-echo/index.mjs", "plugins/napcat-plugin-echo/bridge.mjs",
        )
    ))


def _string_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _path_value(value: Any) -> Path | None:
    if isinstance(value, Path):
        return value
    text = _string_value(value)
    if text is None:
        return None
    return Path(text)


__all__ = [
    "DEFAULT_NAPCAT_BRIDGE_URL",
    "QQConfigCorrupted",
    "QQConfigNotFound",
    "QQConfigWriteFailed",
    "QQEnvironmentConfig",
    "QQEnvironmentConfigError",
    "QQEnvironmentConfigLoader",
    "QQEnvironmentConfigWriter",
    "bundled_qq_runtime_available",
    "default_qq_environment_config",
]
