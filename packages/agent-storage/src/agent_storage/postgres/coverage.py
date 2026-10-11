"""Explicit Event-backed coverage storage; does not certify external Host authority.

Frozen persisted Host scope and expiry are checked. Live external grant revocation
requires the successor Host authority adapter; this store activates no runtime.
"""

from datetime import datetime
from pickle import dump, load
from tempfile import TemporaryFile
from typing import Any

from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_task_admission import coverage_admission_input
from agent_core.domain.coverage_validation import CoverageUnitKey, expected_units
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.leases import LeaseFence
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort
from agent_core.ports.coverage import CoverageCommit, CoverageCommitReceipt

from agent_storage.postgres.coverage_artifacts import read_manifest, verify_results
from agent_storage.postgres.coverage_execution import CoverageExecutionQueries
from agent_storage.postgres.coverage_execution_receipts import (
    VerifiedCommitFacts,
    mint_execution_receipt,
)
from agent_storage.postgres.coverage_model_acceptance import (
    ModelObservationDeriver,
    verify_model_results,
)
from agent_storage.postgres.coverage_model_budget import CoverageModelBudgetQueries
from agent_storage.postgres.coverage_model_checkpoint import check_checkpoint_retention
from agent_storage.postgres.coverage_model_source import MODEL_TYPES
from agent_storage.postgres.coverage_model_verification import _ModelVerification
from agent_storage.postgres.coverage_projection import (
    accept_units,
    project_batch,
    project_watermark,
    receipt_from_event,
    replay_request,
    seed_run,
)
from agent_storage.postgres.coverage_publication import CoveragePublicationQueries
from agent_storage.postgres.coverage_transactions import (
    append_coverage_event,
    assert_not_certified,
    assert_projection,
    binding_from_event,
    iter_run_events,
    lock_run,
    manifest_event,
    request_digest,
    validate_event_fence,
    validate_request,
    validate_write,
    validated_binding,
)
from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.work_unit import postgres_work_unit


