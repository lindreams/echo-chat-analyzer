"""Application-layer import pipeline foundation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..legacy_projection import project_legacy_messages
from ..message import ChatMessage
from ..rich_message import RichMessage
from ..qq_db_adapter import (
    QQ_DB_JSON_FORMAT,
    is_qq_db_payload,
    load_qq_db_json,
    parse_qq_db_rich_messages,
)
from ..wechat_cli_adapter import (
    is_cli_payload,
    parse_messages as parse_wechat_cli_messages,
)
from ..wechat_db_adapter import (
    DB_JSON_FORMAT as WECHAT_DB_FORMAT,
    is_wechat_db_payload,
    messages_from_payload as wechat_db_rows,
    parse_rich_messages as parse_wechat_db_rich_messages,
)
from ..wechat_parser import (
    is_detailed_payload,
    detailed_conversation_context,
    is_chatlab_records,
    load_chatlab_records,
    chatlab_conversation_context,
    parse_messages as parse_wechat_messages,
)
from .errors import InputPathNotFound, NoSupportedInput
from .import_outcome import ImportOutcome
from .import_request import ImportRequest
from .import_result import ImportResult


_SUPPORTED_INPUT_SUFFIXES = frozenset({".json", ".jsonl"})

WECHAT_CLI_FORMAT = "cli-json"

_SIDECAR_FILE_NAMES = frozenset({"manifest.json", "avatars.json"})
_SIDECAR_DIR_NAMES = frozenset({"resources"})
_CHUNK_DIR_NAMES = frozenset({"chunks"})
_CHUNK_DATA_SUFFIXES = frozenset({".jsonl"})

WARNING_NO_MESSAGES_LOADED = "no_messages_loaded"
WARNING_UNSUPPORTED_FORMAT = "unsupported_format"
WARNING_PLATFORM_HINT_FORMAT_MISMATCH = "platform_hint_format_mismatch"

_UNKNOWN_PLATFORM = None


@dataclass(frozen=True, slots=True)
class _ImportedFile:
    platform: str | None
    messages: tuple[ChatMessage, ...]
    rich_messages: tuple[RichMessage, ...]
    format: str | None
    warnings: tuple[str, ...]
    raw_count: int


class ImportService:
    """Import local chat files into ChatMessage without running analysis."""

    def execute(self, request: ImportRequest) -> ImportOutcome:
        _validate_input_path(request.input_path)
        candidate_files = _find_candidate_input_files(request.input_path)
        if not candidate_files:
            raise NoSupportedInput()

        input_files = [
            path
            for path in candidate_files
            if not _is_sidecar(path, request.input_path)
        ]
        if not input_files:
            return _unsupported_outcome(request.platform)

        messages: list[ChatMessage] = []
        rich_messages: list[RichMessage] = []
        rich_message_pairs: list[tuple[ChatMessage, RichMessage]] = []
        warnings: list[str] = []
        formats: set[str] = set()
        detected_platforms: list[str] = []
        processed_message_count = 0

        for input_file in input_files:
            imported = _import_file(input_file, request.platform)
            warnings.extend(imported.warnings)
            if imported.platform is _UNKNOWN_PLATFORM:
                continue
            detected_platforms.append(imported.platform)
            messages.extend(imported.messages)
            rich_messages.extend(imported.rich_messages)
            if imported.rich_messages:
                rich_message_pairs.extend(
                    zip(imported.messages, imported.rich_messages, strict=True)
                )
            if imported.format is not None:
                formats.add(imported.format)
            processed_message_count += imported.raw_count

        valid_text_count = sum(1 for message in messages if message.text.strip())
        result = ImportResult(
            platform=_resolve_platform(request.platform, detected_platforms),
            message_count=len(messages),
            valid_text_count=valid_text_count,
            warnings=_dedupe_warnings(warnings),
            format=_single_format(formats),
        )
        return ImportOutcome(
            result=result,
            processed_message_count=processed_message_count,
            messages=tuple(messages),
            rich_messages=tuple(rich_messages),
            rich_message_pairs=tuple(rich_message_pairs),
        )


def _validate_input_path(input_path: Path) -> None:
    if not input_path.exists():
        raise InputPathNotFound()


def _find_candidate_input_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() in _SUPPORTED_INPUT_SUFFIXES:
            return [input_path]
        return []
    if not input_path.is_dir():
        return []
    return sorted(
        path
        for path in input_path.rglob("*")
        if path.is_file() and path.suffix.lower() in _SUPPORTED_INPUT_SUFFIXES
    )


def _unsupported_outcome(platform_hint: str | None) -> ImportOutcome:
    return ImportOutcome(
        result=ImportResult(
            platform=_resolve_platform(platform_hint, []),
            message_count=0,
            valid_text_count=0,
            warnings=(WARNING_UNSUPPORTED_FORMAT,),
            format=None,
        ),
        processed_message_count=0,
        messages=(),
    )


def _is_sidecar(path: Path, root: Path) -> bool:
    if path.name.lower() in _SIDECAR_FILE_NAMES:
        return True
    try:
        relative_parents = path.relative_to(root).parent.parts
    except ValueError:
        return False

    lowered_parents = [part.lower() for part in relative_parents]
    if any(part in _SIDECAR_DIR_NAMES for part in lowered_parents):
        return True
    if any(part in _CHUNK_DIR_NAMES for part in lowered_parents):
        return path.suffix.lower() not in _CHUNK_DATA_SUFFIXES
    return False


def _import_file(
    input_file: Path,
    platform_hint: str | None,
) -> _ImportedFile:
    if platform_hint not in (None, "qq", "wechat"):
        return _unsupported_file(WARNING_PLATFORM_HINT_FORMAT_MISMATCH)
    # Retain only this file's decoded payload; no cross-import cache or copies
    # of the source text are needed for detection and parsing.
    is_jsonl = input_file.suffix.lower() == ".jsonl"
    records = load_chatlab_records(input_file) if is_jsonl else []
    if is_jsonl:
        payload = records[0] if len(records) == 1 else None
        chatlab = is_chatlab_records(records)
        if is_qq_db_payload(payload) or not chatlab:
            # QQ DB documents historically also accepted a .jsonl suffix,
            # including pretty-printed JSON. Keep that uncommon path.
            payload = load_qq_db_json(input_file)
    else:
        chatlab = False
        try:
            with input_file.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = None

    qq = is_qq_db_payload(payload)
    if platform_hint == "qq" or (platform_hint is None and qq):
        return (
            _import_qq_db_payload(payload) if qq
            else _unsupported_file(WARNING_PLATFORM_HINT_FORMAT_MISMATCH)
        )
    # A WeChat hint historically checks the detailed shape before the DB
    # shape. Automatic detection gives the DB marker priority instead.
    detailed = (
        not is_jsonl and isinstance(payload, dict) and is_detailed_payload(payload)
        if platform_hint == "wechat" else None
    )
    if not is_jsonl and isinstance(payload, dict) and is_wechat_db_payload(payload):
        return _import_wechat_db_rows(wechat_db_rows(payload))
    if detailed is None:
        detailed = (
            not is_jsonl and isinstance(payload, dict) and is_detailed_payload(payload)
        )
    if detailed or chatlab:
        raw_messages = (
            [record for record in records if record.get("_type") == "message"]
            if chatlab else payload.get("messages", [])
        )
        if not isinstance(raw_messages, list):
            raw_messages = []
        conversation_id, conversation_type = (
            chatlab_conversation_context(records) if chatlab
            else detailed_conversation_context(payload)
        )
        parsed_messages = tuple(parse_wechat_messages(
            raw_messages,
            conversation_id=conversation_id,
            conversation_type=conversation_type,
        ))
        return _ImportedFile(
            platform="wechat",
            messages=parsed_messages,
            rich_messages=(),
            format="chatlab-jsonl" if is_jsonl else "detailed-json",
            warnings=_empty_input_warning(raw_messages),
            raw_count=len(raw_messages),
        )
    if not is_jsonl and isinstance(payload, list) and is_cli_payload(payload):
        return _import_wechat_cli_rows(payload)
    return _unsupported_file(
        WARNING_PLATFORM_HINT_FORMAT_MISMATCH if platform_hint is not None
        else WARNING_UNSUPPORTED_FORMAT
    )


def _unsupported_file(warning: str) -> _ImportedFile:
    return _ImportedFile(
        platform=_UNKNOWN_PLATFORM,
        messages=(),
        rich_messages=(),
        format=None,
        warnings=(warning,),
        raw_count=0,
    )


def _import_qq_db_payload(payload: dict) -> _ImportedFile:
    raw_records = payload["records"]
    rich_messages, parse_warnings = parse_qq_db_rich_messages(payload)
    parsed_messages = tuple(project_legacy_messages(rich_messages))
    warnings = (
        *parse_warnings,
        *_empty_input_warning(raw_records),
    )
    return _ImportedFile(
        platform="qq",
        messages=parsed_messages,
        rich_messages=tuple(rich_messages),
        format=QQ_DB_JSON_FORMAT,
        warnings=warnings,
        raw_count=len(raw_records),
    )


def _import_wechat_cli_rows(raw_messages: list) -> _ImportedFile:
    parsed_messages = tuple(parse_wechat_cli_messages(raw_messages))
    return _ImportedFile(
        platform="wechat",
        messages=parsed_messages,
        rich_messages=(),
        format=WECHAT_CLI_FORMAT,
        warnings=_empty_input_warning(raw_messages),
        raw_count=len(raw_messages),
    )


def _import_wechat_db_rows(raw_messages: list) -> _ImportedFile:
    rich_messages = tuple(parse_wechat_db_rich_messages(raw_messages))
    parsed_messages = tuple(project_legacy_messages(rich_messages))
    return _ImportedFile(
        platform="wechat",
        messages=parsed_messages,
        rich_messages=rich_messages,
        format=WECHAT_DB_FORMAT,
        warnings=_empty_input_warning(raw_messages),
        raw_count=len(raw_messages),
    )


def _empty_input_warning(raw_messages: list) -> tuple[str, ...]:
    return () if raw_messages else (WARNING_NO_MESSAGES_LOADED,)


def _resolve_platform(
    platform_hint: str | None,
    detected_platforms: list[str],
) -> str | None:
    if platform_hint:
        return platform_hint
    if detected_platforms:
        return detected_platforms[0]
    return None


def _dedupe_warnings(warnings: list[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for warning in warnings:
        seen.setdefault(warning, None)
    return tuple(seen)


def _single_format(formats: set[str]) -> str | None:
    if len(formats) == 1:
        return next(iter(formats))
    return None
