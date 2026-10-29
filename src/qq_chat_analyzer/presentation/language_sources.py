"""Project retained lexical matches into a small, offline original-message table.

The caller passes the token lists used by analysis, in kept-message order, and
their import positions. No source IDs, new tokenization, or database reads are
needed. Import gaps and uncertain time/conversation facts stop context expansion.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from ..analysis.identity import stable_sender_key
from ..analysis.timestamps import to_chat_datetime, to_epoch_seconds
from ..message import ChatMessage
from .models import EchoLanguageMessage, EchoLanguageSources, EchoLanguageTerm, EchoReportView


CONTEXT_MESSAGES_PER_SIDE = 2
CONTEXT_SECONDS = 600


def build_language_sources(
    view: EchoReportView,
    messages: Sequence[ChatMessage],
    message_tokens: Sequence[Sequence[str]],
    *,
    source_positions: Sequence[int],
) -> EchoLanguageSources | None:
    """Associate only displayed words with their actual, scoped lexical input."""
    if (len(messages) != len(message_tokens) or len(messages) != len(source_positions)
            or any(type(position) is not int or position < 0 for position in source_positions)):
        raise ValueError("language_source_alignment")
    profile = view.language_profile
    expected_mode = {"private": "private_common", "group": "group_distinctive"}.get(view.conversation_kind)
    if profile is None or not profile.available or profile.mode != expected_mode:
        return None

    requests: dict[tuple[int | None, str], frozenset[str]] = {}
    for index, member in enumerate(profile.members):
        for word in (*member.primary_words, *member.context_words):
            if word and not word.startswith("expression:"):
                requests[index, word] = frozenset((member.speaker_key,))
    member_keys = frozenset(member.speaker_key for member in profile.members)
    for word in profile.shared_words:
        if word.word and not word.word.startswith("expression:"):
            requests[None, word.word] = member_keys
    by_word: dict[str, list[tuple[int | None, str]]] = {}
    for key in requests:
        by_word.setdefault(key[1], []).append(key)
    counts = Counter()
    matches: dict[tuple[int | None, str], list[int]] = {key: [] for key in requests}
    for ref, (message, tokens) in enumerate(zip(messages, message_tokens, strict=True)):
        sender = stable_sender_key(message)
        for word, count in Counter(token for token in tokens if token in by_word).items():
            for key in by_word[word]:
                if sender and sender in requests[key]:
                    counts[key] += count
                    matches[key].append(ref)

    # A retained message is serialized once even if several words match it.
    hits = {ref for refs in matches.values() for ref in refs}
    contexts = {ref: (
        _context_refs(messages, source_positions, ref, -1),
        _context_refs(messages, source_positions, ref, 1),
    ) for ref in hits}
    needed = hits | {ref for before, after in contexts.values() for ref in (*before, *after)}
    name_counts = Counter(member.display_name for member in view.members)
    names = {member.speaker_key: (
        f"{member.display_name} · {index + 1:02d}"
        if name_counts[member.display_name] > 1 else member.display_name
    ) for index, member in enumerate(view.members)}
    originals = []
    for ref in sorted(needed):
        message = messages[ref]
        moment = to_chat_datetime(message.timestamp)
        before, after = contexts.get(ref, ((), ()))
        originals.append(EchoLanguageMessage(
            ref=ref, speaker_label=names.get(stable_sender_key(message), "未知成员"),
            timestamp=moment.strftime("%Y-%m-%d %H:%M:%S") if moment else "",
            text=message.text, message_type=message.message_type,
            before_refs=before, after_refs=after,
        ))
    return EchoLanguageSources(messages=tuple(originals), terms=tuple(
        EchoLanguageTerm(word, member_index, counts[member_index, word], tuple(matches[member_index, word]))
        for member_index, word in requests
    ))


def _context_refs(messages, positions, hit: int, direction: int) -> tuple[int, ...]:
    anchor = messages[hit]
    anchor_time = to_epoch_seconds(anchor.timestamp)
    if anchor_time is None or not anchor.conversation_id:
        return ()
    refs = []
    previous = hit
    for offset in range(1, CONTEXT_MESSAGES_PER_SIDE + 1):
        ref = hit + direction * offset
        if not 0 <= ref < len(messages) or positions[ref] != positions[previous] + direction:
            break
        message = messages[ref]
        timestamp = to_epoch_seconds(message.timestamp)
        previous_time = to_epoch_seconds(messages[previous].timestamp)
        if (message.platform != anchor.platform or message.conversation_id != anchor.conversation_id
                or message.conversation_type != anchor.conversation_type
                or timestamp is None or previous_time is None
                or direction * (timestamp - previous_time) < 0
                or abs(timestamp - anchor_time) > CONTEXT_SECONDS):
            break
        refs.append(ref)
        previous = ref
    return tuple(reversed(refs)) if direction < 0 else tuple(refs)