class PostgresCoverageStore(
    CoverageExecutionQueries, CoveragePublicationQueries, CoverageModelBudgetQueries
):
    def __init__(
        self,
        dsn: str,
        *,
        deployment_namespace: str,
        artifacts: ArtifactPayloadStorePort,
        supported_model_profiles: tuple[str, ...] = (),
        model_observation_deriver: ModelObservationDeriver | None = None,
        execution_receipts: bool = False,
        execution_receipt_verifier: str | None = None,
    ) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._deployment = deployment_namespace
        self._artifacts = artifacts
        self._supported_model_profiles = frozenset(supported_model_profiles)
        self._model_observation_deriver = model_observation_deriver
        # Dormant until native protocol/capability qualification is composed.
        self._execution_receipts = execution_receipts
        self._execution_receipt_verifier = execution_receipt_verifier

    def _binding(self, namespace: str, run_id: str) -> CoverageRunBinding:
        with self._database.connect() as connection:
            row = manifest_event(connection, self._deployment, namespace, run_id)
        if row is None:
            raise ValueError("coverage run was not found in this namespace")
        return binding_from_event(row, namespace, run_id)

    def bind(
        self,
        binding: CoverageRunBinding,
        *,
        fence: LeaseFence,
        expected_stream_revision: int | None = None,
        task_binding_digest: str | None = None,
    ) -> int:
        binding = validated_binding(binding)
        records = read_manifest(self._artifacts, binding)
        with self._database.connect() as connection:
            row, version = lock_run(
                connection,
                self._deployment,
                binding,
                fence,
                expected_stream_revision=expected_stream_revision,
                task_binding_digest=task_binding_digest,
            )
            source = manifest_event(connection, self._deployment, binding.namespace, binding.run_id)
            if source is not None:
                assert_projection(connection, self._deployment, binding, row)
                if row["cancelled"]:
                    raise ValueError("coverage run is cancelled")
                validate_write(connection, self._deployment, binding, fence)
                return int(source["sequence"])
            if row is not None:
                raise ValueError("coverage index has no authoritative manifest Event")
            from agent_storage.postgres.coverage_membership import membership_descriptor

            membership = (
                {"membership": membership_descriptor(binding, records)}
                if any(check.kind == "model" for check in binding.contract.checks) else {}
            )
            count = (membership["membership"]["expected_count"] if membership else
                     len(expected_units(binding.contract, records)))
            event = append_coverage_event(
                connection,
                self._deployment,
                binding,
                fence,
                version + 1,
                EventType.COVERAGE_MANIFEST_COMMITTED,
                {"binding": binding.model_dump(mode="json"), "expected_count": count,
                 **membership},
            )
            seed_run(connection, self._deployment, binding, records, event.sequence)
            validate_write(connection, self._deployment, binding, fence)
            return event.sequence

    def commit(self, request: CoverageCommit, *, fence: LeaseFence) -> CoverageCommitReceipt:
        request = CoverageCommit.model_validate(coverage_admission_input(request), strict=True)
        binding = self._binding(request.namespace, request.run_id)
        validate_request(binding, request)
        verify_results(self._artifacts, request)
        digest = request_digest(request)
        with postgres_work_unit(self._database), self._database.connect() as connection:
            row, version = lock_run(connection, self._deployment, binding, fence)
            assert_projection(connection, self._deployment, binding, row)
            if row["cancelled"]:
                raise ValueError("coverage run is cancelled")
            previous = connection.execute(
                """SELECT * FROM session_events WHERE deployment_namespace=%s
                   AND payload->>'namespace'=%s AND payload->>'run_id'=%s
                   AND event_type='coverage_batch_accepted'
                   AND payload #>> '{request,commit_key}'=%s LIMIT 2""",
                (self._deployment, request.namespace, request.run_id, request.commit_key),
            ).fetchall()
            event = SessionEvent.model_validate(previous[0]) if previous else None
            # Reject conflicting retries before model/history/object proof. A matching
            # retry still passes the complete required proof and current write fences.
            if event is not None and (
                len(previous) != 1
                or event.session_id != binding.session_id
                or event.payload["request_digest"] != digest
                or event.payload["request"] != request.model_dump(mode="json", exclude={"results"})
                or event.payload["result_count"] != len(request.results)
                or ("record_ids" in event.payload and event.payload["record_ids"]
                    != sorted({item.key.record_id for item in request.results}))
            ):
                raise ValueError("coverage commit key reused with a different request")
            deadlines: list[datetime] = []
            verified_commits: list[VerifiedCommitFacts] = []
            policy = verify_model_results(
                connection,
                self._deployment,
                binding,
                request.results,
                artifacts=self._artifacts,
                derive=self._model_observation_deriver,
                deadlines=deadlines,
                request=request,
                before_sequence=previous[0]["sequence"] if previous else version + 1,
                incremental_commit=True,
                verified_commits=verified_commits if self._execution_receipts else None,
            )
            if event is not None:
                validate_write(connection, self._deployment, binding, fence)
                check_checkpoint_retention(connection, deadlines)
                return receipt_from_event(event)
            assert_not_certified(connection, self._deployment, binding)
            accept_units(connection, self._deployment, request)
            event = append_coverage_event(
                connection,
                self._deployment,
                binding,
                fence,
                version + 1,
                EventType.COVERAGE_BATCH_ACCEPTED,
                {
                    "request": request.model_dump(mode="json", exclude={"results"}),
                    "request_digest": digest,
                    "result_count": len(request.results),
                    "record_ids": sorted({item.key.record_id for item in request.results}),
                },
            )
            receipt = project_batch(connection, self._deployment, binding, request, event)
            validate_write(connection, self._deployment, binding, fence)
            now = check_checkpoint_retention(connection, deadlines)
            if policy is not None and not policy.started_at <= now < policy.deadline:
                raise ValueError("first MODEL acceptance exceeded original execution deadline")
            if verified_commits:
                assert policy is not None
                mint_execution_receipt(
                    connection, self._deployment, binding, event, verified_commits[0],
                    valid_until=min(policy.deadline, binding.snapshot.expires_at, *deadlines),
                    verifier_contract=self._execution_receipt_verifier,
                )
                # Mint I/O is inside the transaction; never commit a late witness.
                check_checkpoint_retention(connection, [policy.deadline, *deadlines])
                validate_write(connection, self._deployment, binding, fence)
            return receipt

    def cancel(self, namespace: str, run_id: str, *, fence: LeaseFence) -> int:
        binding = self._binding(namespace, run_id)
        with self._database.connect() as connection:
            row, version = lock_run(connection, self._deployment, binding, fence, cancelling=True)
            assert_projection(connection, self._deployment, binding, row)
            if row["cancelled"]:
                validate_write(connection, self._deployment, binding, fence, cancelling=True)
                return int(row["source_watermark"])
            event = append_coverage_event(
                connection,
                self._deployment,
                binding,
                fence,
                version + 1,
                EventType.COVERAGE_RUN_CANCELLED,
                {"binding_digest": coverage_digest(binding.model_dump(mode="json"))},
            )
            project_watermark(connection, self._deployment, binding, event.sequence, cancelled=True)
            validate_write(connection, self._deployment, binding, fence, cancelling=True)
            return event.sequence

    def rebuild(self, namespace: str, run_id: str) -> int:
        """Replay one run without Event/wakeup side effects, even after snapshot expiry."""
        # ponytail: disk-spooled exact source comparison; bounded pages, not all history.
        # Necessary manifest/transcript indexes remain O(units); certificate proof is independent.
        with TemporaryFile() as history:
            return self._rebuild_spooled(namespace, run_id, history)

    def _rebuild_spooled(self, namespace: str, run_id: str, history: Any) -> int:
        with self._database.connect() as connection:
            rows = iter_run_events(connection, self._deployment, namespace, run_id)
            first = next(rows, None)
            if first is None or first["event_type"] != EventType.COVERAGE_MANIFEST_COMMITTED.value:
                raise ValueError("coverage source manifest is missing")
            dump(first, history)
            for row in rows:
                dump(row, history)
        history.seek(0)
        first = load(history)
        if first["event_type"] != EventType.COVERAGE_MANIFEST_COMMITTED.value:
            raise ValueError("coverage source manifest is missing")
        binding = binding_from_event(first, namespace, run_id)
        records = read_manifest(self._artifacts, binding)
        cancelled = False
        certified = False
        accepted_batches = False
        history.seek(0)
        load(history)
        while True:
            try:
                event = SessionEvent.model_validate(load(history))
            except EOFError:
                break
            validate_event_fence(event.payload)
            if event.session_id != binding.session_id or cancelled:
                raise ValueError("coverage Event order or Session binding conflicts")
            if event.event_type == EventType.COVERAGE_BATCH_ACCEPTED:
                accepted_batches = True
                if certified:
                    raise ValueError("coverage changed after certification")
                replay_request(self._artifacts, binding, event)
            elif event.event_type == EventType.COVERAGE_REPORT_CERTIFIED:
                if certified:
                    raise ValueError("coverage has duplicate certificates")
                certified = True
            elif event.event_type == EventType.COVERAGE_RUN_CANCELLED:
                if event.payload["binding_digest"] != coverage_digest(
                    binding.model_dump(mode="json"),
                ):
                    raise ValueError("coverage cancellation binding conflicts")
                cancelled = True
            elif event.event_type in MODEL_TYPES:
                if certified:
                    raise ValueError("model budget changed after certification")
            else:
                raise ValueError("coverage source has more than one manifest")
        with self._database.connect() as connection:
            lock_run(connection, self._deployment, binding, None)
            deadlines: list[datetime] = []
            self._assert_rebuild_source(connection, namespace, run_id, history)
            transcript = None
            if accepted_batches or certified:
                transcript = _ModelVerification(
                    connection,
                    self._deployment,
                    binding,
                    artifacts=self._artifacts,
                    derive=self._model_observation_deriver,
                    rebuild=True,
                )
                transcript.verify((), deadlines=deadlines)
            else:
                from agent_core.domain.coverage_validation import expected_units

                from agent_storage.postgres.coverage_model_source import replay_model

                # ponytail: no accepted results need semantic proof; budget replay
                # still verifies every original checkpoint and retains its deadline.
                replay_model(
                    connection,
                    self._deployment,
                    binding,
                    artifacts=self._artifacts,
                    source_keys=set(expected_units(binding.contract, records)),
                    retention_deadlines=deadlines,
                    rebuild=True,
                )
            connection.execute(
                """DELETE FROM coverage_runs WHERE deployment_namespace=%s
                   AND namespace=%s AND run_id=%s""",
                (self._deployment, namespace, run_id),
            )
            initial = SessionEvent.model_validate(first)
            count = seed_run(connection, self._deployment, binding, records, initial.sequence)
            if initial.payload["expected_count"] != count:
                raise ValueError("coverage manifest Event count conflicts")
            history.seek(0)
            load(history)
            last_sequence = initial.sequence
            while True:
                try:
                    event = SessionEvent.model_validate(load(history))
                except EOFError:
                    break
                last_sequence = event.sequence
                if event.event_type == EventType.COVERAGE_BATCH_ACCEPTED:
                    assert transcript is not None
                    request = replay_request(self._artifacts, binding, event)
                    transcript.verify(
                        request.results,
                        deadlines=deadlines,
                        request=request,
                        before_sequence=event.sequence,
                    )
                    accept_units(connection, self._deployment, request)
                    project_batch(connection, self._deployment, binding, request, event)
                elif event.event_type == EventType.COVERAGE_RUN_CANCELLED:
                    project_watermark(
                        connection,
                        self._deployment,
                        binding,
                        event.sequence,
                        cancelled=True,
                    )
                elif event.event_type in MODEL_TYPES:
                    project_watermark(
                        connection, self._deployment, binding, event.sequence, cancelled=False
                    )
                else:
                    self._replay_certificate(
                        connection, binding, event, retention_deadlines=deadlines
                    )
            self._rebuild_budget(connection, binding)
            self._assert_rebuild_source(connection, namespace, run_id, history)
            check_checkpoint_retention(connection, deadlines)
            return last_sequence

    def _assert_rebuild_source(
        self, connection: Any, namespace: str, run_id: str, history: Any
    ) -> None:
        history.seek(0)
        for current in iter_run_events(
            connection, self._deployment, namespace, run_id, locked=True
        ):
            try:
                original = load(history)
            except EOFError:
                raise ValueError("coverage Events changed during rebuild; retry required") from None
            if current != original:
                raise ValueError("coverage Events changed during rebuild; retry required")
        if history.read(1):
            raise ValueError("coverage Events changed during rebuild; retry required")

    def missing_units(
        self,
        namespace: str,
        run_id: str,
        *,
        limit: int = 100,
        after_ordinal: int = -1,
    ) -> tuple[tuple[int, CoverageUnitKey], ...]:
        """Resume after the last returned ordinal, including across accepted gaps.

        Ordinals enumerate records by ordinal, then existing expected_units order.
        This is keyset paging; concurrent acceptance only removes missing keys.
        """
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("coverage missing-unit limit must be between 1 and 1000")
        if type(after_ordinal) is not int or after_ordinal < -1:
            raise ValueError("coverage ordinal cursor must be >= -1")
        with self._database.connect() as connection:
            self._require_run(connection, namespace, run_id)
            rows = connection.execute(
                """SELECT ordinal,unit_key FROM coverage_units WHERE deployment_namespace=%s
                   AND namespace=%s AND run_id=%s AND result IS NULL AND ordinal>%s
                   ORDER BY ordinal LIMIT %s""",
                (self._deployment, namespace, run_id, after_ordinal, limit),
            ).fetchall()
            return tuple(
                (int(row["ordinal"]), CoverageUnitKey.model_validate(row["unit_key"]))
                for row in rows
            )

    def counts(self, namespace: str, run_id: str) -> tuple[int, int]:
        with self._database.connect() as connection:
            self._require_run(connection, namespace, run_id)
            row = connection.execute(
                """SELECT count(*) AS expected, count(result) AS accepted FROM coverage_units
                   WHERE deployment_namespace=%s AND namespace=%s AND run_id=%s""",
                (self._deployment, namespace, run_id),
            ).fetchone()
            assert row is not None
            return int(row["expected"]), int(row["accepted"])

    def _require_run(self, connection: Any, namespace: str, run_id: str) -> None:
        if (
            connection.execute(
                """SELECT 1 FROM coverage_runs WHERE deployment_namespace=%s
               AND namespace=%s AND run_id=%s""",
                (self._deployment, namespace, run_id),
            ).fetchone()
            is None
        ):
            raise ValueError("coverage run was not found in this namespace")
