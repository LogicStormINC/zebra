"""Source-owned pure preparation; each real I/O/mutation still owns its fresh guard."""

from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime
from types import CodeType, FunctionType, MethodType
from typing import Any, cast

from agent_core.domain.artifact_objects import (
    ArtifactObjectExpectation,
    ArtifactObjectVerificationStatus,
)
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.coverage_contracts import (
    CoverageRefusalReason,
    CoverageRefusedError,
    coverage_digest,
)
from agent_core.domain.coverage_execution import PublishedCoverageCheck
from agent_core.domain.coverage_model_budget import (
    CoverageModelPolicy,
    CoverageModelReservation,
    CoverageModelUsageReceipt,
)
from agent_core.domain.coverage_model_checkpoint import (
    MAX_MODEL_CHECKPOINT_BYTES,
    MODEL_CHECKPOINT_KIND,
    completion_usage,
    decode_model_checkpoint,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_task_admission import coverage_admission_input
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.leases import LeaseFence
from agent_integrations import ModelProviderSettings, build_model_gateway
from agent_integrations.coverage_model import SemanticCoverageModel
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_integrations.coverage_model_invocation import CoverageModelInvocation, _utc_now
from agent_integrations.coverage_snapshot_artifacts import CoverageArtifacts
from agent_integrations.openai_compatible import OpenAICompatibleModelGateway
from agent_storage.postgres.artifact_payloads import PostgresCloudArtifactPayloadStore
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_artifact_publication import PostgresCoverageArtifactPublisher
from agent_storage.postgres.coverage_authority import PostgresCoverageAuthority
from agent_storage.postgres.coverage_evidence_operation import PostgresCoverageEvidenceOperation
from agent_storage.postgres.coverage_evidence_selection import CoverageEvidenceUnavailable

from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts
from zebra_agent_worker.coverage_native_publication import NativeCoverageArtifacts


def _methods(kind: type[Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: getattr(kind, name) for name in names}


_INVOCATION = _methods(CoverageModelInvocation, (
    "__call__", "_boundary", "_fence", "_time", "_required", "_load",
))
_ARTIFACTS = _methods(CoverageArtifacts, (
    "load", "load_payload", "_load_payload", "publish", "_publish",
))
_NATIVE_ARTIFACTS = _methods(NativeCoverageArtifacts, tuple(_ARTIFACTS))
_CLOUD = _methods(CloudCoverageArtifacts, (
    "_record", "read_payload_scope", "read_payload_verified_bounded",
    "_read_payload_bytes_for_record", "store_payload_immutable", "_locked_proof_scope",
    "get_payload", "inspect_payload", "_stored", "_remember_publication", "_remember_verified",
))
_STORE = _methods(PostgresCoverageStore, (
    "reserve_model_call", "_model_boundary", "_model_clock", "_model_artifact_scope",
    "record_model_usage", "settle_model_checkpoint", "_settle_model_checkpoint",
))
_PUBLISHER = _methods(PostgresCoverageArtifactPublisher, (
    "publish", "publish_batch", "_record_receipts", "_revalidate_finalized",
    "_prepare_publication", "_upload_verified", "_finalize_locked",
))
_EVIDENCE = _methods(PostgresCoverageEvidenceOperation, (
    "_qualify", "_qualify_guards", "publish_model_checkpoint", "commit_evidence", "_execute",
    "_prefetch_existing", "_settlement_facts",
))
_BUILD_GATEWAY = build_model_gateway
_METADATA = _methods(PostgresCloudArtifactPayloadStore, ("get_metadata",))
_AUTHORITY = _methods(PostgresCoverageAuthority, (
    "check", "observe", "observe_payloads", "_read_lineage", "_validate_lineage",
))
_SEMANTIC = _methods(SemanticCoverageModel, ("__init__", "__call__"))


def _unmodified(value: Any, kind: type[Any], methods: dict[str, Any]) -> bool:
    return type(value) is kind and all(
        name not in vars(value) and getattr(type(value), name) is method
        for name, method in methods.items()
    )


def _fingerprint(value: Any) -> str:
    if type(value) not in {CoverageRunBinding, CoverageModelPolicy}:
        raise CoverageRefusedError(CoverageRefusalReason.UNSUPPORTED)
    validated = type(value).model_validate(coverage_admission_input(value), strict=True)
    return coverage_digest(validated.model_dump(mode="json"))


def _worker_guard(value: Any, name: str) -> bool:
    from zebra_agent_worker.coverage_dispatch import execute_cloud_coverage

    codes = {constant for constant in execute_cloud_coverage.__code__.co_consts
             if type(constant) is CodeType and constant.co_name == name}
    return (
        type(value) is FunctionType and value.__code__ in codes
        and value.__globals__ is execute_cloud_coverage.__globals__
        and value.__defaults__ is None and value.__kwdefaults__ is None and not vars(value)
    )


def _closure(value: Any) -> dict[str, Any]:
    if type(value) is not FunctionType:
        return {}
    try:
        return dict(zip(value.__code__.co_freevars,
                        (cell.cell_contents for cell in value.__closure__ or ()), strict=True))
    except ValueError:
        return {}


def qualified_final_reads(source: CloudCoverageArtifacts) -> bool:
    """A locked pure proof owns bytes; it never inherits execution permission."""
    check, local, external = (
        source.check_authority, source.check_local_authority, source.check_external_authority,
    )
    if not (_unmodified(source, CloudCoverageArtifacts, _CLOUD)
            and _worker_guard(check, "check") and _worker_guard(local, "check_local")
            and _worker_guard(external, "check_external")):
        return False
    callbacks = _closure(check)
    native = _closure(local).get("check_local_native")
    authority = _closure(native).get("execution_authority")
    if not _unmodified(authority, PostgresCoverageAuthority, _AUTHORITY):
        return False
    authority = cast(PostgresCoverageAuthority, authority)
    return (
        callbacks.get("check_local") is local and callbacks.get("check_external") is external
        and _worker_guard(native, "check_local_native")
        and _worker_guard(_closure(native).get("validate_local_entry"), "validate_local_entry")
        and authority.database is source.metadata._database
        and authority.session == source.binding.session_id
        and authority.database.deployment_namespace == source.deployment
        and _unmodified(source.metadata, PostgresCloudArtifactPayloadStore, _METADATA)
        and _unmodified(source.publisher, PostgresCoverageArtifactPublisher, _PUBLISHER)
        and source.publisher._metadata is source.metadata
        and source.publisher._objects is source.objects
        and source.publisher._deployment == source.deployment
        and source.publisher._database.deployment_namespace == source.deployment
        and source.publisher._database._dsn == source.metadata._database._dsn
    )


def qualified_checkpoint_publication(
    artifacts: NativeCoverageArtifacts, validate: Any,
) -> bool:
    if type(validate) is not MethodType:
        return False
    invoke = validate.__self__
    source = cast(CloudCoverageArtifacts, artifacts.store)
    return (
        type(invoke) is NativeCoverageModelInvocation
        and validate.__func__ in {_OWNED["_preparation_boundary"], _INVOCATION["_boundary"]}
        and invoke.artifacts is artifacts
        and _unmodified(artifacts, NativeCoverageArtifacts, _NATIVE_ARTIFACTS)
        and _OWNED["_qualified_preparation"](invoke)
        and qualified_final_reads(source)
        and source.sync_events is source.check_local_authority
    )


def owned_evidence_operation(
    invocation: "NativeCoverageModelInvocation",
) -> PostgresCoverageEvidenceOperation | None:
    if not _OWNED["_qualified_preparation"](invocation):
        return None
    operation = invocation._evidence_operation
    source = cast(CloudCoverageArtifacts, invocation.artifacts.store)
    if not _unmodified(operation, PostgresCoverageEvidenceOperation, _EVIDENCE):
        return None
    operation = cast(PostgresCoverageEvidenceOperation, operation)
    if (operation is not invocation._evidence_owner
            or operation.store is not invocation.store
            or operation.publisher is not source.publisher
            or operation.authority is not source.authority
            or operation.check_authority is not invocation.check_authority):
        return None
    operation._qualify(invocation.binding)
    return operation


class NativeCoverageModelInvocation(CoverageModelInvocation):
    def __init__(
        self, *, fence: LeaseFence, settings: ModelProviderSettings,
        check_authority: Callable[[], None],
        evidence_operation: PostgresCoverageEvidenceOperation | None = None, **kwargs: Any,
    ) -> None:
        self._owned_fence = LeaseFence.model_validate(coverage_admission_input(fence), strict=True)
        self._settings = settings
        self._authority_owner = check_authority
        self._evidence_operation = self._evidence_owner = evidence_operation
        super().__init__(
            **kwargs, fresh_fence=self._copy_fence, gateway_factory=self._gateway,
            check_authority=check_authority,
        )
        self._original_binding = _fingerprint(self.binding)
        self._original_policy = _fingerprint(self.policy)
        source = self.artifacts.store
        self._local_owner = getattr(source, "check_local_authority", None)
        self._external_owner = getattr(source, "check_external_authority", None)

    def _copy_fence(self) -> LeaseFence:
        return LeaseFence.model_validate(coverage_admission_input(self._owned_fence), strict=True)

    def _gateway(self) -> OpenAICompatibleModelGateway:
        result = build_model_gateway(self._settings)
        if type(result) is not OpenAICompatibleModelGateway:
            raise ValueError("native MODEL requires the configured builtin gateway")
        return result

    def _qualified_preparation(self) -> bool:
        # No user flag, TTL, cached permission or memoized budget authorizes this
        # path. It qualifies only pure native helpers. Altered delegates fall back
        # to the original guard; their actual callbacks cannot inherit a shortcut.
        if (
            type(self) is not NativeCoverageModelInvocation
            or not self._defer_boundary_proof
            or self.now is not _utc_now
            or self.check_authority is not self._authority_owner
            or not _worker_guard(self.check_authority, "check")
            or self.fresh_fence != self._copy_fence
            or self.gateway_factory != self._gateway
            or build_model_gateway is not _BUILD_GATEWAY
            or type(self._settings) is not ModelProviderSettings
            or self._settings.max_retries != 0
            or any(name in vars(self) or getattr(type(self), name) is not method
                   for name, method in _INVOCATION.items())
            or any(getattr(type(self), name) is not method or name in vars(self)
                   for name, method in _OWNED.items())
            or _fingerprint(self.binding) != self._original_binding
            or _fingerprint(self.policy) != self._original_policy
            or not (_unmodified(self.artifacts, CoverageArtifacts, _ARTIFACTS)
                    or _unmodified(self.artifacts, NativeCoverageArtifacts, _NATIVE_ARTIFACTS))
            or type(self.artifacts.publication_lock) is not nullcontext
            or not _unmodified(self.store, PostgresCoverageStore, _STORE)
        ):
            return False
        source = self.artifacts.store
        store = cast(PostgresCoverageStore, self.store)
        return (
            _unmodified(source, CloudCoverageArtifacts, _CLOUD)
            and qualified_final_reads(cast(CloudCoverageArtifacts, source))
            and source is store._artifacts
            and source.binding == self.binding
            and source.deployment == store._deployment
            and source.check_authority is self.check_authority
            and source.check_local_authority is self._local_owner
            and source.check_external_authority is self._external_owner
            and _worker_guard(self._local_owner, "check_local")
            and _worker_guard(self._external_owner, "check_external")
            and store._model_observation_deriver is derive_semantic_observation
            and _unmodified(source.publisher, PostgresCoverageArtifactPublisher, _PUBLISHER)
            and _unmodified(source.metadata, PostgresCloudArtifactPayloadStore, _METADATA)
            and source.metadata is source.publisher._metadata
            and source.objects is source.publisher._objects
            and source.metadata._database._dsn == store._database._dsn
            and source.metadata._database.deployment_namespace == source.deployment
            and source.publisher._database._dsn == store._database._dsn
            and source.publisher._database.deployment_namespace == source.deployment
            and source.publisher._deployment == source.deployment
        )

    def _preparation_boundary(self) -> datetime:
        if _OWNED["_qualified_preparation"](self):
            return self._time()
        return super()._preparation_boundary()

    def _mutation_fence(self) -> LeaseFence:
        if _OWNED["_qualified_preparation"](self):
            self._time()
            return self._copy_fence()
        return super()._mutation_fence()

    def _publish_checkpoint(self, identifier: Any, body: bytes) -> bool:
        operation = owned_evidence_operation(self)
        if operation is None:
            return super()._publish_checkpoint(identifier, body)
        checkpoint = decode_model_checkpoint(body)
        if checkpoint.binding != self.binding or checkpoint.artifact_id != identifier:
            raise ValueError("native evidence changed the original checkpoint identity")
        counts = completion_usage(checkpoint.completion, checkpoint.reservation)
        receipt = CoverageModelUsageReceipt(
            reservation=checkpoint.reservation, input_tokens=counts[0], output_tokens=counts[1],
            total_tokens=counts[2], checkpoint_ref=f"artifact://{identifier}",
            checkpoint_digest=checkpoint.digest,
        )
        try:
            sequence, verified = operation.publish_model_checkpoint(
                self.binding, receipt, ArtifactPayloadWrite(
                    session_id=self.binding.session_id, kind=MODEL_CHECKPOINT_KIND,
                    mime_type="application/json", payload=body, created_at=self._time(),
                    retained_until=self.binding.snapshot.expires_at,
                ), fence=self._mutation_fence(),
            )
        except CoverageEvidenceUnavailable:
            return super()._publish_checkpoint(identifier, body)
        if (type(sequence) is not int or sequence < 1
                or type(verified) is not bytes or verified != body):
            raise ValueError("native evidence checkpoint acknowledgement conflicts")
        return True

    def _recover_checkpoint(
        self, identifier: ArtifactId, reservation: CoverageModelReservation,
    ) -> bytes | None:
        if owned_evidence_operation(self) is None:
            return None
        source = cast(CloudCoverageArtifacts, self.artifacts.store)
        record = source._record(identifier)
        if record is None or record.lifecycle_status != "staged":
            return None
        stored = record.reservation
        identity = coverage_digest(self.binding.model_dump(mode="json"))
        if (stored.idempotency_key != f"coverage:{identity}:{identifier}"
                or stored.kind != MODEL_CHECKPOINT_KIND or stored.mime_type != "application/json"
                or stored.size_bytes > MAX_MODEL_CHECKPOINT_BYTES):
            raise ValueError("staged checkpoint does not bind the exact native run")
        expectation = ArtifactObjectExpectation(
            deployment_namespace=source.deployment, artifact_id=identifier,
            sha256=stored.sha256, size_bytes=stored.size_bytes,
        )
        self._boundary()
        verification = source.objects.verify(expectation)
        self._boundary()
        if verification.status is ArtifactObjectVerificationStatus.NOT_FOUND:
            return None  # Never authorize a second MODEL request for lost response bytes.
        if (verification.status is not ArtifactObjectVerificationStatus.VERIFIED
                or verification.receipt is None):
            raise ValueError("staged checkpoint object conflicts with immutable metadata")
        body = source.objects.read_version_verified(
            expectation, verification.receipt.object_version,
        )
        self._boundary()
        if source._record(identifier) != record:
            raise ValueError("staged checkpoint changed during recovery")
        checkpoint = decode_model_checkpoint(body)
        if (checkpoint.binding != self.binding or checkpoint.reservation != reservation
                or checkpoint.artifact_id != identifier or checkpoint.canonical_bytes != body
                or checkpoint.digest != stored.sha256 or len(body) != stored.size_bytes):
            raise ValueError("recovered checkpoint conflicts with original request")
        return body


_OWNED = _methods(NativeCoverageModelInvocation, (
    "_copy_fence", "_gateway", "_qualified_preparation", "_preparation_boundary", "_mutation_fence",
    "_publish_checkpoint", "_recover_checkpoint",
))


class NativeSemanticCoverageModel(SemanticCoverageModel):
    """Pure outer formatting delegates I/O ownership to the exact native invocation."""

    def _authorize(self) -> None:
        invoke = self._invoke_or_replay
        if (
            type(self) is NativeSemanticCoverageModel
            and type(invoke) is NativeCoverageModelInvocation
            and self._check_authority is invoke.check_authority
            and self._gateway is None
            and self._reserve_call is None
            and self._record_response is None
            and type(self._definition) is type(invoke.definition) is PublishedCoverageCheck
            and self._definition == invoke.definition
            and "_authorize" not in vars(self)
            and type(self)._authorize is _NATIVE_SEMANTIC_AUTHORIZATION
            and all(name not in vars(self) and getattr(type(self), name) is method
                    for name, method in _SEMANTIC.items())
            and _OWNED["_qualified_preparation"](invoke)
        ):
            invoke._time()
            return
        super()._authorize()


_NATIVE_SEMANTIC_AUTHORIZATION = NativeSemanticCoverageModel._authorize
