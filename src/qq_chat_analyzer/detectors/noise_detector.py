"""Detect high-confidence repetitive message noise without filtering it."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ..analysis.identity import stable_sender_key
from ..analysis.timestamps import to_epoch_seconds
from ..candidates import Candidate
from ..message import ChatMessage


MIN_SINGLE_CHARACTER_REPETITIONS = 6
MIN_FRAGMENT_REPETITIONS = 3
MIN_REPEATED_FRAGMENT_TEXT_LENGTH = 8
MIN_BURST_REPETITIONS = 3
BURST_WINDOW_SECONDS = 60
MAX_EXAMPLES = 3


@dataclass(slots=True)
class _BurstRun:
    sender: str
    sender_key: str
    text: str
    start_timestamp: int
    last_timestamp: int
    start_index: int
    messages: list[ChatMessage]


def detect_noise_candidates(
    messages: Iterable[ChatMessage],
) -> list[Candidate]:
    """Return high-confidence repetition candidates without filtering input."""
    message_list = list(messages)
    candidates = [
        *_detect_message_internal_noise(message_list),
        *_detect_sender_burst_noise(message_list),
    ]
    return candidates


def _detect_message_internal_noise(
    messages: list[ChatMessage],
) -> list[Candidate]:
    groups: dict[tuple[str, str], list[ChatMessage]] = {}

    for message in messages:
        text = _normalize_text(message.text)
        if not text:
            continue

        if _is_single_character_repeat(text):
            key = ("noise_single_character_repeat", text)
        else:
            fragment = _repeated_fragment(text)
            if fragment is None:
                continue
            key = ("noise_repeated_fragment", text)
        groups.setdefault(key, []).append(message)

    candidates: list[Candidate] = []
    for (candidate_type, text), matched_messages in groups.items():
        if candidate_type == "noise_single_character_repeat":
            reasons = ["single_character_repeated"]
            metadata: dict[str, object] = {
                "rule": "single_character_repeat",
                "character": text[0],
                "repeat_count": len(text),
            }
        else:
            fragment = _repeated_fragment(text)
            if fragment is None:
                continue
            reasons = ["message_fragment_repeated"]
            metadata = {
                "rule": "repeated_fragment",
                "fragment": fragment,
                "repeat_count": len(text) // len(fragment),
            }
        metadata.update(
            {
                "matched_message_count": len(matched_messages),
                "examples": [
                    message.text for message in matched_messages[:MAX_EXAMPLES]
                ],
            }
        )
        candidates.append(
            Candidate(
                target=text,
                candidate_type=candidate_type,
                score=1.0,
                reasons=reasons,
                metadata=metadata,
            )
        )
    return candidates


def _detect_sender_burst_noise(
    messages: list[ChatMessage],
) -> list[Candidate]:
    """Detect repeated same-text runs per stable sender identity.

    Run continuity uses ``stable_sender_key``: members who share a display name
    are different senders, while one member who renamed mid-run stays the same
    sender. Records without a usable identity keep the historical display-name
    behaviour, and a name never stands in for a resolved identity.
    """
    completed_runs: list[_BurstRun] = []
    current_run: _BurstRun | None = None

    for message_index, message in enumerate(messages):
        text = _normalize_text(message.text)
        timestamp = to_epoch_seconds(message.timestamp)
        if not text or timestamp is None:
            current_run = _finish_run(current_run, completed_runs)
            continue

        sender_key = stable_sender_key(message)
        continues_run = (
            current_run is not None
            and current_run.sender_key == sender_key
            and current_run.text == text
            and 0 <= timestamp - current_run.last_timestamp <= BURST_WINDOW_SECONDS
            and timestamp - current_run.start_timestamp <= BURST_WINDOW_SECONDS
        )
        if continues_run:
            current_run.last_timestamp = timestamp
            current_run.messages.append(message)
            continue

        current_run = _finish_run(current_run, completed_runs)
        current_run = _BurstRun(
            sender=message.sender,
            sender_key=sender_key,
            text=text,
            start_timestamp=timestamp,
            last_timestamp=timestamp,
            start_index=message_index,
            messages=[message],
        )

    _finish_run(current_run, completed_runs)

    candidates: list[Candidate] = []
    for run in completed_runs:
        candidates.append(
            Candidate(
                target=run.text,
                candidate_type="noise_sender_burst_repeat",
                score=1.0,
                reasons=["same_sender_short_interval_repeat"],
                metadata={
                    "rule": "sender_burst_repeat",
                    "sender": run.sender,
                    "repeat_count": len(run.messages),
                    "window_seconds": run.last_timestamp - run.start_timestamp,
                    "message_indexes": tuple(
                        range(run.start_index, run.start_index + len(run.messages))
                    ),
                    "examples": [
                        message.text for message in run.messages[:MAX_EXAMPLES]
                    ],
                },
            )
        )
    return candidates


def _finish_run(
    run: _BurstRun | None,
    completed_runs: list[_BurstRun],
) -> None:
    if run is not None and len(run.messages) >= MIN_BURST_REPETITIONS:
        completed_runs.append(run)
    return None


def _normalize_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    return " ".join(text.split()).strip()


def _is_single_character_repeat(text: str) -> bool:
    return (
        len(text) >= MIN_SINGLE_CHARACTER_REPETITIONS
        and len(set(text)) == 1
    )


def _repeated_fragment(text: str) -> str | None:
    if len(text) < MIN_REPEATED_FRAGMENT_TEXT_LENGTH:
        return None

    # The next occurrence in the doubled string gives the shortest exact
    # period. A non-repeated text only matches again at its full length.
    # Avoid a fragment-length cap that misses copied whole sentences.
    fragment_length = (text + text).find(text, 1)
    if (
        fragment_length < 2
        or len(text) % fragment_length != 0
        or len(text) // fragment_length < MIN_FRAGMENT_REPETITIONS
    ):
        return None
    return text[:fragment_length]
