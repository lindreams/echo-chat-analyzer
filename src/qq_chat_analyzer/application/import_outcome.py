"""Internal import pipeline result that may carry parsed messages."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..message import ChatMessage
from ..qq_db_adapter import QQPicMediaFact
from ..rich_message import RichMessage
from .import_result import ImportResult


class _RichMessagePairs(Sequence):
    """Lazy projection pairing; iteration creates no retained pair objects."""

    __slots__ = ("_messages", "_rich_messages", "_indexes")

    def __init__(self, messages, rich_messages, indexes):
        self._messages = messages
        self._rich_messages = rich_messages
        self._indexes = indexes

    def __len__(self):
        return len(self._rich_messages)

    def __iter__(self):
        if self._indexes:
            for index, rich in zip(self._indexes, self._rich_messages, strict=True):
                yield self._messages[index], rich
        else:
            yield from zip(self._messages, self._rich_messages, strict=True)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return tuple(self)[index]
        rich = self._rich_messages[index]
        message_index = self._indexes[index] if self._indexes else index
        return self._messages[message_index], rich


@dataclass(frozen=True, slots=True)
class ImportOutcome:
    """Internal pipeline result combining public summary with messages."""

    result: ImportResult
    processed_message_count: int
    messages: tuple[ChatMessage, ...]
    rich_messages: tuple[RichMessage, ...] = ()
    # Compact association for mixed legacy/Rich directories. An empty index
    # means every message has one Rich projection in the same order.
    rich_message_indexes: tuple[int, ...] = ()
    # Compatibility for direct internal constructors. Production imports use
    # the compact aligned/indexed representation above.
    rich_message_pairs: Sequence[tuple[ChatMessage, RichMessage]] = ()
    # Only custom-PIC messages retain compact locating facts; no source record,
    # message blob, text, path or URL is copied into this channel.
    qq_pic_media_facts: tuple[QQPicMediaFact, ...] = ()

    def __post_init__(self):
        if self.rich_message_pairs or not self.rich_messages:
            return
        if self.rich_message_indexes:
            if len(self.rich_message_indexes) != len(self.rich_messages):
                raise ValueError("invalid rich message association")
        elif len(self.messages) != len(self.rich_messages):
            raise ValueError("invalid aligned rich message association")
        object.__setattr__(
            self,
            "rich_message_pairs",
            _RichMessagePairs(
                self.messages,
                self.rich_messages,
                self.rich_message_indexes,
            ),
        )

    def iter_rich_message_pairs(self):
        """Yield actual projection instances without retaining pair objects."""
        yield from self.rich_message_pairs
