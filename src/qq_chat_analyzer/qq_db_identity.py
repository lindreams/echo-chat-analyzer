"""Canonical self identity for the QQ Direct DB source.

The Direct DB path supports exactly one self-identity namespace: ``qq_uin``,
whose value is the source's self context: legacy NapCat ``core.selfInfo.uin``
or the explicitly confirmed user declaration for an independently authenticated
offline profile. The latter retains ``user_declared`` provenance in reports.
This module is intentionally tiny: it owns the
namespace constant and the canonicalization used to compare a message's
sender field (``40033``) against the bound self identity.

Neither the value nor the namespace ever carries a human-readable nickname;
it is an opaque account key and must not be logged or surfaced.
"""

from __future__ import annotations

from typing import Any

#: The single identity namespace the Direct DB path consumes.
QQ_DB_SELF_NAMESPACE = "qq_uin"


def canonical_qq_uin(value: Any) -> str | None:
    """Return the canonical ``qq_uin`` string, or ``None`` when unreliable.

    ``None`` is the only valid way to say "we cannot tell"; the adapter must
    treat it as unknown (``is_self=None``), never as peer.  Values that carry
    no reliable identity -- ``0``, empty text, booleans, non-scalars -- all
    canonicalize to ``None``.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (int, float)):
        text = str(value)
    else:
        return None
    if not text or text == "0":
        return None
    return text


__all__ = [
    "QQ_DB_SELF_NAMESPACE",
    "canonical_qq_uin",
]
