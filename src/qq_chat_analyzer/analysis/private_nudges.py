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
    action: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class PrivateNudges:
    self_count: int
    peer_count: int
    recent: tuple[NudgeMoment, ...]
    source: str = "wechat"
    self_suffix: str = field(default="", repr=False)
    peer_suffix: str = field(default="", repr=False)
    self_action: str = field(default="", repr=False)
    peer_action: str = field(default="", repr=False)


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
        event = NudgeMoment(timestamp, message.is_self, relation.suffix, relation.action)
        if message.message_id in events and events[message.message_id] != event:
            conflicts.add(message.message_id)
        events[message.message_id] = event
    retained = [event for identity, event in events.items() if identity not in conflicts]
    if not retained:
        return None
    self_count = sum(event.is_self for event in retained)
    self_action, self_suffix = _latest_style(retained, is_self=True)
    peer_action, peer_suffix = _latest_style(retained, is_self=False)
    return PrivateNudges(
        self_count=self_count, peer_count=len(retained) - self_count,
        recent=tuple(sorted(retained, key=lambda event: event.timestamp, reverse=True)[:3]),
        source=context[0],
        self_suffix=self_suffix, peer_suffix=peer_suffix,
        self_action=self_action, peer_action=peer_action,
    )


def _latest_style(events: list[NudgeMoment], *, is_self: bool) -> tuple[str, str]:
    """Use the latest retained direction, leaving simultaneous disagreement unknown."""
    direction = [event for event in events if event.is_self == is_self]
    latest = max((event.timestamp for event in direction), default=None)
    styles = {(event.action, event.suffix) for event in direction if event.timestamp == latest}
    return next(iter(styles)) if len(styles) == 1 else ("", "")
