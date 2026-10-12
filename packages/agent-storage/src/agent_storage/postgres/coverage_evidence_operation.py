"""Native two-phase evidence publication and settlement; acknowledgement follows owner commit."""

from collections.abc import Callable
from hashlib import sha256
from types import CodeType, FunctionType
from typing import Any, cast

from agent_core.application.coverage_executor import observation_id
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.cloud_artifact_payloads import CloudArtifactPayloadRecord
from agent_core.domain.coverage_model_budget import CoverageModelUsageReceipt
from agent_core.domain.coverage_model_checkpoint import (
    MODEL_CHECKPOINT_KIND,
    decode_model_checkpoint,
    model_checkpoint_id,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_task_admission import coverage_admission_input
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.leases import LeaseFence
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from agent_core.ports.coverage import CoverageCommit, CoverageCommitReceipt

from agent_storage.postgres.artifact_payloads import PostgresCloudArtifactPayloadStore
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_artifact_publication import PostgresCoverageArtifactPublisher
from agent_storage.postgres.coverage_artifact_reservations import reserve_batch
from agent_storage.postgres.coverage_artifacts import MAX_COVERAGE_ARTIFACT_BYTES, _identity
from agent_storage.postgres.coverage_authority import PostgresCoverageAuthority
from agent_storage.postgres.coverage_evidence_reads import EvidenceOperationReads
from agent_storage.postgres.coverage_evidence_selection import (
    CoverageEvidenceUnavailable,
    acceptance_evidence_ids,
)
from agent_storage.postgres.coverage_membership import membership_state
from agent_storage.postgres.coverage_model_index import indexed_state
from agent_storage.postgres.coverage_model_source import task_policy
from agent_storage.postgres.coverage_model_volume_summary import volume_summary
from agent_storage.postgres.coverage_transactions import (
    lock_run,
    validate_request,
    validate_write,
    validated_binding,
)
from agent_storage.postgres.work_unit import borrow_work_unit, postgres_transaction_work_unit


class PostgresCoverageEvidenceOperation:
    def __init__(
        self, store: PostgresCoverageStore, publisher: PostgresCoverageArtifactPublisher,
        authority: Callable[[], WorkerMutationAuthority], check_authority: Callable[[], None],
        *, check_local_authority: Callable[[], None] | None = None,
    ) -> None:
        self.store, self.publisher = store, publisher
        self.authority, self.check_authority = authority, check_authority
        self.check_local_authority = check_local_authority
        self._guard_owners = (authority, check_authority, check_local_authority,
                              getattr(store._artifacts, "check_external_authority", None))
        self._native_local = _cells(check_local_authority).get("check_local_native")
        self._native_cells = _cells(self._native_local)
        self._authority_cells = _cells(authority)
        self._derive = store._model_observation_deriver
        self._source_methods: dict[str, Any] | None = None

    def _qualify_guards(self, source: Any, binding: CoverageRunBinding) -> None:
        local, external = self.check_local_authority, source.check_external_authority
        if (any(actual is not original for actual, original in zip(
                (self.authority, self.check_authority, local, external), self._guard_owners,
                strict=True)) or source.check_local_authority is not local):
            raise ValueError("native evidence captured authority callbacks changed")
        if local is None and external is None:
            # Direct DB fixtures have no Host split. Keep every foreign callback
            # and the full post-callback proof; they cannot inherit the shortcut.
            return
        entry = getattr(self.check_authority, "__globals__", {}).get("execute_cloud_coverage")

        def native(value: Any, name: str, parent: Any = entry) -> bool:
            return (type(parent) is FunctionType
                    and parent.__module__ in {"zebra_agent_worker.coverage_dispatch",
                                             "zebra_agent_worker.coverage_bootstrap"}
                    and type(value) is FunctionType and value.__globals__ is parent.__globals__
                    and value.__code__ in {code for code in parent.__code__.co_consts
                                          if type(code) is CodeType and code.co_name == name}
                    and value.__defaults__ is None and value.__kwdefaults__ is None
                    and not vars(value))

        wrapper = _cells(self.authority)
        dispatch_authority = self.authority
        if "authority" in wrapper:
            bootstrap = getattr(self.authority, "__globals__", {}).get("bootstrap_cloud_coverage")
            if (not native(self.authority, "fresh_authority", bootstrap)
                    or any(wrapper.get(name) is not self._authority_cells.get(name)
                           for name in ("authority", "check_authority"))
                    or wrapper.get("check_authority") is not self.check_authority
                    or wrapper.get("deployment_namespace") != self.store._deployment
                    or wrapper.get("session_id") != binding.session_id):
                raise ValueError("native evidence bootstrap authority callbacks changed")
            dispatch_authority = wrapper["authority"]
        checks = _cells(self.check_authority)
        callback = _cells(local).get("check_local_native")
        captured = _cells(callback)
        authority = captured.get("execution_authority")
        if (not native(self.check_authority, "check") or not native(local, "check_local")
                or not native(external, "check_external")
                or not native(dispatch_authority, "authority")
                or not native(callback, "check_local_native")
                or callback is not self._native_local
                or any(captured.get(name) is not self._native_cells.get(name) for name in (
                    "execution_authority", "ownership_check", "validate_local_entry"))
                or not native(captured.get("validate_local_entry"), "validate_local_entry")
                or checks.get("check_local") is not local
                or checks.get("check_external") is not external
                or _cells(dispatch_authority).get("check_local_native") is not callback
                or type(authority) is not PostgresCoverageAuthority
                or any(name in vars(authority) or getattr(type(authority), name) is not method
                       for name, method in _AUTHORITY_METHODS.items())
                or authority.database is not source.metadata._database
                or authority.database.deployment_namespace != self.store._deployment
                or authority.session != binding.session_id
                or authority.fence != getattr(
                    _cells(dispatch_authority).get("lease"), "fence", None)
                or ("authority" in wrapper and wrapper.get("fence") != authority.fence)
                or str(authority.binding.task_id) != str(binding.task_id)):
            raise ValueError("native evidence requires exact separated Worker authority guards")

    def _qualify(self, binding: CoverageRunBinding) -> Any:
        store, publisher, source = self.store, self.publisher, self.store._artifacts
        if (type(store) is not PostgresCoverageStore
                or type(publisher) is not PostgresCoverageArtifactPublisher
                or type(publisher._metadata) is not PostgresCloudArtifactPayloadStore
                or any(name in vars(store) or getattr(type(store), name) is not method
                       for name, method in _STORE_METHODS.items())
                or any(name in vars(publisher) or getattr(type(publisher), name) is not method
                       for name, method in _PUBLISHER_METHODS.items())
                or acceptance_evidence_ids is not _READ_SELECTOR
                or EvidenceOperationReads is not _READ_OWNER
                or any(getattr(EvidenceOperationReads, name) is not method
                       for name, method in _READ_METHODS.items())):
            raise ValueError("altered evidence delegates require the guarded public operation")
        key = (store._database._dsn, store._deployment)
        if (key != (publisher._database._dsn, publisher._deployment)
                or key != (publisher._metadata._database._dsn,
                           publisher._metadata._database.deployment_namespace)
                or publisher._database.deployment_namespace != store._deployment
                or store._database.deployment_namespace != store._deployment
                or getattr(source, "binding", None) != binding
                or getattr(source, "deployment", None) != store._deployment
                or getattr(source, "publisher", None) is not publisher
                or getattr(source, "metadata", None) is not publisher._metadata
                or getattr(source, "objects", None) is not publisher._objects
                or getattr(source, "authority", None) is not self.authority
                or getattr(source, "check_authority", None) is not self.check_authority):
            raise ValueError("native evidence source/database/namespace ownership conflicts")
        scope = getattr(source, "_locked_proof_scope", None)
        # The actual source-owned implementation qualifies its pure deriver.
        # Structural protocol implementations and named callbacks cannot mint proof.
        function = getattr(getattr(scope, "__func__", None), "__wrapped__", None)
        origin = getattr(function, "__globals__", {})
        native = origin.get("CloudCoverageArtifacts")
        derive = self.store._model_observation_deriver
        if (native is None or type(source) is not native
                or native.__module__ != "zebra_agent_worker.coverage_artifacts"
                or "_locked_proof_scope" in vars(source)
                or "_execution_receipt_verifier" in vars(source)
                or derive is not self._derive or type(derive) is not FunctionType
                or derive.__module__ != "agent_integrations.coverage_model_derivation"
                or derive.__globals__.get("derive_semantic_observation") is not derive):
            raise ValueError("native evidence requires source-owned pure proof qualification")
        names = ("_locked_proof_scope", "_execution_receipt_verifier", "read_payload_scope",
                 "_record", "_read_payload_bytes_for_record", "_remember_publication",
                 "_remember_verified", "_stored")
        if self._source_methods is None:
            self._source_methods = {name: getattr(native, name) for name in names}
        if any(name in vars(source) or getattr(type(source), name) is not method
               for name, method in self._source_methods.items()):
            raise ValueError("altered evidence source requires the guarded public operation")
        self._qualify_guards(source, binding)
        return source

    def publish_model_checkpoint(
        self, binding: CoverageRunBinding, receipt: CoverageModelUsageReceipt,
        payload: ArtifactPayloadWrite, *, fence: LeaseFence,
    ) -> tuple[int, bytes]:
        binding = validated_binding(binding)
        receipt = CoverageModelUsageReceipt.model_validate(coverage_admission_input(receipt))
        payload = ArtifactPayloadWrite.model_validate(payload.model_dump(), strict=True)
        if payload.kind != MODEL_CHECKPOINT_KIND or payload.mime_type != "application/json":
            raise ValueError("checkpoint kind/MIME conflicts with native evidence")
        checkpoint = decode_model_checkpoint(payload.payload)
        identifier = model_checkpoint_id(binding, receipt.reservation)
        checkpoint.validate_receipt(receipt)
        if checkpoint.binding != binding or checkpoint.canonical_bytes != payload.payload:
            raise ValueError("evidence checkpoint is not exact canonical run evidence")
        return cast(tuple[int, bytes], self._execute(
            binding, ((identifier, payload),), fence, receipt, None,
        ))

    def commit_evidence(
        self, binding: CoverageRunBinding, request: CoverageCommit,
        payloads: tuple[tuple[ArtifactId, ArtifactPayloadWrite], ...], *, fence: LeaseFence,
    ) -> CoverageCommitReceipt:
        binding = validated_binding(binding)
        request = CoverageCommit.model_validate(coverage_admission_input(request), strict=True)
        validate_request(binding, request)
        result_id = _identity(request.result_artifact_ref)
        if result_id not in {identifier for identifier, _ in payloads}:
            raise ValueError("evidence operation requires the exact result Artifact write")
        observations = {observation_id(binding, item.key) for item in request.results}
        for identifier, payload in payloads:
            kind = "coverage_results" if identifier == result_id else "coverage_observation"
            if (identifier not in observations | {result_id} or payload.kind != kind
                    or payload.mime_type != "application/octet-stream"):
                raise ValueError("acceptance evidence identity/kind/MIME conflicts")
        return cast(CoverageCommitReceipt, self._execute(binding, payloads, fence, None, request))

    def _prefetch_existing(
        self, binding: CoverageRunBinding, exclude: set[ArtifactId], remaining: int,
        selected: tuple[ArtifactId, ...],
    ) -> tuple[tuple[CloudArtifactPayloadRecord, bytes], ...]:
        # Usage proof consumes only its candidate checkpoint, already PUT/GET verified.
        if not selected:
            return ()
        self.check_authority()
        selected = tuple(identifier for identifier in selected if identifier not in exclude)
        if not selected:
            return ()
        source = self.store._artifacts
        verified = []
        # Native readonly preparation returns full records at both boundaries.
        # It may reuse bytes only on exact full-record equality. Every actual GET
        # still has fresh pre/post guards; this scope owns no mutation transaction.
        with source.read_payload_scope(selected) as prepared:
            for identifier in selected:
                record = prepared._record(identifier)
                if (record is None or record.lifecycle_status != "finalized"
                        or record.object_receipt is None):
                    raise ValueError("affected evidence is unavailable")
                if record.reservation.size_bytes > remaining:
                    raise ValueError("affected evidence exceeds bounded prefetch")
                body = prepared._read_payload_bytes_for_record(
                    identifier, record, max_bytes=remaining,
                )
                if (len(body) != record.reservation.size_bytes
                        or sha256(body).hexdigest() != record.reservation.sha256):
                    raise ValueError("affected evidence bytes conflict with full metadata")
                remaining -= len(body)
                verified.append((record, body))
        return tuple(verified)

    def _settlement_facts(
        self, connection: Any, binding: CoverageRunBinding, sequence: int,
        receipt: CoverageModelUsageReceipt | None, request: CoverageCommit | None,
    ) -> Any:
        return connection.execute(
            """SELECT to_jsonb(r) AS run,s.current_version,
               (SELECT to_jsonb(e) FROM session_events e
                 WHERE e.deployment_namespace=r.deployment_namespace
                 AND e.session_id=r.session_id AND e.sequence=%s) AS event,
               (SELECT to_jsonb(l) FROM coverage_model_ledger l
                 WHERE l.deployment_namespace=r.deployment_namespace
                 AND l.namespace=r.namespace AND l.run_id=r.run_id) AS ledger,
               (SELECT to_jsonb(c) FROM coverage_model_calls c
                 WHERE c.deployment_namespace=r.deployment_namespace
                   AND c.namespace=r.namespace AND c.run_id=r.run_id
                   AND c.reservation_key=%s) AS call,
               (SELECT jsonb_agg(to_jsonb(u) ORDER BY u.ordinal) FROM (
                 SELECT * FROM coverage_units u WHERE u.deployment_namespace=r.deployment_namespace
                   AND u.namespace=r.namespace AND u.run_id=r.run_id
                   AND u.unit_key->>'record_id'=ANY(%s) ORDER BY ordinal LIMIT 1001) u) AS units,
               (SELECT to_jsonb(m) FROM coverage_membership_seals m
                 WHERE m.deployment_namespace=r.deployment_namespace AND m.namespace=r.namespace
                   AND m.run_id=r.run_id) AS membership,
               (SELECT to_jsonb(m) FROM coverage_model_summary m
                 WHERE m.deployment_namespace=r.deployment_namespace AND m.namespace=r.namespace
                   AND m.run_id=r.run_id) AS model_summary,
               (SELECT to_jsonb(w) FROM coverage_execution_receipts w
                 WHERE w.deployment_namespace=r.deployment_namespace AND w.namespace=r.namespace
                   AND w.run_id=r.run_id AND w.sequence=%s) AS witness
               FROM coverage_runs r JOIN session_streams s
                 ON s.deployment_namespace=r.deployment_namespace
                 AND s.session_id=r.session_id WHERE r.deployment_namespace=%s
                 AND r.namespace=%s AND r.run_id=%s""",
            (sequence, receipt.reservation.reservation_key if receipt is not None else None,
             sorted({item.key.record_id for item in request.results}) if request else [],
             sequence, self.store._deployment, binding.namespace, binding.run_id),
        ).fetchone()

    def _execute(
        self, binding: CoverageRunBinding,
        payloads: tuple[tuple[ArtifactId, ArtifactPayloadWrite], ...], fence: LeaseFence,
        receipt: CoverageModelUsageReceipt | None, request: CoverageCommit | None,
    ) -> Any:
        source = self._qualify(binding)
        if borrow_work_unit((self.store._database._dsn, self.store._deployment)) is not None:
            raise ValueError("evidence acknowledgement requires its own completed transaction")
        fence = LeaseFence.model_validate(coverage_admission_input(fence), strict=True)
        self.check_authority()
        authority = WorkerMutationAuthority.model_validate(
            coverage_admission_input(self.authority()),
        )
        if authority.lease_fence != fence:
            raise ValueError("evidence operation fence conflicts with fresh authority")
        payloads = self.publisher._prepare_publication(binding, payloads, authority)
        database, deployment = self.store._database, self.store._deployment
        # Eligibility errors belong ONLY to this pre-I/O phase. Generic fallback
        # must never run after a durable reservation or a physical object write.
        with database.connect() as connection:
            validate_write(connection, deployment, binding, fence)
            policy = task_policy(connection, deployment, binding, incremental=True)
            if policy is None or policy.validation_mode != "final_certification":
                raise CoverageEvidenceUnavailable(
                    "bounded evidence requires native final_certification admission"
                )
            if (membership_state(connection, deployment, binding) is None
                    or volume_summary(connection, deployment, binding) is None):
                raise CoverageEvidenceUnavailable(
                    "legacy evidence prerequisites require the guarded public operation"
                )
            selected = (acceptance_evidence_ids(connection, deployment, binding, request)
                        if request is not None else ())
        # Durable before any PUT: a lost upload acknowledgement leaves only staged rows.
        with database.connect() as connection, postgres_transaction_work_unit(database, connection):
            validate_write(connection, deployment, binding, fence)
            records = reserve_batch(connection, deployment, binding, payloads, authority)
        receipts, bodies = self.publisher._upload_verified(
            binding, records, payloads, self.check_authority,
        )
        previous = self._prefetch_existing(
            binding, {record.artifact_id for record in records},
            MAX_COVERAGE_ARTIFACT_BYTES - sum(len(body) for body in bodies),
            selected,
        )
        self.check_authority()
        self._qualify(binding)
        with database.connect() as connection, postgres_transaction_work_unit(database, connection):
            row, version = lock_run(connection, deployment, binding, fence)
            guard = self.check_local_authority or self.check_authority
            if self.check_local_authority is not None:
                guard()  # Fresh locked SQL lineage/epoch/lease/STOP; no Host I/O.
            finalized, version = self.publisher._finalize_locked(
                connection, binding, records, receipts, authority, row, version,
            )
            reader = None
            try:
                if self.check_local_authority is None:
                    guard()  # Preserve the legacy scope's entry callback.
                reader = EvidenceOperationReads(
                    source, connection, deployment, binding,
                    (*previous, *zip(finalized, bodies, strict=True)), derive=self._derive,
                )
                result: Any
                if receipt is not None:
                    result = self.store._settle_model_checkpoint_locked(
                        connection, binding, receipt, fence=fence, row=row,
                        version=version, artifacts=reader,
                    )
                    sequence = result[0]
                else:
                    assert request is not None
                    result = self.store._commit_locked(
                        connection, binding, request, fence=fence, row=row,
                        version=version, artifacts=reader,
                    )
                    sequence = result.event_watermark
                facts = self._settlement_facts(connection, binding, sequence, receipt, request)
                guard()
                if self.check_local_authority is None:
                    guard()  # Preserve the legacy scope's extensible exit callback.
                # Extensible exit callbacks may write on the borrowed connection.
                # Revalidate originals AND settlement, never return a stale acknowledgement.
                self._qualify(binding)
                validate_write(connection, deployment, binding, fence)
                reader.revalidate()
                self.publisher._revalidate_finalized(connection, binding, finalized)
                if facts != self._settlement_facts(connection, binding, sequence, receipt, request):
                    raise ValueError("evidence settlement changed during final callback")
                if any(check.kind == "model" for check in binding.contract.checks):
                    state = indexed_state(connection, deployment, binding)
                    self.store._model_clock(connection, binding, fence, state.policy)
                    reader.finish_retention(state.policy.deadline)
            finally:
                if reader is not None:
                    reader.close()
        # Only the transaction owner knows the actual physically verified version.
        # Seed bytes after its commit; future reads still obtain fresh full metadata.
        self.check_authority()  # A late Host revocation refuses ack of committed private evidence.
        self._qualify(binding)
        for record, (identifier, payload) in zip(finalized, payloads, strict=True):
            source._remember_publication(record, identifier, payload)
        return result


_STORE_METHODS = {name: getattr(PostgresCoverageStore, name) for name in (
    "commit", "_commit_locked", "record_model_usage", "settle_model_checkpoint",
    "_settle_model_checkpoint", "_settle_model_checkpoint_locked", "_model_clock",
)}
_PUBLISHER_METHODS = {name: getattr(PostgresCoverageArtifactPublisher, name) for name in (
    "publish", "publish_batch", "_prepare_publication", "_upload_verified", "_finalize_locked",
    "_record_receipts", "_revalidate_finalized",
)}
_READ_SELECTOR = acceptance_evidence_ids
_READ_OWNER = EvidenceOperationReads
_READ_METHODS = {name: getattr(EvidenceOperationReads, name) for name in (
    "__init__", "_boundary", "_native_payload_row", "_native_materialized_sources",
    "_locked_proof_scope",
    "_prefetch_proof", "_execution_receipt_verifier", "get_payload",
    "read_payload_bytes_bounded", "read_payload_verified_bounded", "revalidate",
    "finish_retention", "close",
)}
_AUTHORITY_METHODS = {name: getattr(PostgresCoverageAuthority, name) for name in (
    "check", "observe", "_read_lineage", "_validate_lineage",
)}


def _cells(callback: Any) -> dict[str, Any]:
    if type(callback) is not FunctionType:
        return {}
    try:
        return dict(zip(callback.__code__.co_freevars,
                        (cell.cell_contents for cell in callback.__closure__ or ()), strict=True))
    except ValueError:
        return {}
