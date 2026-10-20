"""Coalesce QQ original scopes without expanding media read authority."""
from pathlib import Path
import re


def qq_media_search_roots(scopes: tuple[Path, ...]) -> tuple[Path, ...]:
    """Coalesce known month layouts for traversal, never for read authority.

    The caller must also pass the unchanged scopes to the validator. Unknown
    layouts remain individual roots and retain the existing root-budget limit.
    """
    roots = []
    for scope in scopes:
        root = scope
        if scope.name == "Ori" and re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", scope.parent.name):
            base = scope.parent.parent
            if (base.name == "Pic" and base.parent.name == "nt_data"
                    and base.parent.parent.name == "nt_qq") or (
                base.name == "emoji-recv" and base.parent.name == "Emoji"
                and base.parent.parent.name == "nt_data"
                and base.parent.parent.parent.name == "nt_qq"
            ):
                root = base
        if root not in roots:
            roots.append(root)
    return tuple(roots)
