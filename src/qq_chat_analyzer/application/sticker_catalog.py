"""Read-only material counts from the existing analyzed sending facts."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..analysis.stickers import StickerSend


@dataclass(frozen=True, slots=True)
class StickerCatalogEntry:
    media_key: str = field(repr=False)
    identity_basis: str
    identity_known: bool
    self_count: int = 0
    other_count: int = 0
    unknown_count: int = 0

    @property
    def count(self) -> int:
        return self.self_count + self.other_count + self.unknown_count


def build_sticker_catalog(sends: Iterable[StickerSend], *, source: str) -> tuple[StickerCatalogEntry, ...]:
    """Never infer sender/material identity or merge distinct namespaces.

    Unresolved sends retain their occurrence-level media keys, not a shared
    'unknown' material. Counts include unknown senders in a separate column.
    """
    groups: dict[str, list[StickerSend]] = {}
    for send in sends:
        if send.source == source and send.conversation_type == "private":
            groups.setdefault(send.media_key, []).append(send)
    entries = []
    for key, group in groups.items():
        entries.append(StickerCatalogEntry(
            key, group[0].identity_basis, group[0].identity_key is not None,
            sum(s.is_self is True for s in group),
            sum(s.is_self is False for s in group),
            sum(s.is_self is None for s in group)))
    return tuple(sorted(entries, key=lambda entry: (-entry.count, entry.media_key)))
