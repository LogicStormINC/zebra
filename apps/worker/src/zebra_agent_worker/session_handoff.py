from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from agent_context import handoff_runtime_evidence
from agent_core.application.session_projection import apply_event
from agent_core.application.workspace_projection import apply_event as apply_workspace_event
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import HandoffId, SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.session_handoff import SessionHandoffEnvelope
from agent_core.ports import ArtifactPayloadStorePort, EffectDispatchPort, EffectLedgerPort
from agent_core.ports.context_compiler import RuntimeEvidenceInput
from agent_storage import (
    ControlPlaneStores,
    sqlite_control_plane_stores,
)
from agent_tools import EffectGuardedToolGateway, FencedEffectToolGateway


class HandoffWorkspaceDriftError(ValueError):
    """Raised when a child no longer has the workspace revision it inherited."""


class HandoffRecoveryRejectedError(ValueError):
    """Raised after a failed recovery gate has released the worker claim."""


@dataclass(frozen=True, slots=True)
class RecoveredHandoff:
    envelope: SessionHandoffEnvelope
    runtime_evidence: RuntimeEvidenceInput


class SessionHandoffRecoveryGate:
    def __init__(
        self,
        database_path: str,
        *,
        stores: ControlPlaneStores | None = None,
    ) -> None:
        active_stores = stores or sqlite_control_plane_stores(database_path)
        self._handoffs = active_stores.handoffs
        self._dispatch = active_stores.handoff_dispatch
        self._events = active_stores.events
        self._leases = active_stores.leases
        self._sessions = active_stores.sessions
        self._workspaces = active_stores.workspaces

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
        lease = self._leases.get(session_id)
        if lease is None or lease.owner_instance_id != worker_id:
            raise ValueError("handoff child is not leased by the recovering worker")
        dispatch = self._dispatch.claim_for_child(
            session_id, fence=lease.fence, claimed_at=recovered_at
        )
        current_revision = (
            self._handoffs.inspect_source_facts(session_id, at=recovered_at).workspace_revision
            if dispatch is None
            else self._dispatch.acknowledge_if_workspace_matches(
                dispatch,
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
    ledger: EffectLedgerPort,
    session_id: SessionId,
    recovered_handoff: RecoveredHandoff | None,
    authority_scope: str,
    dispatch: EffectDispatchPort | None = None,
    artifacts: ArtifactPayloadStorePort | None = None,
    fence: LeaseFence | None = None,
    claim_ttl: timedelta | None = None,
    next_event: Callable[[EventType, EventActor, dict[str, object]], SessionEvent] | None = None,
    accept_event: Callable[[SessionEvent], object] | None = None,
    ownership_check: Callable[[], None] | None = None,
) -> EffectGuardedToolGateway | FencedEffectToolGateway:
    root_session_id = (
        session_id if recovered_handoff is None else recovered_handoff.envelope.root_session_id
    )
    if dispatch is not None:
        if any(
            value is None
            for value in (
                artifacts,
                fence,
                claim_ttl,
                next_event,
                accept_event,
                ownership_check,
            )
        ):
            raise ValueError("fenced Effect dispatch requires its complete runtime context")
        assert artifacts is not None
        assert fence is not None
        assert claim_ttl is not None
        assert next_event is not None
        assert accept_event is not None
        assert ownership_check is not None
        guarded = FencedEffectToolGateway(
            gateway,
            dispatch=dispatch,
            artifacts=artifacts,
            execution_session_id=session_id,
            root_session_id=root_session_id,
            fence=fence,
            claim_ttl=claim_ttl,
            authority_scope=authority_scope,
            next_event=next_event,
            accept_event=accept_event,
            ownership_check=ownership_check,
        )
        guarded.reconcile_expired()
        return guarded
    return EffectGuardedToolGateway(
        gateway,
        ledger=ledger,
        root_session_id=root_session_id,
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
