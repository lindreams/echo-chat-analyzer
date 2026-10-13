"""Application-layer WeChat environment configuration.

This module owns the durable configuration that tells the WeChat connection
layer where the local data and native runtime live. It does not read
databases, parse chat messages, or make any runtime decision.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from ...resources import (
    default_wechat_wcdb_cli_path,
    default_wechat_wcdb_dll_path,
    user_data_dir,
)


CONFIG_DIRECTORY = "config"
CONFIG_FILENAME = "wechat.json"


class WeChatEnvironmentConfigError(Exception):
    """Base error for reading or validating the WeChat environment config."""

    code = "wechat_environment_config_error"
    public_message = "\u5fae\u4fe1\u73af\u5883\u914d\u7f6e\u65e0\u6cd5\u4f7f\u7528\u3002"

    def __init__(
        self,
        public_message: str | None = None,
        *,
        code: str | None = None,
    ) -> None:
        self.code = code or type(self).code
        self.public_message = public_message or type(self).public_message
        super().__init__(self.public_message)


class WeChatConfigNotFound(WeChatEnvironmentConfigError):
    """Raised when no configuration file exists yet."""

    code = "wechat_config_not_found"
    public_message = (
        "\u672a\u627e\u5230\u5fae\u4fe1\u73af\u5883\u914d\u7f6e\uff0c"
        "\u8bf7\u5148\u5b8c\u6210\u5fae\u4fe1\u73af\u5883\u8bbe\u7f6e\u3002"
    )


class WeChatConfigCorrupted(WeChatEnvironmentConfigError):
    """Raised when the configuration file cannot be parsed safely."""

    code = "wechat_config_corrupted"
    public_message = (
        "\u5fae\u4fe1\u73af\u5883\u914d\u7f6e\u635f\u574f\uff0c"
        "\u8bf7\u91cd\u65b0\u8bbe\u7f6e\u3002"
    )


class WeChatConfigWriteFailed(WeChatEnvironmentConfigError):
    """Raised when the configuration file cannot be written safely."""

    code = "wechat_config_write_failed"
    public_message = (
        "\u5fae\u4fe1\u73af\u5883\u914d\u7f6e\u4fdd\u5b58\u5931\u8d25\uff0c"
        "\u8bf7\u68c0\u67e5\u5199\u5165\u6743\u9650\u540e\u91cd\u8bd5\u3002"
    )


@dataclass(frozen=True, slots=True)
class WeChatEnvironmentConfig:
    """Durable WeChat environment settings loaded from disk."""

    data_root: Path | None = None
    db_key: str | None = None
    wcdb_cli_path: Path | None = None
    wcdb_dll_path: Path | None = None


class WeChatEnvironmentConfigWriter:
    """Persist a WeChat environment config as stable JSON.

    The writer owns only serialization: it creates the parent directory,
    writes a sorted, stable JSON object, and converts every failure into
    :class:`WeChatConfigWriteFailed` so callers never see an OS error.
    """

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

    def save(self, config: WeChatEnvironmentConfig) -> None:
        """Persist one config, raising a user-safe error on failure."""
        payload = {
            "data_root": _stringify(config.data_root),
            "db_key": config.db_key if config.db_key else None,
            "wcdb_cli_path": _stringify(config.wcdb_cli_path),
            "wcdb_dll_path": _stringify(config.wcdb_dll_path),
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._writer(self._config_path, body)
        except Exception:
            raise WeChatConfigWriteFailed() from None

    @staticmethod
    def _write_file(path: Path, body: str) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as file:
            file.write(body)


def _stringify(value: Path | str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class WeChatEnvironmentConfigLoader:
    """Load a WeChat environment config from user data."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._config_path = (
            Path(config_path)
            if config_path is not None
            else user_data_dir() / CONFIG_DIRECTORY / CONFIG_FILENAME
        )

    def config_path(self) -> Path:
        return self._config_path

    def load(self) -> WeChatEnvironmentConfig:
        """Return a config, or raise a user-safe config error."""
        if not self._config_path.exists():
            raise WeChatConfigNotFound()

        try:
            with self._config_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise WeChatConfigCorrupted() from None

        if not isinstance(payload, dict):
            raise WeChatConfigCorrupted()

        return WeChatEnvironmentConfig(
            data_root=_path_value(payload.get("data_root")),
            db_key=_string_value(payload.get("db_key")),
            wcdb_cli_path=_path_value(payload.get("wcdb_cli_path")),
            wcdb_dll_path=_path_value(payload.get("wcdb_dll_path")),
        )

    def load_or_default(self) -> WeChatEnvironmentConfig:
        """Load user config with one consistent runtime pair, or use defaults.

        A saved pair is resolved by :func:`resolve_wechat_runtime_pair`, so a
        saved Portable path is carried over to this Setup install as a pair.
        """
        try:
            config = self.load()
        except WeChatConfigNotFound:
            config = None
        if config is None:
            return _bundled_runtime_config()

        return resolve_wechat_runtime_pair(config)


def bundled_wechat_runtime_available() -> bool:
    """Return whether bundled WeChat runtime files are present."""
    return (
        default_wechat_wcdb_cli_path().is_file()
        and default_wechat_wcdb_dll_path().is_file()
    )


def _bundled_runtime_config() -> WeChatEnvironmentConfig:
    """Return the bundled CLI/DLL pair, or raise when it is not installed."""
    if not bundled_wechat_runtime_available():
        raise WeChatConfigNotFound()
    return default_wechat_environment_config()


def default_wechat_environment_config() -> WeChatEnvironmentConfig:
    """Return a config pointing at bundled WeChat runtime files."""
    return WeChatEnvironmentConfig(
        wcdb_cli_path=(
            default_wechat_wcdb_cli_path()
            if default_wechat_wcdb_cli_path().is_file()
            else None
        ),
        wcdb_dll_path=(
            default_wechat_wcdb_dll_path()
            if default_wechat_wcdb_dll_path().is_file()
            else None
        ),
    )


def resolve_wechat_runtime_pair(
    config: WeChatEnvironmentConfig,
) -> WeChatEnvironmentConfig:
    """Return one config with a single, consistent CLI/DLL runtime pair.

    The CLI and the DLL are one runtime pair and are only ever rebound
    together, so a binary from an older installation is never paired with the
    one this installation ships. This is the one place that decides which pair
    a saved configuration ends up using, shared by reading the config and by
    writing it back.

    A complete pair is kept, unchanged, whatever produced it: an old bundled
    path and a user-chosen custom path cannot be told apart from the value
    alone, so neither is overwritten. A half-valid pair is kept exactly as
    saved too, because completing its missing half from this installation would
    run two builds as one runtime and would discard the surviving path. Only a
    pair that is entirely unusable is rebound, as a pair, to the bundled pair,
    and the saved values are kept when this installation provides no complete
    pair, so a caller reports the missing component instead of a fabricated
    runtime.
    """
    if _is_file(config.wcdb_cli_path) or _is_file(config.wcdb_dll_path):
        return config
    if not bundled_wechat_runtime_available():
        return config
    defaults = default_wechat_environment_config()
    return replace(
        config,
        wcdb_cli_path=defaults.wcdb_cli_path,
        wcdb_dll_path=defaults.wcdb_dll_path,
    )


def _string_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _path_value(value: Any) -> Path | None:
    if isinstance(value, Path):
        return value
    text = _string_value(value)
    if text is None:
        return None
    return Path(text)


def _is_file(path: Path | None) -> bool:
    return path is not None and path.is_file()


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
