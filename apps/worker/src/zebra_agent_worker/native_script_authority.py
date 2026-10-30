"""Extend in-attempt script authority only from an explicitly renewed binding.

A continuous attempt with native scripts can outlive the persisted authority
snapshot (worker pickup plus cold sandbox invocations) while the Host renewed
the binding. The refresh reuses the exact attempt-boundary resolution path:
only a stored binding renewal with unchanged ceilings may extend, every
extension appends durable authority evidence, and without a renewal the
original fail-closed refusal surfaces unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agent_core.application.execution_authority_replay import latest_authority_snapshot
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.execution_authority import ExecutionAuthorityResolutionRequest
from agent_core.domain.identifiers import SessionId
from agent_core.domain.task_bindings import TaskBindingSnapshot
from agent_core.ports.event_store import EventStorePort

from zebra_agent_worker.bound_execution_authority import (
    BoundHostExecutionAuthorityResolver,
    load_bound_binding,
    select_attempt_authority,
)
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder

# A cold container-backed invocation must fit inside the remaining window;
# refreshing earlier than one binding window is wasteful, later is fatal.
FORWARD_HORIZON_SECONDS = 60.0


@dataclass(frozen=True)
class RenewedBindingAuthority:
    """Load the current stored binding and persist renewed authority evidence."""

    binding_loader: Callable[[SessionId], object] | None
    events: EventStorePort
    session_id: SessionId
    attempt_number: int

    def ensure_current(
        self,
        recorder: DurableHarnessEventRecorder,
        *,
        horizon_seconds: float = FORWARD_HORIZON_SECONDS,
    ) -> TaskBindingSnapshot | None:
        """Best-effort proactive extension; never weakens an existing refusal.

        Returns the stored binding when durable authority evidence was appended,
        so callers can swap any binding-held checks to the current generation.
        """
        loader = self.binding_loader
        if loader is None:
            return None
        history = self.events.list_for_session(self.session_id)
        latest = latest_authority_snapshot(tuple(history))
        now = datetime.now(UTC)
        if latest is None or latest.expires_at > now + timedelta(seconds=horizon_seconds):
            return None
        binding = load_bound_binding(loader, self.session_id)
        if binding is None:
            return None
        resolver, scope, _ = select_attempt_authority(
            None, None, None, None, self.session_id, binding=binding
        )
        if not isinstance(resolver, BoundHostExecutionAuthorityResolver) or scope is None:
            return None
        request = ExecutionAuthorityResolutionRequest(
            session_id=self.session_id,
            attempt_number=self.attempt_number,
            scope=scope,
            validated_at=now,
        )
        renewed = resolver.resolve_renewed_binding(request, latest)
        if renewed is None:
            # Without an explicit renewal never append a denied revalidation:
            # a refused durable event would poison every later replay.
            return None
        recorder.append(
            EventType.EXECUTION_AUTHORITY_RESOLVED,
            EventActor.SYSTEM,
            renewed.to_event_payload(),
            created_at=now,
        )
        return binding

