"""Explicit Cloud snapshot-create callback; no Worker activation or reconciliation."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from agent_core.application.coverage_admission import validate_coverage_admission
from agent_core.domain.artifact_objects import (
    ArtifactObjectIntegrityError,
    ArtifactObjectUnavailableError,
)
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadLifecycleStatus
from agent_core.domain.cloud_artifact_requests import ArtifactMetadataQuery
from agent_core.domain.coverage_contracts import CoverageRefusalReason as Reason
from agent_core.domain.coverage_contracts import CoverageRefusedError, coverage_digest
from agent_core.domain.coverage_task_admission import CoverageTaskAdmission
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from agent_core.domain.leases import LeaseFence
from agent_core.domain.modeling import ModelToolDefinition
from agent_core.domain.policies import PolicyDecision, PolicyDecisionType
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_core.domain.tools import ToolCall, ToolResult
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.artifact_payload_read import ArtifactPayloadReadUnavailableError
from agent_core.ports.effect_dispatch import effect_input
from agent_core.ports.policy_engine import PolicyEnginePort
from agent_integrations.host_tools.contracts import HostToolManifest
from agent_integrations.host_tools.gateway import HostToolGateway
from agent_storage.artifact_payload_reads import CloudArtifactPayloadReader
from agent_storage.artifact_projection import artifact_id_from_uri
from agent_storage.postgres.artifact_payloads import PostgresCloudArtifactPayloadStore
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.leases import assert_current_lease_fence
from agent_storage.postgres.outbox import PostgresEffectDispatchStore
from agent_tools.effect_guard import FencedEffectToolGateway
from agent_tools.effect_guard_support import effect_identity

from zebra_agent_worker.cloud_effect_payloads import CloudEffectPayloadCoordinator
from zebra_agent_worker.coverage_effect_validation import (
    CREATE,
    create_arguments,
    create_call_id,
    frozen_manifest,
    validate_result,
)
from zebra_agent_worker.tool_output_artifacts import CloudToolOutputArtifactCoordinator


class CloudCoverageEffectInvoke:
    """Bind a signed Host gateway to one admitted Cloud Session and Task snapshot.

    check_authority must verify current external revocation, not just expiry.
    Event callbacks must use the existing durable recorder/authority lifecycle.
    No direct gateway or local payload coordinator can confer write admission.
    """

    def __init__(
        self,
        *,
        payloads: CloudEffectPayloadCoordinator,
        gateway: HostToolGateway,
        admission: CoverageTaskAdmission,
        binding: TaskBindingSnapshot,
        context: HostContextEnvelope,
        fence: LeaseFence,
        authority: Callable[[], WorkerMutationAuthority],
        policy: PolicyEnginePort,
        check_authority: Callable[[], None],
        next_event: Callable[[EventType, EventActor, dict[str, object]], SessionEvent],
        accept_event: Callable[[SessionEvent], object],
    ) -> None:
        if type(payloads) is not CloudEffectPayloadCoordinator:
            raise ValueError("coverage requires the Cloud Effect payload coordinator")
        if type(payloads._dispatch) is not PostgresEffectDispatchStore:
            raise ValueError("coverage requires PostgreSQL atomic Effect publication")
        assert isinstance(payloads._dispatch, PostgresEffectDispatchStore)
        self.dispatch = payloads._dispatch
        if type(payloads._artifacts) is not CloudToolOutputArtifactCoordinator:
            raise ValueError("coverage requires Cloud output artifacts")
        metadata = payloads._artifacts._metadata_store
        database = payloads._dispatch._database
        if (
            type(metadata) is not PostgresCloudArtifactPayloadStore
            or metadata._database._dsn != database._dsn
            or metadata._database.deployment_namespace != database.deployment_namespace
            or payloads._session_id != payloads._artifacts._session_id
        ):
            raise ValueError("coverage Effect stores must bind the same Cloud deployment/Session")
        if type(gateway) is not HostToolGateway or not gateway.shared_secret:
            raise ValueError("coverage requires the actual signed Host gateway")
        self.payloads, self.gateway, self.database = payloads, gateway, database
        self.artifacts, self.metadata = payloads._artifacts, metadata
        self.context = HostContextEnvelope.model_validate(
            effect_input(context), strict=True, extra="forbid"
        )
        self.admission = CoverageTaskAdmission.model_validate(
            effect_input(admission), strict=True, extra="forbid"
        )
        self.binding = TaskBindingSnapshot.model_validate(
            effect_input(binding), strict=True, extra="forbid"
        )
        self.fence = LeaseFence.model_validate(effect_input(fence), strict=True, extra="forbid")
        if gateway.manifest is None:
            raise ValueError("coverage requires a preconfigured frozen Host manifest")
        self.manifest = frozen_manifest(gateway.manifest, self.admission.contract)
        self.endpoint, self.workload = gateway.endpoint, gateway.workload_identity
        self.secret, self.transport = gateway.shared_secret, gateway.transport
        self.session = payloads._session_id
        self.authority, self.policy, self.check_authority = authority, policy, check_authority
        self.next_event, self.accept_event = next_event, accept_event
        self.resource = self.admission.source_resource
        self._preflight()

    def _preflight(self, call: ToolCall | None = None) -> WorkerMutationAuthority:
        self.check_authority()
        current = WorkerMutationAuthority.model_validate(
            effect_input(self.authority()), strict=True, extra="forbid"
        )
        if (
            current.deployment_namespace != self.database.deployment_namespace
            or current.session_id != self.session
            or current.lease_fence != self.fence
            or self.payloads._session_id != self.session
            or self.payloads._dispatch is not self.dispatch
            or self.payloads._artifacts is not self.artifacts
            or self.artifacts._session_id != self.session
            or self.artifacts._metadata_store is not self.metadata
            or self.metadata._database._dsn != self.database._dsn
            or self.metadata._database.deployment_namespace != self.database.deployment_namespace
            or self.gateway.endpoint != self.endpoint
            or self.gateway.workload_identity != self.workload
            or self.gateway.shared_secret != self.secret
            or self.gateway.transport is not self.transport
            or self.gateway.manifest is None
            or frozen_manifest(self.gateway.manifest, self.admission.contract) != self.manifest
            or self.manifest.workload_identity != self.workload.subject
        ):
            raise ValueError("coverage current Cloud/Host authority conflicts")
        self.workload.assert_matches(self.context)
        now = datetime.now(UTC)
        validate_coverage_admission(self.admission, host_context=self.context, now=now)
        tool = self.manifest.get(CREATE)
        assert tool is not None
        if not set(tool.scopes).issubset(self.context.scopes):
            raise ValueError("coverage write scopes are not granted")
        # ponytail: O(Session events) memory/I/O on every check; no scale claim.
        # Replace with an indexed authoritative admission/STOP read for large histories.
        history = PostgresEventStore(
            self.database._dsn, deployment_namespace=self.database.deployment_namespace
        ).list_for_session(self.session)
        prepared = [event for event in history if event.event_type is EventType.TASK_PREPARED]
        if not prepared or any(
            coverage_digest(event.payload.get("coverage_admission"))
            != coverage_digest(self.admission.model_dump(mode="json"))
            or coverage_digest(event.payload.get("host_context"))
            != coverage_digest(self.context.model_dump(mode="json"))
            for event in prepared
        ):
            raise ValueError("coverage requires the full persisted strict admission")
        if any(
            event.event_type
            in {EventType.SESSION_CANCELLED, EventType.SESSION_FAILED, EventType.SESSION_COMPLETED}
            or (
                event.event_type is EventType.SESSION_COMMAND_ACCEPTED
                and event.payload.get("kind") in {"stop", "cancel"}
            )
            for event in history
        ):
            raise ValueError("coverage Session has STOP/cancel or is terminal")
        with self.database.connect() as connection:
            assert_current_lease_fence(
                connection, self.database.deployment_namespace, self.session, self.fence
            )
            row = connection.execute(
                """SELECT task.active_segment_id, binding.snapshot_json, stream.current_version,
                  session.namespace_id
                FROM agent_tasks task JOIN LATERAL (
                  SELECT snapshot_json FROM task_binding_snapshots
                  WHERE deployment_namespace=task.deployment_namespace AND task_id=task.task_id
                  ORDER BY binding_revision DESC LIMIT 1) binding ON TRUE
                JOIN session_streams stream ON stream.deployment_namespace=task.deployment_namespace
                  AND stream.session_id=%s
                JOIN session_projections session
                  ON session.deployment_namespace=stream.deployment_namespace
                  AND session.session_id=stream.session_id
                WHERE task.deployment_namespace=%s AND task.task_id=%s""",
                (self.session, self.database.deployment_namespace, self.binding.task_id),
            ).fetchone()
        if (
            row is None
            or row["active_segment_id"] != self.session
            or row["namespace_id"] != self.context.namespace_id
            or coverage_digest(row["snapshot_json"])
            != coverage_digest(self.binding.model_dump(mode="json"))
            or row["current_version"] != current.expected_stream_revision
            or not history
            or history[-1].sequence != current.expected_stream_revision
        ):
            raise ValueError("coverage persisted Task binding/segment or revision conflicts")
        host = self.binding.host_capability
        if (
            host.host_context != self.context
            or host.grant_digest != host_context_digest(self.context)
            or host.manifest_digest != self.manifest.digest
            or host.namespace_id != self.context.namespace_id
            or host.host_app_id != self.context.host_app_id
            or host.grant_expires_at != self.context.expires_at
            or host.bound_at > now
            or self.binding.bound_at > now
        ):
            raise ValueError("coverage frozen Host binding conflicts")
        if call is not None:
            decision = PolicyDecision.model_validate(
                effect_input(self.policy.evaluate_tool_call(call)), strict=True, extra="forbid"
            )
            if decision.decision is not PolicyDecisionType.ALLOW:
                raise ValueError("coverage create requires current policy ALLOW")
        return current

    def __call__(
        self,
        tool_call: ToolCall,
        context: HostContextEnvelope,
        *,
        idempotency_key: str | None = None,
        required_resource: HostResourceRef | None = None,
        manifest: HostToolManifest | None = None,
    ) -> ToolResult:
        self._preflight()
        call = ToolCall.model_validate(effect_input(tool_call), strict=True, extra="forbid")
        bound_context = HostContextEnvelope.model_validate(
            effect_input(context), strict=True, extra="forbid"
        )
        resource = HostResourceRef.model_validate(
            effect_input(required_resource), strict=True, extra="forbid"
        )
        arguments = create_arguments(self.admission)
        if (
            type(idempotency_key) is not str
            or not idempotency_key.strip()
            or len(idempotency_key) > 512
            or bound_context != self.context
            or resource != self.resource
            or manifest is None
            or frozen_manifest(manifest, self.admission.contract) != self.manifest
            or call.name != CREATE
            or coverage_digest(call.arguments) != coverage_digest(arguments)
            or call.provider_call_id is not None
            or call.provider_tool_name is not None
            or call.provider_arguments is not None
            or call.tool_call_id
            != create_call_id(
                idempotency_key, self.context, self.manifest, arguments, self.resource
            )
        ):
            raise ValueError("coverage invocation context/resource/manifest/key/identity conflicts")
        scope = "cloud-coverage-create/1:" + coverage_digest(
            {
                "admission": self.admission.model_dump(mode="json"),
                "binding": self.binding.model_dump(mode="json"),
                "context": self.context.model_dump(mode="json"),
                "manifest": self.manifest.to_payload(),
                "deployment": self.database.deployment_namespace,
                "session": str(self.session),
                "endpoint": self.endpoint,
                "workload": self.workload.subject,
                "key": idempotency_key,
                "arguments": arguments,
                "resource": self.resource.model_dump(mode="json"),
            }
        )
        self._preflight(call)

        def ownership_check() -> None:
            self._preflight(call)

        fenced = FencedEffectToolGateway(
            _BoundCreate(self, call, idempotency_key),
            dispatch=self.dispatch,
            artifacts=None,
            execution_session_id=self.session,
            root_session_id=self.session,
            fence=self.fence,
            claim_ttl=timedelta(seconds=30),
            authority_scope=scope,
            next_event=self.next_event,
            accept_event=self.accept_event,
            ownership_check=ownership_check,
            effect_payloads=self.payloads,
            mutation_authority=lambda: self._preflight(call),
        )
        result = fenced.execute_exact(call)
        self._preflight(call)
        result = validate_result(result, call, self.admission, self.context, self.manifest)
        # The inline ledger result is not the original output evidence. Require
        # finalized, terminal-Event-bound bytes from the immutable object version.
        uri = result.metadata.get("artifact_uri")
        if not isinstance(uri, str):
            raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)
        artifact_id = artifact_id_from_uri(uri)
        if artifact_id is None or uri != f"artifact://{artifact_id}":
            raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)
        durable = self.dispatch.find_by_ledger_key(
            self.session, identity=effect_identity(call, scope)
        )
        reader = CloudArtifactPayloadReader(
            self.metadata,
            self.artifacts._object_store,
            deployment_namespace=self.database.deployment_namespace,
        )
        record = self.metadata.get_metadata(
            ArtifactMetadataQuery(
                deployment_namespace=self.database.deployment_namespace,
                artifact_id=artifact_id,
                session_id=self.session,
            )
        )
        if (
            durable is None
            or durable.result != result
            or record is None
            or record.lifecycle_status is not CloudArtifactPayloadLifecycleStatus.FINALIZED
            or record.reservation.kind != "tool_output"
            or record.event_binding is None
            or record.event_binding.event_id != durable.terminal_event_id
        ):
            raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)
        try:
            original = reader.read_payload_bytes(self.session, uri)
        except (
            FileNotFoundError,
            ValueError,
            ArtifactObjectIntegrityError,
            ArtifactObjectUnavailableError,
            ArtifactPayloadReadUnavailableError,
        ) as exc:
            raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE) from exc
        if (
            original != result.output.encode()
            or result.metadata.get("output_sha256") != sha256(original).hexdigest()
            or type(result.metadata.get("output_size_bytes")) is not int
            or result.metadata["output_size_bytes"] != len(original)
        ):
            raise CoverageRefusedError(Reason.ARTIFACT_UNAVAILABLE)
        self._preflight(call)
        return result


class _BoundCreate:
    read_only_tools: frozenset[str] = frozenset()
    model_tools: tuple[ModelToolDefinition, ...] = ()
    effective_mcp_tools: tuple[ModelToolDefinition, ...] = ()
    effective_skill_components: tuple[str, ...] = ()
    parallel_safe_tools: frozenset[str] = frozenset()
    parallel_batch_limits: dict[str, int] = {}

    def __init__(self, owner: CloudCoverageEffectInvoke, call: ToolCall, key: str) -> None:
        self.owner, self.call, self.key = owner, call, key

    def resolve_model_tool_calls(self, calls: tuple[ToolCall, ...]) -> tuple[ToolCall, ...]:
        raise ValueError("coverage callback is not a model tool gateway")

    def close(self) -> None:
        pass  # The composition owner owns the shared signed transport.

    def execute(self, call: ToolCall) -> ToolResult:
        owner = self.owner
        owner._preflight(self.call)
        if call.tool_call_id != self.call.tool_call_id or call.arguments != self.call.arguments:
            raise ValueError("coverage exact transport request conflicts")
        result = owner.gateway.invoke(
            call,
            owner.context,
            idempotency_key=self.key,
            required_resource=owner.resource,
            manifest=owner.manifest,
        )
        result = ToolResult.model_validate(effect_input(result), strict=True, extra="forbid")
        if result.tool_call_id != call.tool_call_id:
            raise ValueError("coverage Host result identity conflicts")
        projected = owner.payloads._artifacts.output_projector.project_text(
            result.output,
            artifact_name="coverage-snapshot-create.json",
            content_type="application/json",
        )
        # Keep original descriptor bytes; the projector's preview is not replay evidence.
        return result.model_copy(update={"metadata": {**result.metadata, **projected.metadata}})
