"""Explicit Event-backed coverage storage; does not certify external Host authority.

Frozen persisted Host scope and expiry are checked. Live external grant revocation
requires the successor Host authority adapter; this store activates no runtime.
"""

from typing import Any

from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_validation import CoverageUnitKey, expected_units
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.leases import LeaseFence
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort
from agent_core.ports.coverage import CoverageCommit, CoverageCommitReceipt

from agent_storage.postgres.coverage_artifacts import read_manifest, verify_results
from agent_storage.postgres.coverage_projection import (
    accept_units,
    project_batch,
    project_watermark,
    receipt_from_event,
    replay_request,
    seed_run,
)
from agent_storage.postgres.coverage_transactions import (
    append_coverage_event,
    assert_projection,
    binding_from_event,
    lock_run,
    manifest_event,
    request_digest,
    run_events,
    validate_event_fence,
    validate_request,
    validate_write,
)
from agent_storage.postgres.database import PostgresDatabase


class PostgresCoverageStore:
    def __init__(
        self, dsn: str, *, deployment_namespace: str, artifacts: ArtifactPayloadStorePort,
    ) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)
        self._deployment = deployment_namespace
        self._artifacts = artifacts

    def _binding(self, namespace: str, run_id: str) -> CoverageRunBinding:
        with self._database.connect() as connection:
            row = manifest_event(connection, self._deployment, namespace, run_id)
        if row is None:
            raise ValueError("coverage run was not found in this namespace")
        return binding_from_event(row, namespace, run_id)

    def bind(self, binding: CoverageRunBinding, *, fence: LeaseFence) -> int:
        binding = CoverageRunBinding.model_validate(binding.model_dump(mode="json"))
        records = read_manifest(self._artifacts, binding)
        with self._database.connect() as connection:
            row, version = lock_run(connection, self._deployment, binding, fence)
            source = manifest_event(connection, self._deployment, binding.namespace, binding.run_id)
            if source is not None:
                assert_projection(connection, self._deployment, binding, row)
                if row["cancelled"]:
                    raise ValueError("coverage run is cancelled")
                validate_write(connection, self._deployment, binding, fence)
                return int(source["sequence"])
            if row is not None:
                raise ValueError("coverage index has no authoritative manifest Event")
            count = sum(len(expected_units(binding.contract, (record,))) for record in records)
            event = append_coverage_event(
                connection, self._deployment, binding, fence, version + 1,
                EventType.COVERAGE_MANIFEST_COMMITTED,
                {"binding": binding.model_dump(mode="json"), "expected_count": count},
            )
            seed_run(connection, self._deployment, binding, records, event.sequence)
            validate_write(connection, self._deployment, binding, fence)
            return event.sequence

    def commit(self, request: CoverageCommit, *, fence: LeaseFence) -> CoverageCommitReceipt:
        request = CoverageCommit.model_validate(request.model_dump(mode="json"))
        binding = self._binding(request.namespace, request.run_id)
        validate_request(binding, request)
        verify_results(self._artifacts, request)
        digest = request_digest(request)
        with self._database.connect() as connection:
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
            if previous:
                event = SessionEvent.model_validate(previous[0])
                if (
                    len(previous) != 1 or event.session_id != binding.session_id
                    or event.payload["request_digest"] != digest
                    or event.payload["request"] != request.model_dump(
                        mode="json", exclude={"results"},
                    )
                    or event.payload["result_count"] != len(request.results)
                ):
                    raise ValueError("coverage commit key reused with a different request")
                validate_write(connection, self._deployment, binding, fence)
                return receipt_from_event(event)
            accept_units(connection, self._deployment, request)
            event = append_coverage_event(
                connection, self._deployment, binding, fence, version + 1,
                EventType.COVERAGE_BATCH_ACCEPTED,
                {"request": request.model_dump(mode="json", exclude={"results"}),
                 "request_digest": digest, "result_count": len(request.results)},
            )
            receipt = project_batch(connection, self._deployment, binding, request, event)
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
                connection, self._deployment, binding, fence, version + 1,
                EventType.COVERAGE_RUN_CANCELLED,
                {"binding_digest": coverage_digest(binding.model_dump(mode="json"))},
            )
            project_watermark(connection, self._deployment, binding, event.sequence, cancelled=True)
            validate_write(connection, self._deployment, binding, fence, cancelling=True)
            return event.sequence

    def rebuild(self, namespace: str, run_id: str) -> int:
        """Replay one run without Event/wakeup side effects, even after snapshot expiry."""
        # ponytail: O(run Event history) administrative replay. For very long runs,
        # stream descriptors under the same locks; each Artifact is capped at 32 MiB.
        with self._database.connect() as connection:
            rows = run_events(connection, self._deployment, namespace, run_id)
        if not rows or rows[0]["event_type"] != EventType.COVERAGE_MANIFEST_COMMITTED.value:
            raise ValueError("coverage source manifest is missing")
        binding = binding_from_event(rows[0], namespace, run_id)
        records = read_manifest(self._artifacts, binding)
        events = tuple(SessionEvent.model_validate(row) for row in rows)
        requests = {}
        cancelled = False
        for event in events[1:]:
            validate_event_fence(event.payload)
            if event.session_id != binding.session_id or cancelled:
                raise ValueError("coverage Event order or Session binding conflicts")
            if event.event_type == EventType.COVERAGE_BATCH_ACCEPTED:
                requests[event.event_id] = replay_request(self._artifacts, binding, event)
            elif event.event_type == EventType.COVERAGE_RUN_CANCELLED:
                if event.payload["binding_digest"] != coverage_digest(
                    binding.model_dump(mode="json"),
                ):
                    raise ValueError("coverage cancellation binding conflicts")
                cancelled = True
            else:
                raise ValueError("coverage source has more than one manifest")
        with self._database.connect() as connection:
            lock_run(connection, self._deployment, binding, None)
            current = run_events(connection, self._deployment, namespace, run_id)
            if current != rows:
                raise ValueError("coverage Events changed during rebuild; retry required")
            connection.execute(
                """DELETE FROM coverage_runs WHERE deployment_namespace=%s
                   AND namespace=%s AND run_id=%s""", (self._deployment, namespace, run_id),
            )
            count = seed_run(connection, self._deployment, binding, records, events[0].sequence)
            if events[0].payload["expected_count"] != count:
                raise ValueError("coverage manifest Event count conflicts")
            for event in events[1:]:
                if event.event_type == EventType.COVERAGE_BATCH_ACCEPTED:
                    request = requests[event.event_id]
                    accept_units(connection, self._deployment, request)
                    project_batch(connection, self._deployment, binding, request, event)
                else:
                    project_watermark(
                        connection, self._deployment, binding, event.sequence, cancelled=True,
                    )
            return events[-1].sequence

    def missing_units(
        self, namespace: str, run_id: str, *, limit: int = 100, after_ordinal: int = -1,
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
        if connection.execute(
            """SELECT 1 FROM coverage_runs WHERE deployment_namespace=%s
               AND namespace=%s AND run_id=%s""", (self._deployment, namespace, run_id),
        ).fetchone() is None:
            raise ValueError("coverage run was not found in this namespace")
