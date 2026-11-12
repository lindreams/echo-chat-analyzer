"""Offline Unicode 18.0 emoji recognition shared by analysis and lexical masking.

Use the official fully/minimally/unqualified sequences in chat text, preserving
the spelling as the key. Components alone are not expressions. VS15 explicitly
requests text presentation and prevents that element from matching as emoji.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ._unicode_emoji_data import EMOJI_CODEPOINT_SEQUENCES


_SEQUENCES = tuple(
    "".join(chr(int(point, 16)) for point in line.split())
    for line in EMOJI_CODEPOINT_SEQUENCES.splitlines()
)
# Longest alternatives first keep flags, modifiers, tags and ZWJ sequences whole.
# Also reject a shorter prefix before VS16: it belongs to the preceding element.
# Gate the large alternation by its exact start characters. Most chat text
# cannot start any supported sequence; do not try thousands of alternatives
# at every ordinary text position. The sequence and presentation rules stay
# identical for recognition and lexical masking.
_EMOJI_RE = re.compile(
    "(?=[" + re.escape("".join(sorted({item[0] for item in _SEQUENCES}))) + "])"
    + "(?:" + "|".join(re.escape(item) for item in sorted(_SEQUENCES, key=lambda s: (-len(s), s)))
    + ")(?![\ufe0e\ufe0f])"
)


# The large alternation still costs time at every text position even with the
# lookahead gate. Recognition therefore runs the same gate as a plain set test
# first: no supported sequence is ASCII-only, and every sequence starts with a
# character from the same derived set. The set and the pattern read one source,
# so the cheap rejection cannot drift from the real recognition rules.
_EMOJI_START_CHARACTERS = frozenset(item[0] for item in _SEQUENCES)


def _may_contain_emoji(text: str) -> bool:
    if text.isascii():
        return False
    return any(character in _EMOJI_START_CHARACTERS for character in text)


def iter_emoji_clusters(text: str) -> Iterator[str]:
    """Yield supported emoji sequences, without inferring from block ranges."""
    if not _may_contain_emoji(text):
        return
    for match in _EMOJI_RE.finditer(text):
        yield match.group(0)


def mask_emoji(text: str) -> str:
    """Separate wording from expressions, including ASCII-based keycaps."""
    if not _may_contain_emoji(text):
        return text
    return _EMOJI_RE.sub(" ", text)
