"""Shared template syntax: literal braces versus generated variables.

A detected template is stored as a single string because ``Candidate.target``
and ``FilterDecision.target`` are plain text. User messages may contain the
very same ``{number}``-style sequences the detector generates for variables, so
the detector escapes every literal ``{`` as ``{{`` before it inserts its own
placeholders. The detector and the filter then parse templates through this
module, which keeps the stored string the single source of truth: a template
can neither widen its match beyond the messages it was built from, nor fail to
match those messages.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator


_LITERAL_ESCAPE = "{{"
_TOKEN_PATTERN = re.compile(
    r"\{\{"
    r"|\{(?P<kind>variable|number|id|user|url)\}"
)


def escape_literal(text: str) -> str:
    """Escape literal opening braces so they cannot read as placeholders.

    Only ``{`` is escaped: recognizing a placeholder always needs a complete
    ``{kind}`` sequence, so ``}`` stays untouched. Escaping every opening brace
    (instead of only placeholder-shaped ones) keeps the transformation exactly
    reversible for arbitrary input.
    """
    return text.replace("{", _LITERAL_ESCAPE)


def iter_tokens(template: str) -> Iterator[tuple[str, str]]:
    """Yield ``("literal", text)`` and ``("kind", kind)`` tokens in order."""
    position = 0
    for match in _TOKEN_PATTERN.finditer(template):
        if match.start() > position:
            yield "literal", template[position : match.start()]
        if match.group("kind") is None:
            yield "literal", "{"
        else:
            yield "kind", match.group("kind")
        position = match.end()
    if position < len(template):
        yield "literal", template[position:]


def static_text(template: str) -> str:
    """Return the decoded literal text, without generated placeholders."""
    return "".join(
        value for kind, value in iter_tokens(template) if kind == "literal"
    )


def variable_counts(template: str) -> Counter[str]:
    """Count generated placeholders by kind, ignoring literal brace text."""
    return Counter(
        value for kind, value in iter_tokens(template) if kind == "kind"
    )
