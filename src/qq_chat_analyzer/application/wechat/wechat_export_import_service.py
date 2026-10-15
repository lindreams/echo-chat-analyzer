"""Orchestrate a WeChat database export into the existing import pipeline.

This module keeps the seam between two pieces that must not know about each
other: the WeChat database provider produces a local JSON file, and the existing
:class:`~qq_chat_analyzer.application.import_service.ImportService` turns local
files into :class:`~qq_chat_analyzer.message.ChatMessage` objects.

Deliberate boundaries:

* No WCDB, no SQL, and no key handling live here. The provider is injected and
  only has to satisfy :class:`WeChatExportProvider`, so tests can supply a stub.
* ``wechat_db_adapter`` is untouched and stays unaware that a provider exists.
  It is reached indirectly, through the normal ``ImportService`` file dispatch.
* ``wechat_parser.py`` and the analysis core are not involved.

The provider contract is intentionally narrow: given a session id and an
optional time window, hand back a path to a finished export document.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ...analysis.timestamps import to_epoch_seconds
from ..errors import ApplicationServiceError
from ..import_outcome import ImportOutcome
from ..import_request import ImportRequest
from ..import_service import ImportService


_LOGGER = logging.getLogger(
    "qq_chat_analyzer.desktop.wechat_export_import_service"
)


WECHAT_PLATFORM = "wechat"


class WeChatExportUnavailable(ApplicationServiceError):
    """Raised when the provider could not produce an export file."""

    code = "wechat_export_unavailable"
    public_message = (
        "\u65e0\u6cd5\u4ece\u5fae\u4fe1\u6570\u636e\u5e93\u83b7\u53d6\u5bfc\u51fa\u6587\u4ef6\u3002"
    )


class WeChatExportFileMissing(ApplicationServiceError):
    """Raised when the export reports success but the file is not on disk."""

    code = "wechat_export_file_missing"
    public_message = (
        "\u5fae\u4fe1\u5bfc\u51fa\u5df2\u5b8c\u6210\uff0c"
        "\u4f46\u672a\u627e\u5230\u5bfc\u51fa\u6587\u4ef6\u3002"
    )


@runtime_checkable
class WeChatExportProvider(Protocol):
    """Minimal surface this orchestrator needs from a WeChat provider."""

    def list_sessions(self) -> list[Any]:  # pragma: no cover - contract only
        """Return the conversations that are available for export."""
        ...

    def export_session_json(
        self,
        session_id: str,
        output_path: Any,
        start_time: Any = None,
        end_time: Any = None,
    ) -> Path:  # pragma: no cover - structural contract only
        ...

    def read_session_time_bounds(self, session_id: str) -> list[Any]:
        """Return raw shard extrema and distinct non-numeric timestamps."""
        ...


@dataclass(frozen=True, slots=True)
class WeChatExportImportRequest:
    """Describe one "export from WeChat, then import" operation."""

    session_id: str
    output_path: Path
    start_time: Any = None
    end_time: Any = None


class WeChatExportImportService:
    """Export one WeChat conversation through a provider, then import it."""

    def __init__(
        self,
        provider: WeChatExportProvider | None = None,
        import_service: ImportService | None = None,
        *,
        provider_factory: Any = None,
    ) -> None:
        if provider is None and provider_factory is None:
            raise TypeError(
                "WeChatExportImportService needs a provider or a"
                " provider_factory"
            )
        self._injected_provider = provider
        self._provider_factory = provider_factory
        self._import_service = import_service or ImportService()

    def provider(self) -> WeChatExportProvider:
        """Return the provider used for exports.

        When a shared provider factory is injected, the instance comes
        from that factory, so this read path and the connection status
        check observe the same configuration and the same provider.
        """
        if self._provider_factory is not None:
            return self._provider_factory.create()
        return self._injected_provider

    @property
    def _provider(self) -> WeChatExportProvider:
        return self.provider()

    def execute(self, request: WeChatExportImportRequest) -> ImportOutcome:
        export_path = self.export_only(request)

        try:
            return self._import_service.execute(
                ImportRequest(input_path=export_path, platform=WECHAT_PLATFORM)
            )
        except Exception as error:
            _LOGGER.warning(
                "wechat.import.failed error_type=%s",
                type(error).__name__,
            )
            raise

    def list_sessions(self) -> list[Any]:
        """Delegate session listing to the injected provider.

        Thin pass-through so callers such as a future CLI or GUI reach provider
        listings through this application service instead of constructing a
        provider themselves. Provider errors propagate unchanged; they already
        carry user-facing messages.
        """
        return self._provider.list_sessions()

    def get_session_message_range(self, session_id: str) -> tuple[int, int] | None:
        """Normalize shard time aggregates using the shared timestamp rules."""
        epochs = [
            epoch
            for row in self._provider.read_session_time_bounds(session_id)
            for name in ("min_time", "max_time")
            if (epoch := to_epoch_seconds(row.get(name))) is not None
        ]
        return (min(epochs), max(epochs)) if epochs else None

    def export_only(self, request: WeChatExportImportRequest) -> Path:
        """Export one conversation and return the finished JSON file path.

        This is the first half of :meth:`execute`, exposed for callers that
        want the export file without immediately importing it. Provider errors
        propagate unchanged; only a missing or unusable return value becomes
        :class:`WeChatExportUnavailable`, and a path that is not present on
        disk becomes :class:`WeChatExportFileMissing`.
        """
        export_path = self._export(request)
        if not export_path.exists():
            raise WeChatExportFileMissing()
        return export_path

    # ---------------------------------------------------------------- internals

    def _export(self, request: WeChatExportImportRequest) -> Path:
        """Run the provider export, normalising its failures.

        Provider-level errors are re-raised untouched: they already carry
        actionable, user-facing messages such as "database not found" or
        "key unavailable". Only a missing or unusable return value is
        translated here.
        """
        result = self._provider.export_session_json(
            request.session_id,
            request.output_path,
            start_time=request.start_time,
            end_time=request.end_time,
        )
        if result is None:
            raise WeChatExportUnavailable()
        if isinstance(result, Path):
            return result
        if isinstance(result, str) and result.strip():
            return Path(result)
        raise WeChatExportUnavailable()
