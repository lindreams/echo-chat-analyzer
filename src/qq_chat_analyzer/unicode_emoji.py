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
_EMOJI_RE = re.compile(
    "(?:" + "|".join(re.escape(item) for item in sorted(_SEQUENCES, key=lambda s: (-len(s), s)))
    + ")(?![\ufe0e\ufe0f])"
)


def iter_emoji_clusters(text: str) -> Iterator[str]:
    """Yield supported emoji sequences, without inferring from block ranges."""
    for match in _EMOJI_RE.finditer(text):
        yield match.group(0)


def mask_emoji(text: str) -> str:
    """Separate wording from expressions, including ASCII-based keycaps."""
    return _EMOJI_RE.sub(" ", text)
