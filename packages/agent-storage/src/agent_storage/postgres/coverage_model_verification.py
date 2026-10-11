"""Private, invocation-local proof transcript; never reused across locked phases."""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from agent_core.application.coverage_semantic import semantic_check
from agent_core.domain.coverage_model_budget import (
    CoverageModelBudgetState,
    CoverageModelPolicy,
    CoverageModelUsageReceipt,
)
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_validation import (
    AcceptedCoverageUnit,
    CoverageUnitKey,
    expected_units,
)
from agent_core.domain.events import SessionEvent
from agent_core.ports.artifact_payload_store import BoundedArtifactPayloadReaderPort
from agent_core.ports.coverage import CoverageCommit

from agent_storage.postgres.coverage_artifacts import MAX_COVERAGE_ARTIFACT_BYTES, read_manifest
from agent_storage.postgres.coverage_model_checkpoint import _CheckpointBodies
from agent_storage.postgres.coverage_model_source import replay_model, task_policy
from agent_storage.postgres.coverage_projection import replay_request

if TYPE_CHECKING:
    from agent_storage.postgres.coverage_model_acceptance import ModelObservationDeriver


class _ModelVerification:
    def __init__(
        self,
        connection: Any,
        deployment: str,
        binding: CoverageRunBinding,
        *,
        artifacts: Any,
        derive: "ModelObservationDeriver | None",
        rebuild: bool = False,
        _recovery: bool = False,
        _commit_results: tuple[AcceptedCoverageUnit, ...] | None = None,
        _membership_qualified: bool = False,
    ) -> None:
        from agent_storage.postgres.coverage_model_acceptance import pin_evidence

        self.connection, self.deployment, self.binding = connection, deployment, binding
        if isinstance(artifacts, BoundedArtifactPayloadReaderPort):
            artifacts = _CheckpointBodies(artifacts)
        self.artifacts, self.derive = artifacts, derive
        self.deadlines: list[datetime] = []
        self.policy = (
            task_policy(connection, deployment, binding, incremental=True)
            if _commit_results is not None and not rebuild and not _recovery
            else task_policy(connection, deployment, binding)
        )
        self.state: CoverageModelBudgetState | None = None
        self.calls: dict[str, Any] = {}
        self.settled: dict[CoverageUnitKey, Any] = {}
        self._batches: tuple[tuple[int, CoverageCommit, int], ...] | None = None
        self.part_sources: dict[
            str, dict[CoverageUnitKey, list[tuple[int, AcceptedCoverageUnit]]]
        ] = {}
        self.batch_bytes = 0
        self._batch_record_ids: list[str] | None = None
        self.membership: Any = None
        if self.policy is None:
            if any(check.kind == "model" for check in binding.contract.checks):
                replay_model(
                    connection,
                    deployment,
                    binding,
                    artifacts=artifacts,
                    retention_deadlines=self.deadlines,
                    rebuild=rebuild,
                    _policy=self.policy,
                )
            if _recovery:
                raise ValueError("strict MODEL recovery has no admitted policy")
            return
        if not callable(derive):
            raise ValueError("strict MODEL acceptance requires a configured observation verifier")
        self.definition = semantic_check(self.policy.model_profile)
        if binding.contract.checks != (self.definition.contract_check,):
            raise ValueError("strict MODEL frozen check conflicts")
        self.spent = pin_evidence(
            connection,
            deployment,
            binding,
            artifacts,
            binding.snapshot.manifest_artifact_ref,
            binding.manifest_artifact_digest,
            self.deadlines,
        )
        if self.spent > MAX_COVERAGE_ARTIFACT_BYTES:
            raise ValueError("strict MODEL evidence exceeds cumulative read bound")
        if (_commit_results is not None and not rebuild and not _recovery
                and self.policy.validation_mode == "final_certification"
                and _membership_qualified):
            from agent_storage.postgres.coverage_membership import membership_state

            self.membership = membership_state(connection, deployment, binding)
        if self.membership is not None:
            from agent_storage.postgres.coverage_membership import membership_records

            assert _commit_results is not None
            self.records = membership_records(
                connection, deployment, binding, {item.key.record_id for item in _commit_results},
            )
        else:
            self.records = read_manifest(artifacts, binding)
        self.indexed = {record.record_id: record for record in self.records}
        if len(self.indexed) != len(self.records):
            raise ValueError("strict MODEL duplicate record/result identity")
        self.expected = set(expected_units(binding.contract, self.records))
        incremental_keys = None
        if _commit_results is not None and self.policy.validation_mode == "final_certification":
            if rebuild or _recovery:
                raise ValueError("incremental acceptance cannot replace recovery or rebuild")
            record_ids = {item.key.record_id for item in _commit_results}
            self._batch_record_ids = sorted(record_ids)
            incremental_keys = {key for key in self.expected if key.record_id in record_ids}
        self.state, self.calls = replay_model(
            connection,
            deployment,
            binding,
            artifacts=artifacts,
            source_keys=self.expected,
            retention_deadlines=self.deadlines,
            rebuild=rebuild,
            _incremental_keys=incremental_keys,
            _policy=self.policy,
        )
        if self.state is None:
            if not _recovery:
                raise ValueError("strict MODEL acceptance has no initialized receipt proof")
            return
        for call in self.calls.values():
            if call["receipt"] is None:
                continue
            receipt = CoverageModelUsageReceipt.model_validate(call["receipt"])
            if receipt.reservation.key in self.settled:
                raise ValueError("strict MODEL part has duplicate settled receipts")
            self.settled[receipt.reservation.key] = (call, receipt)

    def batches(self) -> tuple[tuple[int, CoverageCommit, int], ...]:
        from agent_core.application.coverage_executor import observation_id

        from agent_storage.postgres.coverage_model_acceptance import pin_evidence
        from agent_storage.postgres.coverage_proof_prefetch import prefetch_proof

        if self._batches is not None:
            return self._batches
        rows: list[tuple[int, CoverageCommit, int]] = []
        seen: set[CoverageUnitKey] = set()
        cursor = -1
        # Routing hints are not proof: replay_request validates selected canonical
        # bytes; final certification/recovery always replay every batch. Old events
        # have no hints and retain full reads. No cross-operation proof cache.
        selection = ""
        if self._batch_record_ids is not None:
            selection = """AND (NOT payload ? 'record_ids'
                OR jsonb_typeof(payload->'record_ids') IS DISTINCT FROM 'array'
                OR (payload->'record_ids') ?| %s)"""
        while True:
            sources = self.connection.execute(
                f"""SELECT * FROM session_events WHERE deployment_namespace=%s AND session_id=%s
                   AND event_type='coverage_batch_accepted' AND payload->>'namespace'=%s
                   AND payload->>'run_id'=%s {selection}
                   AND sequence>%s ORDER BY sequence LIMIT 100""",
                (
                    self.deployment,
                    self.binding.session_id,
                    self.binding.namespace,
                    self.binding.run_id,
                    *((self._batch_record_ids,) if selection else ()),
                    cursor,
                ),
            ).fetchall()
            if not sources:
                break
            prefetch_proof(self.artifacts, tuple(
                source["payload"]["request"]["result_artifact_ref"] for source in sources
            ))
            for source in sources:
                size = 0
                if self.policy is not None:
                    descriptor = source["payload"]["request"]
                    size = pin_evidence(
                        self.connection,
                        self.deployment,
                        self.binding,
                        self.artifacts,
                        descriptor["result_artifact_ref"],
                        descriptor["result_artifact_digest"],
                        self.deadlines,
                    )
                    self.batch_bytes += size
                    if self.spent + self.batch_bytes > MAX_COVERAGE_ARTIFACT_BYTES:
                        raise ValueError("strict MODEL evidence exceeds cumulative read bound")
                batch = replay_request(
                    self.artifacts, self.binding, SessionEvent.model_validate(source)
                )
                prefetch_proof(self.artifacts, tuple(
                    f"artifact://{observation_id(self.binding, item.key)}"
                    for item in batch.results if self._batch_record_ids is None
                    or item.key.record_id in self._batch_record_ids
                ))
                for item in batch.results:
                    if item.key in seen:
                        raise ValueError("accepted coverage has duplicate source Artifacts")
                    seen.add(item.key)
                if len(seen) > 200000 or len(rows) >= 200000:
                    raise ValueError("coverage accepted sources exceed validation bound")
                rows.append((source["sequence"], batch, size))
                for item in batch.results:
                    if item.key.kind == "part":
                        parts = self.part_sources.setdefault(item.key.record_id, {})
                        parts.setdefault(item.key, []).append((source["sequence"], item))
                cursor = source["sequence"]
            # Callers hold the run lock or a RR snapshot: a short page is exhaustive.
            if len(sources) < 100:
                break
        self._batches = tuple(rows)
        return self._batches

    def merge_deadlines(self, deadlines: list[datetime]) -> None:
        if self.deadlines:
            deadlines[:] = [min((*deadlines, *self.deadlines))]

    def verify(
        self,
        results: tuple[AcceptedCoverageUnit, ...],
        *,
        deadlines: list[datetime],
        request: CoverageCommit | None = None,
        before_sequence: int | None = None,
    ) -> CoverageModelPolicy | None:
        from agent_storage.postgres.coverage_model_acceptance import _verify_model_results

        if self.policy is not None and self.state is None:
            raise ValueError("strict MODEL acceptance has no initialized receipt proof")
        return _verify_model_results(
            self,
            results,
            deadlines=deadlines,
            request=request,
            before_sequence=before_sequence,
        )
