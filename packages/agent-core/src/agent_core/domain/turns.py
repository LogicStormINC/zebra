"""Turn lifecycle domain vocabulary (ADR-026)."""

from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from agent_core.domain.identifiers import TurnId


class TurnStatus(StrEnum):
    """Outcome of one user-visible interaction round inside a Segment."""

    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InteractionMode(StrEnum):
    """How a Task admission declares its multi-turn shape."""

    CONVERSATION = "conversation"
    ONE_SHOT = "one_shot"


def resolve_interaction_mode(value: str | None) -> InteractionMode:
    """Interpret a TASK_PREPARED interaction_mode with legacy replay rules.

    Old events carry no interaction_mode. They keep the exact legacy
    behavior (every final answer closes the Segment), so a missing value
    resolves to ONE_SHOT rather than the conversation default.
    """

    if value is None:
        return InteractionMode.ONE_SHOT
    return InteractionMode(value)


def derive_turn_id(session_id: UUID, turn_index: int) -> TurnId:
    """Deterministic Turn identity inside one Segment.

    Derived from the Segment (session) identity and the turn position so
    replays of the same admission converge on the same Turn.
    """

    return TurnId(uuid5(NAMESPACE_URL, f"zebra:turn:{session_id}:{turn_index}"))
