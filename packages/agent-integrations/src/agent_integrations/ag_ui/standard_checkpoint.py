"""Bounded root-Segment cells preserve one public lifecycle across handoffs."""

from collections.abc import Callable
from hashlib import sha256

from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.ports.task_projection_checkpoints import (
    ProjectionCell,
    ProjectionCellKey,
)

from agent_integrations.ag_ui.contracts import AgUiProjectionError
from agent_integrations.ag_ui.standard_state import (
    MAX_STANDARD_STATE_BYTES,
    StandardProjectionState,
)

_CHARS = 1800
# ponytail: O(state) snapshot per Event; bounded derived metadata only. G7 can
# replace this with indexed per-entity cells if measured 10k-history costs require it.
_MAX_BYTES = MAX_STANDARD_STATE_BYTES


def state_key(root: SessionId, key: str) -> ProjectionCellKey:
    return ProjectionCellKey(root, "standard_v1", key)


def load_standard(
    root: SessionId,
    load: Callable[[tuple[ProjectionCellKey, ...]], tuple[ProjectionCell, ...]],
    *,
    required: bool = False,
) -> StandardProjectionState:
    rows = load((state_key(root, "count"),))
    if not rows:
        if required:
            raise AgUiProjectionError("required standard checkpoint is missing")
        return StandardProjectionState()
    try:
        count = int(rows[0].value or "0")
    except (TypeError, ValueError):
        raise AgUiProjectionError("invalid standard checkpoint count") from None
    if not 1 <= count <= _MAX_BYTES // _CHARS + 1:
        raise AgUiProjectionError("standard checkpoint exceeds state bound")
    rows = load(tuple(state_key(root, str(i)) for i in range(count)))
    values = {row.key.key: row.value for row in rows}
    if any(values.get(str(i)) is None for i in range(count)):
        raise AgUiProjectionError("standard checkpoint is incomplete")
    return StandardProjectionState.restore("".join(str(values[str(i)]) for i in range(count)))


def save_standard(
    root: SessionId,
    state: StandardProjectionState,
    change: Callable[[ProjectionCellKey, int, str | None], None],
    position: int,
) -> None:
    value = state.snapshot()
    if len(value.encode()) > _MAX_BYTES:
        raise AgUiProjectionError("standard checkpoint exceeds bounded metadata budget")
    chunks = [value[i : i + _CHARS] for i in range(0, len(value), _CHARS)]
    change(state_key(root, "count"), position, str(len(chunks)))
    for i, chunk in enumerate(chunks):
        change(state_key(root, str(i)), position, chunk)


def membership_key(
    root: SessionId, event: SessionEvent, protocol_run_id: str | None
) -> tuple[ProjectionCellKey, str, str] | None:
    if event.event_type is EventType.MODEL_RESPONSE_RECEIVED:
        value = event.payload.get("model_call_id") or "event:" + str(event.event_id)
        kind = "usage"
    elif event.event_type is EventType.PUBLIC_OUTPUT:
        value = event.payload.get("output_id")
        kind = "publication"
    elif event.event_type is EventType.ANSWER_COMMITTED:
        value = "answer:" + str(event.event_id)
        kind = "publication"
    else:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return (
        state_key(
            root,
            kind
            + ":"
            + sha256(
                (
                    (str(protocol_run_id) if kind == "usage" else "publication") + ":" + value
                ).encode()
            ).hexdigest(),
        ),
        kind,
        value,
    )


def load_membership(
    root: SessionId,
    event: SessionEvent,
    state: StandardProjectionState,
    load: Callable[[tuple[ProjectionCellKey, ...]], tuple[ProjectionCell, ...]],
) -> None:
    member = membership_key(root, event, state.protocol_run_id)
    if member is None:
        return
    key, kind, value = member
    if any(row.value == "1" for row in load((key,))):
        (state.seen_usage if kind == "usage" else state.publications).add(value)


def save_membership(
    root: SessionId,
    event: SessionEvent,
    state: StandardProjectionState,
    change: Callable[[ProjectionCellKey, int, str | None], None],
    position: int,
) -> None:
    member = membership_key(root, event, state.protocol_run_id)
    if member is not None:
        key, kind, value = member
        if value in (state.seen_usage if kind == "usage" else state.publications):
            change(key, position, "1")
