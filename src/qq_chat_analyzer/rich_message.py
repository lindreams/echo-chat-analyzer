"""Source-neutral P0 semantic model for chat messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


EXPRESSION_KIND_UNICODE = "unicode"
EXPRESSION_KIND_PLATFORM_FACE = "platform_face"
EXPRESSION_KIND_STICKER = "sticker"


@dataclass(frozen=True, slots=True)
class SenderIdentity:
    """Stable source identity plus its human-readable name."""

    identity_id: str | None
    display_name: str
    remark: str | None = None
    nickname: str | None = None
    contextual_name: str | None = None


@dataclass(frozen=True, slots=True)
class TextContent:
    """Text authored in the current message."""

    text: str


@dataclass(frozen=True, slots=True)
class StickerIdentity:
    """Source evidence, distinct from the legacy expression display key.

    No identity means an occurrence must not be merged with another send.
    Local paths are untrusted hints, never proof of an original resource.
    """

    classification_basis: str
    identity_basis: str
    identity_key: str | None = field(default=None, repr=False)
    content_md5: str | None = field(default=None, repr=False)
    local_paths: tuple[str, ...] = field(default=(), repr=False)
    # Untrusted acquisition hint taken from validated source XML; never part of
    # identity and never serialized. A consumer must still verify the digest.
    recovery_url: str | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ImageReference:
    """PIC metadata; these fields do not classify an image as a sticker."""

    content_md5: str | None = field(default=None, repr=False)
    is_original: bool | None = None
    local_paths: tuple[str, ...] = field(default=(), repr=False)


@dataclass(frozen=True, slots=True)
class ExpressionContent:
    """One source-neutral expression occurrence in a message."""

    expression_kind: str
    expression_key: str
    display_text: str | None = None
    source: str | None = None
    position: int | None = None
    text_before: str | None = None
    text_after: str | None = None
    sticker: StickerIdentity | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ReplyRelation:
    """Relation from the current message to the replied-to message."""

    target_message_id: str


@dataclass(frozen=True, slots=True)
class MentionRelation:
    """Mention fact; ``None`` means its target identity is unresolved."""

    target_identity_id: str | None
    display_text: str | None = None


@dataclass(frozen=True, slots=True)
class RecallState:
    """Known recall state of a message; absence means the source did not say."""

    is_recalled: bool


@dataclass(frozen=True, slots=True)
class RecallEvent:
    """Known facts about an event that recalled a target message."""

    target_message_id: str
    actor_identity_id: str | None = None
    timestamp: int | float | str | None = None


@dataclass(frozen=True, slots=True)
class NonTextContent:
    """One non-text occurrence with optional untrusted source metadata.

    Some sources expose sticker evidence on an image segment. The content stays
    a non-text image fact for legacy statistics; sticker is separate provenance.
    """

    kind: Literal["image", "unknown"]
    media: ImageReference | None = field(default=None, repr=False)
    sticker: StickerIdentity | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.kind not in ("image", "unknown"):
            raise ValueError("Unsupported non-text content kind")


RichContent = TextContent | ExpressionContent | NonTextContent
MessageRelation = ReplyRelation | MentionRelation


@dataclass(frozen=True, slots=True)
class RichMessage:
    """P0 source-neutral message fact used before legacy projection."""

    message_id: str | None
    source: str
    conversation_id: str | None
    sender: SenderIdentity
    timestamp: int | float | str
    message_type: str
    contents: tuple[RichContent, ...]
    source_type: str | int | None = None
    relations: tuple[MessageRelation, ...] = ()
    recall_state: RecallState | None = None
    recall_event: RecallEvent | None = None
    is_system: bool = False
    conversation_type: str = "unknown"
    is_self: bool | None = None
