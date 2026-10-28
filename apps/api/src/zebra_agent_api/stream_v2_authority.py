"""Fresh canonical qualification of Redis generation locators for one signed request."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from agent_core.application.turn_projection import current_turn
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import TaskId
from agent_core.domain.stream_admission import StreamMode
from agent_core.domain.task_bindings import require_task_host_context
from agent_core.ports.agent_tasks import AgentTaskPort
from agent_core.ports.task_projection_checkpoints import CheckpointNotReady, ProjectionScope
from agent_integrations.ag_ui.profiles import AgUiProjectionProfile
from agent_integrations.redis_transient_discovery import TransientDescriptor, transient_lane
from agent_integrations.run_stream_admission import load_run_stream_admission
from agent_storage import ControlPlaneStores
from agent_storage.postgres.stream_proof_batch import StreamProofReader, StreamProofSnapshot


@dataclass(frozen=True, slots=True)
class V2ReadBinding:
    namespace: str
    task_id: TaskId
    run_id: str
    authority: OpaqueAuthorityScope
    host: HostContextEnvelope
    key_prefix: str = "zebra:transient:v2"

    @property
    def lane(self) -> str:
        assert self.authority.allowed_session_ids is not None
        return transient_lane(
            self.namespace,
            self.authority,
            str(self.task_id),
            self.authority.allowed_session_ids[0],
            self.run_id,
            key_prefix=self.key_prefix,
        )


class V2ReadAuthority:
    def __init__(
        self,
        stores: ControlPlaneStores,
        *,
        dsn: str,
        namespace: str,
        key_prefix: str = "zebra:transient:v2",
    ) -> None:
        self.stores, self.dsn, self.namespace = stores, dsn, namespace
        self.key_prefix = key_prefix
        self.proofs = StreamProofReader(dsn, deployment_namespace=namespace)

    def bind(self, task_id: TaskId, run_id: str, host: HostContextEnvelope) -> V2ReadBinding | None:
        with self.proofs.snapshot() as proof:
            return self.bind_snapshot(proof, task_id, run_id, host)

    _snapshot_native_bind = bind

    def bind_snapshot(
        self, proof: StreamProofSnapshot, task_id: TaskId, run_id: str, host: HostContextEnvelope
    ) -> V2ReadBinding | None:
        admission = load_run_stream_admission(cast(AgentTaskPort, proof), task_id, run_id)
        if admission is None or admission.mode is StreamMode.LEGACY:
            return None
        header = proof.read_task_header(task_id, require_source_coverage=True)
        if header is None or type(header.strict_coverage) is not bool:
            raise ValueError("provisional output privacy is unavailable")
        binding = proof.binding(header.active_segment_id)
        if binding is None:
            raise ValueError("provisional Task Host binding is unavailable")
        require_task_host_context(
            binding,
            host,
            task_id=str(task_id),
            run_id=run_id,
            now=datetime.now(UTC),
        )
        return V2ReadBinding(
            self.namespace,
            task_id,
            run_id,
            OpaqueAuthorityScope(
                authority_issuer=binding.host_capability.authority_issuer,
                namespace_id=binding.host_capability.namespace_id,
                allowed_session_ids=(str(header.active_segment_id),),
            ),
            host,
            self.key_prefix,
        )

    _snapshot_native_bind_snapshot = bind_snapshot

    def bind_profile(
        self,
        task_id: TaskId,
        run_id: str,
        host: HostContextEnvelope,
        profile: AgUiProjectionProfile,
        *,
        stores: object | None = None,
    ) -> V2ReadBinding:
        native = self.stores if stores is None else stores
        database = getattr(getattr(native, "tasks", None), "_database", None)
        if (
            getattr(database, "_dsn", None) != self.dsn
            or getattr(database, "deployment_namespace", None) != self.namespace
            or getattr(native, "deployment_namespace", None) != self.namespace
        ):
            raise ValueError("profile read proof crosses its API database scope")
        with self.proofs.snapshot() as proof:
            run = proof.read_run_header(task_id, run_id)
            if run.anchor is None:
                raise CheckpointNotReady("profile observation requires an admitted Run")
            header = proof.read_task_header(task_id, require_source_coverage=True)
            if header is None or type(header.strict_coverage) is not bool:
                raise ValueError("canonical output privacy is unavailable")
            binding = proof.binding(header.active_segment_id)
            if binding is None:
                raise ValueError("canonical Task Host binding is unavailable")
            require_task_host_context(
                binding, host, task_id=str(task_id), run_id=run_id, now=datetime.now(UTC)
            )
            profile.binding_digest(
                ProjectionScope(
                    self.namespace,
                    task_id,
                    run.anchor.event_id,
                    profile.checkpoint_version(coverage=run.strict_coverage),
                ),
                run,
            )
            if proof.read_event_header(task_id, run.start) != run.anchor:
                raise ValueError("profile anchor is not canonical")
            # Profile output is canonical-only. Its signed lane must survive a
            # mutable active-Segment handoff while remaining bound to this Run.
            return V2ReadBinding(
                self.namespace,
                task_id,
                run_id,
                OpaqueAuthorityScope(
                    authority_issuer=binding.host_capability.authority_issuer,
                    namespace_id=binding.host_capability.namespace_id,
                    allowed_session_ids=(str(run.anchor.segment_id),),
                ),
                host,
                self.key_prefix,
            )

    def qualify(self, bound: V2ReadBinding, descriptor: TransientDescriptor) -> datetime:
        with self.proofs.snapshot() as proof:
            return self._qualify(proof, bound, descriptor)

    def _qualify(
        self, proof: StreamProofSnapshot, bound: V2ReadBinding, descriptor: TransientDescriptor
    ) -> datetime:
        scope, generation = descriptor.scope, descriptor.scope.generation
        fresh = self.bind_snapshot(proof, bound.task_id, bound.run_id, bound.host)
        if fresh != bound or (
            scope.deployment_namespace != bound.namespace
            or scope.authority_scope != bound.authority
            or generation.task_id != bound.task_id
            or generation.run_id != bound.run_id
            or descriptor.fence.fencing_token != generation.lease_fence
        ):
            raise ValueError("temporary generation crosses canonical request scope")
        run = proof.read_latest_run_header(bound.task_id)
        if (
            run.run_id != bound.run_id
            or run.stop is not None
            or run.control_only
            or run.strict_coverage
        ):
            raise ValueError("temporary Run is no longer active")
        page = proof.read_event_page(
            bound.task_id,
            descriptor.request_sequence - 1,
            through_sequence=run.highwater,
            limit=256,
            max_bytes=1_048_576,
        )
        if not page.events or page.has_more:
            raise ValueError("temporary source exceeds bounded qualification")
        first = page.events[0]
        request = first.event
        if (
            not run.start <= descriptor.request_sequence <= run.highwater
            or first.task_sequence != descriptor.request_sequence
            or first.segment_id != generation.segment_id
            or request.event_type is not EventType.MODEL_REQUEST_STARTED
            or request.actor is not EventActor.HARNESS
            or request.payload.get("purpose") is not None
            or request.payload.get("model_call_id") != generation.model_call_id
            or request.payload.get("attempt_number") != generation.attempt_number
        ):
            raise ValueError("temporary source does not identify the actual callback")
        for entry in page.events[1:]:
            event = entry.event
            if event.event_type in {
                EventType.HARNESS_ATTEMPT_STARTED,
                EventType.SESSION_COMPLETED,
                EventType.SESSION_FAILED,
                EventType.SESSION_CANCELLED,
            }:
                raise ValueError("temporary callback was superseded")
            if (
                event.event_type is EventType.MODEL_RESPONSE_RECEIVED
                and event.payload.get("model_call_id") == generation.model_call_id
            ):
                raise ValueError("temporary callback has a canonical response")
            if event.event_type is EventType.MODEL_REQUEST_STARTED and (
                event.actor is not EventActor.HARNESS
                or entry.segment_id != generation.segment_id
                or event.payload.get("purpose") != "public_expression"
                or event.payload.get("attempt_number") != generation.attempt_number
                or not isinstance(event.payload.get("model_call_id"), str)
                or not event.payload.get("model_call_id")
                or event.payload.get("model_call_id") == generation.model_call_id
            ):
                raise ValueError("temporary callback identity was reused")
        turn = current_turn(proof.authority_events(generation.segment_id))
        if (
            turn is None
            or turn.legacy
            or turn.turn_id != str(generation.turn_id)
            or turn.opened_sequence >= request.sequence
        ):
            raise ValueError("temporary generation has no canonical open Turn")
        lease = proof.get(generation.segment_id)
        now = datetime.now(UTC)
        if lease is None or lease.fence != descriptor.fence or lease.expires_at <= now:
            raise ValueError("temporary generation full lease fence is stale")
        assert bound.host.expires_at is not None
        return min(now + timedelta(seconds=30), lease.expires_at, bound.host.expires_at)
