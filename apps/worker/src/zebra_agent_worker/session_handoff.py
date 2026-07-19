from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from agent_context import handoff_runtime_evidence
from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.session_handoff import SessionHandoffEnvelope
from agent_core.ports.context_compiler import RuntimeEvidenceInput
from agent_storage import (
    SQLiteEffectLedger,
    SQLiteEventStore,
    SQLiteHandoffDispatchStore,
    SQLiteProjectionStore,
    SQLiteSessionHandoffStore,
    SQLiteWorkspaceProjectionStore,
)
from agent_tools import EffectGuardedToolGateway


class HandoffWorkspaceDriftError(ValueError):
    """Raised when a child no longer has the workspace revision it inherited."""


class HandoffRecoveryRejectedError(ValueError):
    """Raised after a failed recovery gate has released the worker claim."""


@dataclass(frozen=True, slots=True)
class RecoveredHandoff:
    envelope: SessionHandoffEnvelope
    runtime_evidence: RuntimeEvidenceInput


class SessionHandoffRecoveryGate:
    def __init__(self, database_path: str) -> None:
        self._handoffs = SQLiteSessionHandoffStore(database_path)
        self._dispatch = SQLiteHandoffDispatchStore(database_path)
        self._events = SQLiteEventStore(database_path)
        self._sessions = SQLiteProjectionStore(database_path)
        self._workspaces = SQLiteWorkspaceProjectionStore(database_path)

    def recover(
        self,
        session_id: SessionId,
        *,
        worker_id: str,
        recovered_at: datetime,
    ) -> RecoveredHandoff | None:
        events = self._events.list_for_session(session_id)
        received = next(
            (event for event in events if event.event_type is EventType.SESSION_HANDOFF_RECEIVED),
            None,
        )
        if received is None:
            return None
        handoff_id = received.payload.get("handoff_id")
        if not isinstance(handoff_id, str):
            raise ValueError("handoff child is missing inbound handoff id")
        try:
            parsed_handoff_id = HandoffId(UUID(handoff_id))
        except ValueError as exc:
            raise ValueError("handoff child has an invalid inbound handoff id") from exc
        result = self._handoffs.get_handoff(parsed_handoff_id)
        if result is None:
            raise ValueError("handoff child references a missing committed envelope")
        envelope = self._handoffs.get_envelope(result.handoff_id)
        if envelope is None:
            raise ValueError("handoff child references a missing committed envelope")
        recovered = RecoveredHandoff(envelope, handoff_runtime_evidence(envelope))
        if any(event.event_type is EventType.HARNESS_ATTEMPT_STARTED for event in events):
            # ponytail: the inherited revision is checked before the first attempt;
            # later continuations validate current runtime authority through normal setup.
            return recovered
        dispatch = self._dispatch.claim_for_child(
            session_id, worker_id=worker_id, claimed_at=recovered_at
        )
        current_revision = (
            self._handoffs.inspect_source_facts(session_id, at=recovered_at).workspace_revision
            if dispatch is None
            else self._dispatch.acknowledge_if_workspace_matches(
                dispatch.delivery_id,
                child_session_id=session_id,
                worker_id=worker_id,
                expected=envelope.workspace_revision,
                checked_at=recovered_at,
            )
        )
        if current_revision != envelope.workspace_revision:
            self._suspend_for_drift(
                session_id,
                envelope,
                current_revision.revision_hash,
                recovered_at,
            )
            raise HandoffWorkspaceDriftError("handoff workspace revision drift detected")
        return recovered

    def _suspend_for_drift(
        self,
        session_id: SessionId,
        envelope: SessionHandoffEnvelope,
        actual_revision: str,
        created_at: datetime,
    ) -> None:
        session = self._sessions.get_session(session_id)
        workspace = self._workspaces.get_workspace(session_id)
        if session is None or workspace is None:
            raise ValueError("handoff child projections are missing")
        event = SessionEvent.create(
            session_id=session_id,
            sequence=session.current_sequence + 1,
            event_type=EventType.SESSION_HANDOFF_WORKSPACE_DRIFT_DETECTED,
            actor=EventActor.SYSTEM,
            created_at=created_at,
            idempotency_key=f"handoff-drift:{envelope.handoff_id}",
            payload={
                "handoff_id": str(envelope.handoff_id),
                "expected_revision_hash": envelope.workspace_revision.revision_hash,
                "actual_revision_hash": actual_revision,
            },
        )
        persisted = self._events.append(event)
        self._sessions.save_session(apply_event(session, persisted))
        self._workspaces.save_workspace(apply_workspace_event(workspace, persisted))


def guard_effectful_tools(
    gateway: Any,
    *,
    database_path: Path,
    session_id: SessionId,
    recovered_handoff: RecoveredHandoff | None,
    authority_scope: str,
) -> EffectGuardedToolGateway:
    return EffectGuardedToolGateway(
        gateway,
        ledger=SQLiteEffectLedger(database_path),
        root_session_id=(
            session_id if recovered_handoff is None else recovered_handoff.envelope.root_session_id
        ),
        authority_scope=authority_scope,
    )


def recover_worker_handoff(
    gate: SessionHandoffRecoveryGate,
    session_id: SessionId,
    *,
    worker_id: str,
    recovered_at: datetime,
    release: Callable[[], None],
) -> RecoveredHandoff | None:
    try:
        return gate.recover(session_id, worker_id=worker_id, recovered_at=recovered_at)
    except (HandoffWorkspaceDriftError, ValueError) as exc:
        release()
        raise HandoffRecoveryRejectedError(str(exc)) from exc
