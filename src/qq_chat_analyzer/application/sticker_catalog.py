"""Read-only material counts from the existing analyzed sending facts."""
from __future__ import annotations

from collections import Counter
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
    member_counts: tuple[tuple[str, int], ...] = field(default=(), repr=False)

    @property
    def count(self) -> int:
        return self.self_count + self.other_count + self.unknown_count

    @property
    def unknown_sender_count(self) -> int:
        return self.count - sum(count for _, count in self.member_counts)


def build_sticker_catalog(
    sends: Iterable[StickerSend], *, source: str, conversation_type: str = "private",
) -> tuple[StickerCatalogEntry, ...]:
    """Never infer sender/material identity or merge distinct namespaces.

    Unresolved sends retain their occurrence-level media keys, not a shared
    'unknown' material. Member counts use sender_id independently of is_self;
    an unknown self marker does not make a known member unknown.
    """
    groups: dict[str, list[StickerSend]] = {}
    for send in sends:
        if send.source == source and send.conversation_type == conversation_type:
            groups.setdefault(send.media_key, []).append(send)
    entries = []
    for key, group in groups.items():
        entries.append(StickerCatalogEntry(
            key, group[0].identity_basis, group[0].identity_key is not None,
            sum(s.is_self is True for s in group),
            sum(s.is_self is False for s in group),
            sum(s.is_self is None for s in group),
            tuple(sorted(Counter(s.sender_id for s in group if s.sender_id).items()))))
    return tuple(sorted(entries, key=lambda entry: (-entry.count, entry.media_key)))
