"""Real cloud callback binding; no synthetic Turn, Run or verified Grant."""

from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID, uuid4

from agent_core.application.turn_projection import current_turn
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import TurnId
from agent_core.domain.leases import WorkerLease
from agent_core.domain.stream_admission import RunStreamAdmission, StreamMode
from agent_core.domain.task_bindings import require_task_host_context
from agent_core.domain.transient_output import TransientGeneration
from agent_core.ports.transient_output import TransientStreamScope, TransientWriterAuthorization
from agent_integrations.redis_transient_output import (
    RedisTransientOutput,
    TransientOutputUnavailable,
)
from agent_integrations.run_stream_admission import load_run_stream_admission
from agent_storage import PostgresControlPlaneStores
from agent_storage.postgres.stream_proof_batch import StreamProofReader, StreamProofSnapshot
from agent_storage.postgres.task_io import task_io_deadline
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_worker.progress_recovery import WorkerProgressRecovery
from zebra_agent_worker.transient_output_runtime import TransientDeltaSink, WorkerTransientCallGate


def compose_transient_output_factory(
    stores: PostgresControlPlaneStores, *, dsn: str, namespace: str, settings: ZebraAgentSettings
) -> Callable[[WorkerProgressRecovery, WorkerLease], TransientDeltaSink | None]:
    """Always mode-aware, even when new admission is disabled or Redis is absent."""
    reader = StreamProofReader(
        dsn, deployment_namespace=namespace,
        task_io_connections=getattr(stores, "task_io_connections", None),
    )

    def factory(progress: WorkerProgressRecovery, lease: WorkerLease) -> TransientDeltaSink | None:
        run_scope = progress.head.scope

        try:
            with task_io_deadline(monotonic() + 2):
                selected = load_run_stream_admission(
                    stores.tasks, run_scope.task_id, run_scope.run_id
                )
                run = stores.tasks.read_run_header(run_scope.task_id, run_scope.run_id)
                if run.anchor is not None and run.anchor.event_id != run_scope.anchor_event_id:
                    raise TransientOutputUnavailable("Worker Run anchor changed")
            if selected is None or selected.mode is StreamMode.LEGACY:
                return None
        except Exception:
            # No transport can downgrade unknown/faulting mode to v1 partial writes.
            selected = None

        def admission() -> RunStreamAdmission | None:
            # Accepted command Events are append-only: cache only their immutable
            # proven mode. Current Run/anchor/privacy/lease/Host/Turn remain fresh.
            return selected

        gate: WorkerTransientCallGate | None = None

        def resolve(authorization: TransientWriterAuthorization) -> None:
            if gate is None:
                raise TransientOutputUnavailable("no actual callback gate")
            gate.resolve(authorization)

        try:
            port = (
                RedisTransientOutput.from_url(
                    settings.live_events.redis_url,
                    resolve_authorization=resolve,
                    descriptor_source=lambda authorization: gate.request_sequence if gate else 0,
                )
                if settings.live_events.redis_url
                else None
            )
        except Exception:
            port = None  # Broken visual transport cannot fail durable execution.

        def open_call(call_id: str, attempt: int) -> WorkerTransientCallGate:
            nonlocal gate
            if selected is None:
                raise TransientOutputUnavailable("initial Run mode was unavailable")
            with reader.snapshot() as proof:
                # The hook follows the durable request sink; a publication timer may
                # already have advanced progress, so bind its exact bounded source row.
                position = progress.head.through_sequence
                entry = None
                source_bytes = 0
                for candidate in range(
                    position, max(run_scope.anchor_sequence - 1, position - 256), -1
                ):
                    header = proof.read_event_header(run_scope.task_id, candidate)
                    if header is None:
                        raise TransientOutputUnavailable("callback Task position is unavailable")
                    if header.event_type is not EventType.MODEL_REQUEST_STARTED:
                        continue
                    page = proof.read_event_page(
                        run_scope.task_id,
                        candidate - 1,
                        through_sequence=candidate,
                        limit=1,
                        max_bytes=1_048_576,
                    )
                    if len(page.events) != 1 or page.has_more:
                        raise TransientOutputUnavailable(
                            "actual model callback source is unavailable"
                        )
                    current = page.events[0]
                    request = current.event
                    source_bytes += page.byte_count
                    if source_bytes > 1_048_576 or (
                        current.task_sequence != candidate
                        or current.segment_id != header.segment_id
                        or request.event_type is not EventType.MODEL_REQUEST_STARTED
                        or request.event_id != header.event_id
                        or request.sequence != header.segment_sequence
                        or current.segment_id != lease.session_id
                        or request.actor is not EventActor.HARNESS
                        or request.payload.get("attempt_number") != attempt
                    ):
                        raise TransientOutputUnavailable("callback source changed from its header")
                    if request.payload.get("purpose") == "public_expression":
                        ancillary_id = request.payload.get("model_call_id")
                        if (
                            not isinstance(ancillary_id, str)
                            or not ancillary_id
                            or ancillary_id == call_id
                        ):
                            raise TransientOutputUnavailable(
                                "ancillary callback identity conflicts"
                            )
                        continue  # Only this trusted, distinct ancillary request may be passed.
                    entry = current
                    position = candidate
                    break
                if entry is None:
                    raise TransientOutputUnavailable(
                        "callback request exceeds header lookup budget"
                    )
                request = entry.event
                if (
                    entry.segment_id != lease.session_id
                    or request.actor is not EventActor.HARNESS
                    or request.event_type is not EventType.MODEL_REQUEST_STARTED
                    or request.payload.get("model_call_id") != call_id
                    or request.payload.get("attempt_number") != attempt
                    or request.payload.get("purpose") is not None
                ):
                    raise TransientOutputUnavailable("actual model callback source conflicts")
                turn = current_turn(proof.authority_events(entry.segment_id))
                if turn is None or turn.legacy or turn.opened_sequence >= request.sequence:
                    raise TransientOutputUnavailable("no canonical open Turn for temporary draft")
                turn_id = TurnId(UUID(turn.turn_id))
                binding = proof.binding(entry.segment_id)
                if binding is None or binding.task_id != str(run_scope.task_id):
                    raise TransientOutputUnavailable("Task Host binding is unavailable")
                host = binding.host_capability
                scope = TransientStreamScope(
                    deployment_namespace=namespace,
                    authority_scope=OpaqueAuthorityScope(
                        authority_issuer=host.authority_issuer,
                        namespace_id=host.namespace_id,
                        allowed_session_ids=(str(entry.segment_id),),
                    ),
                    generation=TransientGeneration(
                        task_id=run_scope.task_id,
                        segment_id=entry.segment_id,
                        turn_id=turn_id,
                        run_id=run_scope.run_id,
                        attempt_number=attempt,
                        model_call_id=call_id,
                        message_id=f"message:{call_id}",
                        generation_id=str(uuid4()),
                        lease_fence=lease.fence.fencing_token,
                    ),
                )

                def snapshot_expiry(
                    candidate: TransientStreamScope, fresh_proof: StreamProofSnapshot
                ) -> datetime:
                    fresh = fresh_proof.binding(entry.segment_id)
                    if fresh is None or candidate != scope:
                        raise TransientOutputUnavailable("Task Host binding changed")
                    context = fresh.host_capability.host_context
                    if context is None:
                        raise TransientOutputUnavailable("Task has no API-verified Host context")
                    require_task_host_context(
                        fresh,
                        context,
                        task_id=str(run_scope.task_id),
                        now=datetime.now(UTC),
                        authority_issuer=scope.authority_scope.authority_issuer,
                        run_id=run_scope.run_id,
                    )
                    require_task_host_context(
                        binding,
                        context,
                        task_id=str(run_scope.task_id),
                        now=datetime.now(UTC),
                        authority_issuer=scope.authority_scope.authority_issuer,
                        run_id=run_scope.run_id,
                    )
                    if (
                        fresh.host_capability.namespace_id != scope.authority_scope.namespace_id
                        or fresh.host_capability.authority_issuer
                        != scope.authority_scope.authority_issuer
                    ):
                        raise TransientOutputUnavailable("Task Host namespace changed")
                    current = current_turn(fresh_proof.authority_events(entry.segment_id))
                    if current is None or current.legacy or current.turn_id != str(turn_id):
                        raise TransientOutputUnavailable("callback Turn closed or changed")
                    expiry = context.expires_at
                    assert expiry is not None
                    frozen_expiry = fresh.host_capability.grant_expires_at
                    return min(expiry, frozen_expiry) if frozen_expiry is not None else expiry

                def fresh_expiry(candidate: TransientStreamScope) -> datetime:
                    with reader.snapshot() as fresh_proof:
                        return snapshot_expiry(candidate, fresh_proof)

                gate = WorkerTransientCallGate(
                    scope=scope,
                    fence=lease.fence,
                    expected_anchor_event_id=run_scope.anchor_event_id,
                    request_sequence=position,
                    tasks=stores.tasks,
                    leases=stores.leases,
                    load_admission=admission,
                    fresh_grant_expiry=fresh_expiry,
                    fresh_snapshot=reader.snapshot,
                    snapshot_grant_expiry=snapshot_expiry,
                )
                return gate

        return TransientDeltaSink(
            port, open_call, durable_anchor=lambda: progress.head.through_sequence
        )

    return factory
