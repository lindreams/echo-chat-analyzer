"""Aggregate explicit private nudges without treating actions as authored text."""

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..rich_message import NudgeRelation, RichMessage
from .timestamps import to_epoch_seconds


@dataclass(frozen=True, slots=True)
class NudgeMoment:
    timestamp: int
    is_self: bool
    suffix: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class PrivateNudges:
    self_count: int
    peer_count: int
    recent: tuple[NudgeMoment, ...]
    source: str = "wechat"


def analyze_private_nudges(messages: Iterable[RichMessage]) -> PrivateNudges | None:
    """Count one confirmed pair; conflicting duplicate identities count neither."""
    context = None
    events: dict[str, NudgeMoment] = {}
    conflicts: set[str] = set()
    for message in messages:
        if (message.message_type != "nudge" or message.conversation_type != "private"
                or message.source not in {"wechat", "qq"} or not message.message_id
                or not message.conversation_id or type(message.is_self) is not bool
                or len(message.relations) != 1
                or not isinstance(message.relations[0], NudgeRelation)):
            continue
        relation = message.relations[0]
        actor, target = message.sender.identity_id, relation.target_identity_id
        timestamp = to_epoch_seconds(message.timestamp)
        if not actor or not target or actor == target or timestamp is None:
            continue
        owner, peer = (actor, target) if message.is_self else (target, actor)
        candidate = (message.source, message.conversation_id, owner, peer)
        if ((message.source == "wechat" and message.conversation_id != peer)
                or (context is not None and candidate != context)):
            return None
        context = candidate
        event = NudgeMoment(timestamp, message.is_self, relation.suffix)
        if message.message_id in events and events[message.message_id] != event:
            conflicts.add(message.message_id)
        events[message.message_id] = event
    retained = [event for identity, event in events.items() if identity not in conflicts]
    if not retained:
        return None
    self_count = sum(event.is_self for event in retained)
    return PrivateNudges(
        self_count=self_count, peer_count=len(retained) - self_count,
        recent=tuple(sorted(retained, key=lambda event: event.timestamp, reverse=True)[:3]),
        source=context[0],
    )
