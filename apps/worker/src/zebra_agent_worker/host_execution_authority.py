"""Opt-in fresh Host authorization at private context, model and tool boundaries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from threading import RLock
from typing import TYPE_CHECKING

from agent_core.domain.events import SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.ports.model_gateway import ModelGatewayPort

from zebra_agent_worker.execution_events import DurableHarnessEventRecorder

if TYPE_CHECKING:
    from zebra_agent_worker.execution_composition import SessionExecutionComposition

from agent_core.application.execution_authority_replay import latest_authority_snapshot
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.execution_authority import (
    ExecutionAuthorityDecision,
    ExecutionAuthorityResolutionError,
    ExecutionAuthorityRevalidationRequest,
    ExecutionAuthoritySnapshot,
)
from agent_integrations.host_credentials import ConfiguredHmacHostCredentialResolver

from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver
from zebra_agent_worker.host_authority_probe import HostAuthorityProbe


class HostExecutionAuthority:
    def __init__(self, probe: HostAuthorityProbe):
        self.probe = probe
        self._prior: ExecutionAuthoritySnapshot | None = None
        self._recorder: Callable[[], DurableHarnessEventRecorder] | None = None
        self._denied = False
        self._lock = RLock()

    @classmethod
    def for_execution(
        cls, service: SessionExecutionComposition, session_id: SessionId
    ) -> HostExecutionAuthority | None:
        settings = service._settings.host_execution_authority
        if not settings.enabled:
            return None
        if (
            service._task_index_store is None
            or service._task_binding_loader is None
            or service._egress_registry is None
            or not service._settings.host_tool_shared_secret
        ):
            raise ExecutionAuthorityResolutionError("fresh Host authority wiring is incomplete")
        task_id = service._task_index_store.task_id_for_session(session_id)
        if task_id is None:
            raise ExecutionAuthorityResolutionError("fresh Host authority requires indexed Task")
        binding = service._task_binding_loader(session_id)
        from agent_core.domain.task_bindings import TaskBindingSnapshot

        if not isinstance(binding, TaskBindingSnapshot):
            raise ExecutionAuthorityResolutionError("fresh Host authority requires typed binding")
        return cls(
            HostAuthorityProbe(
                binding,
                service._egress_registry,
                ConfiguredHmacHostCredentialResolver(service._settings.host_tool_shared_secret),
                task_id=str(task_id),
                settings=settings,
            )
        )

    def before_private_input(self, ownership_check: Callable[[], None]) -> None:
        ownership_check()
        self.probe.check()
        ownership_check()

    def bind(
        self, recorder: Callable[[], DurableHarnessEventRecorder], events: list[SessionEvent]
    ) -> None:
        self._recorder = recorder
        self._prior = latest_authority_snapshot(events)
        if self._prior is None:
            raise ExecutionAuthorityResolutionError("fresh Host authority has no durable snapshot")
        self.check("context")

    def check(self, boundary: str, identity: str = "") -> None:
        # ponytail: serialize only this attempt's probe/journal chain. Business I/O
        # remains outside the lock; parallel tools still execute concurrently.
        with self._lock:
            if self._denied or self._prior is None or self._recorder is None:
                raise ExecutionAuthorityResolutionError("fresh Host authority unavailable")
            recorder = self._recorder()
            with recorder.mutation():
                recorder.require_active_execution()
                prior = self._prior
                try:
                    expiry = self.probe.check()
                    decision = BoundHostExecutionAuthorityResolver(
                        self.probe.binding
                    ).revalidate_attempt(
                        ExecutionAuthorityRevalidationRequest(
                            session_id=recorder.session.session_id,
                            attempt_number=prior.attempt_number,
                            scope=prior.scope,
                            prior_snapshot=prior,
                            validated_at=datetime.now(UTC),
                        )
                    )
                    snapshot = decision.effective_snapshot
                    if snapshot is not None and expiry < snapshot.expires_at:
                        payload = snapshot.model_dump(exclude={"snapshot_digest"})
                        payload["expires_at"] = expiry
                        snapshot = ExecutionAuthoritySnapshot.model_validate(payload)
                        prior.ensure_not_expanded(snapshot)
                        decision = decision.model_copy(
                            update={
                                "effective_snapshot": snapshot,
                                "effective_snapshot_digest": snapshot.snapshot_digest,
                                "expires_at": expiry,
                            }
                        )
                    recorder.require_active_execution()
                except Exception:
                    self._denied = True
                    # Do not normalize lease, cancellation or storage failures into
                    # provider failures, or run a fallback model after this refusal.
                    raise
                recorder.append(
                    EventType.EXECUTION_AUTHORITY_REVALIDATED,
                    EventActor.SYSTEM,
                    decision.to_event_payload(),
                )
                if decision.decision not in {
                    ExecutionAuthorityDecision.ALLOWED,
                    ExecutionAuthorityDecision.NARROWED,
                }:
                    self._denied = True
                    raise ExecutionAuthorityResolutionError("fresh Host authority denied execution")
                self._prior = decision.effective_snapshot

    def model(self, gateway: ModelGatewayPort) -> ModelGatewayPort:
        if not hasattr(gateway, "authority_check"):
            raise ExecutionAuthorityResolutionError("model transport lacks fresh authority hook")
        gateway.authority_check = lambda request_id: self.check("model", request_id)
        return gateway
