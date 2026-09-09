"""Recover one immutable, server-bound extension snapshot before execution."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from heapq import heappop, heappush
from typing import Protocol

from agent_core.application import current_turn, project_turns
from agent_core.contracts import (
    SessionCommandAcceptedPayload,
    SessionCommandKind,
    is_command_message_materialization,
    validate_accepted_session_command,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.extension_snapshots import ExtensionSnapshot, ExtensionTaskCeiling
from agent_core.domain.extensions import ExtensionScope
from agent_core.domain.identifiers import SessionId
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports.extension_snapshots import (
    ExtensionSnapshotIntegrityError,
    ExtensionSnapshotNotFoundError,
    ExtensionSnapshotStore,
    ExtensionTaskAuthorityStore,
)
from agent_security.mcp_execution_authority import extension_scope_from_task_ceiling


class WorkerExtensionStore(ExtensionSnapshotStore, ExtensionTaskAuthorityStore, Protocol):
    """The one exact persistence authority used by an enabled cloud Worker."""


@dataclass(frozen=True, slots=True)
class RecoveredTurnExtension:
    scope: ExtensionScope
    snapshot: ExtensionSnapshot
    task_ceiling: ExtensionTaskCeiling


def recover_turn_extension(
    *,
    store: WorkerExtensionStore | None,
    events: list[SessionEvent],
    session_id: SessionId,
    task_binding: TaskBindingSnapshot | None,
    allow_mcp: bool = False,
) -> RecoveredTurnExtension | None:
    """Load only the snapshot named by the accepted command for the active Turn."""

    if store is None:
        return None
    active = current_turn(events)
    binding = _materialized_binding(events, session_id=session_id)
    if binding is None:
        if active is None or active.legacy:
            return None
        ceiling, scope = _validated_authority(store, session_id, task_binding)
        try:
            exists = asyncio.run(
                store.exists(scope=scope, session_id=str(session_id), turn_id=active.turn_id)
            )
        except RuntimeError as exc:
            if "asyncio.run() cannot be called" not in str(exc):
                raise
            raise ValueError("extension recovery requires the synchronous Worker boundary") from exc
        if exists:
            raise ValueError("active Turn snapshot is missing its accepted command binding")
        return None
    assert binding.extension_turn_id is not None
    assert binding.extension_snapshot_digest is not None
    ceiling, scope = _validated_authority(store, session_id, task_binding)
    try:
        snapshot = asyncio.run(
            store.get(
                scope=scope,
                session_id=str(session_id),
                turn_id=binding.extension_turn_id,
                expected_digest=binding.extension_snapshot_digest,
            )
        )
    except (ExtensionSnapshotIntegrityError, ExtensionSnapshotNotFoundError) as exc:
        raise ValueError("bound extension snapshot is unavailable or invalid") from exc
    except RuntimeError as exc:
        if "asyncio.run() cannot be called" not in str(exc):
            raise
        raise ValueError("extension recovery requires the synchronous Worker boundary") from exc
    if (
        snapshot.scope != scope
        or snapshot.session_id != str(session_id)
        or snapshot.turn_id != binding.extension_turn_id
        or snapshot.digest != binding.extension_snapshot_digest
    ):
        raise ValueError("extension snapshot disagrees with its trusted Turn binding")
    if snapshot.mcp and not allow_mcp:
        raise ValueError("MCP snapshots are not authorized for this Worker slice")
    if any(skill.version.skill_id not in ceiling.skill_components for skill in snapshot.skills):
        raise ValueError("extension snapshot exceeds the frozen Task Skill ceiling")
    return RecoveredTurnExtension(scope=scope, snapshot=snapshot, task_ceiling=ceiling)


def _materialized_binding(
    events: list[SessionEvent], *, session_id: SessionId
) -> SessionCommandAcceptedPayload | None:
    active = current_turn(events)
    event_ids: dict[object, int] = defaultdict(int)
    canonical: dict[object, list[SessionEvent]] = defaultdict(list)
    legacy: dict[str, list[SessionEvent]] = defaultdict(list)
    accepted_events: list[SessionEvent] = []
    message_types = {EventType.USER_MESSAGE_RECEIVED, EventType.CLARIFICATION_RESPONDED}
    for event in events:
        event_ids[event.event_id] += 1
        if event.event_type is EventType.SESSION_COMMAND_ACCEPTED:
            accepted_events.append(event)
        elif event.event_type in message_types:
            if event.causation_id is not None:
                canonical[event.causation_id].append(event)
            elif event.idempotency_key is not None:
                legacy[event.idempotency_key].append(event)
    bound_messages: list[tuple[SessionEvent, SessionCommandAcceptedPayload]] = []
    for event in accepted_events:
        parsed = SessionCommandAcceptedPayload.model_validate(event.payload)
        binding_values = (
            parsed.extension_snapshot_digest,
            parsed.extension_turn_id,
        )
        if binding_values == (None, None):
            continue
        accepted = validate_accepted_session_command(
            event.payload, session_id=session_id, idempotency_key=event.idempotency_key
        )
        if (
            accepted.extension_snapshot_digest is None
            or accepted.extension_turn_id is None
            or accepted.kind
            not in {
                SessionCommandKind.MESSAGE,
                SessionCommandKind.RUN,
                SessionCommandKind.RESUME,
            }
        ):
            raise ValueError("accepted command has an invalid extension binding")
        if (
            event.session_id != session_id
            or event.actor is not EventActor.USER
            or event_ids[event.event_id] != 1
        ):
            raise ValueError("bound accepted command identity is not canonical")
        bound_messages.append((event, accepted))
    turns = sorted(project_turns(events), key=lambda turn: turn.opened_sequence)
    known_turns = {turn.turn_id for turn in turns}
    open_turns: list[tuple[int, int]] = []
    next_turn = 0
    candidates: list[tuple[int, SessionCommandAcceptedPayload]] = []
    for event, accepted in sorted(bound_messages, key=lambda item: item[0].sequence):
        assert accepted.extension_turn_id is not None
        if accepted.kind in {SessionCommandKind.RUN, SessionCommandKind.RESUME}:
            while next_turn < len(turns) and turns[next_turn].opened_sequence < event.sequence:
                heappush(open_turns, (-turns[next_turn].opened_sequence, next_turn))
                next_turn += 1
            while open_turns:
                closed = turns[open_turns[0][1]].closed_sequence
                if closed is None or closed >= event.sequence:
                    break
                heappop(open_turns)
            prior_turn = turns[open_turns[0][1]] if open_turns else None
            if (
                prior_turn is None
                or prior_turn.legacy
                or prior_turn.turn_id != accepted.extension_turn_id
            ):
                raise ValueError("execution command extension binding is not its active Turn")
            if active is not None and active.turn_id == accepted.extension_turn_id:
                candidates.append((event.sequence, accepted))
            continue
        matches = _command_materializations(canonical, legacy, event, accepted)
        if len(matches) != 1:
            detail = "missing" if not matches else "ambiguous"
            raise ValueError(f"bound message command has {detail} canonical materialization")
        message = matches[0]
        if message.sequence <= event.sequence:
            raise ValueError("message materialization precedes its accepted command")
        clarification = accepted.payload.get("clarification_id") is not None
        expected_type = (
            EventType.CLARIFICATION_RESPONDED if clarification else EventType.USER_MESSAGE_RECEIVED
        )
        if message.event_type is not expected_type or message.actor is not EventActor.USER:
            raise ValueError("bound message has invalid canonical materialization")
        if message.session_id != session_id:
            raise ValueError("canonical command message belongs to another session")
        if message.causation_id == event.event_id:
            if message.idempotency_key != f"command-input:{event.event_id}":
                raise ValueError("canonical command message identity is corrupt")
        if message.payload.get("content") != str(
            accepted.payload.get("content", "")
        ).strip() or message.payload.get("clarification_id") != accepted.payload.get(
            "clarification_id"
        ):
            raise ValueError("canonical command message payload is corrupt")
        if not clarification:
            message_turn = message.payload.get("turn_id")
            if message_turn != accepted.extension_turn_id:
                raise ValueError("materialized human Turn does not match accepted extension Turn")
        if accepted.extension_turn_id not in known_turns:
            raise ValueError("accepted extension Turn does not match a known human Turn")
        if active is None:
            continue
        if accepted.extension_turn_id != active.turn_id:
            continue
        if active.legacy:
            raise ValueError("bound extension command cannot target a legacy Turn")
        candidates.append((message.sequence, accepted))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def _command_materializations(
    canonical: dict[object, list[SessionEvent]],
    legacy: dict[str, list[SessionEvent]],
    accepted_event: SessionEvent,
    accepted: SessionCommandAcceptedPayload,
) -> list[SessionEvent]:
    legacy_key = f"{accepted.idempotency_key}:message"
    matches = {
        event.event_id: event
        for event in (*canonical.get(accepted_event.event_id, ()), *legacy.get(legacy_key, ()))
        if is_command_message_materialization(
            causation_id=event.causation_id,
            idempotency_key=event.idempotency_key,
            accepted_event_id=accepted_event.event_id,
            accepted_idempotency_key=accepted.idempotency_key,
        )
    }
    return list(matches.values())


def _validated_authority(
    store: WorkerExtensionStore,
    session_id: SessionId,
    task_binding: TaskBindingSnapshot | None,
) -> tuple[ExtensionTaskCeiling, ExtensionScope]:
    if task_binding is None:
        raise ValueError("extension recovery requires a frozen Task binding")
    ceiling = store.resolve_task_ceiling(session_id=str(session_id))
    if (
        ceiling.task_id != task_binding.task_id
        or ceiling.binding.binding_digest != task_binding.binding_digest
        or ceiling.binding != task_binding
    ):
        raise ValueError("extension and execution Task bindings disagree")
    return ceiling, extension_scope_from_task_ceiling(ceiling)
